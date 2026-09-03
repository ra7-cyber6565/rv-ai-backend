"""Trading-specific quantitative validation for AI-2.

Every caller-controlled collection/iteration that can create material CPU or
memory work is bounded before expensive work starts. Oversized requests return a
machine-readable RESOURCE_LIMIT_EXCEEDED receipt; nothing is silently sampled,
truncated or run with fewer simulations than requested.
"""
from __future__ import annotations

from itertools import islice
import math
import random
import statistics
from typing import Any, Dict, Mapping, Sequence

from .validation_limits import (
    MAX_FRICTION_SCENARIOS,
    MAX_MONTE_CARLO_SIMULATIONS,
    MAX_MONTE_CARLO_WORK_UNITS,
    MAX_TRADES,
    MAX_TRADING_REGIMES,
    MAX_TRADING_STRESS_WORK_UNITS,
    bounded_iterations,
    bounded_length,
    resource_error,
    strict_int,
)
from .validation_stats import bootstrap_mean_ci, quantile
from .validation_types import HypothesisStatus, UNKNOWN, number, numbers, text

_TRADE_COST_FIELDS = ("commission", "spread_cost", "slippage_cost", "financing_cost", "tax_cost")


def _bounded_materialize(values: Any, *, maximum: int, field: str):
    """Materialize a caller collection without letting an unsized iterator run forever."""
    if values is None:
        return [], None
    limit = bounded_length(values, maximum, field)
    if limit:
        return [], limit
    try:
        len(values)
    except (TypeError, AttributeError):
        try:
            rows = list(islice(iter(values), maximum + 1))
        except TypeError:
            return [], {"status": UNKNOWN, "reason": f"{field} must be an iterable collection."}
        if len(rows) > maximum:
            return [], resource_error(field, f">{maximum}", f"count exceeds hard maximum {maximum}")
        return rows, None
    try:
        return list(values), None
    except TypeError:
        return [], {"status": UNKNOWN, "reason": f"{field} must be an iterable collection."}


def _max_drawdown_from_pnl(pnl: Sequence[float]) -> float:
    equity = peak = max_dd = 0.0
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _longest_losing_streak(pnl: Sequence[float]) -> int:
    best = cur = 0
    for value in pnl:
        if value < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def trade_pnl_series(trades: Sequence[Any]) -> Dict[str, Any]:
    """Extract net P&L without silently setting missing gross-trade costs to zero."""
    rows, limit = _bounded_materialize(trades, maximum=MAX_TRADES, field="trades")
    if limit:
        return limit

    net, skipped, maes, mfes, regimes = [], [], [], [], []
    friction_total = 0.0
    for idx, raw in enumerate(rows):
        if isinstance(raw, Mapping):
            pnl = number(raw.get("net_pnl"))
            if pnl is None:
                gross = number(raw.get("gross_pnl"))
                if gross is None:
                    skipped.append({"index": idx, "reason": "neither net_pnl nor gross_pnl supplied"})
                    continue
                missing = [key for key in _TRADE_COST_FIELDS if key not in raw or number(raw.get(key)) is None]
                if missing:
                    skipped.append({"index": idx, "reason": "gross row missing explicit friction", "missing": missing})
                    continue
                costs = sum(float(raw[key]) for key in _TRADE_COST_FIELDS)
                pnl, friction_total = gross - costs, friction_total + costs
            net.append(pnl)
            mae, mfe = number(raw.get("mae")), number(raw.get("mfe"))
            if mae is not None:
                maes.append(mae)
            if mfe is not None:
                mfes.append(mfe)
            regimes.append(text(raw.get("regime"), "unknown"))
        else:
            pnl = number(raw)
            if pnl is None:
                skipped.append({"index": idx, "reason": "non-numeric trade outcome"})
            else:
                net.append(pnl)
                regimes.append("unknown")
    return {"net": net, "friction_total": friction_total, "skipped": skipped,
            "maes": maes, "mfes": mfes, "regimes": regimes}


