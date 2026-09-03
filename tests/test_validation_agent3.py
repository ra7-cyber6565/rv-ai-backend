"""Agent-3 quantitative validation engine — deterministic/offline tests."""
from __future__ import annotations

from research_engine.validation_agent3 import (
    Agent3ValidationEngine,
    FinalStatus,
    audit_bias,
    audit_split,
    benjamini_hochberg,
    bootstrap_mean_ci,
    build_test_matrix,
    decide_status,
    execute_quantitative_test,
    monte_carlo_trade_failure,
    permutation_mean_difference,
    seal_holdout,
    trading_metrics,
)


ALL_CLEAR_BIASES = {
    "look_ahead": False,
    "hindsight": False,
    "survivorship": False,
    "data_snooping": False,
    "cherry_picking": False,
    "publication_bias": False,
    "selection_bias": False,
    "p_hacking": False,
    "hidden_leakage": False,
    "future_known_variables": False,
    "revised_data": False,
}


def _hypothesis(hid="H1", domain="general"):
    return {
        "id": hid,
        "domain": domain,
        "statement": "Treatment improves the primary outcome relative to control.",
        "dataset": "Frozen Dataset v1",
        "dataset_source": "local fixture",
        "timeframe": "2020-01-01 to 2024-12-31",
        "unit_of_analysis": "independent subject",
        "how_to_test": "Pre-registered treatment-control comparison",
        "null_hypothesis": "Mean treatment effect is zero.",
        "falsification_rule": "Reject hypothesis if effect <= 0 on untouched test.",
        "metrics": ["mean_difference", "cohens_d"],
        "prediction": {"variables": ["treatment", "primary_outcome"]},
    }


def _clean_meta():
    holdout = seal_holdout(["test-1", "test-2", "test-3"])
    return {
        "split": {
            "train": "2020-2022",
            "validation": "2023",
            "test": "2024",
            "test_touched_for_tuning": False,
            "holdout_seal_before": holdout,
            "holdout_seal_after": holdout,
        },
        "bias_flags": dict(ALL_CLEAR_BIASES),
        "test_touched_for_tuning": False,
    }


def test_planning_without_execution_never_claims_tested_or_pass():
    packet = Agent3ValidationEngine().validate(
        "Does treatment improve outcomes?",
        {},
        {"hypotheses": [_hypothesis()]},
    )
    row = packet["5. Hypothesis results"]["H1"]
    assert row["status"] == "INCONCLUSIVE"
    assert "NOT TESTED / UNKNOWN" in row["reason"]
    assert packet["1. Tests actually performed"] == []
    assert packet["2. Tests not possible + reason"]


def test_exact_fourteen_handoff_sections_are_present():
    packet = Agent3ValidationEngine().validate("q", {}, {"hypotheses": [_hypothesis()]})
    assert list(packet) == [
        "1. Tests actually performed",
        "2. Tests not possible + reason",
        "3. Dataset / evidence quality",
        "4. Baseline results",
        "5. Hypothesis results",
        "6. Robustness tests",
        "7. Ablation results",
        "8. Bias/leakage audit",
        "9. Real-world friction results",
        "10. Failure-mode analysis",
        "11. Surviving final candidates",
        "12. Practical implementation candidate",
        "13. Unknown/unverified elements",
        "14. FINAL VALIDATION PACKET FOR AGENT 4",
    ]


def test_missing_dataset_timeframe_test_and_falsifier_are_blockers():
    matrix = build_test_matrix(
        "generic question", {}, {"id": "H", "statement": "X causes Y"}
    )
    assert not matrix.executable
    assert "exact dataset missing" in matrix.blockers
    assert "exact timeframe missing" in matrix.blockers
    assert "exact test/measurement protocol missing" in matrix.blockers
    assert "pre-specified falsification rule missing" in matrix.blockers


def test_holdout_seal_is_deterministic_and_content_sensitive():
    assert seal_holdout({"b": 2, "a": 1}) == seal_holdout({"a": 1, "b": 2})
    assert seal_holdout([1, 2, 3]) != seal_holdout([1, 2, 4])


def test_trading_split_must_be_chronological():
    meta = _clean_meta()
    findings = audit_split(meta, domain="trading")
    chronological = [x for x in findings if x.check == "chronological split"][0]
    assert chronological.status == "FAIL"
    assert chronological.severity.value == "CRITICAL"


def test_trading_split_passes_when_chronological_is_explicit():
    meta = _clean_meta()
    meta["split"]["chronological"] = True
    findings = audit_split(meta, domain="trading")
    assert [x for x in findings if x.check == "chronological split"][0].status == "PASS"


def test_lookahead_contamination_is_critical_failure():
    meta = _clean_meta()
    meta["bias_flags"]["look_ahead"] = True
    findings = audit_bias(meta)
    hit = [x for x in findings if x.check == "look-ahead"][0]
    assert hit.status == "FAIL"
    assert hit.severity.value == "CRITICAL"


