"""Durable retry queue for cloud archive operations.

Cloud storage is optional and may be temporarily unavailable. A failed upload or
verification must never make research fail or delete the local file. This queue
persists retry intent under the configured Infinity archive directory and uses
bounded exponential backoff.

No provider secrets are stored here. Same-process read/modify/write operations
are protected by a path-scoped re-entrant lock so parallel research threads do
not silently overwrite each other's retry entries. Multi-process deployments
still need a shared transactional store or an OS-level lock.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from utils.archive_manifest import sha256_file
from utils.storage_paths import ensure_layout


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


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


BASE_BACKOFF_SECONDS = _int_env("ARCHIVE_RETRY_BASE_SECONDS", 60, 5, 3600)
MAX_BACKOFF_SECONDS = _int_env("ARCHIVE_RETRY_MAX_SECONDS", 3600, 60, 86400)


def default_retry_path() -> str:
    folder = Path(ensure_layout()["archive"])
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder / "retry_queue.json")


class ArchiveRetryQueue:
    """Atomic JSON queue keyed by provider + remote path + local SHA-256."""

    def __init__(self, path: str | None = None):
        self.path = os.path.abspath(path or default_retry_path())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = _lock_for(self.path)

    def _load(self) -> dict[str, Any]:
        with self._lock:
            if not os.path.exists(self.path):
                return {"version": 1, "items": {}}
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Archive retry queue is corrupted: {self.path}") from exc
            if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
                raise RuntimeError(f"Archive retry queue is invalid: {self.path}")
            return data

    def _save(self, data: dict[str, Any]) -> None:
        with self._lock:
            parent = os.path.dirname(self.path)
            fd, temp_path = tempfile.mkstemp(prefix="retry_", suffix=".json", dir=parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, self.path)
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

    @staticmethod
    def _key(provider: str, remote_path: str, sha256: str) -> str:
        return f"{provider.strip().lower()}|{remote_path.strip()}|{sha256.lower()}"

    def enqueue(
        self,
        *,
        local_path: str,
        remote_path: str,
        provider: str,
        error: str = "",
        now: float | None = None,
    ) -> dict[str, Any]:
        local = os.path.abspath(local_path)
        if not os.path.isfile(local):
            raise FileNotFoundError(local)
        if not str(remote_path).strip():
            raise ValueError("remote_path khaali nahi ho sakta")
        if not str(provider).strip():
            raise ValueError("provider khaali nahi ho sakta")

        current = int(time.time() if now is None else now)
        digest = sha256_file(local)
        key = self._key(provider, remote_path, digest)
        with self._lock:
            data = self._load()
            old = data["items"].get(key) or {}
            attempts = int(old.get("attempts", 0))
            delay = min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * (2 ** min(attempts, 10)))
            item = {
                "key": key,
                "local_path": local,
                "remote_path": str(remote_path),
                "provider": str(provider),
                "sha256": digest,
                "size": os.path.getsize(local),
                "status": "pending",
                "attempts": attempts,
                "last_error": str(error)[:1000],
                "created_at": int(old.get("created_at", current)),
                "updated_at": current,
                "next_attempt_at": current + delay,
            }
            data["items"][key] = item
            self._save(data)
        return dict(item)

    def due(self, *, provider: str | None = None, now: float | None = None, limit: int = 20) -> list[dict[str, Any]]:
        current = int(time.time() if now is None else now)
        wanted = (provider or "").strip().lower()
        with self._lock:
            rows: list[dict[str, Any]] = []
            for item in self._load()["items"].values():
                if item.get("status") != "pending":
                    continue
                if wanted and str(item.get("provider", "")).lower() != wanted:
                    continue
                if int(item.get("next_attempt_at", 0)) > current:
                    continue
                rows.append(dict(item))
        rows.sort(key=lambda row: (int(row.get("next_attempt_at", 0)), int(row.get("created_at", 0))))
        return rows[: max(1, min(100, int(limit)))]

    def mark_failure(self, key: str, error: str, *, now: float | None = None) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            item = data["items"].get(key)
            if not item:
                raise KeyError(key)
            current = int(time.time() if now is None else now)
            attempts = int(item.get("attempts", 0)) + 1
            delay = min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * (2 ** min(attempts, 10)))
            item["attempts"] = attempts
            item["status"] = "pending"
            item["last_error"] = str(error)[:1000]
            item["updated_at"] = current
            item["next_attempt_at"] = current + delay
            self._save(data)
            return dict(item)

    def mark_success(self, key: str) -> None:
        with self._lock:
            data = self._load()
            if key in data["items"]:
                del data["items"][key]
                self._save(data)

    def remove_for(self, *, provider: str, remote_path: str, sha256: str) -> None:
        self.mark_success(self._key(provider, remote_path, sha256))

    def items(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = [dict(item) for item in self._load()["items"].values()]
        rows.sort(key=lambda row: int(row.get("created_at", 0)))
        return rows

    def summary(self) -> dict[str, Any]:
        rows = self.items()
        missing = sum(1 for row in rows if not os.path.isfile(str(row.get("local_path", ""))))
        providers: dict[str, int] = {}
        for row in rows:
            name = str(row.get("provider") or "unknown")
            providers[name] = providers.get(name, 0) + 1
        return {
            "pending": len(rows),
            "missing_local_files": missing,
            "providers": providers,
        }
