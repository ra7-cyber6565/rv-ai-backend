"""Strong labels need claim-level A-E verification, not just any full-text cite."""
from __future__ import annotations

from research_engine.claim_labels import downgrade
from research_engine.models import EvidencePack, SourceRecord, SourceType


def _source(
    sid: str,
    *,
    snippet: str,
    level: str = "full_text",
    relevance: float = 0.9,
    quality: float = 0.8,
) -> SourceRecord:
    source = SourceRecord(
        title="Urban density and car travel",
        url=f"https://example.org/{sid.lower()}",
        snippet=snippet,
        source_type=SourceType.PAPER,
        peer_reviewed=True,
        read_level=level,
        relevance_score=relevance,
        quality_score=quality,
    )
    source.source_id = sid
    if level == "full_text":
        source.full_text_chars = max(500, len(snippet))
    return source


def _pack(*sources: SourceRecord) -> EvidencePack:
    return EvidencePack(
        question="Does higher urban density reduce per-capita car travel?",
        sources=list(sources),
        topic_terms=["urban", "density", "car", "travel"],
    )


def test_established_survives_only_when_same_fulltext_source_passes_A_to_E():
    source = _source(
        "S1",
        snippet="Higher urban density reduces per-capita car travel in the studied cities.",
    )
    text, report = downgrade(
        "[ESTABLISHED] Higher urban density reduces per-capita car travel [S1].",
        _pack(source),
    )
    assert "[ESTABLISHED]" in text
    assert report["a_e_checked"] == 1
    assert report["a_e_failed"] == 0
    assert report["downgraded"] == 0


def test_unrelated_fulltext_citation_cannot_keep_established_label():
    source = _source(
        "S1",
        snippet="Maternal mortality fell after expansion of obstetric services in rural hospitals.",
        relevance=0.0,
    )
    text, report = downgrade(
        "[ESTABLISHED] Higher urban density reduces per-capita car travel [S1].",
        _pack(source),
    )
    assert "[ESTABLISHED]" not in text
    assert "[UNVERIFIED]" in text
    assert report["a_e_failed"] == 1


def test_fulltext_unrelated_plus_abstract_support_cannot_mix_dimensions_to_fake_established():
    unrelated_full = _source(
        "S1",
        snippet="A clinical paper about hospital outcomes and maternal mortality.",
        relevance=0.0,
        quality=0.9,
    )
    supporting_abstract = _source(
        "S2",
        snippet="Higher urban density reduces per-capita car travel in the reported analysis.",
        level="abstract",
        relevance=0.9,
        quality=0.9,
    )
    text, report = downgrade(
        "[FACT] Higher urban density reduces per-capita car travel [S1][S2].",
        _pack(unrelated_full, supporting_abstract),
    )
    assert "[FACT]" not in text
    assert "[UNVERIFIED]" in text
    assert report["a_e_failed"] == 1


def test_low_quality_fulltext_support_does_not_keep_strong_label():
    weak = _source(
        "S1",
        snippet="Higher urban density reduces per-capita car travel.",
        quality=0.1,
    )
    text, report = downgrade(
        "[STRONG EVIDENCE] Higher urban density reduces per-capita car travel [S1].",
        _pack(weak),
    )
    assert "[STRONG EVIDENCE]" not in text
    assert "[UNVERIFIED]" in text
    assert report["a_e_failed"] == 1
