"""Static privacy regression for capability-bearing API response headers."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_api_v1_responses_are_explicitly_no_store():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'startswith("/api/v1/")' in text
    assert 'response.headers["Cache-Control"] = "no-store, max-age=0"' in text
    assert 'response.headers["Pragma"] = "no-cache"' in text


def test_security_headers_apply_to_normal_and_rate_limited_responses():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '"X-Content-Type-Options", "nosniff"' in text
    assert '"Referrer-Policy", "no-referrer"' in text
    assert '"X-Frame-Options", "DENY"' in text
    assert "return _harden_response(response, request.url.path)" in text
    # There must be one hardened return for the 429 branch and another after
    # normal call_next processing.
    assert text.count("return _harden_response(response, request.url.path)") >= 2


def test_session_and_job_tokens_are_never_encoded_into_cacheable_urls():
    web = (ROOT / "web" / "index.html").read_text(encoding="utf-8").lower()
    for marker in (
        "?project_access_token=", "&project_access_token=",
        "?job_access_token=", "&job_access_token=",
        "?project_token=", "&project_token=",
    ):
        assert marker not in web
