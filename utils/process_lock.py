"""Small stdlib-only cross-process lock for single-writer runtime stores.

Infinity Research AI deliberately avoids adding Redis/database infrastructure just
to coordinate a free single-process deployment. Some JSON stores are safe for
threads but are not transactional across multiple Python worker processes. This
lock lets those components fail closed instead of silently corrupting state.

The lock is advisory: every writer must cooperate by using this helper.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


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
