"""Zero-cost anonymous project/session capability isolation.

A public backend must not let one caller choose another caller's predictable
``project_id`` and then upload/search inside that vector namespace. Requiring a
static backend secret in Android/web would simply move the secret into the client,
so the server instead creates a random project id and returns an opaque capability
for that id.

The capability is HMAC(server-local secret, project_id). The server secret is
stored under the configured Infinity data root with best-effort owner-only file
permissions. No per-session database is required, and the raw secret never leaves
the backend. Browser/Android clients keep the returned project token in memory or
secure device storage and send it only in ``X-Project-Token`` headers.

This is namespace isolation, not an identity/account system. It prevents casual
cross-project poisoning/enumeration while keeping the project ₹0 and self-hosted.

Secret creation is also race-safe. Multiple signer instances in the same process
share a path lock, and a short-lived OS file lock serializes first creation across
processes. That matters because two workers creating different HMAC secrets at the
same path could otherwise issue tokens that become invalid immediately after one
secret overwrites the other.
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


_PROJECT_ID_RE = re.compile(r"^p_[A-Za-z0-9_-]{20,78}$")
_SECRET_BYTES = 32
_SECRET_FILENAME = "project_capability.key"
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


def _safe_project_id(project_id: object) -> str:
    value = str(project_id or "").strip()
    return value if _PROJECT_ID_RE.fullmatch(value) else ""


def default_secret_path() -> str:
    folder = Path(ensure_layout()["research_memory"]) / "access"
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder / _SECRET_FILENAME)


class ProjectCapabilitySigner:
    def __init__(self, secret_path: Optional[str] = None):
        self.secret_path = os.path.abspath(secret_path or default_secret_path())
        self._lock = _lock_for(self.secret_path)
        self._secret: bytes | None = None

    @staticmethod
    def _read_secret(path: str) -> bytes:
        try:
            raw = Path(path).read_bytes()
        except FileNotFoundError:
            return b""
        except OSError as exc:
            raise RuntimeError("Project access secret read nahi ho saka") from exc
        if len(raw) != _SECRET_BYTES:
            raise RuntimeError("Project access secret invalid/corrupt hai")
        return raw

    @staticmethod
    def _write_new_secret(path: str, raw: bytes) -> None:
        """Atomically publish a fully-written secret while caller holds create lock."""
        parent = os.path.dirname(path)
        Path(parent).mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="project_capability_", suffix=".tmp", dir=parent)
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

            existing = self._read_secret(self.secret_path)
            if existing:
                self._secret = existing
                return existing

            deadline = time.monotonic() + _CREATE_LOCK_WAIT_SECONDS
            create_lock_path = self.secret_path + ".create.lock"

            while True:
                guard = ExclusiveProcessFileLock(create_lock_path)
                try:
                    guard.acquire()
                except ProcessLockError:
                    # Another process is probably publishing the first secret.
                    # Re-read before sleeping so normal startup races resolve fast.
                    existing = self._read_secret(self.secret_path)
                    if existing:
                        self._secret = existing
                        return existing
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "Project access secret creation lock busy raha; safe startup fail-closed hua"
                        )
                    time.sleep(_CREATE_LOCK_POLL_SECONDS)
                    continue

                try:
                    # Double-check after obtaining the OS lock because another
                    # process may have created the secret while we were waiting.
                    existing = self._read_secret(self.secret_path)
                    if existing:
                        self._secret = existing
                        return existing

                    raw = secrets.token_bytes(_SECRET_BYTES)
                    try:
                        self._write_new_secret(self.secret_path, raw)
                    except OSError as exc:
                        raise RuntimeError(
                            "Project access secret safely persist nahi ho saka"
                        ) from exc
                    persisted = self._read_secret(self.secret_path)
                    if not hmac.compare_digest(raw, persisted):
                        raise RuntimeError("Project access secret verification fail hua")
                    self._secret = persisted
                    return persisted
                finally:
                    guard.release()

    def create(self) -> dict[str, str]:
        """Create one random anonymous project namespace + bearer capability."""
        project_id = "p_" + secrets.token_urlsafe(24)
        token = self.issue(project_id)
        return {
            "project_id": project_id,
            "project_access_token": token,
            "project_access_header": "X-Project-Token",
        }

    def issue(self, project_id: object) -> str:
        safe = _safe_project_id(project_id)
        if not safe:
            raise ValueError("project_id invalid hai")
        secret = self._load_or_create()
        digest = hmac.new(
            secret,
            ("project:" + safe).encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return _b64url(digest)

    def verify(self, project_id: object, token: object) -> bool:
        safe = _safe_project_id(project_id)
        candidate = str(token or "").strip()
        if not safe or not candidate or len(candidate) > 128:
            return False
        try:
            expected = self.issue(safe)
        except Exception:
            return False
        return hmac.compare_digest(expected, candidate)

    def status(self) -> dict[str, bool]:
        """Non-secret readiness only; never returns secret/token/id."""
        try:
            ready = len(self._load_or_create()) == _SECRET_BYTES
        except Exception:
            ready = False
        return {"project_capability_tokens_ready": ready}


project_access = ProjectCapabilitySigner()


__all__ = [
    "ProjectCapabilitySigner",
    "project_access",
    "default_secret_path",
]
