#!/usr/bin/env python3
"""Capture a blind, frozen LIVE MAXIMUM benchmark campaign safely.

This tool is the generation/provenance half of the held-out release gate.  It
never grades an answer and never stores gold/rubric/solution data.  A private
operator-supplied task pack contains only task ids + prompts and must be frozen
by SHA-256 before execution.  Raw research results are written only to the
private capture file; the public receipt contains hashes/counters/provenance.

The harness deliberately reuses the MAXIMUM live-acceptance client so every
trial first proves the deployed revision, ZERO_COST_ONLY health state, usable
confirmed-free model layer and the six-specialist + chief execution contract.
An HTTP-attempt ceiling is predeclared by the operator and checked after each
run; unlike the wall-clock timeout, that ceiling is an acceptance cap rather
than an in-process provider throttle, so the receipt says exactly that.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools import maximum_live_acceptance as max_live  # noqa: E402
from utils.research_runtime import digest  # noqa: E402


_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FORBIDDEN_TARGET_KEYS = {
    "answer", "answers", "gold", "gold_answer", "gold_answers",
    "ground_truth", "ground_truths", "label", "labels",
    "reference_answer", "reference_answers", "rubric", "rubrics",
    "solution", "solutions", "expected_answer", "expected_answers",
}
_CAPABILITY_KEYS = {
    "project_access_token", "job_access_token", "x_project_token",
    "x_research_job_token", "authorization", "api_key", "apikey",
}


class CampaignCaptureError(ValueError):
    """Malformed, unsafe or non-auditable benchmark capture input/result."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha40(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA40.fullmatch(text):
        raise CampaignCaptureError(f"{label} must be one full 40-character Git SHA")
    return text


