"""Deterministic receipt-based quantitative evaluation for AI-2.

Nothing in this module turns plans, targets, or claimed metrics into results.
Calculations require numeric observations plus explicit provenance. Decision
thresholds are never invented: PASS/FAIL requires an explicit machine-readable
rule supplied with the receipt.
"""
from __future__ import annotations

import math
import random
from copy import deepcopy
from statistics import NormalDist, mean, stdev
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .validation_contracts import (
    FAIL, INCONCLUSIVE, NOT_TESTED, PASS, RESULT_OBSERVED, UNKNOWN, meaningful, text,
)

_PROVENANCE_KEYS = (
    "test_id", "run_id", "dataset_id", "source", "source_id", "timestamp",
    "artifact", "report", "observed_metrics",
)
_OPERATORS = {
    ">": lambda x, y: x > y,
    ">=": lambda x, y: x >= y,
    "<": lambda x, y: x < y,
    "<=": lambda x, y: x <= y,
    "==": lambda x, y: x == y,
    "!=": lambda x, y: x != y,
}


def _numbers(value: Any) -> List[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    out: List[float] = []
    for item in value:
        if isinstance(item, bool):
            return []
        try:
            number = float(item)
        except (TypeError, ValueError):
            return []
        if not math.isfinite(number):
            return []
        out.append(number)
    return out


def _provenance(receipt: Mapping[str, Any]) -> Dict[str, Any]:
    raw = receipt.get("provenance") or receipt.get("result_provenance") or receipt.get("test_provenance")
    if not isinstance(raw, Mapping):
        return {}
    return deepcopy(dict(raw)) if any(meaningful(raw.get(k)) for k in _PROVENANCE_KEYS) else {}


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return math.nan
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = max(0.0, min(1.0, q)) * (len(sorted_values) - 1)
    lo = int(math.floor(pos)); hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_values[lo])
    weight = pos - lo
    return float(sorted_values[lo] * (1.0 - weight) + sorted_values[hi] * weight)


def _decision(metrics: Mapping[str, Any], rule: Any) -> Dict[str, Any]:
    if not isinstance(rule, Mapping):
        return {"status": INCONCLUSIVE, "reason": "No explicit machine-readable decision rule supplied."}
    metric = str(rule.get("metric") or "").strip()
    operator = str(rule.get("operator") or "").strip()
    threshold = rule.get("threshold")
    if metric not in metrics or operator not in _OPERATORS or isinstance(threshold, bool):
        return {"status": INCONCLUSIVE, "reason": "Decision rule is incomplete or references an unavailable metric."}
    try:
        observed = float(metrics[metric]); target = float(threshold)
    except (TypeError, ValueError):
        return {"status": INCONCLUSIVE, "reason": "Decision metric/threshold is not numeric."}
    if not (math.isfinite(observed) and math.isfinite(target)):
        return {"status": INCONCLUSIVE, "reason": "Decision metric/threshold is not finite."}
    passed = bool(_OPERATORS[operator](observed, target))
    return {
        "status": PASS if passed else FAIL,
        "metric": metric,
        "observed": observed,
        "operator": operator,
        "threshold": target,
        "rule_source": "SUPPLIED_IN_RESULT_RECEIPT",
    }


