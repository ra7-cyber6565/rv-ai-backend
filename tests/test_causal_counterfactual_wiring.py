from research_engine.models import ResearchResult
from research_engine.causal_counterfactual_wiring import (
    apply_causal_counterfactual_wiring,
    build_causal_counterfactual_packet,
    install,
)


def _contract():
    return {
        "model": {
            "nodes": [
                {"name": "X", "parents": {}, "intercept": 0},
                {"name": "Y", "parents": {"X": 2}, "intercept": 1},
            ],
            "hidden_confounding_addressed": False,
            "identification_basis": "explicit structured hypothesis",
        },
        "factual": {"X": 1, "Y": 3},
        "intervention": {"X": 4},
        "targets": ["Y"],
    }


def test_prose_only_hypothesis_does_not_trigger_causal_discovery():
    packet = build_causal_counterfactual_packet([
        {"id": "H1", "statement": "X might cause Y."}
    ])
    assert packet["status"] == "NO_EXPLICIT_CONTRACTS"
    assert packet["explicit_contracts"] == 0
    assert packet["results"] == []
    assert packet["natural_language_causal_discovery_performed"] is False
    assert packet["truth_proven"] is False


def test_explicit_contract_runs_and_remains_model_only():
    packet = build_causal_counterfactual_packet([
        {"id": "H1", "causal_contract": _contract()}
    ])
    assert packet["status"] == "AUDITED"
    assert packet["explicit_contracts"] == 1
    row = packet["results"][0]
    assert row["status"] == "MODELED_COUNTERFACTUAL"
    assert row["predicted_values"]["Y"] == 9.0
    assert row["deltas"]["Y"] == 6.0
    assert row["causal_graph_empirically_proven"] is False
    assert row["real_world_effect_proven"] is False
    assert row["truth_proven"] is False


def test_invalid_contract_is_audited_without_crashing_result_pipeline():
    broken = _contract()
    broken["model"] = {
        "nodes": [
            {"name": "A", "parents": {"B": 1}},
            {"name": "B", "parents": {"A": 1}},
        ]
    }
    packet = build_causal_counterfactual_packet([
        {"id": "H1", "causal_contract": broken}
    ])
    assert packet["status"] == "PARTIAL_INVALID_CONTRACTS"
    assert packet["invalid_contracts"] == 1
    assert packet["results"][0]["status"] == "INVALID_CAUSAL_CONTRACT"
    assert packet["results"][0]["truth_proven"] is False


def test_apply_wiring_preserves_answer_status_and_existing_coverage():
    original = {
        "answer": "bounded answer",
        "status": "PARTIAL",
        "hypotheses": [{"id": "H1", "causal_contract": _contract()}],
        "coverage": {"existing": {"kept": True}},
    }
    result = apply_causal_counterfactual_wiring(original)
    assert result["answer"] == "bounded answer"
    assert result["status"] == "PARTIAL"
    assert result["coverage"]["existing"] == {"kept": True}
    assert result["coverage"]["causal_counterfactual"]["status"] == "AUDITED"


def test_real_research_result_serialization_contains_causal_packet():
    install()
    payload = ResearchResult(
        question="short question",
        answer="bounded answer",
        status="PARTIAL",
        hypotheses=[{"id": "H1", "causal_contract": _contract()}],
    ).to_dict()
    packet = payload["coverage"]["causal_counterfactual"]
    assert packet["ran"] is True
    assert packet["status"] == "AUDITED"
    assert packet["results"][0]["predicted_values"]["Y"] == 9.0
    assert payload["status"] == "PARTIAL"


def test_install_is_idempotent():
    from research_engine import result_coverage_gate

    before = result_coverage_gate.enforce
    install()
    after_first = result_coverage_gate.enforce
    install()
    after_second = result_coverage_gate.enforce
    assert before is after_first
    assert after_first is after_second
