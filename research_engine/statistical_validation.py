"""Deterministic statistical validation primitives for the research laboratory.

The functions here are intentionally model-agnostic and zero-cost. They turn
several blueprint labels (multiple-testing correction, placebo testing, Monte
Carlo stress, sensitivity analysis, leakage checks and walk-forward holdouts)
into executable, testable numerical behavior.

No function promotes an empirical result to a guarantee. Inputs, method and
random seed remain explicit so results can be reproduced.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from statistics import mean
from typing import Any, List, Mapping, Optional, Sequence, Tuple


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _pvalue(value: Any, field: str = "p_value") -> float:
    number = _finite(value, field)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1")
    return number


@dataclass(frozen=True)
class MultipleTestingResult:
    method: str
    alpha: float
    raw_p_values: Tuple[float, ...]
    adjusted_p_values: Tuple[float, ...]
    rejected: Tuple[bool, ...]


@dataclass(frozen=True)
class PlaceboResult:
    observed_effect: float
    p_value: float
    permutations: int
    seed: int
    alternative: str


@dataclass(frozen=True)
class MonteCarloSummary:
    paths: int
    horizon: int
    seed: int
    median_terminal_equity: float
    terminal_equity_p05: float
    terminal_equity_p95: float
    median_max_drawdown: float
    max_drawdown_p95: float
    ruin_probability: float


@dataclass(frozen=True)
class SensitivityResult:
    best_parameter: float
    best_score: float
    plateau_min: float
    plateau_max: float
    plateau_fraction: float
    cliff_detected: bool
    local_drop_fraction: float


@dataclass(frozen=True)
class LeakageFinding:
    index: int
    kind: str
    event_time: float
    available_time: float
    target_time: float
    detail: str


def benjamini_hochberg(
    p_values: Sequence[float],
    *,
    alpha: float = 0.05,
) -> MultipleTestingResult:
    """Control false discovery rate with Benjamini-Hochberg adjustment."""
    alpha = _pvalue(alpha, "alpha")
    raw = tuple(_pvalue(value, f"p_values[{index}]") for index, value in enumerate(p_values))
    m = len(raw)
    if m == 0:
        return MultipleTestingResult("benjamini-hochberg", alpha, (), (), ())

    ordered = sorted(enumerate(raw), key=lambda pair: pair[1])
    adjusted_sorted = [0.0] * m
    running = 1.0
    for rank_from_end in range(m, 0, -1):
        _, p_value = ordered[rank_from_end - 1]
        candidate = min(1.0, p_value * m / rank_from_end)
        running = min(running, candidate)
        adjusted_sorted[rank_from_end - 1] = running

    adjusted = [0.0] * m
    for sorted_index, (original_index, _) in enumerate(ordered):
        adjusted[original_index] = adjusted_sorted[sorted_index]
    rejected = tuple(value <= alpha for value in adjusted)
    return MultipleTestingResult(
        "benjamini-hochberg",
        alpha,
        raw,
        tuple(round(value, 12) for value in adjusted),
        rejected,
    )


def holm_bonferroni(
    p_values: Sequence[float],
    *,
    alpha: float = 0.05,
) -> MultipleTestingResult:
    """Control family-wise error rate with Holm's step-down procedure."""
    alpha = _pvalue(alpha, "alpha")
    raw = tuple(_pvalue(value, f"p_values[{index}]") for index, value in enumerate(p_values))
    m = len(raw)
    if m == 0:
        return MultipleTestingResult("holm-bonferroni", alpha, (), (), ())

    ordered = sorted(enumerate(raw), key=lambda pair: pair[1])
    adjusted_sorted: List[float] = []
    running = 0.0
    for sorted_index, (_, p_value) in enumerate(ordered):
        factor = m - sorted_index
        candidate = min(1.0, p_value * factor)
        running = max(running, candidate)
        adjusted_sorted.append(running)

    adjusted = [0.0] * m
    for sorted_index, (original_index, _) in enumerate(ordered):
        adjusted[original_index] = adjusted_sorted[sorted_index]

    reject_sorted = [False] * m
    still_rejecting = True
    for sorted_index, (_, p_value) in enumerate(ordered):
        threshold = alpha / (m - sorted_index)
        if still_rejecting and p_value <= threshold:
            reject_sorted[sorted_index] = True
        else:
            still_rejecting = False

    rejected = [False] * m
    for sorted_index, (original_index, _) in enumerate(ordered):
        rejected[original_index] = reject_sorted[sorted_index]

    return MultipleTestingResult(
        "holm-bonferroni",
        alpha,
        raw,
        tuple(round(value, 12) for value in adjusted),
        tuple(rejected),
    )


