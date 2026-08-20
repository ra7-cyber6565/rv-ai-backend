"""Offline tests for provider-neutral cloud archive safety."""
from __future__ import annotations

import os
import tempfile

import pytest

from utils.archive_manifest import ArchiveManifest, sha256_file
from utils.cloud_storage import ArchiveCoordinator, RemoteObject


class FakeProvider:
    name = "fake-free-cloud"

    def __init__(self, *, fail_upload: bool = False, wrong_size: bool = False):
        self.fail_upload = fail_upload
        self.wrong_size = wrong_size
        self.objects = {}

    def upload_file(self, local_path: str, remote_path: str) -> RemoteObject:
        if self.fail_upload:
            raise RuntimeError("simulated upload failure")
        size = os.path.getsize(local_path)
        digest = sha256_file(local_path)
        obj = RemoteObject(path=remote_path, size=size, sha256=digest)
        self.objects[remote_path] = obj
        return obj

    def stat(self, remote_path: str) -> RemoteObject:
        obj = self.objects[remote_path]
        if self.wrong_size:
            return RemoteObject(path=obj.path, size=obj.size + 1, sha256=obj.sha256)
        return obj


def _file(root: str, name: str = "paper.pdf") -> str:
    path = os.path.join(root, name)
    with open(path, "wb") as handle:
        handle.write(b"verified research payload")
    return path


def test_verified_upload_can_delete_local():
    with tempfile.TemporaryDirectory() as root:
        local = _file(root)
        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        out = ArchiveCoordinator(FakeProvider(), manifest).archive(
            local, "/archive/paper.pdf", delete_local=True
        )
        assert out["verified"] is True
        assert out["local_deleted"] is True
        assert not os.path.exists(local)


def test_upload_failure_keeps_local_file():
    with tempfile.TemporaryDirectory() as root:
        local = _file(root)
        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        with pytest.raises(RuntimeError, match="upload failure"):
            ArchiveCoordinator(FakeProvider(fail_upload=True), manifest).archive(
                local, "/archive/paper.pdf", delete_local=True
            )
        assert os.path.isfile(local)
        record = manifest.items()[0]
        assert record["status"] == "failed"
        assert record["verified"] is False


def test_remote_verification_failure_keeps_local_file():
    with tempfile.TemporaryDirectory() as root:
        local = _file(root)
        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        with pytest.raises(RuntimeError, match="Remote size"):
            ArchiveCoordinator(FakeProvider(wrong_size=True), manifest).archive(
                local, "/archive/paper.pdf", delete_local=True
            )
        assert os.path.isfile(local)
        record = manifest.items()[0]
        assert record["status"] == "uploaded_unverified"
        assert record["verified"] is False
