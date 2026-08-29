"""Add capture/transformation integrity as an explicit sixth evidence gate.

A-E retain their existing meanings. F answers a separate question: was the
exact text capture/transformation (OCR/translation) trustworthy enough for
unattended verified support? F may only downgrade/block; it never upgrades A-E
or source truth.
"""
from __future__ import annotations

from typing import Mapping

from .capture_integrity_wiring import _capture_gate
from .semantic import similarity


_INSTALLED = False


def _best_passage_gate(pack, source_id: str, claim: str):
    best = None
    best_score = -1.0
    for passage in getattr(pack, "passages", []) or []:
        if getattr(passage, "source_id", "") != source_id:
            continue
        text = str(getattr(passage, "text", "") or "").strip()
        if not text:
            continue
        score = float(similarity(claim, text))
        if score > best_score:
            best_score = score
            best = passage
    if best is None:
        return {
            "status": "unknown",
            "blocks_strong_claim": False,
            "reason": "no exact Passage capture metadata available",
        }
    span = {
        "locator": str(getattr(best, "locator", "") or ""),
        "passage_provenance": str(getattr(best, "provenance", "") or ""),
        "extraction_integrity": dict(
            getattr(best, "extraction_integrity", {}) or {}
        ),
    }
    gate = dict(_capture_gate(span))
    gate["selected_passage_match"] = round(max(best_score, 0.0), 4)
    gate["selected_locator"] = span["locator"]
    return gate


def _row_ae_passes(row: Mapping[str, object]) -> bool:
    return all(row.get(key) is True for key in ("relevance", "support", "depth", "quality"))


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from . import evidence_verification as ev_mod

    original_verify = ev_mod.EvidenceVerifier.verify

    def verify_with_capture(self, answer, pack):
        report = original_verify(self, answer, pack)

        for item in report.items:
            for row in item.source_checks:
                gate = _best_passage_gate(pack, str(row.get("source_id") or ""), item.claim)
                row["capture_integrity"] = gate
                row["capture_integrity_passed"] = not bool(gate.get("blocks_strong_claim"))
                row["passes_verified_support"] = (
                    _row_ae_passes(row) and row["capture_integrity_passed"]
                )

            verified_paths = [row for row in item.source_checks
                              if row.get("passes_verified_support") is True]
            ae_paths = [row for row in item.source_checks if _row_ae_passes(row)]
            item.capture_integrity = True if verified_paths else (
                False if ae_paths else None
            )
            if ae_paths and not verified_paths:
                item.verdict = "failed_evidence_gate"
                reasons = [
                    str((row.get("capture_integrity") or {}).get("reason") or "capture review required")
                    for row in ae_paths
                ]
                item.note = "Fail: capture_integrity — " + "; ".join(reasons[:2])

        report.passed_claims = sum(
            1 for item in report.items
            if item.verdict == "verified_against_available_evidence"
            and getattr(item, "capture_integrity", None) is True
        )
        report.failed_claims = sum(
            1 for item in report.items if item.verdict == "failed_evidence_gate"
        )
        report.uncertain_claims = max(
            0, report.claims_checked - report.passed_claims - report.failed_claims
        )

        captures = [getattr(item, "capture_integrity", None) for item in report.items]
        if not captures:
            f_state = None
        elif any(value is False for value in captures):
            f_state = False
        elif any(value is None for value in captures):
            f_state = None
        else:
            f_state = True
        report.checks["F_capture_integrity"] = f_state
        report.gate_passed = bool(report.items) and all(
            item.verdict == "verified_against_available_evidence"
            and getattr(item, "capture_integrity", None) is True
            for item in report.items
        )
        if report.items and not report.gate_passed:
            report.note = (
                f"{report.claims_checked} claims check hui: {report.passed_claims} pass, "
                f"{report.uncertain_claims} uncertain, {report.failed_claims} fail. "
                "A-E dimensions ko alag-alag citations se mix karke verification "
                "nahi banayi gayi; same-source A-E ke saath separate capture-integrity "
                "F gate bhi required hai."
            )
        return report

    original_item_to_dict = ev_mod.ClaimEvidenceResult.to_dict

    def item_to_dict_with_capture(self):
        payload = original_item_to_dict(self)
        payload["capture_integrity"] = getattr(self, "capture_integrity", None)
        return payload

    ev_mod.EvidenceVerifier.verify = verify_with_capture
    ev_mod.ClaimEvidenceResult.to_dict = item_to_dict_with_capture
