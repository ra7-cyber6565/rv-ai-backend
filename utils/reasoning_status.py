"""Read-only, non-secret reasoning resilience status.

No provider is contacted here. This only reports whether each configured layer is
eligible under the ₹0 policy. It is safe for /health and /api responses because
API keys/tokens are never returned.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

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

    gemini_key = bool(str(source.get("GEMINI_API_KEY", "")).strip())
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

    layers = {
        "gemini_primary": {"configured": gemini_ready, "kind": "cloud"},
        "groq_backup": {"configured": groq_ready, "kind": "cloud"},
        "openrouter_free_backup": {
            "configured": openrouter_ready,
            "kind": "cloud",
            "model": openrouter_model if _openrouter_free(openrouter_model) else "blocked_nonfree",
        },
        "ollama_local_backup": {
            "configured": ollama_ready,
            "kind": "local",
            "model": str(source.get("OLLAMA_MODEL", "qwen3:4b")).strip() or "qwen3:4b",
            # Do not expose a non-local remote URL in zero-cost mode. Hostname
            # itself can be operationally sensitive and is not needed in health.
            "localhost_only": zero_cost,
        },
        "deterministic_evidence_fallback": {
            "configured": True,
            "kind": "local_builtin",
            "note": "No API/model required; conservative retrieved-evidence answer only.",
        },
    }

    configured_model_layers = [
        name for name, row in layers.items()
        if name != "deterministic_evidence_fallback" and row.get("configured")
    ]
    return {
        "zero_cost_only": zero_cost,
        "fallback_chain": chain,
        "model_layers_configured": len(configured_model_layers),
        "has_model_backup": any(name != "gemini_primary" for name in configured_model_layers),
        "deterministic_last_resort": True,
        "layers": layers,
        "note": (
            "Configured ka matlab policy/config ready hai; live quota/reachability request ke waqt hi pata chalegi. "
            "Saare model providers fail hon tab bhi deterministic evidence fallback available hai."
        ),
    }


__all__ = ["reasoning_status"]
