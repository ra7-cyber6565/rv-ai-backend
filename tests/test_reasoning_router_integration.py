"""Integration tests: Claude pass accounting + ChatGPT free-provider fallback.

Pure offline: fake Gemini/fallback providers only. No API key/network call.
"""
from __future__ import annotations

import os

from research_engine import gemini_reasoning
from research_engine.reasoning_router import ProviderResult, ReasoningProvider
from research_engine.reasoning_router_integrated import ResilientReasoning


class FakeProvider(ReasoningProvider):
    def __init__(self, name: str, model: str, script):
        self.name = name
        self.model = model
        self.script = list(script)
        self.calls = 0

    @property
    def configured(self) -> bool:
        return True

    def generate(self, prompt: str, label: str = "") -> ProviderResult:  # noqa: ARG002
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, str):
            return ProviderResult(
                text=item, provider=self.name, model=self.model, attempts=1
            )
        return item


class FakeGeminiResponse:
    def __init__(self, text: str):
        self.text = text


class FakeGeminiModel:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def generate_content(self, prompt):  # noqa: ARG002
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeGeminiResponse(item)


def quota_failure(provider: str, model: str) -> ProviderResult:
    return ProviderResult(
        provider=provider,
        model=model,
        attempts=1,
        kind="quota",
        human="free quota abhi available nahi",
        technical=f"HTTP 429 private-{provider}-quota-detail",
        block_for_run=True,
    )


def _force_no_gemini(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_ZERO_COST_CONFIRMED", raising=False)
    monkeypatch.setenv("ZERO_COST_ONLY", "true")


def _force_fake_gemini(monkeypatch, brain: ResilientReasoning, script) -> FakeGeminiModel:
    monkeypatch.setenv("ZERO_COST_ONLY", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("GEMINI_ZERO_COST_CONFIRMED", "true")
    fake = FakeGeminiModel(script)
    brain._model = fake
    brain.model = lambda: brain._model
    brain._model_order = lambda: ["fake-gemini"]
    brain.model_name = "fake-gemini"
    return fake


def test_package_runtime_uses_integrated_router():
    assert gemini_reasoning.GeminiReasoning is ResilientReasoning


def test_no_gemini_key_fallback_success_is_one_completed_logical_pass(monkeypatch):
    _force_no_gemini(monkeypatch)
    backup = FakeProvider("openrouter", "openrouter/free", ["complete answer"])
    brain = ResilientReasoning(budget=2, fallback_providers=[backup])

    assert brain.generate("prompt", "analysis") == "complete answer"
    acc = brain.api_accounting()

    assert brain.calls_used == 1
    assert acc["passes_requested"] == 1
    assert acc["passes_with_output"] == 1
    assert acc["passes_empty"] == 0
    assert acc["pass_log"][0]["ok"] is True
    assert acc["pass_log"][0]["label"] == "analysis"
    assert acc["actual_http_attempts"] == 1
    assert acc["provider_fallbacks"] == 1
    assert acc["same_model_retries"] == 0
    assert acc["model_switches"] == 1
    assert brain.failure_kind() == ""
    assert brain.failure_reason() == ""


def test_gemini_daily_quota_then_free_backup_repairs_empty_pass_log(monkeypatch):
    backup = FakeProvider("openrouter", "openrouter/free", ["backup saved the pass"])
    brain = ResilientReasoning(budget=2, fallback_providers=[backup], model_name="fake-gemini")
    daily = RuntimeError(
        "429 ResourceExhausted quota_id: GenerateRequestsPerDayPerProjectPerModel-FreeTier"
    )
    fake = _force_fake_gemini(monkeypatch, brain, [daily])

    assert brain.generate("prompt", "analysis") == "backup saved the pass"
    acc = brain.api_accounting()

    assert fake.calls == 1
    assert backup.calls == 1
    assert acc["logical_reasoning_calls"] == 1
    assert acc["passes_requested"] == 1
    assert acc["passes_with_output"] == 1, acc["pass_log"]
    assert acc["empty_output_passes"] == []
    assert acc["pass_log"][0]["ok"] is True
    assert acc["pass_log"][0]["http_attempts"] == 2
    assert acc["actual_http_attempts"] == 2
    assert acc["provider_fallbacks"] == 1
    assert acc["same_model_retries"] == 0
    assert brain.failure_reason() == "", "saved pass ko quota failure bana kar user ko mat dikhao"


def test_dead_gemini_is_not_retried_on_next_logical_pass(monkeypatch):
    backup = FakeProvider("openrouter", "openrouter/free", ["first", "second"])
    brain = ResilientReasoning(budget=2, fallback_providers=[backup], model_name="fake-gemini")
    daily = RuntimeError(
        "429 ResourceExhausted quota_id: GenerateRequestsPerDayPerProjectPerModel-FreeTier"
    )
    fake = _force_fake_gemini(monkeypatch, brain, [daily, "must never be called"])

    assert brain.generate("p1", "analysis") == "first"
    gemini_calls = fake.calls
    assert brain.generate("p2", "synthesis") == "second"

    assert fake.calls == gemini_calls == 1
    assert backup.calls == 2
    acc = brain.api_accounting()
    assert acc["passes_requested"] == 2
    assert acc["passes_with_output"] == 2
    assert all(row["ok"] for row in acc["pass_log"])


def test_all_backups_exhausted_records_incomplete_pass_without_raw_user_error(monkeypatch):
    _force_no_gemini(monkeypatch)
    a = FakeProvider("groq", "free-a", [quota_failure("groq", "free-a")])
    b = FakeProvider("openrouter", "openrouter/free", [
        quota_failure("openrouter", "openrouter/free")
    ])
    brain = ResilientReasoning(budget=1, fallback_providers=[a, b])

    assert brain.generate("prompt", "analysis") == ""
    acc = brain.api_accounting()

    assert acc["passes_requested"] == 1
    assert acc["passes_with_output"] == 0
    assert acc["passes_empty"] == 1
    assert acc["pass_log"][0]["ok"] is False
    assert acc["actual_http_attempts"] == 2
    assert brain.failure_kind() == "all_free_providers_unavailable"
    user_errors = " ".join(brain.errors)
    assert "HTTP 429" not in user_errors
    assert "private-" not in user_errors
    developer_details = " ".join(brain.technical_details())
    assert "private-groq" in developer_details
    assert "private-openrouter" in developer_details


def test_provider_fallback_is_never_counted_as_same_model_retry(monkeypatch):
    _force_no_gemini(monkeypatch)
    first = FakeProvider("groq", "free-a", [quota_failure("groq", "free-a")])
    second = FakeProvider("openrouter", "openrouter/free", ["done"])
    brain = ResilientReasoning(budget=1, fallback_providers=[first, second])
    assert brain.generate("prompt", "analysis") == "done"
    acc = brain.api_accounting()
    assert acc["same_model_retries"] == 0
    assert acc["retries"] == 0
    assert acc["provider_fallbacks"] == 1
    assert acc["model_switches"] == 1
