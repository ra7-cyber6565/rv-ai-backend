"""Durable archive manifest for cloud-first storage.

This module tracks whether a local working file is safe to delete. A file must
be marked uploaded *and* verified before cleanup is allowed.

The provider upload implementation is intentionally separate: TeraBox tokens and
account-specific API details must never be hard-coded in this repository.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from utils.storage_paths import ensure_layout


def sha256_file(path: str, chunk_bytes: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_bytes)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def default_manifest_path() -> str:
    folder = Path(ensure_layout()["archive"])
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder / "manifest.json")


class ArchiveManifest:
    """Atomic JSON ledger for files moving from local workspace to cloud."""

    def __init__(self, path: str | None = None):
        self.path = os.path.abspath(path or default_manifest_path())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not os.path.exists(self.path):
            return {"version": 1, "items": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
                raise ValueError("invalid archive manifest")
            return data
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Archive manifest is corrupted: {self.path}") from exc

    def _save(self, data: dict[str, Any]) -> None:
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

    def register(self, local_path: str, *, remote_path: str, provider: str) -> dict[str, Any]:
        local = os.path.abspath(local_path)
        if not os.path.isfile(local):
            raise FileNotFoundError(local)
        item = {
            "local_path": local,
            "remote_path": remote_path,
            "provider": provider,
            "size": os.path.getsize(local),
            "sha256": sha256_file(local),
            "status": "pending",
            "verified": False,
            "attempts": 0,
            "last_error": "",
            "updated_at": int(time.time()),
        }
        data = self._load()
        data["items"][item["sha256"]] = item
        self._save(data)
        return dict(item)

    def mark_upload_attempt(self, sha256: str, *, error: str = "") -> None:
        data = self._load()
        item = data["items"].get(sha256)
        if not item:
            raise KeyError(sha256)
        item["attempts"] = int(item.get("attempts", 0)) + 1
        item["status"] = "failed" if error else "uploaded_unverified"
        item["last_error"] = str(error)[:1000]
        item["updated_at"] = int(time.time())
        self._save(data)

    def mark_verification_failed(self, sha256: str, error: str) -> None:
        """Persist verification failure without counting a second upload attempt."""
        data = self._load()
        item = data["items"].get(sha256)
        if not item:
            raise KeyError(sha256)
        item["status"] = "uploaded_unverified"
        item["verified"] = False
        item["last_error"] = str(error)[:1000]
        item["updated_at"] = int(time.time())
        self._save(data)

    def mark_verified(self, sha256: str, *, remote_size: int, remote_sha256: str | None = None) -> None:
        data = self._load()
        item = data["items"].get(sha256)
        if not item:
            raise KeyError(sha256)
        if int(remote_size) != int(item["size"]):
            raise RuntimeError("Remote size does not match local file; refusing verification")
        if remote_sha256 and remote_sha256.lower() != str(item["sha256"]).lower():
            raise RuntimeError("Remote checksum does not match local file; refusing verification")
        item["status"] = "verified"
        item["verified"] = True
        item["last_error"] = ""
        item["updated_at"] = int(time.time())
        self._save(data)

    def mark_local_deleted(self, sha256: str) -> None:
        """Record that the verified local working copy was safely removed."""
        data = self._load()
        item = data["items"].get(sha256)
        if not item:
            raise KeyError(sha256)
        if item.get("status") != "verified" or item.get("verified") is not True:
            raise RuntimeError("Unverified archive item cannot be marked locally deleted")
        item["local_deleted"] = True
        item["local_deleted_at"] = int(time.time())
        item["updated_at"] = int(time.time())
        self._save(data)

    def safe_to_delete_local(self, sha256: str) -> bool:
        item = self._load()["items"].get(sha256) or {}
        return item.get("status") == "verified" and item.get("verified") is True

    def get(self, sha256: str) -> dict[str, Any] | None:
        item = self._load()["items"].get(sha256)
        return dict(item) if item else None

    def items(self) -> list[dict[str, Any]]:
        """Return a snapshot of all archive records, oldest first."""
        records = [dict(item) for item in self._load()["items"].values()]
        records.sort(key=lambda item: int(item.get("updated_at", 0)))
        return records
