"""Deterministic quantitative/statistical primitives for AI-2.

All expensive operations enforce hard compute budgets from ``validation_limits``.
A request above those budgets is refused with RESOURCE_LIMIT_EXCEEDED instead of
being silently clamped or partially executed.
"""
from __future__ import annotations

import math
import random
import statistics
from statistics import NormalDist
from typing import Any, Dict, Mapping, Sequence

from .validation_limits import (
    MAX_BAYES_DRAWS,
    MAX_BOOTSTRAP_RESAMPLES,
    MAX_CLASSIFICATION_WORK_UNITS,
    MAX_CLASS_LABELS,
    MAX_OBSERVATIONS,
    MAX_P_VALUES,
    MAX_PERMUTATIONS,
    MAX_RESAMPLE_WORK_UNITS,
    MAX_TWO_GROUP_TOTAL_OBSERVATIONS,
    bounded_iterations,
    bounded_length,
    resource_error,
)
from .validation_types import UNKNOWN, listify, number, numbers


def quantile(values: Sequence[float], q: float):
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    q = max(0.0, min(1.0, float(q)))
    pos = (len(xs) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    w = pos - lo
    return xs[lo] * (1 - w) + xs[hi] * w


def _observation_limit(values: Any, field: str, maximum: int = MAX_OBSERVATIONS):
    return bounded_length(values, maximum, field)


def _two_group_limit(a: Any, b: Any):
    err = _observation_limit(a, "group_a") or _observation_limit(b, "group_b")
    if err:
        return err
    try:
        total = len(a) + len(b)
    except (TypeError, AttributeError):
        return None
    if total > MAX_TWO_GROUP_TOTAL_OBSERVATIONS:
        return resource_error(
            "two_group_total_observations",
            total,
            f"count exceeds hard maximum {MAX_TWO_GROUP_TOTAL_OBSERVATIONS}",
        )
    return None


def bootstrap_mean_ci(values: Sequence[float], *, confidence: float = 0.95,
                      resamples: int = 4000, seed: int = 20260903) -> Dict[str, Any]:
    limit = _observation_limit(values, "observations")
    if limit:
        return limit
    xs = numbers(values)
    if len(xs) < 2:
        return {"status": UNKNOWN, "reason": "At least 2 observations are required."}
    count, error = bounded_iterations(
        resamples,
        default=4000,
        minimum=100,
        maximum=MAX_BOOTSTRAP_RESAMPLES,
        field="bootstrap_resamples",
        sample_size=len(xs),
        max_work_units=MAX_RESAMPLE_WORK_UNITS,
    )
    if error:
        return error
    if not (0 < confidence < 1):
        return {"status": UNKNOWN, "reason": "Invalid confidence request."}
    rng = random.Random(seed)
    means = [statistics.fmean(rng.choices(xs, k=len(xs))) for _ in range(count)]
    alpha = 1 - confidence
    return {"status": "TEST PERFORMED", "n": len(xs), "mean": statistics.fmean(xs),
            "confidence": confidence, "lower": quantile(means, alpha / 2),
            "upper": quantile(means, 1 - alpha / 2), "resamples": count, "seed": seed}


def bootstrap_difference_ci(a: Sequence[float], b: Sequence[float], *, confidence: float = 0.95,
                            resamples: int = 4000, seed: int = 20260903) -> Dict[str, Any]:
    limit = _two_group_limit(a, b)
    if limit:
        return limit
    x, y = numbers(a), numbers(b)
    if len(x) < 2 or len(y) < 2:
        return {"status": UNKNOWN, "reason": "Both groups need >=2 observations."}
    count, error = bounded_iterations(
        resamples,
        default=4000,
        minimum=100,
        maximum=MAX_BOOTSTRAP_RESAMPLES,
        field="bootstrap_resamples",
        sample_size=len(x) + len(y),
        max_work_units=MAX_RESAMPLE_WORK_UNITS,
    )
    if error:
        return error
    if not (0 < confidence < 1):
        return {"status": UNKNOWN, "reason": "Invalid confidence request."}
    rng = random.Random(seed)
    diffs = [statistics.fmean(rng.choices(x, k=len(x))) - statistics.fmean(rng.choices(y, k=len(y)))
             for _ in range(count)]
    alpha = 1 - confidence
    return {"status": "TEST PERFORMED", "observed_mean_difference": statistics.fmean(x) - statistics.fmean(y),
            "confidence": confidence, "lower": quantile(diffs, alpha / 2),
            "upper": quantile(diffs, 1 - alpha / 2), "resamples": count, "seed": seed}


def mean_difference_effect(a: Sequence[float], b: Sequence[float]) -> Dict[str, Any]:
    limit = _two_group_limit(a, b)
    if limit:
        return limit
    x, y = numbers(a), numbers(b)
    if len(x) < 2 or len(y) < 2:
        return {"status": UNKNOWN, "reason": "Both groups need >=2 observations."}
    mx, my = statistics.fmean(x), statistics.fmean(y)
    vx, vy = statistics.variance(x), statistics.variance(y)
    df = len(x) + len(y) - 2
    pooled_var = ((len(x) - 1) * vx + (len(y) - 1) * vy) / df if df > 0 else 0.0
    pooled_sd = math.sqrt(max(0.0, pooled_var))
    d = (mx - my) / pooled_sd if pooled_sd > 0 else None
    correction = 1 - 3 / (4 * df - 1) if df > 1 else 1.0
    g = d * correction if d is not None else None
    return {"status": "TEST PERFORMED", "n_a": len(x), "n_b": len(y), "mean_a": mx,
            "mean_b": my, "mean_difference": mx - my,
            "cohens_d": d if d is not None else UNKNOWN,
            "hedges_g": g if g is not None else UNKNOWN}


def permutation_mean_difference(a: Sequence[float], b: Sequence[float], *,
                                permutations: int = 5000, seed: int = 20260903) -> Dict[str, Any]:
    limit = _two_group_limit(a, b)
    if limit:
        return limit
    x, y = numbers(a), numbers(b)
    if len(x) < 2 or len(y) < 2:
        return {"status": UNKNOWN, "reason": "Both groups need >=2 observations."}
    count, error = bounded_iterations(
        permutations,
        default=5000,
        minimum=100,
        maximum=MAX_PERMUTATIONS,
        field="permutations",
        sample_size=len(x) + len(y),
        max_work_units=MAX_RESAMPLE_WORK_UNITS,
    )
    if error:
        return error
    observed = statistics.fmean(x) - statistics.fmean(y)
    pooled, nx = x + y, len(x)
    rng, extreme = random.Random(seed), 0
    for _ in range(count):
        shuffled = pooled[:]
        rng.shuffle(shuffled)
        diff = statistics.fmean(shuffled[:nx]) - statistics.fmean(shuffled[nx:])
        extreme += int(abs(diff) >= abs(observed) - 1e-15)
    return {"status": "TEST PERFORMED", "observed_mean_difference": observed,
            "two_sided_p": (extreme + 1) / (count + 1),
            "permutations": count, "seed": seed}


def benjamini_hochberg(p_values: Sequence[float]) -> Dict[str, Any]:
    limit = bounded_length(p_values, MAX_P_VALUES, "p_values")
    if limit:
        return limit
    ps = numbers(p_values)
    if not ps or len(ps) != len(listify(p_values)) or any(p < 0 or p > 1 for p in ps):
        return {"status": UNKNOWN, "reason": "All p-values must be numeric in [0,1]."}
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adjusted, running = [1.0] * m, 1.0
    for rank_index in range(m - 1, -1, -1):
        idx, rank = order[rank_index], rank_index + 1
        running = min(running, ps[idx] * m / rank)
        adjusted[idx] = min(1.0, running)
    return {"status": "TEST PERFORMED", "p_values": ps, "bh_q_values": adjusted}


def two_sample_power_n(*, standardized_effect: Any, alpha: Any, power: Any,
                       two_sided: bool = True) -> Dict[str, Any]:
    d, a, pwr = number(standardized_effect), number(alpha), number(power)
    if d is None or a is None or pwr is None or d <= 0 or not (0 < a < 1) or not (0 < pwr < 1):
        return {"status": UNKNOWN,
                "reason": "standardized_effect, alpha and target power must be explicitly supplied."}
    nd = NormalDist()
    z_alpha = nd.inv_cdf(1 - (a / 2 if two_sided else a))
    z_power = nd.inv_cdf(pwr)
    n = math.ceil(2 * ((z_alpha + z_power) / d) ** 2)
    return {"status": "TEST PROPOSED", "approx_n_per_group": n, "standardized_effect": d,
            "alpha": a, "power": pwr, "two_sided": two_sided,
            "note": "Normal-approximation planning value; replace with design-specific power when available."}


def beta_binomial_posterior(*, successes: Any, failures: Any, prior_alpha: Any,
                            prior_beta: Any, credible_mass: float = 0.95,
                            draws: int = 30000, seed: int = 20260903) -> Dict[str, Any]:
    s, f, a, b = number(successes), number(failures), number(prior_alpha), number(prior_beta)
    if None in (s, f, a, b) or s < 0 or f < 0 or a <= 0 or b <= 0:
        return {"status": UNKNOWN, "reason": "Counts and an explicit proper Beta prior are required."}
    if not float(s).is_integer() or not float(f).is_integer():
        return {"status": UNKNOWN, "reason": "successes/failures must be integer counts."}
    count, error = bounded_iterations(
        draws,
        default=30000,
        minimum=100,
        maximum=MAX_BAYES_DRAWS,
        field="bayesian_draws",
    )
    if error:
        return error
    if not (0 < credible_mass < 1):
        return {"status": UNKNOWN, "reason": "credible_mass must be in (0,1)."}
    pa, pb = a + s, b + f
    rng = random.Random(seed)
    samples = [rng.betavariate(pa, pb) for _ in range(count)]
    tail = (1 - credible_mass) / 2
    return {"status": "TEST PERFORMED", "posterior_alpha": pa, "posterior_beta": pb,
            "posterior_mean": pa / (pa + pb), "credible_mass": credible_mass,
            "lower": quantile(samples, tail), "upper": quantile(samples, 1 - tail),
            "draws": count, "seed": seed, "prior_source": "CALLER SUPPLIED"}


def classification_metrics(y_true: Sequence[Any], y_pred: Sequence[Any],
                           probabilities: Sequence[Any] | None = None) -> Dict[str, Any]:
    limit = _observation_limit(y_true, "y_true") or _observation_limit(y_pred, "y_pred")
    if limit:
        return limit
    if probabilities is not None:
        limit = _observation_limit(probabilities, "probabilities")
        if limit:
            return limit
    truth, pred = list(y_true or []), list(y_pred or [])
    if not truth or len(truth) != len(pred):
        return {"status": UNKNOWN, "reason": "y_true/y_pred missing or unequal."}
    labels = sorted(set(truth) | set(pred), key=lambda x: str(x))
    if len(labels) > MAX_CLASS_LABELS:
        return resource_error("classification_labels", len(labels), f"count exceeds hard maximum {MAX_CLASS_LABELS}")
    if len(truth) * max(1, len(labels)) > MAX_CLASSIFICATION_WORK_UNITS:
        return resource_error(
            "classification_work_units",
            len(truth) * max(1, len(labels)),
            f"exceeds hard budget {MAX_CLASSIFICATION_WORK_UNITS}",
        )
    correct = sum(a == b for a, b in zip(truth, pred))
    per_label, recalls, f1s = {}, [], []
    # The intentionally simple implementation is bounded above; no accidental
    # O(n * unbounded-label-count) request can reach this loop.
    for label in labels:
        tp = sum(a == label and b == label for a, b in zip(truth, pred))
        fp = sum(a != label and b == label for a, b in zip(truth, pred))
        fn = sum(a == label and b != label for a, b in zip(truth, pred))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        recalls.append(recall)
        f1s.append(f1)
        per_label[str(label)] = {"precision": precision, "recall": recall, "f1": f1,
                                 "support": sum(a == label for a in truth)}
    majority = max(sum(x == label for x in truth) for label in labels) / len(truth)
    out: Dict[str, Any] = {"status": "TEST PERFORMED", "n": len(truth),
                           "accuracy": correct / len(truth),
                           "balanced_accuracy": statistics.fmean(recalls),
                           "macro_f1": statistics.fmean(f1s),
                           "majority_baseline_accuracy": majority, "per_label": per_label}
    probs = numbers(probabilities) if probabilities is not None else []
    if len(labels) == 2 and len(probs) == len(truth) and all(0 <= p <= 1 for p in probs):
        positive = labels[-1]
        ys = [1.0 if y == positive else 0.0 for y in truth]
        eps = 1e-15
        out["brier_score"] = statistics.fmean((p - y) ** 2 for p, y in zip(probs, ys))
        out["log_loss"] = -statistics.fmean(
            y * math.log(max(eps, min(1 - eps, p))) +
            (1 - y) * math.log(max(eps, min(1 - eps, 1 - p)))
            for p, y in zip(probs, ys))
    return out


def regression_metrics(y_true: Sequence[Any], y_pred: Sequence[Any]) -> Dict[str, Any]:
    limit = _observation_limit(y_true, "y_true") or _observation_limit(y_pred, "y_pred")
    if limit:
        return limit
    truth, pred = numbers(y_true), numbers(y_pred)
    if not truth or len(truth) != len(pred):
        return {"status": UNKNOWN, "reason": "Numeric y_true/y_pred missing or unequal."}
    errors = [p - y for p, y in zip(pred, truth)]
    mae = statistics.fmean(abs(e) for e in errors)
    rmse = math.sqrt(statistics.fmean(e * e for e in errors))
    ybar = statistics.fmean(truth)
    ss_tot, ss_res = sum((y - ybar) ** 2 for y in truth), sum(e * e for e in errors)
    persistence_mae = (statistics.fmean(abs(a - b) for a, b in zip(truth[1:], truth[:-1]))
                       if len(truth) >= 2 else UNKNOWN)
    return {"status": "TEST PERFORMED", "n": len(truth), "mae": mae, "rmse": rmse,
            "r2": 1 - ss_res / ss_tot if ss_tot > 0 else UNKNOWN,
            "persistence_baseline_mae": persistence_mae}


def statistical_validation(execution: Mapping[str, Any]) -> Dict[str, Any]:
    """Run only explicitly enabled/supplied statistical checks."""
    out: Dict[str, Any] = {"effect_size": UNKNOWN, "uncertainty_interval": UNKNOWN,
                           "permutation": UNKNOWN, "bayesian": UNKNOWN,
                           "multiple_testing": UNKNOWN, "power": UNKNOWN}
    kind = str(execution.get("kind") or "").lower()
    if kind in ("two_group", "two-sample", "experiment"):
        a, b = execution.get("group_a") or [], execution.get("group_b") or []
        out["effect_size"] = mean_difference_effect(a, b)
        out["uncertainty_interval"] = bootstrap_difference_ci(
            a, b,
            confidence=float(number(execution.get("confidence")) or .95),
            resamples=execution.get("bootstrap_resamples") if execution.get("bootstrap_resamples") is not None else 4000,
        )
        out["permutation"] = permutation_mean_difference(
            a, b,
            permutations=execution.get("permutations") if execution.get("permutations") is not None else 5000,
        )
    if execution.get("p_values") is not None:
        out["multiple_testing"] = benjamini_hochberg(execution.get("p_values") or [])
    power = execution.get("power_request") if isinstance(execution.get("power_request"), Mapping) else {}
    if power:
        out["power"] = two_sample_power_n(standardized_effect=power.get("standardized_effect"),
                                           alpha=power.get("alpha"), power=power.get("power"),
                                           two_sided=bool(power.get("two_sided", True)))
    bayes = execution.get("bayesian_binary") if isinstance(execution.get("bayesian_binary"), Mapping) else {}
    if bayes:
        out["bayesian"] = beta_binomial_posterior(
            successes=bayes.get("successes"), failures=bayes.get("failures"),
            prior_alpha=bayes.get("prior_alpha"), prior_beta=bayes.get("prior_beta"),
            credible_mass=float(number(bayes.get("credible_mass")) or .95),
            draws=bayes.get("draws") if bayes.get("draws") is not None else 30000,
        )
    return out


__all__ = [
    "quantile", "bootstrap_mean_ci", "bootstrap_difference_ci", "mean_difference_effect",
    "permutation_mean_difference", "benjamini_hochberg", "two_sample_power_n",
    "beta_binomial_posterior", "classification_metrics", "regression_metrics",
    "statistical_validation",
]
