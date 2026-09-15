#!/usr/bin/env python3
"""One-shot hosted acceptance proof for the unified MAXIMUM research path.

This harness proves execution receipts, not configured intent. A passing run must
show all six specialist roles completed independent first-pass drafts, their
accounting is complete, the specialist handoff was prepared without clipping,
and the chief actually completed analysis + critique + hypothesis + synthesis.
A configured 10-call budget by itself is never accepted as execution proof.

The tool creates short-lived project/job capabilities only in memory. It never
prints or writes either bearer token, never mutates Railway/GitHub/infrastructure,
and emits only a sanitized receipt. ``/health`` must report ZERO_COST_ONLY before
any research job is submitted; this is an application guard, not a provider
billing oracle.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


EXPECTED_ROLES = (
    "evidence",
    "validation",
    "mechanism",
    "red_team",
    "data_quality",
    "implementation",
)
REQUIRED_CHIEF_PASSES = ("analysis", "critique", "hypothesis", "synthesis")
_TERMINAL = {"complete", "completed", "failed", "interrupted", "cancelled"}
_SUCCESS = {"complete", "completed"}


class AcceptanceError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def _json_request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 45.0,
) -> tuple[int, Any]:
    data = None
    merged = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        merged["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=merged, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            status = int(response.status)
    except error.HTTPError as exc:
        raw = exc.read()
        status = int(exc.code)
    except (error.URLError, TimeoutError, OSError) as exc:
        # Never include request headers/capabilities in the error surface.
        raise AcceptanceError(f"request failed: {method} {url}: {type(exc).__name__}") from exc
    try:
        body = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"non-JSON response: {method} {url} HTTP {status}") from exc
    return status, body


def _require(status: int, expected: set[int], body: Any, label: str) -> Any:
    # Deliberately do not echo server bodies: provider errors or capabilities
    # must never become CI/log output through this acceptance tool.
    if status not in expected:
        raise AcceptanceError(f"{label} failed with HTTP {status}")
    return body


def _as_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AcceptanceError(f"{label} is missing or not an object")
    return value


def _int(value: Any) -> int:
    return value if type(value) is int and value >= 0 else 0


def validate_health(health: Any, expected_build_revision: str = "") -> dict[str, Any]:
    health = _as_dict(health, "health response")
    if health.get("zero_cost_only") is not True:
        raise AcceptanceError("ZERO_COST_ONLY is not confirmed by public health; refusing live MAXIMUM run")
    build = str(health.get("build_revision") or "").strip()
    expected = str(expected_build_revision or "").strip()
    if expected and build != expected:
        raise AcceptanceError("deployed build revision does not match the explicitly reviewed revision")
    reasoning = _as_dict(health.get("reasoning_resilience"), "reasoning resilience status")
    if reasoning.get("has_model_layer_usable_now") is not True:
        raise AcceptanceError("no usable confirmed model layer is available; refusing a fake MAXIMUM proof")
    storage = health.get("storage") if isinstance(health.get("storage"), dict) else {}
    return {
        "service_health": str(health.get("status") or ""),
        "build_revision": build,
        "zero_cost_only": True,
        "model_layer_usable_now": True,
        "storage_available": storage.get("available") is True,
        "split_storage": storage.get("split_storage") is True,
    }


def validate_maximum_result(result: Any) -> dict[str, Any]:
    """Fail closed unless result bytes prove the six-worker + chief contract."""
    result = _as_dict(result, "research result")
    if str(result.get("mode") or "").upper() != "MAXIMUM":
        raise AcceptanceError("result mode is not MAXIMUM")

    verification = _as_dict(result.get("verification"), "verification")
    company = _as_dict(verification.get("research_company"), "verification.research_company")
    if company.get("schema_version") != 1:
        raise AcceptanceError("research company receipt schema is missing/unsupported")
    if company.get("status") != "DRAFTS_READY":
        raise AcceptanceError("specialist company did not reach DRAFTS_READY")
    if company.get("requested_workers") != 6 or company.get("completed_workers") != 6:
        raise AcceptanceError("MAXIMUM did not complete exactly 6/6 specialist workers")
    if company.get("logical_call_budget") != 10 or company.get("chief_call_budget") != 4:
        raise AcceptanceError("MAXIMUM company/chief budget contract is not 10 = 6 + 4")
    if company.get("independent_first_passes") is not True:
        raise AcceptanceError("independent specialist first passes are not confirmed")
    # These must stay explicitly false: specialists sharing sources/models are
    # not independent scientific replication and model diversity is not proven.
    if company.get("independent_models_verified") is not False:
        raise AcceptanceError("model-independence truth label is missing or overstated")
    if company.get("independent_scientific_replication") is not False:
        raise AcceptanceError("scientific-replication truth label is missing or overstated")
    if company.get("experiments_performed_by_workers") is not False:
        raise AcceptanceError("worker drafts are incorrectly claiming performed experiments")
    if company.get("accounting_complete") is not True:
        raise AcceptanceError("specialist usage accounting is incomplete")
    if company.get("handoff_prepared") is not True:
        raise AcceptanceError("specialist-to-chief handoff was not prepared")
    clipped = company.get("handoff_truncated_roles")
    if not isinstance(clipped, list) or clipped:
        raise AcceptanceError("specialist-to-chief handoff is missing its truncation receipt or was clipped")

    workers = company.get("workers")
    if not isinstance(workers, list) or len(workers) != 6:
        raise AcceptanceError("worker receipt list is not exactly six entries")
    roles = [str(row.get("role") or "") if isinstance(row, dict) else "" for row in workers]
    if roles != list(EXPECTED_ROLES) or len(set(roles)) != 6:
        raise AcceptanceError("worker roles do not match the exact six-role MAXIMUM contract")

    worker_receipts: list[dict[str, Any]] = []
    for row in workers:
        row = _as_dict(row, "worker receipt")
        role = str(row.get("role") or "")
        if row.get("status") != "DRAFT_READY" or row.get("error") not in {"", None}:
            raise AcceptanceError(f"specialist {role} did not complete a valid draft")
        if row.get("accounting_complete") is not True:
            raise AcceptanceError(f"specialist {role} accounting is incomplete")
        if row.get("provider_output_capture_complete") is not True:
            raise AcceptanceError(f"specialist {role} output was truncated or capture is unproven")
        report = _as_dict(row.get("report"), f"specialist {role} report")
        if report.get("status") != "DRAFT_READY":
            raise AcceptanceError(f"specialist {role} normalized report is not DRAFT_READY")
        if report.get("experiments_performed") is not False:
            raise AcceptanceError(f"specialist {role} incorrectly claims performed experiments")
        accounting = _as_dict(row.get("accounting"), f"specialist {role} accounting")
        logical = _int(accounting.get("logical_reasoning_calls"))
        outputs = _int(accounting.get("passes_with_output"))
        if logical < 1 or outputs < 1:
            raise AcceptanceError(f"specialist {role} has no actual reasoning-output receipt")
        worker_receipts.append({
            "role": role,
            "status": "DRAFT_READY",
            "logical_reasoning_calls": logical,
            "passes_with_output": outputs,
            "accounting_complete": True,
            "output_capture_complete": True,
        })

    chief = _as_dict(company.get("chief_execution"), "chief execution")
    done = chief.get("done_passes")
    if not isinstance(done, list):
        raise AcceptanceError("chief done-pass receipt is missing")
    done_set = {str(name) for name in done}
    missing_chief = [name for name in REQUIRED_CHIEF_PASSES if name not in done_set]
    if missing_chief:
        raise AcceptanceError("chief did not complete all required semantic passes: " + ", ".join(missing_chief))
    chief_accounting = _as_dict(chief.get("accounting"), "chief accounting")
    chief_logical = _int(chief_accounting.get("logical_reasoning_calls"))
    chief_outputs = _int(chief_accounting.get("passes_with_output"))
    # Hypothesis can share the critique call, so four semantic done-passes can
    # legitimately be established by three model outputs. Never demand 4 HTTPs.
    if chief_logical < 3 or chief_outputs < 3:
        raise AcceptanceError("chief semantic passes lack sufficient actual reasoning-output receipts")

    missing_passes = result.get("missing_passes")
    missing_passes = missing_passes if isinstance(missing_passes, list) else []
    company_pass_names = {"specialist_handoff", *REQUIRED_CHIEF_PASSES,
                          *("company_" + role for role in EXPECTED_ROLES)}
    missing_company = sorted({str(name) for name in missing_passes} & company_pass_names)
    if missing_company:
        raise AcceptanceError("final run ledger still marks company/chief passes missing: " + ", ".join(missing_company))

    total_accounting = _as_dict(result.get("api_accounting"), "combined API accounting")
    if total_accounting.get("accounting_complete") is not True:
        raise AcceptanceError("combined worker accounting is not exact")
    if total_accounting.get("counts_are_lower_bounds") is not False:
        raise AcceptanceError("combined call counts are only lower bounds")
    if _int(total_accounting.get("unknown_worker_usage")) != 0:
        raise AcceptanceError("combined accounting reports unknown worker usage")

    return {
        "architecture_pass": True,
        "mode": "MAXIMUM",
        "overall_research_status": str(result.get("status") or ""),
        "company_status": "DRAFTS_READY",
        "requested_workers": 6,
        "completed_workers": 6,
        "roles": list(EXPECTED_ROLES),
        "independent_first_passes": True,
        "independent_models_verified": False,
        "independent_scientific_replication": False,
        "worker_experiments_performed": False,
        "handoff_prepared": True,
        "handoff_truncated_roles": [],
        "workers": worker_receipts,
        "chief_done_passes": list(REQUIRED_CHIEF_PASSES),
        "chief_logical_reasoning_calls": chief_logical,
        "chief_passes_with_output": chief_outputs,
        "combined_logical_reasoning_calls": _int(total_accounting.get("logical_reasoning_calls")),
        "combined_actual_http_attempts": _int(total_accounting.get("actual_http_attempts")),
        "combined_accounting_complete": True,
        "missing_company_passes": [],
    }


def _health(base_url: str) -> dict[str, Any]:
    status, body = _json_request("GET", _url(base_url, "/health"))
    body = _require(status, {200}, body, "health")
    return _as_dict(body, "health response")


def _create_session(base_url: str) -> tuple[str, str]:
    status, body = _json_request("POST", _url(base_url, "/api/v1/session"))
    body = _require(status, {201}, body, "session create")
    body = _as_dict(body, "session response")
    project_id = str(body.get("project_id") or "").strip()
    token = str(body.get("project_access_token") or "").strip()
    if not project_id or not token:
        raise AcceptanceError("session response is missing a private project capability")
    return project_id, token


def _start_job(base_url: str, project_id: str, project_token: str, question: str) -> tuple[str, str]:
    status, body = _json_request(
        "POST",
        _url(base_url, "/api/v1/research-jobs"),
        payload={"question": question, "project_id": project_id, "depth_mode": "MAXIMUM"},
        headers={"X-Project-Token": project_token},
    )
    body = _require(status, {202}, body, "MAXIMUM job submit")
    body = _as_dict(body, "MAXIMUM job response")
    job_id = str(body.get("job_id") or "").strip()
    token = str(body.get("job_access_token") or "").strip()
    if not job_id or not token:
        raise AcceptanceError("MAXIMUM job response is missing a private job capability")
    return job_id, token


def _job_status(base_url: str, job_id: str, token: str) -> dict[str, Any]:
    status, body = _json_request(
        "GET", _url(base_url, f"/api/v1/research-jobs/{job_id}"),
        headers={"X-Research-Job-Token": token},
    )
    body = _require(status, {200}, body, "MAXIMUM job status")
    return _as_dict(body, "MAXIMUM job status")


def _wait_terminal(base_url: str, job_id: str, token: str, timeout_seconds: float, poll_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = _job_status(base_url, job_id, token)
        state = str(latest.get("status") or "").strip().lower()
        if state in _TERMINAL:
            if state not in _SUCCESS:
                raise AcceptanceError(f"MAXIMUM job reached terminal non-success state: {state}")
            return latest
        time.sleep(max(0.5, poll_seconds))
    raise AcceptanceError("MAXIMUM job did not reach a successful terminal state before timeout")


def _fetch_result(base_url: str, job_id: str, token: str) -> dict[str, Any]:
    status, body = _json_request(
        "GET", _url(base_url, f"/api/v1/research-jobs/{job_id}/result"),
        headers={"X-Research-Job-Token": token},
    )
    body = _require(status, {200}, body, "MAXIMUM job result")
    return _as_dict(body, "MAXIMUM job result")


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def run_live(args: argparse.Namespace) -> dict[str, Any]:
    health = _health(args.base_url)
    health_receipt = validate_health(health, args.expected_build_revision)
    project_id, project_token = _create_session(args.base_url)
    job_id, job_token = _start_job(args.base_url, project_id, project_token, args.question)
    _wait_terminal(args.base_url, job_id, job_token, args.timeout_seconds, args.poll_seconds)
    result = _fetch_result(args.base_url, job_id, job_token)
    architecture = validate_maximum_result(result)
    receipt = {
        "schema_version": 1,
        "kind": "MAXIMUM_SIX_SPECIALISTS_CHIEF_ACCEPTANCE",
        "observed_at": _now(),
        "base_url": args.base_url.rstrip("/"),
        "job_id": job_id,
        "health": health_receipt,
        **architecture,
        "project_capability_in_receipt": False,
        "job_capability_in_receipt": False,
        "raw_model_output_in_receipt": False,
        "pass": True,
    }
    _write_receipt(Path(args.receipt_file), receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--receipt-file", required=True, help="Sanitized JSON receipt; contains no bearer capability")
    parser.add_argument("--expected-build-revision", default="", help="Optional exact deployed Git revision; mismatch fails closed")
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument(
        "--question",
        default=(
            "MAXIMUM acceptance test: using credible sources, assess whether random assignment in controlled "
            "experiments reduces baseline confounding compared with an uncontrolled observational comparison. "
            "Include exactly one testable hypothesis with a prediction, simpler baseline, concrete test and "
            "falsification criterion, plus a red-team critique. Keep the final prose concise."
        ),
        help="Keep an explicit hypothesis + red-team request so all four chief semantic passes are required.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = run_live(args)
    except AcceptanceError as exc:
        print(f"MAXIMUM_ACCEPTANCE_FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
