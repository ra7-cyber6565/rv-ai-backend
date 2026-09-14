"""Real SQLite/process sharing with scripted provider failures, no live calls."""
import json
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from research_engine.gemini_reasoning import GeminiReasoning
from utils import research_runtime as runtime
from utils.research_runtime import (
    ModelCooldownActive, ResearchCancelled, RunContext, RuntimeStore,
    bind, model_cooldown_scopes,
)

KEY = "PRIVATE_TEST_CREDENTIAL"
LIMITS = {"http": 100, "input_bytes": 1000000, "output_tokens": 600000, "seconds": 3600}


@pytest.fixture
def ctx(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.sqlite3")
    store.start("project", "run", "input", "v1", LIMITS)
    return RunContext(store, "project", "run")


def scripted_brain(models, key=KEY):
    brain = GeminiReasoning(budget=1, model_name=next(iter(models)))
    brain.keys.active = lambda: key
    brain.keys.has_backup = lambda: False
    class Model:
        def __init__(self, answer):
            self.answer = answer
        def generate_content(self, prompt, **kwargs):
            if isinstance(self.answer, Exception):
                raise self.answer
            return SimpleNamespace(text=self.answer)
    objects = {name: Model(answer) for name, answer in models.items()}
    brain._model = objects[brain.model_name]
    brain.model = lambda: brain._model
    brain._usable_models = lambda: list(models)
    def build(name):
        brain.model_name = name
        brain._model = objects[name]
    brain._build = build
    return brain


def reserve(ctx, *, key=KEY, model="model-a", provider="gemini"):
    ctx.store.reserve(ctx.project, ctx.run, provider, "PRIVATE_PROMPT", 10,
                      cooldown_scopes=model_cooldown_scopes(provider, key, model))


@pytest.mark.parametrize("kind", ["daily_quota", "model_not_found", "auth_failure"])
def test_failure_is_durable_but_does_not_block_other_keys_runs_or_tenants(ctx, kind):
    scope = model_cooldown_scopes("gemini", KEY, "model-a")
    ctx.store.remember_model_failure(ctx.project, ctx.run, "gemini", scope, kind)
    fresh = RunContext(RuntimeStore(ctx.store.path), ctx.project, ctx.run)
    with pytest.raises(ModelCooldownActive) as caught:
        reserve(fresh)
    assert caught.value.kind == kind
    assert fresh.store.snapshot(ctx.project, ctx.run)["reserved_http_attempts"] == 0
    reserve(fresh, key="ANOTHER_TEST_CREDENTIAL")
    if kind == "auth_failure":
        with pytest.raises(ModelCooldownActive):
            reserve(fresh, model="model-b")
    else:
        reserve(fresh, model="model-b")
    reserve(fresh, provider="another_provider")
    for project, run in (("other_project", "run"), ("project", "other_run")):
        ctx.store.start(project, run, "input", "v1", LIMITS)
        reserve(RunContext(ctx.store, project, run))
    snapshot = json.dumps(fresh.store.snapshot(ctx.project, ctx.run))
    assert "PRIVATE" not in snapshot
    assert not any(token in snapshot for token in scope)


def test_provider_retry_after_recovers_without_permanent_blacklist(ctx, monkeypatch):
    clock = [runtime.time.time()]
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    scopes = model_cooldown_scopes("gemini", KEY, "model-a")
    ctx.store.remember_model_failure(ctx.project, ctx.run, "gemini", scopes, "rate_limit", 21)
    clock[0] += 20
    with pytest.raises(ModelCooldownActive):
        reserve(ctx)
    clock[0] += 1
    reserve(ctx)
    assert ctx.store.snapshot(ctx.project, ctx.run)["reserved_http_attempts"] == 1


def test_late_short_rate_limit_cannot_erase_daily_failure(ctx):
    scopes = model_cooldown_scopes("gemini", KEY, "model-a")
    ctx.store.remember_model_failure(ctx.project, ctx.run, "gemini", scopes, "daily_quota")
    ctx.store.remember_model_failure(ctx.project, ctx.run, "gemini", scopes, "rate_limit", 1)
    with pytest.raises(ModelCooldownActive) as caught:
        reserve(ctx)
    assert caught.value.kind == "daily_quota"


@pytest.mark.parametrize("kind,delay", [
    ("empty_response", 0), ("input_too_large", 0), ("unknown", 0),
    ("rate_limit", 0), ("rate_limit", float("nan")), ("rate_limit", float("inf")),
])
def test_content_failures_or_invalid_delays_do_not_disable_other_work(ctx, kind, delay):
    scopes = model_cooldown_scopes("gemini", KEY, "model-a")
    ctx.store.remember_model_failure(ctx.project, ctx.run, "gemini", scopes, kind, delay)
    reserve(ctx)


def test_cancel_still_precedes_shared_cooldown(ctx):
    scopes = model_cooldown_scopes("gemini", KEY, "model-a")
    ctx.store.remember_model_failure(ctx.project, ctx.run, "gemini", scopes, "daily_quota")
    ctx.store.cancel(ctx.project, ctx.run)
    with pytest.raises(ResearchCancelled):
        reserve(ctx)


@pytest.mark.parametrize("message", [
    "429 daily quota exceeded", "429 requests per minute limit; retry after 21s",
])
def test_sibling_can_use_healthy_fallback_after_known_primary_failure(ctx, message):
    models = {"model-a": RuntimeError(message), "model-b": "usable output"}
    first = scripted_brain(models)
    with bind(ctx):
        assert first.generate("question", "worker") == "usable output"
    assert first.attempts == 2
    second = scripted_brain(models)
    with bind(ctx):
        assert second.generate("question", "chief") == "usable output"
    assert second.attempts == second.successes == 1
    assert second.ledger.events[0]["attempt"] == 0
    assert second.ledger.events[0]["origin"] == "shared_run_cooldown"
    assert ctx.store.snapshot(ctx.project, ctx.run)["reserved_http_attempts"] == 3


def _run_isolated_worker(path):
    # Actual subprocess boundaries recreate the process-local state that caused
    # the live retry amplification; only the SQLite run is shared.
    code = """import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
import runpy
ns=runpy.run_path('tests/test_shared_model_cooldown.py')
from research_engine.company_worker import execute
def factory(budget):
 return ns['scripted_brain']({'model-a': RuntimeError('429 daily quota exceeded'),
                             'model-b': RuntimeError('404 model not found')})
result=execute({'role':'evidence','question':'fixture question','evidence':'fixture source',
                'runtime_context':{'path':sys.argv[1],'project':'project','run':'run'}},
                brain_factory=factory)
print(json.dumps(result))
"""
    completed = subprocess.run([sys.executable, "-c", code, path], capture_output=True,
                               text=True, timeout=20, cwd=Path(__file__).resolve().parents[1])
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_confirmed_outage_stops_later_worker_processes_and_chief(ctx):
    first = _run_isolated_worker(ctx.store.path)
    assert first["error"] == "no_model_output"
    assert first["accounting"]["actual_http_attempts"] == 2
    with ThreadPoolExecutor(max_workers=3) as pool:
        others = list(pool.map(_run_isolated_worker, [ctx.store.path] * 3))
    for row in others:
        assert row["error"] == "no_model_output"
        assert row["accounting"]["actual_http_attempts"] == 0
        assert row["accounting"]["successful_calls"] == 0
        assert row["accounting"]["model_switches"] == 0
    chief = scripted_brain({"model-a": "must not be called", "model-b": "must not be called"})
    with bind(ctx):
        assert chief.generate("question", "chief") == ""
    assert chief.attempts == chief.successes == 0
    snap = ctx.store.snapshot(ctx.project, ctx.run)
    assert snap["reserved_http_attempts"] == 2
    skipped = [r for r in snap["events"] if r["kind"] == "MODEL_COOLDOWN_SKIPPED"]
    assert len(skipped) == 8


def test_shared_failure_origin_survives_safe_hosted_report(ctx):
    from research_engine.models import ResearchResult
    from scripts.run_live_zero_cost_gate import evaluate_result
    from scripts.run_hosted_live_gate import summarize
    scopes = model_cooldown_scopes("gemini", KEY, "model-a")
    ctx.store.remember_model_failure(ctx.project, ctx.run, "gemini", scopes, "daily_quota")
    brain = scripted_brain({"model-a": "must not be called"})
    with bind(ctx):
        assert brain.generate("PRIVATE_QUESTION", "analysis") == ""
    result = ResearchResult(mode="COMPANY", status="RESEARCH INCOMPLETE",
                            api_accounting=brain.api_accounting()).to_dict()
    child = evaluate_result(result, required_depth_mode="COMPANY")
    public = summarize({"COMPANY": {"passed": False, "receipt": child}})["COMPANY"]
    assert public["passed"] is False
    assert public["summary"]["failure_events"][0] == {
        "kind": "daily_quota", "attempt": 0, "origin": "shared_run_cooldown",
    }
    assert "PRIVATE" not in json.dumps(public)


def simulated_clock(monkeypatch):
    clock = [runtime.time.time()]
    sleeps = []
    monkeypatch.setattr(runtime.time, "time", lambda: clock[0])
    def sleep(seconds):
        assert 0 < seconds <= 6
        sleeps.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(runtime.time, "sleep", sleep)
    return clock, sleeps


def test_chief_waits_for_sibling_minute_hold_then_gets_output(ctx, monkeypatch):
    clock, sleeps = simulated_clock(monkeypatch)
    scope = model_cooldown_scopes("gemini", KEY, "model-a")
    ctx.store.remember_model_failure(ctx.project, ctx.run, "gemini", scope, "rate_limit", 21)
    brain = scripted_brain({"model-a": "recovered draft"})
    fresh = RunContext(RuntimeStore(ctx.store.path), ctx.project, ctx.run)
    with bind(fresh):
        assert brain.generate("question", "chief") == "recovered draft"
    assert sum(sleeps) == pytest.approx(21)
    assert brain.attempts == brain.successes == 1
    assert brain.same_model_retries == brain.switched_models == 0
    assert brain.cooldown_recovery_cycles == 1
    assert ctx.store.snapshot(ctx.project, ctx.run)["reserved_http_attempts"] == 1


def test_real_rate_error_waits_once_and_retry_is_counted_only_on_admission(ctx, monkeypatch):
    _, sleeps = simulated_clock(monkeypatch)
    brain = scripted_brain({"model-a": "unused"})
    calls = []
    def generate(prompt, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("429 requests per minute; retry after 21s")
        return SimpleNamespace(text="recovered draft")
    brain._model.generate_content = generate
    with bind(ctx):
        assert brain.generate("question", "worker") == "recovered draft"
    assert len(calls) == brain.attempts == 2
    assert brain.same_model_retries == 1 and brain.cooldown_recovery_cycles == 1
    assert sum(sleeps) == pytest.approx(21)
    assert all(c["request_options"]["retry"] is None for c in calls)


def test_recovery_does_not_retry_forever_or_claim_success(ctx, monkeypatch):
    _, sleeps = simulated_clock(monkeypatch)
    brain = scripted_brain({"model-a": RuntimeError("429 per minute; retry after 21s")})
    with bind(ctx):
        assert brain.generate("question", "worker") == ""
    assert brain.attempts == 2 and brain.successes == 0
    assert brain.cooldown_recovery_cycles == 1
    assert sum(sleeps) == pytest.approx(21)


def test_deadline_refuses_wait_without_spending_an_attempt(ctx, monkeypatch):
    clock, sleeps = simulated_clock(monkeypatch)
    scoped = RunContext(ctx.store, ctx.project, ctx.run, deadline=clock[0] + 10)
    scope = model_cooldown_scopes("gemini", KEY, "model-a")
    ctx.store.remember_model_failure(ctx.project, ctx.run, "gemini", scope, "rate_limit", 21)
    brain = scripted_brain({"model-a": "must not run"})
    with bind(scoped):
        assert brain.generate("question", "worker") == ""
    assert brain.attempts == brain.same_model_retries == 0 and not sleeps


def test_cancel_interrupts_wait_before_generation(ctx, monkeypatch):
    _, _ = simulated_clock(monkeypatch)
    monkeypatch.setattr(runtime.time, "sleep", lambda seconds: ctx.store.cancel(ctx.project, ctx.run))
    with bind(ctx), pytest.raises(ResearchCancelled):
        runtime.wait_for_model_retry(21)
    assert ctx.store.snapshot(ctx.project, ctx.run)["reserved_http_attempts"] == 0


def test_recovery_respects_original_request_budget(ctx, monkeypatch):
    _, _ = simulated_clock(monkeypatch)
    ctx.store.start("limited", "run", "input", "v1", dict(LIMITS, http=1))
    scoped = RunContext(ctx.store, "limited", "run")
    brain = scripted_brain({"model-a": RuntimeError("429 per minute; retry after 21s")})
    with bind(scoped), pytest.raises(runtime.RuntimeBlocked, match="budget exhausted"):
        brain.generate("question", "worker")
    assert brain.attempts == 1 and brain.same_model_retries == 0
    assert ctx.store.snapshot("limited", "run")["reserved_http_attempts"] == 1


def test_provider_timeout_is_clipped_to_worker_deadline(ctx, monkeypatch):
    clock, _ = simulated_clock(monkeypatch)
    scoped = RunContext(ctx.store, ctx.project, ctx.run, deadline=clock[0] + 12)
    brain = scripted_brain({"model-a": "unused"})
    options = []
    def generate(prompt, **kwargs):
        options.append(kwargs["request_options"])
        return SimpleNamespace(text="draft")
    brain._model.generate_content = generate
    with bind(scoped):
        assert brain.generate("question", "worker") == "draft"
    assert 0 < options[0]["timeout"] <= 12


def test_parent_passes_a_bounded_deadline_without_mutating_payload(ctx, monkeypatch):
    from research_engine import research_company as company
    clock, _ = simulated_clock(monkeypatch)
    payload = {"runtime_context": ctx.wire(), "role": "evidence"}
    captured = []
    def run(*args, **kwargs):
        captured.append(json.loads(kwargs["input"]))
        return SimpleNamespace(returncode=0, stdout='{"answer":"draft"}')
    monkeypatch.setattr(company.subprocess, "run", run)
    assert company.process_worker(payload, timeout=30)["answer"] == "draft"
    assert "deadline" not in payload["runtime_context"]
    assert captured[0]["runtime_context"]["deadline"] == clock[0] + 29


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), True, "tomorrow", -1])
def test_invalid_operation_deadlines_fail_closed(ctx, deadline):
    with pytest.raises(runtime.RuntimeBlocked):
        RunContext(ctx.store, ctx.project, ctx.run, deadline=deadline)