def trading_metrics(trades: Sequence[Any], *, unit: str = UNKNOWN,
                    _include_bootstrap: bool = True) -> Dict[str, Any]:
    extracted = trade_pnl_series(trades)
    if extracted.get("status") == "RESOURCE_LIMIT_EXCEEDED":
        return extracted
    net = list(extracted.get("net") or [])
    if not net:
        reason = "No actual net trade P&L observations supplied."
        if extracted.get("skipped"):
            reason += " Some gross rows were unusable because friction was not fully specified."
        return {"status": UNKNOWN, "reason": reason, "skipped_rows": extracted.get("skipped", [])}
    wins, losses = [x for x in net if x > 0], [x for x in net if x < 0]
    gp, gl = sum(wins), -sum(losses)
    result = {"status": "RESULT OBSERVED", "unit": unit, "sample_size": len(net),
              "win_rate": len(wins) / len(net),
              "average_win": statistics.fmean(wins) if wins else 0.0,
              "average_loss": statistics.fmean(losses) if losses else 0.0,
              "expectancy": statistics.fmean(net),
              "profit_factor": gp / gl if gl > 0 else (math.inf if gp > 0 else UNKNOWN),
              "net_total": sum(net), "maximum_drawdown": _max_drawdown_from_pnl(net),
              "longest_losing_streak": _longest_losing_streak(net),
              "friction_total_from_decomposed_rows": extracted.get("friction_total", 0.0),
              "mae_mean": statistics.fmean(extracted.get("maes") or []) if extracted.get("maes") else UNKNOWN,
              "mfe_mean": statistics.fmean(extracted.get("mfes") or []) if extracted.get("mfes") else UNKNOWN,
              "risk_of_ruin": UNKNOWN, "skipped_rows": extracted.get("skipped", []),
              "friction_completeness": "COMPLETE FOR USED ROWS" if not extracted.get("skipped") else "PARTIAL — skipped rows had incomplete inputs"}
    if _include_bootstrap and len(net) >= 2:
        result["expectancy_bootstrap_ci"] = bootstrap_mean_ci(
            net, confidence=.95, resamples=2000, seed=20260903)
    elif _include_bootstrap:
        result["expectancy_bootstrap_ci"] = {"status": UNKNOWN}
    else:
        result["expectancy_bootstrap_ci"] = {
            "status": UNKNOWN,
            "reason": "Bootstrap intentionally not repeated inside multi-scenario friction stress.",
        }
    return result


def monte_carlo_trade_paths(trades: Sequence[Any], *, simulations: int = 5000,
                            seed: int = 20260903, starting_capital: Any = None,
                            ruin_floor: Any = None) -> Dict[str, Any]:
    extracted = trade_pnl_series(trades)
    if extracted.get("status") == "RESOURCE_LIMIT_EXCEEDED":
        return extracted
    xs = list(extracted.get("net") or [])
    if len(xs) < 2:
        return {"status": UNKNOWN, "reason": "At least two observed net trade outcomes are required."}
    count, error = bounded_iterations(
        simulations,
        default=5000,
        minimum=100,
        maximum=MAX_MONTE_CARLO_SIMULATIONS,
        field="monte_carlo_simulations",
        sample_size=len(xs),
        max_work_units=MAX_MONTE_CARLO_WORK_UNITS,
    )
    if error:
        return error

    rng, final_pnl, dds, streaks = random.Random(seed), [], [], []
    cap, floor, ruin_count = number(starting_capital), number(ruin_floor), 0
    for _ in range(count):
        path = rng.choices(xs, k=len(xs))
        final_pnl.append(sum(path))
        dds.append(_max_drawdown_from_pnl(path))
        streaks.append(_longest_losing_streak(path))
        if cap is not None and floor is not None:
            equity, ruined = cap, False
            for pnl in path:
                equity += pnl
                if equity <= floor:
                    ruined = True
                    break
            ruin_count += int(ruined)
    out = {"status": "TEST PERFORMED", "simulations": count, "seed": seed,
           "sampling_assumption": "IID bootstrap of supplied observed net trades",
           "final_pnl_p05": quantile(final_pnl, .05), "final_pnl_median": quantile(final_pnl, .5),
           "final_pnl_p95": quantile(final_pnl, .95), "max_drawdown_p50": quantile(dds, .5),
           "max_drawdown_p95": quantile(dds, .95),
           "losing_streak_p95": quantile([float(x) for x in streaks], .95),
           "risk_of_ruin": ruin_count / count if cap is not None and floor is not None else UNKNOWN}
    if cap is None or floor is None:
        out["risk_of_ruin_note"] = "starting_capital and ruin_floor were not both supplied."
    return out


