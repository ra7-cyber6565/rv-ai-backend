from research_engine.hypothesis import HypothesisEngine


def test_rich_walk_forward_plan_populates_core_structure_from_explicit_text():
    text = """
    Setup: run an event-driven walk-forward backtest with untouched OOS folds.
    Dataset: US100 and XAUUSD 5 minute OHLCV bars from 2022 through 2025.
    Measured variables: profit factor, Sharpe ratio, max drawdown and expectancy after spread, slippage and commission.
    Baseline: compare against a no-trade baseline.
    Success if: out-of-sample expectancy stays positive after trading costs.
    Fail if: out-of-sample expectancy is zero or negative after trading costs.
    """

    exp = HypothesisEngine._parse_experiment(text)

    assert exp is not None
    assert exp.experiment_type == "trading backtest / validation"
    assert "US100" in exp.system_or_sample
    assert "profit factor" in exp.measured_quantity.lower()
    assert "success if" in exp.expected_signal.lower()
    assert "fail if" in exp.null_result.lower()
    assert exp.is_complete is True


def test_vague_backtest_request_stays_structurally_incomplete():
    exp = HypothesisEngine._parse_experiment(
        "Backtest this US100 strategy and tell me whether it works in practice."
    )

    assert exp is not None
    assert exp.experiment_type == "trading backtest / validation"
    assert exp.is_complete is False
    assert not exp.measured_quantity
    assert not exp.expected_signal
    assert not exp.null_result


def test_trading_metrics_do_not_create_unstated_success_or_failure_thresholds():
    exp = HypothesisEngine._parse_experiment(
        "Run a walk-forward backtest on XAUUSD OHLCV bars and measure profit factor, "
        "Sharpe ratio, max drawdown and expectancy after spread and slippage."
    )

    assert exp is not None
    assert exp.measured_quantity
    assert exp.expected_signal == ""
    assert exp.null_result == ""
    assert exp.is_complete is False


def test_non_trading_lab_plan_keeps_generic_parser_behavior():
    exp = HypothesisEngine._parse_experiment(
        "Run a lab experiment. Setup: use a four-probe apparatus. "
        "Sample: ten material samples. Measurement: resistance. "
        "Expected signal: resistance drop. Null result: no resistance drop."
    )

    assert exp is not None
    assert exp.experiment_type == "lab experiment"
    assert exp.experiment_type != "trading backtest / validation"
