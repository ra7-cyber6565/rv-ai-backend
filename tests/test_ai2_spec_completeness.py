from research_engine.validation_advanced import (
    analyze_ablation_receipt, analyze_failure_receipt, analyze_predictive_receipt,
    analyze_robustness_receipt,
)
from research_engine.validation_contracts import CONDITIONAL_PASS, INCONCLUSIVE, RESULT_OBSERVED
from research_engine.validation_director import AI2ValidationDirector
from research_engine.validation_trading_risk import simulate_risk_of_ruin


def _hypothesis():
    return {
        "id": "H1",
        "statement": "Candidate improves the locked outcome.",
        "prediction": {
            "variables": [
                {"name": "candidate", "role": "independent", "unit": "category"},
                {"name": "outcome", "role": "dependent", "unit": "score"},
            ],
            "expected_outcome": "Candidate outcome is higher.",
            "falsification_condition": "No reproducible improvement.",
        },
        "experiment": {
            "dataset_or_sample": "locked sample",
            "experimental_setup": "pre-registered controlled comparison",
            "null_hypothesis": "No difference.",
            "statistical_metric": "mean difference",
            "control_or_baseline": "simple baseline",
            "confounders": ["baseline severity"],
            "falsification_condition": "No reproducible improvement.",
            "replication_method": "independent repeat",
        },
    }


def _result():
    return {"question": "Does it work?", "hypotheses": [_hypothesis()], "sources": [{"id": "S1"}]}


def _experiment(packet):
    return packet["sections"]["6. Exact Experiments / Backtests / Simulations Required"]["domain_hypothesis_experiments"][0]


def test_math_model_requires_full_pro_max_contract():
    r = _result()
    r["mathematical_model"] = {
        "model_type": "causal",
        "equation": "y = beta*x + e",
        "objective": "Estimate causal effect on y",
        "constraints": [],
        "assumptions": ["random assignment", "stable measurement"],
        "parameters": {
            "beta": {"definition": "causal slope", "unit": "score/category", "interpretation": "effect of x on y"},
            "x": {"definition": "treatment indicator", "unit": "category", "interpretation": "assigned treatment"},
            "y": {"definition": "outcome", "unit": "score", "interpretation": "measured response"},
        },
        "estimation_method": "difference in means",
        "identifiability": "randomized assignment identifies beta",
        "data_linked_prediction": "locked treatment arm mean exceeds control mean",
    }
    model = AI2ValidationDirector().build_packet("Does it work?", r)["sections"]["3. Mathematical Model"]["domain_models_found"][0]
    assert model["model_contract_complete"] is True
    assert all(model["requirements_status"].values())

    r["mathematical_model"].pop("identifiability")
    model2 = AI2ValidationDirector().build_packet("Does it work?", r)["sections"]["3. Mathematical Model"]["domain_models_found"][0]
    assert model2["model_contract_complete"] is False
    assert model2["status"] == INCONCLUSIVE


def test_predictive_receipt_requires_untouched_test_and_supports_conditional_pass():
    receipt = {
        "provenance": {"test_id": "P1", "dataset_id": "locked-v1"},
        "primary_metric": "accuracy",
        "splits": {
            "train": {"accuracy": 0.94},
            "validation": {"accuracy": 0.89},
            "untouched_test": {"accuracy": 0.86},
        },
        "test_was_used_for_tuning": False,
        "decision_rule": {"metric": "untouched_test_metric", "operator": ">=", "threshold": 0.85,
                          "status_if_pass": "CONDITIONAL PASS"},
    }
    out = analyze_predictive_receipt(receipt)
    assert out["observed"] is True and out["final_test_valid"] is True
    assert out["status"] == CONDITIONAL_PASS

    receipt["test_was_used_for_tuning"] = True
    out2 = analyze_predictive_receipt(receipt)
    assert out2["status"] == INCONCLUSIVE


def test_robustness_receipt_uses_explicit_rule_only():
    receipt = {
        "provenance": {"run_id": "R1"},
        "scenarios": {"nominal": 1.2, "nearby-a": 1.1, "nearby-b": 1.15},
        "nominal_scenario": "nominal",
        "decision_rule": {"metric": "minimum", "operator": ">", "threshold": 1.0},
    }
    out = analyze_robustness_receipt(receipt)
    assert out["observed"] is True
    assert out["status"] == "PASS"
    assert out["metrics"]["max_absolute_deviation_from_nominal"] > 0


