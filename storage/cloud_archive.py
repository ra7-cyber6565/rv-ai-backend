"""Compatibility wrapper for the original cloud-archive interface.

New provider implementations should use ``utils.cloud_storage`` directly. This
module keeps the earlier ``upload(...)`` provider contract working, but delegates
verification/retry semantics to the single ArchiveCoordinator implementation so
safety rules cannot drift between two cloud layers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol

from utils.archive_manifest import ArchiveManifest
from utils.archive_retry import ArchiveRetryQueue
from utils.cloud_storage import ArchiveCoordinator, RemoteObject


@dataclass(frozen=True)
class CloudObject:
    path: str
    size: int
    sha256: Optional[str] = None
    object_id: str = ""


class CloudStorageProvider(Protocol):
    """Legacy minimum contract kept for backward compatibility."""

    name: str

    def upload(self, local_path: str, remote_path: str) -> CloudObject: ...

    def stat(self, remote_path: str) -> CloudObject: ...


class _LegacyProviderAdapter:
    def __init__(self, provider: CloudStorageProvider):
        self._provider = provider
        self.name = provider.name

    @staticmethod
    def _remote(obj: CloudObject) -> RemoteObject:
        return RemoteObject(
            path=obj.path,
            size=int(obj.size),
            sha256=obj.sha256,
            etag=obj.object_id or None,
        )

    def upload_file(self, local_path: str, remote_path: str) -> RemoteObject:
        return self._remote(self._provider.upload(local_path, remote_path))

    def stat(self, remote_path: str) -> RemoteObject:
        return self._remote(self._provider.stat(remote_path))


class ArchiveService:
    """Backward-compatible service backed by the canonical ArchiveCoordinator."""

    def __init__(self, provider: CloudStorageProvider, manifest: Optional[ArchiveManifest] = None):
        self.provider = provider
        self.manifest = manifest or ArchiveManifest()
        retry_path = self.manifest.path + ".retry.json"
        self._coordinator = ArchiveCoordinator(
            _LegacyProviderAdapter(provider),
            self.manifest,
            ArchiveRetryQueue(retry_path),
        )

    def archive(self, local_path: str, remote_path: str) -> dict:
        """Upload + independently stat + verify; never auto-delete local data."""
        try:
            out = self._coordinator.archive(local_path, remote_path, delete_local=False)
            return {
                "ok": True,
                "verified": bool(out.get("verified")),
                "local_retained": os.path.exists(local_path),
                "archive_id": out.get("archive_id"),
                "sha256": out.get("sha256"),
                "remote_path": out.get("remote_path", remote_path),
            }
        except Exception as exc:  # noqa: BLE001 - legacy API returns failure dict
            # Locate the exact newest matching record for diagnostics without
            # assuming a content hash is globally unique across providers/paths.
            candidate = None
            for item in reversed(self.manifest.items()):
                if (
                    item.get("provider") == self.provider.name
                    and item.get("remote_path") == remote_path
                    and item.get("local_path") == os.path.abspath(local_path)
                ):
                    candidate = item
                    break
            return {
                "ok": False,
                "verified": False,
                "local_retained": os.path.exists(local_path),
                "archive_id": (candidate or {}).get("archive_id"),
                "sha256": (candidate or {}).get("sha256"),
                "error": f"{type(exc).__name__}: {str(exc)[:500]}",
            }

    def delete_local_if_verified(self, reference: str) -> bool:
        """Delete only after exact manifest verification; then record deletion."""
        item = self.manifest.get(reference)
        if not item:
            return False
        archive_ref = str(item.get("archive_id") or reference)
        if not self.manifest.safe_to_delete_local(archive_ref):
            return False
        local_path = str(item.get("local_path") or "")
        if not local_path:
            return False
        if not os.path.exists(local_path):
            return True
        if os.path.islink(local_path) or not os.path.isfile(local_path):
            return False
        os.remove(local_path)
        self.manifest.mark_local_deleted(archive_ref)
        return not os.path.exists(local_path)
