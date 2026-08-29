from research_engine.models import ResearchResult
from research_engine.world_model_wiring import (
    apply_world_model_wiring,
    build_world_model_packet,
    install,
)


def _inputs():
    return {
        "spec": {
            "state_names": ["position", "velocity"],
            "action_names": ["thrust"],
            "observation_names": ["sensor_position"],
            "transition_matrix": [[1.0, 1.0], [0.0, 1.0]],
            "action_matrix": [[0.0], [1.0]],
            "transition_bias": [0.0, 0.0],
            "observation_matrix": [[1.0, 0.0]],
            "observation_bias": [0.0],
            "lower_bounds": [-100.0, -20.0],
            "upper_bounds": [100.0, 20.0],
            "calibration_tolerance": 0.05,
        },
        "rollout": {
            "initial_state": {"position": 0.0, "velocity": 1.0},
            "actions": [{"thrust": 2.0}, {"thrust": 0.0}],
        },
        "counterfactual": {
            "initial_state": {"position": 0.0, "velocity": 0.0},
            "baseline_actions": [{"thrust": 0.0}, {"thrust": 0.0}],
            "intervention_actions": [{"thrust": 1.0}, {"thrust": 1.0}],
        },
    }


def test_structured_world_model_runs_without_claiming_reality_or_status_upgrade():
    result = apply_world_model_wiring({
        "answer": "partial",
        "status": "PARTIAL",
        "coverage": {"world_model_inputs": _inputs(), "existing": {"kept": True}},
    })
    packet = result["coverage"]["world_model"]
    assert packet["status"] == "AUDITED"
    assert packet["rollout"]["software_only"] is True
    assert packet["rollout"]["world_model_is_reality"] is False
    assert packet["rollout"]["sim_to_reality_gap_open"] is True
    assert packet["counterfactual"]["causal_effect_proven"] is False
    assert packet["world_model_is_reality"] is False
    assert packet["truth_proven"] is False
    assert result["status"] == "PARTIAL"
    assert result["coverage"]["existing"] == {"kept": True}


def test_free_form_answer_never_invents_world_dynamics():
    packet = build_world_model_packet({"answer": "The system probably behaves like a linear plant."})
    assert packet["status"] == "NO_STRUCTURED_WORLD_MODEL_INPUTS"
    assert packet["free_form_dynamics_inference_performed"] is False
    assert packet["world_model_is_reality"] is False


def test_bad_explicit_world_model_fails_closed_without_status_upgrade():
    bad = _inputs()
    bad["spec"]["transition_matrix"] = [[1.0]]
    result = apply_world_model_wiring({
        "status": "PARTIAL",
        "world_model_inputs": bad,
    })
    packet = result["coverage"]["world_model"]
    assert packet["ran"] is False
    assert packet["status"] == "ASSESSMENT_ERROR"
    assert packet["truth_proven"] is False
    assert result["status"] == "PARTIAL"


def test_normal_research_result_serialization_activates_world_model_wiring():
    result = ResearchResult(
        question="bounded world model audit",
        answer="partial",
        status="PARTIAL",
        coverage={"world_model_inputs": _inputs()},
    ).to_dict()
    packet = result["coverage"]["world_model"]
    assert packet["ran"] is True
    assert packet["status"] == "AUDITED"
    assert packet["result_status_upgraded"] is False
    assert packet["world_model_is_reality"] is False
    assert result["status"] != "COMPLETE"


def test_install_is_idempotent():
    from research_engine import result_coverage_gate

    before = result_coverage_gate.enforce
    install()
    after_first = result_coverage_gate.enforce
    install()
    after_second = result_coverage_gate.enforce
    assert before is after_first
    assert after_first is after_second
