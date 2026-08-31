import pytest

from research_engine.statistical_validation import (
    ablation_analysis,
    benjamini_hochberg,
    detect_temporal_leakage,
    holm_bonferroni,
    monte_carlo_return_paths,
    overfit_diagnostic,
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


def test_ablation_identifies_component_dependency_without_claiming_causality():
    result = ablation_analysis(
        100.0,
        {"core": 70.0, "helper": 95.0, "noise": 105.0},
        min_relative_degradation=0.10,
    )
    assert result.critical_components == ("core",)
    effects = {item.component: item for item in result.effects}
    assert effects["core"].degradation == 30.0
    assert effects["core"].relative_degradation == pytest.approx(0.30)
    assert effects["core"].critical is True
    assert effects["helper"].critical is False
    assert effects["noise"].improved_when_removed is True
    assert result.causal_importance_proven is False
    assert result.interaction_effects_tested is False
    assert result.truth_proven is False


def test_ablation_supports_lower_is_better_metrics():
    result = ablation_analysis(
        0.20,
        {"calibration": 0.40, "regularizer": 0.21, "bad_component": 0.10},
        higher_is_better=False,
        min_relative_degradation=0.20,
    )
    assert result.critical_components == ("calibration",)
    effects = {item.component: item for item in result.effects}
    assert effects["calibration"].degradation == pytest.approx(0.20)
    assert effects["bad_component"].improved_when_removed is True


def test_ablation_rejects_normalized_duplicate_names_nonfinite_and_empty_inputs():
    with pytest.raises(ValueError, match="unique after normalization"):
        ablation_analysis(1.0, {"A": 0.8, " A ": 0.7})
    with pytest.raises(ValueError, match="non-empty mapping"):
        ablation_analysis(1.0, {})
    with pytest.raises(ValueError, match="must be finite"):
        ablation_analysis(1.0, {"A": float("nan")})
    with pytest.raises(ValueError, match="boolean"):
        ablation_analysis(1.0, {"A": 0.8}, higher_is_better=1)


def test_overfit_diagnostic_flags_large_gap_without_proving_overfitting():
    result = overfit_diagnostic(
        [100.0, 98.0, 102.0],
        [70.0, 72.0, 68.0],
        max_relative_gap=0.10,
    )
    assert result.train_mean == pytest.approx(100.0)
    assert result.validation_mean == pytest.approx(70.0)
    assert result.generalization_gap == pytest.approx(30.0)
    assert result.relative_gap == pytest.approx(0.30)
    assert result.suspicious is True
    assert result.overfitting_proven is False
    assert result.distribution_shift_ruled_out is False
    assert result.truth_proven is False


def test_overfit_diagnostic_stable_and_lower_is_better_cases():
    stable = overfit_diagnostic([0.90, 0.91, 0.89], [0.88, 0.90, 0.89])
    assert stable.suspicious is False

    lower = overfit_diagnostic(
        [0.10, 0.12, 0.11],
        [0.30, 0.28, 0.32],
        higher_is_better=False,
        max_relative_gap=0.20,
    )
    assert lower.suspicious is True
    assert lower.generalization_gap > 0
    assert lower.overfitting_proven is False


def test_overfit_diagnostic_invalid_inputs_fail_closed():
    with pytest.raises(ValueError, match="same length"):
        overfit_diagnostic([1.0, 2.0], [1.0])
    with pytest.raises(ValueError, match="at least two"):
        overfit_diagnostic([1.0], [1.0])
    with pytest.raises(ValueError, match="must be finite"):
        overfit_diagnostic([1.0, float("inf")], [1.0, 1.0])
    with pytest.raises(ValueError, match="boolean"):
        overfit_diagnostic([1.0, 1.0], [1.0, 1.0], higher_is_better="yes")


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
