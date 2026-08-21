"""Offline tests for non-secret reasoning resilience status."""
from __future__ import annotations

from utils.reasoning_status import reasoning_status


def test_empty_config_still_reports_deterministic_last_resort():
    status = reasoning_status({"ZERO_COST_ONLY": "true"})
    assert status["zero_cost_only"] is True
    assert status["model_layers_configured"] == 0
    assert status["has_model_backup"] is False
    assert status["deterministic_last_resort"] is True
    assert status["layers"]["deterministic_evidence_fallback"]["configured"] is True


def test_confirmed_free_layers_are_reported_without_keys():
    env = {
        "ZERO_COST_ONLY": "true",
        "GEMINI_API_KEY": "SECRET-GEMINI",
        "GEMINI_ZERO_COST_CONFIRMED": "true",
        "GROQ_API_KEY": "SECRET-GROQ",
        "GROQ_ZERO_COST_CONFIRMED": "true",
        "OPENROUTER_API_KEY": "SECRET-OR",
        "OPENROUTER_MODEL": "openrouter/free",
        "OLLAMA_ENABLED": "true",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "OLLAMA_MODEL": "qwen3:4b",
    }
    status = reasoning_status(env)
    blob = repr(status)
    assert status["model_layers_configured"] == 4
    assert status["has_model_backup"] is True
    assert status["layers"]["gemini_primary"]["configured"] is True
    assert status["layers"]["groq_backup"]["configured"] is True
    assert status["layers"]["openrouter_free_backup"]["configured"] is True
    assert status["layers"]["ollama_local_backup"]["configured"] is True
    for secret in ("SECRET-GEMINI", "SECRET-GROQ", "SECRET-OR"):
        assert secret not in blob


def test_confirmed_backup_only_gemini_key_counts_as_ready_without_leak():
    env = {
        "ZERO_COST_ONLY": "true",
        "GEMINI_API_KEY_2": "SECRET-BACKUP-GEMINI",
        "GEMINI_ZERO_COST_CONFIRMED": "true",
    }
    status = reasoning_status(env)
    assert status["layers"]["gemini_primary"]["configured"] is True
    assert status["model_layers_configured"] == 1
    assert "SECRET-BACKUP-GEMINI" not in repr(status)


def test_unconfirmed_backup_only_gemini_key_is_not_ready():
    status = reasoning_status({
        "ZERO_COST_ONLY": "true",
        "GEMINI_API_KEYS": "SECRET-ONE,SECRET-TWO",
        "GEMINI_ZERO_COST_CONFIRMED": "false",
    })
    assert status["layers"]["gemini_primary"]["configured"] is False
    assert status["model_layers_configured"] == 0
    assert "SECRET-ONE" not in repr(status)
    assert "SECRET-TWO" not in repr(status)


def test_unconfirmed_or_paid_paths_are_not_reported_ready():
    status = reasoning_status({
        "ZERO_COST_ONLY": "true",
        "GEMINI_API_KEY": "g",
        "GEMINI_ZERO_COST_CONFIRMED": "false",
        "GROQ_API_KEY": "q",
        "GROQ_ZERO_COST_CONFIRMED": "false",
        "OPENROUTER_API_KEY": "o",
        "OPENROUTER_MODEL": "paid/model",
        "OLLAMA_ENABLED": "true",
        "OLLAMA_BASE_URL": "https://remote-paid.example.com",
    })
    assert status["layers"]["gemini_primary"]["configured"] is False
    assert status["layers"]["groq_backup"]["configured"] is False
    assert status["layers"]["openrouter_free_backup"]["configured"] is False
    assert status["layers"]["openrouter_free_backup"]["model"] == "blocked_nonfree"
    assert status["layers"]["ollama_local_backup"]["configured"] is False
    assert status["deterministic_last_resort"] is True


def test_fallback_chain_is_visible_but_credentials_are_not():
    status = reasoning_status({
        "ZERO_COST_ONLY": "true",
        "REASONING_FALLBACK_CHAIN": "openrouter,ollama,groq",
        "OPENROUTER_API_KEY": "hidden",
        "OPENROUTER_MODEL": "provider/model:free",
    })
    assert status["fallback_chain"] == ["openrouter", "ollama", "groq"]
    assert "hidden" not in repr(status)
    assert status["layers"]["openrouter_free_backup"]["configured"] is True
