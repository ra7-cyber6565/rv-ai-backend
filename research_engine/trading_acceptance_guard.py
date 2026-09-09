"""Final acceptance boundary for technical trading-model requests.

The existing :mod:`trademodel` contract measures the requested trading work but
historically remained diagnostic: a run could still be labelled COMPLETE while
an explicitly requested model/test/script was missing.  This module connects
that already-measured contract to the public task contract without inventing a
result or weakening any research gate.

It also records provenance for actionable numeric trading thresholds.  A number
is not treated as measured merely because a model wrote it.  User-supplied
constraints, same-line source citations, and actual LAB-marked measurements are
traceable; explicitly proposed/unvalidated values stay provisional.  An
unlabelled, untraceable actionable threshold blocks final trading acceptance.
"""
from __future__ import annotations

import re
from functools import wraps
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set


_DEMAND_TO_POINTS = {
    "walk_forward": ("walk_forward_validation",),
    "monte_carlo": ("monte_carlo_risk",),
    "robustness": ("parameter_robustness",),
    "baseline": ("baseline_tournament",),
    "leakage": ("no_leakage",),
    "costs": ("realistic_costs",),
    "out_of_sample": ("walk_forward_validation",),
    "red_team": ("red_team",),
    "regime": ("regime_detection",),
    "session": ("session_expectancy",),
    "macro_events": ("macro_event_windows",),
    "intermarket": ("intermarket_tests",),
    "information_theory": ("information_theory",),
    "game_theory": ("game_theory",),
    # Asking for microstructure does not manufacture L2/order-book access.  The
    # evidence-backed theory point is the enforceable requirement; the separate
    # order-flow edge remains structurally blocked unless real data exists.
    "microstructure": ("theory_base",),
    "risk_sizing": ("final_spec_tradeable",),
}

_FULL_MODEL_RE = re.compile(
    r"\b(?:trading\s+model|entry\s+model|model|strategy|system|setup|playbook|"
    r"framework|final\s+spec|trade\s+spec)\b",
    re.IGNORECASE,
)
_STOP_REQUEST_RE = re.compile(r"\b(?:stop[- ]?loss|\bsl\b|stop placement|mae)\b", re.I)
_TARGET_REQUEST_RE = re.compile(
    r"\b(?:take[- ]?profit|\btp\b|target|risk[- ]?reward|\brr\b)\b", re.I)
_BACKTEST_EXECUTION_RE = re.compile(
    r"(?:\bback[- ]?test(?:ing)?\b.{0,24}\b(?:karo|karna|run|execute|perform|"
    r"chalao|chalaana|test)\b|\b(?:run|execute|perform|chalao)\b.{0,16}"
    r"\bback[- ]?test\b)",
    re.IGNORECASE,
)
_PYTHON_REQUEST_RE = re.compile(
    r"\bpython\b.{0,40}\b(?:script|code|back[- ]?test)\b|"
    r"\b(?:script|code|back[- ]?test)\b.{0,40}\bpython\b",
    re.IGNORECASE,
)
_PINE_REQUEST_RE = re.compile(r"\bpine\s*script\b|\bpinescript\b", re.I)
_GENERIC_SCRIPT_RE = re.compile(
    r"\b(?:back[- ]?test|trading|strategy)\b.{0,30}\bscript\b|"
    r"\bscript\b.{0,30}\b(?:back[- ]?test|trading|strategy)\b",
    re.IGNORECASE,
)

# Numeric thresholds are scanned only on actionable trading-rule lines.  This
# deliberately ignores ordinary dates/source counts/statistics in the report.
_ACTIONABLE_LINE_RE = re.compile(
    r"\b(?:entry|trigger|long\s+if|short\s+if|buy\s+if|sell\s+if|stop[- ]?loss|"
    r"\bsl\b|take[- ]?profit|\btp\b|target|risk\s+per\s+trade|position\s+size|"
    r"threshold|rsi|atr|ema|sma|vwap|fvg|order\s+block|liquidity|breakout|"
    r"close\s+(?:above|below)|no[- ]?trade|invalidation|risk[- ]?reward|\brr\b)\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(
    r"(?P<cmp>>=|<=|>|<|=)?\s*(?P<num>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>%|R\b|ATR\b|x\b)?",
    re.IGNORECASE,
)
_TIMEFRAME_AFTER_RE = re.compile(r"^\s*(?:m|min|mins|minute|minutes|h|hr|hour|hours|d|day|days|w|week|weeks)\b", re.I)
_CITATION_RE = re.compile(r"\[S\d+\]", re.I)
_PROVISIONAL_RE = re.compile(
    r"\b(?:propos(?:ed|al)|candidate|illustrative|example|hypothesis|"
    r"not\s+validated|unvalidated|to\s+be\s+(?:tested|tuned)|parameter\s+sweep|"
    r"assumption|placeholder|research\s+only)\b|\[EVIDENCE-D\]|\[UNVERIFIED\]",
    re.IGNORECASE,
)
_LAB_MARKER_RE = re.compile(r"\bLAB\b|\[LAB[^\]]*\]|\b(?:naapa gaya|measured by lab)\b", re.I)


