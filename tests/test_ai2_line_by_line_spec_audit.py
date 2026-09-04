from research_engine.validation_contracts import CONDITIONAL_PASS, FAIL, INCONCLUSIVE, PASS
from research_engine.validation_director import AI2ValidationDirector, attach_ai2_validation
from research_engine.validation_spec_hardening import harden_ai2_runtime_result


def _hypothesis():
    return {
        "id": "H1",
        "statement": "Candidate improves the locked outcome.",
        "prediction": {
            "variables": [
                {
                    "name": "candidate assignment",
                    "role": "independent",
                    "unit": "category",
                    "definition": "candidate versus baseline assignment",
                    "interpretation": "treatment/model assignment",
                },
                {
                    "name": "locked outcome",
                    "role": "dependent",
                    "unit": "score",
                    "definition": "pre-specified measured outcome",
                    "interpretation": "primary response",
                },
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
    return {
        "question": "Does it work?",
        "hypotheses": [_hypothesis()],
        "sources": [{"id": "S1"}],
    }


def _harden(question, result):
    attached = attach_ai2_validation(question, result)
    return harden_ai2_runtime_result(question, attached)


def _experiment(result):
    return result["ai2_validation"]["sections"]["6. Exact Experiments / Backtests / Simulations Required"]["domain_hypothesis_experiments"][0]


def test_line_by_line_audit_covers_role_primary_18_requirements_and_final_packet():
    out = _harden("Does it work?", _result())
    audit = out["ai2_validation"]["line_by_line_spec_audit"]
    ids = [row["id"] for row in audit["matrix"]]
    assert ids == ["ROLE", "PRIMARY"] + [str(i) for i in range(1, 19)] + ["FINAL"]
    assert audit["valid"] is True
    assert all(row["implementation_status"] != "MISSING" for row in audit["matrix"])
    assert len(out["ai2_validation"]["sections"]) == 17


def test_goal_section_explicitly_states_eventual_outcome_evidence_and_measurement_limits():
    out = _harden("Does it work?", _result())
    section = out["ai2_validation"]["sections"]["1. Interpretation of User Goal"]
    assert section["eventual_outcome_required"]
    assert section["quantitative_evidence_required"][0]["primary_metric"] == "mean difference"
    assert section["what_can_realistically_be_measured"]
    assert section["what_cannot_be_claimed_measured_without_extra_evidence"]


def test_ai2_constructs_only_fail_closed_symbol_defined_validation_model_skeleton():
    out = _harden("Does it work?", _result())
    section = out["ai2_validation"]["sections"]["3. Mathematical Model"]
    models = section["ai2_constructed_validation_models"]
    assert len(models) == 1
    model = models[0]
    assert model["status"] == INCONCLUSIVE
    assert model["model_contract_complete"] is False
    assert "TO BE ESTIMATED" in str(model["symbol_metadata"])
    for symbol in model["symbol_metadata"]:
        assert symbol["symbol"]
        assert symbol["definition"]
        assert symbol["unit"]
        assert symbol["interpretation"]


def test_predictive_positive_is_blocked_without_train_validation_or_explicit_not_applicable_reason():
    r = _result()
    r["predictive_validation_receipt"] = {
        "provenance": {"test_id": "P1", "dataset_id": "locked-final"},
        "primary_metric": "accuracy",
        "splits": {"untouched_test": {"accuracy": 0.91}},
        "test_was_used_for_tuning": False,
        "decision_rule": {"metric": "untouched_test_metric", "operator": ">=", "threshold": 0.90},
    }
    out = _harden("Predict model performance", r)
    predictive = out["ai2_validation"]["advanced_receipt_analyses"]["predictive_validation"]
    assert predictive["pre_split_guard_status"] == PASS
    assert predictive["status"] == INCONCLUSIVE
    assert predictive["split_contract_complete"] is False

    r["predictive_validation_receipt"]["train_validation_not_applicable_reason"] = "Externally trained model was frozen before this independent evaluation."
    out2 = _harden("Predict model performance", r)
    predictive2 = out2["ai2_validation"]["advanced_receipt_analyses"]["predictive_validation"]
    assert predictive2["split_contract_complete"] is True
    assert predictive2["status"] == PASS


def test_explicit_multi_metric_bundle_can_overrule_single_attractive_metric_without_invented_thresholds():
    r = _result()
    r["validation_receipts"] = [{
        "hypothesis_id": "H1",
        "provenance": {"test_id": "T-MM", "dataset_id": "D-MM"},
        "observations": {"candidate": [5, 6, 7], "baseline": [1, 2, 3]},
        "decision_rule": {"metric": "mean_difference", "operator": ">", "threshold": 0},
        "decision_logic": "all",
        "decision_rules": [
            {"metric": "mean_difference", "operator": ">", "threshold": 0},
            {"metric": "standardized_effect", "operator": ">", "threshold": 99},
        ],
    }]
    out = _harden("Does it work?", r)
    exp = _experiment(out)
    assert exp["quantitative_result_analysis"]["metrics"]["mean_difference"] > 0
    assert exp["hypothesis_status"] == FAIL
    assert exp["decision_basis"]["multi_metric"] is True
    assert exp["decision_basis"]["rule_count"] == 2
    assert exp["decision_basis"]["rule_source"] == "SUPPLIED_IN_RESULT_RECEIPT"


def test_single_metric_decision_is_scoped_and_does_not_claim_overall_robustness():
    r = _result()
    r["validation_receipts"] = [{
        "hypothesis_id": "H1",
        "provenance": {"test_id": "T1", "dataset_id": "D1"},
        "observations": {"candidate": [5, 6, 7], "baseline": [1, 2, 3]},
        "decision_rule": {"metric": "mean_difference", "operator": ">", "threshold": 0},
    }]
    out = _harden("Does it work?", r)
    exp = _experiment(out)
    assert exp["hypothesis_status"] == PASS
    assert exp["broader_validation_status"] == INCONCLUSIVE
    assert "narrow tested claim" in exp["decision_scope"]
    assert exp["status_reason"]


def test_failure_receipt_gets_regime_scenario_and_dependence_aware_analysis():
    r = _result()
    r["failure_distribution_receipt"] = {
        "provenance": {"run_id": "F2", "dataset_id": "stress-v2"},
        "failure_flags": [False, True, True, False],
        "failure_severities": [1.0, 4.0, 8.0, 2.0],
        "failure_regimes": ["A", "A", "B", "B"],
        "stress_scenarios": {"base": 2.0, "shock": 9.0},
        "stress_higher_is_worse": True,
        "failure_dependence_model": "block_bootstrap",
        "failure_block_length": 2,
        "monte_carlo_iterations": 40,
        "random_seed": 17,
    }
    out = _harden("Does it work?", r)
    failure = out["ai2_validation"]["advanced_receipt_analyses"]["failure_distribution"]
    assert failure["regime_analysis"]["state"] == "RESULT OBSERVED"
    by_regime = {row["regime"]: row for row in failure["regime_analysis"]["regimes"]}
    assert by_regime["A"]["failure_frequency"] == 0.5
    assert by_regime["B"]["failure_frequency"] == 0.5
    assert failure["scenario_analysis"]["worst_scenario"] == "shock"
    assert failure["dependence_aware_monte_carlo"]["status"] == "CALCULATED"
    assert failure["dependence_aware_monte_carlo"]["block_length"] == 2


def test_robustness_receipt_reports_exact_dimension_coverage_instead_of_universal_claim():
    r = _result()
    r["robustness_receipt"] = {
        "provenance": {"run_id": "R2"},
        "scenarios": {"near": 1.2, "time": 1.1},
        "scenario_dimensions": {
            "near": "nearby parameter values",
            "time": "different time periods",
        },
        "required_dimensions": ["nearby parameter values", "different time periods", "different regimes"],
        "decision_rule": {"metric": "minimum", "operator": ">", "threshold": 1.0},
    }
    out = _harden("Does it work?", r)
    robustness = out["ai2_validation"]["advanced_receipt_analyses"]["robustness"]
    audit = robustness["dimension_coverage_audit"]
    assert audit["coverage_complete"] is False
    assert "different regimes" in audit["missing_dimensions"]
    assert robustness["status"] == PASS
    assert "tested" in audit["rule"]


def _trading_result(dataset_role, tuned, conditional=False):
    r = {
        "hypotheses": [{"id": "H1", "statement": "Locked rule has positive net expectancy."}],
        "trade_contract": {
            "instrument": "MARKET CFD",
            "feed_assumptions": "locked historical bid/ask feed",
            "futures_vs_cfd_relationship": "explicit mapping",
            "timeframe": "5m",
            "regime": "all labeled regimes",
            "session": "session A",
            "long_rules": "locked long",
            "short_rules": "locked short",
            "entry_rule": "locked entry",
            "stop_loss": "locked stop",
            "take_profit": "locked target",
            "position_sizing": "fixed risk",
            "no_trade_rules": "locked avoid rules",
            "news_filtering": "locked news rule",
            "spread": "included",
            "commission": "included",
            "slippage": "included",
            "latency": "included",
        },
        "trade_result_receipt": {
            "provenance": {"test_id": "BT-LBL", "dataset_id": "trade-data"},
            "trade_returns": [1.0, -0.25, 1.5, -0.25],
            "returns_are_net_of_friction": True,
            "dataset_role": dataset_role,
            "test_was_used_for_tuning": tuned,
            "decision_rule": {
                "metric": "expectancy",
                "operator": ">",
                "threshold": 0,
                **({"status_if_pass": "CONDITIONAL PASS"} if conditional else {}),
            },
        },
    }
    return r


def test_trading_positive_cannot_generalize_from_in_sample_or_tuned_data():
    out = _harden("Backtest MARKET CFD strategy", _trading_result("train", True))
    trading = out["ai2_validation"]["sections"]["6. Exact Experiments / Backtests / Simulations Required"]["trading_validation_standard"]
    assert trading["pre_generalization_guard_status"] == PASS
    assert trading["observed_result_status"] == INCONCLUSIVE
    assert trading["generalization_gate"]["passed"] is False


def test_trading_untouched_friction_net_never_tuned_receipt_can_emit_explicit_conditional_pass():
    out = _harden("Backtest MARKET CFD strategy", _trading_result("untouched_test", False, conditional=True))
    trading = out["ai2_validation"]["sections"]["6. Exact Experiments / Backtests / Simulations Required"]["trading_validation_standard"]
    assert trading["generalization_gate"]["passed"] is True
    assert trading["observed_result_status"] == CONDITIONAL_PASS
    assert trading["execution_contract_audit"]["complete"] is True


def test_bias_rows_distinguish_provenance_bearing_from_unprovenanced_assertions():
    r = _result()
    r["bias_audit"] = {
        "look_ahead_bias": {
            "status": "FOUND",
            "evidence": "future timestamp in predictor",
            "provenance": {"artifact": "audit-1"},
        },
        "selection_bias": {
            "status": "FOUND",
            "evidence": "selection may depend on outcome",
        },
    }
    out = _harden("Does it work?", r)
    rows = {row["risk"]: row for row in out["ai2_validation"]["sections"]["7. Bias & Leakage Risks"]}
    assert rows["look-ahead bias"]["verification_level"] == "PROVENANCE_BEARING"
    assert rows["selection bias"]["verification_level"] == "ASSERTED_EVIDENCE_WITHOUT_PROVENANCE"


def test_structured_second_pass_inputs_are_promoted_to_specific_information_gain_tasks_without_fake_score():
    r = _result()
    r["ai3_theory_packet"] = {
        "disputed_claims": [{"id": "D1", "claim": "Mechanism disputed"}],
        "merged_models": [{"id": "M1"}],
    }
    r["ai4_red_team_packet"] = {
        "objections": [{"id": "O1", "claim": "Leakage risk"}],
    }
    out = _harden("Does it work?", r)
    tasks = out["ai2_validation"]["sections"]["15. Highest-Value Second-Pass Validation Tasks"]
    assert tasks[0]["source_agent"] == "AI-3"
    assert tasks[0]["expected_information_gain"] == "TO BE ESTIMATED"
    assert any(task.get("source_agent") == "AI-4" for task in tasks if isinstance(task, dict))
    assert [task["priority"] for task in tasks] == list(range(1, len(tasks) + 1))
