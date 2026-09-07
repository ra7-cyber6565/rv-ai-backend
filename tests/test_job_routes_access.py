"""Route-level tests for private research-job polling capability."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from api import job_routes


class FakeAccess:
    def __init__(self, valid: bool):
        self.valid = valid
        self.calls = []

    def verify(self, job_id, token):
        self.calls.append((job_id, token))
        return self.valid


class FakeRunner:
    def __init__(self, item=None):
        self.item = item
        self.calls = []

    def get(self, job_id, include_result=False):
        self.calls.append((job_id, include_result))
        return self.item


def test_missing_or_wrong_capability_does_not_even_probe_job_store(monkeypatch):
    access = FakeAccess(False)
    runner = FakeRunner({"status": "completed"})
    monkeypatch.setattr(job_routes, "job_access", access)
    monkeypatch.setattr(job_routes, "runner", runner)

    with pytest.raises(HTTPException) as exc:
        job_routes._authorized_job("a" * 32, None)
    assert exc.value.status_code == 404
    assert runner.calls == [], "wrong token par job existence probe bhi nahi hona chahiye"


def test_valid_capability_but_unknown_job_returns_same_404(monkeypatch):
    monkeypatch.setattr(job_routes, "job_access", FakeAccess(True))
    monkeypatch.setattr(job_routes, "runner", FakeRunner(None))

    with pytest.raises(HTTPException) as exc:
        job_routes._authorized_job("a" * 32, "private-token")
    assert exc.value.status_code == 404


def test_valid_capability_returns_job_and_can_request_result(monkeypatch):
    item = {"job_id": "a" * 32, "status": "completed", "result": {"answer": "ok"}}
    runner = FakeRunner(item)
    monkeypatch.setattr(job_routes, "job_access", FakeAccess(True))
    monkeypatch.setattr(job_routes, "runner", runner)

    got = job_routes._authorized_job("a" * 32, "private-token", include_result=True)
    assert got == item
    assert runner.calls == [("a" * 32, True)]


def test_storage_full_reports_preserved_results_without_exposing_paths(monkeypatch):
    from types import SimpleNamespace
    from utils.storage_quota import StorageQuotaError
    class FullRunner:
        def submit(self, **kwargs):
            raise StorageQuotaError("PRIVATE_DATA_PATH secret=not-public")
    monkeypatch.setattr(job_routes, "require_project_access", lambda *args: None)
    monkeypatch.setattr(job_routes, "job_access", SimpleNamespace(status=lambda: {"job_capability_tokens_ready": True}))
    monkeypatch.setattr(job_routes, "runner", FullRunner())
    with pytest.raises(HTTPException) as exc:
        job_routes.start_research_job(job_routes.ResearchJobRequest(question="test"), "valid")
    assert exc.value.status_code == 507
    assert "safe" in exc.value.detail and "paused" in exc.value.detail
    assert "PRIVATE" not in exc.value.detail and "secret=" not in exc.value.detail
