"""Offline regression tests for claim-level evidence verification A-E."""
from __future__ import annotations

from research_engine.evidence_verification import EvidenceVerifier
from research_engine.models import EvidencePack, SourceRecord, SourceType
from research_engine.verification import VerificationEngine


def _source(*, snippet: str, read_level: str = "full_text", relevance: float = 0.9,
            quality: float = 0.8, retracted: bool = False, source_id: str = "S1",
            year: int | None = None) -> SourceRecord:
    s = SourceRecord(
        title="Urban density and car travel",
        url="https://example.org/paper",
        snippet=snippet,
        source_type=SourceType.PAPER,
        peer_reviewed=True,
        read_level=read_level,
        relevance_score=relevance,
        quality_score=quality,
        retracted=retracted,
        year=year,
    )
    s.source_id = source_id
    s.full_text_chars = len(snippet) if read_level == "full_text" else 0
    return s


def _pack(source: SourceRecord) -> EvidencePack:
    return EvidencePack(
        question="Does higher urban density reduce per-capita car travel?",
        sources=[source],
        topic_terms=["urban", "density", "car", "travel"],
    )


def test_strong_fact_passes_only_when_citation_relevance_support_depth_and_quality_pass():
    source = _source(
        snippet="Higher urban density reduces per-capita car travel by 30 percent in the studied cities."
    )
    answer = "[FACT] Higher urban density reduces per-capita car travel by 30% [S1]."
    report = EvidenceVerifier().verify(answer, _pack(source))
    assert report.claims_checked == 1
    assert report.gate_passed is True
    assert report.passed_claims == 1
    assert all(value is True for value in report.checks.values())


def test_percent_word_and_percent_symbol_are_normalized():
    source = _source(snippet="Car travel fell by 30 percent with higher urban density.")
    report = EvidenceVerifier().verify(
        "[FACT] Higher urban density was linked to 30% lower car travel [S1].",
        _pack(source),
    )
    assert report.items[0].source_checks[0]["numeric_match"] is True


def test_publication_year_in_structured_metadata_does_not_false_fail_numeric_gate():
    source = _source(
        snippet="Higher urban density reduces per-capita car travel in the reported analysis.",
        year=2021,
    )
    report = EvidenceVerifier().verify(
        "[FACT] A 2021 study reports lower per-capita car travel with higher urban density [S1].",
        _pack(source),
    )
    assert report.items[0].source_checks[0]["numeric_match"] is True


def test_valid_citation_does_not_hide_wrong_numeric_claim():
    source = _source(
        snippet="Higher urban density reduces per-capita car travel by 30 percent in the studied cities."
    )
    answer = "[FACT] Higher urban density reduces per-capita car travel by 100% [S1]."
    report = EvidenceVerifier().verify(answer, _pack(source))
    assert report.gate_passed is False
    assert report.items[0].citation is True
    assert report.items[0].support is False
    assert report.checks["C_support"] is False


def test_obvious_direction_reversal_fails_support_even_with_same_keywords():
    source = _source(
        snippet="Higher urban density reduces and lowers per-capita car travel in the studied cities."
    )
    report = EvidenceVerifier().verify(
        "[FACT] Higher urban density increases per-capita car travel [S1].",
        _pack(source),
    )
    assert report.items[0].support is False
    assert report.gate_passed is False


def test_hinglish_paraphrase_with_shared_technical_terms_is_not_blindly_rejected():
    source = _source(
        snippet="Higher urban density reduces per-capita car travel in the reported analysis."
    )
    report = EvidenceVerifier().verify(
        "[FACT] Urban density badhne par per-capita car travel kam hota hai [S1].",
        _pack(source),
    )
    assert report.items[0].support is not False


