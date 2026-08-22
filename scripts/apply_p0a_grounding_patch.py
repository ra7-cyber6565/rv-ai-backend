from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    "research_engine/claim_verification.py",
    "research_engine/quality_producers.py",
    "research_engine/final_quality_gate.py",
)


def _literal_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 literal match, found {count}")
    return text.replace(old, new, 1)


def _regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    new, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 regex match, found {count}")
    return new


def patch_claim_verification(text: str) -> str:
    text = _literal_once(
        text,
        '    spans: List[Dict] = field(default_factory=list)   # evidence spans\n'
        '    section: str = ""                    # kis section ki line thi\n',
        '    spans: List[Dict] = field(default_factory=list)   # evidence spans\n'
        '    section: str = ""                    # kis section ki line thi\n'
        '    # P0-A: A-E ka ek hi-source audit trail. Aggregate checks ko kabhi\n'
        '    # same-source success samajhna allowed nahi.\n'
        '    source_checks: List[Dict] = field(default_factory=list)\n'
        '    canonical_span: Dict = field(default_factory=dict)\n'
        '    supporting_source_id: str = ""\n',
        "ClaimCheck P0-A fields",
    )

    text = _regex_once(
        text,
        r'    @property\n    def passes_ae\(self\) -> bool:\n.*?(?=\n    # ── §8: entailment)',
        '''    @property
    def passes_ae(self) -> bool:
        """True only when ONE cited source passes A, B, C, D and E together.

        `checks` remains the selected per-claim path for backwards-compatible
        reporting, but P0-A never synthesizes A-E success across different
        sources. Legacy manually-constructed ClaimCheck objects without
        `source_checks` keep the old local check behavior.
        """
        if self.source_checks:
            return any(bool(row.get("passes_ae")) for row in self.source_checks)
        return all(self.status(key) == PASS for key in ("A", "B", "C", "D", "E"))
''',
        "ClaimCheck.passes_ae",
    )

    text = _literal_once(
        text,
        '''        if (self.access_depth == PASS and self.source_quality != FAIL
                and self.status("B") != FAIL):
            return CLAIM_SUPPORTED
        return CLAIM_PARTIAL
''',
        '''        if self.passes_ae:
            return CLAIM_SUPPORTED
        return CLAIM_PARTIAL
''',
        "ClaimCheck.result same-source support",
    )

    text = _regex_once(
        text,
        r'    @property\n    def has_spans\(self\) -> bool:\n.*?(?=\n    def failed_checks)',
        '''    @property
    def has_spans(self) -> bool:
        # P0-A canonical span is the evidence artifact actually used by C.
        # Legacy objects may only have `spans`, so keep that fallback.
        return bool(self.canonical_span or self.spans)
''',
        "ClaimCheck.has_spans",
    )

    text = _literal_once(
        text,
        '                "evidence_spans": [dict(s) for s in self.spans],\n'
        '                "checks": [c.to_dict() for c in self.checks]}\n',
        '                "evidence_spans": [dict(s) for s in self.spans],\n'
        '                "canonical_evidence_span": dict(self.canonical_span) if self.canonical_span else {},\n'
        '                "supporting_source_id": self.supporting_source_id,\n'
        '                "same_source_ae_passed": self.passes_ae,\n'
        '                "source_checks": [dict(row) for row in self.source_checks],\n'
        '                "checks": [c.to_dict() for c in self.checks]}\n',
        "ClaimCheck.to_dict P0-A fields",
    )

    text = _regex_once(
        text,
        r'def evidence_spans\(line: str, records: Sequence\[SourceRecord\],\n'
        r'\s+pack: Optional\[EvidencePack\] = None,\n'
        r'\s+max_spans: int = 3\) -> List\[Dict\]:\n.*?(?=\n\ndef source_text)',
        '''def evidence_spans(line: str, records: Sequence[SourceRecord],
                   pack: Optional[EvidencePack] = None,
                   max_spans: int = 3) -> List[Dict]:
    """Return one explicit best evidence span per cited source.

    P0-A chooses a concrete passage/window first. The same exact `passage` is
    later fed to check C; source-wide concatenated text is not the support
    artifact. Number agreement participates in span ranking without changing
    any entailment threshold.
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
                text = (getattr(passage, "text", "") or "").strip()
                if text:
                    chunks.append((text,
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
            candidate = {
                "source_id": record.source_id,
                "passage": window,
                "locator": locator or record.locator or "",
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
        key=lambda d: (d.get("entailment_score", 0.0), d.get("match", 0.0)),
        reverse=True,
    )
    return out[:max_spans]
''',
        "evidence_spans canonical ranking",
    )

    text = _regex_once(
        text,
        r'def check_c\(claim: str, records: Sequence\[SourceRecord\],\n'
        r'\s+pack: Optional\[EvidencePack\] = None\) -> Tuple\[Check, str\]:\n.*?(?=\n\n# ── D: reading depth)',
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
    text = str(span.get("passage") or "").strip()
    if len(text) < _MIN_TEXT_CHARS:
        c.status = UNKNOWN
        c.detail = ("selected evidence span bahut chhota/khali hai, isliye claim ka "
                    "support check nahi ho saka")
        return c

    wanted = _numbers(body)
    score = _similarity(body, text)
    low = text.lower()
    hits = [n for n in wanted if n in low]
    matched_all = bool(wanted) and len(hits) == len(wanted)
    effective = score + (0.20 if matched_all else 0.0)
    threshold = _ENTAIL_SIM_WITH_NUM if wanted else _ENTAIL_SIM
    sid = str(span.get("source_id") or "?")
    locator = str(span.get("locator") or "").strip()
    if wanted:
        note = f"{len(hits)}/{len(wanted)} number exact span mein mile, text-match {score:.2f}"
    else:
        note = f"text-match {score:.2f}"
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
    """Choose explicit spans first, then evaluate C on those exact spans."""
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

    evaluated: List[Tuple[Dict, Check]] = []
    for span in spans:
        checked = check_c_span(claim, span)
        evaluated.append((span, checked))
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
        "check_c exact-span implementation",
    )

    text = _regex_once(
        text,
        r'def verify_claim\(line: str, pack: Optional\[EvidencePack\] = None,\n'
        r'\s+claim_id: str = "", critical: Optional\[bool\] = None,\n'
        r'\s+section: str = ""\) -> ClaimCheck:\n.*?(?=\n\n# ── poore answer ka report)',
        '''def verify_claim(line: str, pack: Optional[EvidencePack] = None,
                 claim_id: str = "", critical: Optional[bool] = None,
                 section: str = "") -> ClaimCheck:
    """Verify one claim with a per-source A-E chain and canonical evidence span."""
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
        passes = all(item.status == PASS for item in checks)
        path = {
            "source_id": record.source_id,
            "passes_ae": passes,
            "canonical_span": canonical,
            "checks": [item.to_dict() for item in checks],
        }
        paths.append((path, checks))

    cc.source_checks = [dict(path) for path, _checks in paths]

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
    cc.checks = chosen_checks
    cc.canonical_span = dict(chosen_path.get("canonical_span") or {})
    if cc.status("C") == PASS:
        cc.best_source = str(chosen_path.get("source_id") or "")
    if chosen_path.get("passes_ae"):
        cc.supporting_source_id = str(chosen_path.get("source_id") or "")

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
        "verify_claim per-source A-E",
    )

    text = _literal_once(
        text,
        '''    @property
    def strong_claims_failed(self) -> int:
        return len([claim for claim in self.strong_claims if not claim.passes_ae])

    @property
    def gate_passed(self) -> bool:
''',
        '''    @property
    def strong_claims_failed(self) -> int:
        return len([claim for claim in self.strong_claims if not claim.passes_ae])

    @property
    def same_source_ae_passed(self) -> int:
        return len([claim for claim in self.claims if claim.passes_ae])

    @property
    def critical_same_source_ae_passed(self) -> int:
        return len([claim for claim in self.critical_claims if claim.passes_ae])

    @property
    def claim_verification_achievement(self) -> bool:
        """Non-vacuous achievement: at least one critical claim passed same-source A-E."""
        return bool(self.critical_claims) and self.critical_same_source_ae_passed > 0

    @property
    def gate_passed(self) -> bool:
''',
        "VerificationReport achievement properties",
    )

    text = _regex_once(
        text,
        r'    def critical_claim_spans\(self\) -> List\[Dict\]:\n.*?(?=\n    def to_dict\(self\) -> Dict:)',
        '''    def critical_claim_spans(self) -> List[Dict]:
        """Critical claims with the canonical exact span that drove check C."""
        out: List[Dict] = []
        for cc in self.critical_claims:
            out.append({
                "claim_id": cc.claim_id,
                "claim": cc.text[:220],
                "result": cc.result,
                "section": cc.section,
                "cited_ids": list(cc.cited_ids),
                "supporting_source_id": cc.supporting_source_id,
                "same_source_ae_passed": cc.passes_ae,
                "canonical_span": dict(cc.canonical_span) if cc.canonical_span else {},
                "spans": [dict(s) for s in cc.spans],
                "spans_present": cc.has_spans,
            })
        return out

    def supporting_source_ids(self, critical_only: bool = False) -> List[str]:
        """Sources that passed A-E together for a claim; never aggregate C-only support."""
        out: List[str] = []
        for cc in self.claims:
            if critical_only and not cc.critical:
                continue
            sid = cc.supporting_source_id if cc.passes_ae else ""
            if sid and sid not in out:
                out.append(sid)
        return out
''',
        "VerificationReport canonical spans/supporting IDs",
    )

    text = _literal_once(
        text,
        '                "strong_claims_failed": self.strong_claims_failed,\n'
        '                "check_counts": self.check_counts(),\n',
        '                "strong_claims_failed": self.strong_claims_failed,\n'
        '                "same_source_ae_passed": self.same_source_ae_passed,\n'
        '                "critical_claims_same_source_ae_passed": self.critical_same_source_ae_passed,\n'
        '                "claim_verification_achievement": self.claim_verification_achievement,\n'
        '                "check_counts": self.check_counts(),\n',
        "VerificationReport.to_dict achievement",
    )

    return text


def patch_quality_producers(text: str) -> str:
    text = _literal_once(
        text,
        '    "average_relevance", "critical_claim_spans_complete",\n',
        '    "average_relevance", "critical_claim_spans_complete",\n'
        '    "critical_claims_same_source_ae_passed", "claim_verification_achievement",\n',
        "quality_context tri-state P0-A fields",
    )
    text = _literal_once(
        text,
        '''        "critical_claims": (vdict or {}).get("critical_claims"),
        "critical_claim_spans_complete":
            (vdict or {}).get("critical_claim_spans_complete"),
        "critical_claim_evidence_spans": (vdict or {}).get("critical_claim_spans"),
''',
        '''        "critical_claims": (vdict or {}).get("critical_claims"),
        "critical_claims_same_source_ae_passed":
            (vdict or {}).get("critical_claims_same_source_ae_passed"),
        "claim_verification_achievement":
            (vdict or {}).get("claim_verification_achievement"),
        "critical_claim_supporting_source_ids":
            (vdict or {}).get("sources_supporting_critical_claims"),
        "critical_claim_spans_complete":
            (vdict or {}).get("critical_claim_spans_complete"),
        "critical_claim_evidence_spans": (vdict or {}).get("critical_claim_spans"),
''',
        "quality_context P0-A claim fields",
    )
    return text


def patch_final_quality_gate(text: str) -> str:
    text = _literal_once(
        text,
        '        self._check_claims(state, answer, verification, labels, quality_context)\n',
        '        self._check_claims(state, answer, verification, labels, quality_context, spec)\n',
        "FinalQualityGate evaluate claim signature",
    )
    text = _literal_once(
        text,
        '''        quality_context: Mapping[str, Any],
    ) -> None:
