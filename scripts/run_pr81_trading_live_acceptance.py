#!/usr/bin/env python3
"""Fixed hard Max trading acceptance for PR #81.

This is an acceptance *measurement*, not a trading-performance claim. It runs a
single fixed US100/XAUUSD request through the same public AgentManager used by
the API, then emits only structural booleans/counters and an answer hash. No
answer text, source text/URLs, prompt, credentials or provider error bodies are
written to the receipt.

The gate intentionally fails closed. It requires the unified MAXIMUM path to
actually activate all six specialists, complete the bounded chief handoff,
produce three structured/testable hypotheses, execute the requested isolated
implementation build, and satisfy the measured trading contract including the
lab-backed validation rows. A PARTIAL result is a failed release acceptance,
not a reason to manufacture COMPLETE.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
from typing import Any, Dict, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.release_identity import repository_identity


TRADING_MAX_QUESTION = (
    "MAX mode me 6 specialist AI aur chief ke saath US100 aur XAUUSD ke liye "
    "ek falsifiable intraday/scalping trading model banao. Python event-driven "
    "backtest implementation do aur isolated executor me us implementation ko "
    "run/validate karo. Kam se kam 3 competing testable hypotheses do; har "
    "hypothesis me dataset/sample, baseline/control, measured variables, "
    "parameter range, predeclared statistical metric, success aur failure "
    "threshold, falsification condition, measurement precision, independent "
    "replication plan aur cost/safety boundary saaf ho. Entry, stop, target, "
    "position-size, spread/slippage aur filters ke kisi numeric threshold ko "
    "sirf SOURCE-REPORTED, user-specified, ya PROVISIONAL TEST PARAMETER ke roop "
    "me label karo; unsupported magic number mat banao. Point-in-time/no-leakage "
    "rules, realistic costs, walk-forward out-of-sample validation, Monte Carlo, "
    "parameter robustness, simple baseline tournament, failure classification "
    "aur red-team include karo. Fake live trade, fake broker connection, fake "
    "backtest result, invented win-rate/profitability ya future-profit guarantee "
    "bilkul mat dena; required data/test execute na ho to result PARTIAL rakho."
)

EXPECTED_ROLES = {
    "evidence", "validation", "mechanism", "red_team", "data_quality", "implementation"
}
CRITICAL_TRADE_POINTS = {
    "instrument_scope",
    "execution_chain",
    "no_leakage",
    "realistic_costs",
    "walk_forward_validation",
    "monte_carlo_risk",
    "parameter_robustness",
    "baseline_tournament",
    "failure_classification",
    "red_team",
    "entry_model_exact",
    "stop_loss_research",
    "take_profit_research",
    "final_spec_tradeable",
    "performance_metrics",
    "honest_final_decision",
}
REQUIRED_EXPERIMENT_SPEC = {
    "dataset_or_sample",
    "control_or_baseline",
    "measured_variables",
    "parameter_range",
    "statistical_metric",
    "success_threshold",
    "failure_threshold",
    "falsification_condition",
    "measurement_precision",
    "replication_plan",
    "cost_and_safety",
}


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _safe_check(name: str, passed: bool, detail: str) -> Dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": str(detail)[:240]}


def _experiment_complete(row: Mapping[str, Any]) -> tuple[bool, int]:
    spec = row.get("experiment_spec")
    if not isinstance(spec, Mapping):
        return False, len(REQUIRED_EXPERIMENT_SPEC)
    missing = []
    for key in REQUIRED_EXPERIMENT_SPEC:
        value = spec.get(key)
        if isinstance(value, list):
            present = bool([item for item in value if str(item or "").strip()])
        else:
            present = bool(str(value or "").strip())
        if not present:
            missing.append(key)
    declared_missing = row.get("experiment_spec_missing")
    if isinstance(declared_missing, list):
        missing.extend(
            str(item) for item in declared_missing
            if item in REQUIRED_EXPERIMENT_SPEC
        )
    return not missing, len(set(missing))


def _looks_like_isolated_build_receipt(row: Mapping[str, Any]) -> bool:
    """Identify the server-owned Docker receipt without relying on answer text.

    `tool_registry.execute_tool()` returns a generic record containing
    `tool=isolated_build` for ordinary tools, but the isolated-build branch
    returns `DockerExecutor.run()` directly. That record is structurally unique:
    it contains a python/node runtime plus executor/isolation metadata. Accept
    either representation so the gate measures the real execution boundary.
    """
    if str(row.get("tool") or "") == "isolated_build":
        return True
    return (
        str(row.get("runtime") or "") in {"python", "node"}
        and isinstance(row.get("executor"), Mapping)
        and "automatic_deploy_allowed" in row
        and row.get("physical_experiment") is False
    )


def _implementation_execution(company: Mapping[str, Any]) -> Dict[str, Any]:
    workers = [
        row for row in (company.get("workers") or [])
        if isinstance(row, Mapping)
    ]
    implementation = next(
        (row for row in workers if row.get("role") == "implementation"), None
    )
    if not isinstance(implementation, Mapping):
        return {"present": False, "executed": False, "executed_receipts": 0}
    report = implementation.get("report")
    tools = report.get("tool_results") if isinstance(report, Mapping) else []
    receipts = [row for row in (tools or []) if isinstance(row, Mapping)]
    executed = [
        row for row in receipts
        if row.get("state") == "EXECUTED" and _looks_like_isolated_build_receipt(row)
    ]
    return {
        "present": True,
        "executed": bool(executed),
        "executed_receipts": len(executed),
    }


def evaluate_result(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Evaluate only machine-readable evidence; never answer keyword overlap."""
    coverage = result.get("coverage") or {}
    contract = result.get("task_contract") or {}
    verification = result.get("verification") or {}
    company = verification.get("research_company") or {}
    trade = result.get("trade_contract") or {}
    threshold = contract.get("trading_numeric_threshold_provenance") or {}
    hypotheses = [
        row for row in (result.get("hypotheses") or [])
        if isinstance(row, Mapping)
    ]

    workers = [
        row for row in (company.get("workers") or [])
        if isinstance(row, Mapping)
    ]
    roles = {str(row.get("role") or "") for row in workers if row.get("role")}
    ready_workers = [row for row in workers if row.get("status") == "DRAFT_READY"]
    worker_ids = {
        str(row.get("worker_id") or "") for row in workers
        if row.get("worker_id")
    }
    chief = company.get("chief_execution") or {}
    chief_accounting = chief.get("accounting") or {}
    handoff_roles = {
        str(value) for value in (company.get("handoff_worker_roles") or [])
        if value
    }
    implementation = _implementation_execution(company)

    hypothesis_complete = []
    hypothesis_missing_counts = []
    for row in hypotheses[:3]:
        complete, missing_count = _experiment_complete(row)
        hypothesis_complete.append(
            bool(
                row.get("is_testable") is True
                and row.get("has_prediction") is True
                and complete
            )
        )
        hypothesis_missing_counts.append(missing_count)

    not_met = set(str(value) for value in (trade.get("not_met") or []))
    not_measured = set(str(value) for value in (trade.get("not_measured") or []))
    critical_trade_gaps = sorted(
        CRITICAL_TRADE_POINTS & (not_met | not_measured)
    )

    task_types = {str(value) for value in (contract.get("task_types") or [])}
    checks = [
        _safe_check(
            "status_complete",
            result.get("status") == "COMPLETE",
            str(result.get("status") or "missing"),
        ),
        _safe_check(
            "maximum_mode_executed",
            str(coverage.get("mode") or "").upper() == "MAXIMUM",
            "public result reports MAXIMUM mode",
        ),
        _safe_check(
            "coding_not_creative",
            "coding" in task_types and "creative" not in task_types,
            "task contract classifies technical implementation without CRAFT",
        ),
        _safe_check(
            "six_workers_requested",
            contract.get("explicit_min_workers") == 6,
            "fixed acceptance requires six specialist workers",
        ),
        _safe_check(
            "task_contract_complete",
            contract.get("assessment") != "PARTIAL"
            and contract.get("worker_requirement_gap") is False,
            f"known_missing={len(contract.get('known_missing_deliverables') or [])}",
        ),
        _safe_check(
            "threshold_provenance",
            threshold.get("active") is True
            and threshold.get("passed") is True
            and int(threshold.get("unsupported_rule_lines") or 0) == 0,
            f"checked={int(threshold.get('checked_rule_lines') or 0)}, "
            f"unsupported={int(threshold.get('unsupported_rule_lines') or 0)}",
        ),
        _safe_check(
            "trade_contract_ran",
            trade.get("asked") is True and trade.get("ran") is True,
            f"met={int(trade.get('met_count') or 0)}/"
            f"{int(trade.get('contract_points') or 0)}",
        ),
        _safe_check(
            "critical_trade_contract",
            not critical_trade_gaps,
            f"critical_gaps={len(critical_trade_gaps)}",
        ),
        _safe_check(
            "no_chased_win_rate",
            not (trade.get("chased_win_rate") or []),
            "no 90%+ claimed win-rate accepted",
        ),
        _safe_check(
            "trading_reality_boundaries",
            trade.get("live_tested") is False
            and trade.get("broker_connected") is False
            and trade.get("financial_advice") is False,
            "no fake live/broker/advice state",
        ),
        _safe_check(
            "three_structured_hypotheses",
            len(hypotheses) >= 3
            and len(hypothesis_complete) == 3
            and all(hypothesis_complete),
            f"hypotheses={len(hypotheses)}, "
            f"first3_missing_spec_fields={hypothesis_missing_counts}",
        ),
        _safe_check(
            "six_specialists_executed",
            len(workers) == len(ready_workers) == 6
            and roles == EXPECTED_ROLES
            and len(worker_ids) == 6
            and all(
                _positive_int((row.get("accounting") or {}).get("actual_http_attempts"))
                and _positive_int((row.get("accounting") or {}).get("successful_calls"))
                for row in workers
            ),
            f"ready={len(ready_workers)}/6, roles={len(roles)}/6",
        ),
        _safe_check(
            "specialist_handoff_complete",
            company.get("handoff_prepared") is True
            and company.get("handoff_structured_compaction") is True
            and not (company.get("handoff_truncated_roles") or [])
            and handoff_roles == EXPECTED_ROLES,
            f"handoff_roles={len(handoff_roles)}/6, "
            f"truncated={len(company.get('handoff_truncated_roles') or [])}",
        ),
        _safe_check(
            "company_accounting_complete",
            company.get("accounting_complete") is True
            and all(row.get("accounting_complete") is True for row in workers),
            "worker usage receipts are complete",
        ),
        _safe_check(
            "chief_executed",
            {"analysis", "synthesis"}.issubset(
                set(chief.get("done_passes") or [])
            )
            and _positive_int(chief_accounting.get("successful_calls")),
            "chief analysis+synthesis have execution receipts",
        ),
        _safe_check(
            "implementation_build_executed",
            implementation["executed"] is True,
            f"isolated_build_receipts={implementation['executed_receipts']}",
        ),
        _safe_check(
            "no_false_replication",
            company.get("independent_scientific_replication") is False
            and company.get("experiments_performed_by_workers") is False,
            "specialists are reasoning roles, not fake scientific replication",
        ),
    ]

    answer = str(result.get("answer") or "")
    return {
        "passed": all(row["passed"] for row in checks),
        "checks": checks,
        "summary": {
            "status": str(result.get("status") or ""),
            "mode": str(coverage.get("mode") or ""),
            "task_contract_assessment": str(contract.get("assessment") or ""),
            "known_missing_deliverables": len(
                contract.get("known_missing_deliverables") or []
            ),
            "threshold_rule_lines_checked": int(
                threshold.get("checked_rule_lines") or 0
            ),
            "threshold_rule_lines_unsupported": int(
                threshold.get("unsupported_rule_lines") or 0
            ),
            "trade_contract_points": int(trade.get("contract_points") or 0),
            "trade_met": int(trade.get("met_count") or 0),
            "trade_not_met": int(trade.get("not_met_count") or 0),
            "trade_not_measured": int(trade.get("not_measured_count") or 0),
            "critical_trade_gaps": critical_trade_gaps,
            "hypotheses": len(hypotheses),
            "first_three_experiment_missing_counts": hypothesis_missing_counts,
            "company_workers": len(workers),
            "company_ready_workers": len(ready_workers),
            "handoff_compacted_roles": len(
                company.get("handoff_compacted_roles") or []
            ),
            "handoff_truncated_roles": len(
                company.get("handoff_truncated_roles") or []
            ),
            "isolated_build_receipts": implementation["executed_receipts"],
            "answer_sha256": hashlib.sha256(
                answer.encode("utf-8")
            ).hexdigest(),
        },
        "contains_answer_or_source_text": False,
        "contains_question_text": False,
        "contains_credentials": False,
        "performance_or_profitability_proven": False,
    }


