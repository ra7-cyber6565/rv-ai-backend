"""Elapsed-time regressions with injected clocks, SDK and HTTP responses only."""
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from research_engine import gemini_model, gemini_reasoning, research_company
from research_engine.company_worker import execute
from research_engine.reasoning_router import OpenAICompatibleFreeProvider, OllamaProvider
from research_engine.reasoning_router import ProviderResult
from research_engine.reasoning_router_integrated import ResilientReasoning
from utils import research_runtime as runtime
from utils.provider_health import provider_health


class Clock:
    now = 0.0

    def advance(self, seconds):
        self.now += seconds


def install_sdk(monkeypatch, sdk):
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(generativeai=sdk))
    monkeypatch.setitem(sys.modules, "google.generativeai", sdk)


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(runtime.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(gemini_reasoning.time, "sleep", clock.advance)
    monkeypatch.setattr(gemini_reasoning, "_BACKOFF_SECONDS", (1.5, 4.0))
    for name in list(os.environ):
        if name.startswith(("GEMINI_", "GROQ_", "OPENROUTER_", "OLLAMA_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-key")
    monkeypatch.setenv("GEMINI_MODEL", "model-a")
    monkeypatch.setenv("GEMINI_ZERO_COST_CONFIRMED", "true")
    monkeypatch.setenv("ZERO_COST_ONLY", "true")
    # A missed injection fails locally; these tests cannot reach a provider.
    def unexpected(*args, **kwargs):
        raise AssertionError("unexpected provider access in fixture test")
    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(post=unexpected))
    install_sdk(monkeypatch, SimpleNamespace(
        list_models=unexpected, configure=unexpected, GenerativeModel=unexpected))
    monkeypatch.setitem(sys.modules, "dotenv", SimpleNamespace(load_dotenv=lambda: None))
    provider_health.clear()
    gemini_model.reset_for_new_key()
    yield clock
    provider_health.clear()
    gemini_model.reset_for_new_key()


class Model:
    def __init__(self, clock, script):
        self.clock, self.script, self.requests = clock, list(script), []

    def generate_content(self, prompt, *, request_options, generation_config=None):
        self.requests.append((prompt, dict(request_options), generation_config))
        delay, result = self.script.pop(0)
        self.clock.advance(request_options["timeout"] if delay == "timeout" else delay)
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(text=result)


def brain_for(model, **kwargs):
    brain = ResilientReasoning(budget=1, model_name="model-a", **kwargs)
    brain._model = model
    brain.model = lambda: brain._model
    brain._model_order = lambda: ["model-a"]
    return brain


def worker(brain, evidence=""):
    return execute({"role": "evidence", "question": "Fixture question", "evidence": evidence},
                   lambda budget: brain)


def deadline():
    return RuntimeError("DeadlineExceeded: 504 Deadline Exceeded")


def daily_quota():
    return RuntimeError("429 quota_id: GenerateRequestsPerDayPerProjectPerModel-FreeTier")


def test_slow_compact_recovery_uses_remaining_window_and_keeps_accounting(clock):
    model = Model(clock, [("timeout", deadline())] * 3)
    brain = brain_for(model, fallback_providers=[])
    result = worker(brain, "evidence " * 4000)
    assert [r[1]["timeout"] for r in model.requests] == [75, 75, 20]
    assert clock.now == 170
    assert result["error"] == "worker_deadline"
    assert result["accounting_complete"] is True
    assert result["accounting"]["actual_http_attempts"] == 3
    assert brain.same_model_retries == 2
    assert brain.prompt_compactions == brain.timeout_extensions == 1
    assert brain.pass_log[-1]["http_attempts"] == 3
    assert all(r[1]["retry"] is None for r in model.requests)
    assert all(r[2]["max_output_tokens"] == 6000 for r in model.requests)


def test_compact_recovery_can_still_succeed_without_lowering_output_ceiling(clock):
    model = Model(clock, [("timeout", deadline()), ("timeout", deadline()), (2, "complete report")])
    result = worker(brain_for(model, fallback_providers=[]), "evidence " * 4000)
    assert result["answer"] == "complete report"
    assert result["accounting"]["successful_calls"] == 1
    assert clock.now == 152


def test_fast_primary_failure_preserves_confirmed_free_http_fallback(clock, monkeypatch):
    seen = []
    def post(*args, **kwargs):
        seen.append(kwargs)
        clock.advance(1)
        return SimpleNamespace(status_code=200, json=lambda: {
            "choices": [{"message": {"content": "fallback report"}}]})
    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(post=post))
    monkeypatch.setenv("GROQ_API_KEY", "fixture")
    monkeypatch.setenv("GROQ_ZERO_COST_CONFIRMED", "true")
    backup = OpenAICompatibleFreeProvider(name="groq", endpoint="https://fixture.invalid",
        key_env="GROQ_API_KEY", model="fixture", confirm_env="GROQ_ZERO_COST_CONFIRMED")
    brain = brain_for(Model(clock, [(0.5, daily_quota())]), fallback_providers=[backup])
    result = worker(brain)
    assert result["answer"] == "fallback report"
    assert result["accounting"]["actual_http_attempts"] == 2
    assert brain.calls_used == 1 and brain.same_model_retries == 0
    assert brain.pass_log[-1]["ok"] is True
    assert seen[0]["json"]["max_tokens"] == 6000


