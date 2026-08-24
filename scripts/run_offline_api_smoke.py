"""Exercise the shipped FastAPI path without network, models, or user secrets.

This is intentionally a process-level smoke gate instead of another isolated
unit test.  It imports the real ``main.app`` after forcing a temporary runtime
root, creates a private anonymous session, uses deterministic QUICK chat, then
submits and retrieves one protected MARATHON job through the real HTTP routes.

The research worker is replaced only at the expensive discovery/model boundary
with a deterministic result.  Everything around it remains production code:
middleware, capability checks, async runner, durable result storage, progress
snapshot, final quality enforcement, response headers and route schemas.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable


PASS = 0
FAIL = 0


def check(name: str, condition: object, extra: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" — {extra}" if extra else ""))


def _offline_environment(root: str) -> None:
    """Fail closed to a fresh local root and blank every hosted-provider key."""
    os.environ.update(
        {
            "INFINITY_DATA_ROOT": root,
            "INFINITY_OFFLINE_TEST": "true",
            "ZERO_COST_ONLY": "true",
            "RATE_LIMIT_ENABLED": "false",
            "CLOUD_ARCHIVE_PROVIDER": "none",
            "GOOGLE_DRIVE_RCLONE_REMOTE": "",
            "GEMINI_API_KEY": "",
            "GEMINI_API_KEY_BACKUP": "",
            "GEMINI_API_KEY_FALLBACK": "",
            "GEMINI_API_KEYS": "",
            "GEMINI_API_KEY_LIST": "",
            "GEMINI_BACKUP_KEYS": "",
            "GEMINI_ZERO_COST_CONFIRMED": "false",
            "GROQ_API_KEY": "",
            "GROQ_ZERO_COST_CONFIRMED": "false",
            "OPENROUTER_API_KEY": "",
            "OPENROUTER_MODEL": "openrouter/free",
            "OLLAMA_ENABLED": "false",
            "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
            "RESEARCH_JOB_WORKERS": "1",
            "RESEARCH_JOB_HISTORY": "5",
            "RESEARCH_JOB_PROCESS_LOCK": "true",
        }
    )
    for index in range(2, 10):
        os.environ[f"GEMINI_API_KEY_{index}"] = ""
        os.environ[f"GEMINI_API_KEY{index}"] = ""


def _wait_for_job(client: Any, url: str, headers: dict[str, str], timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        response = client.get(url, headers=headers)
        if response.status_code != 200:
            raise AssertionError(f"job status endpoint returned {response.status_code}")
        last = response.json()
        if last.get("status") in {"completed", "failed", "interrupted"}:
            return last
        time.sleep(0.02)
    raise AssertionError(f"offline job timed out; last status={last.get('status')}")


def _fake_research(**kwargs: Any) -> dict:
    """Deterministic worker output; final API boundary must downgrade overclaims."""
    return {
        "answer": (
            "## Seedha jawab\n"
            "Offline end-to-end smoke result.\n\n"
            "Evidence ka level: VERIFIED\n\n"
            "## Sources\n"
            "Is smoke run mein external source call jaan-boojh kar nahi hui."
        ),
        "status": "COMPLETE",
        "evidence_level": "VERIFIED",
        "sources": [],
        "citations": [],
        "hypotheses": [],
        "coverage": {"mode": kwargs.get("depth_mode"), "offline_smoke": True},
    }


def _run_with_client(client: Any, runtime_root: str, manager: Any) -> None:
    # Import/startup happened with every provider credential blank.  Inject fake
    # canary values only for this read-only health request so the smoke test
    # proves that public diagnostics expose readiness metadata, never raw
    # credential values.  Restore the blank values before any chat/job work.
    credential_canaries = {
        "GEMINI_API_KEY": "rv-smoke-gemini-credential-must-not-leak",
        "GROQ_API_KEY": "rv-smoke-groq-credential-must-not-leak",
        "OPENROUTER_API_KEY": "rv-smoke-openrouter-credential-must-not-leak",
        "GOOGLE_DRIVE_RCLONE_REMOTE": "rv-smoke-archive-credential-must-not-leak",
    }
    previous_values = {name: os.environ.get(name) for name in credential_canaries}
    os.environ.update(credential_canaries)
    try:
        health = client.get("/health")
    finally:
        for name, value in previous_values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    check("real /health route responds", health.status_code == 200, str(health.status_code))
    health_json = health.json()
    check("temporary runtime storage is available", health_json.get("storage", {}).get("available") is True)
    check(
        "project capability layer is ready",
        health_json.get("project_isolation", {}).get("project_capability_tokens_ready") is True,
    )
    health_text = health.text.lower()
    check("public health hides absolute runtime root", runtime_root.lower() not in health_text)
    check(
        "public health hides credential values",
        all(value.lower() not in health_text for value in credential_canaries.values()),
    )

    website = client.get("/")
    check(
        "shipped web client loads",
        website.status_code == 200 and "Infinity Research AI" in website.text,
    )
    check("web client gets CSP", bool(website.headers.get("content-security-policy")))
    check("web client is not cached", "no-store" in website.headers.get("cache-control", ""))

    session = client.post("/api/v1/session")
    check("anonymous private session is created", session.status_code == 201, str(session.status_code))
    session_json = session.json()
    project_id = str(session_json.get("project_id") or "")
    project_token = str(session_json.get("project_access_token") or "")
    check("project id is random-shaped", project_id.startswith("p_") and len(project_id) >= 22)
    check("project token is present but distinct", len(project_token) >= 32 and project_token != project_id)
    check("private session response is no-store", "no-store" in session.headers.get("cache-control", ""))
    check("private session response is noindex", "noindex" in session.headers.get("x-robots-tag", ""))

    chat_payload = {"message": "hello bhai", "project_id": project_id}
    missing_chat = client.post("/api/v1/chat", json=chat_payload)
    check("chat without project capability is hidden as 404", missing_chat.status_code == 404)

    project_headers = {"X-Project-Token": project_token}
    chat = client.post("/api/v1/chat", json=chat_payload, headers=project_headers)
    chat_json = chat.json()
    check("authorized QUICK chat succeeds", chat.status_code == 200 and chat_json.get("ok") is True)
    check("greeting spends zero model calls", chat_json.get("api_attempts") == 0)
    check("QUICK response is useful", bool(str(chat_json.get("answer") or "").strip()))
    check("QUICK response does not expose capability", project_token not in chat.text)

    modes = client.get("/api/v1/depth-modes")
    modes_json = modes.json()
    marathon = modes_json.get("MARATHON", {})
    check("MARATHON is exposed by the real API", modes.status_code == 200 and bool(marathon))
    check("MARATHON source rail is 40", marathon.get("max_sources") == 40)
    check("MARATHON full-text rail is 16", marathon.get("max_fulltext") == 16)
    check("MARATHON runs all five bounded rounds",
          marathon.get("max_rounds") == 5 and marathon.get("require_all_rounds") is True)
    check("MARATHON exposes a 90% process target, not a truth probability",
          marathon.get("research_process_target_percent") == 90)

    job_payload = {
        "question": "Offline end-to-end API smoke question",
        "project_id": project_id,
        "depth_mode": "MARATHON",
    }
    missing_job = client.post("/api/v1/research-jobs", json=job_payload)
    check("job creation without project capability is hidden as 404", missing_job.status_code == 404)

    invalid_payload = dict(job_payload)
    invalid_payload["depth_mode"] = "UNBOUNDED"
    invalid_job = client.post("/api/v1/research-jobs", json=invalid_payload, headers=project_headers)
    check("unbounded/unknown depth mode is rejected", invalid_job.status_code == 400)

    original_research: Callable[..., Any] = manager.research
    manager.research = _fake_research
    try:
        started = client.post("/api/v1/research-jobs", json=job_payload, headers=project_headers)
        check("authorized MARATHON job is accepted", started.status_code == 202, str(started.status_code))
        started_json = started.json()
        job_id = str(started_json.get("job_id") or "")
        job_token = str(started_json.get("job_access_token") or "")
        status_url = str(started_json.get("status_url") or "")
        result_url = str(started_json.get("result_url") or "")
        progress_url = str(started_json.get("progress_url") or "")
        check("job id and capability are distinct", bool(job_id) and len(job_token) >= 32 and job_token != job_id)
        check("job capability is not placed in URLs", all(job_token not in url for url in (status_url, result_url, progress_url)))

        hidden = client.get(status_url)
        wrong = client.get(status_url, headers={"X-Research-Job-Token": "wrong"})
        check("missing job capability is hidden as 404", hidden.status_code == 404)
        check("wrong job capability is indistinguishable", wrong.status_code == 404)

        job_headers = {"X-Research-Job-Token": job_token}
        completed = _wait_for_job(client, status_url, job_headers)
        check("background worker completes", completed.get("status") == "completed")
        check("durable result was saved", completed.get("result_durable") is True)

        progress = client.get(progress_url, headers=job_headers)
        check("protected progress route responds", progress.status_code == 200)
        check("progress route retains job status", progress.json().get("job", {}).get("status") == "completed")

        result = client.get(result_url, headers=job_headers)
        result_json = result.json()
        check("protected final result responds", result.status_code == 200)
        check("final quality gate ran", result_json.get("quality_enforced") is True)
        check(
            "unsupported VERIFIED claim is blocked",
            result_json.get("quality_gate", {}).get("verified_allowed") is False
            and "VERIFIED" not in str(result_json.get("evidence_level") or "").upper(),
        )
        check("unsupported COMPLETE status is downgraded", result_json.get("status") == "PARTIAL")
        check("completed result keeps bounded progress snapshot", isinstance(result_json.get("research_progress"), dict))
        check("result does not expose project capability", project_token not in result.text)
        check("result does not expose job capability", job_token not in result.text)
        check("private result is no-store", "no-store" in result.headers.get("cache-control", ""))
    finally:
        manager.research = original_research


def main() -> int:
    global PASS, FAIL
    PASS = 0
    FAIL = 0
    print("OFFLINE API SMOKE — real FastAPI/session/chat/job/result path (₹0, no network)")

    with tempfile.TemporaryDirectory(prefix="rv_api_smoke_") as runtime_root:
        _offline_environment(runtime_root)
        # Imports happen only after environment isolation so module-level storage,
        # capability signers and the durable job runner all use the temp root.
        from fastapi.testclient import TestClient
        from main import app
        from research_engine.agent_manager import manager
        from utils.research_jobs import runner

        try:
            with TestClient(app) as client:
                _run_with_client(client, str(Path(runtime_root).resolve()), manager)
        finally:
            runner.close(wait=True)

    print(f"\nOFFLINE API SMOKE: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
