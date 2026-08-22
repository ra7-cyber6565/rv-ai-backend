"""Offline tests for provider-level reasoning failover. No network/API key."""
from __future__ import annotations

import os

# Keep production policy explicit during tests.
os.environ.setdefault("ZERO_COST_ONLY", "true")
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GROQ_API_KEY", None)
os.environ.pop("OPENROUTER_API_KEY", None)
os.environ["OLLAMA_ENABLED"] = "false"

from research_engine import gemini_reasoning  # noqa: E402
from research_engine.reasoning_router import (  # noqa: E402
    ProviderResult,
    ReasoningProvider,
    ResilientReasoning,
    _local_ollama_url,
    _openrouter_model_is_free,
)


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
        if self.script:
            item = self.script.pop(0)
        else:
            item = ProviderResult(
                provider=self.name, model=self.model, attempts=1,
                kind="quota", human="quota", block_for_run=True,
            )
        if isinstance(item, str):
            return ProviderResult(
                text=item, provider=self.name, model=self.model, attempts=1
            )
        return item


def _fail(name: str, model: str, kind: str = "quota", block: bool = True):
    return ProviderResult(
        provider=name,
        model=model,
        attempts=1,
        kind=kind,
        human=f"{name} unavailable",
        technical=f"HTTP 429 secret-provider-detail-{name}",
        block_for_run=block,
    )


def test_package_exports_accounting_integrated_resilient_subclass():
    # Package export is the small accounting-integration subclass layered over
    # this base provider router. This preserves old provider behaviour while
    # fixing Claude's new pass_log/accounting fields after a fallback succeeds.
    assert issubclass(gemini_reasoning.GeminiReasoning, ResilientReasoning)


def test_quota_on_first_fallback_moves_to_second_and_completes_same_logical_pass():
    first = FakeProvider("groq", "free-a", [_fail("groq", "free-a")])
    second = FakeProvider("openrouter", "openrouter/free", ["poora fallback jawab"])
    brain = ResilientReasoning(budget=2, fallback_providers=[first, second])

    text = brain.generate("prompt", "analysis")

    assert text == "poora fallback jawab"
    assert brain.calls_used == 1, "provider switch same logical pass hai"
    assert first.calls == 1 and second.calls == 1
    assert brain.blocked_providers.get("groq") == "quota"
    assert brain.failure_kind() == "", "successful fallback ko failure nahi bolna"
    assert not brain.errors, "intermediate quota user-facing error list mein nahi aani chahiye"
    assert any("openrouter" in note for note in brain.notes)
    assert any("secret-provider-detail-groq" in row for row in brain.technical_details())


def test_quota_block_is_remembered_for_later_passes():
    first = FakeProvider("groq", "free-a", [_fail("groq", "free-a"), "should-not-run"])
    second = FakeProvider("openrouter", "openrouter/free", ["analysis", "synthesis"])
    brain = ResilientReasoning(budget=2, fallback_providers=[first, second])

    assert brain.generate("p1", "analysis") == "analysis"
    assert brain.generate("p2", "synthesis") == "synthesis"
    assert first.calls == 1, "known quota-dead provider ko next pass mein dobara hit nahi karna"
    assert second.calls == 2
    assert brain.calls_used == 2
    assert brain.successes == 2


def test_all_free_providers_fail_returns_empty_but_only_safe_human_error():
    a = FakeProvider("groq", "free-a", [_fail("groq", "free-a")])
    b = FakeProvider("openrouter", "openrouter/free", [_fail("openrouter", "openrouter/free")])
    brain = ResilientReasoning(budget=1, fallback_providers=[a, b])

    assert brain.generate("prompt", "analysis") == ""
    assert brain.failure_kind() == "all_free_providers_unavailable"
    assert brain.errors
    joined = " ".join(brain.errors)
    for raw in ("HTTP 429", "secret-provider-detail", "Traceback", "ResourceExhausted"):
        assert raw not in joined
    technical = " ".join(brain.technical_details())
    assert "secret-provider-detail" in technical


def test_accounting_separates_provider_fallback_from_same_model_retry():
    first = FakeProvider("groq", "free-a", [_fail("groq", "free-a")])
    second = FakeProvider("openrouter", "openrouter/free", ["done"])
    brain = ResilientReasoning(budget=1, fallback_providers=[first, second])
    assert brain.generate("prompt", "analysis") == "done"
    acc = brain.api_accounting()
    assert acc["logical_reasoning_calls"] == 1
    assert acc["actual_http_attempts"] == 2
    assert acc["provider_fallbacks"] == 1
    assert acc["provider_attempts"] == {"groq": 1, "openrouter": 1}
    assert acc["provider_successes"] == {"openrouter": 1}
    assert acc["same_model_retries"] == 0
    assert acc["retries"] == 0, "provider switch ko retry kehna galat hai"


def test_free_model_and_local_url_guards():
    assert _openrouter_model_is_free("openrouter/free")
    assert _openrouter_model_is_free("some/model:free")
    assert not _openrouter_model_is_free("openai/gpt-5")
    assert _local_ollama_url("http://127.0.0.1:11434")
    assert _local_ollama_url("http://localhost:11434")
    assert not _local_ollama_url("https://paid.example.com")


def test_provider_status_never_contains_api_secret(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "TOP-SECRET-KEY")
    monkeypatch.setenv("OPENROUTER_MODEL", "openrouter/free")
    brain = ResilientReasoning(budget=1)
    text = repr(brain.provider_status())
    assert "TOP-SECRET-KEY" not in text
    assert "openrouter" in text
