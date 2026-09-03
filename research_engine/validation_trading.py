"""Trading-specific quantitative validation for AI-2."""
from __future__ import annotations

import math
import random
import statistics
from typing import Any, Dict, Mapping, Sequence

from .validation_stats import bootstrap_mean_ci, quantile
from .validation_types import HypothesisStatus, UNKNOWN, number, numbers, text

_TRADE_COST_FIELDS = ("commission", "spread_cost", "slippage_cost", "financing_cost", "tax_cost")


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
            cur += 1; best = max(best, cur)
        else:
            cur = 0
    return best


def trade_pnl_series(trades: Sequence[Any]) -> Dict[str, Any]:
    """Extract net P&L without silently setting missing gross-trade costs to zero."""
    net, skipped, maes, mfes, regimes = [], [], [], [], []
    friction_total = 0.0
    for idx, raw in enumerate(list(trades or [])):
        if isinstance(raw, Mapping):
            pnl = number(raw.get("net_pnl"))
            if pnl is None:
                gross = number(raw.get("gross_pnl"))
                if gross is None:
                    skipped.append({"index": idx, "reason": "neither net_pnl nor gross_pnl supplied"}); continue
                missing = [key for key in _TRADE_COST_FIELDS if key not in raw or number(raw.get(key)) is None]
                if missing:
                    skipped.append({"index": idx, "reason": "gross row missing explicit friction", "missing": missing}); continue
                costs = sum(float(raw[key]) for key in _TRADE_COST_FIELDS)
                pnl, friction_total = gross - costs, friction_total + costs
            net.append(pnl)
            mae, mfe = number(raw.get("mae")), number(raw.get("mfe"))
            if mae is not None: maes.append(mae)
            if mfe is not None: mfes.append(mfe)
            regimes.append(text(raw.get("regime"), "unknown"))
        else:
            pnl = number(raw)
            if pnl is None:
                skipped.append({"index": idx, "reason": "non-numeric trade outcome"})
            else:
                net.append(pnl); regimes.append("unknown")
    return {"net": net, "friction_total": friction_total, "skipped": skipped,
            "maes": maes, "mfes": mfes, "regimes": regimes}


def trading_metrics(trades: Sequence[Any], *, unit: str = UNKNOWN) -> Dict[str, Any]:
    extracted, net = trade_pnl_series(trades), []
    extracted_net = extracted["net"]
    net.extend(extracted_net)
    if not net:
        reason = "No actual net trade P&L observations supplied."
        if extracted["skipped"]:
            reason += " Some gross rows were unusable because friction was not fully specified."
        return {"status": UNKNOWN, "reason": reason, "skipped_rows": extracted["skipped"]}
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
              "friction_total_from_decomposed_rows": extracted["friction_total"],
              "mae_mean": statistics.fmean(extracted["maes"]) if extracted["maes"] else UNKNOWN,
              "mfe_mean": statistics.fmean(extracted["mfes"]) if extracted["mfes"] else UNKNOWN,
              "risk_of_ruin": UNKNOWN, "skipped_rows": extracted["skipped"],
              "friction_completeness": "COMPLETE FOR USED ROWS" if not extracted["skipped"] else "PARTIAL — skipped rows had incomplete inputs"}
    result["expectancy_bootstrap_ci"] = bootstrap_mean_ci(net, confidence=.95, resamples=2000, seed=20260903) if len(net) >= 2 else {"status": UNKNOWN}
    return result


