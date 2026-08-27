from __future__ import annotations

from research_engine.final_stress_hardening import _augment_for_final_gate
from research_engine.models import EvidencePack, SourceRecord, SourceType
from research_engine.specialist_lane_quality import _qualify, qualify_lane_report


def _source(
    source_id: str,
    *,
    kind: SourceType = SourceType.PAPER,
    title: str = "Relevant source",
    snippet: str = "We measured participants and report results.",
    url: str = "https://doi.org/10.0000/example",
    relevance: float = 0.8,
    quality: float = 0.8,
    read_level: str = "abstract",
    proposition=True,
    retracted=False,
    rejected_reason: str = "",
) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        source_type=kind,
        title=title,
        snippet=snippet,
        url=url,
        relevance_score=relevance,
        quality_score=quality,
        read_level=read_level,
        relevance_parts={"tests_proposition": proposition},
        retracted=retracted,
        rejected_reason=rejected_reason,
    )


def _report(lane: str, source_ids: list[str]) -> dict:
    return {
        "active": True,
        "required_lanes": [lane],
        "lanes": [{
            "key": lane,
            "label": lane,
            "rule": "test rule",
            "source_ids": list(source_ids),
            "source_count": len(source_ids),
        }],
    }


def _plan(lane: str) -> dict:
    return {"specialist": {"expected_lanes": [lane]}}


def test_low_relevance_candidate_cannot_satisfy_empirical_lane():
    source = _source("S1", relevance=0.12, proposition=False)
    out = qualify_lane_report(
        _report("empirical_science", ["S1"]),
        _plan("empirical_science"),
        EvidencePack(sources=[source]),
    )
    row = out["lanes"][0]
    assert row["candidate_source_count"] == 1
    assert row["qualified_source_count"] == 0
    assert row["qualification_status"] == "WEAK"
    assert "empirical_science" in out["weak_required_lanes"]
    assert "empirical_science" in out["missing_required_lanes"]
    reasons = row["qualification_receipts"][0]["reasons"]
    assert "RELEVANCE_BELOW_LANE_FLOOR" in reasons
    assert "PROPOSITION_MISMATCH" in reasons


def test_metadata_only_official_record_is_weak_not_coverage():
    source = _source(
        "S1",
        kind=SourceType.WEB,
        title="Declassified memorandum",
        snippet="",
        url="https://www.cia.gov/readingroom/document/example",
        read_level="metadata",
        proposition=None,
    )
    receipt = _qualify(source, "official_document_record")
    assert receipt["qualified"] is False
    assert "CONTENT_NOT_ACCESSED" in receipt["reasons"]


def test_relevant_official_snippet_can_cover_provenance_lane_without_truth_upgrade():
    source = _source(
        "S1",
        kind=SourceType.WEB,
        title="Declassified Project Stargate memorandum",
        snippet="CIA Reading Room released memorandum dated 1984 concerning Project Stargate.",
        url="https://www.cia.gov/readingroom/document/example",
        read_level="snippet",
        proposition=None,
    )
    out = qualify_lane_report(
        _report("official_document_record", ["S1"]),
        _plan("official_document_record"),
        EvidencePack(sources=[source]),
    )
    assert out["lanes"][0]["qualified_source_ids"] == ["S1"]
    assert out["missing_required_lanes"] == []
    assert out["required_lane_coverage_complete"] is True
    assert "verified" not in out["lanes"][0]["qualification_receipts"][0]
    assert "truth" not in out["lanes"][0]["qualification_receipts"][0]


def test_empirical_lane_requires_relevance_depth_quality_and_proposition_support():
    source = _source(
        "S1",
        title="Digital abstinence and sustained attention",
        snippet=(
            "We measured 420 participants in a longitudinal experiment and report "
            "sustained-attention outcomes with confidence intervals."
        ),
        read_level="abstract",
        relevance=0.86,
        quality=0.81,
        proposition=True,
    )
    receipt = _qualify(source, "empirical_science")
    assert receipt["qualified"] is True
    assert receipt["reasons"] == []


def test_retracted_empirical_paper_cannot_satisfy_required_lane():
    source = _source("S1", retracted=True)
    receipt = _qualify(source, "empirical_science")
    assert receipt["qualified"] is False
    assert "RETRACTED_SOURCE" in receipt["reasons"]


def test_empirical_abstract_that_only_mentions_topic_is_not_lane_evidence():
    source = _source(
        "S1",
        title="Attention terminology in software models",
        snippet="This paper discusses an attention mechanism for text classification.",
        relevance=0.72,
        quality=0.78,
        proposition=None,
    )
    receipt = _qualify(source, "empirical_science")
    assert receipt["qualified"] is False
    assert "PROPOSITION_NOT_CONFIRMED" in receipt["reasons"]