def test_multiple_testing_without_correction_fails_audit():
    meta = _clean_meta()
    meta["tests_tried"] = 100
    findings = audit_bias(meta)
    hit = [x for x in findings if x.check == "multiple testing correction"][0]
    assert hit.status == "FAIL"


def test_benjamini_hochberg_flags_small_p_values_without_inventing_missing_values():
    out = benjamini_hochberg([0.001, 0.02, 0.6, 0.9], alpha=0.05)
    assert out["status"] == "TESTED"
    assert out["tests"] == 4
    assert 0 in out["rejected_indexes"]


def test_bootstrap_is_deterministic_for_same_seed():
    a = bootstrap_mean_ci([1, 2, 3, 4, 5], iterations=500, seed=9)
    b = bootstrap_mean_ci([1, 2, 3, 4, 5], iterations=500, seed=9)
    assert a == b
    assert a["low"] <= a["mean"] <= a["high"]


def test_permutation_test_uses_actual_groups():
    out = permutation_mean_difference([10, 11, 12, 13], [1, 2, 3, 4], iterations=1000)
    assert out["status"] == "TESTED"
    assert out["mean_difference"] == 9.0
    assert 0 <= out["p_value_two_sided"] <= 1


def test_prediction_execution_calculates_metrics_and_baseline_delta():
    matrix = build_test_matrix("prediction", {}, _hypothesis(domain="predictive_modeling"))
    execution = {
        **_clean_meta(),
        "kind": "prediction",
        "dataset_name": "Frozen Dataset v1",
        "actual": [1, 2, 3, 4],
        "predicted": [1.1, 1.9, 3.2, 3.8],
        "baseline_predicted": [2.5, 2.5, 2.5, 2.5],
        "falsified": False,
    }
    result = execute_quantitative_test(matrix, execution)
    assert result.executed
    assert result.sample_size == 4
    assert result.metrics["MAE"] < result.baseline_results["baseline_MAE"]
    assert result.baseline_results["candidate_beats_baseline"] is True


def test_group_comparison_returns_effect_and_uncertainty():
    matrix = build_test_matrix("treatment", {}, _hypothesis())
    execution = {
        **_clean_meta(),
        "kind": "group_comparison",
        "treatment": [8, 9, 10, 11, 12],
        "control": [1, 2, 3, 4, 5],
        "falsified": False,
    }
    result = execute_quantitative_test(matrix, execution)
    assert result.executed
    assert result.metrics["mean_difference"] == 7.0
    assert result.statistical_tests["permutation"]["status"] == "TESTED"
    assert result.statistical_tests["bootstrap_effect_ci"]["low"] > 0


def test_trading_metrics_are_from_net_trade_rows_only():
    trades = [
        {"net_pnl": 3}, {"net_pnl": -1}, {"net_pnl": 2}, {"net_pnl": -1},
    ]
    out = trading_metrics(trades, starting_equity=100)
    assert out["status"] == "TESTED"
    assert out["trades"] == 4
    assert out["win_rate"] == 0.5
    assert out["expectancy"] == 0.75
    assert out["total_net_pnl"] == 3
    assert out["profit_factor"] == 2.5


def test_trading_gross_pnl_subtracts_supplied_friction():
    out = trading_metrics([
        {"gross_pnl": 10, "spread_cost": 1, "commission": 2, "slippage": 3},
        {"gross_pnl": -4, "spread_cost": 1, "commission": 1, "slippage": 0},
    ])
    assert out["total_net_pnl"] == 2
    assert out["expectancy"] == 1


def test_trading_friction_fails_when_gross_rows_omit_major_cost_fields():
    h = _hypothesis(domain="trading")
    matrix = build_test_matrix("US100 trading", {}, h)
    meta = _clean_meta()
    meta["split"]["chronological"] = True
    execution = {
        **meta,
        "kind": "trading",
        "trades": [{"gross_pnl": 5, "commission": 1} for _ in range(12)],
        "baseline_trades": [{"net_pnl": 0} for _ in range(12)],
        "starting_equity": 100,
        "falsified": False,
    }
    result = execute_quantitative_test(matrix, execution)
    assert result.friction["status"] == "FAIL"
    assert "spread_cost" in result.friction["missing_cost_fields"]
    assert "slippage" in result.friction["missing_cost_fields"]


def test_monte_carlo_trade_failure_is_deterministic_and_bounded():
    a = monte_carlo_trade_failure([2, 1, -1, 3, -2, 1, 2, -1], starting_equity=20, trials=1000, seed=42)
    b = monte_carlo_trade_failure([2, 1, -1, 3, -2, 1, 2, -1], starting_equity=20, trials=1000, seed=42)
    assert a == b
    assert 0 <= a["failure_probability"] <= 1


