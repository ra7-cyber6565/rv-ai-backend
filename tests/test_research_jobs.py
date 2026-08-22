"""Offline tests for long-running research job lifecycle."""
from __future__ import annotations

import json
import time

import pytest

from utils.research_jobs import ResearchJobRunner


def _wait(runner: ResearchJobRunner, job_id: str, timeout: float = 2.0):
    end = time.time() + timeout
    while time.time() < end:
        item = runner.get(job_id, include_result=True)
        if item and item["status"] in {"completed", "failed", "interrupted"}:
            return item
        time.sleep(0.01)
    raise AssertionError("job timeout in offline test")


def test_job_returns_result_after_background_execution():
    runner = ResearchJobRunner(max_workers=1, max_jobs=5, persist=False)

    def fake_run(**kwargs):
        return {"answer": "ok", "job_id": kwargs["job_id"]}

    job = runner.submit(project_id="p1", question="test question", mode="DEEP", custom=None, run=fake_run)
    done = _wait(runner, job.job_id)
    assert done["status"] == "completed"
    assert done["result"]["answer"] == "ok"
    assert done["result"]["job_id"] == job.job_id
    runner.close()


def test_job_failure_is_captured_instead_of_crashing_request():
    runner = ResearchJobRunner(max_workers=1, max_jobs=5, persist=False)

    def broken(**kwargs):
        raise RuntimeError("provider unavailable")

    job = runner.submit(project_id="p1", question="test failure", mode="MAXIMUM", custom=None, run=broken)
    done = _wait(runner, job.job_id)
    assert done["status"] == "failed"
    assert "provider unavailable" in done["error"]
    runner.close()


def test_raw_provider_trace_and_secret_are_not_exposed():
    runner = ResearchJobRunner(max_workers=1, max_jobs=5, persist=False)

    def broken(**kwargs):
        raise RuntimeError(
            "ResourceExhausted protobuf google.rpc token=super-secret-value "
            "https://provider.example/v1/raw"
        )

    job = runner.submit(project_id="p1", question="safe failure", mode="DEEP", custom=None, run=broken)
    done = _wait(runner, job.job_id)
    assert done["status"] == "failed"
    lowered = done["error"].lower()
    assert "super-secret-value" not in lowered
    assert "protobuf" not in lowered
    assert "resourceexhausted" not in lowered
    assert "technical details hidden" in lowered
    runner.close()


def test_empty_question_is_rejected_before_worker_submission():
    runner = ResearchJobRunner(max_workers=1, max_jobs=5, persist=False)
    try:
        runner.submit(project_id="p", question="   ", mode="DEEP", custom=None, run=lambda **_: {})
    except ValueError:
        pass
    else:
        raise AssertionError("empty question should fail")
    runner.close()


def test_completed_result_survives_runner_restart_in_separate_gzip_file(tmp_path):
    store = tmp_path / "jobs.json"
    runner1 = ResearchJobRunner(max_workers=1, max_jobs=5, store_path=str(store), persist=True)
    job = runner1.submit(
        project_id="p", question="durable test", mode="DEEP", custom=None,
        run=lambda **_: {"answer": "saved", "sources": [{"title": "paper"}]},
    )
    first = _wait(runner1, job.job_id)
    assert first["status"] == "completed"
    assert first["result_durable"] is True

    ledger = json.loads(store.read_text(encoding="utf-8"))
    row = next(row for row in ledger["jobs"] if row["job_id"] == job.job_id)
    assert row["result"] is None
    assert row["result_file"].endswith(".json.gz")
    result_path = store.parent / "results" / row["result_file"]
    assert result_path.is_file()
    runner1.close()

    runner2 = ResearchJobRunner(max_workers=1, max_jobs=5, store_path=str(store), persist=True)
    restored = runner2.get(job.job_id, include_result=True)
    assert restored is not None
    assert restored["status"] == "completed"
    assert restored["result_durable"] is True
    assert restored["result"]["answer"] == "saved"
    runner2.close()


def test_second_process_owner_is_blocked_for_same_store(tmp_path):
    store = tmp_path / "jobs.json"
    runner1 = ResearchJobRunner(max_workers=1, max_jobs=5, store_path=str(store), persist=True)
    try:
        with pytest.raises(RuntimeError, match="single worker"):
            ResearchJobRunner(max_workers=1, max_jobs=5, store_path=str(store), persist=True)
    finally:
        runner1.close()

    runner2 = ResearchJobRunner(max_workers=1, max_jobs=5, store_path=str(store), persist=True)
    runner2.close()


def test_oversized_result_is_compacted_and_disclosed(tmp_path):
    store = tmp_path / "jobs.json"
    runner = ResearchJobRunner(max_workers=1, max_jobs=5, store_path=str(store), persist=True, max_result_bytes=1024)
    huge = "x" * 50_000
    job = runner.submit(
        project_id="p", question="large result", mode="MAXIMUM", custom=None,
        run=lambda **_: {
            "answer": "important final answer",
            "debug_blob": huge,
            "sources": [{"title": f"source-{i}", "raw": huge} for i in range(30)],
        },
    )
    done = _wait(runner, job.job_id)
    assert done["status"] == "completed"
    assert done["result_durable"] is True
    assert done["result_compacted"] is True
    assert done["result_bytes"] > 1024
    assert done["result"].get("_storage_compacted") is True
    assert done["result"].get("answer") == "important final answer"
    runner.close()


