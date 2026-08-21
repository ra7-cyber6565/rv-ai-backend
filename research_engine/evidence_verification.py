"""Stricter A-E evidence-verification facade.

The detailed deterministic checks live in ``evidence_verification_legacy.py``.
This facade closes an important multi-source loophole: evidence dimensions may
not be mixed across different citations. A high-quality source that does not
support the claim cannot rescue a low-quality source that does support it.

The A-E chain is therefore cumulative on the SAME cited source:
A citation valid -> B relevant -> C supports claim -> D enough access depth ->
E enough quality/not retracted.
"""
from __future__ import annotations

from typing import Optional

from .evidence_verification_legacy import *  # noqa: F401,F403
from .evidence_verification_legacy import EvidenceVerifier as _BaseEvidenceVerifier


def _joint_state(rows, keys) -> Optional[bool]:
    """True if one row passes every key; None if one could; else False."""
    if any(all(row.get(key) is True for key in keys) for row in rows):
        return True
    if any(all(row.get(key) is not False for key in keys) for row in rows):
        return None
    return False


class EvidenceVerifier(_BaseEvidenceVerifier):
    """Run base checks, then enforce same-source cumulative A-E grounding."""

    def verify(self, answer, pack):
        report = super().verify(answer, pack)
        report.passed_claims = 0
        report.uncertain_claims = 0
        report.failed_claims = 0

        for item in report.items:
            rows = list(item.source_checks or [])
            if item.citation is not True:
                item.relevance = False
                item.support = False
                item.depth = False
                item.quality = False
            else:
                item.relevance = _joint_state(rows, ("relevance",))
                item.support = _joint_state(rows, ("relevance", "support"))
                item.depth = _joint_state(rows, ("relevance", "support", "depth"))
                item.quality = _joint_state(
                    rows, ("relevance", "support", "depth", "quality")
                )

            states = [item.citation, item.relevance, item.support, item.depth, item.quality]
            if all(value is True for value in states):
                item.verdict = "verified_against_available_evidence"
                item.note = (
                    "Ek hi cited source ne relevance, available-text support, depth aur "
                    "quality ke cumulative A-E gate ko pass kiya."
                )
                report.passed_claims += 1
            elif any(value is False for value in states):
                item.verdict = "failed_evidence_gate"
                failed = [name for name, value in (
                    ("citation", item.citation),
                    ("relevance", item.relevance),
                    ("support", item.support),
                    ("depth", item.depth),
                    ("quality", item.quality),
                ) if value is False]
                item.note = "Fail: " + ", ".join(failed)
                report.failed_claims += 1
            else:
                item.verdict = "uncertain_needs_deeper_check"
                item.note = (
                    "A-E ke kuch cumulative steps abhi uncertain hain; alag-alag "
                    "sources ke passes ko jodkar fake verification nahi banayi gayi."
                )
                report.uncertain_claims += 1

        def aggregate(attr):
            if not report.items:
                return None
            values = [getattr(item, attr) for item in report.items]
            if any(value is False for value in values):
                return False
            if any(value is None for value in values):
                return None
            return True

        report.checks = {
            "A_citation": aggregate("citation"),
            "B_relevance": aggregate("relevance"),
            "C_support": aggregate("support"),
            "D_depth": aggregate("depth"),
            "E_quality": aggregate("quality"),
        }
        report.gate_passed = bool(report.items) and all(
            item.verdict == "verified_against_available_evidence"
            for item in report.items
        )
        if report.items:
            if report.gate_passed:
                report.note = (
                    f"{report.claims_checked}/{report.claims_checked} labelled factual/evidence "
                    "claims ne same-source cumulative A-E gate pass kiya."
                )
            else:
                report.note = (
                    f"{report.claims_checked} claims check hui: {report.passed_claims} pass, "
                    f"{report.uncertain_claims} uncertain, {report.failed_claims} fail. "
                    "A-E dimensions ko alag-alag citations se mix karke verification nahi banayi gayi."
                )
        return report
