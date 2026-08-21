"""Offline tests for the process-local ₹0 request guard."""
from __future__ import annotations

from types import SimpleNamespace

from utils.request_guard import Limit, SlidingWindowLimiter, client_key, limit_for


def test_sliding_window_blocks_after_limit_and_returns_retry_after():
    limiter = SlidingWindowLimiter()
    limit = Limit(requests=2, window_seconds=60)

    ok1, retry1 = limiter.check("client", "bucket", limit, now=100.0)
    ok2, retry2 = limiter.check("client", "bucket", limit, now=101.0)
    ok3, retry3 = limiter.check("client", "bucket", limit, now=102.0)

    assert ok1 is True and retry1 == 0
    assert ok2 is True and retry2 == 0
    assert ok3 is False and retry3 >= 58


def test_window_expires_and_allows_again():
    limiter = SlidingWindowLimiter()
    limit = Limit(requests=1, window_seconds=10)
    assert limiter.check("c", "b", limit, now=5.0)[0] is True
    assert limiter.check("c", "b", limit, now=6.0)[0] is False
    assert limiter.check("c", "b", limit, now=16.0)[0] is True


def test_get_requests_are_not_limited():
    assert limit_for("GET", "/api/v1/research-jobs") is None


def test_unknown_post_endpoint_is_not_limited():
    assert limit_for("POST", "/health") is None


def test_expensive_post_endpoints_are_guarded():
    for path in (
        "/api/v1/chat",
        "/api/v1/ask",
        "/api/v1/deep-research",
        "/api/v1/research-jobs",
        "/api/v1/upload-document",
        "/api/v1/upload-pdf",
        "/api/v1/ingest-youtube",
        "/api/v1/upload-audio",
        "/api/v1/transcribe-audio",
    ):
        assert limit_for("POST", path) is not None, path


def test_client_key_does_not_trust_forwarded_header_by_default(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    request = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.9"},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    assert client_key(request) == "127.0.0.1"


def test_client_key_can_use_proxy_header_when_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    request = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.9, 10.0.0.1"},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    assert client_key(request) == "203.0.113.9"
