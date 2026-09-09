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


def _strings(value: Any):
    return value if isinstance(value, list) and all(type(v) is str for v in value) else []


def _positive(row: Mapping[str, Any], key: str) -> bool:
    value = _mapping(row.get("accounting")).get(key)
    return type(value) is int and value > 0


def _safe_status(value: Any) -> str:
    # Status fields are not allowed to smuggle answer/credential text into CI.
    return value if type(value) is str and value in {
        "COMPLETE", "PARTIAL", "BLOCKED", "FAILED", "INCONCLUSIVE", "NOT_RUN"
    } else "UNKNOWN"


def evaluate_trading_result(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Verify execution and fail-closed behavior, not scientific/market quality.

    Recompute the integrated final trading audit over the fixed question and
    actual answer. A claimed SATISFIED flag is not a delivered Python script.
    Missing empirical work is acceptable only as an explicit PARTIAL result.
    """
    from research_engine import craft
    from research_engine.trading_acceptance_guard import audit

    result = _mapping(result)
    answer = result.get("answer") if type(result.get("answer")) is str else ""
    assessed = audit(dict(result, question=TRADING_LIVE_QUESTION, answer=answer))
    recorded = _mapping(_mapping(result.get("coverage")).get("trading_acceptance"))
    fields = (
        "required", "complete", "required_contract_points", "missing_contract_points",
        "script_requested", "script_kinds", "script_delivered", "trade_contract_ran",
        "trade_contract_partition_valid", "unsupported_numeric_threshold_count",
    )
    audit_matches = all(key in recorded and type(recorded[key]) is type(assessed[key])
                        and recorded[key] == assessed[key] for key in fields)
    gaps = assessed["missing_contract_points"]
    required = set(assessed["required_contract_points"])
    unsupported = assessed["unsupported_numeric_threshold_count"]
    status = _safe_status(result.get("status"))
    task = _mapping(result.get("task_contract"))
    task_status = _safe_status(task.get("assessment"))
    missing_passes = _strings(result.get("missing_passes"))
    missing_sections = _strings(result.get("missing_sections"))
    gaps_declared = all("trading:" + gap in missing_sections for gap in gaps)
    public_gaps = bool(gaps or missing_passes or missing_sections or task_status == "PARTIAL")
    honest_gaps = status in {"COMPLETE", "PARTIAL"} and (
        not public_gaps or status == "PARTIAL"
    ) and (not gaps or gaps_declared)

    company = _company_record(result)
    chief = _mapping(company.get("chief_execution"))
    chief_done = set(_strings(chief.get("done_passes")))
    truncated_roles = company.get("handoff_truncated_roles")
    truncation_known = isinstance(truncated_roles, list)
    prepared = company.get("handoff_prepared") is True
    truncated = bool(truncated_roles) or not truncation_known
    consumer = bool(chief_done & {"analysis", "synthesis"}) and _positive(chief, "successful_calls")
    consumed = prepared and not truncated and consumer
    handoff_ok = (
        consumed and "specialist_handoff" not in missing_passes
    ) or (
        not consumed and status == "PARTIAL" and "specialist_handoff" in missing_passes
    )

    workers_raw = company.get("workers")
    workers = workers_raw if isinstance(workers_raw, list) else []
    roles = {"evidence", "validation", "mechanism", "red_team", "data_quality", "implementation"}
    shape_ok = len(workers) == 6 and all(isinstance(w, Mapping) for w in workers)
    ready_workers = [w for w in workers if isinstance(w, Mapping) and w.get("status") == "DRAFT_READY"]
    role_ids = [w.get("role") for w in ready_workers]
    worker_ids = [w.get("worker_id") for w in ready_workers]
    identity_ok = (
        all(type(v) is str and v for v in role_ids + worker_ids)
        and set(role_ids) == roles and len(set(worker_ids)) == 6
    ) if len(ready_workers) == 6 else False
    workers_ok = (
        type(company.get("requested_workers")) is int and company["requested_workers"] == 6
        and type(company.get("completed_workers")) is int and company["completed_workers"] == 6
        and shape_ok and identity_ok
        and all(_positive(w, "actual_http_attempts") and _positive(w, "successful_calls")
                and w.get("accounting_complete") is True
                and w.get("provider_output_capture_complete") is True for w in ready_workers)
        and company.get("accounting_complete") is True
    )
    runtime = _mapping(result.get("runtime_execution"))
    attempts = runtime.get("reserved_http_attempts")
    runtime_ok = (
        runtime.get("available") is True and runtime.get("event_durability") == "SQLITE_TRANSACTION"
        and runtime.get("cancelled") is False and type(attempts) is int and attempts >= 7
    )
    # One successful chief synthesis is required. Analysis may have failed only
    # if public PARTIAL/missing-pass accounting preserves that failed work.
    chief_ok = (
        "synthesis" in chief_done and _positive(chief, "successful_calls")
        and _positive(chief, "actual_http_attempts")
        and ("analysis" in chief_done or (status == "PARTIAL" and "analysis" in missing_passes))
    )
    checks = [
        ("fixed_question_executed", result.get("question") == TRADING_LIVE_QUESTION),
        ("technical_script_not_creative", not bool(_mapping(craft.detect(TRADING_LIVE_QUESTION)).get("is_request"))),
        ("trade_acceptance_active", assessed["required"] is True and audit_matches),
        ("python_script_kind_detected", "python" in assessed["script_kinds"]),
        ("python_script_delivered", assessed["script_delivered"] is True),
        ("requested_trade_points_registered", _EXPECTED_TRADE_POINTS.issubset(required)),
        ("trade_contract_partition_valid", assessed["trade_contract_partition_valid"] is True),
        ("threshold_provenance_ran", audit_matches),
        ("unsupported_thresholds_fail_closed", unsupported == 0 or (status == "PARTIAL" and gaps_declared)),
        ("missing_deliverables_fail_closed", honest_gaps),
        ("max_six_specialists_executed", workers_ok),
        ("public_runtime_executed", runtime_ok),
        ("chief_execution_observed", chief_ok),
        ("specialist_handoff_semantics", handoff_ok),
        ("no_false_scientific_replication", company.get("independent_scientific_replication") is False
         and company.get("experiments_performed_by_workers") is False),
    ]
    rows = [{"name": name, "passed": bool(passed)} for name, passed in checks]
    return {
        "schema": 2,
        "passed": all(row["passed"] for row in rows),
        "checks": rows,
        "summary": {
            "depth_mode": "MAXIMUM", "status": status, "task_assessment": task_status,
            "trade_gap_count": len(gaps), "unsupported_threshold_count": unsupported,
            "requested_trade_point_count": len(required),
            "company_requested_workers": 6 if company.get("requested_workers") == 6 else 0,
            "company_ready_workers": len(ready_workers),
            "handoff_prepared": prepared, "handoff_truncated": truncated,
            "handoff_consumer_observed": consumer,
            "specialist_handoff_missing": "specialist_handoff" in missing_passes,
            "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
        },
        "backtest_execution_verified": False,
        "independent_quality_verified": False,
        "contains_answer_or_source_text": False, "contains_credentials": False,
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