''',
        '''        quality_context: Mapping[str, Any],
        spec: QualityContract,
    ) -> None:
''',
        "FinalQualityGate._check_claims signature",
    )

    anchor = '''        if unsupported:
            state.issue(
                "CRITICAL_CLAIM_UNSUPPORTED",
                "claim_citation",
                "critical",
                "At least one critical claim failed source-entailment verification.",
                deduction=10,
                hard_cap=40,
                details={"count": unsupported},
            )

'''
    achievement = '''        if unsupported:
            state.issue(
                "CRITICAL_CLAIM_UNSUPPORTED",
                "claim_citation",
                "critical",
                "At least one critical claim failed source-entailment verification.",
                deduction=10,
                hard_cap=40,
                details={"count": unsupported},
            )

        # P0-A keeps two meanings separate:
        #   safety: no unsupported strong label escaped (can be true at 0/0)
        #   achievement: at least one required critical claim genuinely passed
        #                A-E on the SAME source (must never pass at 0/0).
        achievement_required = any(
            section in set(spec.required_sections)
            for section in ("direct_answer", "established_knowledge",
                            "supporting_evidence", "conclusion")
        )
        explicit_achievement = quality_context.get("claim_verification_achievement")
        explicit_passed = quality_context.get("critical_claims_same_source_ae_passed")
        explicit_total = quality_context.get("critical_claims")
        if not achievement_required:
            achievement_ok = True
        elif explicit_achievement is not None:
            achievement_ok = _as_bool(explicit_achievement)
        elif explicit_passed is not None or explicit_total is not None:
            achievement_ok = (_as_int(explicit_total) > 0
                              and _as_int(explicit_passed) > 0)
        else:
            legacy_support = _as_int(
                quality_context.get("sources_supporting_critical_claims"), 0
            )
            legacy_spans = quality_context.get("critical_claim_evidence_spans")
            achievement_ok = legacy_support > 0 and isinstance(legacy_spans, list) and bool(legacy_spans)
        state.check("verified_critical_claim_achievement", achievement_ok)
        if not achievement_ok:
            state.issue(
                "CRITICAL_CLAIM_ACHIEVEMENT_MISSING",
                "claim_citation",
                "critical",
                "No required critical claim achieved same-source A-E support; 0/0 is not verification success.",
                deduction=8,
                hard_cap=70,
                details={
                    "critical_claims": explicit_total,
                    "same_source_ae_passed": explicit_passed,
                    "achievement": explicit_achievement,
                },
            )