def paired_placebo_permutation_test(
    observed: Sequence[float],
    placebo: Sequence[float],
    *,
    permutations: int = 10000,
    seed: int = 0,
    alternative: str = "greater",
) -> PlaceboResult:
    """Paired randomization test of observed treatment/strategy vs placebo."""
    if len(observed) != len(placebo):
        raise ValueError("observed and placebo must have the same length")
    if len(observed) < 2:
        raise ValueError("at least two paired observations are required")
    if not isinstance(permutations, int) or permutations < 100:
        raise ValueError("permutations must be an integer >= 100")
    if alternative not in {"greater", "less", "two-sided"}:
        raise ValueError("alternative must be greater, less or two-sided")

    differences = [
        _finite(a, f"observed[{i}]") - _finite(b, f"placebo[{i}]")
        for i, (a, b) in enumerate(zip(observed, placebo))
    ]
    effect = mean(differences)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(permutations):
        statistic = mean(value if rng.random() < 0.5 else -value for value in differences)
        if alternative == "greater":
            hit = statistic >= effect
        elif alternative == "less":
            hit = statistic <= effect
        else:
            hit = abs(statistic) >= abs(effect)
        if hit:
            extreme += 1
    p_value = (extreme + 1.0) / (permutations + 1.0)
    return PlaceboResult(
        observed_effect=round(effect, 12),
        p_value=round(p_value, 12),
        permutations=permutations,
        seed=int(seed),
        alternative=alternative,
    )


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("values cannot be empty")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be between 0 and 1")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _max_drawdown(equity_curve: Sequence[float]) -> float:
    peak = equity_curve[0]
    worst = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, (peak - equity) / peak)
    return worst


def monte_carlo_return_paths(
    returns: Sequence[float],
    *,
    paths: int = 10000,
    horizon: Optional[int] = None,
    seed: int = 0,
    initial_equity: float = 1.0,
    ruin_equity: float = 0.5,
) -> MonteCarloSummary:
    """Bootstrap return paths and report drawdown/ruin distribution.

    Sampling estimates sequence uncertainty only; it does not prove that the
    future return distribution will match the input distribution.
    """
    samples = tuple(_finite(value, f"returns[{i}]") for i, value in enumerate(returns))
    if not samples:
        raise ValueError("returns cannot be empty")
    if any(value <= -1.0 for value in samples):
        raise ValueError("simple returns must be greater than -1")
    if not isinstance(paths, int) or paths < 100:
        raise ValueError("paths must be an integer >= 100")
    horizon = len(samples) if horizon is None else int(horizon)
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    initial = _finite(initial_equity, "initial_equity")
    ruin = _finite(ruin_equity, "ruin_equity")
    if initial <= 0 or ruin <= 0:
        raise ValueError("equity levels must be positive")

    rng = random.Random(seed)
    terminals: List[float] = []
    drawdowns: List[float] = []
    ruined = 0
    for _ in range(paths):
        equity = initial
        curve = [equity]
        path_ruined = False
        for _ in range(horizon):
            equity *= 1.0 + rng.choice(samples)
            curve.append(equity)
            if equity <= ruin:
                path_ruined = True
        terminals.append(equity)
        drawdowns.append(_max_drawdown(curve))
        if path_ruined:
            ruined += 1

    return MonteCarloSummary(
        paths=paths,
        horizon=horizon,
        seed=int(seed),
        median_terminal_equity=round(_percentile(terminals, 0.50), 12),
        terminal_equity_p05=round(_percentile(terminals, 0.05), 12),
        terminal_equity_p95=round(_percentile(terminals, 0.95), 12),
        median_max_drawdown=round(_percentile(drawdowns, 0.50), 12),
        max_drawdown_p95=round(_percentile(drawdowns, 0.95), 12),
        ruin_probability=round(ruined / paths, 12),
    )


