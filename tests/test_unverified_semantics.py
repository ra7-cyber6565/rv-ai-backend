"""UNVERIFIED must remain distinct from creative speculation and top grades."""
from __future__ import annotations

from research_engine.evidence import EvidenceEngine
from research_engine.models import (
    Claim,
    ClaimType,
    EvidencePack,
    SourceRecord,
    SourceType,
    label_to_claim_type,
)


def _strong_pack() -> EvidencePack:
    sources = []
    for index in range(3):
        source = SourceRecord(
            source_id=f"S{index + 1}",
            title=f"Peer reviewed urban study {index + 1}",
            url=f"https://example.org/{index + 1}",
            snippet="Higher urban density reduces per-capita car travel.",
            connector="openalex",
            source_type=SourceType.PAPER,
            peer_reviewed=True,
            doi=f"10.1/{index + 1}",
            read_level="full_text",
            full_text_chars=5000,
            relevance_score=0.9,
            quality_score=0.9,
        )
        sources.append(source)
    return EvidencePack(
        question="Does urban density reduce car travel?",
        sources=sources,
        topic_terms=["urban", "density", "car", "travel"],
        reasoning_planned=2,
        reasoning_done=2,
    )


def test_unverified_label_has_explicit_non_speculation_internal_type():
    assert label_to_claim_type("[UNVERIFIED]") is ClaimType.UNVERIFIED
    assert label_to_claim_type("[UNVERIFIED]") is not ClaimType.SPECULATION


def test_unverified_serialization_stays_compatible_with_old_enum_consumers():
    payload = Claim("Unproven factual statement", ClaimType.UNVERIFIED, ["S1"]).to_dict()
    assert payload["claim_type"] == ClaimType.UNKNOWN.value
    assert payload["claim_state"] == ClaimType.UNVERIFIED.value
    assert payload["grounded"] is True


def test_evidence_table_counts_unverified_separately_from_speculation():
    table = EvidenceEngine().evidence_table([
        Claim("unverified", ClaimType.UNVERIFIED, ["S1"]),
        Claim("speculation", ClaimType.SPECULATION, []),
    ])
    assert table["by_type"]["UNVERIFIED"] == 1
    assert table["by_type"]["SPECULATION"] == 1


def test_failed_AE_claim_blocks_source_count_verified_grade():
    grade = EvidenceEngine().grade_evidence(
        _strong_pack(),
        label_report={"a_e_failed": 1, "entailment_blocked": 1},
        claim_checks={
            "total_claims": 1,
            "genuine_support": 0,
            "source_reported": 0,
            "cited_only": 1,
            "unsupported": 0,
            "entailment_not_checkable": 0,
            "overclaims": [{"claim": "bad conclusion"}],
        },
    )
    assert "VERIFIED" not in grade
    assert "STRONG" not in grade
    assert "MIXED" in grade
    assert "A-E" in grade


def test_source_reported_claim_blocks_top_grade_but_all_genuine_claims_allow_it():
    engine = EvidenceEngine()
    mixed = engine.grade_evidence(
        _strong_pack(),
        label_report={},
        claim_checks={
            "total_claims": 2,
            "genuine_support": 1,
            "source_reported": 1,
            "cited_only": 0,
            "unsupported": 0,
            "entailment_not_checkable": 0,
            "overclaims": [],
        },
    )
    assert "VERIFIED" not in mixed and "STRONG" not in mixed

    top = engine.grade_evidence(
        _strong_pack(),
        label_report={},
        claim_checks={
            "total_claims": 2,
            "genuine_support": 2,
            "source_reported": 0,
            "cited_only": 0,
            "unsupported": 0,
            "entailment_not_checkable": 0,
            "overclaims": [],
        },
    )
    assert "VERIFIED" in top or "STRONG" in top
