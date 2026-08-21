"""Offline tests for the process-local ₹0 request guard."""
from __future__ import annotations

from types import SimpleNamespace

from utils.request_guard import (
    Limit,
    SlidingWindowLimiter,
    bucket_for,
    client_key,
    limit_for,
)


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


def test_bucket_table_is_bounded_and_fails_closed_for_new_clients():
    limiter = SlidingWindowLimiter(max_buckets=100, cleanup_interval_seconds=999999)
    limit = Limit(requests=2, window_seconds=3600)
    for i in range(100):
        assert limiter.check(f"client-{i}", "research", limit, now=100.0)[0] is True
    allowed, retry = limiter.check("client-over-cap", "research", limit, now=101.0)
    assert allowed is False
    assert retry > 0
    stats = limiter.stats()
    assert stats["active_buckets"] == 100
    assert stats["capacity_rejections"] == 1


def test_global_cleanup_releases_expired_idle_buckets():
    limiter = SlidingWindowLimiter(max_buckets=100, cleanup_interval_seconds=1)
    limit = Limit(requests=1, window_seconds=10)
    assert limiter.check("old", "research", limit, now=0.0)[0] is True
    assert limiter.check("new", "research", limit, now=4000.0)[0] is True
    assert limiter.stats()["active_buckets"] == 1


def test_stats_never_expose_client_keys():
    limiter = SlidingWindowLimiter(max_buckets=100)
    limiter.check("203.0.113.99", "bucket", Limit(1, 60), now=1.0)
    stats = limiter.stats()
    assert "203.0.113.99" not in repr(stats)
    assert set(stats) == {"active_buckets", "max_buckets", "capacity_rejections"}


def test_collection_get_is_not_limited_but_job_polling_is():
    assert limit_for("GET", "/api/v1/research-jobs") is None
    for path in (
        "/api/v1/research-jobs/abc123",
        "/api/v1/research-jobs/abc123/progress",
        "/api/v1/research-jobs/abc123/result",
    ):
        limit = limit_for("GET", path)
        assert limit is not None
        assert limit.window_seconds == 60


def test_dynamic_job_urls_share_one_normalized_bucket():
    paths = (
        "/api/v1/research-jobs/job-one",
        "/api/v1/research-jobs/job-two/progress",
        "/api/v1/research-jobs/job-three/result",
    )
    buckets = {bucket_for("GET", path) for path in paths}
    assert buckets == {"/api/v1/research-jobs/{job}/poll"}


def test_non_job_paths_keep_original_bucket():
    assert bucket_for("POST", "/api/v1/chat") == "/api/v1/chat"
    assert bucket_for("GET", "/health") == "/health"


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
