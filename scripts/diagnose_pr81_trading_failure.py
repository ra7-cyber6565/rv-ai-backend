#!/usr/bin/env python3
"""Public-safe failure-stage diagnostic for the fixed PR #81 live acceptance.

This module deliberately reuses the real acceptance runner and evaluator instead
of creating a second research path. It is only a diagnostic harness: on failure
it emits structural metadata about *where* execution failed, never exception
messages, prompts, answers, sources, URLs, credentials, or provider bodies.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
import traceback
from typing import Any, Dict, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]

from scripts import run_pr81_trading_live_acceptance as acceptance
from utils.release_identity import repository_identity


def _exception_family(exc: Exception) -> str:
    """Classify from exception type/module only; never inspect secret-bearing text."""
    name = type(exc).__name__.lower()
    module = str(type(exc).__module__ or "").lower()
    token = f"{module}.{name}"
    if any(part in token for part in ("timeout", "deadline")):
        return "timeout"
    if any(part in token for part in ("auth", "unauth", "permission", "forbidden")):
        return "authentication_or_permission"
    if any(part in token for part in ("resourceexhaust", "ratelimit", "quota")):
        return "provider_capacity"
    if any(part in token for part in ("json", "decode", "parse")):
        return "structured_response"
    if any(part in token for part in ("docker", "subprocess", "process", "executor")):
        return "isolated_execution"
    if any(part in token for part in ("sqlite", "storage", "disk", "database")):
        return "storage"
    if "runtimeblocked" in token:
        return "runtime_guard"
    if "assert" in token:
        return "contract_assertion"
    return "unclassified_exception"


def _internal_origin(exc: Exception) -> Dict[str, Any]:
    """Return only public-repo frame coordinates; omit code lines and values."""
    root = ROOT.resolve()
    frames = traceback.extract_tb(exc.__traceback__)
    for frame in reversed(frames):
        try:
            path = Path(frame.filename).resolve()
            rel = path.relative_to(root)
        except (OSError, ValueError):
            continue
        return {
            "file": rel.as_posix(),
            "function": str(frame.name)[:120],
            "line": int(frame.lineno),
        }
    return {"file": "external", "function": "external", "line": 0}


def _safe_exception(exc: Exception) -> Dict[str, Any]:
    return {
        "family": _exception_family(exc),
        "type": str(type(exc).__name__)[:120],
        "module": str(type(exc).__module__ or "").split(".", 1)[0][:80],
        "origin": _internal_origin(exc),
        "message_recorded": False,
    }


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), indent=2), encoding="utf-8")
    os.replace(tmp, path)


def execute(receipt_path: Path | None = None) -> Dict[str, Any]:
    started = time.time()
    identity = repository_identity(ROOT)
    report: Dict[str, Any] = {
        "schema_version": 1,
        "code_revision": str(identity.get("revision") or ""),
        "repository_clean": identity.get("clean") is True,
        "passed": False,
        "failure_stage": "preflight",
        "contains_answer_or_source_text": False,
        "contains_question_text": False,
        "contains_credentials": False,
        "contains_exception_message": False,
    }
    if not identity.get("available") or identity.get("clean") is not True:
        report.update(
            duration_seconds=round(time.time() - started, 2),
            failure_category="repository_identity",
        )
        if receipt_path is not None:
            _write(receipt_path, report)
        return report

    report["failure_stage"] = "research_execution"
    try:
        result = acceptance.run_live()
    except Exception as exc:
        report.update(
            duration_seconds=round(time.time() - started, 2),
            failure_category="research_execution_exception",
            exception=_safe_exception(exc),
        )
        if receipt_path is not None:
            _write(receipt_path, report)
        return report

    report["failure_stage"] = "acceptance_evaluation"
    try:
        measured = acceptance.evaluate_result(result)
    except Exception as exc:
        report.update(
            duration_seconds=round(time.time() - started, 2),
            failure_category="acceptance_evaluation_exception",
            exception=_safe_exception(exc),
        )
        if receipt_path is not None:
            _write(receipt_path, report)
        return report

    failed_checks = [
        str(row.get("name") or "")
        for row in (measured.get("checks") or [])
        if isinstance(row, Mapping) and row.get("passed") is not True
    ]
    report.update(
        passed=measured.get("passed") is True,
        failure_stage="none" if measured.get("passed") is True else "acceptance_checks",
        failure_category="none" if measured.get("passed") is True else "measured_contract_gap",
        failed_checks=failed_checks,
        failed_check_count=len(failed_checks),
        duration_seconds=round(time.time() - started, 2),
    )
    if receipt_path is not None:
        _write(receipt_path, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", help="sanitized diagnostic JSON receipt path")
    args = parser.parse_args(argv)
    report = execute(Path(args.receipt).resolve() if args.receipt else None)
    print(json.dumps(report, indent=2))
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
