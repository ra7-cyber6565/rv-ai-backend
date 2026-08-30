from research_engine.mechanistic_reasoning_wiring import (
    apply_mechanistic_reasoning_wiring,
    build_mechanistic_reasoning_packet,
    install,
)
from research_engine.models import ResearchResult


def _contract():
    return {
        "model_id": "m1",
        "variables": [
            {"id": "x", "initial": 2.0, "min": -10.0, "max": 10.0,
             "unit": "1", "role": "STATE", "observable_ref": "sensor:x"},
            {"id": "y", "initial": 0.0, "min": -20.0, "max": 20.0,
             "unit": "1", "role": "STATE", "observable_ref": "sensor:y"},
        ],
        "equations": [
            {"target": "x", "terms": [{"variable": "x", "coefficient": -1.0,
                                         "transform": "identity"}],
             "bias": 0.0, "decay": 0.0,
             "mechanism": "x decays with x", "observable": "x each step",
             "falsifier": "x fails to halve", "evidence_refs": ["source:1#x"]},
            {"target": "y", "terms": [{"variable": "x", "coefficient": 1.0,
                                         "transform": "identity"}],
             "bias": 0.0, "decay": 0.0,
             "mechanism": "x drives y", "observable": "y each step",
             "falsifier": "y increment differs", "evidence_refs": ["source:2#y"]},
        ],
        "dt": 0.5,
        "steps": 2,
    }


def test_no_explicit_contract_does_not_infer_mechanism_from_prose():
    packet = build_mechanistic_reasoning_packet({
        "hypotheses": [{"id": "H1", "statement": "X may cause Y through a mediator."}]
    })
    assert packet["status"] == "NO_EXPLICIT_MECHANISTIC_MODELS"
    assert packet["explicit_models"] == 0
    assert packet["prose_formalization_performed"] is False
    assert packet["causal_mechanism_proven"] is False


def test_explicit_complete_contract_runs_baseline_intervention_and_sensitivity():
    packet = build_mechanistic_reasoning_packet({
        "hypotheses": [{
            "id": "H1",
            "mechanistic_model": _contract(),
            "mechanistic_interventions": [{"x": 4.0}],
            "mechanistic_sensitivity": True,
        }]
    })
    assert packet["status"] == "AUDITED_MODEL_CONSEQUENCES"
    assert packet["complete_mechanism_contracts"] == 1
    assert packet["simulated_models"] == 1
    row = packet["models"][0]
    assert row["mechanism_audit"]["complete"] is True
    assert dict(row["simulation"]["final_state"])["x"] == 0.5
    assert len(row["intervention_comparisons"]) == 1
    assert row["sensitivity"]["rows"]
    assert row["causal_mechanism_proven"] is False
    assert row["empirical_validation_proven"] is False
    assert row["truth_proven"] is False


def test_invalid_contract_is_visible_and_does_not_crash_result_pipeline():
    bad = _contract()
    bad["dt"] = float("nan")
    packet = build_mechanistic_reasoning_packet({
        "hypotheses": [{"id": "H1", "mechanistic_model": bad}]
    })
    assert packet["status"] == "PARTIAL_INVALID_MECHANISTIC_MODELS"
    assert packet["invalid_models"] == 1
    assert packet["models"][0]["status"] == "INVALID_MECHANISTIC_CONTRACT"
    assert packet["models"][0]["truth_proven"] is False


def test_incomplete_mechanism_requirement_does_not_execute_model():
    incomplete = _contract()
    incomplete["equations"][0]["falsifier"] = ""
    packet = build_mechanistic_reasoning_packet({
        "hypotheses": [{"id": "H1", "mechanistic_model": incomplete}]
    })
    assert packet["status"] == "INCOMPLETE_MECHANISM_REQUIREMENTS"
    assert packet["complete_mechanism_contracts"] == 0
    assert packet["simulated_models"] == 0
    assert packet["models"][0]["simulation"] is None


def test_wiring_preserves_answer_status_and_existing_coverage():
    original = {
        "answer": "keep me",
        "status": "PARTIAL",
        "coverage": {"existing": {"kept": True}},
        "hypotheses": [{"id": "H1", "mechanistic_model": _contract()}],
    }
    result = apply_mechanistic_reasoning_wiring(original)
    assert result["answer"] == "keep me"
    assert result["status"] == "PARTIAL"
    assert result["coverage"]["existing"] == {"kept": True}
    assert result["coverage"]["mechanistic_reasoning"]["simulated_models"] == 1
    assert result["coverage"]["mechanistic_reasoning"]["truth_proven"] is False


def test_real_research_result_serialization_receives_mechanistic_audit_packet():
    install()
    payload = ResearchResult(
        question="q",
        answer="a",
        status="PARTIAL",
        hypotheses=[{"id": "H1", "mechanistic_model": _contract()}],
    ).to_dict()
    packet = payload["coverage"]["mechanistic_reasoning"]
    assert packet["ran"] is True
    assert packet["status"] == "AUDITED_MODEL_CONSEQUENCES"
    assert packet["model_execution_proves_causality"] is False
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
