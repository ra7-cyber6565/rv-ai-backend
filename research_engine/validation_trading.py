"""Research-only market-strategy validation contract for AI-2. Does not execute trades."""
from __future__ import annotations
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Sequence
from .validation_contracts import NOT_TESTED, TRADING_FIELDS, UNKNOWN, first, meaningful, trade_contract


def trading_standard(hypotheses: Sequence[Mapping[str, Any]], result: Mapping[str, Any]) -> Dict[str, Any]:
    values = {field: UNKNOWN for field in TRADING_FIELDS}
    aliases = {
        "exact_instrument": ("instrument", "symbol", "market"),
        "feed_assumptions": ("feed_assumptions", "feed", "data_feed"),
        "futures_vs_cfd_relationship": ("futures_vs_cfd_relationship", "basis_mapping", "cfd_futures_mapping"),
        "timeframe": ("timeframe", "time_frame"), "regime": ("regime",), "session": ("session",),
        "long_rules": ("long_rules", "long_entry"), "short_rules": ("short_rules", "short_entry"),
        "entry": ("entry", "entry_rule"), "stop": ("stop", "stop_loss", "sl"),
        "target": ("target", "take_profit", "tp"), "position_sizing": ("position_sizing", "risk_rule", "risk"),
        "no_trade_rules": ("no_trade_rules", "avoid_rules"), "news_filtering": ("news_filtering", "news_filter"),
        "spread": ("spread",), "commission": ("commission",), "slippage": ("slippage",),
        "latency": ("latency",), "sample_size": ("sample_size", "trades"),
    }
    upstream = trade_contract(result); sources: List[Mapping[str, Any]] = []
    if upstream["present"]: sources.append(upstream["contract"])
    for h in hypotheses:
        combined = dict(h); exp = h.get("experiment")
        if isinstance(exp, Mapping): combined.update(exp)
        sources.append(combined)
    for source in sources:
        for target, keys in aliases.items():
            if values[target] == UNKNOWN and meaningful(first(source, *keys)):
                values[target] = deepcopy(first(source, *keys))
    performance_fields = (
        "win_rate", "average_win", "average_loss", "expectancy", "profit_factor", "maximum_drawdown",
        "losing_streak_distribution", "risk_of_ruin", "MAE", "MFE", "out_of_sample", "walk_forward",
        "monte_carlo", "parameter_stability", "regime_stability", "edge_decay",
    )
    for field in performance_fields: values[field] = NOT_TESTED
    values["validation_rule"] = "Targets, narratives and planned simulations never populate performance metrics; only executed, provenance-bearing validation may do so."
    values["friction_rule"] = "Net evaluation must include feed-appropriate spread, commission, slippage, latency and liquidity assumptions."
    values["upstream_trade_contract"] = upstream
    return values
