"""Stdlib-only cross-process locks for durable runtime stores.

Infinity Research AI deliberately avoids adding Redis/database infrastructure just
to coordinate a free single-machine deployment. JSON ledgers therefore need two
different locking contracts:

``ExclusiveProcessFileLock``
    Non-blocking, lifetime lock used when an entire component must have exactly
    one writer process (for example the durable research-job store).

``bounded_process_file_lock``
    Short transaction lock used around read/modify/write operations. It waits for
    another process for a bounded amount of time, is re-entrant for the same
    thread/path, and always releases the OS lock. This lets independent backend
    processes share small atomic JSON ledgers without silently losing updates.

Both locks are advisory: every writer to a protected file must cooperate.
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator


class ProcessLockError(RuntimeError):
    pass


class ExclusiveProcessFileLock:
    """Hold an exclusive non-blocking lock for this object's lifetime."""

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self._handle: BinaryIO | None = None
        self._backend = ""

    @property
    def acquired(self) -> bool:
        return self._handle is not None

    def acquire(self) -> None:
        if self._handle is not None:
            return
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)

            if os.name == "nt":
                import msvcrt

                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise ProcessLockError(
                        f"Runtime store already locked by another process: {self.path}"
                    ) from exc
                self._backend = "msvcrt"
            else:
                import fcntl

                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise ProcessLockError(
                        f"Runtime store already locked by another process: {self.path}"
                    ) from exc
                self._backend = "flock"

            # Helpful diagnostics only. The file contents are not used to decide
            # lock ownership; the OS lock is the source of truth.
            handle.seek(0)
            handle.truncate()
            handle.write(f"pid={os.getpid()}\n".encode("ascii", errors="ignore"))
            handle.flush()
            os.fsync(handle.fileno())
            handle.seek(0)
            self._handle = handle
        except Exception:
            handle.close()
            raise

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if self._backend == "msvcrt":
                import msvcrt

                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            elif self._backend == "flock":
                import fcntl

                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            try:
                handle.close()
            finally:
                self._handle = None
                self._backend = ""

    def __enter__(self) -> "ExclusiveProcessFileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


# ``flock``/``msvcrt`` solve process coordination, but same-process threads also
# need deterministic ordering. A path-scoped RLock keeps the helper re-entrant
# while avoiding needless polling between local threads.
_WAIT_LOCKS_GUARD = threading.Lock()
_WAIT_LOCKS: dict[str, threading.RLock] = {}
_WAIT_DEPTH = threading.local()


def _wait_thread_lock(path: str) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(path))
    with _WAIT_LOCKS_GUARD:
        lock = _WAIT_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _WAIT_LOCKS[key] = lock
        return lock


def _depths() -> dict[str, int]:
    rows = getattr(_WAIT_DEPTH, "paths", None)
    if rows is None:
        rows = {}
        _WAIT_DEPTH.paths = rows
    return rows


@contextmanager
def bounded_process_file_lock(
    path: str,
    *,
    timeout_seconds: float = 5.0,
    poll_seconds: float = 0.05,
) -> Iterator[None]:
    """Acquire a short, bounded, re-entrant cross-process transaction lock.

    Unlike ``ExclusiveProcessFileLock.acquire()``, contention is expected here:
    another worker may simply be committing its own manifest update. We wait for
    a small bounded window instead of failing immediately, but still fail closed
    rather than continuing unlocked after the deadline.

    Re-entrancy is scoped to the current thread + normalized lock path. This is
    important for operations such as verified cleanup that hold the transaction
    while calling another manifest mutator on the same ledger.
    """
    lock_path = os.path.abspath(path)
    key = os.path.normcase(lock_path)
    timeout = max(0.0, float(timeout_seconds))
    poll = max(0.005, min(0.5, float(poll_seconds)))
    thread_lock = _wait_thread_lock(lock_path)

    with thread_lock:
        depths = _depths()
        depth = int(depths.get(key, 0))
        if depth:
            depths[key] = depth + 1
            try:
                yield
            finally:
                remaining = int(depths.get(key, 1)) - 1
                if remaining > 0:
                    depths[key] = remaining
                else:
                    depths.pop(key, None)
            return

        deadline = time.monotonic() + timeout
        held: ExclusiveProcessFileLock | None = None
        while held is None:
            candidate = ExclusiveProcessFileLock(lock_path)
            try:
                candidate.acquire()
                held = candidate
            except ProcessLockError as exc:
                if time.monotonic() >= deadline:
                    raise ProcessLockError(
                        "Timed out waiting for another process to finish a durable-store transaction"
                    ) from exc
                time.sleep(min(poll, max(0.0, deadline - time.monotonic())))

        depths[key] = 1
        try:
            yield
        finally:
            depths.pop(key, None)
            held.release()


__all__ = [
    "ProcessLockError",
    "ExclusiveProcessFileLock",
    "bounded_process_file_lock",
]
