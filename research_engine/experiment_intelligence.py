"""Bayesian experiment selection for discriminating hypotheses.

This module answers a narrower question than the hypothesis generator: given a
set of explicit competing hypotheses, explicit prior weights, and explicit
outcome likelihoods for candidate experiments, which experiment is expected to
separate the hypotheses most, which acceptable experiment is cheapest, and how
should belief weights update after an observed outcome?

The probability inputs are model assumptions, not measured truth. Expected
information gain is therefore a planning score, not a probability that a
hypothesis is correct. Real-world safety/ethics approval remains external; an
experiment marked ``REVIEW_REQUIRED`` or ``BLOCKED`` is excluded by default.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Tuple


_EPS = 1e-12
_SAFETY_STATES = {"APPROVED", "REVIEW_REQUIRED", "BLOCKED"}


def _finite(value: float, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _canonical_hash(value: object) -> str:
    body = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _entropy_bits(probabilities: Sequence[float]) -> float:
    return -sum(
        probability * math.log2(probability)
        for probability in probabilities
        if probability > 0.0
    )


def _normalize_priors(priors: Mapping[str, float]) -> Dict[str, float]:
    if len(priors) < 2:
        raise ValueError("at least two competing hypotheses are required")
    clean: Dict[str, float] = {}
    for hypothesis_id, value in priors.items():
        hid = str(hypothesis_id or "").strip()
        if not hid or len(hid) > 200:
            raise ValueError("hypothesis ids must be non-empty and bounded")
        if hid in clean:
            raise ValueError("duplicate hypothesis id")
        number = _finite(value, f"prior.{hid}")
        if number < 0:
            raise ValueError("prior weights cannot be negative")
        clean[hid] = number
    total = sum(clean.values())
    if total <= 0:
        raise ValueError("at least one prior weight must be positive")
    normalized = {hid: value / total for hid, value in clean.items()}
    # A zero prior can never recover under ordinary Bayes. Require explicit
    # non-zero support for every hypothesis that the planner is asked to compare.
    if any(value <= 0 for value in normalized.values()):
        raise ValueError("every competing hypothesis must have positive prior support")
    return normalized


@dataclass(frozen=True)
class ExperimentDesign:
    experiment_id: str
    outcome_likelihoods: Mapping[str, Mapping[str, float]]
    monetary_cost: float
    duration_hours: float = 0.0
    operational_risk: float = 0.0
    safety_status: str = "APPROVED"
    feasible: bool = True
    measurement: str = ""
    notes: str = ""

    def validate(self, hypothesis_ids: Sequence[str]) -> Tuple[str, ...]:
        eid = str(self.experiment_id or "").strip()
        if not eid or len(eid) > 200:
            raise ValueError("experiment_id is required and bounded")
        cost = _finite(self.monetary_cost, "monetary_cost")
        duration = _finite(self.duration_hours, "duration_hours")
        risk = _finite(self.operational_risk, "operational_risk")
        if cost < 0 or duration < 0:
            raise ValueError("cost and duration cannot be negative")
        if not 0 <= risk <= 1:
            raise ValueError("operational_risk must be in [0,1]")
        safety = str(self.safety_status or "").strip().upper()
        if safety not in _SAFETY_STATES:
            raise ValueError("unsupported safety_status")

        expected_hypotheses = set(hypothesis_ids)
        if set(self.outcome_likelihoods) != expected_hypotheses:
            raise ValueError("likelihood table must contain every hypothesis exactly once")
        outcome_sets = []
        for hid in hypothesis_ids:
            row = self.outcome_likelihoods[hid]
            if not isinstance(row, Mapping) or len(row) < 2:
                raise ValueError("each hypothesis needs at least two possible outcomes")
            cleaned_outcomes = {str(outcome or "").strip() for outcome in row}
            if "" in cleaned_outcomes or len(cleaned_outcomes) != len(row):
                raise ValueError("outcome labels must be unique and non-empty")
            total = 0.0
            for outcome, value in row.items():
                probability = _finite(value, f"likelihood.{hid}.{outcome}")
                if not 0 <= probability <= 1:
                    raise ValueError("likelihood probabilities must be in [0,1]")
                total += probability
            if not math.isclose(total, 1.0, rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError("likelihoods for each hypothesis must sum to 1")
            outcome_sets.append(cleaned_outcomes)
        if any(outcomes != outcome_sets[0] for outcomes in outcome_sets[1:]):
            raise ValueError("all hypotheses must define the same outcome labels")
        return tuple(sorted(outcome_sets[0]))


@dataclass(frozen=True)
class OutcomePosterior:
    outcome: str
    predictive_probability: float
    posterior: Mapping[str, float]
    entropy_bits: float


@dataclass(frozen=True)
class ExperimentScore:
    experiment_id: str
    prior_entropy_bits: float
    expected_posterior_entropy_bits: float
    information_gain_bits: float
    normalized_information_gain: float
    weakest_pair_separation: float
    mean_pair_separation: float
    monetary_cost: float
    duration_hours: float
    operational_risk: float
    cost_efficiency: float
    utility: float
    feasible: bool
    safety_status: str
    eligible: bool
    outcome_posteriors: Tuple[OutcomePosterior, ...]
    assumptions_hash: str
    truth_proven: bool = False


@dataclass(frozen=True)
class ExperimentRecommendation:
    experiment_id: str
    reason: str
    score: ExperimentScore
    rejected: Tuple[Tuple[str, str], ...]
    planning_only: bool = True
    real_world_approval_implied: bool = False


def _pairwise_separation(
    experiment: ExperimentDesign,
    hypothesis_ids: Sequence[str],
    outcomes: Sequence[str],
    priors: Mapping[str, float],
) -> Tuple[float, float]:
    separations = []
    weights = []
    for index, left in enumerate(hypothesis_ids):
        for right in hypothesis_ids[index + 1:]:
            # Total variation distance.  0 = indistinguishable outcome models,
            # 1 = perfectly separating models.
            distance = 0.5 * sum(
                abs(
                    float(experiment.outcome_likelihoods[left][outcome])
                    - float(experiment.outcome_likelihoods[right][outcome])
                )
                for outcome in outcomes
            )
            separations.append(distance)
            weights.append(priors[left] * priors[right])
    weakest = min(separations) if separations else 0.0
    weighted_total = sum(weights)
    mean = (
        sum(distance * weight for distance, weight in zip(separations, weights))
        / weighted_total
        if weighted_total > 0
        else 0.0
    )
    return weakest, mean


def score_experiment(
    priors: Mapping[str, float],
    experiment: ExperimentDesign,
    *,
    duration_cost_per_hour: float = 0.0,
    risk_cost: float = 0.0,
    allow_review_required: bool = False,
) -> ExperimentScore:
    """Calculate expected information gain and separation for one design."""
    normalized = _normalize_priors(priors)
    hypothesis_ids = tuple(sorted(normalized))
    outcomes = experiment.validate(hypothesis_ids)
    duration_weight = _finite(duration_cost_per_hour, "duration_cost_per_hour")
    risk_weight = _finite(risk_cost, "risk_cost")
    if duration_weight < 0 or risk_weight < 0:
        raise ValueError("cost weights cannot be negative")

    prior_entropy = _entropy_bits(tuple(normalized.values()))
    posterior_rows = []
    expected_entropy = 0.0
    for outcome in outcomes:
        predictive = sum(
            normalized[hid] * float(experiment.outcome_likelihoods[hid][outcome])
            for hid in hypothesis_ids
        )
        if predictive <= _EPS:
            posterior = dict(normalized)
            entropy = prior_entropy
            predictive = 0.0
        else:
            posterior = {
                hid: (
                    normalized[hid]
                    * float(experiment.outcome_likelihoods[hid][outcome])
                    / predictive
                )
                for hid in hypothesis_ids
            }
            entropy = _entropy_bits(tuple(posterior.values()))
            expected_entropy += predictive * entropy
        posterior_rows.append(OutcomePosterior(
            outcome=outcome,
            predictive_probability=predictive,
            posterior=posterior,
            entropy_bits=entropy,
        ))

    information_gain = max(0.0, prior_entropy - expected_entropy)
    normalized_gain = (
        information_gain / prior_entropy if prior_entropy > _EPS else 0.0
    )
    weakest, mean = _pairwise_separation(
        experiment, hypothesis_ids, outcomes, normalized
    )
    cost = float(experiment.monetary_cost)
    duration = float(experiment.duration_hours)
    risk = float(experiment.operational_risk)
    effective_cost = cost + duration * duration_weight + risk * risk_weight
    # Zero-cost computational experiments are allowed. Avoid an artificial
    # infinity while still ranking positive information above zero information.
    cost_efficiency = information_gain / max(effective_cost, 1e-9)
    utility = information_gain * (0.5 + 0.5 * mean) / max(effective_cost, 1e-9)
    safety = str(experiment.safety_status).strip().upper()
    safety_eligible = safety == "APPROVED" or (
        allow_review_required and safety == "REVIEW_REQUIRED"
    )
    eligible = bool(experiment.feasible and safety_eligible and safety != "BLOCKED")
    assumptions_hash = _canonical_hash({
        "priors": normalized,
        "experiment_id": experiment.experiment_id,
        "likelihoods": experiment.outcome_likelihoods,
        "cost": cost,
        "duration": duration,
        "risk": risk,
        "safety": safety,
        "feasible": bool(experiment.feasible),
        "duration_cost_per_hour": duration_weight,
        "risk_cost": risk_weight,
    })
    return ExperimentScore(
        experiment_id=experiment.experiment_id,
        prior_entropy_bits=prior_entropy,
        expected_posterior_entropy_bits=expected_entropy,
        information_gain_bits=information_gain,
        normalized_information_gain=normalized_gain,
        weakest_pair_separation=weakest,
        mean_pair_separation=mean,
        monetary_cost=cost,
        duration_hours=duration,
        operational_risk=risk,
        cost_efficiency=cost_efficiency,
        utility=utility,
        feasible=bool(experiment.feasible),
        safety_status=safety,
        eligible=eligible,
        outcome_posteriors=tuple(posterior_rows),
        assumptions_hash=assumptions_hash,
    )


def rank_discriminating_experiments(
    priors: Mapping[str, float],
    experiments: Sequence[ExperimentDesign],
    *,
    duration_cost_per_hour: float = 0.0,
    risk_cost: float = 0.0,
    allow_review_required: bool = False,
) -> Tuple[ExperimentScore, ...]:
    if not experiments:
        raise ValueError("at least one experiment is required")
    if len({experiment.experiment_id for experiment in experiments}) != len(experiments):
        raise ValueError("experiment ids must be unique")
    scores = [
        score_experiment(
            priors,
            experiment,
            duration_cost_per_hour=duration_cost_per_hour,
            risk_cost=risk_cost,
            allow_review_required=allow_review_required,
        )
        for experiment in experiments
    ]
    # Ineligible experiments remain visible for audit, but never outrank an
    # eligible design.  The primary objective is actual discrimination, then
    # weakest-pair coverage, then lower cost/risk/time.
    scores.sort(key=lambda score: (
        not score.eligible,
        -score.information_gain_bits,
        -score.weakest_pair_separation,
        score.monetary_cost,
        score.operational_risk,
        score.duration_hours,
        score.experiment_id,
    ))
    return tuple(scores)


def choose_discriminating_experiment(
    priors: Mapping[str, float],
    experiments: Sequence[ExperimentDesign],
    *,
    min_information_gain_bits: float = 0.0,
    min_weakest_pair_separation: float = 0.0,
    duration_cost_per_hour: float = 0.0,
    risk_cost: float = 0.0,
) -> ExperimentRecommendation:
    minimum_gain = _finite(min_information_gain_bits, "min_information_gain_bits")
    minimum_separation = _finite(
        min_weakest_pair_separation, "min_weakest_pair_separation"
    )
    if minimum_gain < 0 or not 0 <= minimum_separation <= 1:
        raise ValueError("invalid discrimination threshold")
    ranked = rank_discriminating_experiments(
        priors,
        experiments,
        duration_cost_per_hour=duration_cost_per_hour,
        risk_cost=risk_cost,
    )
    rejected = []
    for score in ranked:
        reason = None
        if not score.eligible:
            reason = f"ineligible:{score.safety_status}"
        elif score.information_gain_bits + _EPS < minimum_gain:
            reason = "insufficient_information_gain"
        elif score.weakest_pair_separation + _EPS < minimum_separation:
            reason = "weakest_hypothesis_pair_not_separated"
        if reason:
            rejected.append((score.experiment_id, reason))
            continue
        return ExperimentRecommendation(
            experiment_id=score.experiment_id,
            reason=(
                "highest expected information gain among eligible designs while "
                "meeting the requested discrimination thresholds"
            ),
            score=score,
            rejected=tuple(rejected),
        )
    raise ValueError("no eligible experiment meets the discrimination thresholds")


def choose_minimum_cost_experiment(
    priors: Mapping[str, float],
    experiments: Sequence[ExperimentDesign],
    *,
    min_information_gain_bits: float,
    min_weakest_pair_separation: float = 0.0,
    max_operational_risk: float = 1.0,
    max_duration_hours: Optional[float] = None,
) -> ExperimentRecommendation:
    """Choose the cheapest eligible design that clears scientific constraints."""
    minimum_gain = _finite(min_information_gain_bits, "min_information_gain_bits")
    minimum_separation = _finite(
        min_weakest_pair_separation, "min_weakest_pair_separation"
    )
    maximum_risk = _finite(max_operational_risk, "max_operational_risk")
    maximum_duration = (
        None if max_duration_hours is None
        else _finite(max_duration_hours, "max_duration_hours")
    )
    if minimum_gain < 0 or not 0 <= minimum_separation <= 1:
        raise ValueError("invalid scientific threshold")
    if not 0 <= maximum_risk <= 1:
        raise ValueError("max_operational_risk must be in [0,1]")
    if maximum_duration is not None and maximum_duration < 0:
        raise ValueError("max_duration_hours cannot be negative")

    scores = rank_discriminating_experiments(priors, experiments)
    accepted = []
    rejected = []
    for score in scores:
        reason = None
        if not score.eligible:
            reason = f"ineligible:{score.safety_status}"
        elif score.information_gain_bits + _EPS < minimum_gain:
            reason = "insufficient_information_gain"
        elif score.weakest_pair_separation + _EPS < minimum_separation:
            reason = "insufficient_pair_separation"
        elif score.operational_risk > maximum_risk + _EPS:
            reason = "risk_limit_exceeded"
        elif maximum_duration is not None and score.duration_hours > maximum_duration + _EPS:
            reason = "duration_limit_exceeded"
        if reason:
            rejected.append((score.experiment_id, reason))
        else:
            accepted.append(score)
    if not accepted:
        raise ValueError("no eligible experiment satisfies cost-plan constraints")
    accepted.sort(key=lambda score: (
        score.monetary_cost,
        score.duration_hours,
        score.operational_risk,
        -score.information_gain_bits,
        score.experiment_id,
    ))
    winner = accepted[0]
    return ExperimentRecommendation(
        experiment_id=winner.experiment_id,
        reason=(
            "minimum monetary cost among eligible experiments that satisfy the "
            "information, discrimination, risk and duration constraints"
        ),
        score=winner,
        rejected=tuple(sorted(rejected)),
    )


def choose_active_learning_step(
    priors: Mapping[str, float],
    experiments: Sequence[ExperimentDesign],
    *,
    duration_cost_per_hour: float = 0.0,
    risk_cost: float = 0.0,
    min_information_gain_bits: float = 1e-6,
) -> ExperimentRecommendation:
    """Choose the best information-per-resource next measurement."""
    minimum_gain = _finite(min_information_gain_bits, "min_information_gain_bits")
    if minimum_gain < 0:
        raise ValueError("min_information_gain_bits cannot be negative")
    scores = rank_discriminating_experiments(
        priors,
        experiments,
        duration_cost_per_hour=duration_cost_per_hour,
        risk_cost=risk_cost,
    )
    eligible = [
        score for score in scores
        if score.eligible and score.information_gain_bits + _EPS >= minimum_gain
    ]
    if not eligible:
        raise ValueError("no eligible informative experiment exists")
    eligible.sort(key=lambda score: (
        -score.utility,
        -score.information_gain_bits,
        score.monetary_cost,
        score.duration_hours,
        score.operational_risk,
        score.experiment_id,
    ))
    winner = eligible[0]
    rejected = tuple(
        (score.experiment_id, "lower_active_learning_utility")
        for score in scores if score.experiment_id != winner.experiment_id
    )
    return ExperimentRecommendation(
        experiment_id=winner.experiment_id,
        reason=(
            "highest expected information gain per declared cost/time/risk among "
            "eligible experiments"
        ),
        score=winner,
        rejected=rejected,
    )


def update_posterior(
    priors: Mapping[str, float],
    experiment: ExperimentDesign,
    observed_outcome: str,
) -> Mapping[str, float]:
    """Bayesian active-learning update after a real/simulated outcome is supplied."""
    normalized = _normalize_priors(priors)
    hypothesis_ids = tuple(sorted(normalized))
    outcomes = experiment.validate(hypothesis_ids)
    outcome = str(observed_outcome or "").strip()
    if outcome not in outcomes:
        raise ValueError("observed outcome was not predeclared for this experiment")
    predictive = sum(
        normalized[hid] * float(experiment.outcome_likelihoods[hid][outcome])
        for hid in hypothesis_ids
    )
    if predictive <= _EPS:
        raise ValueError("observed outcome had zero probability under all hypotheses")
    posterior = {
        hid: (
            normalized[hid]
            * float(experiment.outcome_likelihoods[hid][outcome])
            / predictive
        )
        for hid in hypothesis_ids
    }
    # Normalize once more to absorb floating-point drift.
    total = sum(posterior.values())
    return {hid: value / total for hid, value in posterior.items()}


def stop_active_learning(
    priors: Mapping[str, float],
    experiments: Sequence[ExperimentDesign],
    *,
    posterior_dominance: float = 0.95,
    min_remaining_information_gain_bits: float = 0.01,
) -> Mapping[str, object]:
    """Explicit stopping rule: dominance OR no worthwhile eligible experiment."""
    normalized = _normalize_priors(priors)
    dominance = _finite(posterior_dominance, "posterior_dominance")
    minimum_gain = _finite(
        min_remaining_information_gain_bits,
        "min_remaining_information_gain_bits",
    )
    if not 0.5 < dominance < 1 or minimum_gain < 0:
        raise ValueError("invalid active-learning stop thresholds")
    leader, leader_probability = max(normalized.items(), key=lambda item: item[1])
    if leader_probability >= dominance:
        return {
            "stop": True,
            "reason": "posterior_dominance_threshold_reached",
            "leader": leader,
            "leader_probability": leader_probability,
            "truth_proven": False,
        }
    scores = rank_discriminating_experiments(priors, experiments)
    best_gain = max(
        (score.information_gain_bits for score in scores if score.eligible),
        default=0.0,
    )
    return {
        "stop": best_gain < minimum_gain,
        "reason": (
            "no_remaining_experiment_clears_information_gain_floor"
            if best_gain < minimum_gain else "continue_active_learning"
        ),
        "leader": leader,
        "leader_probability": leader_probability,
        "best_remaining_information_gain_bits": best_gain,
        "truth_proven": False,
    }
