"""Offline tests for provider-neutral verified cloud archiving."""
from __future__ import annotations

import hashlib
import os
import tempfile

from storage.cloud_archive import ArchiveService, CloudObject
from utils.archive_manifest import ArchiveManifest


class FakeProvider:
    name = "fake-free-cloud"

    def __init__(self, *, wrong_size: bool = False):
        self.objects = {}
        self.wrong_size = wrong_size

    def upload(self, local_path: str, remote_path: str) -> CloudObject:
        with open(local_path, "rb") as handle:
            payload = handle.read()
        digest = hashlib.sha256(payload).hexdigest()
        self.objects[remote_path] = (payload, digest)
        return CloudObject(remote_path, len(payload), digest)

    def stat(self, remote_path: str) -> CloudObject:
        payload, digest = self.objects[remote_path]
        size = len(payload) + (1 if self.wrong_size else 0)
        return CloudObject(remote_path, size, digest)


def test_verified_upload_keeps_local_until_explicit_cleanup():
    with tempfile.TemporaryDirectory() as root:
        local = os.path.join(root, "paper.pdf")
        with open(local, "wb") as handle:
            handle.write(b"important research")
        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        service = ArchiveService(FakeProvider(), manifest)

        result = service.archive(local, "/papers/paper.pdf")
        assert result["ok"] is True
        assert result["verified"] is True
        assert os.path.exists(local)
        assert service.delete_local_if_verified(result["sha256"]) is True
        assert not os.path.exists(local)


def test_verification_mismatch_never_deletes_local_file():
    with tempfile.TemporaryDirectory() as root:
        local = os.path.join(root, "dataset.bin")
        with open(local, "wb") as handle:
            handle.write(b"123456")
        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        service = ArchiveService(FakeProvider(wrong_size=True), manifest)

        result = service.archive(local, "/data/dataset.bin")
        assert result["ok"] is False
        assert result["verified"] is False
        assert os.path.exists(local)
        assert service.delete_local_if_verified(result["sha256"]) is False
        item = manifest.get(result["sha256"])
        assert item["status"] == "uploaded_unverified"
        assert item["verified"] is False
