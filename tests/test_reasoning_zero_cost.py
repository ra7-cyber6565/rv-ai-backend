"""Zero-cost policy tests for Gemini/Groq/OpenRouter/Ollama fallback config."""
from __future__ import annotations

from utils.zero_cost_guard import inspect_zero_cost_config


def _base(**extra):
    env = {"ZERO_COST_ONLY": "true"}
    env.update(extra)
    return env


def test_groq_key_requires_explicit_free_account_confirmation():
    status = inspect_zero_cost_config(_base(GROQ_API_KEY="gsk_test"))
    assert not status.ok
    assert any("GROQ_ZERO_COST_CONFIRMED" in item for item in status.blocked_keys)

    status = inspect_zero_cost_config(_base(
        GROQ_API_KEY="gsk_test",
        GROQ_ZERO_COST_CONFIRMED="true",
    ))
    assert status.ok


def test_openrouter_is_allowed_only_on_explicit_free_models():
    free_router = inspect_zero_cost_config(_base(
        OPENROUTER_API_KEY="or-key",
        OPENROUTER_MODEL="openrouter/free",
    ))
    assert free_router.ok

    free_variant = inspect_zero_cost_config(_base(
        OPENROUTER_API_KEY="or-key",
        OPENROUTER_MODEL="provider/model:free",
    ))
    assert free_variant.ok

    paid = inspect_zero_cost_config(_base(
        OPENROUTER_API_KEY="or-key",
        OPENROUTER_MODEL="anthropic/claude-sonnet",
    ))
    assert not paid.ok
    assert any("OPENROUTER_MODEL" in item for item in paid.blocked_keys)


def test_local_ollama_only_in_zero_cost_mode():
    local = inspect_zero_cost_config(_base(
        OLLAMA_ENABLED="true",
        OLLAMA_BASE_URL="http://127.0.0.1:11434",
    ))
    assert local.ok

    remote = inspect_zero_cost_config(_base(
        OLLAMA_ENABLED="true",
        OLLAMA_BASE_URL="https://remote-inference.example.com",
    ))
    assert not remote.ok
    assert any("OLLAMA_BASE_URL" in item for item in remote.blocked_keys)


def test_zero_cost_disabled_does_not_apply_these_policy_blocks():
    status = inspect_zero_cost_config({
        "ZERO_COST_ONLY": "false",
        "GROQ_API_KEY": "x",
        "OPENROUTER_API_KEY": "y",
        "OPENROUTER_MODEL": "paid/model",
        "OLLAMA_ENABLED": "true",
        "OLLAMA_BASE_URL": "https://remote.example.com",
    })
    assert status.ok
    assert status.enabled is False
