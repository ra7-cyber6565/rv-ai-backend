"""Hard guardrails for the project's zero-cost runtime policy.

The app owner requires that normal runtime must not silently use paid AI APIs.
Known paid-provider credentials are blocked outright. Gemini and Groq keys can
belong to free or billing-enabled projects/accounts, so ZERO_COST_ONLY requires
an explicit owner confirmation before either can be used. OpenRouter is allowed
only through its explicit free router / ``:free`` model variants. Local Ollama
is allowed only on localhost so a remote paid inference endpoint cannot be
silently disguised as "Ollama".

This is still not a billing oracle. Provider/model routing and request budgets
must separately stay conservative, and confirmations must only be set after the
corresponding account/project is verified to have no paid spend path.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse


TRUTHY = {"1", "true", "yes", "on"}

FORBIDDEN_IN_ZERO_COST_MODE = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)

_GEMINI_UNCONFIRMED = "Gemini credential(s) present (GEMINI_ZERO_COST_CONFIRMED missing/false)"
_GROQ_UNCONFIRMED = "GROQ_API_KEY (GROQ_ZERO_COST_CONFIRMED missing/false)"
_OPENROUTER_NONFREE = "OPENROUTER_API_KEY (OPENROUTER_MODEL is not free-only)"
_REMOTE_OLLAMA = "OLLAMA_BASE_URL (ZERO_COST_ONLY permits localhost only)"

# Keep this list aligned with research_engine.key_pool without importing the
# research package at startup. Importing research_engine here would make the
# safety guard depend on heavy runtime modules and can create import cycles.
_GEMINI_SINGLE_VARS = (
    "GEMINI_API_KEY",
    "GEMINI_API_KEY_BACKUP",
    "GEMINI_API_KEY_FALLBACK",
)
_GEMINI_LIST_VARS = (
    "GEMINI_API_KEYS",
    "GEMINI_API_KEY_LIST",
    "GEMINI_BACKUP_KEYS",
)


@dataclass(frozen=True)
class ZeroCostStatus:
    enabled: bool
    blocked_keys: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.blocked_keys


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in TRUTHY


def _openrouter_model_is_free(model: object) -> bool:
    value = str(model or "openrouter/free").strip().lower()
    return value == "openrouter/free" or value.endswith(":free")


def _ollama_is_local(value: object) -> bool:
    raw = str(value or "http://127.0.0.1:11434").strip()
    try:
        parsed = urlparse(raw)
        return parsed.scheme in {"http", "https"} and parsed.hostname in {
            "127.0.0.1", "localhost", "::1"
        }
    except Exception:
        return False


def gemini_credentials_configured(env: Mapping[str, str] | None = None) -> bool:
    """True when *any* primary/backup/list Gemini credential is configured.

    This closes a subtle zero-cost bypass: a deployment with only
    ``GEMINI_API_KEY_2`` or ``GEMINI_API_KEYS`` set must be held to the same
    confirmation rule as the primary key.
    """
    source = env if env is not None else os.environ
    names = list(_GEMINI_SINGLE_VARS) + list(_GEMINI_LIST_VARS)
    names.extend(f"GEMINI_API_KEY_{i}" for i in range(2, 10))
    names.extend(f"GEMINI_API_KEY{i}" for i in range(2, 10))
    return any(str(source.get(name, "") or "").strip() for name in names)


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

    if gemini_credentials_configured(source) and not _truthy(
        source.get("GEMINI_ZERO_COST_CONFIRMED", "")
    ):
        blocked.append(_GEMINI_UNCONFIRMED)

    groq_key = str(source.get("GROQ_API_KEY", "")).strip()
    if groq_key and not _truthy(source.get("GROQ_ZERO_COST_CONFIRMED", "")):
        blocked.append(_GROQ_UNCONFIRMED)

    openrouter_key = str(source.get("OPENROUTER_API_KEY", "")).strip()
    if openrouter_key and not _openrouter_model_is_free(source.get("OPENROUTER_MODEL")):
        blocked.append(_OPENROUTER_NONFREE)

    if _truthy(source.get("OLLAMA_ENABLED", "")) and not _ollama_is_local(
        source.get("OLLAMA_BASE_URL")
    ):
        blocked.append(_REMOTE_OLLAMA)

    return ZeroCostStatus(enabled=True, blocked_keys=tuple(blocked))


def enforce_zero_cost_config(env: Mapping[str, str] | None = None) -> ZeroCostStatus:
    """Fail closed when runtime configuration could create a paid AI path."""
    status = inspect_zero_cost_config(env)
    if status.blocked_keys:
        joined = ", ".join(status.blocked_keys)
        hints = []
        if _GEMINI_UNCONFIRMED in status.blocked_keys:
            hints.append(
                "Gemini confirmation tabhi true karein jab har configured Google project/key par paid billing/spend path disabled verify ho."
            )
        if _GROQ_UNCONFIRMED in status.blocked_keys:
            hints.append(
                "Groq confirmation tabhi true karein jab key Free plan/no-billing account ki ho."
            )
        if _OPENROUTER_NONFREE in status.blocked_keys:
            hints.append(
                "OpenRouter model ko openrouter/free ya explicit :free variant par rakhein."
            )
        if _REMOTE_OLLAMA in status.blocked_keys:
            hints.append(
                "ZERO_COST_ONLY mein Ollama ko localhost par hi chalaya ja sakta hai."
            )
        extra = (" " + " ".join(hints)) if hints else ""
        raise RuntimeError(
            "ZERO_COST_ONLY is enabled, but unsafe/unconfirmed AI credential "
            f"configuration was found: {joined}.{extra}"
        )
    return status


__all__ = [
    "ZeroCostStatus",
    "enforce_zero_cost_config",
    "gemini_credentials_configured",
    "inspect_zero_cost_config",
    "zero_cost_enabled",
]
