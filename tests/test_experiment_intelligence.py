import math

import pytest

from research_engine.experiment_intelligence import (
    ExperimentDesign,
    choose_active_learning_step,
    choose_discriminating_experiment,
    choose_minimum_cost_experiment,
    rank_discriminating_experiments,
    score_experiment,
    stop_active_learning,
    update_posterior,
)


def _priors():
    return {"H1": 0.5, "H2": 0.5}


def _strong(eid="strong", cost=100.0, *, safety="APPROVED", feasible=True):
    return ExperimentDesign(
        experiment_id=eid,
        outcome_likelihoods={
            "H1": {"positive": 0.9, "negative": 0.1},
            "H2": {"positive": 0.1, "negative": 0.9},
        },
        monetary_cost=cost,
        duration_hours=2.0,
        operational_risk=0.1,
        safety_status=safety,
        feasible=feasible,
        measurement="pre-registered binary assay",
    )


def _weak(eid="weak", cost=10.0):
    return ExperimentDesign(
        experiment_id=eid,
        outcome_likelihoods={
            "H1": {"positive": 0.55, "negative": 0.45},
            "H2": {"positive": 0.45, "negative": 0.55},
        },
        monetary_cost=cost,
        duration_hours=1.0,
        operational_risk=0.05,
    )


def test_strong_discriminating_experiment_has_more_information_and_pair_separation():
    strong = score_experiment(_priors(), _strong())
    weak = score_experiment(_priors(), _weak())
    assert strong.information_gain_bits > weak.information_gain_bits
    assert strong.weakest_pair_separation > weak.weakest_pair_separation
    assert strong.normalized_information_gain > 0
    assert strong.truth_proven is False
    assert sum(row.predictive_probability for row in strong.outcome_posteriors) == pytest.approx(1.0)
    for row in strong.outcome_posteriors:
        assert sum(row.posterior.values()) == pytest.approx(1.0)


def test_identical_likelihoods_have_zero_information_gain():
    design = ExperimentDesign(
        experiment_id="uninformative",
        outcome_likelihoods={
            "H1": {"yes": 0.6, "no": 0.4},
            "H2": {"yes": 0.6, "no": 0.4},
        },
        monetary_cost=1.0,
    )
    score = score_experiment(_priors(), design)
    assert score.information_gain_bits == pytest.approx(0.0, abs=1e-12)
    assert score.weakest_pair_separation == pytest.approx(0.0)
    with pytest.raises(ValueError, match="no eligible informative"):
        choose_active_learning_step(_priors(), [design], min_information_gain_bits=0.001)


def test_discriminating_choice_excludes_blocked_review_and_infeasible_designs():
    blocked = _strong("blocked", cost=1.0, safety="BLOCKED")
    review = _strong("review", cost=1.0, safety="REVIEW_REQUIRED")
    infeasible = _strong("infeasible", cost=1.0, feasible=False)
    good = _weak("good", cost=50.0)
    recommendation = choose_discriminating_experiment(
        _priors(),
        [blocked, review, infeasible, good],
        min_information_gain_bits=0.001,
    )
    assert recommendation.experiment_id == "good"
    assert recommendation.planning_only is True
    assert recommendation.real_world_approval_implied is False
    rejected = dict(recommendation.rejected)
    assert rejected["blocked"].startswith("ineligible")
    assert rejected["review"].startswith("ineligible")
    assert rejected["infeasible"].startswith("ineligible")


def test_minimum_cost_planner_does_not_pick_cheapest_if_it_misses_scientific_floor():
    too_weak = _weak("cheap-weak", cost=1.0)
    strong_expensive = _strong("strong-expensive", cost=100.0)
    strong_cheaper = _strong("strong-cheaper", cost=20.0)
    recommendation = choose_minimum_cost_experiment(
        _priors(),
        [too_weak, strong_expensive, strong_cheaper],
        min_information_gain_bits=0.3,
        min_weakest_pair_separation=0.5,
        max_operational_risk=0.2,
        max_duration_hours=3.0,
    )
    assert recommendation.experiment_id == "strong-cheaper"
    assert recommendation.score.monetary_cost == 20.0
    assert dict(recommendation.rejected)["cheap-weak"] in {
        "insufficient_information_gain",
        "insufficient_pair_separation",
    }