def _threshold_signatures(text: str) -> Set[str]:
    """Return literal-ish numeric rule signatures, excluding timeframes/citations."""
    out: Set[str] = set()
    for raw in str(text or "").splitlines() or [str(text or "")]:
        if not _ACTIONABLE_LINE_RE.search(raw):
            continue
        line = _CITATION_RE.sub("", raw)
        for hit in _NUMBER_RE.finditer(line):
            tail = line[hit.end():hit.end() + 12]
            if not hit.group("unit") and _TIMEFRAME_AFTER_RE.match(tail):
                continue
            cmp_ = hit.group("cmp") or ""
            num = hit.group("num")
            unit = (hit.group("unit") or "").lower()
            # A naked integer without comparator/unit is too ambiguous unless
            # the same line names a numerical indicator/risk concept.
            if not cmp_ and not unit and not re.search(
                r"\b(?:rsi|atr|risk|rr|ratio|threshold|ema|sma|vwap)\b", line, re.I
            ):
                continue
            out.add(f"{cmp_}{num}{unit}")
    # Common user constraint "1:2 RR" semantically supplies a 2R target.
    for hit in re.finditer(r"\b\d+(?:\.\d+)?\s*:\s*(\d+(?:\.\d+)?)\b", str(text or "")):
        out.add(f"{hit.group(1)}r")
    return out


