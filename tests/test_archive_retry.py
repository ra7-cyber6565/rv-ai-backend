"""Offline tests for durable archive retry queue."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from utils.archive_retry import ArchiveRetryQueue


def _file(tmp_path: Path, name: str = "data.bin", content: bytes = b"abc") -> str:
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


def test_enqueue_is_deduplicated_by_provider_remote_and_hash(tmp_path):
    queue = ArchiveRetryQueue(str(tmp_path / "retry.json"))
    path = _file(tmp_path)
    one = queue.enqueue(local_path=path, remote_path="/a/data.bin", provider="drive", now=100)
    two = queue.enqueue(local_path=path, remote_path="/a/data.bin", provider="drive", now=101)
    assert one["key"] == two["key"]
    assert len(queue.items()) == 1


def test_due_respects_next_attempt_time(tmp_path):
    queue = ArchiveRetryQueue(str(tmp_path / "retry.json"))
    path = _file(tmp_path)
    item = queue.enqueue(local_path=path, remote_path="/a", provider="drive", now=100)
    assert queue.due(now=100) == []
    assert queue.due(now=item["next_attempt_at"])[0]["key"] == item["key"]


def test_failure_increments_attempts_and_keeps_pending(tmp_path):
    queue = ArchiveRetryQueue(str(tmp_path / "retry.json"))
    path = _file(tmp_path)
    item = queue.enqueue(local_path=path, remote_path="/a", provider="drive", now=100)
    failed = queue.mark_failure(item["key"], "offline", now=200)
    assert failed["attempts"] == 1
    assert failed["status"] == "pending"
    assert failed["last_error"] == "offline"


def test_success_removes_queue_entry(tmp_path):
    queue = ArchiveRetryQueue(str(tmp_path / "retry.json"))
    path = _file(tmp_path)
    item = queue.enqueue(local_path=path, remote_path="/a", provider="drive", now=100)
    queue.mark_success(item["key"])
    assert queue.items() == []


def test_summary_reports_missing_local_copy(tmp_path):
    queue = ArchiveRetryQueue(str(tmp_path / "retry.json"))
    path = Path(_file(tmp_path))
    queue.enqueue(local_path=str(path), remote_path="/a", provider="drive", now=100)
    path.unlink()
    summary = queue.summary()
    assert summary["pending"] == 1
    assert summary["missing_local_files"] == 1
    assert summary["providers"] == {"drive": 1}


def test_parallel_enqueue_does_not_drop_retry_records(tmp_path):
    queue = ArchiveRetryQueue(str(tmp_path / "retry.json"))
    paths = [
        _file(tmp_path, name=f"data-{i}.bin", content=f"payload-{i}".encode())
        for i in range(24)
    ]

    def add(index: int) -> None:
        queue.enqueue(
            local_path=paths[index],
            remote_path=f"/archive/data-{index}.bin",
            provider="drive",
            now=100 + index,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(add, range(len(paths))))

    rows = queue.items()
    assert len(rows) == len(paths)
    assert {row["remote_path"] for row in rows} == {
        f"/archive/data-{i}.bin" for i in range(len(paths))
    }
