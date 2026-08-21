"""Private capability tokens for public async research-job polling.

The job id is metadata, not authentication. A UUID in a status URL can leak via
logs/history/screenshots, so status/progress/result endpoints should require a
second opaque capability returned only to the client that created the job.

This module uses a server-local 256-bit HMAC secret stored under the configured
Infinity data root. The raw secret never leaves the backend and no per-job token
is persisted: a token is deterministically derived as HMAC(secret, job_id).
That gives three useful properties:

- tokens survive a backend restart as long as the same local data root survives;
- the research-job JSON never contains bearer credentials;
- pruning jobs does not need a second token database cleanup path.

This is intentionally not a user/account auth system. It is a zero-cost
capability layer for single-user/public-backend deployments until a real account
system is deliberately added.

Secret first-creation is race-safe across signer instances and processes. This
prevents two simultaneous starters from publishing different HMAC secrets and
invalidating a token immediately after it was issued.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from utils.process_lock import ExclusiveProcessFileLock, ProcessLockError
from utils.storage_paths import ensure_layout


_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_SECRET_BYTES = 32
_SECRET_FILENAME = "research_job_capability.key"
_CREATE_LOCK_WAIT_SECONDS = 2.0
_CREATE_LOCK_POLL_SECONDS = 0.01

_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}


def _lock_for(path: str) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(path))
    with _LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[key] = lock
        return lock


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _safe_job_id(job_id: object) -> str:
    value = str(job_id or "").strip()
    return value if _JOB_ID_RE.fullmatch(value) else ""


def default_secret_path() -> str:
    folder = Path(ensure_layout()["research_memory"]) / "jobs"
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder / _SECRET_FILENAME)


class JobCapabilitySigner:
    def __init__(self, secret_path: Optional[str] = None):
        # Keep import side-effect free. The default data-root path is resolved
        # only when a job actually needs a capability token/status check.
        self.secret_path = os.path.abspath(secret_path) if secret_path else ""
        self._lock = threading.RLock()
        self._secret: bytes | None = None

    def _path(self) -> str:
        if self.secret_path:
            return self.secret_path
        path = os.path.abspath(default_secret_path())
        self.secret_path = path
        return path

    @staticmethod
    def _read_secret(path: str) -> bytes:
        try:
            raw = Path(path).read_bytes()
        except FileNotFoundError:
            return b""
        except OSError as exc:
            raise RuntimeError("Research job access secret read nahi ho saka") from exc
        if len(raw) != _SECRET_BYTES:
            raise RuntimeError("Research job access secret invalid/corrupt hai")
        return raw

    @staticmethod
    def _write_new_secret(path: str, raw: bytes) -> None:
        parent = os.path.dirname(path)
        Path(parent).mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="job_capability_", suffix=".tmp", dir=parent)
        try:
            try:
                os.fchmod(fd, 0o600)
            except (AttributeError, OSError):
                pass
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _load_or_create(self) -> bytes:
        with self._lock:
            if self._secret is not None:
                return self._secret
            path = self._path()

            # Different signer instances targeting the same file must serialize
            # the read/create/publish sequence even within one Python process.
            with _lock_for(path):
                existing = self._read_secret(path)
                if existing:
                    self._secret = existing
                    return existing

                deadline = time.monotonic() + _CREATE_LOCK_WAIT_SECONDS
                create_lock_path = path + ".create.lock"
                while True:
                    guard = ExclusiveProcessFileLock(create_lock_path)
                    try:
                        guard.acquire()
                    except ProcessLockError:
                        existing = self._read_secret(path)
                        if existing:
                            self._secret = existing
                            return existing
                        if time.monotonic() >= deadline:
                            raise RuntimeError(
                                "Research job access secret creation lock busy raha; safe startup fail-closed hua"
                            )
                        time.sleep(_CREATE_LOCK_POLL_SECONDS)
                        continue

                    try:
                        # Another process may have published the secret while we
                        # waited for the OS lock, so always re-read first.
                        existing = self._read_secret(path)
                        if existing:
                            self._secret = existing
                            return existing

                        raw = secrets.token_bytes(_SECRET_BYTES)
                        try:
                            self._write_new_secret(path, raw)
                        except OSError as exc:
                            raise RuntimeError(
                                "Research job access secret safely persist nahi ho saka"
                            ) from exc
                        persisted = self._read_secret(path)
                        if not hmac.compare_digest(raw, persisted):
                            raise RuntimeError(
                                "Research job access secret verification fail hua"
                            )
                        self._secret = persisted
                        return persisted
                    finally:
                        guard.release()

    def issue(self, job_id: object) -> str:
        safe = _safe_job_id(job_id)
        if not safe:
            raise ValueError("job_id invalid hai")
        secret = self._load_or_create()
        digest = hmac.new(secret, safe.encode("utf-8"), hashlib.sha256).digest()
        return _b64url(digest)

    def verify(self, job_id: object, token: object) -> bool:
        safe = _safe_job_id(job_id)
        candidate = str(token or "").strip()
        if not safe or not candidate or len(candidate) > 128:
            return False
        try:
            expected = self.issue(safe)
        except Exception:
            # A damaged/missing backend secret is a security failure. Never fall
            # back to "job id alone is enough".
            return False
        return hmac.compare_digest(expected, candidate)

    def status(self) -> dict:
        """Non-secret readiness only; creates/loads the server secret if needed."""
        try:
            secret = self._load_or_create()
            ready = len(secret) == _SECRET_BYTES
        except Exception:
            ready = False
        return {"job_capability_tokens_ready": ready}


job_access = JobCapabilitySigner()


__all__ = ["JobCapabilitySigner", "job_access", "default_secret_path"]
