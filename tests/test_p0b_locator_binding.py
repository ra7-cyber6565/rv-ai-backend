"""P0-B hardening: pre-draft evidence must bind source + text + exact locator."""
from __future__ import annotations

from research_engine.evidence_drafting import (
    EvidenceDraftManifest,
    EvidenceDraftSpan,
    audit_claims_against_manifest,
)

PASSAGE = (
    "Electrical resistance measurements reproducibly show that lanthanum hydride "
    "LaH10 has a superconducting transition temperature of 250 K at 170 GPa "
    "under the reported experimental conditions."
)
CANONICAL = (
    "lanthanum hydride LaH10 has a superconducting transition temperature "
    "of 250 K at 170 GPa"
)


def _span(locator: str) -> EvidenceDraftSpan:
    return EvidenceDraftSpan(
        span_id="ES001", source_id="S9", locator=locator, passage=PASSAGE,
        passage_sha256="fixture", span_kind="passage", question_match=0.9,
        source_relevance=0.9, source_quality=0.9, access_depth="full_text",
        retracted=False, is_patent=False, strong_claim_eligible=True,
        eligibility_reasons=[],
        eligibility_checks={"B": "pass", "D": "pass", "E": "pass"},
        passage_provenance="full_text", read_level_at_capture="full_text",
    )


def _verification(locator: str) -> dict:
    return {"critical_claim_spans": [{
        "claim_id": "CL001",
        "same_source_ae_passed": True,
        "supporting_source_id": "S9",
        "canonical_span": {
            "source_id": "S9", "locator": locator, "passage": CANONICAL,
        },
    }]}


def test_same_text_same_source_but_different_locator_fails_preselection():
    manifest = EvidenceDraftManifest(question="fixture", spans=[_span("p.42 ¶3")])
    audit = audit_claims_against_manifest(_verification("p.77 ¶1"), manifest)
    assert audit["critical_claims_preselected_span_matched"] == 0
    assert audit["critical_claims_preselected_span_unmatched"] == 1
    assert audit["critical_claim_preselection_complete"] is False
    assert audit["evidence_first_achievement"] is False


def test_same_text_same_source_same_locator_passes_preselection():
    manifest = EvidenceDraftManifest(question="fixture", spans=[_span("p.42 ¶3")])
    audit = audit_claims_against_manifest(_verification("p.42 ¶3"), manifest)
    assert audit["critical_claims_preselected_span_matched"] == 1
    assert audit["critical_claims_preselected_span_unmatched"] == 0
    assert audit["critical_claim_preselection_complete"] is True
    assert audit["evidence_first_achievement"] is True
    assert audit["claim_matches"][0]["preselected_span_id"] == "ES001"
