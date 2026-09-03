"""AI-2 trading validation resource-budget regressions. Pure offline pytest."""
from __future__ import annotations

from research_engine.validation_limits import (
    MAX_FRICTION_SCENARIOS,
    MAX_MONTE_CARLO_SIMULATIONS,
    MAX_MONTE_CARLO_WORK_UNITS,
    MAX_TRADES,
    MAX_TRADING_REGIMES,
    MAX_TRADING_STRESS_WORK_UNITS,
    RESOURCE_LIMIT_STATUS,
)
from research_engine.validation_trading import (
    edge_decay_analysis,
    monte_carlo_trade_paths,
    trade_pnl_series,
    trading_friction_stress,
    trading_metrics,
    trading_regime_metrics,
)


def _assert_resource_refusal(result):
    assert result["status"] == RESOURCE_LIMIT_STATUS
    assert result["scientific_result_observed"] is False
    assert result["silently_clamped"] is False
    assert "hard" in result["reason"] or "refused" in result["reason"]


def _gross_trade(regime: str = "r"):
    return {
        "gross_pnl": 2.0,
        "commission": 0.1,
        "spread_cost": 0.1,
        "slippage_cost": 0.1,
        "financing_cost": 0.0,
        "tax_cost": 0.0,
        "regime": regime,
    }


def test_trade_series_rejects_more_than_hard_trade_cap():
    result = trade_pnl_series([1.0] * (MAX_TRADES + 1))
    _assert_resource_refusal(result)
    assert result["field"] == "trades"


def test_trade_series_bounds_unsized_iterators_without_full_materialization():
    result = trade_pnl_series((1.0 for _ in range(MAX_TRADES + 1)))
    _assert_resource_refusal(result)
    assert result["field"] == "trades"


def test_metrics_propagate_trade_resource_refusal_instead_of_partial_result():
    result = trading_metrics([1.0] * (MAX_TRADES + 1))
    _assert_resource_refusal(result)
    assert "sample_size" not in result


def test_monte_carlo_rejects_simulation_count_above_cap_without_clamping():
    result = monte_carlo_trade_paths([1.0, -0.5], simulations=MAX_MONTE_CARLO_SIMULATIONS + 1)
    _assert_resource_refusal(result)
    assert result["field"] == "monte_carlo_simulations"
    assert result["requested"] == MAX_MONTE_CARLO_SIMULATIONS + 1


def test_monte_carlo_rejects_product_work_budget_before_sampling():
    # Pick the smallest sample that makes the default 5,000 simulations exceed
    # the hard work budget. No stochastic loop should start.
    sample_size = MAX_MONTE_CARLO_WORK_UNITS // 5000 + 1
    result = monte_carlo_trade_paths([1.0, -1.0] * ((sample_size + 1) // 2), simulations=5000)
    _assert_resource_refusal(result)
    assert result["field"] == "monte_carlo_simulations"
    assert "work=" in result["reason"]


def test_small_monte_carlo_still_executes_exact_requested_count():
    result = monte_carlo_trade_paths([1.0, -0.5, 0.25, -0.1], simulations=100, seed=7)
    assert result["status"] == "TEST PERFORMED"
    assert result["simulations"] == 100
    assert result["seed"] == 7


def test_regime_cardinality_is_bounded():
    rows = [{"net_pnl": 1.0, "regime": f"regime-{i}"}
            for i in range(MAX_TRADING_REGIMES + 1)]
    result = trading_regime_metrics(rows)
    _assert_resource_refusal(result)
    assert result["field"] == "trading_regimes"


def test_friction_scenario_count_is_bounded():
    result = trading_friction_stress(
        [_gross_trade()],
        [1.0] * (MAX_FRICTION_SCENARIOS + 1),
    )
    _assert_resource_refusal(result)
    assert result["field"] == "friction_scenarios"


def test_friction_trade_times_scenario_work_is_bounded():
    # Repeating one immutable-looking fixture reference is enough: the function
    # only reads mappings, and the check happens before the expensive nested loop.
    scenarios = [1.0] * MAX_FRICTION_SCENARIOS
    n = MAX_TRADING_STRESS_WORK_UNITS // MAX_FRICTION_SCENARIOS + 1
    result = trading_friction_stress([_gross_trade()] * n, scenarios)
    _assert_resource_refusal(result)
    assert result["field"] == "friction_stress_work_units"


def test_friction_stress_does_not_repeat_bootstrap_per_scenario():
    result = trading_friction_stress([_gross_trade(), _gross_trade()], [1.0, 1.5])
    assert result["status"] == "TEST PERFORMED"
    assert len(result["scenarios"]) == 2
    for scenario in result["scenarios"]:
        ci = scenario["metrics"]["expectancy_bootstrap_ci"]
        assert ci["status"] == "UNKNOWN"
        assert "not repeated" in ci["reason"]


def test_edge_decay_rejects_oversized_input_and_invalid_window_safely():
    too_many = edge_decay_analysis([1.0] * (MAX_TRADES + 1), window=10)
    _assert_resource_refusal(too_many)
    assert too_many["field"] == "ordered_trade_outcomes"

    assert edge_decay_analysis([1, 2, 3, 4], window=True)["status"] == "UNKNOWN"
    assert edge_decay_analysis([1, 2, 3, 4], window=2.5)["status"] == "UNKNOWN"
