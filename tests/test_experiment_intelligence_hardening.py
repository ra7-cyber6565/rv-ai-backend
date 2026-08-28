import pytest

from research_engine.experiment_intelligence import (
    ExperimentDesign,
    choose_active_learning_step,
    choose_discriminating_experiment,
    rank_discriminating_experiments,
    stop_active_learning,
    update_posterior,
    update_posterior_with_receipt,
)


def _priors():
    return {"H1": 0.5, "H2": 0.5}


def _design(eid, h1_yes, h2_yes, *, cost=10.0, safety="APPROVED", feasible=True):
    return ExperimentDesign(
        experiment_id=eid,
        outcome_likelihoods={
            "H1": {"yes": h1_yes, "no": 1.0 - h1_yes},
            "H2": {"yes": h2_yes, "no": 1.0 - h2_yes},
        },
        monetary_cost=cost,
        duration_hours=1.0,
        operational_risk=0.05,
        safety_status=safety,
        feasible=feasible,
        measurement="pre-registered binary measurement",
    )


def test_discriminating_recommendation_preserves_complete_rejection_audit():
    winner = _design("winner", 0.8, 0.2, cost=20.0)
    lower = _design("lower", 0.7, 0.3, cost=10.0)
    blocked = _design("blocked", 0.99, 0.01, cost=1.0, safety="BLOCKED")
    review = _design("review", 0.99, 0.01, cost=1.0, safety="REVIEW_REQUIRED")
    infeasible = _design("infeasible", 0.99, 0.01, cost=1.0, feasible=False)

    result = choose_discriminating_experiment(
        _priors(),
        [blocked, lower, infeasible, winner, review],
        min_information_gain_bits=0.01,
    )
    assert result.experiment_id == "winner"
    rejected = dict(result.rejected)
    assert rejected["blocked"] == "ineligible:BLOCKED"
    assert rejected["review"] == "ineligible:REVIEW_REQUIRED"
    assert rejected["infeasible"] == "ineligible:APPROVED"
    assert rejected["lower"] == "lower_discrimination_rank"
    assert result.planning_only is True
    assert result.real_world_approval_implied is False


def test_posterior_receipt_is_deterministic_auditable_and_never_claims_truth():
    design = _design("assay", 0.9, 0.1)
    first = update_posterior_with_receipt(_priors(), design, "yes")
    second = update_posterior_with_receipt(_priors(), design, "yes")
    assert first.posterior["H1"] == pytest.approx(0.9)
    assert first.posterior["H2"] == pytest.approx(0.1)
    assert first.update_hash == second.update_hash
    assert first.assumptions_hash == second.assumptions_hash
    assert len(first.update_hash) == 64
    assert len(first.assumptions_hash) == 64
    assert first.posterior_entropy_bits < first.prior_entropy_bits
    assert first.truth_proven is False
    assert first.experiment_executed_by_this_function is False
    assert update_posterior(_priors(), design, "yes") == first.posterior

    opposite = update_posterior_with_receipt(_priors(), design, "no")
    assert opposite.update_hash != first.update_hash
    assert opposite.assumptions_hash == first.assumptions_hash

    changed_prior = update_posterior_with_receipt({"H1": 0.7, "H2": 0.3}, design, "yes")
    assert changed_prior.assumptions_hash != first.assumptions_hash
    assert changed_prior.update_hash != first.update_hash


def test_no_remaining_experiment_is_an_explicit_stop_not_an_exception():
    result = stop_active_learning(
        _priors(),
        [],
        posterior_dominance=0.95,
        min_remaining_information_gain_bits=0.01,
    )
    assert result["stop"] is True
    assert result["reason"] == "no_remaining_experiment_clears_information_gain_floor"
    assert result["best_remaining_information_gain_bits"] == 0.0
    assert result["truth_proven"] is False


def test_trimmed_duplicate_experiment_ids_fail_closed():
    with pytest.raises(ValueError, match="ids must be unique"):
        rank_discriminating_experiments(
            _priors(),
            [
                _design("same", 0.8, 0.2),
                _design(" same ", 0.7, 0.3),
            ],
        )


def test_review_required_and_blocked_designs_cannot_win_active_learning():
    approved = _design("approved", 0.7, 0.3, cost=100.0)
    review = _design("review", 0.99, 0.01, cost=1.0, safety="REVIEW_REQUIRED")
    blocked = _design("blocked", 0.99, 0.01, cost=1.0, safety="BLOCKED")
    result = choose_active_learning_step(_priors(), [review, blocked, approved])
    assert result.experiment_id == "approved"
    rejected = dict(result.rejected)
    assert rejected["review"].startswith("ineligible")
    assert rejected["blocked"].startswith("ineligible")
