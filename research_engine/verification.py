"""Integrated verification facade: computational checks + A-E + capture integrity.

A-E remain citation/relevance/support/depth/source-quality checks. Transformed
text adds a separate F_capture_integrity check for OCR/translation provenance.
A valid citation or A-E pass cannot by itself make weak transformed text
SOURCE GROUNDED.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .evidence_verification import EvidenceVerifier
from .verification_claude import Check
from .verification_claude import VerificationReport as _ClaudeVerificationReport
from .verification_claude import VerificationEngine as _ClaudeVerificationEngine


@dataclass
class VerificationReport(_ClaudeVerificationReport):
    evidence_verification: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        data = super().to_dict()
        data["evidence_verification"] = self.evidence_verification
        return data


class VerificationEngine(_ClaudeVerificationEngine):
    """Computational/physics checks + cumulative same-source evidence gate."""

    def __init__(self):
        super().__init__()
        self.evidence_verifier = EvidenceVerifier()

    @staticmethod
    def _check_detail(name: str, state: Optional[bool], evidence: Dict) -> str:
        checked = int(evidence.get("claims_checked") or 0)
        passed = int(evidence.get("passed_claims") or 0)
        uncertain = int(evidence.get("uncertain_claims") or 0)
        failed = int(evidence.get("failed_claims") or 0)
        if state is True:
            return f"{checked} labelled factual/evidence claim(s) mein ye check pass hua."
        if state is False:
            return (
                f"Claim-level evidence gate mein problem mili: {passed} pass, "
                f"{uncertain} uncertain, {failed} fail."
            )
        return (
            f"Is check ko pakka pass/fail bolne layak claim-level data nahi mila "
            f"({checked} claim(s) check hui)."
        )

    def verify(
        self,
        answer: str,
        pack,
        citation_ok: bool = True,
        ungrounded_count: int = 0,
        hypotheses: Optional[List[Dict]] = None,
        cited_ids: Optional[List[str]] = None,
        question: str = "",
    ) -> VerificationReport:
        base = super().verify(
            answer,
            pack,
            citation_ok=citation_ok,
            ungrounded_count=ungrounded_count,
            hypotheses=hypotheses,
            cited_ids=cited_ids,
            question=question,
        )
        ev = self.evidence_verifier.verify(answer, pack).to_dict()
        report_checks: List[Check] = []
        arithmetic_name = re.compile(
            r"^(\d[\d,]*(?:\.\d+)?)\s*([+\-*x×/])\s*"
            r"(\d[\d,]*(?:\.\d+)?)\s*=\s*\d[\d,]*(?:\.\d+)?$"
        )
        for check in base.checks:
            match = arithmetic_name.match(str(check.name or ""))
            if match:
                a, op, b = match.groups()
                report_checks.append(Check(f"{a} {op} {b}", check.passed, check.detail))
            else:
                report_checks.append(check)
        report = VerificationReport(
            status=base.status,
            checks=report_checks,
            warnings=list(base.warnings),
            required_tests=list(base.required_tests),
            statistics=dict(base.statistics),
            data_for_verification=list(base.data_for_verification),
            limits=list(base.limits),
            physics=dict(getattr(base, "physics", {}) or {}),
            evidence_verification=ev,
        )

        mapping = [
            ("A_citation", "Claim ke citations asli source se match karte hain"),
            ("B_relevance", "Cited source sawal se relevant hai"),
            ("C_support", "Claim cited text/excerpt se support hoti hai"),
            ("D_depth", "Claim ke liye source enough depth tak padha gaya"),
            ("E_quality", "Supporting source ki quality evidence ke layak hai"),
            ("F_capture_integrity", "OCR/translation capture integrity strong-claim use ke layak hai"),
        ]
        states = ev.get("checks") or {}
        for key, human_name in mapping:
            state = states.get(key)
            report.checks.append(
                Check(human_name, state, self._check_detail(key, state, ev))
            )

        claims_checked = int(ev.get("claims_checked") or 0)
        gate_passed = bool(ev.get("gate_passed"))

        if claims_checked == 0:
            if report.status == "SOURCE GROUNDED":
                report.status = "UNVERIFIABLE HERE"
            report.warnings.append(
                "Claim-level A-E + capture-integrity verification apply nahi ho saki "
                "kyunki koi labelled factual/evidence claim detect nahi hui. Valid "
                "citation ID ko akela source verification nahi maana gaya."
            )
        elif not gate_passed:
            report.warnings.append(
                "Valid citation IDs mile, lekin same-source A-E aur separate "
                "capture-integrity gate poori pass nahi hui. Isliye answer ko fully "
                "source-verified nahi maana gaya."
            )
            if report.status == "SOURCE GROUNDED":
                report.status = "UNVERIFIABLE HERE"
            elif report.status == "COMPUTATIONALLY VERIFIED":
                report.status = "COMPUTATIONALLY VERIFIED (partial)"
        elif report.status in {"UNVERIFIABLE HERE", "LOGICALLY CONSISTENT"}:
            report.status = "SOURCE GROUNDED"

        return report


__all__ = ["Check", "VerificationReport", "VerificationEngine"]
