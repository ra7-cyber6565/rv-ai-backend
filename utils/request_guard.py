"""Small in-memory abuse/rate guard for the ₹0 backend.

Public endpoints that trigger model calls, long research or large uploads can
otherwise burn the entire free quota. This module uses only stdlib, stores no
persistent IP history and does not depend on Redis/paid infrastructure.

It is intentionally conservative: process restart resets counters, which is fine
for a single-instance free deployment. A future multi-instance deployment should
replace this with a shared free/self-hosted limiter rather than pretending these
counters are global.
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


DEFAULT_LIMITS: dict[str, Limit] = {
    "/api/v1/chat": Limit(_int_env("RATE_CHAT_PER_MINUTE", 30, 1, 300), 60),
    "/api/v1/deep-research": Limit(_int_env("RATE_SYNC_RESEARCH_PER_HOUR", 4, 1, 60), 3600),
    "/api/v1/research-jobs": Limit(_int_env("RATE_RESEARCH_JOBS_PER_HOUR", 6, 1, 60), 3600),
    "/api/v1/upload-document": Limit(_int_env("RATE_UPLOADS_PER_HOUR", 20, 1, 200), 3600),
    "/api/v1/upload-pdf": Limit(_int_env("RATE_UPLOADS_PER_HOUR", 20, 1, 200), 3600),
    "/api/v1/upload-audio": Limit(_int_env("RATE_AUDIO_UPLOADS_PER_HOUR", 8, 1, 100), 3600),
    "/api/v1/transcribe-audio": Limit(_int_env("RATE_AUDIO_UPLOADS_PER_HOUR", 8, 1, 100), 3600),
}


class SlidingWindowLimiter:
    def __init__(self):
        self._events: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, bucket: str, limit: Limit, *, now: float | None = None) -> tuple[bool, int]:
        current = time.time() if now is None else float(now)
        cutoff = current - limit.window_seconds
        index = (key, bucket)
        with self._lock:
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
