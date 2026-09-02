from research_engine.historical_context_wiring import (
    apply_historical_context_wiring,
    build_historical_context_packet,
    install,
)
from research_engine.models import ResearchResult


def _inputs():
    return {
        "events": [
            {"event_id": "E1", "label": "Decision", "when": {"earliest": 1914, "latest": 1914}}
        ],
        "sources": [
            {
                "source_id": "S-period",
                "publication_year": 1914,
                "independence_group": "G1",
                "evidence_ref": "archive:S-period",
                "position": "SUPPORT",
                "primary_source": True,
                "provenance_complete": True,
                "describes_event_id": "E1",
            },
            {
                "source_id": "S-late",
                "publication_year": 1950,
                "independence_group": "G2",
                "evidence_ref": "book:S-late",
                "position": "CHALLENGE",
                "primary_source": False,
                "provenance_complete": True,
                "describes_event_id": "E1",
            },
        ],
        "knowledge_claims": [
            {
                "claim_id": "K1",
                "actor_id": "A1",
                "statement": "The actor had documented period knowledge.",
                "knowledge_cutoff_year": 1914,
                "evidence_source_ids": ["S-period", "S-late"],
            }
        ],
        "causal_factors": [
            {
                "factor_id": "F1",
                "label": "Later policy",
                "active_when": {"earliest": 1920, "latest": 1920},
                "alleged_outcome_event_id": "E1",
            }
        ],
        "concept_claims": [
            {
                "concept_id": "C1",
                "concept": "Documented period category",
                "attribution_event_id": "E1",
                "contemporary_evidence_source_ids": ["S-period"],
            }
        ],
    }


def test_packet_audits_explicit_historical_inputs_only():
    packet = build_historical_context_packet({"historical_context_inputs": _inputs()})
    assert packet["ran"] is True
    assert packet["status"] == "AUDITED"
    assert packet["free_form_date_inference_performed"] is False
    assert packet["actor_knowledge_audits"][0]["eligible_contemporary_evidence"] == ["S-period"]
    assert packet["actor_knowledge_audits"][0]["hindsight_only_evidence"] == ["S-late"]
    assert packet["causal_chronology_audits"][0]["impossible_causal_order"] is True
    assert packet["period_concept_audits"][0]["period_concept_gate_passed"] is True
    assert packet["truth_proven"] is False
    assert packet["result_status_upgraded"] is False


def test_existing_coverage_transport_carries_structured_inputs():
    packet = build_historical_context_packet({
        "coverage": {"historical_context_inputs": _inputs()}
    })
    assert packet["status"] == "AUDITED"
    assert packet["events"][0]["event_id"] == "E1"


def test_top_level_explicit_input_has_priority_over_coverage_transport():
    packet = build_historical_context_packet({
        "historical_context_inputs": {},
        "coverage": {"historical_context_inputs": _inputs()},
    })
    assert packet["status"] == "NO_STRUCTURED_HISTORICAL_INPUTS"


def test_free_form_history_prose_does_not_trigger_invented_analysis():
    packet = build_historical_context_packet({
        "answer": "In 1914 an actor made a decision; later historians debated it.",
        "sources": [{"year": 1914, "title": "A source"}],
        "coverage": {},
    })
    assert packet["status"] == "NO_STRUCTURED_HISTORICAL_INPUTS"
    assert packet["events"] == []
    assert packet["actor_knowledge_audits"] == []
    assert packet["free_form_date_inference_performed"] is False


def test_unknown_fields_fail_closed_into_assessment_error():
    result = apply_historical_context_wiring({
        "answer": "unchanged",
        "status": "PARTIAL",
        "historical_context_inputs": {"events": [], "invented_magic": True},
        "coverage": {"existing": {"kept": True}},
    })
    packet = result["coverage"]["historical_context"]
    assert packet["ran"] is False
    assert packet["status"] == "ASSESSMENT_ERROR"
    assert packet["error"] == "ValueError"
    assert result["status"] == "PARTIAL"
    assert result["answer"] == "unchanged"
    assert result["coverage"]["existing"] == {"kept": True}


def test_invalid_nan_like_or_non_integer_year_does_not_get_coerced():
    inputs = _inputs()
    inputs["sources"][0]["publication_year"] = 1914.0
    result = apply_historical_context_wiring({
        "status": "PARTIAL",
        "coverage": {"historical_context_inputs": inputs},
    })
    assert result["coverage"]["historical_context"]["status"] == "ASSESSMENT_ERROR"
    assert result["coverage"]["historical_context"]["truth_proven"] is False


def test_apply_wiring_preserves_answer_status_and_input_ledger():
    original = {
        "answer": "Historical synthesis remains partial.",
        "status": "PARTIAL",
        "coverage": {
            "historical_context_inputs": _inputs(),
            "existing": {"kept": True},
        },
    }
    result = apply_historical_context_wiring(original)
    assert result["answer"] == original["answer"]
    assert result["status"] == "PARTIAL"
    assert result["coverage"]["existing"] == {"kept": True}
    assert result["coverage"]["historical_context_inputs"] == _inputs()
    assert result["coverage"]["historical_context"]["status"] == "AUDITED"


def test_research_result_serialization_can_carry_inputs_through_coverage():
    install()
    result = ResearchResult(
        question="historical question",
        answer="partial",
        status="PARTIAL",
        coverage={"historical_context_inputs": _inputs()},
    ).to_dict()
    packet = result["coverage"]["historical_context"]
    assert packet["ran"] is True
    assert packet["status"] == "AUDITED"
    assert packet["truth_proven"] is False
    assert result["status"] == "PARTIAL"


def test_install_is_idempotent():
    from research_engine import result_coverage_gate

    before = result_coverage_gate.enforce
    install()
    once = result_coverage_gate.enforce
    install()
    twice = result_coverage_gate.enforce
    assert before is once
    assert once is twice
