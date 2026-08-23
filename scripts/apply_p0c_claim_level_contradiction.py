"""Guarded local applicator for P0-C claim-level contradiction grounding.

Run only on branch `chatgpt-p0c-claim-level-contradiction-20260823`.
All transforms are prepared and validated in memory before any file is written.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "chatgpt-p0c-claim-level-contradiction-20260823"
CLAIM = ROOT / "research_engine" / "claim_verification.py"
QUALITY = ROOT / "research_engine" / "quality_producers.py"
FINAL = ROOT / "research_engine" / "final_quality_gate.py"
STATUS = ROOT / "WORK_STATUS.md"

THRESHOLDS = {
    "_ENTAIL_SIM": "0.30",
    "_ENTAIL_SIM_WITH_NUM": "0.12",
    "_MIN_TEXT_CHARS": "120",
    "_MIN_RELEVANCE": "0.25",
    "_MIN_QUALITY": "0.35",
    "_LOW_QUALITY": "0.20",
}


def die(message: str) -> None:
    raise SystemExit(f"STOP: {message}")


def branch_name() -> str:
    proc = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        die("git branch check failed")
    return proc.stdout.strip()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        die(f"{label}: expected exactly 1 anchor, found {count}")
    return text.replace(old, new, 1)


def threshold_snapshot(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in THRESHOLDS:
        match = re.search(rf"^{re.escape(name)}\s*=\s*([^\s#]+)", text, re.MULTILINE)
        if not match:
            die(f"threshold {name} not found")
        out[name] = match.group(1)
    return out


def patch_claim(text: str) -> str:
    before_thresholds = threshold_snapshot(text)
    if before_thresholds != THRESHOLDS:
        die(f"unexpected threshold baseline: {before_thresholds}")
    if "contradiction_span: Dict = field(default_factory=dict)" in text:
        die("claim_verification.py already appears P0-C patched")

    text = replace_once(
        text,
        '    supporting_source_id: str = ""\n',
        '    supporting_source_id: str = ""\n'
        '    # P0-C: exact span/locator that alone triggered contradiction.\n'
        '    contradiction_span: Dict = field(default_factory=dict)\n',
        "ClaimCheck contradiction span field",
    )

    text = replace_once(
        text,
        '                "contradicted": bool(self.contradicted),\n'
        '                "evidence_spans": [dict(s) for s in self.spans],\n',
        '                "contradicted": bool(self.contradicted),\n'
        '                "contradiction_span": (dict(self.contradiction_span)\n'
        '                                       if self.contradiction_span else {}),\n'
        '                "verified_support": bool(self.passes_ae and not self.contradicted),\n'
        '                "evidence_spans": [dict(s) for s in self.spans],\n',
        "ClaimCheck serialization",
    )

    start = text.find("def claim_contradicted(line: str, records: Sequence[SourceRecord],")
    end_marker = "\n\n# ── ek claim = A..E + ek verdict"
    end = text.find(end_marker, start)
    if start < 0 or end < 0:
        die("claim_contradicted function boundary not found")
    old_block = text[start:end]
    if "text = source_text(record, pack)" not in old_block:
        die("claim_contradicted source-wide baseline guard failed")

    new_block = '''def claim_contradiction_from_spans(
        line: str, spans: Sequence[Dict]) -> Tuple[bool, str, Dict]:
    """Detect contradiction only on an explicit claim-level evidence span.

    P0-C intentionally refuses source-wide concatenation.  A distant paragraph
    cannot contradict a claim unless that paragraph itself is the selected,
    sufficiently similar span whose stance is opposite to the claim.
    """
    body = claim_body(line)
    if len(body) < 20 or not spans:
        return False, "", {}
    try:
        from .contradiction import ContradictionEngine
        engine = ContradictionEngine()
    except Exception:                       # pragma: no cover - defensive
        return False, "", {}
    claim_stance, _ = engine.stance(body)
    if claim_stance not in ("SUPPORT", "OPPOSE"):
        return False, "", {}

    for raw_span in spans:
        span = dict(raw_span or {})
        text = str(span.get("passage") or "").strip()
        if len(text) < _MIN_TEXT_CHARS:
            continue
        match = float(_similarity(body, text))
        # Keep the pre-existing contradiction similarity floor unchanged.
        if match < _ENTAIL_SIM:
            continue
        source_stance, cues = engine.stance(text)
        if source_stance in ("SUPPORT", "OPPOSE") and source_stance != claim_stance:
            audit = dict(span)
            audit["claim_stance"] = claim_stance
            audit["source_stance"] = source_stance
            audit["stance_cues"] = list(cues[:3])
            audit["claim_match"] = round(match, 4)
            sid = str(audit.get("source_id") or "?")
            locator = str(audit.get("locator") or "").strip()
            where = f" ({locator})" if locator else ""
            cue = ", ".join(cues[:3])
            reason = (f"{sid} ke exact claim-level evidence span{where} ka stance "
                      f"is claim ke ulta hai (claim={claim_stance}, "
                      f"source={source_stance}"
                      + (f"; ishaara: {cue}" if cue else "") + ")")
            return True, reason, audit
    return False, "", {}


def claim_contradicted(line: str, records: Sequence[SourceRecord],
                       pack: Optional[EvidencePack] = None) -> Tuple[bool, str]:
    """Backward-compatible wrapper, now exact-span grounded instead of source-wide."""
    spans = evidence_spans(line, records, pack, max_spans=max(1, len(records)))
    contradicted, reason, _span = claim_contradiction_from_spans(line, spans)
    return contradicted, reason
'''
    text = text[:start] + new_block + text[end:]

    text = replace_once(
        text,
        '    cc.spans = evidence_spans(line, records, pack, max_spans=max(3, len(records)))\n'
        '    contradicted, contra_why = claim_contradicted(line, records, pack)\n'
        '    cc.contradicted = contradicted\n\n',
        '    cc.spans = evidence_spans(line, records, pack, max_spans=max(3, len(records)))\n\n',
        "remove pre-path source-wide contradiction",
    )

    text = replace_once(
        text,
        '    chosen_path, chosen_checks = max(paths, key=_rank)\n'
        '    chosen_source_id = str(chosen_path.get("source_id") or "")\n'
        '    cc.checks = chosen_checks\n'
        '    cc.canonical_span = dict(chosen_path.get("canonical_span") or {})\n'
        '    if cc.status("C") == PASS:\n'
        '        cc.best_source = chosen_source_id\n'
        '    if chosen_path.get("passes_ae"):\n'
        '        cc.supporting_source_id = chosen_source_id\n',
        '    chosen_path, chosen_checks = max(paths, key=_rank)\n'
        '    chosen_source_id = str(chosen_path.get("source_id") or "")\n'
        '    cc.checks = chosen_checks\n'
        '    cc.canonical_span = dict(chosen_path.get("canonical_span") or {})\n'
        '    contradiction_candidates = [\n'
        '        dict(path.get("canonical_span") or {})\n'
        '        for path, _checks in paths\n'
        '        if path.get("canonical_span")\n'
        '    ]\n'
        '    contradicted, contra_why, contradiction_span = claim_contradiction_from_spans(\n'
        '        line, contradiction_candidates)\n'
        '    cc.contradicted = contradicted\n'
        '    cc.contradiction_span = dict(contradiction_span or {})\n'
        '    if cc.status("C") == PASS:\n'
        '        cc.best_source = chosen_source_id\n'
        '    if chosen_path.get("passes_ae") and not cc.contradicted:\n'
        '        cc.supporting_source_id = chosen_source_id\n',
        "bind contradiction to canonical per-source spans",
    )

    text = replace_once(
        text,
        '    if contradicted:\n'
        '        cc.verdict = CITED_ONLY\n'
        '        cc.reason = contra_why\n'
        '        return cc\n',
        '    if contradicted:\n'
        '        # An unresolved exact contradiction cannot remain a supporting source.\n'
        '        cc.supporting_source_id = ""\n'
        '        cc.verdict = CITED_ONLY\n'
        '        cc.reason = contra_why\n'
        '        return cc\n',
        "contradiction clears supporting source",
    )

    text = replace_once(
        text,
        '        return len([claim for claim in self.strong_claims if claim.passes_ae])\n',
        '        return len([claim for claim in self.strong_claims\n'
        '                    if claim.passes_ae and not claim.contradicted])\n',
        "strong claim pass accounting",
    )
    text = replace_once(
        text,
        '        return len([claim for claim in self.strong_claims if not claim.passes_ae])\n',
        '        return len([claim for claim in self.strong_claims\n'
        '                    if not claim.passes_ae or claim.contradicted])\n',
        "strong claim failure accounting",
    )
    text = replace_once(
        text,
        '        return len([claim for claim in self.claims if claim.passes_ae])\n',
        '        return len([claim for claim in self.claims\n'
        '                    if claim.passes_ae and not claim.contradicted])\n',
        "same-source accepted support accounting",
    )
    text = replace_once(
        text,
        '        return len([claim for claim in self.critical_claims if claim.passes_ae])\n',
        '        return len([claim for claim in self.critical_claims\n'
        '                    if claim.passes_ae and not claim.contradicted])\n',
        "critical accepted support accounting",
    )

    old_overclaim = '        if cc.strong_label and not cc.passes_ae:\n            report.overclaims.append(cc)\n'
    if text.count(old_overclaim) != 1:
        die(f"strong overclaim anchor expected once, found {text.count(old_overclaim)}")
    text = text.replace(
        old_overclaim,
        '        if cc.strong_label and (not cc.passes_ae or cc.contradicted):\n'
        '            report.overclaims.append(cc)\n',
        1,
    )

    text = replace_once(
        text,
        '    @property\n'
        '    def unverifiable_critical(self) -> List[ClaimCheck]:\n'
        '        return [c for c in self.critical_claims\n'
        '                if c.result == CLAIM_UNVERIFIABLE]\n\n',
        '    @property\n'
        '    def unverifiable_critical(self) -> List[ClaimCheck]:\n'
        '        return [c for c in self.critical_claims\n'
        '                if c.result == CLAIM_UNVERIFIABLE]\n\n'
        '    @property\n'
        '    def critical_contradicted(self) -> List[ClaimCheck]:\n'
        '        return [c for c in self.critical_claims if c.contradicted]\n\n'
        '    @property\n'
        '    def critical_contradiction_spans_complete(self) -> Optional[bool]:\n'
        '        """None = no critical contradiction existed; otherwise exact-span completeness."""\n'
        '        if not self.critical_contradicted:\n'
        '            return None\n'
        '        return all(bool(c.contradiction_span) for c in self.critical_contradicted)\n\n',
        "critical contradiction report properties",
    )

    text = replace_once(
        text,
        '                "source_quality": cc.source_quality_label,\n'
        '                "evidence_spans": [dict(s) for s in cc.spans],\n',
        '                "source_quality": cc.source_quality_label,\n'
        '                "contradicted": bool(cc.contradicted),\n'
        '                "contradiction_span": (dict(cc.contradiction_span)\n'
        '                                       if cc.contradiction_span else {}),\n'
        '                "evidence_spans": [dict(s) for s in cc.spans],\n',
        "critical claim contradiction provenance",
    )
    text = replace_once(
        text,
        '                "same_source_ae_passed": cc.passes_ae,\n'
        '                "canonical_span": dict(cc.canonical_span) if cc.canonical_span else {},\n',
        '                "same_source_ae_passed": cc.passes_ae,\n'
        '                "verified_support": bool(cc.passes_ae and not cc.contradicted),\n'
        '                "canonical_span": dict(cc.canonical_span) if cc.canonical_span else {},\n',
        "critical claim accepted support provenance",
    )

    text = replace_once(
        text,
        '        for cc in self.claims:\n'
        '            if critical_only and not cc.critical:\n'
        '                continue\n'
        '            sid = cc.supporting_source_id if cc.passes_ae else ""\n',
        '        for cc in self.claims:\n'
        '            if critical_only and not cc.critical:\n'
        '                continue\n'
        '            if cc.contradicted:\n'
        '                continue\n'
        '            sid = cc.supporting_source_id if cc.passes_ae else ""\n',
        "supporting-source contradiction accounting",
    )

    text = replace_once(
        text,
        '                "contradicted_claims": self.contradicted,\n'
        '                "critical_claims": len(self.critical_claims),\n',
        '                "contradicted_claims": self.contradicted,\n'
        '                "critical_contradicted_claims": len(self.critical_contradicted),\n'
        '                "critical_contradiction_spans_complete":\n'
        '                    self.critical_contradiction_spans_complete,\n'
        '                "critical_claims": len(self.critical_claims),\n',
        "verification contradiction counters",
    )

    after_thresholds = threshold_snapshot(text)
    if after_thresholds != before_thresholds:
        die(f"thresholds changed unexpectedly: {after_thresholds}")
    return text


def patch_quality(text: str) -> str:
    if '"critical_contradiction_spans_complete"' in text:
        die("quality_producers.py already appears P0-C patched")
    text = replace_once(
        text,
        '    "average_relevance", "critical_claim_spans_complete",\n'
        '    "critical_claims_same_source_ae_passed", "claim_verification_achievement",\n',
        '    "average_relevance", "critical_claim_spans_complete",\n'
        '    "critical_contradiction_spans_complete",\n'
        '    "critical_claims_same_source_ae_passed", "claim_verification_achievement",\n',
        "quality tri-state contradiction completeness",
    )
    text = replace_once(
        text,
        '        "unverifiable_critical_claims": (vdict or {}).get("unverifiable_critical_claims"),\n'
        '        "critical_claims": (vdict or {}).get("critical_claims"),\n',
        '        "unverifiable_critical_claims": (vdict or {}).get("unverifiable_critical_claims"),\n'
        '        "critical_contradicted_claims": (vdict or {}).get("critical_contradicted_claims"),\n'
        '        "critical_contradiction_spans_complete":\n'
        '            (vdict or {}).get("critical_contradiction_spans_complete"),\n'
        '        "critical_claims": (vdict or {}).get("critical_claims"),\n',
        "quality context contradiction fields",
    )
    return text


def patch_final(text: str) -> str:
    if '"CONTRADICTION_SPAN_MISSING"' in text:
        die("final_quality_gate.py already appears P0-C patched")
    anchor = '''        no_source_count = _as_int(
            quality_context.get("critical_no_source_claims"),
            len(NO_SOURCE_RE.findall(answer)),
        )
'''
    block = '''        # P0-C — an explicit claim-level contradiction must itself have
        # exact provenance.  Legacy callers that do not emit the new count remain
        # compatible; current verification emits count + completeness explicitly.
        contradicted_value = quality_context.get("critical_contradicted_claims")
        if contradicted_value is None:
            contradicted_count = 0
            contradiction_span_ok = True
        else:
            contradicted_count = _as_int(contradicted_value)
            if contradicted_count <= 0:
                contradiction_span_ok = True
            else:
                contradiction_rows = [
                    row for row in _list_of_mappings(
                        quality_context.get("critical_claim_evidence_spans"))
                    if str(row.get("result") or "").strip().upper() == "CONTRADICTED"
                ]
                rows_complete = (
                    len(contradiction_rows) >= contradicted_count
                    and all(_meaningful(row.get("contradiction_span"), 2)
                            for row in contradiction_rows)
                )
                explicit_complete = quality_context.get(
                    "critical_contradiction_spans_complete")
                contradiction_span_ok = (
                    explicit_complete is not None
                    and _as_bool(explicit_complete)
                    and rows_complete
                )
        state.check("critical_contradictions_have_exact_spans", contradiction_span_ok)
        if not contradiction_span_ok:
            state.issue(
                "CONTRADICTION_SPAN_MISSING",
                "claim_citation",
                "critical",
                "A critical claim is marked contradicted without an exact source passage/locator.",
                deduction=5,
                hard_cap=60,
                details={"count": contradicted_count},
            )

'''
    text = replace_once(text, anchor, block + anchor, "final gate contradiction provenance")
    return text


def patch_status(text: str) -> str:
    heading = "## Evidence-grounding continuation — 2026-08-23"
    if heading in text:
        die("WORK_STATUS continuation section already exists")
    anchor = "## Latest independent offline validation — 2026-08-22"
    if anchor not in text:
        die("WORK_STATUS insertion anchor missing")
    section = '''## Evidence-grounding continuation — 2026-08-23

- **P0-A same-source evidence grounding:** merged through PR #18 at `66a4668` after Foundation run #371 passed. Critical support now requires one source to pass A-E together; check C is tied to a canonical evidence span/locator; explicit 0/0 does not count as verification achievement.
- **P0-B evidence-before-generation:** merged through PR #19 at `0874d93` after Foundation run #372 passed. A deterministic pre-draft evidence manifest constrains analysis/synthesis, post-generation matching is audited, and the final gate fails closed when required critical support was not preselected.
- These are **offline foundation** claims only. They do not replace the separate live ₹0 provider/deployment validation required before production sign-off.

'''
    return text.replace(anchor, section + anchor, 1)


def main() -> int:
    if branch_name() != EXPECTED_BRANCH:
        die(f"wrong branch; expected {EXPECTED_BRANCH}")
    for path in (CLAIM, QUALITY, FINAL, STATUS):
        if not path.is_file():
            die(f"missing file: {path.relative_to(ROOT)}")

    originals = {
        CLAIM: CLAIM.read_text(encoding="utf-8"),
        QUALITY: QUALITY.read_text(encoding="utf-8"),
        FINAL: FINAL.read_text(encoding="utf-8"),
        STATUS: STATUS.read_text(encoding="utf-8"),
    }
    patched = {
        CLAIM: patch_claim(originals[CLAIM]),
        QUALITY: patch_quality(originals[QUALITY]),
        FINAL: patch_final(originals[FINAL]),
        STATUS: patch_status(originals[STATUS]),
    }

    # Final cross-file invariants before first write.
    claim_text = patched[CLAIM]
    final_text = patched[FINAL]
    quality_text = patched[QUALITY]
    required_markers = (
        "claim_contradiction_from_spans",
        "contradiction_span: Dict = field(default_factory=dict)",
        "critical_contradiction_spans_complete",
    )
    if not all(marker in claim_text for marker in required_markers):
        die("claim-verification P0-C markers incomplete")
    if "text = source_text(record, pack)" in claim_text[claim_text.find("def claim_contradicted"):]:
        die("source-wide contradiction scan survived wrapper")
    if "CONTRADICTION_SPAN_MISSING" not in final_text:
        die("final fail-closed contradiction gate missing")
    if '"critical_contradiction_spans_complete"' not in quality_text:
        die("quality contradiction audit propagation missing")
    if threshold_snapshot(claim_text) != THRESHOLDS:
        die("threshold invariant failed at final validation")

    for path, content in patched.items():
        path.write_text(content, encoding="utf-8", newline="\n")

    print("P0-C claim-level contradiction integration applied safely to 4 files.")
    print(f"Thresholds unchanged: {THRESHOLDS}")
    print("[OK] contradiction uses exact selected per-source spans")
    print("[OK] contradiction source/locator provenance recorded")
    print("[OK] contradicted strong claims blocked from support/achievement accounting")
    print("[OK] final gate requires exact contradiction span for explicit P0-C records")
    print("[OK] P0-A/P0-B merged status recorded without claiming live production readiness")
    return 0


if __name__ == "__main__":
    sys.exit(main())