def test_primary_traditional_text_requires_actual_text_access_but_not_empirical_truth():
    snippet_only = _source(
        "S1",
        kind=SourceType.BOOK,
        title="Hermetic writings",
        snippet="A catalogue description of a Hermetic text.",
        url="https://archive.org/details/example",
        read_level="snippet",
        proposition=None,
    )
    read_text = _source(
        "S2",
        kind=SourceType.BOOK,
        title="Hermetic writings",
        snippet="The text presents a historical spiritual teaching.",
        url="https://archive.org/details/example2",
        read_level="full_text",
        proposition=None,
    )
    assert _qualify(snippet_only, "traditional_belief_text")["qualified"] is False
    receipt = _qualify(read_text, "traditional_belief_text")
    assert receipt["qualified"] is True
    assert receipt["tests_proposition"] is None


def test_relevance_hard_reject_always_prevents_lane_coverage():
    source = _source(
        "S1",
        rejected_reason="DOMAIN_MISMATCH: unrelated earthquake engineering paper",
    )
    receipt = _qualify(source, "empirical_science")
    assert receipt["qualified"] is False
    assert "RELEVANCE_GATE_REJECTED" in receipt["reasons"]


def test_candidate_view_remains_backward_compatible_while_completion_uses_qualified_view():
    source = _source("S1", relevance=0.10, proposition=False)
    out = qualify_lane_report(
        _report("empirical_science", ["S1"]),
        _plan("empirical_science"),
        EvidencePack(sources=[source]),
    )
    row = out["lanes"][0]
    assert row["source_ids"] == ["S1"]
    assert row["source_count"] == 1
    assert row["qualified_source_ids"] == []
    assert out["required_lane_coverage_complete"] is False


def test_weak_required_lane_blocks_evidence_first_final_completion():
    source = _source("S1", relevance=0.10, proposition=False)
    lane_report = qualify_lane_report(
        _report("empirical_science", ["S1"]),
        _plan("empirical_science"),
        EvidencePack(sources=[source]),
    )
    result = {
        "answer": "A superficially sourced answer [S1].",
        "status": "COMPLETE",
        "quality_contract": {"evidence_first_required": True},
        "requested_ledger": {"unmet": []},
        "specialist_research": lane_report,
    }
    augmented = _augment_for_final_gate(result)
    item = next(
        x for x in augmented["requested_ledger"]["unmet"]
        if x["key"] == "specialist_source_family_coverage"
    )
    assert "empirical_science" in item["got"]
    assert item["mandatory"] is True


def test_installed_report_uses_qualified_coverage_not_candidate_count():
    from research_engine import specialist_domains as sd

    question = "CIA declassified records and consciousness experiment evidence"
    plan = {
        "specialist": {
            "active": True,
            "expected_lanes": ["official_document_record", "empirical_science"],
            "profile_keys": ["declassified_intelligence", "mind_cognition"],
            "profiles": [],
            "profile_labels": [],
            "claim_boundary_rules": [],
            "hypothesis_policy": {},
            "multilingual": {},
            "official_archive_queries": [],
            "unknown_terms": [],
        }
    }
    official = _source(
        "S1",
        kind=SourceType.WEB,
        title="CIA declassified consciousness record",
        snippet="Official CIA Reading Room record concerning a consciousness study.",
        url="https://www.cia.gov/readingroom/document/example",
        read_level="snippet",
        proposition=None,
    )
    irrelevant_empirical = _source(
        "S2",
        title="Image-classifier benchmark experiment",
        snippet=(
            "We measured a large image dataset in an experiment and report "
            "classification results with statistical confidence intervals."
        ),
        relevance=0.11,
        proposition=False,
        read_level="abstract",
    )
    report = sd.build_evidence_lane_report(
        question, plan, EvidencePack(sources=[official, irrelevant_empirical])
    )
    assert "official_document_record" in report["covered_required_lanes"]
    assert "empirical_science" in report["missing_required_lanes"]
    assert "empirical_science" in report["weak_required_lanes"]
    empirical = next(row for row in report["lanes"] if row["key"] == "empirical_science")
    assert empirical["candidate_source_ids"] == ["S2"]
    assert empirical["qualified_source_ids"] == []
    assert report["required_lane_coverage_complete"] is False


def test_rendered_report_exposes_weak_candidate_instead_of_hiding_it():
    from research_engine import specialist_domains as sd

    source = _source("S1", relevance=0.10, proposition=False)
    report = qualify_lane_report(
        _report("empirical_science", ["S1"]),
        _plan("empirical_science"),
        EvidencePack(sources=[source]),
    )
    rendered = sd.render_evidence_lane_report(report)
    assert "Specialist lane quality gate" in rendered
    assert "0/1 candidate source strict lane-quality gate pass" in rendered
    assert "COMPLETE nahi karta" in rendered
