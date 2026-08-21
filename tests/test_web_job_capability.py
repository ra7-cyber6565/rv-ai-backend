"""Static regression for browser project/job capability handling.

No browser/network needed. This intentionally checks the shipped HTML/JS because
backend capability enforcement is useless if the official web client forgets to
send headers or leaks tokens into URLs/persistent browser storage.
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "index.html"


def _text() -> str:
    return WEB.read_text(encoding="utf-8")


def test_web_creates_server_issued_project_session_before_project_work():
    text = _text()
    assert 'API+"/api/v1/session"' in text
    assert 'method:"POST"' in text
    assert "data.project_id" in text
    assert "data.project_access_token" in text
    assert "await ensureSession()" in text


def test_chat_and_job_start_send_private_project_header():
    text = _text()
    assert 'function projectHeaders(){return {"Content-Type":"application/json","X-Project-Token":PROJECT.token};}' in text
    assert 'headers:projectHeaders()' in text
    assert 'project_id:projectId' in text
    assert 'projectPost("/api/v1/chat"' in text
    assert 'projectPost("/api/v1/research-jobs"' in text


def test_stale_project_capability_gets_exactly_one_session_refresh_attempt():
    text = _text()
    start = text.index("async function projectPost")
    end = text.index("async function runChat", start)
    block = text[start:end]

    assert "for(let attempt=0;attempt<2;attempt++)" in block
    assert "out.r.status!==404||attempt===1" in block
    assert "resetProjectSession();" in block
    assert "await ensureSession();" in block
    # Retry is only for project-scoped POST creation paths. Job polling must keep
    # its original per-job capability and must not silently start a new job.
    run_start = text.index("async function runResearch")
    run_end = text.index("function renderResearch", run_start)
    polling = text[run_start:run_end]
    assert "projectPost(" not in polling[polling.index("const pollOpts"):]


def test_reset_project_session_clears_only_in_memory_capability():
    text = _text()
    assert 'function resetProjectSession(){PROJECT.id="";PROJECT.token="";sessionPromise=null;}' in text
    low = text.lower()
    assert "localstorage" not in low
    assert "sessionstorage" not in low


def test_deep_max_client_requires_job_access_token_from_start_response():
    text = _text()
    assert "start.data.job_access_token" in text
    assert "!start.data.job_access_token" in text
    assert 'jobToken=start.data.job_access_token' in text


def test_all_async_polling_uses_private_job_header():
    text = _text()
    assert 'const pollOpts={headers:{"X-Research-Job-Token":jobToken}}' in text

    status_call = 'encodeURIComponent(jobId),pollOpts)'
    progress_call = 'encodeURIComponent(jobId)+"/progress",pollOpts)'
    result_call = 'encodeURIComponent(jobId)+"/result",pollOpts)'
    assert status_call in text
    assert progress_call in text
    assert result_call in text


def test_tokens_are_not_put_in_url_or_persistent_browser_storage():
    text = _text()
    low = text.lower()
    assert "localstorage" not in low
    assert "sessionstorage" not in low
    for marker in (
        "?job_access_token=", "&job_access_token=", "?project_access_token=",
        "&project_access_token=", "?project_token=", "&project_token=",
        "?token=", "&token=",
    ):
        assert marker not in low

    # Function-local job token and in-memory project token must never be appended
    # to request URLs.
    assert not re.search(r"(?:api|research-jobs)[^\n]{0,180}\+\s*jobToken", text)
    assert not re.search(r"(?:api|session|chat)[^\n]{0,180}\+\s*PROJECT\.token", text)


def test_project_token_is_memory_only_not_generated_client_side():
    text = _text()
    assert 'const PROJECT={id:"",token:""}' in text
    assert "PROJECT.id=data.project_id" in text
    assert "PROJECT.token=data.project_access_token" in text
    # Project IDs must be server-issued, not predictable/browser-generated.
    assert 'PROJECT_ID="web-"' not in text
    assert "Math.random().toString(36)" not in text


def test_poll_token_is_function_local_not_global():
    text = _text()
    run_start = text.index("async function runResearch")
    run_end = text.index("function renderResearch", run_start)
    run_body = text[run_start:run_end]
    before = text[:run_start]

    assert 'let jobId="",jobToken=""' in run_body
    assert "jobToken=" not in before


def test_failed_quick_chat_recovers_through_async_quick_job():
    text = _text()
    chat_start = text.index("async function runChat")
    chat_end = text.index("function progressPanel", chat_start)
    chat = text[chat_start:chat_end]
    research_start = text.index("async function runResearch")
    research_end = text.index("function renderResearch", research_start)
    research = text[research_start:research_end]

    assert "data.start_research_job===true" in chat
    assert 'runResearch(message,el,"QUICK")' in chat
    assert "requestedMode=mode" in research
    assert "depth_mode:requestedMode" in research
    assert "Abhi server se baat nahi ho paayi" not in text


def test_web_failure_message_is_actionable_and_preserves_question():
    text = _text()
    assert "function clientFailure(" in text
    assert "code===429" in text
    assert "code===503" in text
    assert "restoreQuestion(message)" in text
    assert "restoreQuestion(question)" in text