def test_fallback_only_expiry_preserves_its_requested_pass_and_http_counts(clock, monkeypatch):
    def slow(*args):
        clock.advance(170)
        return ProviderResult(provider="fixture-free", model="fixture", attempts=1, kind="network")
    first = SimpleNamespace(name="fixture-free", model="fixture", configured=True, generate=slow)
    second = SimpleNamespace(name="unused", model="fixture", configured=True,
                             generate=lambda *args: pytest.fail("fallback after expiry"))
    brain = ResilientReasoning(budget=1, fallback_providers=[first, second])
    monkeypatch.setattr(brain, "_gemini_allowed", lambda: False)
    result = worker(brain)
    assert result["error"] == "worker_deadline"
    assert result["accounting_complete"] is True
    assert brain.attempts == 1 and brain.calls_used == 1
    assert brain.pass_log == [{"label": "company_evidence", "ok": False,
                              "http_attempts": 1, "model": ""}]


@pytest.mark.parametrize("kind", ["hosted", "ollama"])
def test_fallback_http_connect_and_read_share_remaining_time(clock, monkeypatch, kind):
    seen = []
    def post(*args, **kwargs):
        seen.append(kwargs)
        return SimpleNamespace(status_code=200, json=lambda: {
            "message": {"content": "ok"}, "choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(post=post))
    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture")
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    provider = OllamaProvider() if kind == "ollama" else OpenAICompatibleFreeProvider(
        name="openrouter", endpoint="https://fixture.invalid", key_env="OPENROUTER_API_KEY",
        model="openrouter/free")
    with runtime.generation_window(8):
        assert provider.generate("fixture").ok
    assert sum(seen[0]["timeout"]) <= 8
    assert min(seen[0]["timeout"]) > 0


@pytest.mark.parametrize("elapsed, expected_attempts", [(5, 1), (10, 0)])
def test_discovery_consumes_the_same_generation_window(clock, monkeypatch, elapsed, expected_attempts):
    options = []
    model = Model(clock, [("timeout", deadline())])
    def discover(**kwargs):
        options.append(kwargs["request_options"])
        clock.advance(elapsed)
        return [SimpleNamespace(name="models/model-a", supported_generation_methods=["generateContent"])]
    install_sdk(monkeypatch, SimpleNamespace(
        configure=lambda **kwargs: None, list_models=discover, GenerativeModel=lambda name: model))
    brain = ResilientReasoning(budget=1, fallback_providers=[], model_name="model-a")
    brain._model_order = lambda: ["model-a"]
    # Explicit model_name avoids resolve(); exercise the real discovery branch.
    monkeypatch.setattr(gemini_reasoning, "MODEL_NAME", "model-a")
    with runtime.generation_window(10):
        result = worker(brain)
    assert options == [{"timeout": 10, "retry": None}]
    assert result["error"] == "worker_deadline"
    assert result["accounting"]["actual_http_attempts"] == expected_attempts
    if expected_attempts:
        assert model.requests[0][1]["timeout"] == 5


def test_backup_key_rotation_keeps_the_remaining_window(clock, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY_2", "fixture-backup")
    backup = Model(clock, [(0.2, "backup-key report")])
    seen = []
    def discover(**kwargs):
        seen.append(kwargs["request_options"])
        clock.advance(0.2)
        return [SimpleNamespace(name="model-a", supported_generation_methods=["generateContent"])]
    install_sdk(monkeypatch, SimpleNamespace(
        configure=lambda **kwargs: None, list_models=discover, GenerativeModel=lambda name: backup))
    brain = brain_for(Model(clock, [(0.5, daily_quota())]), fallback_providers=[])
    with runtime.generation_window(2):
        result = worker(brain)
    assert result["answer"] == "backup-key report"
    assert brain.key_switches == 1 and brain.attempts == 2
    assert seen[0]["timeout"] == 1.5
    assert backup.requests[0][1]["timeout"] == pytest.approx(1.3)


def test_exhausted_central_lease_does_not_count_a_planned_compact_retry(clock, monkeypatch):
    leases = []
    def reserve(*args):
        leases.append(args)
        if len(leases) > 1:
            raise runtime.RuntimeBlocked("fixture budget")
    monkeypatch.setattr(runtime, "reserve_request", reserve)
    brain = brain_for(Model(clock, [(0.1, RuntimeError("503 Service Unavailable"))]), fallback_providers=[])
    result = worker(brain, "evidence " * 4000)
    assert result["error"] == "application_budget"
    assert result["accounting_complete"] is True
    assert brain.attempts == 1 and brain.same_model_retries == brain.prompt_compactions == 0


def test_backoff_cannot_start_a_retry_after_window_expiry(clock):
    brain = brain_for(Model(clock, [(0.5, RuntimeError("503 Service Unavailable"))]), fallback_providers=[])
    with runtime.generation_window(1.5):
        result = worker(brain)
    assert result["error"] == "worker_deadline"
    assert clock.now == 1.5 and brain.attempts == 1 and brain.same_model_retries == 0


def test_last_attempt_cannot_claim_an_undispatched_compaction(clock, monkeypatch):
    monkeypatch.setattr(gemini_reasoning, "_BACKOFF_SECONDS", ())
    brain = brain_for(Model(clock, [(0, RuntimeError("input token count exceeds maximum context length"))]),
                      fallback_providers=[])
    worker(brain, "evidence " * 4000)
    assert brain.attempts == 1 and brain.prompt_compactions == brain.same_model_retries == 0


def test_adapter_rejection_is_not_counted_as_an_http_attempt(clock):
    model = SimpleNamespace(generate_content=lambda prompt: pytest.fail("unbounded adapter invoked"))
    brain = brain_for(model, fallback_providers=[])
    result = worker(brain)
    assert result["accounting_complete"] is True
    assert brain.attempts == 0 and brain.prompt_attempt_log == []


def test_expired_parent_cutoff_dispatches_nothing(clock):
    def factory(**kwargs):
        pytest.fail("model constructed after cutoff")
    result = execute({"role": "evidence", "question": "Fixture question", "evidence": "",
                      "generation_deadline": 0}, factory)
    assert result["error"] == "worker_deadline" and result["accounting_complete"] is True
    assert result["accounting"]["actual_http_attempts"] == 0


def test_successful_http_with_invalid_json_never_becomes_a_ready_report(clock):
    from research_engine.depth import get_depth_config
    from research_engine.models import EvidencePack
    def invalid_worker(payload):
        brain = brain_for(Model(clock, [(0, "not a JSON report")]), fallback_providers=[])
        return execute(payload, lambda budget: brain)
    result = research_company.run_company("Fixture question", EvidencePack(),
        get_depth_config("COMPANY"), worker=invalid_worker)
    assert result["completed_workers"] == 0
    assert all(row["status"] != "DRAFT_READY" for row in result["workers"])
    assert all(row["accounting"]["successful_calls"] == 1 for row in result["workers"])


def test_parent_owns_cutoff_and_process_death_remains_unknown(clock, monkeypatch):
    monkeypatch.setattr(research_company.time, "time", lambda: 1000)
    def run(*args, **kwargs):
        assert json.loads(kwargs["input"])["generation_deadline"] == 1170
        assert kwargs["timeout"] == 180
        raise subprocess.TimeoutExpired(args[0], 180, output="private body")
    monkeypatch.setattr(research_company.subprocess, "run", run)
    result = research_company.process_worker({"generation_deadline": 999999})
    assert result == {"error": "worker_deadline", "accounting_complete": False}


def test_nested_window_does_not_extend_deadline_or_leak_to_next_call(clock):
    with runtime.generation_window(2):
        clock.advance(1)
        with runtime.generation_window(170):
            assert runtime.bounded_request_timeout(75) == 1
        clock.advance(1)
        with pytest.raises(runtime.GenerationDeadline):
            runtime.bounded_request_timeout(75)
    assert runtime.bounded_request_timeout(75) == 75