'''
    text = _literal_once(text, anchor, achievement, "FinalQualityGate non-vacuous achievement")

    text = _literal_once(
        text,
        '''        access_depth_mismatch = _as_int(quality_context.get("access_depth_mismatches"))
        state.check("access_depth_labels_accurate", access_depth_mismatch == 0)
''',
        '''        mismatch_value = quality_context.get("access_depth_mismatch_count")
        if mismatch_value is None:
            raw_mismatches = quality_context.get("access_depth_mismatches")
            access_depth_mismatch = (len(raw_mismatches)
                                     if isinstance(raw_mismatches, list)
                                     else _as_int(raw_mismatches))
        else:
            access_depth_mismatch = _as_int(mismatch_value)
        state.check("access_depth_labels_accurate", access_depth_mismatch == 0)
''',
        "FinalQualityGate mismatch count",
    )

    text = _literal_once(
        text,
        '''        evidence_spans = quality_context.get("critical_claim_evidence_spans")
        spans_present = _as_bool(quality_context.get("critical_claim_spans_complete")) or (
            isinstance(evidence_spans, list) and bool(evidence_spans)
        )
''',
        '''        evidence_spans = quality_context.get("critical_claim_evidence_spans")
        spans_complete_flag = quality_context.get("critical_claim_spans_complete")
        if spans_complete_flag is None:
            spans_present = isinstance(evidence_spans, list) and bool(evidence_spans)
        else:
            spans_present = _as_bool(spans_complete_flag)
''',
        "FinalQualityGate explicit span completeness",
    )
    return text


def main() -> int:
    originals = {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in TARGETS}
    patched = {
        TARGETS[0]: patch_claim_verification(originals[TARGETS[0]]),
        TARGETS[1]: patch_quality_producers(originals[TARGETS[1]]),
        TARGETS[2]: patch_final_quality_gate(originals[TARGETS[2]]),
    }
    for rel, new_text in patched.items():
        if new_text == originals[rel]:
            raise RuntimeError(f"{rel}: patch produced no change")
    for rel, new_text in patched.items():
        (ROOT / rel).write_text(new_text, encoding="utf-8", newline="\n")
    print("P0-A patch applied to:")
    for rel in TARGETS:
        print(f"  - {rel}")
    print("No thresholds were changed. Run focused tests before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