def test_ablation_recommends_removal_only_with_supplied_materiality_threshold():
    receipt = {
        "provenance": {"run_id": "A1"},
        "full_model_score": 0.90,
        "without_component_scores": {"A": 0.899, "B": 0.84},
        "higher_is_better": True,
        "materiality_threshold": 0.005,
    }
    out = analyze_ablation_receipt(receipt)
    by_component = {row["component"]: row for row in out["components"]}
    assert by_component["A"]["recommendation"] == "REMOVAL"
    assert by_component["B"]["recommendation"] == "KEEP"

    receipt.pop("materiality_threshold")
    out2 = analyze_ablation_receipt(receipt)
    assert all(row["recommendation"] == "NOT TESTED" for row in out2["components"])


def test_failure_distribution_computes_frequency_cluster_tail_and_explicit_catastrophe():
    receipt = {
        "provenance": {"run_id": "F1"},
        "failure_flags": [False, True, True, False, True],
        "failure_severities": [1.0, 4.0, 8.0],
        "catastrophe_threshold": 7.0,
        "severity_higher_is_worse": True,
        "monte_carlo_iterations": 50,
        "random_seed": 7,
        "decision_rule": {"metric": "failure_frequency", "operator": "<", "threshold": 0.8},
    }
    out = analyze_failure_receipt(receipt)
    assert out["observed"] is True
    assert out["metrics"]["failure_frequency"] == 0.6
    assert out["metrics"]["longest_failure_cluster"] == 2
    assert out["metrics"]["catastrophic_failure_frequency"] == 1 / 3
    assert out["monte_carlo"]["iterations"] == 50


def test_verified_bias_finding_downgrades_positive_hypothesis_verdict():
    r = _result()
    r["validation_receipts"] = [{
        "hypothesis_id": "H1",
        "provenance": {"test_id": "T1", "dataset_id": "locked"},
        "observations": {"candidate": [3, 4, 5], "baseline": [1, 1, 2]},
        "decision_rule": {"metric": "mean_difference", "operator": ">", "threshold": 0},
    }]
    r["bias_audit"] = {
        "look_ahead_bias": {"status": "FOUND", "evidence": "future timestamp was present in a predictor",
                            "provenance": {"artifact": "audit-1"}}
    }
    packet = AI2ValidationDirector().build_packet("Does it work?", r)
    exp = _experiment(packet)
    assert exp["pre_bias_guard_status"] == "PASS"
    assert exp["hypothesis_status"] == INCONCLUSIVE
    assert packet["decision_guards"]["bias_leakage_guard"]["positive_verdicts_downgraded"] is True


def test_auto_consumes_existing_ai1_handoff_for_second_pass_without_restart():
    r = _result()
    r["ai1_research_packet"] = {"hypotheses": [{"id": "AI1-H1", "statement": "Evidence-backed mechanism", "prediction": "x"}]}
    packet = AI2ValidationDirector().build_packet("Does it work?", r)
    assert packet["second_pass_context"]["present"] is True
    assert "AI-1" in packet["second_pass_context"]["agents_received"]
    assert "AI-1" in packet["second_pass_context"]["agent_outputs"]
    assert packet["second_pass_context"]["agent_outputs"]["AI-1"]["full_payload_embedded"] is False
    assert "hypotheses" not in packet["second_pass_context"]["agent_outputs"]["AI-1"]
    assert packet["second_pass_context"]["full_payloads_embedded_in_ai2_packet"] is False
    tasks = packet["sections"]["15. Highest-Value Second-Pass Validation Tasks"]
    assert "Triangulate" in tasks[0]["task"]


def test_friction_receipts_are_consumed_without_inventing_other_values():
    r = _result()
    r["friction_audit"] = {
        "measurement_error": {"value": "sensor SD=0.2", "tested": True,
                              "provenance": {"report": "calibration-7"}, "relevance": "RELEVANT"}
    }
    rows = AI2ValidationDirector().build_packet("Does it work?", r)["sections"]["10. Real-World Friction"]
    lookup = {row["factor"]: row for row in rows}
    assert lookup["measurement error"]["tested"] is True
    assert lookup["measurement error"]["value"] == "sensor SD=0.2"
    assert lookup["hardware"]["value"] == "TO BE ESTIMATED"


