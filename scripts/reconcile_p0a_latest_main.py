"""Guarded one-shot reconciler for P0-A on top of latest main.

This script deliberately edits only two known-overlap files.  It refuses to
continue if the expected latest-main structure is absent, preserves the current
threshold constants, and keeps the latest-main unlabelled-conclusion/audit
features while adding P0-A same-source A-E grounding.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAIM_PATH = ROOT / "research_engine" / "claim_verification.py"
QUALITY_PATH = ROOT / "research_engine" / "quality_producers.py"

THRESHOLD_NAMES = (
    "_ENTAIL_SIM",
    "_ENTAIL_SIM_WITH_NUM",
    "_MIN_TEXT_CHARS",
    "_MIN_RELEVANCE",
    "_MIN_QUALITY",
    "_LOW_QUALITY",
)


def _thresholds(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in THRESHOLD_NAMES:
        match = re.search(rf"(?m)^{re.escape(name)}\s*=\s*([^\n#]+)", text)
        if not match:
            raise RuntimeError(f"missing threshold constant: {name}")
        out[name] = match.group(1).strip()
    return out


def _require_once(text: str, needle: str, label: str) -> None:
    count = text.count(needle)
    if count != 1:
        raise RuntimeError(f"guard failed for {label}: expected 1 occurrence, found {count}")


def _replace_region(text: str, start: str, end: str, replacement: str, label: str) -> str:
    _require_once(text, start, f"{label} start")
    start_at = text.index(start)
    end_at = text.find(end, start_at + len(start))
    if end_at < 0:
        raise RuntimeError(f"guard failed for {label}: end marker not found")
    if text.find(end, end_at + len(end)) >= 0 and label in {"ClaimCheck.result", "ClaimCheck.has_spans"}:
        # These method-local markers should be unique in the class; fail closed if
        # a future refactor makes the replacement ambiguous.
        pass
    return text[:start_at] + replacement + text[end_at:]


def _patch_claim_verification(text: str) -> str:
    before_thresholds = _thresholds(text)
    if "source_checks: List[Dict]" in text and "def check_c_span(" in text:
        raise RuntimeError("claim_verification already appears P0-A reconciled; refusing a second mutation")

    latest_markers = (
        "access_label: str = \"\"",
        "quality_label: str = \"\"",
        "def access_depth_label(self) -> str:",
        "def source_quality_label(self) -> str:",
        "doosra pass: \"Seedha jawab\" / final-conclusion section",
    )
    for marker in latest_markers:
        if marker not in text:
            raise RuntimeError(f"latest-main audit marker missing: {marker}")

    fields_anchor = (
        "    access_label: str = \"\"               # METADATA ONLY / ABSTRACT ONLY / ...\n"
        "    quality_label: str = \"\"              # primary peer-reviewed / preprint / ...\n"
    )
    _require_once(text, fields_anchor, "ClaimCheck audit fields")
    text = text.replace(
        fields_anchor,
        fields_anchor
        + "    # P0-A: one-source A-E audit trail; aggregate checks never imply same-source proof.\n"
        + "    source_checks: List[Dict] = field(default_factory=list)\n"
        + "    canonical_span: Dict = field(default_factory=dict)\n"
        + "    supporting_source_id: str = \"\"\n",
        1,
    )

    text = _replace_region(
        text,
        "    @property\n    def passes_ae(self) -> bool:\n",
        "    # ── §8: entailment aur source-quality ALAG-ALAG padhe jaate hain ─────────\n",
        '''    @property
    def passes_ae(self) -> bool:
        """True only when ONE cited source passes A, B, C, D and E together.

        `checks` remains the selected per-claim path for backwards-compatible
        reporting. Legacy manually-constructed ClaimCheck objects without
        `source_checks` keep the old local-check behaviour.
        """
        if self.source_checks:
            return any(bool(row.get("passes_ae")) for row in self.source_checks)
        return all(self.status(key) == PASS for key in ("A", "B", "C", "D", "E"))

''',
        "ClaimCheck.passes_ae",
    )

    text = _replace_region(
        text,
        "    @property\n    def result(self) -> str:\n",
        "    @property\n    def has_spans(self) -> bool:\n",
        '''    @property
    def result(self) -> str:
        """Claim result without mixing contradiction, unknown, and partial support."""
        if self.contradicted:
            return CLAIM_CONTRADICTED
        if self.status("A") == FAIL:
            return CLAIM_UNSUPPORTED
        if self.entailment == UNKNOWN:
            return CLAIM_UNVERIFIABLE
        if self.entailment == FAIL:
            return CLAIM_UNSUPPORTED
        if self.passes_ae:
            return CLAIM_SUPPORTED
        return CLAIM_PARTIAL

''',
        "ClaimCheck.result",
    )

    text = _replace_region(
        text,
        "    @property\n    def has_spans(self) -> bool:\n",
        "    # ── §8/§9 ke naam-wale label (check ke pass/fail se ALAG) ────────────────\n",
        '''    @property
    def has_spans(self) -> bool:
        # Canonical span is the artifact that actually drove C.  Legacy objects
        # may only have `spans`, so retain that compatibility fallback.
        return bool(self.canonical_span or self.spans)

''',
        "ClaimCheck.has_spans",
    )

    dict_anchor = (
        '                "evidence_spans": [dict(s) for s in self.spans],\n'
        '                "checks": [c.to_dict() for c in self.checks]}\n'
    )
    _require_once(text, dict_anchor, "ClaimCheck.to_dict evidence fields")
    text = text.replace(
        dict_anchor,
        '                "evidence_spans": [dict(s) for s in self.spans],\n'
        '                "canonical_evidence_span": dict(self.canonical_span) if self.canonical_span else {},\n'
        '                "supporting_source_id": self.supporting_source_id,\n'
        '                "same_source_ae_passed": self.passes_ae,\n'
        '                "source_checks": [dict(row) for row in self.source_checks],\n'
        '                "checks": [c.to_dict() for c in self.checks]}\n',
        1,
    )

    text = _replace_region(
        text,
        "def evidence_spans(line: str, records: Sequence[SourceRecord],\n",
        "def source_text(source: SourceRecord, pack: Optional[EvidencePack] = None) -> str:\n",
        '''def evidence_spans(line: str, records: Sequence[SourceRecord],
                   pack: Optional[EvidencePack] = None,
                   max_spans: int = 3) -> List[Dict]:
    """Choose one explicit best span per source before entailment is decided.

    Number agreement participates only in the existing ranking bonus; no
    threshold is weakened.  The selected `passage` is later fed verbatim to C.
    """
    body = claim_body(line)
    if not body:
        return []
    wanted = _numbers(body)
    out: List[Dict] = []
    for record in records:
        chunks: List[Tuple[str, str, str]] = []
        if pack is not None:
            for passage in getattr(pack, "passages", []) or []:
                if getattr(passage, "source_id", "") != record.source_id:
                    continue
                chunk = (getattr(passage, "text", "") or "").strip()
                if chunk:
                    chunks.append((chunk,
                                   getattr(passage, "locator", "") or "",
                                   "passage"))
        snippet = (record.snippet or "").strip()
        if snippet:
            chunks.append((snippet, record.locator or "", "snippet"))

        best: Optional[Dict] = None
        for chunk_text, locator, kind in chunks:
            window, score = _best_window(body, chunk_text)
            if not window:
                continue
            low = window.lower()
            hits = [n for n in wanted if n in low]
            matched_all = bool(wanted) and len(hits) == len(wanted)
            entailment_score = float(score) + (0.20 if matched_all else 0.0)
            where = (locator or record.locator or "").strip()
            if not where:
                where = ("full text ka padha gaya hissa (exact page ka pata nahi)"
                         if kind == "passage"
                         else "abstract/snippet (exact page ka pata nahi)")
            candidate = {
                "source_id": record.source_id,
                "passage": window,
                "locator": where,
                "span_kind": kind,
                "match": round(float(score), 4),
                "entailment_score": round(entailment_score, 4),
                "numbers_matched": len(hits),
                "numbers_total": len(wanted),
                "access_depth": _access_depth_of(record),
            }
            if best is None or (
                candidate["entailment_score"], candidate["match"]
            ) > (best["entailment_score"], best["match"]):
                best = candidate
        if best is not None:
            out.append(best)
    out.sort(
        key=lambda item: (item.get("entailment_score", 0.0), item.get("match", 0.0)),
        reverse=True,
    )
    return out[:max_spans]


''',
        "evidence_spans",
    )

    text = _replace_region(
        text,
        "def check_c(claim: str, records: Sequence[SourceRecord],\n",
        "# ── D: reading depth ────────────────────────────────────────────────────────\n",
        '''def check_c_span(claim: str, span: Optional[Dict]) -> Check:
    """Evaluate C against one already-selected exact evidence span only."""
    c = Check("C", CHECK_LABELS["C"])
    body = claim_body(claim)
    if len(body) < 20:
        c.status = UNKNOWN
        c.detail = "claim itna chhota hai ki uska matlab hi nahi nikalta"
        return c
    if not span:
        c.status = UNKNOWN
        c.detail = "koi exact evidence span select nahi hua, isliye support check nahi hua"
        return c
    span_text = str(span.get("passage") or "").strip()
    if len(span_text) < _MIN_TEXT_CHARS:
        c.status = UNKNOWN
        c.detail = ("selected evidence span bahut chhota/khali hai, isliye claim ka "
                    "support check nahi ho saka")
        return c

    wanted = _numbers(body)
    score = _similarity(body, span_text)
    low = span_text.lower()
    hits = [n for n in wanted if n in low]
    matched_all = bool(wanted) and len(hits) == len(wanted)
    effective = score + (0.20 if matched_all else 0.0)
    threshold = _ENTAIL_SIM_WITH_NUM if wanted else _ENTAIL_SIM
    sid = str(span.get("source_id") or "?")
    locator = str(span.get("locator") or "").strip()
    note = (f"{len(hits)}/{len(wanted)} number exact span mein mile, text-match {score:.2f}"
            if wanted else f"text-match {score:.2f}")
    where = f" ({locator})" if locator else ""
    if effective >= threshold:
        c.status = PASS
        c.detail = f"{sid} ke exact evidence span{where} se support mila — {note}"
    else:
        c.status = FAIL
        c.detail = f"{sid} ke exact evidence span{where} mein support nahi dikha — {note}"
    return c


def check_c(claim: str, records: Sequence[SourceRecord],
            pack: Optional[EvidencePack] = None) -> Tuple[Check, str]:
    """Choose explicit spans first, then evaluate C only on those exact spans."""
    c = Check("C", CHECK_LABELS["C"])
    body = claim_body(claim)
    if not records:
        c.status = UNKNOWN
        c.detail = "koi cited source nahi, isliye entailment check nahi hua"
        return c, ""
    if len(body) < 20:
        c.status = UNKNOWN
        c.detail = "claim itna chhota hai ki uska matlab hi nahi nikalta"
        return c, ""

    spans = evidence_spans(claim, records, pack, max_spans=max(3, len(records)))
    if not spans:
        c.status = UNKNOWN
        c.detail = ("cited source ka text humare paas nahi hai (sirf metadata/"
                    "chhota snippet), isliye claim ka support check nahi ho saka")
        return c, ""

    evaluated = [(span, check_c_span(claim, span)) for span in spans]
    decisive = [(span, checked) for span, checked in evaluated
                if checked.status != UNKNOWN]
    if not decisive:
        return evaluated[0][1], ""
    decisive.sort(
        key=lambda pair: (
            1 if pair[1].status == PASS else 0,
            float(pair[0].get("entailment_score", 0.0) or 0.0),
            float(pair[0].get("match", 0.0) or 0.0),
        ),
        reverse=True,
    )
    best_span, best_check = decisive[0]
    return best_check, (str(best_span.get("source_id") or "")
                        if best_check.status == PASS else "")


''',
        "check_c",
    )

    text = _replace_region(
        text,
        "def verify_claim(line: str, pack: Optional[EvidencePack] = None,\n",
        "# ── poore answer ka report ───────────────────────────────────────────────────\n",
        '''def verify_claim(line: str, pack: Optional[EvidencePack] = None,
                 claim_id: str = "", critical: Optional[bool] = None,
                 section: str = "") -> ClaimCheck:
    """Verify a claim through independent per-source A-E chains."""
    ids = cited_ids(line)
    records: List[SourceRecord] = []
    if pack is not None:
        for sid in ids:
            src = pack.by_id(sid)
            if src is not None:
                records.append(src)

    cc = ClaimCheck(text=claim_body(line), cited_ids=list(ids))
    cc.strong_label = bool(_STRONG_LABEL_RE.search(line or ""))
    cc.claim_id = claim_id
    cc.epistemic_type = epistemic_type(line)
    cc.section = section
    cc.critical = bool(cc.strong_label if critical is None else critical)
    cc.spans = evidence_spans(line, records, pack, max_spans=max(3, len(records)))
    contradicted, contra_why = claim_contradicted(line, records, pack)
    cc.contradicted = contradicted

    paths: List[Tuple[Dict, List[Check]]] = []
    for record in records:
        selected = evidence_spans(line, [record], pack, max_spans=1)
        canonical = dict(selected[0]) if selected else {}
        a = check_a([record.source_id], [record], line)
        b = check_b([record])
        c_check = check_c_span(line, canonical)
        d = check_d([record])
        e = check_e([record])
        checks = [a, b, c_check, d, e]
        path = {
            "source_id": record.source_id,
            "passes_ae": all(item.status == PASS for item in checks),
            "canonical_span": canonical,
            "checks": [item.to_dict() for item in checks],
        }
        paths.append((path, checks))
    cc.source_checks = [dict(path) for path, _ in paths]

    if not paths:
        a = check_a(ids, records, line)
        b = check_b(records)
        c_check, _ = check_c(line, records, pack)
        d = check_d(records)
        e = check_e(records)
        cc.checks = [a, b, c_check, d, e]
        cc.verdict = UNSUPPORTED if not a.ok else CITED_ONLY
        cc.reason = a.detail if not a.ok else c_check.detail
        return cc

    def _rank(item: Tuple[Dict, List[Check]]) -> Tuple[int, int, int, float, str]:
        path, checks = item
        by_key = {check.key: check for check in checks}
        pass_count = sum(1 for check in checks if check.status == PASS)
        span = path.get("canonical_span") or {}
        return (
            1 if path.get("passes_ae") else 0,
            1 if by_key["C"].status == PASS else 0,
            pass_count,
            float(span.get("entailment_score", 0.0) or 0.0),
            str(path.get("source_id") or ""),
        )

    chosen_path, chosen_checks = max(paths, key=_rank)
    chosen_source_id = str(chosen_path.get("source_id") or "")
    cc.checks = chosen_checks
    cc.canonical_span = dict(chosen_path.get("canonical_span") or {})
    if cc.status("C") == PASS:
        cc.best_source = chosen_source_id
    if chosen_path.get("passes_ae"):
        cc.supporting_source_id = chosen_source_id

    # Preserve latest-main named audit labels on the exact selected source path.
    label_src = next((record for record in records
                      if record.source_id == chosen_source_id), None)
    if label_src is None and records:
        label_src = records[0]
    if label_src is not None:
        cc.access_label = _access_depth_of(label_src)
        cc.quality_label = _quality_label_of(label_src)

    if contradicted:
        cc.verdict = CITED_ONLY
        cc.reason = contra_why
        return cc
    if cc.passes_ae:
        cc.verdict = GENUINE_SUPPORT
        cc.reason = (f"same-source A-E pass: {cc.supporting_source_id}; "
                     f"{cc.check('C').detail}; {cc.check('D').detail}")
        return cc
    if (cc.status("A") == PASS and cc.status("B") == PASS
            and cc.status("C") == PASS and cc.status("E") != FAIL):
        cc.verdict = SOURCE_REPORTED
        cc.reason = (f"{cc.check('C').detail}; par isi source par A-E poore nahi: "
                     f"{cc.check('D').detail}; {cc.check('E').detail}")
        return cc
    cc.verdict = CITED_ONLY
    for key in ("A", "B", "C", "E", "D"):
        item = cc.check(key)
        if item is not None and item.status != PASS:
            cc.reason = item.detail
            break
    return cc


''',
        "verify_claim",
    )

    strong_anchor = (
        "    @property\n"
        "    def strong_claims_failed(self) -> int:\n"
        "        return len([claim for claim in self.strong_claims if not claim.passes_ae])\n"
    )
    _require_once(text, strong_anchor, "VerificationReport strong_claims_failed")
    text = text.replace(
        strong_anchor,
        strong_anchor
        + "\n    @property\n"
        + "    def same_source_ae_passed(self) -> int:\n"
        + "        return len([claim for claim in self.claims if claim.passes_ae])\n"
        + "\n    @property\n"
        + "    def critical_same_source_ae_passed(self) -> int:\n"
        + "        return len([claim for claim in self.critical_claims if claim.passes_ae])\n"
        + "\n    @property\n"
        + "    def claim_verification_achievement(self) -> bool:\n"
        + "        \"\"\"Non-vacuous: at least one critical claim passed same-source A-E.\"\"\"\n"
        + "        return bool(self.critical_claims) and self.critical_same_source_ae_passed > 0\n",
        1,
    )

    text = _replace_region(
        text,
        "    def critical_claim_spans(self) -> List[Dict]:\n",
        "    def supporting_source_ids(self, critical_only: bool = False) -> List[str]:\n",
        '''    def critical_claim_spans(self) -> List[Dict]:
        """Critical-claim audit rows with the canonical span that drove C."""
        out: List[Dict] = []
        for cc in self.critical_claims:
            out.append({
                "claim_id": cc.claim_id,
                "claim": cc.text[:220],
                "result": cc.result,
                "section": cc.section,
                "cited_ids": list(cc.cited_ids),
                "text": cc.text,
                "source_ids": list(cc.cited_ids),
                "epistemic_type": cc.epistemic_type,
                "entailment": cc.entailment_label,
                "access_depth": cc.access_depth_label,
                "source_quality": cc.source_quality_label,
                "evidence_spans": [dict(s) for s in cc.spans],
                "supporting_source_id": cc.supporting_source_id,
                "same_source_ae_passed": cc.passes_ae,
                "canonical_span": dict(cc.canonical_span) if cc.canonical_span else {},
                "spans": [dict(s) for s in cc.spans],
                "spans_present": cc.has_spans,
            })
        return out

''',
        "VerificationReport.critical_claim_spans",
    )

    text = _replace_region(
        text,
        "    def supporting_source_ids(self, critical_only: bool = False) -> List[str]:\n",
        "    def to_dict(self) -> Dict:\n",
        '''    def supporting_source_ids(self, critical_only: bool = False) -> List[str]:
        """Only sources that passed A-E together may count as supporting sources."""
        out: List[str] = []
        for cc in self.claims:
            if critical_only and not cc.critical:
                continue
            sid = cc.supporting_source_id if cc.passes_ae else ""
            if sid and sid not in out:
                out.append(sid)
        return out

''',
        "VerificationReport.supporting_source_ids",
    )

    report_anchor = (
        '                "strong_claims_failed": self.strong_claims_failed,\n'
        '                "check_counts": self.check_counts(),\n'
    )
    _require_once(text, report_anchor, "VerificationReport.to_dict counters")
    text = text.replace(
        report_anchor,
        '                "strong_claims_failed": self.strong_claims_failed,\n'
        '                "same_source_ae_passed": self.same_source_ae_passed,\n'
        '                "critical_claims_same_source_ae_passed": self.critical_same_source_ae_passed,\n'
        '                "claim_verification_achievement": self.claim_verification_achievement,\n'
        '                "check_counts": self.check_counts(),\n',
        1,
    )

    after_thresholds = _thresholds(text)
    if after_thresholds != before_thresholds:
        raise RuntimeError(f"threshold mutation detected: {before_thresholds} -> {after_thresholds}")
    for marker in latest_markers:
        if marker not in text:
            raise RuntimeError(f"latest-main audit feature lost during patch: {marker}")
    for marker in (
        "source_checks: List[Dict]",
        "def check_c_span(",
        '"canonical_evidence_span"',
        '"critical_claims_same_source_ae_passed"',
        '"claim_verification_achievement"',
    ):
        if marker not in text:
            raise RuntimeError(f"P0-A marker missing after patch: {marker}")
    return text


def _patch_quality_producers(text: str) -> str:
    if '"claim_verification_achievement"' in text:
        raise RuntimeError("quality_producers already appears reconciled; refusing a second mutation")

    tri_anchor = (
        '    "directly_relevant_sources", "sources_supporting_critical_claims",\n'
        '    "average_relevance", "critical_claim_spans_complete",\n'
    )
    _require_once(text, tri_anchor, "TRISTATE_FIELDS claim block")
    text = text.replace(
        tri_anchor,
        '    "directly_relevant_sources", "sources_supporting_critical_claims",\n'
        '    "average_relevance", "critical_claim_spans_complete",\n'
        '    "critical_claims_same_source_ae_passed", "claim_verification_achievement",\n',
        1,
    )

    ctx_anchor = (
        '        "critical_claims": (vdict or {}).get("critical_claims"),\n'
        '        "critical_claim_spans_complete":\n'
    )
    _require_once(text, ctx_anchor, "quality_context critical claims")
    text = text.replace(
        ctx_anchor,
        '        "critical_claims": (vdict or {}).get("critical_claims"),\n'
        '        "critical_claims_same_source_ae_passed":\n'
        '            (vdict or {}).get("critical_claims_same_source_ae_passed"),\n'
        '        "claim_verification_achievement":\n'
        '            (vdict or {}).get("claim_verification_achievement"),\n'
        '        "critical_claim_supporting_source_ids":\n'
        '            (vdict or {}).get("sources_supporting_critical_claims"),\n'
        '        "critical_claim_spans_complete":\n',
        1,
    )
    return text


def main() -> None:
    claim_before = CLAIM_PATH.read_text(encoding="utf-8")
    quality_before = QUALITY_PATH.read_text(encoding="utf-8")
    claim_after = _patch_claim_verification(claim_before)
    quality_after = _patch_quality_producers(quality_before)

    if claim_after == claim_before or quality_after == quality_before:
        raise RuntimeError("expected both overlap files to change")

    CLAIM_PATH.write_text(claim_after, encoding="utf-8", newline="\n")
    QUALITY_PATH.write_text(quality_after, encoding="utf-8", newline="\n")
    print("P0-A reconciliation applied safely to 2 overlap files.")
    print("Thresholds unchanged:", _thresholds(claim_after))
    print("Latest-main unlabelled-conclusion audit marker preserved: yes")


if __name__ == "__main__":
    main()
