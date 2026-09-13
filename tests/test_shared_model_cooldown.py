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
