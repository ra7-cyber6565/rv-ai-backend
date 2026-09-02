"""Offline tests for cross-request provider health/circuit breaking."""
from __future__ import annotations

import os

os.environ.setdefault("ZERO_COST_ONLY", "true")
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GEMINI_API_KEYS", None)
os.environ.pop("GEMINI_API_KEY_2", None)

from research_engine.reasoning_router import ProviderResult, ReasoningProvider  # noqa: E402
from research_engine.reasoning_router_integrated import ResilientReasoning  # noqa: E402
from utils.provider_health import ProviderHealthRegistry, provider_health  # noqa: E402


class FakeProvider(ReasoningProvider):
    def __init__(self, name: str, script):
        self.name = name
        self.model = "fake-free-model"
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
                text=item,
                provider=self.name,
                model=self.model,
                attempts=1,
            )
        return item


def quota(provider: str) -> ProviderResult:
    return ProviderResult(
        provider=provider,
        model="fake-free-model",
        attempts=1,
        kind="quota",
        human="free quota unavailable",
        technical="HTTP 429 raw body that must never enter health memory",
        block_for_run=True,
    )


def test_offline_suite_must_not_have_a_live_gemini_primary():
    """Order-independence guard (2026-08-23).

    Upar ke `os.environ.pop` sirf IMPORT ke waqt chalte hain. pytest poori suite
    ek hi process me chalata hai, isliye baad me chalne wala koi bhi test
    (jaise `tests/test_boot_preflight.py` ka asli `load_dotenv()`) `.env` ki
    `GEMINI_API_KEY` + `GEMINI_ZERO_COST_CONFIRMED=true` wapas daal sakta hai.
    Tab `ResilientReasoning` pehle ASLI Gemini primary call maarta hai aur is
    file ke circuit-breaker test ka hisaab (calls/attempts) bigad jaata hai -
    saath hi ek offline test chupke se network par chala jaata hai. Ye test us
    haalat ko seedha naam deta hai, taaki wajah dhoondhni na pade.
    """
    assert not ResilientReasoning._gemini_allowed(), (
        "process env me live Gemini credential maujood hai (naam: GEMINI_API_KEY / "
        "GEMINI_ZERO_COST_CONFIRMED) - koi dusra test env leak kar raha hai; "
        "offline test ko primary provider live nahi milna chahiye"
    )


def test_registry_cooldown_expires_and_allows_probe_again(monkeypatch):
    now = [1000.0]
    monkeypatch.setenv("PROVIDER_HEALTH_RATE_LIMIT_SECONDS", "10")
    registry = ProviderHealthRegistry(clock=lambda: now[0])

    registry.record_failure("openrouter", "quota")
    blocked, reason, remaining = registry.blocked("openrouter")
    assert blocked is True
    assert reason == "quota"
    assert remaining == 10

    now[0] = 1011.0
    blocked, reason, remaining = registry.blocked("openrouter")
    assert blocked is False
    assert remaining == 0


def test_success_clears_cooldown():
    now = [1000.0]
    registry = ProviderHealthRegistry(clock=lambda: now[0])
    registry.record_failure("groq", "quota")
    assert registry.blocked("groq")[0] is True

    registry.record_success("groq")
    assert registry.blocked("groq")[0] is False
    row = registry.snapshot()["groq"]
    assert row["cooldown_active"] is False
    assert row["failures"] == 0
    assert row["reason"] == ""


def test_unknown_content_specific_failure_does_not_globally_block_provider():
    registry = ProviderHealthRegistry()
    registry.record_failure("openrouter", "empty_response")
    assert registry.blocked("openrouter")[0] is False


def test_health_snapshot_contains_no_prompt_response_or_secret():
    registry = ProviderHealthRegistry()
    registry.record_failure("openrouter", "quota")
    text = repr(registry.snapshot()).lower()
    assert "api_key" not in text
    assert "bearer" not in text
    assert "raw body" not in text
    assert "user question" not in text


def test_second_research_request_skips_provider_known_quota_dead():
    provider_health.clear()
    first = FakeProvider("openrouter", [quota("openrouter")])
    brain1 = ResilientReasoning(budget=1, fallback_providers=[first])
    assert brain1.generate("question one", "analysis") == ""
    assert first.calls == 1
    assert provider_health.blocked("openrouter")[0] is True

    # New Reasoning instance = new HTTP/chat/research request. The provider is
    # still skipped process-wide, so a quota-dead free service does not add the
    # same latency/error to every new request.
    second = FakeProvider("openrouter", ["must not be called yet"])
    brain2 = ResilientReasoning(budget=1, fallback_providers=[second])
    assert brain2.generate("question two", "analysis") == ""
    assert second.calls == 0
    assert brain2.attempts == 0, "circuit-open skip is not an HTTP attempt"
    assert brain2.blocked_providers.get("openrouter") == "circuit_open"
    provider_health.clear()


def test_different_backup_still_runs_when_first_provider_circuit_is_open():
    provider_health.clear()
    provider_health.record_failure("groq", "quota")
    groq = FakeProvider("groq", ["must not run"])
    openrouter = FakeProvider("openrouter", ["backup answer"])

    brain = ResilientReasoning(budget=1, fallback_providers=[groq, openrouter])
    assert brain.generate("prompt", "synthesis") == "backup answer"
    assert groq.calls == 0
    assert openrouter.calls == 1
    assert brain.attempts == 1
    assert brain.failure_kind() == ""
    provider_health.clear()
