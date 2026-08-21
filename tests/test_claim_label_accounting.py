"""Claim-label audit counters must describe what actually ran."""
from __future__ import annotations

from research_engine.claim_labels import downgrade
from research_engine.models import EvidencePack, SourceRecord, SourceType


def _source(sid: str, level: str, snippet: str) -> SourceRecord:
    source = SourceRecord(
        title="Urban density and car travel",
        url=f"https://example.org/{sid.lower()}",
        snippet=snippet,
        source_type=SourceType.PAPER,
        peer_reviewed=True,
        read_level=level,
        relevance_score=0.9,
        quality_score=0.8,
    )
    source.source_id = sid
    if level == "full_text":
        source.full_text_chars = max(500, len(snippet))
    return source


def test_abstract_depth_downgrade_is_not_reported_as_AE_failure():
    source = _source(
        "S1",
        "abstract",
        "Higher urban density reduces per-capita car travel in the analysis.",
    )
    pack = EvidencePack(
        question="Does higher urban density reduce per-capita car travel?",
        sources=[source],
        topic_terms=["urban", "density", "car", "travel"],
    )
    text, report = downgrade(
        "[FACT] Higher urban density reduces per-capita car travel [S1].",
        pack,
        check_entailment=True,
    )
    assert "[SOURCE-REPORTED]" in text
    assert report["a_e_checked"] == 0
    assert report["a_e_failed"] == 0
    assert report["entailment_blocked"] == 0
    assert "source access depth" in report["note"]


def test_fulltext_support_failure_is_reported_as_AE_failure():
    source = _source(
        "S1",
        "full_text",
        "Higher urban density reduces per-capita car travel in the analysis.",
    )
    pack = EvidencePack(
        question="Does higher urban density reduce per-capita car travel?",
        sources=[source],
        topic_terms=["urban", "density", "car", "travel"],
    )
    text, report = downgrade(
        "[FACT] Higher urban density increases per-capita car travel [S1].",
        pack,
        check_entailment=True,
    )
    assert "[UNVERIFIED]" in text
    assert report["a_e_checked"] == 1
    assert report["a_e_failed"] == 1
    assert report["entailment_blocked"] == 1
    assert "A-E support" in report["note"]


if __name__ == "__main__":
    test_abstract_depth_downgrade_is_not_reported_as_AE_failure()
    test_fulltext_support_failure_is_reported_as_AE_failure()
    print("claim-label accounting: PASS")