def audit_thresholds(question: str, spec: Any, *, lab_report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Classify actionable numeric thresholds without asserting they are true."""
    user_signatures = _threshold_signatures(question)
    rows: List[Dict[str, Any]] = []
    counts = {"user_supplied": 0, "source_cited": 0, "lab_measured": 0,
              "provisional": 0, "unsupported": 0}

    for line_no, raw in enumerate(str(spec or "").splitlines(), start=1):
        if not _ACTIONABLE_LINE_RE.search(raw):
            continue
        cited = bool(_CITATION_RE.search(raw))
        provisional = bool(_PROVISIONAL_RE.search(raw))
        lab_marked = bool(_LAB_MARKER_RE.search(raw)) and bool(lab_report)
        clean = _CITATION_RE.sub("", raw)
        for hit in _NUMBER_RE.finditer(clean):
            tail = clean[hit.end():hit.end() + 12]
            if not hit.group("unit") and _TIMEFRAME_AFTER_RE.match(tail):
                continue
            cmp_ = hit.group("cmp") or ""
            num = hit.group("num")
            unit = (hit.group("unit") or "").lower()
            if not cmp_ and not unit and not re.search(
                r"\b(?:rsi|atr|risk|rr|ratio|threshold|ema|sma|vwap)\b", clean, re.I
            ):
                continue
            signature = f"{cmp_}{num}{unit}"
            if signature in user_signatures:
                provenance = "user_supplied"
            elif lab_marked:
                provenance = "lab_measured"
            elif cited:
                provenance = "source_cited"
            elif provisional:
                provenance = "provisional"
            else:
                provenance = "unsupported"
            counts[provenance] += 1
            if len(rows) < 24:
                rows.append({
                    "line_no": line_no,
                    "expression": signature,
                    "provenance": provenance,
                    "line": raw.strip()[:240],
                })

    total = sum(counts.values())
    unsupported = counts["unsupported"]
    return {
        "ran": True,
        "actionable_numeric_thresholds": total,
        **{f"{key}_count": value for key, value in counts.items()},
        "acceptance_blocked": unsupported > 0,
        "rows": rows,
        "truth_proven": False,
        "note": (
            f"{unsupported}/{total} actionable numeric threshold ka traceable "
            "source/user/LAB/provisional label nahi mila."
            if unsupported else
            f"{total} actionable numeric threshold mile; koi unlabelled/untraceable "
            "threshold nahi mila. Provenance validation ka substitute nahi hai."
        ),
    }


def _required_trade_points(question: str, ask: Any) -> List[str]:
    required: List[str] = []
    if _FULL_MODEL_RE.search(question):
        required.extend(("entry_model_exact", "final_spec_tradeable"))
    elif getattr(ask, "concepts", ()):
        required.append("concept_definitions")

    if len(getattr(ask, "instruments", ()) or ()) > 1:
        required.append("instrument_scope")
    if len(getattr(ask, "chain", ()) or ()) == 3:
        required.append("execution_chain")
    if getattr(ask, "concepts", ()):
        required.extend(("concept_definitions", "no_authority_truth"))
    if _STOP_REQUEST_RE.search(question):
        required.append("stop_loss_research")
    if _TARGET_REQUEST_RE.search(question):
        required.append("take_profit_research")
    if _BACKTEST_EXECUTION_RE.search(question):
        required.append("performance_metrics")
    for demand in getattr(ask, "demands", ()) or ():
        required.extend(_DEMAND_TO_POINTS.get(str(demand), ()))
    return list(dict.fromkeys(required))


def _script_kind(question: str) -> str:
    if _PINE_REQUEST_RE.search(question):
        return "pine"
    if _PYTHON_REQUEST_RE.search(question):
        return "python"
    if _GENERIC_SCRIPT_RE.search(question):
        return "code"
    return ""


def _script_present(answer: str, kind: str) -> bool:
    text = str(answer or "")
    if kind == "pine":
        return bool(re.search(r"//@version\s*=|```\s*(?:pine|pinescript)\b", text, re.I))
    if kind == "python":
        return bool(re.search(r"```\s*(?:python|py)\b", text, re.I))
    if kind == "code":
        return bool(re.search(r"```\s*[A-Za-z0-9_+.-]*\s*\n", text))
    return True


def install() -> None:
    """Install threshold provenance + task completion downgrade once."""
    from . import trademodel
    from . import task_contract

    prior_study = trademodel.study
    if not getattr(prior_study, "__threshold_provenance_guard__", False):
        @wraps(prior_study)
        def guarded_study(question: str = "", spec: Any = "",
                          sources: Iterable[Any] = (),
                          hypotheses: Sequence[Any] = (),
                          lab_report: Optional[Dict[str, Any]] = None):
            report = prior_study(question, spec, sources, hypotheses, lab_report)
            if isinstance(report, dict) and report.get("asked") and report.get("ran"):
                report["threshold_provenance"] = audit_thresholds(
                    question, spec, lab_report=lab_report)
            return report

        guarded_study.__threshold_provenance_guard__ = True
        trademodel.study = guarded_study

    prior_public = trademodel.public_record
    if not getattr(prior_public, "__threshold_provenance_guard__", False):
        @wraps(prior_public)
        def guarded_public_record(report: Optional[Dict[str, Any]] = None):
            out = prior_public(report)
            if isinstance(out, dict) and isinstance(report, dict):
                threshold = report.get("threshold_provenance")
                if isinstance(threshold, dict):
                    out["threshold_provenance"] = threshold
            return out

        guarded_public_record.__threshold_provenance_guard__ = True
        trademodel.public_record = guarded_public_record

    prior_assess = task_contract.assess_contract
    if getattr(prior_assess, "__trading_acceptance_guard__", False):
        return

    @wraps(prior_assess)
    def guarded_assess_contract(contract: Dict[str, Any], result: Dict[str, Any]):
        assessed = prior_assess(contract, result)
        question = str(contract.get("objective") or "")
        if not trademodel.is_request(question):
            return assessed

        report = result.get("trade_contract") or {}
        ask = trademodel.ask_of(question)
        required = _required_trade_points(question, ask)
        gaps: List[str] = []
        coverage_rows: List[Dict[str, Any]] = []

        if not isinstance(report, dict) or not report.get("ran") or not report.get("asked"):
            gaps.append("trade_contract_not_executed")
            for point in required:
                coverage_rows.append({"requirement_id": f"trade:{point}",
                                      "assessment": "NOT_ASSESSED",
                                      "output_reference": "trade_contract"})
        else:
            bad = set(report.get("not_met") or ()) | set(report.get("not_measured") or ())
            for point in required:
                status = "MISSING" if point in bad else "SATISFIED"
                coverage_rows.append({"requirement_id": f"trade:{point}",
                                      "assessment": status,
                                      "output_reference": "trade_contract"})
                if point in bad:
                    gaps.append(point)

        script_kind = _script_kind(question)
        if script_kind:
            present = _script_present(str(result.get("answer") or ""), script_kind)
            coverage_rows.append({"requirement_id": f"technical_script:{script_kind}",
                                  "assessment": "SATISFIED" if present else "MISSING",
                                  "output_reference": "answer"})
            if not present:
                gaps.append(f"technical_script_{script_kind}")

        threshold = report.get("threshold_provenance") if isinstance(report, dict) else None
        if isinstance(threshold, dict):
            blocked = bool(threshold.get("acceptance_blocked"))
            coverage_rows.append({
                "requirement_id": "trade:threshold_provenance",
                "assessment": "MISSING" if blocked else "SATISFIED",
                "output_reference": "trade_contract.threshold_provenance",
            })
            if blocked:
                gaps.append("unsupported_numeric_thresholds")
        elif isinstance(report, dict) and report.get("ran"):
            coverage_rows.append({
                "requirement_id": "trade:threshold_provenance",
                "assessment": "NOT_ASSESSED",
                "output_reference": "trade_contract",
            })
            gaps.append("threshold_provenance_not_assessed")

        gaps = list(dict.fromkeys(gaps))
        assessed["coverage"] = list(assessed.get("coverage") or []) + coverage_rows
        assessed["trade_acceptance"] = {
            "active": True,
            "required_contract_points": required,
            "script_kind": script_kind or None,
            "gaps": gaps,
            "passed": not gaps,
            "complete_means_profitability": False,
            "threshold_provenance": threshold if isinstance(threshold, dict) else {},
        }
        if gaps:
            existing = list(assessed.get("known_missing_deliverables") or [])
            assessed["known_missing_deliverables"] = list(dict.fromkeys(
                existing + [f"trade:{gap}" for gap in gaps]
            ))
            assessed["assessment"] = "PARTIAL"
        return assessed

    guarded_assess_contract.__trading_acceptance_guard__ = True
    task_contract.assess_contract = guarded_assess_contract


install()
