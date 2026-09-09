"""Fail-closed final acceptance for explicit trading-model deliverables.

The generic structured-answer gate checks headings/coverage. A deployed Max
acceptance run showed why that is not sufficient for trading: a response can
look structurally complete while the requested trading model, validation,
technical script, or numeric rule provenance is still absent. This deterministic
gate runs on the final ``ResearchResult.to_dict`` payload and can only downgrade
completion.

It does not decide whether a strategy is profitable. It only asks whether the
specific deliverables requested by the user are actually present/measured by
the existing trading contract. A requested backtest that did not run remains a
missing deliverable; prose never becomes a test, and a hard-coded trading
threshold never becomes evidence merely because it contains a number.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from . import trademodel

_COMPLETE = "COMPLETE"
_PARTIAL = "PARTIAL"
_MARKER = "TRADING ACCEPTANCE GAP"

_DEMAND_TO_POINT = {
    "walk_forward": "walk_forward_validation",
    "out_of_sample": "walk_forward_validation",
    "monte_carlo": "monte_carlo_risk",
    "robustness": "parameter_robustness",
    "baseline": "baseline_tournament",
    "leakage": "no_leakage",
    "costs": "realistic_costs",
    "red_team": "red_team",
    "regime": "regime_detection",
    "session": "session_expectancy",
    "macro_events": "macro_event_windows",
    "intermarket": "intermarket_tests",
    "information_theory": "information_theory",
    "game_theory": "game_theory",
    "microstructure": "theory_base",
    "risk_sizing": "performance_metrics",
}

_SCRIPT_REQUEST_RE = re.compile(
    r"(?:\bpython\b[^\n]{0,80}\bscript\b|\bpine\s*script\b|\bpinescript\b|"
    r"\bback[- ]?test(?:ing)?\b[^\n]{0,80}\bscript\b|"
    r"\b(?:code|script)\b[^\n]{0,80}\b(?:python|pine|tradingview|back[- ]?test)\b)",
    re.IGNORECASE,
)
_FENCED_CODE_RE = re.compile(r"```\s*([a-zA-Z0-9_+.-]*)\s*\n([\s\S]*?)```", re.MULTILINE)
_SOURCE_CITATION_RE = re.compile(r"\[S\d+\]", re.IGNORECASE)
_TRADING_THRESHOLD_TERM_RE = re.compile(
    r"\b(?:rsi|adx|atr|vwap|volume|volatility|spread|slippage|commission|"
    r"drawdown|risk(?:\s+per\s+trade)?|stop(?:[-\s]?loss)?|take[-\s]?profit|"
    r"target|reward|r\s*:\s*r|rr|mae|mfe|imbalance|fvg|order\s+block|"
    r"liquidity|percentile|z[-\s]?score|standard\s+deviation|std|correlation|"
    r"entropy|mutual\s+information|probability|win\s+rate|profit\s+factor|"
    r"sharpe|sortino|expectancy|entry|trigger|no[-\s]?trade)\b",
    re.IGNORECASE,
)
_RULE_NUMBER_RE = re.compile(
    r"(?:>=|<=|>|<|=)\s*\d+(?:\.\d+)?\s*%?"
    r"|\b(?:above|below|over|under|at\s+least|at\s+most|minimum|maximum|"
    r"threshold|risk\s+per\s+trade|stop(?:[-\s]?loss)?|take[-\s]?profit|target)\b"
    r"[^\n.;]{0,36}\d+(?:\.\d+)?\s*(?:%|r\b|atr\b|points?\b|ticks?\b)?",
    re.IGNORECASE,
)
_NON_RULE_RE = re.compile(
    r"^[\s>*#-]*(?:illustrative\s+(?:example|candidate)|example\s+only|"
    r"hypothesis\s+only|test\s+proposed|do\s+not\s+(?:use|set|enter|trade))\b",
    re.IGNORECASE,
)


def _dedupe(values: Iterable[Any]) -> List[str]:
    out: List[str] = []
    for value in values or ():
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _technical_script_requested(question: str) -> bool:
    return bool(_SCRIPT_REQUEST_RE.search(str(question or "")))


def _technical_script_delivered(answer: str) -> bool:
    """Conservative code-presence check; never executes or judges profitability."""
    for match in _FENCED_CODE_RE.finditer(str(answer or "")):
        lang = (match.group(1) or "").strip().lower()
        body = (match.group(2) or "").strip()
        if len(body) < 120:
            continue
        lower = body.lower()
        if lang in {"pine", "pinescript"} or "//@version=" in lower:
            if "strategy(" in lower or "indicator(" in lower:
                return True
        if lang in {"python", "py"} or re.search(r"\b(?:import|def)\s+", body):
            programming = bool(re.search(r"\b(?:import|def|class|for|while)\b", lower))
            trading = bool(re.search(
                r"\b(?:backtest|entry|position|trade|pnl|returns?|stop|target|slippage|commission)\b",
                lower,
            ))
            if programming and trading:
                return True
    return False


def unsupported_numeric_thresholds(answer: str) -> List[Dict[str, Any]]:
    """Find prose decision thresholds without an explicit source reference.

    Code blocks are excluded: this gate audits the model's claimed rationale,
    while code presence has its own deliverable check. A source citation on the
    same line is only provenance presence; normal claim-entailment gates still
    decide whether that source really supports the number. A sentence claiming
    calibration on N samples is untrusted prose, not an execution receipt. This
    check does not yet bind numeric rules to structured lab receipts; uncited
    purported measurements therefore stay unresolved.
    """
    text = str(answer or "")
    # Our deterministic first-paragraph banner must not shift diagnostic line
    # numbers every time ResearchResult is serialized again.
    if text.startswith("> ⚠️ **PARTIAL — TRADING ACCEPTANCE GAP:**"):
        text = text.partition("\n\n")[2]
    prose = _FENCED_CODE_RE.sub("", text)
    out: List[Dict[str, Any]] = []
    for line_no, raw in enumerate(prose.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if not _TRADING_THRESHOLD_TERM_RE.search(line) or not _RULE_NUMBER_RE.search(line):
            continue
        if _NON_RULE_RE.search(line):
            continue
        cited = bool(_SOURCE_CITATION_RE.search(line))
        if cited:
            continue
        out.append({
            "line_no": line_no,
            "excerpt": line[:240],
            "reason": "numeric trading decision threshold has no same-line source citation; a claimed sample count is not a verified receipt",
        })
        if len(out) >= 12:
            break
    return out


def _required_points(question: str) -> List[str]:
    ask = trademodel.ask_of(question)
    if not ask.asked:
        return []
    required = ["entry_model_exact", "final_spec_tradeable"]
    if len(ask.instruments) > 1:
        required.append("instrument_scope")
    if len(ask.chain) >= 2:
        required.append("execution_chain")
    if ask.concepts:
        required.extend(("concept_definitions", "no_authority_truth"))
    for demand in ask.demands:
        point = _DEMAND_TO_POINT.get(demand)
        if point:
            required.append(point)
    return _dedupe(required)


def _contract_partition_valid(contract: Dict[str, Any]) -> bool:
    """Public trade record must still account for every one of the 34 checks."""
    names = ("contract_points", "met_count", "not_met_count", "not_measured_count")
    if any(type(contract.get(name)) is not int for name in names):
        return False
    if any(not isinstance(contract.get(name), list) for name in ("not_met", "not_measured")):
        return False
    points, met_count, not_met_count, not_measured_count = (contract[name] for name in names)
    not_met = [str(v) for v in (contract.get("not_met") or [])]
    not_measured = [str(v) for v in (contract.get("not_measured") or [])]
    valid_ids = set(trademodel.CONTRACT_IDS)
    bad_ids = set(not_met) | set(not_measured)
    return bool(
        points == trademodel.CONTRACT_POINTS
        and met_count >= 0 and not_met_count >= 0 and not_measured_count >= 0
        and met_count + not_met_count + not_measured_count == points
        and len(not_met) == not_met_count
        and len(not_measured) == not_measured_count
        and len(set(not_met)) == not_met_count
        and len(set(not_measured)) == not_measured_count
        and not (set(not_met) & set(not_measured))
        and bad_ids <= valid_ids
    )


def audit(result: Dict[str, Any]) -> Dict[str, Any]:
    data = result if isinstance(result, dict) else {}
    question = str(data.get("question") or "")
    ask = trademodel.ask_of(question)
    if not ask.asked:
        return {
            "required": False,
            "complete": None,
            "required_contract_points": [],
            "missing_contract_points": [],
            "script_requested": False,
            "script_delivered": None,
            "unsupported_numeric_threshold_count": 0,
            "unsupported_numeric_thresholds": [],
            "note": "trading-model deliverable gate not required",
        }

    contract = data.get("trade_contract") if isinstance(data.get("trade_contract"), dict) else {}
    required = _required_points(question)
    not_met = set(str(v) for v in contract.get("not_met", [])) if isinstance(contract.get("not_met"), list) else set()
    not_measured = set(str(v) for v in contract.get("not_measured", [])) if isinstance(contract.get("not_measured"), list) else set()
    missing: List[str] = []
    lane_ran = bool(contract.get("ran") is True and contract.get("asked") is True)
    partition_valid = _contract_partition_valid(contract) if lane_ran else False
    if not lane_ran:
        missing.append("trade_contract_not_run")
    elif not partition_valid:
        missing.append("trade_contract_status_partition_invalid")
    else:
        for point in required:
            if point in not_met or point in not_measured:
                missing.append(point)

    answer = str(data.get("answer") or "")
    script_requested = _technical_script_requested(question)
    script_delivered = _technical_script_delivered(answer) if script_requested else None
    if script_requested and not script_delivered:
        missing.append("technical_backtest_script")

    unsupported = unsupported_numeric_thresholds(answer)
    if unsupported:
        missing.append("unsupported_numeric_trading_thresholds")

    return {
        "required": True,
        "complete": not missing,
        "required_contract_points": required,
        "missing_contract_points": _dedupe(missing),
        "script_requested": script_requested,
        "script_delivered": script_delivered,
        "trade_contract_ran": lane_ran,
        "trade_contract_partition_valid": partition_valid,
        "unsupported_numeric_threshold_count": len(unsupported),
        "unsupported_numeric_thresholds": unsupported,
        "profitability_proven": False,
        "live_tested": bool(contract.get("live_tested") is True),
        "note": (
            "delivery/provenance/measurement acceptance only; a MET contract point, "
            "citation presence, or code block is not proof of future profitability"
        ),
    }


def enforce(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    check = audit(data)
    coverage = dict(data.get("coverage") or {})
    coverage["trading_acceptance"] = check
    data["coverage"] = coverage
    if not check.get("required") or check.get("complete") is True:
        return data

    missing = _dedupe(check.get("missing_contract_points") or [])
    current = str(data.get("status") or _COMPLETE)
    if current == _COMPLETE:
        data["status"] = _PARTIAL

    existing = _dedupe(data.get("missing_sections") or [])
    human_missing = ["trading:" + item for item in missing]
    data["missing_sections"] = _dedupe(existing + human_missing)

    reason = "Trading request ke actual model/testing deliverables poore verify nahi hue: " + ", ".join(missing[:8])
    old_reason = str(data.get("status_reason") or "").strip()
    if current == _COMPLETE or not old_reason:
        data["status_reason"] = reason
    elif reason not in old_reason:
        data["status_reason"] = old_reason + " | " + reason

    warning = _MARKER + ": " + ", ".join(missing[:8])
    warnings = _dedupe(data.get("warnings") or [])
    if warning not in warnings:
        warnings.append(warning)
    data["warnings"] = warnings

    state = dict(data.get("research_state") or {})
    if str(state.get("answer_state") or "") == _COMPLETE:
        state["answer_state"] = _PARTIAL
    if state:
        conflicts = _dedupe(state.get("conflicts") or [])
        note = "Trading delivery incomplete: " + ", ".join(missing[:8])
        if note not in conflicts:
            conflicts.append(note)
        state["conflicts"] = conflicts
        data["research_state"] = state

    answer = str(data.get("answer") or "")
    if _MARKER not in answer:
        banner = (
            "> ⚠️ **PARTIAL — TRADING ACCEPTANCE GAP:** maanga hua trading model/testing "
            "deliverable poora nahi mila: " + ", ".join(missing[:8])
            + ". Isse tested/profitable model mat maano."
        )
        data["answer"] = banner + "\n\n" + answer
    return data


def install() -> None:
    """Install once; wrapper order stays monotonic with other result gates."""
    from . import models

    cls = models.ResearchResult
    if getattr(cls, "_trading_acceptance_guard_installed", False):
        return
    original = cls.to_dict

    def guarded_to_dict(self):
        return enforce(original(self))

    cls.to_dict = guarded_to_dict
    cls._trading_acceptance_guard_installed = True


install()
