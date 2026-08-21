"""Small in-memory abuse/rate guard for the ₹0 backend.

Public endpoints that trigger model calls, long research or large uploads can
otherwise burn the entire free quota. This module uses only stdlib, stores no
persistent IP history and does not depend on Redis/paid infrastructure.

It is intentionally conservative: process restart resets counters, which is fine
for a single-instance free deployment. A future multi-instance deployment should
replace this with a shared free/self-hosted limiter rather than pretending these
counters are global.

The bucket table is bounded so a flood of unique spoofed/source addresses cannot
turn the limiter itself into an unbounded-memory denial of service.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Tuple


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class Limit:
    requests: int
    window_seconds: int


_QUICK_PER_MINUTE = _int_env("RATE_QUICK_AI_PER_MINUTE", 12, 1, 120)
_UPLOADS_PER_HOUR = _int_env("RATE_UPLOADS_PER_HOUR", 20, 1, 200)
_AUDIO_PER_HOUR = _int_env("RATE_AUDIO_UPLOADS_PER_HOUR", 8, 1, 100)

DEFAULT_LIMITS: dict[str, Limit] = {
    # endpoints that can consume model/search quota
    "/api/v1/chat": Limit(_int_env("RATE_CHAT_PER_MINUTE", 30, 1, 300), 60),
    "/api/v1/ask": Limit(_QUICK_PER_MINUTE, 60),
    "/api/v1/deep-research": Limit(_int_env("RATE_SYNC_RESEARCH_PER_HOUR", 4, 1, 60), 3600),
    "/api/v1/research-jobs": Limit(_int_env("RATE_RESEARCH_JOBS_PER_HOUR", 6, 1, 60), 3600),

    # ingestion/processing endpoints that can use CPU, disk or local model time
    "/api/v1/upload-document": Limit(_UPLOADS_PER_HOUR, 3600),
    "/api/v1/upload-pdf": Limit(_UPLOADS_PER_HOUR, 3600),
    "/api/v1/ingest-youtube": Limit(_UPLOADS_PER_HOUR, 3600),
    "/api/v1/upload-audio": Limit(_AUDIO_PER_HOUR, 3600),
    "/api/v1/transcribe-audio": Limit(_AUDIO_PER_HOUR, 3600),
}


class SlidingWindowLimiter:
    def __init__(self, *, max_buckets: int | None = None, cleanup_interval_seconds: int = 60):
        self._events: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._max_buckets = max(100, int(max_buckets or _int_env("RATE_LIMIT_MAX_BUCKETS", 10_000, 100, 100_000)))
        self._cleanup_interval = max(1, int(cleanup_interval_seconds))
        self._last_cleanup = 0.0
        self._capacity_rejections = 0

    def _cleanup_locked(self, current: float) -> None:
        """Drop expired/empty buckets without retaining client identifiers forever."""
        # Every route has a window <= 1 hour in the current policy. Per-bucket
        # exact expiry is handled on normal access; this global sweep removes
        # completely idle buckets after the longest configured window.
        longest_window = max((limit.window_seconds for limit in DEFAULT_LIMITS.values()), default=3600)
        cutoff = current - longest_window
        for index, queue in list(self._events.items()):
            while queue and queue[0] <= cutoff:
                queue.popleft()
            if not queue:
                self._events.pop(index, None)
        self._last_cleanup = current

    def check(self, key: str, bucket: str, limit: Limit, *, now: float | None = None) -> tuple[bool, int]:
        current = time.time() if now is None else float(now)
        cutoff = current - limit.window_seconds
        index = (key, bucket)
        with self._lock:
            if (
                current - self._last_cleanup >= self._cleanup_interval
                or len(self._events) >= self._max_buckets
            ):
                self._cleanup_locked(current)

            # Fail closed for a brand-new bucket if the bounded table is still
            # full. Existing clients keep their normal sliding-window behavior.
            if index not in self._events and len(self._events) >= self._max_buckets:
                self._capacity_rejections += 1
                return False, max(1, min(60, limit.window_seconds))

            queue = self._events[index]
            while queue and queue[0] <= cutoff:
                queue.popleft()
            if len(queue) >= limit.requests:
                retry_after = max(1, int(queue[0] + limit.window_seconds - current) + 1)
                return False, retry_after
            queue.append(current)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._last_cleanup = 0.0
            self._capacity_rejections = 0

    def stats(self) -> dict[str, int]:
        """Safe aggregate metrics only; never expose client identifiers."""
        with self._lock:
            return {
                "active_buckets": len(self._events),
                "max_buckets": self._max_buckets,
                "capacity_rejections": self._capacity_rejections,
            }


limiter = SlidingWindowLimiter()


def client_key(request) -> str:
    """Return client identifier without persisting it anywhere.

    X-Forwarded-For is trusted only when explicitly enabled, because otherwise a
    caller can spoof that header and bypass the limiter.
    """
    if _bool_env("TRUST_PROXY_HEADERS", False):
        forwarded = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded[:128]
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return str(host or "unknown")[:128]


def limit_for(method: str, path: str) -> Limit | None:
    if method.upper() != "POST":
        return None
    return DEFAULT_LIMITS.get(path)


def enabled() -> bool:
    return _bool_env("RATE_LIMIT_ENABLED", True)