def run_live() -> Dict[str, Any]:
    """Run the fixed question through the public manager path once."""
    from research_engine.agent_manager import AgentManager

    job = uuid.uuid4().hex
    project = "pr81_trading_live_" + job
    manager = AgentManager()
    try:
        return manager.research(
            TRADING_MAX_QUESTION,
            project_id=project,
            depth_mode="MAXIMUM",
            job_id=job,
        )
    finally:
        manager.drop(project)


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def execute(receipt_path: Path | None = None) -> Dict[str, Any]:
    started = time.time()
    identity = repository_identity(ROOT)
    public: Dict[str, Any] = {
        "schema_version": 1,
        "created_at_epoch": int(started),
        "code_revision": str(identity.get("revision") or ""),
        "repository_clean": identity.get("clean") is True,
        "passed": False,
        "contains_answer_or_source_text": False,
        "contains_question_text": False,
        "contains_credentials": False,
        "performance_or_profitability_proven": False,
    }
    try:
        if not identity.get("available") or identity.get("clean") is not True:
            raise RuntimeError("clean_committed_checkout_required")
        result = run_live()
        public.update(evaluate_result(result))
        public["duration_seconds"] = round(time.time() - started, 2)
    except Exception:
        public.update(
            duration_seconds=round(time.time() - started, 2),
            failure_code="trading_max_live_execution_or_evaluation_failed",
            checks=[
                _safe_check(
                    "trading_max_live_execution",
                    False,
                    "fixed acceptance failed safely; raw error hidden",
                )
            ],
        )
    if receipt_path is not None:
        _write(receipt_path, public)
    return public


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", help="sanitized JSON receipt path")
    args = parser.parse_args(argv)
    report = execute(Path(args.receipt).resolve() if args.receipt else None)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
