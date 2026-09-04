from research_engine.validation_contracts import INCONCLUSIVE, PASS
from research_engine.validation_director import attach_ai2_validation
from research_engine.validation_spec_hardening import harden_ai2_runtime_result
from research_engine.validation_spec_quant_extension import extend_ai2_quantitative_receipts


def _hypothesis():
    return {
        "id": "H1",
        "statement": "Candidate improves outcome.",
        "prediction": {
            "variables": [
                {"name": "candidate", "role": "independent", "unit": "category"},
                {"name": "outcome", "role": "dependent", "unit": "score"},
            ],
            "expected_outcome": "Candidate outcome is higher.",
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


def _apply(result):
    out = attach_ai2_validation("Does it work?", result)
    out = harden_ai2_runtime_result("Does it work?", out)
    return extend_ai2_quantitative_receipts(out)


def test_generic_monte_carlo_samples_are_summarized_without_upgrading_hypothesis_status():
    result = {
        "hypotheses": [_hypothesis()],
        "validation_receipts": [{
            "hypothesis_id": "H1",
            "provenance": {"test_id": "T-MC", "dataset_id": "D-MC"},
            "observations": {"candidate": [4, 5, 6], "baseline": [1, 2, 3]},
            "monte_carlo_samples": [0.2, 0.4, -0.1, 0.3, 0.5],
            "monte_carlo_sample_source": "caller-supplied simulation under explicit model M1",
            "monte_carlo_assumptions": ["model M1 is correctly specified"],
        }],
    }
    out = _apply(result)
    exp = out["ai2_validation"]["sections"]["6. Exact Experiments / Backtests / Simulations Required"]["domain_hypothesis_experiments"][0]
    mc = exp["statistical_validation"]["monte_carlo"]
    assert mc["status"] == "CALCULATED"
    assert mc["n"] == 5
    assert mc["minimum"] == -0.1
    assert mc["maximum"] == 0.5
    assert exp["hypothesis_status"] == INCONCLUSIVE
    assert "cannot by itself prove" in exp["monte_carlo_truth_rule"]


def test_generic_monte_carlo_requires_provenance_and_sample_source():
    result = {
        "hypotheses": [_hypothesis()],
        "validation_receipts": [{
            "hypothesis_id": "H1",
            "observations": {"candidate": [4, 5], "baseline": [1, 2]},
            "monte_carlo_samples": [1, 2, 3],
            "monte_carlo_sample_source": "simulation",
        }],
    }
    out = _apply(result)
    exp = out["ai2_validation"]["sections"]["6. Exact Experiments / Backtests / Simulations Required"]["domain_hypothesis_experiments"][0]
    mc = exp["statistical_validation"]["monte_carlo"]
    assert mc["status"] == "NOT TESTED"


def test_positive_robustness_is_downgraded_when_caller_declared_required_dimensions_are_missing():
    result = {
        "hypotheses": [_hypothesis()],
        "robustness_receipt": {
            "provenance": {"run_id": "R-Q"},
            "scenarios": {"near": 1.2, "time": 1.1},
            "scenario_dimensions": {
                "near": "nearby parameter values",
                "time": "different time periods",
            },
            "required_dimensions": [
                "nearby parameter values",
                "different time periods",
                "different regimes",
            ],
            "decision_rule": {"metric": "minimum", "operator": ">", "threshold": 1.0},
        },
    }
    out_before = attach_ai2_validation("Does it work?", result)
    out_before = harden_ai2_runtime_result("Does it work?", out_before)
    assert out_before["ai2_validation"]["advanced_receipt_analyses"]["robustness"]["status"] == PASS

    out = extend_ai2_quantitative_receipts(out_before)
    robustness = out["ai2_validation"]["advanced_receipt_analyses"]["robustness"]
    assert robustness["pre_dimension_guard_status"] == PASS
    assert robustness["status"] == INCONCLUSIVE
    assert robustness["decision"]["status"] == INCONCLUSIVE
    assert "different regimes" in robustness["dimension_coverage_audit"]["missing_dimensions"]
