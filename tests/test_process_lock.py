"""Offline tests for the stdlib cross-process file locks."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from utils.process_lock import (
    ExclusiveProcessFileLock,
    ProcessLockError,
    bounded_process_file_lock,
)


ROOT = Path(__file__).resolve().parents[1]


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


def test_bounded_transaction_lock_is_reentrant_for_same_thread(tmp_path):
    path = str(tmp_path / "transaction.lock")
    with bounded_process_file_lock(path, timeout_seconds=0.5):
        with bounded_process_file_lock(path, timeout_seconds=0.01):
            # A separate raw lock still sees the outer OS lock. Re-entrancy is
            # provided by the bounded helper, not by weakening the OS contract.
            with pytest.raises(ProcessLockError):
                ExclusiveProcessFileLock(path).acquire()

    with ExclusiveProcessFileLock(path) as raw:
        assert raw.acquired is True


def _holder_process(lock_path: str, hold_seconds: float) -> subprocess.Popen[str]:
    code = (
        "import time\n"
        "from utils.process_lock import ExclusiveProcessFileLock\n"
        f"lock=ExclusiveProcessFileLock({lock_path!r})\n"
        "lock.acquire()\n"
        "print('READY', flush=True)\n"
        f"time.sleep({float(hold_seconds)!r})\n"
        "lock.release()\n"
    )
    env = dict(os.environ)
    inherited = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + inherited if inherited else "")
    return subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_ready(proc: subprocess.Popen[str]) -> None:
    assert proc.stdout is not None
    line = proc.stdout.readline().strip()
    if line != "READY":
        stderr = proc.stderr.read() if proc.stderr is not None else ""
        proc.kill()
        raise AssertionError(f"lock holder did not start: stdout={line!r} stderr={stderr!r}")


def test_bounded_transaction_waits_for_real_other_process_then_acquires(tmp_path):
    path = str(tmp_path / "cross-process.lock")
    proc = _holder_process(path, 0.30)
    try:
        _wait_ready(proc)
        started = time.monotonic()
        with bounded_process_file_lock(path, timeout_seconds=2.0, poll_seconds=0.02):
            elapsed = time.monotonic() - started
            assert elapsed >= 0.10
        assert proc.wait(timeout=2) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)


def test_bounded_transaction_fails_closed_when_other_process_outlives_deadline(tmp_path):
    path = str(tmp_path / "timeout.lock")
    proc = _holder_process(path, 0.80)
    try:
        _wait_ready(proc)
        with pytest.raises(ProcessLockError, match="Timed out"):
            with bounded_process_file_lock(path, timeout_seconds=0.08, poll_seconds=0.01):
                pass
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=2)

    # A timeout must not poison the helper's local re-entrancy bookkeeping.
    with bounded_process_file_lock(path, timeout_seconds=0.5):
        pass
