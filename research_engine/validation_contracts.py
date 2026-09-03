"""Shared contracts for AI-2 quantitative validation."""
from __future__ import annotations
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Sequence, Tuple

AGENT_ID = "AI-2 / VALIDATION-DIRECTOR"
SCHEMA_VERSION = "ai2-validation-packet/v1"
UNKNOWN = "UNKNOWN"
TO_BE_ESTIMATED = "TO BE ESTIMATED"
NOT_TESTED = "NOT TESTED"
TEST_PROPOSED = "TEST PROPOSED"
TEST_POSSIBLE = "TEST POSSIBLE"
TEST_PERFORMED = "TEST PERFORMED"
RESULT_OBSERVED = "RESULT OBSERVED"
TEST_STATES = {TEST_PROPOSED, TEST_POSSIBLE, TEST_PERFORMED, RESULT_OBSERVED}
PASS = "PASS"
CONDITIONAL_PASS = "CONDITIONAL PASS"
INCONCLUSIVE = "INCONCLUSIVE"
FAIL = "FAIL"
HYPOTHESIS_STATUSES = {PASS, CONDITIONAL_PASS, INCONCLUSIVE, FAIL}

REQUIRED_SECTIONS: Tuple[str, ...] = (
    "1. Interpretation of User Goal", "2. Quantifiable Components",
    "3. Mathematical Model", "4. Baselines", "5. Independent Testable Hypotheses",
    "6. Exact Experiments / Backtests / Simulations Required", "7. Bias & Leakage Risks",
    "8. Robustness Plan", "9. Ablation Plan", "10. Real-World Friction",
    "11. Failure Modes", "12. What Can Be Tested Now", "13. What Cannot Yet Be Tested",
    "14. Cross-Agent Alerts", "15. Highest-Value Second-Pass Validation Tasks",
    "16. Confidence /100", "17. Exactly What Prevents a Higher Score",
)
EXPERIMENT_FIELDS: Tuple[str, ...] = (
    "Hypothesis", "Variables", "Dataset/sample", "Experimental setup", "Prediction",
    "Null hypothesis", "Metric", "Baseline", "Confounders", "Falsification condition",
    "Replication method",
)
TRADING_FIELDS: Tuple[str, ...] = (
    "exact_instrument", "feed_assumptions", "futures_vs_cfd_relationship", "timeframe",
    "regime", "session", "long_rules", "short_rules", "entry", "stop", "target",
    "position_sizing", "no_trade_rules", "news_filtering", "spread", "commission",
    "slippage", "latency", "sample_size", "win_rate", "average_win", "average_loss",
    "expectancy", "profit_factor", "maximum_drawdown", "losing_streak_distribution",
    "risk_of_ruin", "MAE", "MFE", "out_of_sample", "walk_forward", "monte_carlo",
    "parameter_stability", "regime_stability", "edge_decay",
)
BIAS_RISKS = (
    "look-ahead bias", "hindsight bias", "survivorship bias", "selection bias",
    "confirmation bias", "data snooping", "cherry-picking", "p-hacking",
    "publication bias", "revised data", "future-known information",
    "hidden target leakage", "repeated tuning on final data",
)
ROBUSTNESS_DIMENSIONS = (
    "nearby parameter values", "different time periods", "alternative definitions",
    "reasonable noise", "reduced data", "changed assumptions", "different regimes",
    "external dataset or site", "temporal replication",
)
FRICTION_FACTORS = (
    "transaction costs", "slippage", "latency", "liquidity", "taxes", "regulation",
    "hardware", "compute", "measurement error", "manufacturing tolerances", "human error",
    "implementation difficulty", "maintenance", "opportunity cost",
)
FAILURE_DIMENSIONS = (
    "failure frequency", "failure severity", "failure regime", "failure clustering",
    "worst case", "catastrophic failure", "tail risk", "stress scenarios",
    "Monte Carlo failure distribution",
)
TRADING_TERMS = (
    "trading", "trade", "strategy", "backtest", "forex", "cfd", "futures", "xauusd",
    "gold", "us100", "nas100", "nasdaq", "spx", "crypto", "entry", "stop loss",
    "take profit", "profit factor", "drawdown",
)


def meaningful(value: Any) -> bool:
    if value is None or isinstance(value, bool): return False
    if isinstance(value, str): return bool(value.strip())
    if isinstance(value, Mapping): return bool(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)): return bool(value)
    return True


def text(value: Any, fallback: str = UNKNOWN) -> str:
    if not meaningful(value): return fallback
    return value.strip() if isinstance(value, str) else str(value)


def first(mapping: Mapping[str, Any], *keys: str, fallback: Any = None) -> Any:
    for key in keys:
        value = mapping.get(key)
        if meaningful(value): return value
    return fallback


def as_list(value: Any) -> List[Any]:
    if value is None: return []
    if isinstance(value, list): return value
    if isinstance(value, tuple): return list(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)): return list(value)
    return [value]


def clean_status(value: Any) -> str:
    status = str(value or "").strip().upper()
    status = {
        "CONDITIONAL_PASS": CONDITIONAL_PASS, "CONDITIONAL": CONDITIONAL_PASS,
        "PASSED": PASS, "FAILED": FAIL, "REJECTED": FAIL, "SUPPORTED": CONDITIONAL_PASS,
        "UNTESTED": INCONCLUSIVE, "UNTESTED HYPOTHESIS": INCONCLUSIVE, "UNKNOWN": INCONCLUSIVE,
    }.get(status, status)
    return status if status in HYPOTHESIS_STATUSES else INCONCLUSIVE


