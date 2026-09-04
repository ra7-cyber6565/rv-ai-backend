from research_engine.validation_contracts import INCONCLUSIVE
from research_engine.validation_director import attach_ai2_validation
from research_engine.validation_spec_final_guard import enforce_ai2_final_truth_guards
from research_engine.validation_spec_hardening import harden_ai2_runtime_result


def _hypothesis():
    return {
        "id": "H1",
        "statement": "Candidate improves outcome.",
        "prediction": {
            "variables": [
                {"name": "candidate", "role": "independent", "unit": "category"},
                {"name": "outcome", "role": "dependent", "unit": "score"},
            ],
            "expected_outcome": "Candidate is higher.",
            "falsification_condition": "No improvement.",
        },
        "experiment": {
            "dataset_or_sample": "locked sample",
            "experimental_setup": "controlled comparison",
            "null_hypothesis": "No difference.",
            "statistical_metric": "mean difference",
            "control_or_baseline": "baseline",
            "confounders": ["severity"],
            "falsification_condition": "No improvement.",
            "replication_method": "independent repeat",
        },
    }


def test_verified_bias_downgrade_cannot_be_reupgraded_by_multi_metric_composition():
    result = {
        "question": "Does it work?",
        "sources": [{"id": "S1"}],
        "hypotheses": [_hypothesis()],
        "validation_receipts": [{
            "hypothesis_id": "H1",
            "provenance": {"test_id": "T1", "dataset_id": "D1"},
            "observations": {"candidate": [5, 6, 7], "baseline": [1, 2, 3]},
            "decision_rule": {"metric": "mean_difference", "operator": ">", "threshold": 0},
            "decision_rules": [
                {"metric": "mean_difference", "operator": ">", "threshold": 0},
                {"metric": "candidate_mean", "operator": ">", "threshold": 4},
            ],
            "decision_logic": "all",
        }],
        "bias_audit": {
            "look_ahead_bias": {
                "status": "FOUND",
                "evidence": "future timestamp entered evaluated predictor",
                "provenance": {"artifact": "audit-verified"},
            }
        },
    }
    out = attach_ai2_validation(result["question"], result)
    out = harden_ai2_runtime_result(result["question"], out)
    # Multi-metric composition can calculate the supplied rules, but the final
    # one-way guard must restore the earlier verified-bias hold.
    out = enforce_ai2_final_truth_guards(out)
    exp = out["ai2_validation"]["sections"]["6. Exact Experiments / Backtests / Simulations Required"]["domain_hypothesis_experiments"][0]
    assert exp["hypothesis_status"] == INCONCLUSIVE
    assert exp["final_truth_guard"] == "BIAS_OR_LEAKAGE_DOWNGRADE_IS_MONOTONIC"
    guard = out["ai2_validation"]["decision_guards"]["final_monotonic_truth_guard"]
    assert guard["active"] is True
    assert guard["downgraded_hypothesis_ids"] == ["H1"]
