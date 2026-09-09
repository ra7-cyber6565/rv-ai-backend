"""Bounded specialist-handoff recovery for COMPANY research.

This module is intentionally conservative: it retries a failed specialist handoff only
when the callable explicitly reports a retryable handoff failure. It never fabricates a
specialist result and never upgrades PARTIAL/failed work to complete without a real
successful handoff payload.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional


_RETRYABLE_CODES = {
    "specialist_handoff",
    "specialist_handoff_failed",
    "handoff_failed",
    "handoff_timeout",
    "handoff_transport_error",
}


@dataclass(frozen=True)
class HandoffRecovery:
    payload: Any
    attempts: int
    recovered: bool
    retryable_failure: bool


def _status_code(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("code", "error_code", "failure_code", "reason", "status"):
            raw = value.get(key)
            if raw:
                return str(raw).strip().lower()
    for key in ("code", "error_code", "failure_code", "reason", "status"):
        raw = getattr(value, key, None)
        if raw:
            return str(raw).strip().lower()
    return ""


def is_retryable_specialist_handoff_failure(value: Any) -> bool:
    """Return True only for explicit handoff-level failures.

    A generic model/validation/quality failure is deliberately not retryable here;
    retrying those could hide substantive specialist disagreement or missing evidence.
    """
    code = _status_code(value)
    return code in _RETRYABLE_CODES


def recover_specialist_handoff(
    invoke: Callable[[], Any],
    *,
    max_attempts: int = 2,
    success_predicate: Optional[Callable[[Any], bool]] = None,
) -> HandoffRecovery:
    """Invoke a specialist handoff with at most one bounded retry by default.

    Recovery is declared only when the second real invocation satisfies
    ``success_predicate`` (or, by default, is not another explicit handoff failure).
    Exceptions are returned as failure metadata and are not converted into success.
    """
    attempts = max(1, min(int(max_attempts or 1), 2))
    last: Any = None
    retryable = False

    def _ok(value: Any) -> bool:
        if success_predicate is not None:
            return bool(success_predicate(value))
        return not is_retryable_specialist_handoff_failure(value)

    for attempt in range(1, attempts + 1):
        try:
            last = invoke()
        except Exception as exc:  # preserve failure; never manufacture completion
            last = {
                "status": "handoff_transport_error",
                "error_type": type(exc).__name__,
                "message": str(exc),
            }

        if _ok(last):
            return HandoffRecovery(
                payload=last,
                attempts=attempt,
                recovered=attempt > 1,
                retryable_failure=False,
            )

        retryable = is_retryable_specialist_handoff_failure(last)
        if not retryable:
            break

    return HandoffRecovery(
        payload=last,
        attempts=attempts,
        recovered=False,
        retryable_failure=retryable,
    )
