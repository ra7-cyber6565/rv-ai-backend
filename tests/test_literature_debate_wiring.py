from research_engine.literature_debate_wiring import (
    apply_literature_debate_wiring,
    build_literature_debate_packet,
    install,
)
from research_engine.models import ResearchResult


def _source(source_id, domain, *, relevance=0.8, retracted=False, snippet=None):
    return {
        "source_id": source_id,
        "title": f"Study {source_id}",
        "url": f"https://{domain}/paper/{source_id}",
        "domain": domain,
        "snippet": snippet or f"independent text {source_id}",
        "doi": "",
        "relevance_score": relevance,
        "reading_level": "abstract",
        "peer_reviewed": True,
        "retracted": retracted,
    }


def _contradiction(a="S1", b="S2", *, valid=True, opposite=True, schema=True):
    return {
        "kind": "STANCE",
        "valid": valid,
        "schema_complete": schema,
        "opposing_direction": opposite,
        "normalized_proposition": "intervention changes measured outcome",
        "source_ids": [a, b],
        "source_a_claim": "The intervention significantly improves the measured outcome.",
        "source_b_claim": "The intervention shows no significant improvement in the measured outcome.",
        "evidence_span_refs": [f"{a} page 4", f"{b} page 7"],
    }


def test_valid_structured_opposition_becomes_unresolved_debate():
    packet = build_literature_debate_packet({
        "sources": [_source("S1", "a.example"), _source("S2", "b.example")],
        "contradictions": [_contradiction()],
    })
    assert packet["ran"] is True
    assert packet["status"] == "AUDITED"
    assert packet["accepted_contradictions"] == 1
    assert packet["proposition_count"] == 1
    debate = packet["debates"][0]
    assert debate["status"] == "DISPUTED_UNRESOLVED"
    assert debate["eligible_components"] == 2
    assert debate["cross_examinations"]
    assert packet["consensus_proves_truth"] is False
    assert packet["independent_validation_proven"] is False


def test_invalid_or_nonopposing_contradictions_are_not_invented_as_debate():
    packet = build_literature_debate_packet({
        "sources": [_source("S1", "a.example"), _source("S2", "b.example")],
        "contradictions": [
            _contradiction(valid=False),
            _contradiction(opposite=False),
            _contradiction(schema=False),
        ],
    })
    assert packet["status"] == "NO_EXPLICIT_OPPOSING_LITERATURE"
    assert packet["accepted_contradictions"] == 0
    assert packet["skipped_contradictions"] == 3
    assert packet["debates"] == []


def test_missing_source_metadata_fails_closed_instead_of_creating_ghost_position():
    packet = build_literature_debate_packet({
        "sources": [_source("S1", "a.example")],
        "contradictions": [_contradiction()],
    })
    assert packet["status"] == "NO_EXPLICIT_OPPOSING_LITERATURE"
    assert packet["accepted_contradictions"] == 0


def test_same_domain_is_conservatively_one_independence_family():
    packet = build_literature_debate_packet({
        "sources": [
            _source("S1", "same.example", snippet="different text A"),
            _source("S2", "same.example", snippet="different text B"),
        ],
        "contradictions": [_contradiction()],
    })
    debate = packet["debates"][0]
    assert debate["effective_components"] == 2
    # Components remain position-specific for audit, but neither pair is
    # independently validated by this software packet; the top-level boundary
    # is always explicit.
    assert packet["independent_validation_proven"] is False


def test_retracted_side_cannot_be_eligible_strong_component():
    packet = build_literature_debate_packet({
        "sources": [
            _source("S1", "a.example"),
            _source("S2", "b.example", retracted=True),
        ],
        "contradictions": [_contradiction()],
    })
    debate = packet["debates"][0]
    assert debate["eligible_components"] == 1
    assert debate["status"] == "INSUFFICIENT_INDEPENDENT_EVIDENCE"


def test_low_relevance_snippet_side_does_not_become_usable_literature():
    weak = _source("S2", "b.example", relevance=0.05)
    weak["reading_level"] = "snippet"
    packet = build_literature_debate_packet({
        "sources": [_source("S1", "a.example"), weak],
        "contradictions": [_contradiction()],
    })
    assert packet["debates"][0]["eligible_components"] == 1


def test_apply_wiring_never_upgrades_result_status_answer_or_evidence():
    original = {
        "answer": "bounded answer",
        "status": "PARTIAL",
        "evidence_level": "MIXED",
        "coverage": {"existing": {"kept": True}},
        "sources": [_source("S1", "a.example"), _source("S2", "b.example")],
        "contradictions": [_contradiction()],
    }
    result = apply_literature_debate_wiring(original)
    assert result["answer"] == "bounded answer"
    assert result["status"] == "PARTIAL"
    assert result["evidence_level"] == "MIXED"
    assert result["coverage"]["existing"] == {"kept": True}
    assert result["coverage"]["literature_debate"]["truth_proven"] is False


def test_real_research_result_serialization_contains_literature_debate_packet():
    install()
    result = ResearchResult(
        question="q",
        answer="a",
        status="PARTIAL",
        evidence_level="MIXED",
        sources=[_source("S1", "a.example"), _source("S2", "b.example")],
        contradictions=[_contradiction()],
    ).to_dict()
    packet = result["coverage"]["literature_debate"]
    assert packet["ran"] is True
    assert packet["accepted_contradictions"] == 1
    assert packet["truth_proven"] is False
    assert packet["independent_validation_proven"] is False
    assert result["status"] == "PARTIAL"


def test_install_is_idempotent():
    from research_engine import result_coverage_gate

    before = result_coverage_gate.enforce
    install()
    after_first = result_coverage_gate.enforce
    install()
    after_second = result_coverage_gate.enforce
    assert before is after_first
    assert after_first is after_second