def test_pruning_old_job_removes_external_result_file(tmp_path):
    store = tmp_path / "jobs.json"
    runner = ResearchJobRunner(max_workers=1, max_jobs=1, store_path=str(store), persist=True)
    first = runner.submit(
        project_id="p", question="first", mode="DEEP", custom=None, run=lambda **_: {"answer": "one"}
    )
    assert _wait(runner, first.job_id)["status"] == "completed"
    ledger = json.loads(store.read_text(encoding="utf-8"))
    first_row = next(row for row in ledger["jobs"] if row["job_id"] == first.job_id)
    first_path = store.parent / "results" / first_row["result_file"]
    assert first_path.exists()

    second = runner.submit(
        project_id="p", question="second", mode="DEEP", custom=None, run=lambda **_: {"answer": "two"}
    )
    assert _wait(runner, second.job_id)["status"] == "completed"
    assert runner.get(first.job_id) is None
    assert not first_path.exists()
    runner.close()


def test_previously_running_job_is_marked_interrupted(tmp_path):
    store = tmp_path / "jobs.json"
    store.write_text(json.dumps({
        "version": 1,
        "jobs": [{
            "job_id": "old-job", "project_id": "p", "question": "was running", "mode": "MAXIMUM",
            "status": "running", "created_at": 1.0, "started_at": 2.0, "finished_at": None,
            "result": None, "error": "",
        }],
    }), encoding="utf-8")

    runner = ResearchJobRunner(max_workers=1, max_jobs=5, store_path=str(store), persist=True)
    restored = runner.get("old-job")
    assert restored is not None
    assert restored["status"] == "interrupted"
    assert restored["result_durable"] is False
    assert "restart" in restored["error"].lower()
    runner.close()


def test_old_inline_completed_result_is_migrated(tmp_path):
    store = tmp_path / "jobs.json"
    store.write_text(json.dumps({
        "version": 1,
        "jobs": [{
            "job_id": "old-complete", "project_id": "p", "question": "old result", "mode": "DEEP",
            "status": "completed", "created_at": 1.0, "started_at": 2.0, "finished_at": 3.0,
            "result": {"answer": "legacy saved"}, "error": "",
        }],
    }), encoding="utf-8")

    runner = ResearchJobRunner(max_workers=1, max_jobs=5, store_path=str(store), persist=True)
    restored = runner.get("old-complete", include_result=True)
    assert restored is not None
    assert restored["result_durable"] is True
    assert restored["result"]["answer"] == "legacy saved"
    ledger = json.loads(store.read_text(encoding="utf-8"))
    row = ledger["jobs"][0]
    assert row["result"] is None
    assert row["result_file"].endswith(".json.gz")
    runner.close()


def test_tampered_absolute_result_path_is_never_read_or_deleted(tmp_path):
    store = tmp_path / "jobs.json"
    victim = tmp_path / "do-not-delete.txt"
    victim.write_text("private data", encoding="utf-8")
    store.write_text(json.dumps({
        "version": 2,
        "jobs": [{
            "job_id": "tampered", "project_id": "p", "question": "tampered", "mode": "DEEP",
            "status": "completed", "created_at": 1.0, "started_at": 2.0, "finished_at": 3.0,
            "result": None, "error": "", "result_file": str(victim.resolve()), "result_bytes": 10,
            "result_compacted": False, "durable": True, "storage_warning": "",
        }],
    }), encoding="utf-8")

    runner = ResearchJobRunner(max_workers=1, max_jobs=5, store_path=str(store), persist=True)
    restored = runner.get("tampered", include_result=True)
    assert restored is not None
    assert restored["result_durable"] is False
    assert restored["result"].get("_result_unavailable") is True
    assert "unsafe path" in restored["storage_warning"].lower()
    assert victim.read_text(encoding="utf-8") == "private data"
    runner.close()
    assert victim.exists()


def test_corrupt_json_is_quarantined_but_valid_write_failure_is_not(tmp_path, monkeypatch):
    corrupt = tmp_path / "corrupt-jobs.json"
    corrupt.write_text("{not-json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="corrupt"):
        ResearchJobRunner(max_workers=1, max_jobs=5, store_path=str(corrupt), persist=True)
    assert not corrupt.exists()
    assert list(tmp_path.glob("corrupt-jobs.json.corrupt-*"))

    valid = tmp_path / "valid-jobs.json"
    valid.write_text(json.dumps({"version": 2, "jobs": []}), encoding="utf-8")

    def fail_write(self):
        raise OSError("simulated disk write failure")

    monkeypatch.setattr(ResearchJobRunner, "_persist_locked", fail_write)
    with pytest.raises(OSError, match="disk write failure"):
        ResearchJobRunner(max_workers=1, max_jobs=5, store_path=str(valid), persist=True)
    assert valid.exists()
    assert not list(tmp_path.glob("valid-jobs.json.corrupt-*"))
