"""Durable archive manifest for verified cloud storage copies.

A local working file may have more than one cloud destination over its lifetime
(for example temporary Google Drive now and TeraBox later). Therefore the ledger
must not key records by content hash alone. Version 2 uses a stable ``archive_id``
derived from provider + remote path + SHA-256 while preserving ``sha256`` as the
content identity.

Safety:
- uploaded != verified;
- size-only remote verification may confirm that an object exists, but local
  deletion additionally requires an independently matching remote SHA-256;
- local deletion is allowed only for a specific VERIFIED + checksum-verified
  archive record;
- legacy records without explicit checksum proof fail closed for deletion until
  they are re-verified;
- legacy SHA-only references still work only when they identify exactly one
  record, so ambiguous multi-provider state fails closed;
- same-process read/modify/write is protected by a path-scoped RLock.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

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


def sha256_file(path: str, chunk_bytes: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_bytes)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _archive_id(provider: str, remote_path: str, sha256: str) -> str:
    raw = f"{str(provider).strip().lower()}\0{str(remote_path).strip()}\0{str(sha256).lower()}"
    return "a_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def default_manifest_path() -> str:
    folder = Path(ensure_layout()["archive"])
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder / "manifest.json")


class ArchiveManifest:
    """Atomic JSON ledger for files moving from local workspace to cloud."""

    def __init__(self, path: str | None = None):
        self.path = os.path.abspath(path or default_manifest_path())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = _lock_for(self.path)

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """Migrate legacy SHA-keyed manifests to provider/path-aware v2 in memory.

        Old manifests had only ``verified=True`` and did not record whether that
        verification included a content checksum. Treat that missing fact as
        unknown/False; otherwise an old size-only row could authorize deletion.
        """
        items = data.get("items")
        if not isinstance(items, dict):
            raise ValueError("invalid archive manifest")
        normalized: dict[str, dict[str, Any]] = {}
        for old_key, raw_item in items.items():
            if not isinstance(raw_item, dict):
                continue
            item = dict(raw_item)
            digest = str(item.get("sha256") or old_key or "").strip().lower()
            provider = str(item.get("provider") or "unknown").strip() or "unknown"
            remote_path = str(item.get("remote_path") or "").strip()
            if not digest or not remote_path:
                continue
            archive_id = str(item.get("archive_id") or _archive_id(provider, remote_path, digest))
            item["archive_id"] = archive_id
            item["sha256"] = digest
            item["checksum_verified"] = item.get("checksum_verified") is True
            item["verification_method"] = str(item.get("verification_method") or "")
            normalized[archive_id] = item
        return {"version": 2, "items": normalized}

    def _load(self) -> dict[str, Any]:
        with self._lock:
            if not os.path.exists(self.path):
                return {"version": 2, "items": {}}
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Archive manifest is corrupted: {self.path}") from exc
            if not isinstance(data, dict):
                raise RuntimeError(f"Archive manifest is invalid: {self.path}")
            try:
                return self._normalize(data)
            except ValueError as exc:
                raise RuntimeError(f"Archive manifest is invalid: {self.path}") from exc

    def _save(self, data: dict[str, Any]) -> None:
        with self._lock:
            data = self._normalize(data)
            parent = os.path.dirname(self.path)
            fd, tmp = tempfile.mkstemp(prefix="manifest_", suffix=".json", dir=parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)

    @staticmethod
    def _resolve_key(data: dict[str, Any], reference: str) -> str:
        ref = str(reference or "").strip()
        if not ref:
            raise KeyError(reference)
        if ref in data["items"]:
            return ref
        matches = [
            key for key, item in data["items"].items()
            if str(item.get("sha256") or "").lower() == ref.lower()
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise KeyError(f"Ambiguous archive reference: {ref}; use archive_id")
        raise KeyError(ref)

    def register(self, local_path: str, *, remote_path: str, provider: str) -> dict[str, Any]:
        local = os.path.abspath(local_path)
        if not os.path.isfile(local):
            raise FileNotFoundError(local)
        remote = str(remote_path or "").strip()
        provider_name = str(provider or "").strip()
        if not remote:
            raise ValueError("remote_path khaali nahi ho sakta")
        if not provider_name:
            raise ValueError("provider khaali nahi ho sakta")

        digest = sha256_file(local)
        archive_id = _archive_id(provider_name, remote, digest)
        now = int(time.time())
        fresh = {
            "archive_id": archive_id,
            "local_path": local,
            "remote_path": remote,
            "provider": provider_name,
            "size": os.path.getsize(local),
            "sha256": digest,
            "status": "pending",
            "verified": False,
            "checksum_verified": False,
            "verification_method": "",
            "attempts": 0,
            "last_error": "",
            "updated_at": now,
        }
        with self._lock:
            data = self._load()
            existing = data["items"].get(archive_id)
            if existing:
                # Idempotent re-registration of the same content/destination must
                # not destroy a previously VERIFIED state. A *new upload attempt*
                # below will deliberately clear verification until remote stat is
                # checked again.
                existing["local_path"] = local
                existing["size"] = os.path.getsize(local)
                existing["updated_at"] = now
                item = existing
            else:
                data["items"][archive_id] = fresh
                item = fresh
            self._save(data)
        return dict(item)

    def mark_upload_attempt(self, reference: str, *, error: str = "") -> None:
        """Start/fail one upload attempt while keeping attempt accounting honest.

        ``archive()`` marks the attempt *before* the network call so an older
        VERIFIED flag cannot authorize cleanup while the remote object is being
        replaced. If that same network call then fails, the second call with
        ``error=...`` changes state to failed without counting a second attempt.
        """
        with self._lock:
            data = self._load()
            key = self._resolve_key(data, reference)
            item = data["items"][key]
            already_started = (
                bool(error)
                and item.get("status") == "uploaded_unverified"
                and not str(item.get("last_error") or "")
            )
            if not already_started:
                item["attempts"] = int(item.get("attempts", 0)) + 1
            item["status"] = "failed" if error else "uploaded_unverified"
            # A new upload can replace/alter the remote object. Even an archive
            # record that was verified previously must become unverified before
            # bytes are sent and stay unverified until post-upload validation.
            item["verified"] = False
            item["checksum_verified"] = False
            item["verification_method"] = ""
            item["last_error"] = str(error)[:1000]
            item["updated_at"] = int(time.time())
            self._save(data)

    def mark_verification_failed(self, reference: str, error: str) -> None:
        """Persist verification failure without counting a second upload attempt."""
        with self._lock:
            data = self._load()
            key = self._resolve_key(data, reference)
            item = data["items"][key]
            item["status"] = "uploaded_unverified"
            item["verified"] = False
            item["checksum_verified"] = False
            item["verification_method"] = ""
            item["last_error"] = str(error)[:1000]
            item["updated_at"] = int(time.time())
            self._save(data)

    def mark_verified(self, reference: str, *, remote_size: int, remote_sha256: str | None = None) -> None:
        """Record remote verification strength without overstating deletion safety.

        Matching size is enough to record that the remote object was observed,
        but only a matching SHA-256 authorizes later local cleanup. This keeps
        providers that lack content hashes usable while making data deletion
        fail closed.
        """
        with self._lock:
            data = self._load()
            key = self._resolve_key(data, reference)
            item = data["items"][key]
            if int(remote_size) != int(item["size"]):
                raise RuntimeError("Remote size does not match local file; refusing verification")

            checksum_verified = False
            if remote_sha256:
                remote_digest = str(remote_sha256).strip().lower()
                if remote_digest != str(item["sha256"]).lower():
                    raise RuntimeError("Remote checksum does not match local file; refusing verification")
                checksum_verified = True

            item["status"] = "verified"
            item["verified"] = True
            item["checksum_verified"] = checksum_verified
            item["verification_method"] = "size+sha256" if checksum_verified else "size-only"
            item["last_error"] = ""
            item["updated_at"] = int(time.time())
            self._save(data)

    def mark_local_deleted(self, reference: str) -> None:
        """Record that a strongly verified local working copy was safely removed."""
        with self._lock:
            data = self._load()
            key = self._resolve_key(data, reference)
            item = data["items"][key]
            if not (
                item.get("status") == "verified"
                and item.get("verified") is True
                and item.get("checksum_verified") is True
            ):
                raise RuntimeError(
                    "Archive item needs matching remote checksum before local deletion"
                )
            item["local_deleted"] = True
            item["local_deleted_at"] = int(time.time())
            item["updated_at"] = int(time.time())
            self._save(data)

    def safe_to_delete_local(self, reference: str) -> bool:
        with self._lock:
            data = self._load()
            try:
                key = self._resolve_key(data, reference)
            except KeyError:
                return False
            item = data["items"].get(key) or {}
            return (
                item.get("status") == "verified"
                and item.get("verified") is True
                and item.get("checksum_verified") is True
            )

    def get(self, reference: str) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()
            try:
                key = self._resolve_key(data, reference)
            except KeyError:
                return None
            item = data["items"].get(key)
            return dict(item) if item else None

    def items(self) -> list[dict[str, Any]]:
        """Return a snapshot of all archive records, oldest first."""
        with self._lock:
            records = [dict(item) for item in self._load()["items"].values()]
        records.sort(key=lambda item: int(item.get("updated_at", 0)))
        return records
