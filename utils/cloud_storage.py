"""Provider-neutral cloud archive coordination.

This layer intentionally contains ZERO vendor URLs, tokens or billing logic.
It defines the contract that TeraBox (or another future free provider) must
implement after official API access is available.

Safety invariant:
    local file -> upload -> remote stat/verification -> manifest VERIFIED
    -> only then may local cleanup happen.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol

from utils.archive_manifest import ArchiveManifest


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

    def __init__(self, provider: CloudStorageProvider, manifest: ArchiveManifest | None = None):
        self.provider = provider
        self.manifest = manifest or ArchiveManifest()

    def archive(self, local_path: str, remote_path: str, *, delete_local: bool = False) -> dict:
        if not os.path.isfile(local_path):
            raise FileNotFoundError(local_path)
        if not remote_path or not str(remote_path).strip():
            raise ValueError("remote_path khaali nahi ho sakta")

        item = self.manifest.register(
            local_path,
            remote_path=str(remote_path),
            provider=self.provider.name,
        )
        digest = item["sha256"]

        try:
            uploaded = self.provider.upload_file(local_path, str(remote_path))
            self.manifest.mark_upload_attempt(digest)
        except Exception as exc:
            self.manifest.mark_upload_attempt(digest, error=f"{type(exc).__name__}: {exc}")
            raise

        # Never trust a success response alone. Re-read remote metadata when
        # provider supports it, then verify size/hash against the local record.
        try:
            remote = self.provider.stat(uploaded.path or str(remote_path))
            self.manifest.mark_verified(
                digest,
                remote_size=remote.size,
                remote_sha256=remote.sha256,
            )
        except Exception as exc:
            self.manifest.mark_verification_failed(digest, f"{type(exc).__name__}: {exc}")
            raise

        deleted = False
        if delete_local:
            if not self.manifest.safe_to_delete_local(digest):
                raise RuntimeError("Local file delete blocked: cloud copy verified nahi hai")
            os.remove(local_path)
            self.manifest.mark_local_deleted(digest)
            deleted = True

        final = self.manifest.get(digest) or {}
        return {
            "ok": True,
            "provider": self.provider.name,
            "remote_path": remote.path,
            "sha256": digest,
            "verified": bool(final.get("verified")),
            "local_deleted": deleted,
        }