def analyze_two_group_receipt(receipt: Mapping[str, Any]) -> Dict[str, Any]:
    provenance = _provenance(receipt)
    observations = receipt.get("observations")
    observations = observations if isinstance(observations, Mapping) else {}
    candidate = _numbers(observations.get("candidate"))
    baseline = _numbers(observations.get("baseline"))
    if not provenance or not candidate or not baseline:
        return {"observed": False, "status": INCONCLUSIVE,
                "reason": "Numeric candidate+baseline observations and provenance are required."}

    c_mean = mean(candidate); b_mean = mean(baseline); diff = c_mean - b_mean
    c_sd = stdev(candidate) if len(candidate) > 1 else 0.0
    b_sd = stdev(baseline) if len(baseline) > 1 else 0.0
    pooled_den = len(candidate) + len(baseline) - 2
    pooled_var = (((len(candidate) - 1) * c_sd ** 2 + (len(baseline) - 1) * b_sd ** 2) / pooled_den) if pooled_den > 0 else 0.0
    pooled_sd = math.sqrt(max(0.0, pooled_var))
    standardized = diff / pooled_sd if pooled_sd > 0 else (0.0 if diff == 0 else math.copysign(math.inf, diff))
    metrics: Dict[str, Any] = {
        "candidate_n": len(candidate), "baseline_n": len(baseline),
        "candidate_mean": c_mean, "baseline_mean": b_mean, "mean_difference": diff,
        "candidate_sd": c_sd, "baseline_sd": b_sd,
        "standardized_effect": standardized,
    }

    confidence_level = receipt.get("confidence_level")
    ci: Any = NOT_TESTED
    if confidence_level is not None:
        try:
            cl = float(confidence_level)
        except (TypeError, ValueError):
            cl = math.nan
        if 0 < cl < 1 and len(candidate) > 1 and len(baseline) > 1:
            se = math.sqrt(c_sd ** 2 / len(candidate) + b_sd ** 2 / len(baseline))
            z = NormalDist().inv_cdf((1.0 + cl) / 2.0)
            ci = {"method": "normal_approximation_for_mean_difference", "confidence_level": cl,
                  "lower": diff - z * se, "upper": diff + z * se, "standard_error": se}

    bootstrap: Any = NOT_TESTED
    iterations = receipt.get("bootstrap_iterations")
    seed = receipt.get("random_seed")
    if isinstance(iterations, int) and iterations > 0 and isinstance(seed, int) and confidence_level is not None:
        try:
            cl = float(confidence_level)
        except (TypeError, ValueError):
            cl = math.nan
        if 0 < cl < 1:
            rng = random.Random(seed); boot = []
            for _ in range(iterations):
                c = [candidate[rng.randrange(len(candidate))] for _ in candidate]
                b = [baseline[rng.randrange(len(baseline))] for _ in baseline]
                boot.append(mean(c) - mean(b))
            boot.sort(); alpha = 1.0 - cl
            bootstrap = {"iterations": iterations, "random_seed": seed, "confidence_level": cl,
                         "lower": _percentile(boot, alpha / 2.0), "upper": _percentile(boot, 1.0 - alpha / 2.0)}

    permutation: Any = NOT_TESTED
    p_iterations = receipt.get("permutation_iterations")
    if isinstance(p_iterations, int) and p_iterations > 0 and isinstance(seed, int):
        rng = random.Random(seed); pooled = candidate + baseline; extreme = 0
        observed_abs = abs(diff); n_c = len(candidate)
        for _ in range(p_iterations):
            shuffled = list(pooled); rng.shuffle(shuffled)
            perm_diff = mean(shuffled[:n_c]) - mean(shuffled[n_c:])
            if abs(perm_diff) >= observed_abs:
                extreme += 1
        permutation = {"iterations": p_iterations, "random_seed": seed,
                       "two_sided_p_value": (extreme + 1.0) / (p_iterations + 1.0)}

    decision = _decision(metrics, receipt.get("decision_rule"))
    return {
        "observed": True, "test_state": RESULT_OBSERVED, "status": decision["status"],
        "provenance": provenance, "metrics": metrics, "confidence_interval": ci,
        "bootstrap": bootstrap, "permutation_test": permutation, "decision": decision,
        "limitations": [
            "No causal interpretation is implied by arithmetic alone.",
            "Normal-approximation CI is reported only when an explicit confidence_level is supplied.",
            "Bootstrap/permutation are run only when explicit iteration count and random_seed are supplied.",
        ],
    }


def _max_drawdown(returns: Sequence[float]) -> float:
    cumulative = 0.0; peak = 0.0; worst = 0.0
    for value in returns:
        cumulative += value; peak = max(peak, cumulative); worst = max(worst, peak - cumulative)
    return worst


def _losing_streaks(returns: Sequence[float]) -> Tuple[int, Dict[int, int]]:
    current = 0; maximum = 0; histogram: Dict[int, int] = {}
    for value in list(returns) + [0.0]:
        if value < 0:
            current += 1; maximum = max(maximum, current)
        elif current:
            histogram[current] = histogram.get(current, 0) + 1; current = 0
    return maximum, histogram


def _scenario_summary(mapping: Any) -> Any:
    if not isinstance(mapping, Mapping) or not mapping:
        return NOT_TESTED
    rows = []
    for name, raw in mapping.items():
        values = _numbers(raw)
        if values:
            rows.append({"name": str(name), "n": len(values), "expectancy": mean(values)})
    if not rows:
        return NOT_TESTED
    expectancies = [r["expectancy"] for r in rows]
    return {"scenarios": rows, "all_positive": all(x > 0 for x in expectancies),
            "min_expectancy": min(expectancies), "max_expectancy": max(expectancies),
            "expectancy_range": max(expectancies) - min(expectancies)}


