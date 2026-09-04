"""Explicit-input risk-of-ruin simulation for AI-2 trading validation.

No bankroll, ruin boundary, horizon, dependence model, iterations, or seed is
defaulted. Results are conditional on the supplied return model and assumptions.
"""
from __future__ import annotations

import math
import random
from statistics import mean
from typing import Any, Dict, List, Mapping, Sequence

from .validation_contracts import INCONCLUSIVE, NOT_TESTED, RESULT_OBSERVED


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


def simulate_risk_of_ruin(receipt: Mapping[str, Any], trade_returns: Sequence[float]) -> Any:
    """Bootstrap future paths only when every necessary assumption is explicit."""
    returns = _numbers(trade_returns)
    if not returns:
        return NOT_TESTED
    starting_equity = receipt.get("starting_equity")
    ruin_equity = receipt.get("ruin_equity")
    horizon = receipt.get("risk_of_ruin_horizon_trades")
    iterations = receipt.get("risk_of_ruin_simulations")
    seed = receipt.get("risk_of_ruin_random_seed")
    return_mode = str(receipt.get("risk_of_ruin_return_mode") or "").strip().lower()
    dependence_model = str(receipt.get("risk_of_ruin_dependence_model") or "").strip().lower()
    try:
        starting = float(starting_equity); ruin = float(ruin_equity)
    except (TypeError, ValueError):
        return {"status": NOT_TESTED, "reason": "starting_equity and ruin_equity must be explicitly numeric."}
    if not (math.isfinite(starting) and math.isfinite(ruin) and starting > ruin >= 0):
        return {"status": NOT_TESTED, "reason": "Require finite starting_equity > ruin_equity >= 0."}
    if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon <= 0:
        return {"status": NOT_TESTED, "reason": "Explicit positive risk_of_ruin_horizon_trades is required."}
    if not isinstance(iterations, int) or isinstance(iterations, bool) or iterations <= 0 or not isinstance(seed, int):
        return {"status": NOT_TESTED, "reason": "Explicit positive simulations count and integer random seed are required."}
    if return_mode not in {"fractional_equity", "absolute_equity"}:
        return {"status": NOT_TESTED, "reason": "risk_of_ruin_return_mode must be fractional_equity or absolute_equity."}
    if dependence_model not in {"iid_bootstrap", "block_bootstrap"}:
        return {"status": NOT_TESTED, "reason": "risk_of_ruin_dependence_model must be iid_bootstrap or block_bootstrap."}
    block_length = receipt.get("risk_of_ruin_block_length")
    if dependence_model == "block_bootstrap":
        if not isinstance(block_length, int) or isinstance(block_length, bool) or not (1 <= block_length <= len(returns)):
            return {"status": NOT_TESTED, "reason": "Explicit valid risk_of_ruin_block_length is required for block_bootstrap."}

    rng = random.Random(seed)
    ruined = 0
    terminal_equities: List[float] = []
    ruin_times: List[int] = []

    def draw_path() -> List[float]:
        if dependence_model == "iid_bootstrap":
            return [returns[rng.randrange(len(returns))] for _ in range(horizon)]
        path: List[float] = []
        assert isinstance(block_length, int)
        while len(path) < horizon:
            if len(returns) == block_length:
                start = 0
            else:
                start = rng.randrange(0, len(returns) - block_length + 1)
            path.extend(returns[start:start + block_length])
        return path[:horizon]

    for _ in range(iterations):
        equity = starting
        hit = False
        for trade_index, trade_return in enumerate(draw_path(), 1):
            if return_mode == "fractional_equity":
                equity *= (1.0 + trade_return)
            else:
                equity += trade_return
            if not math.isfinite(equity) or equity <= ruin:
                ruined += 1
                ruin_times.append(trade_index)
                hit = True
                break
        terminal_equities.append(equity)
        if hit:
            continue

    terminal_equities.sort()
    q05_index = max(0, min(len(terminal_equities) - 1, int(math.floor(0.05 * (len(terminal_equities) - 1)))))
    q50_index = max(0, min(len(terminal_equities) - 1, int(math.floor(0.50 * (len(terminal_equities) - 1)))))
    return {
        "status": "CALCULATED",
        "test_state": RESULT_OBSERVED,
        "risk_of_ruin": ruined / iterations,
        "simulations": iterations,
        "horizon_trades": horizon,
        "starting_equity": starting,
        "ruin_equity": ruin,
        "return_mode": return_mode,
        "dependence_model": dependence_model,
        "block_length": block_length if dependence_model == "block_bootstrap" else NOT_TESTED,
        "random_seed": seed,
        "mean_ruin_time_conditional_on_ruin": mean(ruin_times) if ruin_times else NOT_TESTED,
        "median_terminal_equity": terminal_equities[q50_index],
        "p05_terminal_equity": terminal_equities[q05_index],
        "interpretation": "Simulation estimate conditional on the supplied empirical return sample, horizon and bootstrap dependence model; it is not a universal ruin probability.",
        "assumption_warning": "IID bootstrap destroys serial dependence; block bootstrap preserves only dependence up to the supplied block design. Structural breaks and edge decay still require separate stress/regime tests.",
    }