def test_parameter_robustness_and_ablation_are_measured_only_when_runs_supplied():
    matrix = build_test_matrix("model", {}, _hypothesis())
    execution = {
        **_clean_meta(),
        "executed": True,
        "sample_size": 100,
        "metrics": {"score": 0.8},
        "baseline_results": {"score": 0.5, "candidate_beats_baseline": True},
        "friction": {"status": "TESTED"},
        "falsified": False,
        "primary_metric": "score",
        "candidate_primary_metric": 0.8,
        "pass_threshold": 0.7,
        "parameter_runs": [{"score": 0.79}, {"score": 0.81}, {"score": 0.77}],
        "ablation_materiality": 0.02,
        "ablation_runs": [
            {"removed_component": "A", "score": 0.80},
            {"removed_component": "B", "score": 0.60},
        ],
    }
    result = execute_quantitative_test(matrix, execution)
    assert result.robustness["parameter_neighborhood"]["status"] == "TESTED"
    rows = result.ablations["rows"]
    assert rows[0]["recommendation"] == "REMOVE / simplify candidate"
    assert rows[1]["recommendation"] == "KEEP"


def test_critical_leakage_invalidates_even_good_metrics():
    matrix = build_test_matrix("model", {}, _hypothesis())
    execution = {
        **_clean_meta(),
        "executed": True,
        "sample_size": 1000,
        "metrics": {"score": 0.99},
        "baseline_results": {"candidate_beats_baseline": True},
        "friction": {"status": "TESTED"},
        "falsified": False,
        "primary_metric": "score",
        "pass_threshold": 0.8,
        "parameter_runs": [{"score": 0.95}, {"score": 0.96}],
    }
    execution["bias_flags"]["hidden_leakage"] = True
    result = execute_quantitative_test(matrix, execution)
    status, reason = decide_status(matrix, result, execution)
    assert status == FinalStatus.FAIL
    assert "contamination" in reason.lower()


def test_baseline_failure_rejects_unearned_complexity():
    matrix = build_test_matrix("model", {}, _hypothesis())
    execution = {
        **_clean_meta(),
        "executed": True,
        "sample_size": 100,
        "metrics": {"score": 0.6},
        "baseline_results": {"candidate_beats_baseline": False},
        "friction": {"status": "TESTED"},
        "falsified": False,
    }
    result = execute_quantitative_test(matrix, execution)
    status, reason = decide_status(matrix, result, execution)
    assert status == FinalStatus.FAIL
    assert "baseline" in reason.lower()


def test_explicit_falsification_boundary_produces_fail_not_category_wide_claim():
    matrix = build_test_matrix("model", {}, _hypothesis())
    execution = {
        **_clean_meta(),
        "executed": True,
        "sample_size": 100,
        "metrics": {"score": 0.9},
        "baseline_results": {"candidate_beats_baseline": True},
        "friction": {"status": "TESTED"},
        "falsified": True,
    }
    result = execute_quantitative_test(matrix, execution)
    status, reason = decide_status(matrix, result, execution)
    assert status == FinalStatus.FAIL
    assert matrix.falsification_rule in reason
    assert "all theories" not in reason.lower()


def test_full_pass_requires_baseline_robustness_friction_and_complete_audit():
    matrix = build_test_matrix("model", {}, _hypothesis())
    execution = {
        **_clean_meta(),
        "executed": True,
        "sample_size": 500,
        "metrics": {"score": 0.82},
        "baseline_results": {"score": 0.50, "candidate_beats_baseline": True},
        "friction": {"status": "TESTED", "net_of_costs": True},
        "falsified": False,
        "primary_metric": "score",
        "pass_threshold": 0.70,
        "parameter_runs": [{"score": 0.79}, {"score": 0.81}, {"score": 0.78}],
    }
    result = execute_quantitative_test(matrix, execution)
    status, _ = decide_status(matrix, result, execution)
    assert status == FinalStatus.PASS


def test_missing_robustness_downgrades_good_execution_to_conditional_pass():
    matrix = build_test_matrix("model", {}, _hypothesis())
    execution = {
        **_clean_meta(),
        "executed": True,
        "sample_size": 500,
        "metrics": {"score": 0.82},
        "baseline_results": {"candidate_beats_baseline": True},
        "friction": {"status": "TESTED"},
        "falsified": False,
    }
    result = execute_quantitative_test(matrix, execution)
    status, reason = decide_status(matrix, result, execution)
    assert status == FinalStatus.CONDITIONAL_PASS
    assert "robustness" in reason.lower()


def test_agent4_packet_never_hides_unknowns_and_preserves_scope_warning():
    packet = Agent3ValidationEngine().validate(
        "Does treatment work?", {}, {"hypotheses": [_hypothesis()]}
    )
    final = packet["14. FINAL VALIDATION PACKET FOR AGENT 4"]
    assert final["inconclusive"] == 1
    assert final["pass"] == 0
    assert "Planning is not execution." in final["do_not_overclaim"]
    assert packet["13. Unknown/unverified elements"]


def test_trading_test_matrix_contains_required_operational_and_friction_controls():
    matrix = build_test_matrix("US100 scalping strategy", {}, _hypothesis(domain="trading"))
    joined = " ".join(matrix.friction_plan).lower()
    for item in ("spread", "commission", "slippage", "latency", "news"):
        assert item in joined
    assert matrix.split_plan["ordering"] == "chronological"
    assert any("walk-forward" in x.lower() for x in matrix.robustness_plan)
    assert any("Step 1" in x for x in matrix.implementation_steps)
