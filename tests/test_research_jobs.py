"""Offline tests for long-running research job lifecycle."""
from __future__ import annotations

import time

from utils.research_jobs import ResearchJobRunner


def _wait(runner: ResearchJobRunner, job_id: str, timeout: float = 2.0):
    end = time.time() + timeout
    while time.time() < end:
        item = runner.get(job_id, include_result=True)
        if item and item["status"] in {"completed", "failed"}:
            return item
        time.sleep(0.01)
    raise AssertionError("job timeout in offline test")


def test_job_returns_result_after_background_execution():
    runner = ResearchJobRunner(max_workers=1, max_jobs=5)

    def fake_run(**kwargs):
        return {"answer": "ok", "job_id": kwargs["job_id"]}

    job = runner.submit(
        project_id="p1",
        question="test question",
        mode="DEEP",
        custom=None,
        run=fake_run,
    )
    done = _wait(runner, job.job_id)
    assert done["status"] == "completed"
    assert done["result"]["answer"] == "ok"
    assert done["result"]["job_id"] == job.job_id


def test_job_failure_is_captured_instead_of_crashing_request():
    runner = ResearchJobRunner(max_workers=1, max_jobs=5)

    def broken(**kwargs):
        raise RuntimeError("provider unavailable")

    job = runner.submit(
        project_id="p1",
        question="test failure",
        mode="MAXIMUM",
        custom=None,
        run=broken,
    )
    done = _wait(runner, job.job_id)
    assert done["status"] == "failed"
    assert "provider unavailable" in done["error"]


def test_empty_question_is_rejected_before_worker_submission():
    runner = ResearchJobRunner(max_workers=1, max_jobs=5)
    try:
        runner.submit(project_id="p", question="   ", mode="DEEP", custom=None, run=lambda **_: {})
    except ValueError:
        pass
    else:
        raise AssertionError("empty question should fail")
