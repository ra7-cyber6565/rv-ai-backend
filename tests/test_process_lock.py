"""Offline tests for the stdlib single-writer file lock."""
from __future__ import annotations

import pytest

from utils.process_lock import ExclusiveProcessFileLock, ProcessLockError


def test_second_lock_on_same_path_fails_until_first_releases(tmp_path):
    path = str(tmp_path / "runtime.lock")
    first = ExclusiveProcessFileLock(path)
    second = ExclusiveProcessFileLock(path)
    first.acquire()
    try:
        with pytest.raises(ProcessLockError):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    assert second.acquired is True
    second.release()
    assert second.acquired is False


def test_context_manager_releases_lock(tmp_path):
    path = str(tmp_path / "runtime.lock")
    with ExclusiveProcessFileLock(path) as first:
        assert first.acquired is True
    assert first.acquired is False

    with ExclusiveProcessFileLock(path) as second:
        assert second.acquired is True