def sensitivity_plateau(
    scores_by_parameter: Mapping[float, float],
    *,
    acceptable_fraction_of_best: float = 0.90,
    cliff_drop_fraction: float = 0.25,
) -> SensitivityResult:
    """Measure whether a best result sits on a broad plateau or a narrow spike."""
    if len(scores_by_parameter) < 3:
        raise ValueError("at least three parameter points are required")
    fraction = _finite(acceptable_fraction_of_best, "acceptable_fraction_of_best")
    cliff = _finite(cliff_drop_fraction, "cliff_drop_fraction")
    if not 0.0 < fraction <= 1.0 or not 0.0 <= cliff <= 1.0:
        raise ValueError("fractions must be in valid ranges")

    points = sorted(
        (_finite(parameter, "parameter"), _finite(score, "score"))
        for parameter, score in scores_by_parameter.items()
    )
    best_index = max(range(len(points)), key=lambda index: points[index][1])
    best_parameter, best_score = points[best_index]
    if best_score <= 0:
        raise ValueError("best score must be positive for relative plateau analysis")
    floor = best_score * fraction

    left = best_index
    while left > 0 and points[left - 1][1] >= floor:
        left -= 1
    right = best_index
    while right + 1 < len(points) and points[right + 1][1] >= floor:
        right += 1

    neighbor_scores = []
    if best_index > 0:
        neighbor_scores.append(points[best_index - 1][1])
    if best_index + 1 < len(points):
        neighbor_scores.append(points[best_index + 1][1])
    local_drop = max((best_score - score) / best_score for score in neighbor_scores)
    total_span = points[-1][0] - points[0][0]
    plateau_span = points[right][0] - points[left][0]
    plateau_fraction = plateau_span / total_span if total_span > 0 else 0.0

    return SensitivityResult(
        best_parameter=best_parameter,
        best_score=best_score,
        plateau_min=points[left][0],
        plateau_max=points[right][0],
        plateau_fraction=round(plateau_fraction, 12),
        cliff_detected=local_drop >= cliff,
        local_drop_fraction=round(local_drop, 12),
    )


def detect_temporal_leakage(
    rows: Sequence[Mapping[str, Any]],
) -> Tuple[LeakageFinding, ...]:
    """Detect future-information leakage in time-indexed feature rows."""
    findings: List[LeakageFinding] = []
    last_event: Optional[float] = None
    for index, row in enumerate(rows):
        event = _finite(row.get("event_time"), f"rows[{index}].event_time")
        available = _finite(row.get("feature_available_time"), f"rows[{index}].feature_available_time")
        target = _finite(row.get("target_time"), f"rows[{index}].target_time")
        if last_event is not None and event < last_event:
            findings.append(LeakageFinding(
                index, "NON_MONOTONIC_EVENT_TIME", event, available, target,
                "event times are not monotonically non-decreasing",
            ))
        if available > event:
            findings.append(LeakageFinding(
                index, "LOOKAHEAD_FEATURE", event, available, target,
                "feature became available after the decision time",
            ))
        if target <= event:
            findings.append(LeakageFinding(
                index, "INVALID_TARGET_CHRONOLOGY", event, available, target,
                "prediction target must occur after the decision time",
            ))
        last_event = event
    return tuple(findings)


def walk_forward_splits(
    n_samples: int,
    *,
    min_train: int,
    test_size: int,
    step: Optional[int] = None,
    expanding: bool = True,
) -> Tuple[Tuple[Tuple[int, int], Tuple[int, int]], ...]:
    """Generate leakage-safe half-open train/test index windows."""
    n_samples = int(n_samples)
    min_train = int(min_train)
    test_size = int(test_size)
    step = test_size if step is None else int(step)
    if n_samples <= 0 or min_train <= 0 or test_size <= 0 or step <= 0:
        raise ValueError("n_samples, min_train, test_size and step must be positive")
    if min_train + test_size > n_samples:
        raise ValueError("not enough samples for one split")

    out = []
    train_end = min_train
    while train_end + test_size <= n_samples:
        train_start = 0 if expanding else max(0, train_end - min_train)
        test_start = train_end
        test_end = test_start + test_size
        out.append(((train_start, train_end), (test_start, test_end)))
        train_end += step
    return tuple(out)


def population_stability_index(
    reference: Sequence[float],
    current: Sequence[float],
    *,
    bins: int = 10,
    epsilon: float = 1e-6,
) -> float:
    """Distribution-shift diagnostic using Population Stability Index."""
    ref = sorted(_finite(value, f"reference[{i}]") for i, value in enumerate(reference))
    cur = [_finite(value, f"current[{i}]") for i, value in enumerate(current)]
    if bins < 2:
        raise ValueError("bins must be >= 2")
    if len(ref) < bins or len(cur) < 2:
        raise ValueError("samples are too small for requested bins")

    boundaries = [_percentile(ref, i / bins) for i in range(1, bins)]

    def bucket(value: float) -> int:
        index = 0
        while index < len(boundaries) and value > boundaries[index]:
            index += 1
        return index

    ref_counts = [0] * bins
    cur_counts = [0] * bins
    for value in ref:
        ref_counts[bucket(value)] += 1
    for value in cur:
        cur_counts[bucket(value)] += 1

    psi = 0.0
    for ref_count, cur_count in zip(ref_counts, cur_counts):
        ref_rate = max(epsilon, ref_count / len(ref))
        cur_rate = max(epsilon, cur_count / len(cur))
        psi += (cur_rate - ref_rate) * math.log(cur_rate / ref_rate)
    return round(psi, 12)
