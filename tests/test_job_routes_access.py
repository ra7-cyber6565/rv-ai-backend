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
