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
            # If upload had not yet been recorded, record this failed attempt.
            if current.get("status") == "pending":
                self.manifest.mark_upload_attempt(key, error=f"{type(exc).__name__}: {exc}")
            elif current.get("status") != "verified":
                # Keep failure reason without pretending a second upload attempt happened.
                data_error = f"verification failed: {type(exc).__name__}: {exc}"
                # mark_upload_attempt increments attempts, so only use it when the
                # upload itself was still pending. Verification errors surface here.
                current["verification_error"] = data_error[:1000]
            return {
                "ok": False,
                "verified": False,
                "local_retained": os.path.exists(local_path),
                "sha256": key,
                "error": f"{type(exc).__name__}: {exc}"[:1000],
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
