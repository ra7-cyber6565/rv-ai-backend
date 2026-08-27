import pytest

from research_engine.statistical_validation import (
    benjamini_hochberg,
    detect_temporal_leakage,
    holm_bonferroni,
    monte_carlo_return_paths,
    paired_placebo_permutation_test,
    population_stability_index,
    sensitivity_plateau,
    walk_forward_splits,
)


def test_benjamini_hochberg_preserves_order_and_controls_fdr():
    result = benjamini_hochberg([0.01, 0.04, 0.03, 0.20], alpha=0.05)
    assert result.method == "benjamini-hochberg"
    assert result.adjusted_p_values == pytest.approx((0.04, 0.053333333333, 0.053333333333, 0.2))
    assert result.rejected == (True, False, False, False)


def test_holm_bonferroni_is_step_down_and_fail_closed_after_first_non_rejection():
    result = holm_bonferroni([0.01, 0.03, 0.20], alpha=0.05)
    assert result.adjusted_p_values == (0.03, 0.06, 0.2)
    assert result.rejected == (True, False, False)


def test_placebo_permutation_is_seeded_reproducible_and_detects_large_paired_effect():
    observed = [1.0] * 10
    placebo = [0.0] * 10
    one = paired_placebo_permutation_test(observed, placebo, permutations=5000, seed=7)
    two = paired_placebo_permutation_test(observed, placebo, permutations=5000, seed=7)
    assert one == two
    assert one.observed_effect == 1.0
    assert one.p_value < 0.01


def test_monte_carlo_paths_are_reproducible_and_report_drawdown_distribution():
    returns = [0.02, -0.01, 0.015, -0.005, 0.01]
    one = monte_carlo_return_paths(
        returns, paths=500, horizon=20, seed=123, initial_equity=1.0, ruin_equity=0.5
    )
    two = monte_carlo_return_paths(
        returns, paths=500, horizon=20, seed=123, initial_equity=1.0, ruin_equity=0.5
    )
    assert one == two
    assert one.terminal_equity_p05 <= one.median_terminal_equity <= one.terminal_equity_p95
    assert 0.0 <= one.median_max_drawdown <= one.max_drawdown_p95 <= 1.0
    assert 0.0 <= one.ruin_probability <= 1.0


def test_sensitivity_plateau_distinguishes_broad_region_from_brittle_spike():
    broad = sensitivity_plateau({1: 80, 2: 95, 3: 100, 4: 96, 5: 70})
    assert broad.best_parameter == 3.0
    assert broad.plateau_min == 2.0
    assert broad.plateau_max == 4.0
    assert broad.plateau_fraction == 0.5
    assert broad.cliff_detected is False

    spike = sensitivity_plateau({1: 50, 2: 55, 3: 100, 4: 50, 5: 45})
    assert spike.plateau_min == 3.0
    assert spike.plateau_max == 3.0
    assert spike.cliff_detected is True
    assert spike.local_drop_fraction >= 0.45


def test_temporal_leakage_flags_future_feature_bad_target_and_non_monotonic_time():
    rows = [
        {"event_time": 10, "feature_available_time": 9, "target_time": 11},
        {"event_time": 12, "feature_available_time": 13, "target_time": 14},
        {"event_time": 11, "feature_available_time": 10, "target_time": 11},
    ]
    findings = detect_temporal_leakage(rows)
    kinds = {(item.index, item.kind) for item in findings}
    assert (1, "LOOKAHEAD_FEATURE") in kinds
    assert (2, "NON_MONOTONIC_EVENT_TIME") in kinds
    assert (2, "INVALID_TARGET_CHRONOLOGY") in kinds


def test_clean_temporal_rows_have_no_leakage_findings():
    rows = [
        {"event_time": 10, "feature_available_time": 10, "target_time": 11},
        {"event_time": 11, "feature_available_time": 10.5, "target_time": 12},
    ]
    assert detect_temporal_leakage(rows) == ()


def test_walk_forward_splits_never_overlap_each_paired_train_and_test():
    splits = walk_forward_splits(100, min_train=40, test_size=10, step=10)
    assert splits[0] == ((0, 40), (40, 50))
    assert splits[-1] == ((0, 90), (90, 100))
    assert len(splits) == 6
    for train, test in splits:
        assert train[1] <= test[0]
        assert train[0] < train[1]
        assert test[0] < test[1]

    rolling = walk_forward_splits(70, min_train=30, test_size=10, step=10, expanding=False)
    assert rolling[1] == ((10, 40), (40, 50))


def test_population_stability_index_is_zero_for_same_sample_and_rises_for_shift():
    reference = list(range(100))
    same = list(range(100))
    shifted = list(range(100, 200))
    assert population_stability_index(reference, same, bins=10) == pytest.approx(0.0)
    assert population_stability_index(reference, shifted, bins=10) > 0.5


@pytest.mark.parametrize("values", [[-0.1, 0.2], [0.1, 1.2], [float("nan"), 0.1]])
def test_multiple_testing_rejects_invalid_p_values(values):
    with pytest.raises(ValueError):
        benjamini_hochberg(values)


def test_invalid_statistical_inputs_fail_closed():
    with pytest.raises(ValueError):
        paired_placebo_permutation_test([1], [0])
    with pytest.raises(ValueError):
        monte_carlo_return_paths([-1.0, 0.1], paths=100)
    with pytest.raises(ValueError):
        sensitivity_plateau({1: 1, 2: 2})
    with pytest.raises(ValueError):
        walk_forward_splits(20, min_train=15, test_size=10)
    with pytest.raises(ValueError):
        population_stability_index([1, 2], [1, 2], bins=10)
