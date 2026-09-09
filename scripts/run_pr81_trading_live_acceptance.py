"""Fixed, sanitized live acceptance for PR #81 trading repairs.

This is intentionally not a general prompt runner.  The question is hard-coded so
GitHub-hosted release validation cannot be turned into arbitrary model execution.
It exercises the public AgentManager/MAXIMUM path and emits only structural
booleans/counters plus an answer hash; prompts, answers, sources and credentials
never enter the receipt.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, Mapping


TRADING_LIVE_QUESTION = (
    "US100 aur XAUUSD ke liye research-only scalping trading model banao. "
    "Exact entry, exit, invalidation aur risk rules do. Python event-driven "
    "backtest script banao jo held-out/out-of-sample split, simple baseline, "
    "look-ahead/leakage guard, spread/commission/slippage aur performance metrics "
    "calculate kar sake. 3 testable hypotheses aur falsification criteria do. "
    "Har numeric trading threshold ko source-cited, user-supplied, LAB-measured "
    "ya clearly PROPOSED / UNVALIDATED label karo. Historical backtest actually "
    "execute na hua ho to result numbers mat banao; proposed test ko performed mat bolo."
)

_EXPECTED_TRADE_POINTS = {
    "entry_model_exact",
    "final_spec_tradeable",
    "baseline_tournament",
    "no_leakage",
    "realistic_costs",
    "walk_forward_validation",
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _company_record(result: Mapping[str, Any]) -> Mapping[str, Any]:
    for container in (
        result,
        _mapping(result.get("verification")),
        _mapping(result.get("coverage")),
    ):
        company = container.get("research_company")
        if isinstance(company, Mapping):
            return company
    return {}


def evaluate_trading_result(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Evaluate PR #81 invariants without treating missing empirical data as truth.

    A missing empirical/backtest measurement is acceptable only when the public
    result remains PARTIAL.  A missing requested Python script is not accepted:
    the live model must actually return the requested technical deliverable.
    """
    from research_engine import craft

    task = _mapping(result.get("task_contract"))
    trade = _mapping(task.get("trade_acceptance"))
    coverage = [row for row in (task.get("coverage") or []) if isinstance(row, Mapping)]
    coverage_by_id = {str(row.get("requirement_id") or ""): row for row in coverage}
    threshold = _mapping(trade.get("threshold_provenance"))
    if not threshold:
        threshold = _mapping(_mapping(result.get("trade_contract")).get("threshold_provenance"))

    gaps = [str(item) for item in (trade.get("gaps") or []) if isinstance(item, str)]
    status = str(result.get("status") or "").upper()
    task_assessment = str(task.get("assessment") or "").upper()
    required = {str(item) for item in (trade.get("required_contract_points") or [])}

    creative = craft.detect(TRADING_LIVE_QUESTION)
    script_row = _mapping(coverage_by_id.get("technical_script:python"))
    script_satisfied = script_row.get("assessment") == "SATISFIED"

    # Final acceptance must fail closed.  Missing empirical points are not a
    # software failure when the result honestly remains PARTIAL; false COMPLETE is.
    honest_gap_state = (not gaps) or (status == "PARTIAL" and task_assessment == "PARTIAL")
    no_false_complete = not (gaps and status == "COMPLETE")

    company = _company_record(result)
    chief = _mapping(company.get("chief_execution"))
    chief_done = {str(item) for item in (chief.get("done_passes") or [])}
    missing_passes = {str(item) for item in (result.get("missing_passes") or [])}
    prepared = company.get("handoff_prepared") is True
    truncated = bool(company.get("handoff_truncated_roles"))
    consumer = bool(chief_done & {"analysis", "synthesis"})
    handoff_should_count = prepared and not truncated and consumer
    handoff_semantics_ok = (
        (handoff_should_count and "specialist_handoff" not in missing_passes)
        or (not handoff_should_count and status != "COMPLETE")
    )

    workers = [row for row in (company.get("workers") or []) if isinstance(row, Mapping)]
    max_company_executed = (
        company.get("requested_workers") == 6
        and len(workers) == 6
        and sum(row.get("status") == "DRAFT_READY" for row in workers) == 6
    )

    threshold_ran = threshold.get("ran") is True
    unsupported = int(threshold.get("unsupported_count") or 0) if threshold else 0
    unsupported_fail_closed = unsupported == 0 or (
        threshold.get("acceptance_blocked") is True and status == "PARTIAL"
    )

    checks = [
        ("technical_script_not_creative", not bool(_mapping(creative).get("is_request"))),
        ("trade_acceptance_active", trade.get("active") is True),
        ("python_script_kind_detected", trade.get("script_kind") == "python"),
        ("python_script_delivered", script_satisfied),
        ("requested_trade_points_registered", _EXPECTED_TRADE_POINTS.issubset(required)),
        ("threshold_provenance_ran", threshold_ran),
        ("unsupported_thresholds_fail_closed", unsupported_fail_closed),
        ("missing_deliverables_fail_closed", honest_gap_state and no_false_complete),
        ("max_six_specialists_executed", max_company_executed),
        ("specialist_handoff_semantics", handoff_semantics_ok),
    ]
    rows = [{"name": name, "passed": bool(passed)} for name, passed in checks]
    answer = str(result.get("answer") or "")
    return {
        "passed": all(row["passed"] for row in rows),
        "checks": rows,
        "summary": {
            "depth_mode": "MAXIMUM",
            "status": status,
            "task_assessment": task_assessment,
            "trade_gap_count": len(gaps),
            "unsupported_threshold_count": unsupported,
            "requested_trade_point_count": len(required),
            "company_requested_workers": int(company.get("requested_workers") or 0),
            "company_ready_workers": sum(row.get("status") == "DRAFT_READY" for row in workers),
            "handoff_prepared": prepared,
            "handoff_truncated": truncated,
            "handoff_consumer_observed": consumer,
            "specialist_handoff_missing": "specialist_handoff" in missing_passes,
            "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
        },
        "contains_answer_or_source_text": False,
        "contains_credentials": False,
    }


def run_trading_live() -> Dict[str, Any]:
    """Run the fixed question through the same public manager used by the app."""
    from research_engine.agent_manager import AgentManager

    job = uuid.uuid4().hex
    project = "pr81_trading_live_" + job
    manager = AgentManager()
    try:
        result = manager.research(
            TRADING_LIVE_QUESTION,
            project_id=project,
            depth_mode="MAXIMUM",
            job_id=job,
        )
        return evaluate_trading_result(result)
    finally:
        manager.drop(project)
