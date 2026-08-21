"""Hard guardrails for the project's zero-cost runtime policy.

The app owner requires that normal runtime must not silently use paid AI APIs.
Known paid-provider credentials are blocked outright. Gemini is different: the
same API key can belong to a project with a free/no-billing setup or to a
billing-enabled project. Code cannot reliably query that billing state from the
generative API, so ZERO_COST_ONLY requires an explicit owner confirmation before
a Gemini key is allowed at all.

This is still not a billing oracle. Provider/model routing and request budgets
must separately stay conservative, and the confirmation must only be set after
checking that the Google project has no paid billing/spend path enabled.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


TRUTHY = {"1", "true", "yes", "on"}

FORBIDDEN_IN_ZERO_COST_MODE = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)

# Synthetic guard name shown in startup errors. This is not a secret/env key;
# it explains exactly what must be confirmed before Gemini can run.
_GEMINI_UNCONFIRMED = "GEMINI_API_KEY (GEMINI_ZERO_COST_CONFIRMED missing/false)"


@dataclass(frozen=True)
class ZeroCostStatus:
    enabled: bool
    blocked_keys: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.blocked_keys


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in TRUTHY


def zero_cost_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    raw = str(source.get("ZERO_COST_ONLY", "true")).strip().lower()
    return raw in TRUTHY


def inspect_zero_cost_config(env: Mapping[str, str] | None = None) -> ZeroCostStatus:
    source = env if env is not None else os.environ
    enabled = zero_cost_enabled(source)
    if not enabled:
        return ZeroCostStatus(enabled=False, blocked_keys=())

    blocked = [
        key for key in FORBIDDEN_IN_ZERO_COST_MODE
        if str(source.get(key, "")).strip()
    ]

    gemini_key = str(source.get("GEMINI_API_KEY", "")).strip()
    if gemini_key and not _truthy(source.get("GEMINI_ZERO_COST_CONFIRMED", "")):
        blocked.append(_GEMINI_UNCONFIRMED)

    return ZeroCostStatus(enabled=True, blocked_keys=tuple(blocked))


def enforce_zero_cost_config(env: Mapping[str, str] | None = None) -> ZeroCostStatus:
    """Fail closed when runtime configuration could create a paid AI path."""
    status = inspect_zero_cost_config(env)
    if status.blocked_keys:
        joined = ", ".join(status.blocked_keys)
        extra = ""
        if _GEMINI_UNCONFIRMED in status.blocked_keys:
            extra = (
                " For Gemini, set GEMINI_ZERO_COST_CONFIRMED=true only after you "
                "have verified that the Google project/key has no paid billing/spend "
                "path enabled; otherwise leave Gemini disabled."
            )
        raise RuntimeError(
            "ZERO_COST_ONLY is enabled, but unsafe/unconfirmed AI credential "
            f"configuration was found: {joined}.{extra}"
        )
    return status
