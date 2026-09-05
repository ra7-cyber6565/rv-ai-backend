"""Exercise real worker/company and private API boundaries with fixture providers."""
import json
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from research_engine import research_company as company
from research_engine.depth import get_depth_config
from research_engine.models import EvidencePack, SourceRecord, SourceType
from utils.research_runtime import RuntimeStore, RunContext, bind, checkpoint, digest


def test_company_restart_reuses_workers_and_executes_numeric_artifact(tmp_path):
    runtime = RuntimeStore(tmp_path / "state.sqlite3")
    runtime.start("p", "r", "i", "v", {"http": 32, "input_bytes": 1000000, "output_tokens": 192000, "seconds": 3600})
    ctx = RunContext(runtime, "p", "r")
    called = []
    def worker(payload):
        called.append(payload["role"])
        report = {"summary": "Fixture evidence", "claims": [], "hypotheses": [],
                  "limitations": [], "assumptions": [], "contradictions": [], "remaining_questions": []}
        if payload["role"] == "validation":
            report["tool_requests"] = [{"tool": "numeric", "arguments": {"code": "result = 2 * 3", "inputs": {}}}]
        return {"answer": json.dumps(report), "accounting": {}, "accounting_complete": True, "output_truncated": False}
    pack = EvidencePack(question="Q", sources=[SourceRecord(source_id="S1", title="Fixture", source_type=SourceType.PAPER)])
    with bind(ctx):
        first = company.run_company("Q", pack, get_depth_config("COMPANY"), worker=worker)
        second = company.run_company("Q", pack, get_depth_config("COMPANY"), worker=worker)
    assert len(called) == 4
    assert all(w["restored_from_checkpoint"] for w in second["workers"])
    assert [w["worker_id"] for w in first["workers"]] == [w["worker_id"] for w in second["workers"]]
    tool = next(w for w in second["workers"] if w["role"] == "validation")["report"]["tool_results"][0]
    assert tool["state"] == "EXECUTED" and tool["result"]["outputs"]["result"] == 6
    assert tool["physical_experiment"] is False
    assert second["event_durability"] == "SQLITE_TRANSACTION"


def test_evidence_pack_round_trip_retains_types_and_hash(tmp_path):
    runtime = RuntimeStore(tmp_path / "state.sqlite3")
    runtime.start("p", "r", "i", "v", {"http": 1, "input_bytes": 100, "output_tokens": 10, "seconds": 3600})
    pack = EvidencePack(sources=[SourceRecord(source_id="S1", source_type=SourceType.PAPER)])
    with bind(RunContext(runtime, "p", "r")):
        checkpoint("read", {}, lambda: {"pack": pack})
        loaded = checkpoint("read", {}, lambda: pytest.fail("must reuse"))["pack"]
    assert loaded.sources[0].source_type is SourceType.PAPER
    assert digest(loaded) == digest(pack)


def test_cancel_and_resume_require_capability_before_mutation(monkeypatch):
    from api import job_routes
    calls = []
    monkeypatch.setattr(job_routes.job_access, "verify", lambda *a: False)
    monkeypatch.setattr(job_routes.runner, "cancel", lambda *a: calls.append(a))
    monkeypatch.setattr(job_routes.runner, "resume", lambda *a: calls.append(a))
    for endpoint in (job_routes.cancel_research_job, job_routes.resume_research_job):
        with pytest.raises(HTTPException) as exc:
            endpoint("secret-job", "wrong-token")
        assert exc.value.status_code == 404
    assert calls == []


def test_job_cancel_does_not_later_publish_completed_result(tmp_path, monkeypatch):
    from utils.research_jobs import ResearchJobRunner
    from utils import research_runtime
    state = RuntimeStore(tmp_path / "state.sqlite3")
    monkeypatch.setattr(research_runtime, "RuntimeStore", lambda: state)
    runner = ResearchJobRunner(store_path=str(tmp_path / "jobs.json"), enforce_process_lock=False)
    began, finish = threading.Event(), threading.Event()
    def work(**kwargs):
        began.set()
        assert finish.wait(5)
        return {"answer": "too late"}
    try:
        job = runner.submit(project_id="p", question="Q", mode="COMPANY", custom={}, run=work)
        assert began.wait(5)
        assert runner.cancel(job.job_id)
        finish.set()
        runner.close()
        assert runner.get(job.job_id, include_result=True)["status"] == "cancelled"
        assert "result" not in runner.get(job.job_id, include_result=True)
    finally:
        finish.set()
        runner.close()


def test_corrected_source_cannot_return_old_strong_api_result(monkeypatch, tmp_path):
    from api import job_routes
    from utils import governed_memory
    memory = governed_memory.GovernedMemory(RuntimeStore(tmp_path / "state.sqlite3"))
    memory.record_result("p", "j", {"answer": "strong old claim", "sources": [{"url": "https://example.org/a"}]})
    memory.invalidate_source("p", "https://example.org/a", "Withdrawn source")
    monkeypatch.setattr(governed_memory, "GovernedMemory", lambda: memory)
    monkeypatch.setattr(job_routes, "_authorized_job", lambda *a, **kw: {
        "project_id": "p", "status": "completed", "result": {"answer": "strong old claim", "status": "COMPLETE"}})
    result = job_routes.research_job_result("j", "fixture-capability")
    assert result["status"] == "PARTIAL"
    assert result["evidence_level"] == "UNVERIFIED"
    assert "strong old claim" not in result["answer"]