def test_risk_of_ruin_calculates_only_with_full_explicit_contract():
    receipt = {
        "starting_equity": 100.0,
        "ruin_equity": 50.0,
        "risk_of_ruin_horizon_trades": 25,
        "risk_of_ruin_simulations": 100,
        "risk_of_ruin_random_seed": 11,
        "risk_of_ruin_return_mode": "fractional_equity",
        "risk_of_ruin_dependence_model": "block_bootstrap",
        "risk_of_ruin_block_length": 2,
    }
    out = simulate_risk_of_ruin(receipt, [0.02, -0.01, 0.03, -0.02])
    assert out["status"] == "CALCULATED"
    assert 0.0 <= out["risk_of_ruin"] <= 1.0
    assert out["dependence_model"] == "block_bootstrap"

    receipt.pop("risk_of_ruin_horizon_trades")
    out2 = simulate_risk_of_ruin(receipt, [0.02, -0.01])
    assert out2["status"] == "NOT TESTED"


def test_variable_role_audit_is_explicit_without_forcing_irrelevant_roles():
    packet = AI2ValidationDirector().build_packet("Does it work?", _result())
    audit = packet["sections"]["2. Quantifiable Components"]["variable_role_audit"][0]
    assert "independent" in audit["provided_roles"]
    assert "dependent" in audit["provided_roles"]
    assert "mediator" in audit["role_categories_not_explicitly_supplied"]
    assert "not automatically errors" in audit["interpretation"]


def test_generic_numeric_receipt_supports_explicit_conditional_pass():
    r = _result()
    r["validation_receipts"] = [{
        "hypothesis_id": "H1",
        "provenance": {"test_id": "T-COND", "dataset_id": "locked"},
        "observations": {"candidate": [4, 5, 6], "baseline": [1, 2, 3]},
        "decision_rule": {
            "metric": "mean_difference", "operator": ">", "threshold": 0,
            "status_if_pass": "CONDITIONAL PASS",
        },
    }]
    exp = _experiment(AI2ValidationDirector().build_packet("Does it work?", r))
    assert exp["test_state"] == RESULT_OBSERVED
    assert exp["hypothesis_status"] == CONDITIONAL_PASS
    assert exp["decision_basis"]["status"] == CONDITIONAL_PASS
    assert exp["decision_basis"]["rule_source"] == "SUPPLIED_IN_RESULT_RECEIPT"


def test_verified_bias_also_invalidates_fail_until_clean_retest():
    r = _result()
    r["validation_receipts"] = [{
        "hypothesis_id": "H1",
        "provenance": {"test_id": "T-FAIL", "dataset_id": "locked"},
        "observations": {"candidate": [1, 1, 1], "baseline": [3, 4, 5]},
        "decision_rule": {"metric": "mean_difference", "operator": ">", "threshold": 0},
    }]
    r["bias_audit"] = {
        "target_leakage": {"status": "DETECTED", "evidence": "target-derived feature entered the evaluated design",
                           "provenance": {"artifact": "audit-fail"}}
    }
    packet = AI2ValidationDirector().build_packet("Does it work?", r)
    exp = _experiment(packet)
    assert exp["pre_bias_guard_status"] == "FAIL"
    assert exp["hypothesis_status"] == INCONCLUSIVE
    guard = packet["decision_guards"]["bias_leakage_guard"]
    assert guard["decisive_verdicts_downgraded"] is True


def test_handoff_compaction_prevents_ai1_packet_duplication():
    r = _result()
    r["ai1_research_packet"] = {
        "validation": {"valid": True},
        "sections": {"very_large": {"payload": "x" * 5000}},
        "hypotheses": [{"id": "AI1-H1", "statement": "Evidence-backed mechanism"}],
    }
    packet = AI2ValidationDirector().build_packet("Does it work?", r)
    stored = packet["second_pass_context"]["agent_outputs"]["AI-1"]
    assert stored["full_payload_embedded"] is False
    assert stored["packet_valid"] is True
    assert "sections" not in stored
    assert "hypotheses" not in stored
    assert packet["second_pass_context"]["full_payloads_used_internally"] is True