def _sha256(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256.fullmatch(text):
        raise CampaignCaptureError(f"{label} must be one 64-character SHA-256")
    return text


def _normalize_key(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _assert_no_targets(value: Any, path: str = "task_pack") -> None:
    """Reject any grading target from the generation-time prompt artifact."""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _normalize_key(key)
            if normalized in _FORBIDDEN_TARGET_KEYS:
                raise CampaignCaptureError(
                    f"{path} contains grading-target field {key!r}; generation must stay blind"
                )
            _assert_no_targets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_targets(item, f"{path}[{index}]")


def _assert_no_capabilities(value: Any, path: str = "result") -> None:
    """Fail rather than persist a server response that unexpectedly contains credentials."""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _normalize_key(key)
            if normalized in _CAPABILITY_KEYS or "bearer_token" in normalized:
                raise CampaignCaptureError(
                    f"{path} unexpectedly contains a capability-like field; refusing to persist it"
                )
            _assert_no_capabilities(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_capabilities(item, f"{path}[{index}]")


def _read_json(path: str, label: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignCaptureError(f"{label} JSON is unavailable or invalid") from exc


def validate_task_pack(value: Any, expected_sha256: str) -> list[dict[str, str]]:
    """Validate a private prompt-only untouched holdout and its frozen digest."""
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise CampaignCaptureError("task pack schema_version must be 1")
    _assert_no_targets(value)
    if value.get("split") != "untouched_holdout" or value.get("used_for_tuning") is not False:
        raise CampaignCaptureError(
            "task pack must declare split=untouched_holdout and used_for_tuning=false"
        )
    expected = _sha256(expected_sha256, "expected_task_pack_sha256")
    if digest(value) != expected:
        raise CampaignCaptureError("frozen task pack changed")
    raw_tasks = value.get("tasks")
    if not isinstance(raw_tasks, list) or len(raw_tasks) < 2:
        raise CampaignCaptureError("task pack must contain at least two held-out tasks")
    tasks: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, row in enumerate(raw_tasks):
        if not isinstance(row, dict):
            raise CampaignCaptureError(f"tasks[{index}] must be an object")
        task_id = str(row.get("task_id") or "").strip()
        question = str(row.get("question") or "").strip()
        if not _TASK_ID.fullmatch(task_id):
            raise CampaignCaptureError(f"tasks[{index}].task_id is invalid")
        if task_id in seen:
            raise CampaignCaptureError("task ids must be unique")
        if not question or len(question) > 20000:
            raise CampaignCaptureError(f"tasks[{index}].question is empty or too large")
        extra = set(row) - {"task_id", "question"}
        if extra:
            raise CampaignCaptureError(
                f"tasks[{index}] contains undeclared fields: {sorted(extra)}"
            )
        seen.add(task_id)
        tasks.append({"task_id": task_id, "question": question})
    return tasks


def _nonnegative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise CampaignCaptureError(f"{label} must be a nonnegative integer")
    return value


def extract_accounting(result: Any, *, http_budget: int) -> dict[str, int]:
    """Require exact final accounting and enforce the predeclared HTTP cap."""
    if not isinstance(result, dict):
        raise CampaignCaptureError("research result must be an object")
    accounting = result.get("api_accounting")
    if not isinstance(accounting, dict):
        raise CampaignCaptureError("research result lacks combined API accounting")
    if accounting.get("accounting_complete") is not True:
        raise CampaignCaptureError("research result API accounting is incomplete")
    if accounting.get("counts_are_lower_bounds") is not False:
        raise CampaignCaptureError("research result API accounting is only a lower bound")
    if _nonnegative_int(accounting.get("unknown_worker_usage"), "unknown_worker_usage") != 0:
        raise CampaignCaptureError("research result has unknown worker usage")
    actual_http = _nonnegative_int(
        accounting.get("actual_http_attempts"), "actual_http_attempts"
    )
    logical = _nonnegative_int(
        accounting.get("logical_reasoning_calls"), "logical_reasoning_calls"
    )
    if actual_http > http_budget:
        raise CampaignCaptureError(
            "actual HTTP attempts exceeded the predeclared campaign acceptance cap"
        )
    return {
        "actual_http_attempts": actual_http,
        "logical_reasoning_calls": logical,
    }


def _private_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    temp.write_text(payload, encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _public_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _trial(
    *,
    base_url: str,
    expected_revision: str,
    task_id: str,
    question: str,
    trial: int,
    http_budget: int,
    seconds_budget: float,
    poll_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    project_id, project_token = max_live._create_session(base_url)
    job_id, job_token = max_live._start_job(
        base_url, project_id, project_token, question
    )
    max_live._wait_terminal(
        base_url, job_id, job_token, seconds_budget, poll_seconds
    )
    result = max_live._fetch_result(base_url, job_id, job_token)
    _assert_no_capabilities(result)
    architecture = max_live.validate_maximum_result(result)
    accounting = extract_accounting(result, http_budget=http_budget)
    latency = time.monotonic() - started
    if not math.isfinite(latency) or latency < 0 or latency > seconds_budget + max(5.0, poll_seconds * 2):
        raise CampaignCaptureError("trial wall-clock accounting is invalid or exceeded its bounded allowance")
    output_sha = digest(result)
    common = {
        "task_id": task_id,
        "trial": trial,
        "revision": expected_revision,
        "execution_kind": "LIVE",
        "mode": "MAXIMUM",
        "http_budget": http_budget,
        "seconds_budget": float(seconds_budget),
        "latency_seconds": latency,
        "output_sha256": output_sha,
        "actual_http_attempts": accounting["actual_http_attempts"],
        "logical_reasoning_calls": accounting["logical_reasoning_calls"],
        "architecture_pass": architecture.get("architecture_pass") is True,
        "completed_workers": architecture.get("completed_workers"),
        "chief_passes_with_output": architecture.get("chief_passes_with_output"),
    }
    private = {
        **common,
        "job_id": job_id,
        "raw_result": result,
        "project_capability_persisted": False,
        "job_capability_persisted": False,
    }
    public = {
        **common,
        "raw_result_in_receipt": False,
        "question_in_receipt": False,
        "project_capability_in_receipt": False,
        "job_capability_in_receipt": False,
    }
    return private, public


def run_capture(args: argparse.Namespace) -> dict[str, Any]:
    revision = _sha40(args.expected_build_revision, "expected_build_revision")
    if type(args.trials_per_task) is not int or not 1 <= args.trials_per_task <= 5:
        raise CampaignCaptureError("trials_per_task must be an integer from 1 to 5")
    if type(args.http_budget) is not int or not 1 <= args.http_budget <= 100:
        raise CampaignCaptureError("http_budget must be an integer from 1 to 100")
    if not isinstance(args.seconds_budget, (int, float)) or not math.isfinite(args.seconds_budget):
        raise CampaignCaptureError("seconds_budget must be finite")
    if not 30 <= float(args.seconds_budget) <= 3600:
        raise CampaignCaptureError("seconds_budget must be between 30 and 3600 seconds")
    if not isinstance(args.poll_seconds, (int, float)) or not math.isfinite(args.poll_seconds):
        raise CampaignCaptureError("poll_seconds must be finite")
    if not 0.5 <= float(args.poll_seconds) <= 30:
        raise CampaignCaptureError("poll_seconds must be between 0.5 and 30 seconds")

    task_pack = _read_json(args.task_pack, "task pack")
    expected_pack = _sha256(args.expected_task_pack_sha256, "expected_task_pack_sha256")
    tasks = validate_task_pack(task_pack, expected_pack)

    health = max_live._health(args.base_url)
    health_receipt = max_live.validate_health(health, revision)

    private_rows: list[dict[str, Any]] = []
    public_rows: list[dict[str, Any]] = []
    for task in tasks:
        for trial_index in range(args.trials_per_task):
            private, public = _trial(
                base_url=args.base_url,
                expected_revision=revision,
                task_id=task["task_id"],
                question=task["question"],
                trial=trial_index,
                http_budget=args.http_budget,
                seconds_budget=float(args.seconds_budget),
                poll_seconds=float(args.poll_seconds),
            )
            private_rows.append(private)
            public_rows.append(public)

    private_capture = {
        "schema_version": 1,
        "kind": "HELDOUT_BLIND_GENERATION_CAPTURE_PRIVATE",
        "captured_at": _now(),
        "task_pack_sha256": expected_pack,
        "task_pack_id": str(task_pack.get("task_pack_id") or "").strip(),
        "split": "untouched_holdout",
        "used_for_tuning": False,
        "revision": revision,
        "base_url": args.base_url.rstrip("/"),
        "mode": "MAXIMUM",
        "execution_kind": "LIVE",
        "trials_per_task": args.trials_per_task,
        "http_budget": args.http_budget,
        "http_budget_semantics": "predeclared post-run acceptance ceiling; not an in-process provider throttle",
        "seconds_budget": float(args.seconds_budget),
        "rows": private_rows,
    }
    private_capture["capture_sha256"] = digest(private_capture)
    _private_write(Path(args.private_capture_file), private_capture)

    receipt = {
        "schema_version": 1,
        "kind": "HELDOUT_BLIND_GENERATION_CAPTURE_RECEIPT",
        "captured_at": private_capture["captured_at"],
        "task_pack_sha256": expected_pack,
        "task_pack_id": private_capture["task_pack_id"],
        "split": "untouched_holdout",
        "used_for_tuning": False,
        "revision": revision,
        "health": health_receipt,
        "mode": "MAXIMUM",
        "execution_kind": "LIVE",
        "tasks": len(tasks),
        "paired_trials_ready": len(public_rows),
        "trials_per_task": args.trials_per_task,
        "http_budget": args.http_budget,
        "http_budget_semantics": private_capture["http_budget_semantics"],
        "seconds_budget": float(args.seconds_budget),
        "rows": public_rows,
        "private_capture_sha256": private_capture["capture_sha256"],
        "private_capture_path_in_receipt": False,
        "questions_in_receipt": False,
        "grading_targets_in_generation_artifacts": False,
        "raw_results_in_receipt": False,
        "capabilities_in_receipt": False,
        "grading_performed": False,
        "release_decision_performed": False,
        "limitations": [
            "this captures generation/provenance only; an independent frozen grader must score outputs later",
            "the HTTP budget is a predeclared acceptance ceiling checked from exact final accounting, not an in-process provider throttle",
            "a capture pass does not prove benchmark superiority, scientific truth, provider billing state or production persistence",
        ],
        "pass": True,
    }
    receipt["receipt_sha256"] = digest(receipt)
    _public_write(Path(args.receipt_file), receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-build-revision", required=True)
    parser.add_argument("--task-pack", required=True, help="PRIVATE prompt-only untouched holdout JSON")
    parser.add_argument("--expected-task-pack-sha256", required=True, help="Frozen canonical task-pack SHA-256")
    parser.add_argument("--private-capture-file", required=True, help="PRIVATE raw result capture; keep out of logs/artifacts")
    parser.add_argument("--receipt-file", required=True, help="Sanitized public-safe capture receipt")
    parser.add_argument("--trials-per-task", type=int, default=1)
    parser.add_argument("--http-budget", type=int, default=24)
    parser.add_argument("--seconds-budget", type=float, default=1800.0)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = run_capture(args)
    except (CampaignCaptureError, max_live.AcceptanceError) as exc:
        print(f"HELDOUT_CAPTURE_FAIL: {exc}", file=sys.stderr)
        return 2
    print(
        f"HELDOUT_CAPTURE_PASS: tasks={receipt['tasks']} rows={receipt['paired_trials_ready']} "
        f"receipt={args.receipt_file}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