def trading_regime_metrics(trades: Sequence[Any], *, unit: str = UNKNOWN) -> Dict[str, Any]:
    rows, limit = _bounded_materialize(trades, maximum=MAX_TRADES, field="trades")
    if limit:
        return limit
    groups: Dict[str, list[Any]] = {}
    for raw in rows:
        if isinstance(raw, Mapping) and text(raw.get("regime")):
            name = text(raw.get("regime"))
            if name not in groups and len(groups) >= MAX_TRADING_REGIMES:
                return resource_error(
                    "trading_regimes",
                    len(groups) + 1,
                    f"count exceeds hard maximum {MAX_TRADING_REGIMES}",
                )
            groups.setdefault(name, []).append(raw)
    if not groups:
        return {"status": UNKNOWN, "reason": "No explicit regime labels on supplied trades."}
    return {"status": "TEST PERFORMED",
            "regimes": {name: trading_metrics(group_rows, unit=unit)
                        for name, group_rows in sorted(groups.items())}}


def trading_friction_stress(trades: Sequence[Any], multipliers: Sequence[Any], *,
                            unit: str = UNKNOWN) -> Dict[str, Any]:
    trade_rows, trade_limit = _bounded_materialize(trades, maximum=MAX_TRADES, field="trades")
    if trade_limit:
        return trade_limit
    multiplier_rows, multiplier_limit = _bounded_materialize(
        multipliers, maximum=MAX_FRICTION_SCENARIOS, field="friction_scenarios")
    if multiplier_limit:
        return multiplier_limit
    ms = numbers(multiplier_rows)
    if not ms:
        return {"status": UNKNOWN, "reason": "No caller-supplied friction multipliers."}
    work = len(trade_rows) * len(ms)
    if work > MAX_TRADING_STRESS_WORK_UNITS:
        return resource_error(
            "friction_stress_work_units",
            work,
            f"requested work exceeds hard budget {MAX_TRADING_STRESS_WORK_UNITS}",
        )

    rows = [r for r in trade_rows if isinstance(r, Mapping) and number(r.get("gross_pnl")) is not None]
    usable = [r for r in rows if all(key in r and number(r.get(key)) is not None for key in _TRADE_COST_FIELDS)]
    if not usable:
        return {"status": UNKNOWN, "reason": "No gross trade rows with complete friction decomposition."}
    scenarios = []
    for multiplier in ms:
        stressed = []
        for row in usable:
            gross = float(row["gross_pnl"])
            cost = sum(float(row[key]) for key in _TRADE_COST_FIELDS)
            stressed.append(gross - multiplier * cost)
        scenarios.append({
            "friction_multiplier": multiplier,
            "metrics": trading_metrics(stressed, unit=unit, _include_bootstrap=False),
        })
    return {"status": "TEST PERFORMED", "scenarios": scenarios,
            "note": "Stress applies caller-supplied multipliers only to explicitly decomposed monetary friction. Bootstrap is not redundantly rerun inside every stress scenario."}


def edge_decay_analysis(values: Sequence[Any], *, window: int,
                        maximum_allowed_decay: Any = None) -> Dict[str, Any]:
    rows, limit = _bounded_materialize(values, maximum=MAX_TRADES, field="ordered_trade_outcomes")
    if limit:
        return limit
    parsed_window = strict_int(window)
    if parsed_window is None or parsed_window < 2:
        return {"status": UNKNOWN, "reason": "window must be an integer >= 2."}
    xs = numbers(rows)
    if len(xs) < 2 * parsed_window:
        return {"status": UNKNOWN, "reason": "Need at least two full windows of observed ordered outcomes."}
    means = [statistics.fmean(xs[i:i + parsed_window])
             for i in range(0, len(xs) - parsed_window + 1, parsed_window)]
    if len(means) < 2:
        return {"status": UNKNOWN, "reason": "Need at least two complete non-overlapping windows."}
    xbar, ybar = statistics.fmean(range(len(means))), statistics.fmean(means)
    den = sum((i - xbar) ** 2 for i in range(len(means)))
    slope = sum((i - xbar) * (v - ybar) for i, v in enumerate(means)) / den if den else 0.0
    drop, allowed = means[0] - means[-1], number(maximum_allowed_decay)
    verdict = UNKNOWN if allowed is None else (
        HypothesisStatus.PASS.value if drop <= allowed else HypothesisStatus.FAIL.value)
    return {"status": "TEST PERFORMED", "window": parsed_window, "window_expectancies": means,
            "linear_slope_per_window": slope, "first_to_last_decay": drop,
            "caller_maximum_allowed_decay": allowed if allowed is not None else UNKNOWN,
            "decay_verdict": verdict}


__all__ = [
    "trade_pnl_series", "trading_metrics", "monte_carlo_trade_paths",
    "trading_regime_metrics", "trading_friction_stress", "edge_decay_analysis",
]
