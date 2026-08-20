"""Hard guardrails for the project's zero-cost runtime policy.

The app owner requires that normal runtime must not silently use paid AI APIs.
This module is intentionally small and deterministic: if zero-cost mode is on,
known paid-provider credentials cause startup to fail instead of risking a bill.

This is not a billing oracle. Free-tier services can still change terms, so
provider/model routing must separately restrict itself to explicitly free models.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


TRUTHY = {"1", "true", "yes", "on"}

# Direct vendor API keys that can incur usage charges. Keep this list narrow to
# avoid blocking research/data services that may have genuine free quotas.
FORBIDDEN_IN_ZERO_COST_MODE = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)


@dataclass(frozen=True)
class ZeroCostStatus:
    enabled: bool
    blocked_keys: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.blocked_keys


def zero_cost_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    raw = str(source.get("ZERO_COST_ONLY", "true")).strip().lower()
    return raw in TRUTHY


def inspect_zero_cost_config(env: Mapping[str, str] | None = None) -> ZeroCostStatus:
    source = env if env is not None else os.environ
    enabled = zero_cost_enabled(source)
    if not enabled:
        return ZeroCostStatus(enabled=False, blocked_keys=())

    blocked = tuple(
        key for key in FORBIDDEN_IN_ZERO_COST_MODE
        if str(source.get(key, "")).strip()
    )
    return ZeroCostStatus(enabled=True, blocked_keys=blocked)


def enforce_zero_cost_config(env: Mapping[str, str] | None = None) -> ZeroCostStatus:
    """Fail closed when a known paid-provider credential is configured."""
    status = inspect_zero_cost_config(env)
    if status.blocked_keys:
        joined = ", ".join(status.blocked_keys)
        raise RuntimeError(
            "ZERO_COST_ONLY is enabled, but paid-provider credential(s) are set: "
            f"{joined}. Remove them or explicitly disable zero-cost mode."
        )
    return status
