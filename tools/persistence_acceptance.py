#!/usr/bin/env python3
"""Two-phase production persistence acceptance test.

Phase 1 (before a controlled restart/redeploy):
  1. create an anonymous project session,
  2. submit one bounded research job,
  3. wait for a terminal state,
  4. fetch the final result,
  5. save a private state file containing the job capability, and
  6. emit a sanitized receipt with a stable result digest.

Phase 2 (after the restart/redeploy):
  1. load the private state,
  2. fetch the SAME job with the SAME capability token,
  3. fetch the SAME result,
  4. compare the stable digest, and
  5. emit a second sanitized receipt.

The private state file contains a bearer capability and must never be committed or
shared. Receipts intentionally exclude all capability tokens and absolute paths.

This tool does not restart, redeploy, merge, or mutate infrastructure. It only
uses the public API supplied through --base-url.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

_TERMINAL = {"complete", "completed", "failed", "interrupted", "cancelled"}
_SUCCESS = {"complete", "completed"}
_VOLATILE_RESULT_KEYS = {"research_progress"}


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
    timeout: float = 30.0,
) -> tuple[int, Any]:
    body = None
    merged_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        merged_headers["Content-Type"] = "application/json"
    req = request.Request(url, data=body, headers=merged_headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            status = int(response.status)
    except error.HTTPError as exc:
        raw = exc.read()
        status = int(exc.code)
    except (error.URLError, TimeoutError, OSError) as exc:
        raise AcceptanceError(f"request failed: {method} {url}: {exc}") from exc

    try:
        decoded = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"non-JSON response: {method} {url} HTTP {status}") from exc
    return status, decoded


def _require(status: int, expected: set[int], body: Any, label: str) -> Any:
    if status not in expected:
        detail = ""
        if isinstance(body, dict):
            value = body.get("detail")
            if isinstance(value, str):
                detail = ": " + value[:240]
        raise AcceptanceError(f"{label} failed with HTTP {status}{detail}")
    return body


def stable_result(value: Any) -> Any:
    """Remove response-only runtime metadata before hashing persisted semantics."""
    if isinstance(value, dict):
        return {
            str(key): stable_result(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _VOLATILE_RESULT_KEYS
        }
    if isinstance(value, list):
        return [stable_result(item) for item in value]
    return value


def result_digest(value: Any) -> str:
    canonical = json.dumps(
        stable_result(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        try:
            os.chmod(temp, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _health(base_url: str) -> dict[str, Any]:
    status, body = _json_request("GET", _url(base_url, "/health"))
    body = _require(status, {200}, body, "health")
    if not isinstance(body, dict):
        raise AcceptanceError("health response is not an object")
    return body


def _storage_receipt(health: dict[str, Any]) -> dict[str, Any]:
    storage = health.get("storage")
    if not isinstance(storage, dict):
        return {"available": False, "reported": False}
    # Public storage status is already sanitized by the server. Keep only fields
    # needed to prove routing/readiness and avoid accidentally widening receipts.
    allow = {
        "available",
        "configured",
        "split_storage",
        "durable_configured",
        "ephemeral_configured",
        "durable_available",
        "ephemeral_available",
    }
    return {key: storage[key] for key in sorted(allow) if key in storage}


def _create_session(base_url: str) -> tuple[str, str]:
    status, body = _json_request("POST", _url(base_url, "/api/v1/session"))
    body = _require(status, {201}, body, "session create")
    if not isinstance(body, dict):
        raise AcceptanceError("session response is not an object")
    project_id = str(body.get("project_id") or "").strip()
    token = str(body.get("project_access_token") or "").strip()
    if not project_id or not token:
        raise AcceptanceError("session response missing private project capability")
    return project_id, token


def _start_job(
    base_url: str,
    project_id: str,
    project_token: str,
    *,
    question: str,
    depth_mode: str,
) -> tuple[str, str]:
    payload = {
        "question": question,
        "project_id": project_id,
        "depth_mode": depth_mode,
    }
    status, body = _json_request(
        "POST",
        _url(base_url, "/api/v1/research-jobs"),
        payload=payload,
        headers={"X-Project-Token": project_token},
    )
    body = _require(status, {202}, body, "research job submit")
    if not isinstance(body, dict):
        raise AcceptanceError("research job response is not an object")
    job_id = str(body.get("job_id") or "").strip()
    job_token = str(body.get("job_access_token") or "").strip()
    if not job_id or not job_token:
        raise AcceptanceError("research job response missing private job capability")
    return job_id, job_token


def _job_status(base_url: str, job_id: str, token: str) -> dict[str, Any]:
    status, body = _json_request(
        "GET",
        _url(base_url, f"/api/v1/research-jobs/{job_id}"),
        headers={"X-Research-Job-Token": token},
    )
    body = _require(status, {200}, body, "job status")
    if not isinstance(body, dict):
        raise AcceptanceError("job status response is not an object")
    return body


def _wait_terminal(
    base_url: str,
    job_id: str,
    token: str,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = _job_status(base_url, job_id, token)
        current = str(latest.get("status") or "").strip().lower()
        if current in _TERMINAL:
            if current not in _SUCCESS:
                raise AcceptanceError(f"research job reached terminal non-success state: {current}")
            return latest
        time.sleep(max(0.25, poll_seconds))
    current = str(latest.get("status") or "unknown")
    raise AcceptanceError(
        f"research job did not finish within {timeout_seconds:g}s (last status={current})"
    )


def _fetch_result(base_url: str, job_id: str, token: str) -> Any:
    status, body = _json_request(
        "GET",
        _url(base_url, f"/api/v1/research-jobs/{job_id}/result"),
        headers={"X-Research-Job-Token": token},
    )
    return _require(status, {200}, body, "job result")


def _phase1(args: argparse.Namespace) -> dict[str, Any]:
    health = _health(args.base_url)
    project_id, project_token = _create_session(args.base_url)
    job_id, job_token = _start_job(
        args.base_url,
        project_id,
        project_token,
        question=args.question,
        depth_mode=args.depth_mode,
    )
    terminal = _wait_terminal(
        args.base_url,
        job_id,
        job_token,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
    )
    result = _fetch_result(args.base_url, job_id, job_token)
    digest = result_digest(result)

    private_state = {
        "schema_version": 1,
        "created_at": _now(),
        "base_url": args.base_url.rstrip("/"),
        "job_id": job_id,
        "job_access_token": job_token,
        "digest_before": digest,
        "build_revision_before": str(health.get("build_revision") or ""),
    }
    _write_private_json(Path(args.state_file), private_state)

    receipt = {
        "schema_version": 1,
        "phase": "before_restart",
        "observed_at": _now(),
        "base_url": args.base_url.rstrip("/"),
        "build_revision": str(health.get("build_revision") or ""),
        "service_health": str(health.get("status") or ""),
        "storage": _storage_receipt(health),
        "job_id": job_id,
        "job_status": str(terminal.get("status") or ""),
        "stable_result_sha256": digest,
        "private_capability_in_receipt": False,
        "pass": True,
    }
    _write_receipt(Path(args.receipt_file), receipt)
    return receipt


def _phase2(args: argparse.Namespace) -> dict[str, Any]:
    state_path = Path(args.state_file)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"private state file unavailable/invalid: {state_path}") from exc
    if not isinstance(state, dict):
        raise AcceptanceError("private state root must be an object")

    base_url = str(args.base_url or state.get("base_url") or "").rstrip("/")
    job_id = str(state.get("job_id") or "").strip()
    job_token = str(state.get("job_access_token") or "").strip()
    expected_digest = str(state.get("digest_before") or "").strip()
    if not base_url or not job_id or not job_token or len(expected_digest) != 64:
        raise AcceptanceError("private state is missing required acceptance data")

    health = _health(base_url)
    job = _job_status(base_url, job_id, job_token)
    current = str(job.get("status") or "").strip().lower()
    if current not in _SUCCESS:
        raise AcceptanceError(f"same job was not recoverable as completed after restart: {current}")

    result = _fetch_result(base_url, job_id, job_token)
    digest_after = result_digest(result)
    same = digest_after == expected_digest
    if not same:
        raise AcceptanceError(
            "same completed job was reachable, but stable result digest changed across restart"
        )

    receipt = {
        "schema_version": 1,
        "phase": "after_restart",
        "observed_at": _now(),
        "base_url": base_url,
        "build_revision_before": str(state.get("build_revision_before") or ""),
        "build_revision_after": str(health.get("build_revision") or ""),
        "service_health": str(health.get("status") or ""),
        "storage": _storage_receipt(health),
        "job_id": job_id,
        "job_status": str(job.get("status") or ""),
        "stable_result_sha256_before": expected_digest,
        "stable_result_sha256_after": digest_after,
        "same_job_recovered": True,
        "same_capability_still_valid": True,
        "stable_result_identical": True,
        "private_capability_in_receipt": False,
        "pass": True,
    }
    _write_receipt(Path(args.receipt_file), receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)

    start = sub.add_parser("before-restart", help="Create and record one completed durable job")
    start.add_argument("--base-url", required=True)
    start.add_argument("--state-file", required=True, help="PRIVATE file; contains a job bearer capability")
    start.add_argument("--receipt-file", required=True, help="Sanitized JSON receipt safe to archive/share")
    start.add_argument(
        "--question",
        default=(
            "Persistence acceptance test: give one concise source-backed fact about Python's standard library. "
            "Keep the answer short."
        ),
    )
    start.add_argument("--depth-mode", default="QUICK", choices=["QUICK", "DEEP", "MAXIMUM"])
    start.add_argument("--timeout-seconds", type=float, default=600.0)
    start.add_argument("--poll-seconds", type=float, default=2.0)

    verify = sub.add_parser("after-restart", help="Verify the same completed job/result after restart")
    verify.add_argument("--state-file", required=True)
    verify.add_argument("--receipt-file", required=True)
    verify.add_argument("--base-url", default="", help="Optional override; defaults to state file URL")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = _phase1(args) if args.phase == "before-restart" else _phase2(args)
    except AcceptanceError as exc:
        print(f"PERSISTENCE_ACCEPTANCE_FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
