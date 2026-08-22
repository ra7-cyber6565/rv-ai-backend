"""Completed job results retain a bounded public-safe research progress trail."""
from __future__ import annotations

from api import job_routes


def _completed(result=None):
    return {
        "job_id": "job-safe",
        "status": "completed",
        "result": result or {"answer": "final answer", "sources": []},
    }


def test_completed_result_carries_progress_without_mutating_stored_result(monkeypatch):
    stored = {"answer": "final answer", "sources": []}
    monkeypatch.setattr(
        job_routes,
        "_authorized_job",
        lambda *args, **kwargs: _completed(stored),
    )
    monkeypatch.setattr(
        job_routes,
        "get_progress",
        lambda _job_id: {
            "job_id": "must-not-leak",
            "question": "private question",
            "current_stage": "COMPLETE",
            "stages_done": 12,
            "sources_discovered": 18,
            "documents_processed": 2,
            "evidence_conflicts_found": 3,
            "full_text_sources_read": 5,
            "gemini_calls_used": 3,
            "started_at": "private timestamp",
            "log": [
                {"stage": "EVIDENCE_ANALYSIS", "note": "contradiction + independence check"},
                {"stage": "HYPOTHESIS", "note": "3 hypotheses"},
                {"stage": "COMPLETE", "note": "answer ready"},
            ],
        },
    )

    response = job_routes.research_job_result("job-safe", "opaque-token")

    assert response["answer"] == "final answer"
    assert "research_progress" not in stored
    progress = response["research_progress"]
    assert progress["available"] is True
    assert progress["current_stage"] == "COMPLETE"
    assert progress["stages_done"] == 12
    assert progress["sources_discovered"] == 18
    assert progress["evidence_conflicts_found"] == 3
    assert [row["stage"] for row in progress["log"]] == [
        "EVIDENCE_ANALYSIS", "HYPOTHESIS", "COMPLETE",
    ]
    dumped = str(progress).lower()
    assert "job-safe" not in dumped
    assert "private question" not in dumped
    assert "private timestamp" not in dumped


def test_progress_snapshot_is_bounded_and_redacts_raw_provider_detail(monkeypatch):
    rows = [
        {"stage": "READING", "note": f"safe row {index}"}
        for index in range(30)
    ]
    rows.extend([
        {"stage": "NOT_A_STAGE", "note": "must be dropped"},
        {"stage": "SYNTHESIS", "note": "Traceback ResourceExhausted api_key=SECRET"},
    ])
    monkeypatch.setattr(
        job_routes,
        "get_progress",
        lambda _job_id: {
            "current_stage": "NOT_A_STAGE",
            "stages_done": 999,
            "sources_discovered": -4,
            "log": rows,
        },
    )

    progress = job_routes._progress_result_snapshot("job-safe")

    assert progress["current_stage"] == ""
    assert progress["stages_done"] == len(job_routes.STAGES)
    assert progress["sources_discovered"] == 0
    assert len(progress["log"]) <= job_routes._PROGRESS_LOG_LIMIT
    dumped = str(progress).lower()
    assert "not_a_stage" not in dumped
    for raw in ("traceback", "resourceexhausted", "secret", "api_key"):
        assert raw not in dumped
    assert "technical provider detail hidden" in dumped


def test_missing_in_memory_progress_is_disclosed_without_faking_a_trail(monkeypatch):
    monkeypatch.setattr(job_routes, "get_progress", lambda _job_id: {"error": "Job not found"})
    assert job_routes._progress_result_snapshot("old-job") == {"available": False}