def test_active_learning_balances_information_against_declared_resources():
    expensive = _strong("expensive", cost=1000.0)
    efficient = ExperimentDesign(
        experiment_id="efficient",
        outcome_likelihoods={
            "H1": {"positive": 0.8, "negative": 0.2},
            "H2": {"positive": 0.2, "negative": 0.8},
        },
        monetary_cost=10.0,
        duration_hours=1.0,
        operational_risk=0.05,
    )
    recommendation = choose_active_learning_step(
        _priors(), [expensive, efficient], duration_cost_per_hour=5.0, risk_cost=100.0
    )
    assert recommendation.experiment_id == "efficient"
    assert recommendation.score.information_gain_bits > 0


def test_posterior_update_moves_belief_toward_hypothesis_that_predicted_outcome():
    posterior = update_posterior(_priors(), _strong(), "positive")
    assert posterior["H1"] == pytest.approx(0.9)
    assert posterior["H2"] == pytest.approx(0.1)
    assert sum(posterior.values()) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="not predeclared"):
        update_posterior(_priors(), _strong(), "post-hoc-outcome")


def test_zero_probability_post_hoc_surprise_fails_instead_of_dividing_by_zero():
    design = ExperimentDesign(
        experiment_id="zero-surprise",
        outcome_likelihoods={
            "H1": {"seen": 1.0, "impossible": 0.0},
            "H2": {"seen": 1.0, "impossible": 0.0},
        },
        monetary_cost=1.0,
    )
    with pytest.raises(ValueError, match="zero probability"):
        update_posterior(_priors(), design, "impossible")


def test_active_learning_stop_rule_is_explicit_and_never_calls_dominance_truth():
    stop = stop_active_learning(
        {"H1": 0.96, "H2": 0.04},
        [_strong()],
        posterior_dominance=0.95,
    )
    assert stop["stop"] is True
    assert stop["reason"] == "posterior_dominance_threshold_reached"
    assert stop["truth_proven"] is False

    continue_result = stop_active_learning(
        _priors(), [_strong()], posterior_dominance=0.95, min_remaining_information_gain_bits=0.01
    )
    assert continue_result["stop"] is False
    assert continue_result["reason"] == "continue_active_learning"


def test_invalid_probability_tables_and_priors_fail_closed():
    bad_sum = ExperimentDesign(
        experiment_id="bad-sum",
        outcome_likelihoods={
            "H1": {"a": 0.8, "b": 0.8},
            "H2": {"a": 0.5, "b": 0.5},
        },
        monetary_cost=1.0,
    )
    with pytest.raises(ValueError, match="sum to 1"):
        score_experiment(_priors(), bad_sum)

    mismatched_outcomes = ExperimentDesign(
        experiment_id="bad-outcomes",
        outcome_likelihoods={
            "H1": {"a": 0.5, "b": 0.5},
            "H2": {"a": 0.5, "c": 0.5},
        },
        monetary_cost=1.0,
    )
    with pytest.raises(ValueError, match="same outcome"):
        score_experiment(_priors(), mismatched_outcomes)

    with pytest.raises(ValueError, match="positive prior"):
        score_experiment({"H1": 1.0, "H2": 0.0}, _strong())
    with pytest.raises(ValueError, match="negative"):
        score_experiment({"H1": 1.1, "H2": -0.1}, _strong())


def test_ranking_is_deterministic_and_assumptions_hash_changes_with_inputs():
    first = rank_discriminating_experiments(_priors(), [_weak(), _strong()])
    second = rank_discriminating_experiments(_priors(), [_strong(), _weak()])
    assert [item.experiment_id for item in first] == [item.experiment_id for item in second]
    assert [item.assumptions_hash for item in first] == [item.assumptions_hash for item in second]
    changed = score_experiment({"H1": 0.7, "H2": 0.3}, _strong())
    baseline = score_experiment(_priors(), _strong())
    assert changed.assumptions_hash != baseline.assumptions_hash
    assert math.isfinite(changed.information_gain_bits)
