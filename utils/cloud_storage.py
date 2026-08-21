"""Provider-neutral cloud archive coordination.

This layer intentionally contains ZERO vendor URLs, tokens or billing logic.
It defines the contract that Google Drive, TeraBox, or another future genuinely
free provider must implement.

Safety invariant:
    local file -> upload -> remote stat/verification -> manifest VERIFIED
    -> only then may local cleanup happen.

Cloud failures are recorded in a durable retry queue; they do not silently drop
archive intent or delete the local copy. Manifest operations use provider/path-
aware ``archive_id`` references so identical content may safely exist in Google
Drive now and TeraBox later without overwriting provenance.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol

from utils.archive_manifest import ArchiveManifest
from utils.archive_retry import ArchiveRetryQueue


@dataclass(frozen=True)
class RemoteObject:
    path: str
    size: int
    sha256: Optional[str] = None
    etag: Optional[str] = None


class CloudStorageProvider(Protocol):
    """Minimal contract for a safe archive provider."""

    name: str

    def upload_file(self, local_path: str, remote_path: str) -> RemoteObject: ...

    def stat(self, remote_path: str) -> RemoteObject: ...


class ArchiveCoordinator:
    """Moves files to cloud without ever deleting an unverified local copy."""

    def __init__(
        self,
        provider: CloudStorageProvider,
        manifest: ArchiveManifest | None = None,
        retry_queue: ArchiveRetryQueue | None = None,
    ):
        self.provider = provider
        self.manifest = manifest or ArchiveManifest()
        self.retry_queue = retry_queue or ArchiveRetryQueue()

    def _queue_failure(self, local_path: str, remote_path: str, exc: Exception) -> None:
        """Best-effort durable retry registration without masking original error."""
        try:
            self.retry_queue.enqueue(
                local_path=local_path,
                remote_path=remote_path,
                provider=self.provider.name,
                error=f"{type(exc).__name__}: {exc}",
            )
        except Exception:
            pass

    def archive(self, local_path: str, remote_path: str, *, delete_local: bool = False) -> dict:
        if not os.path.isfile(local_path):
            raise FileNotFoundError(local_path)
        if not remote_path or not str(remote_path).strip():
            raise ValueError("remote_path khaali nahi ho sakta")

        remote_path = str(remote_path)
        item = self.manifest.register(
            local_path,
            remote_path=remote_path,
            provider=self.provider.name,
        )
        digest = str(item["sha256"])
        archive_id = str(item.get("archive_id") or digest)

        try:
            uploaded = self.provider.upload_file(local_path, remote_path)
            self.manifest.mark_upload_attempt(archive_id)
        except Exception as exc:
            self.manifest.mark_upload_attempt(archive_id, error=f"{type(exc).__name__}: {exc}")
            self._queue_failure(local_path, remote_path, exc)
            raise

        # Never trust a success response alone. Re-read remote metadata, then
        # verify size/hash against the exact provider/path/content archive record.
        try:
            remote = self.provider.stat(uploaded.path or remote_path)
            self.manifest.mark_verified(
                archive_id,
                remote_size=remote.size,
                remote_sha256=remote.sha256,
            )
        except Exception as exc:
            self.manifest.mark_verification_failed(archive_id, f"{type(exc).__name__}: {exc}")
            self._queue_failure(local_path, remote_path, exc)
            raise

        try:
            self.retry_queue.remove_for(
                provider=self.provider.name,
                remote_path=remote_path,
                sha256=digest,
            )
        except Exception:
            pass

        deleted = False
        if delete_local:
            if not self.manifest.safe_to_delete_local(archive_id):
                raise RuntimeError("Local file delete blocked: cloud copy verified nahi hai")
            os.remove(local_path)
            self.manifest.mark_local_deleted(archive_id)
            deleted = True

        final = self.manifest.get(archive_id) or {}
        return {
            "ok": True,
            "provider": self.provider.name,
            "remote_path": remote.path,
            "archive_id": archive_id,
            "sha256": digest,
            "verified": bool(final.get("verified")),
            "local_deleted": deleted,
        }

    def retry_due(self, *, limit: int = 5) -> dict:
        """Retry due archive records for this provider, never auto-delete local files."""
        due = self.retry_queue.due(provider=self.provider.name, limit=max(1, min(20, int(limit))))
        results: list[dict] = []
        for row in due:
            key = str(row.get("key") or "")
            local_path = str(row.get("local_path") or "")
            remote_path = str(row.get("remote_path") or "")
            if not local_path or not os.path.isfile(local_path):
                if key:
                    try:
                        self.retry_queue.mark_failure(key, "Local archive copy missing; manual recovery required")
                    except Exception:
                        pass
                results.append({"ok": False, "remote_path": remote_path, "error": "local_copy_missing"})
                continue

            try:
                out = self.archive(local_path, remote_path, delete_local=False)
                results.append({
                    "ok": True,
                    "remote_path": remote_path,
                    "archive_id": out.get("archive_id"),
                    "sha256": out.get("sha256"),
                    "verified": bool(out.get("verified")),
                })
            except Exception as exc:  # noqa: BLE001 - bounded retry boundary
                if key:
                    try:
                        self.retry_queue.mark_failure(key, f"{type(exc).__name__}: {exc}")
                    except Exception:
                        pass
                results.append({"ok": False, "remote_path": remote_path, "error": type(exc).__name__})

        return {
            "provider": self.provider.name,
            "attempted": len(due),
            "succeeded": sum(1 for row in results if row.get("ok")),
            "failed": sum(1 for row in results if not row.get("ok")),
            "results": results,
        }
