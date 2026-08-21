"""Static regression for browser async-research capability handling.

No browser/network needed. This intentionally checks the shipped HTML/JS because
backend capability enforcement is useless if the official web client forgets to
send the header or leaks the token into a URL/persistent browser storage.
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "index.html"


def _text() -> str:
    return WEB.read_text(encoding="utf-8")


def test_deep_max_client_requires_job_access_token_from_start_response():
    text = _text()
    assert "start.data.job_access_token" in text
    assert "!start.data.job_access_token" in text
    assert 'jobToken=start.data.job_access_token' in text


def test_all_async_polling_uses_private_header():
    text = _text()
    assert 'const pollOpts={headers:{"X-Research-Job-Token":jobToken}}' in text

    status_call = 'encodeURIComponent(jobId),pollOpts)'
    progress_call = 'encodeURIComponent(jobId)+"/progress",pollOpts)'
    result_call = 'encodeURIComponent(jobId)+"/result",pollOpts)'
    assert status_call in text
    assert progress_call in text
    assert result_call in text


def test_job_token_is_not_put_in_url_or_persistent_browser_storage():
    text = _text()
    low = text.lower()
    assert "localstorage" not in low
    assert "sessionstorage" not in low
    assert "?job_access_token=" not in low
    assert "&job_access_token=" not in low
    assert "?token=" not in low
    assert "&token=" not in low

    # Function-local token should exist, but URL concatenation with jobToken must
    # not. This catches a future shortcut such as `... + '?token=' + jobToken`.
    assert not re.search(r"(?:api|research-jobs)[^\n]{0,180}\+\s*jobToken", text)


def test_poll_token_is_function_local_not_global():
    text = _text()
    run_start = text.index("async function runResearch")
    run_end = text.index("function renderResearch", run_start)
    run_body = text[run_start:run_end]
    before = text[:run_start]

    assert 'let jobId="",jobToken=""' in run_body
    assert "jobToken=" not in before