def analyze_trading_receipt(receipt: Mapping[str, Any]) -> Dict[str, Any]:
    provenance = _provenance(receipt); returns = _numbers(receipt.get("trade_returns"))
    if not provenance or not returns:
        return {"observed": False, "status": INCONCLUSIVE,
                "reason": "Numeric per-trade net returns and provenance are required."}
    wins = [x for x in returns if x > 0]; losses = [x for x in returns if x < 0]
    gross_profit = sum(wins); gross_loss = abs(sum(losses))
    max_streak, streak_hist = _losing_streaks(returns)
    metrics: Dict[str, Any] = {
        "sample_size": len(returns), "win_rate": len(wins) / len(returns),
        "average_win": mean(wins) if wins else 0.0, "average_loss": mean(losses) if losses else 0.0,
        "expectancy": mean(returns), "profit_factor": gross_profit / gross_loss if gross_loss > 0 else math.inf,
        "maximum_drawdown": _max_drawdown(returns),
        "maximum_losing_streak": max_streak, "losing_streak_distribution": streak_hist,
    }
    mae = _numbers(receipt.get("mae")); mfe = _numbers(receipt.get("mfe"))
    metrics["MAE"] = mean(mae) if len(mae) == len(returns) and mae else NOT_TESTED
    metrics["MFE"] = mean(mfe) if len(mfe) == len(returns) and mfe else NOT_TESTED

    mc: Any = NOT_TESTED
    iterations = receipt.get("monte_carlo_iterations"); seed = receipt.get("random_seed")
    if isinstance(iterations, int) and iterations > 0 and isinstance(seed, int):
        rng = random.Random(seed); dds = []
        for _ in range(iterations):
            sample = list(returns); rng.shuffle(sample); dds.append(_max_drawdown(sample))
        dds.sort()
        mc = {"method": "trade_order_permutation", "iterations": iterations, "random_seed": seed,
              "median_max_drawdown": _percentile(dds, 0.5), "p95_max_drawdown": _percentile(dds, 0.95),
              "worst_max_drawdown": max(dds)}

    parameter_stability = _scenario_summary(receipt.get("parameter_scenarios"))
    regime_stability = _scenario_summary(receipt.get("regime_returns"))
    temporal = _scenario_summary(receipt.get("temporal_returns"))
    edge_decay: Any = NOT_TESTED
    if isinstance(temporal, Mapping) and len(temporal.get("scenarios", [])) >= 2:
        rows = temporal["scenarios"]
        edge_decay = {"first_expectancy": rows[0]["expectancy"], "last_expectancy": rows[-1]["expectancy"],
                      "change": rows[-1]["expectancy"] - rows[0]["expectancy"],
                      "interpretation": "Descriptive temporal change only; no decay cause inferred."}

    dataset_role = str(receipt.get("dataset_role") or "").strip().lower()
    out_of_sample: Any = NOT_TESTED
    if dataset_role in {"untouched_test", "out_of_sample", "oos", "external_test"}:
        out_of_sample = {"state": RESULT_OBSERVED, "dataset_role": dataset_role,
                         "sample_size": len(returns), "expectancy": metrics["expectancy"],
                         "profit_factor": metrics["profit_factor"], "maximum_drawdown": metrics["maximum_drawdown"]}

    walk_forward: Any = NOT_TESTED
    folds = receipt.get("walk_forward_folds")
    if isinstance(folds, Sequence) and not isinstance(folds, (str, bytes, bytearray)):
        fold_rows = []
        for i, raw in enumerate(folds, 1):
            values = _numbers(raw)
            if values:
                fold_rows.append({"fold": i, "n": len(values), "expectancy": mean(values), "maximum_drawdown": _max_drawdown(values)})
        if fold_rows:
            walk_forward = {"state": RESULT_OBSERVED, "folds": fold_rows,
                            "positive_expectancy_fold_fraction": sum(r["expectancy"] > 0 for r in fold_rows) / len(fold_rows)}

    decision = _decision(metrics, receipt.get("decision_rule"))
    return {
        "observed": True, "test_state": RESULT_OBSERVED, "status": decision["status"],
        "provenance": provenance, "unit": text(receipt.get("unit")), "metrics": metrics,
        "risk_of_ruin": NOT_TESTED,
        "risk_of_ruin_reason": "Requires explicit bankroll/ruin boundary and dependence/position-size model; no default is invented.",
        "out_of_sample": out_of_sample, "walk_forward": walk_forward, "monte_carlo": mc,
        "parameter_stability": parameter_stability, "regime_stability": regime_stability,
        "edge_decay": edge_decay, "decision": decision,
    }


def find_result_receipt(result: Mapping[str, Any], hypothesis_id: str) -> Optional[Dict[str, Any]]:
    candidates: List[Any] = []
    for key in ("validation_receipts", "experiment_results", "test_results"):
        raw = result.get(key)
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            candidates.extend(raw)
    coverage = result.get("coverage")
    if isinstance(coverage, Mapping):
        for key in ("validation_receipts", "experiment_results", "test_results"):
            raw = coverage.get(key)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
                candidates.extend(raw)
    for item in candidates:
        if isinstance(item, Mapping) and str(item.get("hypothesis_id") or item.get("id") or "") == str(hypothesis_id):
            return dict(item)
    return None


def find_trading_receipt(result: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ("trading_result_receipt", "trade_result_receipt", "backtest_result_receipt"):
        raw = result.get(key)
        if isinstance(raw, Mapping):
            return dict(raw)
    coverage = result.get("coverage")
    if isinstance(coverage, Mapping):
        for key in ("trading_result_receipt", "trade_result_receipt", "backtest_result_receipt"):
            raw = coverage.get(key)
            if isinstance(raw, Mapping):
                return dict(raw)
    return None
