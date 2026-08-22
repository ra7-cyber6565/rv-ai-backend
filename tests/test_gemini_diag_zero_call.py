"""Offline regression: Gemini diagnostics must never spend generation quota."""
from __future__ import annotations

import sys
import types

from research_engine import gemini_model


_BACKUP_VARS = [
    "GEMINI_API_KEY_BACKUP",
    "GEMINI_API_KEY_FALLBACK",
    "GEMINI_API_KEYS",
    "GEMINI_API_KEY_LIST",
    "GEMINI_BACKUP_KEYS",
]
_BACKUP_VARS += [f"GEMINI_API_KEY_{i}" for i in range(2, 10)]
_BACKUP_VARS += [f"GEMINI_API_KEY{i}" for i in range(2, 10)]


def _env(monkeypatch, *, key="fake-key", confirmed="false"):
    monkeypatch.setenv("ZERO_COST_ONLY", "true")
    monkeypatch.setenv("GEMINI_API_KEY", key)
    monkeypatch.setenv("GEMINI_ZERO_COST_CONFIRMED", confirmed)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    for name in _BACKUP_VARS:
        monkeypatch.delenv(name, raising=False)
    gemini_model.reset_for_new_key()


def test_default_diagnose_is_zero_network_and_hides_key_length(monkeypatch):
    _env(monkeypatch)

    def explode(_):
        raise AssertionError("available_models must not run in passive diagnostics")

    monkeypatch.setattr(gemini_model, "available_models", explode)
    report = gemini_model.diagnose()
    assert report["key_present"] is True
    assert report["keys_available"] == 1
    assert report["keys"] == ["free key #1"]
    assert report["network_calls"] == 0
    assert report["generation_calls"] == 0
    assert report["status"] == "configured_not_probed"
    assert "key_length" not in report
    assert "fake-key" not in repr(report)


def test_backup_only_diagnose_is_configured_without_value_or_network(monkeypatch):
    _env(monkeypatch, key="", confirmed="true")
    monkeypatch.setenv("GEMINI_API_KEY_2", "SECRET-BACKUP-VALUE")

    def explode(_):
        raise AssertionError("passive diagnostics must not list models")

    monkeypatch.setattr(gemini_model, "available_models", explode)
    report = gemini_model.diagnose()
    assert report["key_present"] is True
    assert report["keys_available"] == 1
    assert report["keys"] == ["free key #1"]
    assert report["status"] == "configured_not_probed"
    assert report["network_calls"] == 0
    assert report["generation_calls"] == 0
    assert "SECRET-BACKUP-VALUE" not in repr(report)
    assert "key_length" not in report


def test_active_discovery_blocked_until_zero_cost_confirmation(monkeypatch):
    _env(monkeypatch, confirmed="false")

    def explode(_):
        raise AssertionError("zero-cost policy must block active discovery")

    monkeypatch.setattr(gemini_model, "available_models", explode)
    report = gemini_model.diagnose(active_discovery=True)
    assert report["status"] == "blocked_by_zero_cost_policy"
    assert report["network_calls"] == 0
    assert report["generation_calls"] == 0


def test_active_discovery_lists_models_but_never_generate_content(monkeypatch):
    _env(monkeypatch, confirmed="true")
    calls = {"configure": 0, "list": 0, "generate": 0}

    class ModelInfo:
        name = "models/gemini-2.5-flash"
        supported_generation_methods = ["generateContent"]

    fake_genai = types.ModuleType("google.generativeai")

    def configure(*, api_key):
        assert api_key == "fake-key"
        calls["configure"] += 1

    def list_models():
        calls["list"] += 1
        return [ModelInfo()]

    class ForbiddenGenerativeModel:
        def __init__(self, *args, **kwargs):  # noqa: ARG002
            calls["generate"] += 1
            raise AssertionError("diagnostic must never instantiate GenerativeModel")

    fake_genai.configure = configure
    fake_genai.list_models = list_models
    fake_genai.GenerativeModel = ForbiddenGenerativeModel
    google = types.ModuleType("google")
    google.generativeai = fake_genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)

    report = gemini_model.diagnose(active_discovery=True)
    assert report["status"] == "model_list_discovered"
    assert report["network_calls"] == 1
    assert report["generation_calls"] == 0
    assert report["models_found"] == ["gemini-2.5-flash"]
    assert calls == {"configure": 1, "list": 1, "generate": 0}


def test_active_discovery_raw_provider_error_is_sanitized(monkeypatch):
    _env(monkeypatch, confirmed="true")
    fake_genai = types.ModuleType("google.generativeai")
    fake_genai.configure = lambda **kwargs: None

    def fail():
        raise RuntimeError("429 ResourceExhausted protobuf SECRET-SDK-DETAIL")

    fake_genai.list_models = fail
    google = types.ModuleType("google")
    google.generativeai = fake_genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai)

    report = gemini_model.diagnose(active_discovery=True)
    assert report["status"] == "discovery_failed"
    text = repr(report)
    for raw in ("ResourceExhausted", "protobuf", "SECRET-SDK-DETAIL", "429"):
        assert raw not in text
    assert report["generation_calls"] == 0


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
