"""Provider-neutral cloud archive workflow.

TeraBox (or any future free storage provider) plugs into this interface. The
service never deletes a local file merely because an upload call returned
success: it asks the provider for remote metadata, verifies size/checksum when
available, then marks the ArchiveManifest VERIFIED. Local cleanup is a separate
explicit operation and refuses to run before verification.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol

from utils.archive_manifest import ArchiveManifest


@dataclass(frozen=True)
class CloudObject:
    path: str
    size: int
    sha256: Optional[str] = None
    object_id: str = ""


class CloudStorageProvider(Protocol):
    """Minimum contract required from an official cloud-storage adapter."""

    name: str

    def upload(self, local_path: str, remote_path: str) -> CloudObject: ...

    def stat(self, remote_path: str) -> CloudObject: ...


class ArchiveService:
    def __init__(self, provider: CloudStorageProvider, manifest: Optional[ArchiveManifest] = None):
        self.provider = provider
        self.manifest = manifest or ArchiveManifest()

    def archive(self, local_path: str, remote_path: str) -> dict:
        """Upload + independently stat + verify; never auto-delete local data."""
        item = self.manifest.register(
            local_path,
            remote_path=remote_path,
            provider=self.provider.name,
        )
        key = item["sha256"]
        try:
            self.provider.upload(local_path, remote_path)
            self.manifest.mark_upload_attempt(key)
            remote = self.provider.stat(remote_path)
            self.manifest.mark_verified(
                key,
                remote_size=remote.size,
                remote_sha256=remote.sha256,
            )
        except Exception as exc:  # noqa: BLE001 - preserve local file on any cloud failure
            current = self.manifest.get(key) or {}
            message = f"{type(exc).__name__}: {exc}"[:1000]
            if current.get("status") == "pending":
                # Upload itself failed (or failed before we could confirm success).
                self.manifest.mark_upload_attempt(key, error=message)
            elif current.get("status") != "verified":
                # Upload returned, but remote stat/size/checksum verification failed.
                self.manifest.mark_verification_failed(key, message)
            return {
                "ok": False,
                "verified": False,
                "local_retained": os.path.exists(local_path),
                "sha256": key,
                "error": message,
            }

        return {
            "ok": True,
            "verified": True,
            "local_retained": os.path.exists(local_path),
            "sha256": key,
            "remote_path": remote_path,
        }

    def delete_local_if_verified(self, sha256: str) -> bool:
        """Delete only after manifest verification; otherwise refuse."""
        item = self.manifest.get(sha256)
        if not item or not self.manifest.safe_to_delete_local(sha256):
            return False
        local_path = str(item.get("local_path") or "")
        if not local_path:
            return False
        if not os.path.exists(local_path):
            return True
        os.remove(local_path)
        return not os.path.exists(local_path)
