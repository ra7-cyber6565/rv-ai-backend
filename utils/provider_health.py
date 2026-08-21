"""Small process-local circuit breaker for free reasoning providers.

A single research run already remembers providers that returned quota/auth/model
errors. The missing piece was *cross-request* memory: after a free provider had
clearly failed, every new chat/research request immediately hit the same dead
provider again before falling back. That wastes latency and can burn scarce free
rate-limit capacity.

This registry remembers only coarse provider names + normalized failure kinds.
No API key, prompt, response body, URL or user content is stored.

The breaker is intentionally temporary and fail-open after its cooldown expires:
free-tier limits can recover, deployments can be fixed, and a stale in-memory
failure must never permanently disable a provider. The built-in deterministic
evidence fallback remains outside this registry and is always available.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional


def _bounded_seconds(name: str, default: int, *, low: int = 1, high: int = 86400) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


@dataclass
class ProviderHealth:
    provider: str
    reason: str = ""
    failures: int = 0
    blocked_until: float = 0.0
    last_failure: float = 0.0
    last_success: float = 0.0

    def public(self, now: float) -> dict:
        remaining = max(0, int(round(self.blocked_until - now)))
        return {
            "provider": self.provider,
            "reason": self.reason,
            "failures": self.failures,
            "cooldown_active": remaining > 0,
            "cooldown_seconds_remaining": remaining,
            "last_failure_epoch": int(self.last_failure) if self.last_failure else 0,
            "last_success_epoch": int(self.last_success) if self.last_success else 0,
        }


class ProviderHealthRegistry:
    """Thread-safe bounded provider health memory.

    Only hard/temporary provider availability failures create cooldowns. A normal
    empty response or a user/content-specific failure should not globally block a
    provider for unrelated users/questions.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        max_entries: int = 64,
    ) -> None:
        self._clock = clock
        self._max_entries = max(8, min(256, int(max_entries)))
        self._lock = threading.RLock()
        self._states: Dict[str, ProviderHealth] = {}

    @staticmethod
    def _key(provider: object) -> str:
        return str(provider or "").strip().lower()

    @staticmethod
    def _base_ttl(kind: str) -> int:
        value = str(kind or "").strip().lower()
        if value in {"daily_quota", "daily-limit", "daily_limit"}:
            return _bounded_seconds("PROVIDER_HEALTH_DAILY_QUOTA_SECONDS", 1800)
        if value in {"quota", "rate_limit", "rate-limit", "resource_exhausted"}:
            return _bounded_seconds("PROVIDER_HEALTH_RATE_LIMIT_SECONDS", 180)
        if value in {"auth", "permission", "forbidden", "invalid_key"}:
            return _bounded_seconds("PROVIDER_HEALTH_AUTH_SECONDS", 1800)
        if value in {"model_unavailable", "model_not_found", "local_model_unavailable"}:
            return _bounded_seconds("PROVIDER_HEALTH_MODEL_SECONDS", 900)
        if value in {"temporary", "server", "network", "local_unavailable", "local_error"}:
            return _bounded_seconds("PROVIDER_HEALTH_TEMPORARY_SECONDS", 45)
        return 0

    def _prune_locked(self, now: float) -> None:
        # Remove old recovered/expired entries first.
        stale = [
            key for key, state in self._states.items()
            if state.blocked_until <= now and (now - max(state.last_failure, state.last_success, 0.0)) > 3600
        ]
        for key in stale:
            self._states.pop(key, None)
        if len(self._states) <= self._max_entries:
            return
        ordered = sorted(
            self._states.items(),
            key=lambda item: max(item[1].last_failure, item[1].last_success, 0.0),
        )
        for key, _ in ordered[: max(0, len(self._states) - self._max_entries)]:
            self._states.pop(key, None)

    def record_failure(self, provider: object, kind: object) -> None:
        key = self._key(provider)
        if not key:
            return
        normalized = str(kind or "").strip().lower() or "unavailable"
        ttl = self._base_ttl(normalized)
        if ttl <= 0:
            return
        now = self._clock()
        with self._lock:
            state = self._states.get(key) or ProviderHealth(provider=key)
            state.failures += 1
            state.reason = normalized
            state.last_failure = now
            # Repeated failures back off a little more, but stay bounded. This is
            # latency protection, not a permanent ban.
            multiplier = min(4, 1 << max(0, min(2, state.failures - 1)))
            state.blocked_until = max(state.blocked_until, now + min(86400, ttl * multiplier))
            self._states[key] = state
            self._prune_locked(now)

    def record_success(self, provider: object) -> None:
        key = self._key(provider)
        if not key:
            return
        now = self._clock()
        with self._lock:
            state = self._states.get(key) or ProviderHealth(provider=key)
            state.reason = ""
            state.failures = 0
            state.blocked_until = 0.0
            state.last_success = now
            self._states[key] = state
            self._prune_locked(now)

    def blocked(self, provider: object) -> tuple[bool, str, int]:
        key = self._key(provider)
        if not key:
            return False, "", 0
        now = self._clock()
        with self._lock:
            state = self._states.get(key)
            if state is None:
                return False, "", 0
            if state.blocked_until <= now:
                state.blocked_until = 0.0
                return False, state.reason, 0
            remaining = max(1, int(round(state.blocked_until - now)))
            return True, state.reason, remaining

    def snapshot(self) -> dict:
        now = self._clock()
        with self._lock:
            self._prune_locked(now)
            return {
                key: state.public(now)
                for key, state in sorted(self._states.items())
                if state.blocked_until > now or state.last_success or state.last_failure
            }

    def clear(self, provider: Optional[str] = None) -> None:
        with self._lock:
            if provider is None:
                self._states.clear()
            else:
                self._states.pop(self._key(provider), None)


provider_health = ProviderHealthRegistry()


__all__ = ["ProviderHealth", "ProviderHealthRegistry", "provider_health"]