def test_off_topic_source_with_real_id_fails_relevance_and_support_gate():
    source = _source(
        snippet="Maternal mortality fell after expansion of obstetric care in rural hospitals.",
        relevance=0.0,
    )
    answer = "[FACT] Higher urban density reduces per-capita car travel [S1]."
    report = EvidenceVerifier().verify(answer, _pack(source))
    assert report.gate_passed is False
    assert report.items[0].citation is True
    assert report.items[0].relevance is False
    assert report.items[0].support is False


def test_strong_fact_on_abstract_is_not_full_depth_verified():
    source = _source(
        snippet="Higher urban density reduces per-capita car travel in the reported analysis.",
        read_level="abstract",
    )
    answer = "[FACT] Higher urban density reduces per-capita car travel [S1]."
    report = EvidenceVerifier().verify(answer, _pack(source))
    assert report.gate_passed is False
    assert report.items[0].depth is False
    assert report.checks["D_depth"] is False


def test_source_reported_claim_can_use_abstract_but_not_metadata_only():
    abstract_source = _source(
        snippet="Higher urban density reduces per-capita car travel in the reported analysis.",
        read_level="abstract",
    )
    answer = "[SOURCE-REPORTED] Higher urban density reduces per-capita car travel [S1]."
    abstract_report = EvidenceVerifier().verify(answer, _pack(abstract_source))
    assert abstract_report.items[0].depth is True

    metadata_source = _source(
        snippet="Higher urban density reduces per-capita car travel in the reported analysis.",
        read_level="metadata",
    )
    metadata_report = EvidenceVerifier().verify(answer, _pack(metadata_source))
    assert metadata_report.items[0].depth is False
    assert metadata_report.gate_passed is False


def test_low_quality_or_retracted_source_cannot_pass_quality_gate():
    low = _source(
        snippet="Higher urban density reduces per-capita car travel.",
        quality=0.1,
    )
    answer = "[FACT] Higher urban density reduces per-capita car travel [S1]."
    low_report = EvidenceVerifier().verify(answer, _pack(low))
    assert low_report.items[0].quality is False

    retracted = _source(
        snippet="Higher urban density reduces per-capita car travel.",
        quality=0.95,
        retracted=True,
    )
    retracted_report = EvidenceVerifier().verify(answer, _pack(retracted))
    assert retracted_report.items[0].quality is False
    assert retracted_report.gate_passed is False


def test_missing_or_invented_citation_fails_A_gate():
    source = _source(snippet="Higher urban density reduces per-capita car travel.")
    report = EvidenceVerifier().verify(
        "[FACT] Higher urban density reduces per-capita car travel [S99].",
        _pack(source),
    )
    assert report.items[0].citation is False
    assert report.checks["A_citation"] is False
    assert report.gate_passed is False


def test_verification_facade_downgrades_source_grounded_when_AE_gate_fails():
    source = _source(
        snippet="Higher urban density reduces per-capita car travel by 30 percent.",
        read_level="abstract",
    )
    pack = _pack(source)
    report = VerificationEngine().verify(
        "[FACT] Higher urban density reduces per-capita car travel by 30% [S1].",
        pack,
        citation_ok=True,
        ungrounded_count=0,
        cited_ids=["S1"],
    ).to_dict()
    assert report["status"] != "SOURCE GROUNDED"
    assert report["evidence_verification"]["gate_passed"] is False
    names = [row["check"] for row in report["checks"]]
    assert "Claim ke liye source enough depth tak padha gaya" in names


def test_verification_facade_keeps_source_grounded_only_after_AE_passes():
    source = _source(
        snippet="Higher urban density reduces per-capita car travel by 30 percent in the studied cities."
    )
    pack = _pack(source)
    report = VerificationEngine().verify(
        "[FACT] Higher urban density reduces per-capita car travel by 30% [S1].",
        pack,
        citation_ok=True,
        ungrounded_count=0,
        cited_ids=["S1"],
    ).to_dict()
    assert report["evidence_verification"]["gate_passed"] is True
    assert report["status"] == "SOURCE GROUNDED"
