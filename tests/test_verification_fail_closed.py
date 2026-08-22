"""No A-E claim parsed must never silently count as source verification."""
from __future__ import annotations

from research_engine.models import EvidencePack, SourceRecord, SourceType
from research_engine.verification import VerificationEngine


def _pack() -> EvidencePack:
    source = SourceRecord(
        title="Urban density and car travel",
        url="https://example.org/paper",
        snippet="Higher urban density reduces per-capita car travel in the studied cities.",
        source_type=SourceType.PAPER,
        peer_reviewed=True,
        read_level="full_text",
        relevance_score=0.9,
        quality_score=0.9,
    )
    source.source_id = "S1"
    source.full_text_chars = len(source.snippet)
    return EvidencePack(
        question="Does higher urban density reduce per-capita car travel?",
        sources=[source],
        topic_terms=["urban", "density", "car", "travel"],
    )


def test_unlabelled_cited_sentence_cannot_be_source_grounded_when_AE_did_not_run():
    report = VerificationEngine().verify(
        "Higher urban density reduces per-capita car travel [S1].",
        _pack(),
        citation_ok=True,
        ungrounded_count=0,
        cited_ids=["S1"],
    ).to_dict()

    assert report["evidence_verification"]["claims_checked"] == 0
    assert report["evidence_verification"]["gate_passed"] is False
    assert report["status"] == "UNVERIFIABLE HERE"
    warning = " ".join(report["warnings"]).lower()
    assert "claim-level evidence verification" in warning
    assert "apply nahi ho saki" in warning


def test_zero_claim_AE_does_not_erase_independent_arithmetic_verification():
    report = VerificationEngine().verify(
        "2 + 2 = 4",
        _pack(),
        citation_ok=True,
        ungrounded_count=0,
        cited_ids=[],
    ).to_dict()

    assert report["evidence_verification"]["claims_checked"] == 0
    assert report["status"] == "COMPUTATIONALLY VERIFIED"
    assert any(
        check["check"] == "2 + 2" and check["passed"] is True
        for check in report["checks"]
    )