def looks_like_hypothesis(item: Mapping[str, Any]) -> bool:
    keys = {str(k).lower() for k in item}
    return bool(keys & {"hypothesis", "statement", "prediction", "falsification_test",
                        "falsification_condition", "how_to_test", "experiment"})


def extract_hypotheses(result: Mapping[str, Any], limit: int = 24) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []; seen = set()
    def visit(value: Any, depth: int = 0) -> None:
        if depth > 5 or len(found) >= limit: return
        if isinstance(value, Mapping):
            if looks_like_hypothesis(value):
                identity = text(first(value, "id", "hypothesis_id", "statement", "hypothesis"), repr(sorted(value.keys())))
                if identity not in seen:
                    seen.add(identity); found.append(dict(value))
            for key, child in value.items():
                if str(key).lower() in {"hypotheses", "candidates", "ranked", "surviving", "survivors",
                                         "tournament", "advanced_discovery", "discovery", "analysis"}:
                    visit(child, depth + 1)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for child in value: visit(child, depth + 1)
    for key in ("hypotheses", "advanced_discovery", "discovery", "analysis", "coverage"):
        if key in result: visit(result.get(key))
    return found


def has_observed_provenance(item: Mapping[str, Any]) -> bool:
    provenance = first(item, "result_provenance", "provenance", "test_provenance")
    if not isinstance(provenance, Mapping): return False
    keys = ("test_id", "run_id", "dataset_id", "source", "source_id", "timestamp", "artifact", "report", "observed_metrics")
    return any(meaningful(provenance.get(key)) for key in keys)


def test_state(item: Mapping[str, Any]) -> str:
    state = str(first(item, "test_state", "provenance_state", fallback=TEST_PROPOSED)).strip().upper()
    aliases = {"PROPOSED": TEST_PROPOSED, "POSSIBLE": TEST_POSSIBLE, "PERFORMED": TEST_PERFORMED,
               "OBSERVED": RESULT_OBSERVED, "RESULT": RESULT_OBSERVED}
    state = aliases.get(state, state)
    if state not in TEST_STATES: state = TEST_PROPOSED
    if state == RESULT_OBSERVED and not has_observed_provenance(item): return TEST_PERFORMED
    return state


def is_trading(question: str) -> bool:
    q = str(question or "").lower()
    return any(term in q for term in TRADING_TERMS)


def source_count(result: Mapping[str, Any]) -> int:
    sources = result.get("sources")
    return len(sources) if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes, bytearray)) else 0


def existing_experiment_intelligence(result: Mapping[str, Any]) -> Dict[str, Any]:
    candidates = [("experiment_intelligence", result.get("experiment_intelligence")),
                  ("runtime_experiment_packet", result.get("runtime_experiment_packet")),
                  ("experiment_packet", result.get("experiment_packet"))]
    coverage = result.get("coverage")
    if isinstance(coverage, Mapping):
        candidates += [("coverage.experiment_intelligence", coverage.get("experiment_intelligence")),
                       ("coverage.runtime_experiment_packet", coverage.get("runtime_experiment_packet")),
                       ("coverage.experiment_packet", coverage.get("experiment_packet"))]
    for path, value in candidates:
        if isinstance(value, Mapping) and value:
            return {"present": True, "source_path": path, "packet": deepcopy(dict(value)),
                    "interpretation": "UPSTREAM TEST PLANNING ONLY unless explicit executed-result provenance exists."}
    return {"present": False, "source_path": UNKNOWN, "packet": {},
            "interpretation": "No upstream experiment-intelligence packet supplied."}


def trade_contract(result: Mapping[str, Any]) -> Dict[str, Any]:
    candidates = [("trade_contract", result.get("trade_contract"))]
    coverage = result.get("coverage")
    if isinstance(coverage, Mapping): candidates.append(("coverage.trade_contract", coverage.get("trade_contract")))
    for path, value in candidates:
        if isinstance(value, Mapping) and value:
            return {"present": True, "source_path": path, "contract": deepcopy(dict(value))}
    return {"present": False, "source_path": UNKNOWN, "contract": {}}


def second_pass_summary(outputs: Any) -> Dict[str, Any]:
    if not isinstance(outputs, Mapping) or not outputs:
        return {"present": False, "agents_received": [], "structured_hypotheses_received": 0,
                "red_team_input_present": False, "rule": "No second-pass outputs supplied; do not invent disagreements."}
    agents = [str(k) for k in outputs]
    count = 0; red_team = False
    for key, value in outputs.items():
        key_lower = str(key).lower()
        red_team = red_team or any(token in key_lower for token in ("ai-4", "red", "advers"))
        if isinstance(value, Mapping):
            count += len(extract_hypotheses(value))
            probe = str(value).lower()
            red_team = red_team or any(token in probe for token in ("red-team", "red team", "objection", "catastrophic"))
    return {"present": True, "agents_received": agents, "structured_hypotheses_received": count,
            "red_team_input_present": red_team,
            "rule": "Do not restart; validate strongest/disputed/merged claims and red-team objections by information gain."}