def monte_carlo_trade_paths(trades: Sequence[Any], *, simulations: int = 5000,
                            seed: int = 20260903, starting_capital: Any = None,
                            ruin_floor: Any = None) -> Dict[str, Any]:
    xs = list(trade_pnl_series(trades)["net"])
    if len(xs) < 2:
        return {"status": UNKNOWN, "reason": "At least two observed net trade outcomes are required."}
    rng, final_pnl, dds, streaks = random.Random(seed), [], [], []
    cap, floor, ruin_count = number(starting_capital), number(ruin_floor), 0
    for _ in range(simulations):
        path = rng.choices(xs, k=len(xs))
        final_pnl.append(sum(path)); dds.append(_max_drawdown_from_pnl(path)); streaks.append(_longest_losing_streak(path))
        if cap is not None and floor is not None:
            equity, ruined = cap, False
            for pnl in path:
                equity += pnl
                if equity <= floor:
                    ruined = True; break
            ruin_count += int(ruined)
    out = {"status": "TEST PERFORMED", "simulations": simulations, "seed": seed,
           "sampling_assumption": "IID bootstrap of supplied observed net trades",
           "final_pnl_p05": quantile(final_pnl, .05), "final_pnl_median": quantile(final_pnl, .5),
           "final_pnl_p95": quantile(final_pnl, .95), "max_drawdown_p50": quantile(dds, .5),
           "max_drawdown_p95": quantile(dds, .95),
           "losing_streak_p95": quantile([float(x) for x in streaks], .95),
           "risk_of_ruin": ruin_count / simulations if cap is not None and floor is not None else UNKNOWN}
    if cap is None or floor is None:
        out["risk_of_ruin_note"] = "starting_capital and ruin_floor were not both supplied."
    return out


def trading_regime_metrics(trades: Sequence[Any], *, unit: str = UNKNOWN) -> Dict[str, Any]:
    groups: Dict[str, list[Any]] = {}
    for raw in list(trades or []):
        if isinstance(raw, Mapping) and text(raw.get("regime")):
            groups.setdefault(text(raw.get("regime")), []).append(raw)
    if not groups:
        return {"status": UNKNOWN, "reason": "No explicit regime labels on supplied trades."}
    return {"status": "TEST PERFORMED",
            "regimes": {name: trading_metrics(rows, unit=unit) for name, rows in sorted(groups.items())}}


def trading_friction_stress(trades: Sequence[Any], multipliers: Sequence[Any], *,
                            unit: str = UNKNOWN) -> Dict[str, Any]:
    ms = numbers(multipliers)
    if not ms:
        return {"status": UNKNOWN, "reason": "No caller-supplied friction multipliers."}
    rows = [r for r in list(trades or []) if isinstance(r, Mapping) and number(r.get("gross_pnl")) is not None]
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
        scenarios.append({"friction_multiplier": multiplier, "metrics": trading_metrics(stressed, unit=unit)})
    return {"status": "TEST PERFORMED", "scenarios": scenarios,
            "note": "Stress applies caller-supplied multipliers only to explicitly decomposed monetary friction."}


def edge_decay_analysis(values: Sequence[Any], *, window: int,
                        maximum_allowed_decay: Any = None) -> Dict[str, Any]:
    xs = numbers(values)
    if window < 2 or len(xs) < 2 * window:
        return {"status": UNKNOWN, "reason": "Need at least two full windows of observed ordered outcomes."}
    means = [statistics.fmean(xs[i:i + window]) for i in range(0, len(xs) - window + 1, window)]
    if len(means) < 2:
        return {"status": UNKNOWN, "reason": "Need at least two complete non-overlapping windows."}
    xbar, ybar = statistics.fmean(range(len(means))), statistics.fmean(means)
    den = sum((i - xbar) ** 2 for i in range(len(means)))
    slope = sum((i - xbar) * (v - ybar) for i, v in enumerate(means)) / den if den else 0.0
    drop, limit = means[0] - means[-1], number(maximum_allowed_decay)
    verdict = UNKNOWN if limit is None else (HypothesisStatus.PASS.value if drop <= limit else HypothesisStatus.FAIL.value)
    return {"status": "TEST PERFORMED", "window": window, "window_expectancies": means,
            "linear_slope_per_window": slope, "first_to_last_decay": drop,
            "caller_maximum_allowed_decay": limit if limit is not None else UNKNOWN,
            "decay_verdict": verdict}


__all__ = [
    "trade_pnl_series", "trading_metrics", "monte_carlo_trade_paths",
    "trading_regime_metrics", "trading_friction_stress", "edge_decay_analysis",
]
