"""Offline tests for provider-neutral cloud archive safety."""
from __future__ import annotations

import os
import tempfile

import pytest

from utils.archive_manifest import ArchiveManifest, sha256_file
from utils.archive_retry import ArchiveRetryQueue
from utils.cloud_storage import ArchiveCoordinator, RemoteObject


class FakeProvider:
    def __init__(self, *, name: str = "fake-free-cloud", fail_upload: bool = False, wrong_size: bool = False):
        self.name = name
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


def _coordinator(root: str, provider: FakeProvider) -> tuple[ArchiveCoordinator, ArchiveManifest, ArchiveRetryQueue]:
    manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
    retry = ArchiveRetryQueue(os.path.join(root, "retry.json"))
    return ArchiveCoordinator(provider, manifest, retry), manifest, retry


def test_verified_upload_can_delete_local():
    with tempfile.TemporaryDirectory() as root:
        local = _file(root)
        coordinator, _, retry = _coordinator(root, FakeProvider())
        out = coordinator.archive(local, "/archive/paper.pdf", delete_local=True)
        assert out["verified"] is True
        assert out["archive_id"].startswith("a_")
        assert out["local_deleted"] is True
        assert not os.path.exists(local)
        assert retry.items() == []


def test_upload_failure_keeps_local_file_and_queues_retry():
    with tempfile.TemporaryDirectory() as root:
        local = _file(root)
        coordinator, manifest, retry = _coordinator(root, FakeProvider(fail_upload=True))
        with pytest.raises(RuntimeError, match="upload failure"):
            coordinator.archive(local, "/archive/paper.pdf", delete_local=True)
        assert os.path.isfile(local)
        record = manifest.items()[0]
        assert record["status"] == "failed"
        assert record["verified"] is False
        queued = retry.items()
        assert len(queued) == 1
        assert queued[0]["local_path"] == os.path.abspath(local)
        assert queued[0]["provider"] == "fake-free-cloud"


def test_remote_verification_failure_keeps_local_file_and_queues_retry():
    with tempfile.TemporaryDirectory() as root:
        local = _file(root)
        coordinator, manifest, retry = _coordinator(root, FakeProvider(wrong_size=True))
        with pytest.raises(RuntimeError, match="Remote size"):
            coordinator.archive(local, "/archive/paper.pdf", delete_local=True)
        assert os.path.isfile(local)
        record = manifest.items()[0]
        assert record["status"] == "uploaded_unverified"
        assert record["verified"] is False
        assert len(retry.items()) == 1


def test_successful_archive_clears_old_retry_record():
    with tempfile.TemporaryDirectory() as root:
        local = _file(root)
        provider = FakeProvider()
        coordinator, _, retry = _coordinator(root, provider)
        retry.enqueue(
            local_path=local,
            remote_path="/archive/paper.pdf",
            provider=provider.name,
            error="old outage",
            now=0,
        )
        assert len(retry.items()) == 1
        out = coordinator.archive(local, "/archive/paper.pdf")
        assert out["verified"] is True
        assert retry.items() == []


def test_retry_due_marks_missing_local_copy_without_crash():
    with tempfile.TemporaryDirectory() as root:
        local = _file(root)
        provider = FakeProvider()
        coordinator, _, retry = _coordinator(root, provider)
        item = retry.enqueue(
            local_path=local,
            remote_path="/archive/paper.pdf",
            provider=provider.name,
            error="offline",
            now=0,
        )
        os.remove(local)
        out = coordinator.retry_due(limit=5)
        assert out["attempted"] == 1
        assert out["failed"] == 1
        assert out["results"][0]["error"] == "local_copy_missing"
        current = {row["key"]: row for row in retry.items()}[item["key"]]
        assert current["attempts"] == 1


def test_same_content_can_be_verified_in_drive_then_terabox_without_manifest_collision():
    with tempfile.TemporaryDirectory() as root:
        local = _file(root)
        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        drive_retry = ArchiveRetryQueue(os.path.join(root, "drive-retry.json"))
        tera_retry = ArchiveRetryQueue(os.path.join(root, "tera-retry.json"))
        drive = ArchiveCoordinator(FakeProvider(name="google-drive-rclone"), manifest, drive_retry)
        tera = ArchiveCoordinator(FakeProvider(name="terabox"), manifest, tera_retry)

        drive_out = drive.archive(local, "/InfinityResearchAI/paper.pdf")
        tera_out = tera.archive(local, "/archive/paper.pdf")

        assert drive_out["sha256"] == tera_out["sha256"]
        assert drive_out["archive_id"] != tera_out["archive_id"]
        assert len(manifest.items()) == 2
        assert manifest.get(drive_out["archive_id"])["provider"] == "google-drive-rclone"
        assert manifest.get(tera_out["archive_id"])["provider"] == "terabox"
        # Legacy hash lookup becomes intentionally ambiguous and must not silently
        # choose one cloud copy.
        assert manifest.get(drive_out["sha256"]) is None
