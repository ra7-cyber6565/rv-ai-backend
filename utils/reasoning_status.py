"""Read-only, non-secret reasoning resilience status.

No provider is contacted here. This only reports whether each configured layer is
eligible under the ₹0 policy plus coarse process-local cooldown state learned
from real requests. API keys/tokens, prompts and provider response bodies are
never returned.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

from utils.provider_health import provider_health
from utils.zero_cost_guard import gemini_credentials_configured

_TRUTHY = {"1", "true", "yes", "on"}


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


def _openrouter_free(model: object) -> bool:
    value = str(model or "openrouter/free").strip().lower()
    return value == "openrouter/free" or value.endswith(":free")


def _local_url(value: object) -> bool:
    try:
        parsed = urlparse(str(value or "http://127.0.0.1:11434").strip())
        return parsed.scheme in {"http", "https"} and parsed.hostname in {
            "127.0.0.1", "localhost", "::1"
        }
    except Exception:
        return False


def reasoning_status(env=None) -> dict:
    source = env if env is not None else os.environ
    zero_cost = _truthy(source.get("ZERO_COST_ONLY", "true"))

    # Primary or any backup/list Gemini credential counts as configured. This
    # must match the key-pool/zero-cost guard; otherwise backup-only deployments
    # would be silently reported unusable even though the engine can rotate to it.
    gemini_key = gemini_credentials_configured(source)
    gemini_confirmed = _truthy(source.get("GEMINI_ZERO_COST_CONFIRMED", ""))
    gemini_ready = gemini_key and (not zero_cost or gemini_confirmed)

    groq_key = bool(str(source.get("GROQ_API_KEY", "")).strip())
    groq_confirmed = _truthy(source.get("GROQ_ZERO_COST_CONFIRMED", ""))
    groq_ready = groq_key and (not zero_cost or groq_confirmed)

    openrouter_key = bool(str(source.get("OPENROUTER_API_KEY", "")).strip())
    openrouter_model = str(source.get("OPENROUTER_MODEL", "openrouter/free")).strip() or "openrouter/free"
    openrouter_ready = openrouter_key and (not zero_cost or _openrouter_free(openrouter_model))

    ollama_enabled = _truthy(source.get("OLLAMA_ENABLED", "false"))
    ollama_url = str(source.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).strip()
    ollama_ready = ollama_enabled and (not zero_cost or _local_url(ollama_url))

    chain = [item.strip().lower() for item in str(
        source.get("REASONING_FALLBACK_CHAIN", "groq,openrouter,ollama")
    ).split(",") if item.strip()]

    cooldowns = provider_health.snapshot()

    def _layer(configured: bool, kind: str, provider: str, **extra) -> dict:
        health = cooldowns.get(provider, {})
        return {
            "configured": configured,
            "kind": kind,
            "temporarily_skipped": bool(health.get("cooldown_active")),
            "cooldown_reason": str(health.get("reason") or ""),
            "cooldown_seconds_remaining": int(health.get("cooldown_seconds_remaining") or 0),
            **extra,
        }

    layers = {
        "gemini_primary": _layer(gemini_ready, "cloud", "gemini"),
        "groq_backup": _layer(groq_ready, "cloud", "groq"),
        "openrouter_free_backup": _layer(
            openrouter_ready,
            "cloud",
            "openrouter",
            model=openrouter_model if _openrouter_free(openrouter_model) else "blocked_nonfree",
        ),
        "ollama_local_backup": _layer(
            ollama_ready,
            "local",
            "ollama",
            model=str(source.get("OLLAMA_MODEL", "qwen3:4b")).strip() or "qwen3:4b",
            localhost_only=zero_cost,
        ),
        "deterministic_evidence_fallback": {
            "configured": True,
            "kind": "local_builtin",
            "temporarily_skipped": False,
            "cooldown_reason": "",
            "cooldown_seconds_remaining": 0,
            "note": "No API/model required; conservative retrieved-evidence answer only.",
        },
    }

    configured_model_layers = [
        name for name, row in layers.items()
        if name != "deterministic_evidence_fallback" and row.get("configured")
    ]
    usable_now = [
        name for name in configured_model_layers
        if not layers[name].get("temporarily_skipped")
    ]
    return {
        "zero_cost_only": zero_cost,
        "fallback_chain": chain,
        "model_layers_configured": len(configured_model_layers),
        "model_layers_usable_now": len(usable_now),
        "has_model_backup": any(name != "gemini_primary" for name in configured_model_layers),
        "has_model_layer_usable_now": bool(usable_now),
        "deterministic_last_resort": True,
        "layers": layers,
        "note": (
            "Configured ka matlab ₹0 policy/config ready hai. Temporarily_skipped recent quota/auth/network failure ki "
            "short process-local cooldown memory hai; cooldown ke baad provider automatically probe ho sakta hai. "
            "Saare model providers unavailable hon tab bhi deterministic evidence fallback available hai."
        ),
    }


__all__ = ["reasoning_status"]
