#!/usr/bin/env python3
"""Public-safe postmortem for the fixed PR #81 live acceptance receipt.

This diagnostic NEVER starts another research/model run. It only revalidates the
sanitized receipt produced by the original acceptance process and emits a smaller
bounded summary. Prompts, answers, sources, URLs, credentials, provider bodies,
exception names, function names and filesystem paths are never copied out.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.release_identity import repository_identity

_MAX_RECEIPT_BYTES = 256 * 1024
_ALLOWED_FAILURE_CODES = frozenset({
    "trading_max_live_execution_or_evaluation_failed",
    "trading_max_live_research_failed",
    "trading_max_live_evaluation_failed",
})
_ALLOWED_CHECKS = frozenset({
    "status_complete",
    "maximum_mode_executed",
    "coding_not_creative",
    "six_workers_requested",
    "task_contract_complete",
    "threshold_provenance",
    "trade_contract_ran",
    "critical_trade_contract",
    "no_chased_win_rate",
    "trading_reality_boundaries",
    "three_structured_hypotheses",
    "six_specialists_executed",
    "specialist_handoff_complete",
    "company_accounting_complete",
    "chief_executed",
    "implementation_build_executed",
    "no_false_replication",
    "trading_max_live_execution",
})


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _load_acceptance_receipt(path: Path) -> Mapping[str, Any]:
    """Load one bounded JSON mapping; fail closed on malformed/oversized input."""
    try:
        stat = path.stat()
        if stat.st_size <= 0 or stat.st_size > _MAX_RECEIPT_BYTES:
            return {}
        raw = path.read_text(encoding="utf-8")
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _safe_failed_checks(value: Any) -> list[str]:
    rows = value if isinstance(value, list) else []
    failed: list[str] = []
    for row in rows[:64]:
        if not isinstance(row, Mapping) or row.get("passed") is True:
            continue
        name = row.get("name")
        if isinstance(name, str) and name in _ALLOWED_CHECKS:
            failed.append(name)
    return sorted(set(failed))


def _safe_failure_code(value: Any) -> str:
    if isinstance(value, str) and value in _ALLOWED_FAILURE_CODES:
        return value
    return "unclassified_failure"


def execute(
    acceptance_receipt_path: Path,
    receipt_path: Path | None = None,
) -> Dict[str, Any]:
    """Summarize the ORIGINAL run receipt without making any additional calls."""
    started = time.time()
    identity = repository_identity(ROOT)
    report: Dict[str, Any] = {
        "schema_version": 2,
        "code_revision": str(identity.get("revision") or ""),
        "repository_clean": identity.get("clean") is True,
        "passed": False,
        "source_receipt_reused": True,
        "additional_research_calls": 0,
        "additional_model_calls": 0,
        "contains_answer_or_source_text": False,
        "contains_question_text": False,
        "contains_credentials": False,
        "contains_exception_message": False,
        "contains_exception_type_or_function_name": False,
        "contains_filesystem_path": False,
    }
    if not identity.get("available") or identity.get("clean") is not True:
        report.update(
            duration_seconds=round(time.time() - started, 2),
            failure_stage="preflight",
            failure_category="repository_identity",
        )
        if receipt_path is not None:
            _write(receipt_path, report)
        return report

    source = _load_acceptance_receipt(acceptance_receipt_path)
    if not source:
        report.update(
            duration_seconds=round(time.time() - started, 2),
            failure_stage="receipt_validation",
            failure_category="source_receipt_invalid",
            failed_checks=[],
            failed_check_count=0,
        )
        if receipt_path is not None:
            _write(receipt_path, report)
        return report

    failed_checks = _safe_failed_checks(source.get("checks"))
    source_passed = source.get("passed") is True
    failure_code = "none" if source_passed else _safe_failure_code(source.get("failure_code"))
    report.update(
        passed=source_passed,
        failure_stage="none" if source_passed else "original_acceptance_run",
        failure_category=failure_code,
        failed_checks=failed_checks,
        failed_check_count=len(failed_checks),
        source_schema_version=(
            int(source.get("schema_version"))
            if type(source.get("schema_version")) is int
            and 0 <= int(source.get("schema_version")) <= 100
            else 0
        ),
        duration_seconds=round(time.time() - started, 2),
    )
    if receipt_path is not None:
        _write(receipt_path, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--acceptance-receipt",
        required=True,
        help="sanitized receipt from the original PR81 acceptance run",
    )
    parser.add_argument("--receipt", help="sanitized diagnostic JSON receipt path")
    args = parser.parse_args(argv)
    report = execute(
        Path(args.acceptance_receipt).resolve(),
        Path(args.receipt).resolve() if args.receipt else None,
    )
    print(json.dumps(report, indent=2))
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
