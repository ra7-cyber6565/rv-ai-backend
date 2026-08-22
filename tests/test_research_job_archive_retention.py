"""Archive-aware retention tests for durable asynchronous research results."""
from __future__ import annotations

import json
import time

import pytest

from utils.research_jobs import ResearchJobRunner


class _ArchiveIntentOnly:
    def __init__(self, *, intent_ok: bool = True):
        self.intent_ok = intent_ok
        self.submissions: list[tuple[str, str]] = []

    def archive_required(self) -> bool:
        return True

    def submit_file(self, local_path: str, remote_path: str):
        self.submissions.append((local_path, remote_path))
        return {
            "enabled": True,
            "accepted": False,
            "intent_recorded": self.intent_ok,
            "reason": "provider_not_ready" if self.intent_ok else "intent_failed",
        }

    def local_delete_allowed(self, local_path: str, remote_path: str) -> bool:
        return False


def _wait(runner: ResearchJobRunner, job_id: str, timeout: float = 2.0):
    end = time.time() + timeout
    while time.time() < end:
        item = runner.get(job_id, include_result=True)
        if item and item["status"] in {"completed", "failed", "interrupted"}:
            return item
        time.sleep(0.01)
    raise AssertionError("job timeout")


def test_history_pruning_keeps_unverified_local_bytes_when_archive_intent_exists(tmp_path):
    store = tmp_path / "jobs.json"
    archive = _ArchiveIntentOnly(intent_ok=True)
    runner = ResearchJobRunner(
        max_workers=1,
        max_jobs=1,
        store_path=str(store),
        persist=True,
        archive_runtime_override=archive,
    )
    first = runner.submit(
        project_id="p",
        question="first",
        mode="DEEP",
        custom=None,
        run=lambda **_: {"answer": "one"},
    )
    assert _wait(runner, first.job_id)["status"] == "completed"
    ledger = json.loads(store.read_text(encoding="utf-8"))
    first_row = next(row for row in ledger["jobs"] if row["job_id"] == first.job_id)
    first_path = store.parent / "results" / first_row["result_file"]
    assert first_path.exists()
    assert archive.submissions

    second = runner.submit(
        project_id="p",
        question="second",
        mode="DEEP",
        custom=None,
        run=lambda **_: {"answer": "two"},
    )
    assert _wait(runner, second.job_id)["status"] == "completed"

    # History can stay bounded, but the only unverified local copy survives.
    assert runner.get(first.job_id) is None
    assert first_path.exists()
    assert any(remote == f"research-results/{first.job_id}.json.gz" for _, remote in archive.submissions)
    runner.close()


def test_pruning_fails_closed_if_enabled_archive_intent_cannot_be_persisted(tmp_path):
    store = tmp_path / "jobs.json"
    archive = _ArchiveIntentOnly(intent_ok=False)
    runner = ResearchJobRunner(
        max_workers=1,
        max_jobs=1,
        store_path=str(store),
        persist=True,
        archive_runtime_override=archive,
    )
    first = runner.submit(
        project_id="p",
        question="first",
        mode="DEEP",
        custom=None,
        run=lambda **_: {"answer": "one"},
    )
    done = _wait(runner, first.job_id)
    assert done["status"] == "completed"
    assert "local result delete nahi kiya jayega" in done["storage_warning"].lower()
    ledger = json.loads(store.read_text(encoding="utf-8"))
    row = next(row for row in ledger["jobs"] if row["job_id"] == first.job_id)
    first_path = store.parent / "results" / row["result_file"]
    assert first_path.exists()

    with pytest.raises(RuntimeError, match="archive"):
        runner.submit(
            project_id="p",
            question="second",
            mode="DEEP",
            custom=None,
            run=lambda **_: {"answer": "two"},
        )
    assert runner.get(first.job_id) is not None
    assert first_path.exists()
    runner.close()
