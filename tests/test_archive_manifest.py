"""Offline regression tests for safe archive deletion rules."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from utils.archive_manifest import ArchiveManifest, sha256_file


def test_file_is_not_deletable_before_remote_verification():
    with tempfile.TemporaryDirectory() as root:
        local = os.path.join(root, "paper.pdf")
        with open(local, "wb") as handle:
            handle.write(b"research-data")
        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        item = manifest.register(local, remote_path="/papers/paper.pdf", provider="terabox")
        assert item["archive_id"].startswith("a_")
        assert manifest.safe_to_delete_local(item["archive_id"]) is False
        # Legacy SHA reference still works when exactly one record exists.
        assert manifest.safe_to_delete_local(item["sha256"]) is False
        manifest.mark_upload_attempt(item["archive_id"])
        assert manifest.safe_to_delete_local(item["archive_id"]) is False


def test_matching_remote_size_allows_verified_state():
    with tempfile.TemporaryDirectory() as root:
        local = os.path.join(root, "book.pdf")
        payload = b"abc" * 100
        with open(local, "wb") as handle:
            handle.write(payload)
        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        item = manifest.register(local, remote_path="/books/book.pdf", provider="terabox")
        manifest.mark_upload_attempt(item["archive_id"])
        manifest.mark_verified(item["archive_id"], remote_size=len(payload))
        assert manifest.safe_to_delete_local(item["archive_id"]) is True


def test_new_upload_attempt_clears_previous_verified_state_until_rechecked(tmp_path):
    local = tmp_path / "result.bin"
    local.write_bytes(b"stable-result")
    manifest = ArchiveManifest(str(tmp_path / "manifest.json"))
    item = manifest.register(
        str(local), remote_path="/results/result.bin", provider="google-drive-rclone"
    )
    manifest.mark_upload_attempt(item["archive_id"])
    manifest.mark_verified(item["archive_id"], remote_size=local.stat().st_size)
    assert manifest.safe_to_delete_local(item["archive_id"]) is True

    # A fresh upload can replace the remote object. The old verification must
    # not stay true while status says uploaded_unverified.
    manifest.mark_upload_attempt(item["archive_id"])
    refreshed = manifest.get(item["archive_id"])
    assert refreshed is not None
    assert refreshed["status"] == "uploaded_unverified"
    assert refreshed["verified"] is False
    assert manifest.safe_to_delete_local(item["archive_id"]) is False


def test_wrong_remote_size_never_verifies():
    with tempfile.TemporaryDirectory() as root:
        local = os.path.join(root, "data.bin")
        with open(local, "wb") as handle:
            handle.write(b"12345")
        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        item = manifest.register(local, remote_path="/data/data.bin", provider="terabox")
        manifest.mark_upload_attempt(item["archive_id"])
        with pytest.raises(RuntimeError):
            manifest.mark_verified(item["archive_id"], remote_size=4)
        assert manifest.safe_to_delete_local(item["archive_id"]) is False


def test_same_content_can_have_drive_and_terabox_records_without_collision():
    with tempfile.TemporaryDirectory() as root:
        local = os.path.join(root, "same.bin")
        with open(local, "wb") as handle:
            handle.write(b"same content")
        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        drive = manifest.register(
            local,
            remote_path="/InfinityResearchAI/same.bin",
            provider="google-drive-rclone",
        )
        tera = manifest.register(
            local,
            remote_path="/archive/same.bin",
            provider="terabox",
        )
        assert drive["sha256"] == tera["sha256"]
        assert drive["archive_id"] != tera["archive_id"]
        assert len(manifest.items()) == 2

        manifest.mark_upload_attempt(drive["archive_id"])
        manifest.mark_verified(drive["archive_id"], remote_size=len(b"same content"))
        assert manifest.safe_to_delete_local(drive["archive_id"]) is True
        assert manifest.safe_to_delete_local(tera["archive_id"]) is False
        # Hash alone is ambiguous now and must fail closed rather than selecting
        # the wrong provider/path record.
        assert manifest.safe_to_delete_local(drive["sha256"]) is False
        assert manifest.get(drive["sha256"]) is None


def test_reregister_same_destination_is_idempotent_and_preserves_verified_state():
    with tempfile.TemporaryDirectory() as root:
        local = os.path.join(root, "paper.pdf")
        payload = b"paper"
        with open(local, "wb") as handle:
            handle.write(payload)
        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        first = manifest.register(local, remote_path="/paper.pdf", provider="drive")
        manifest.mark_upload_attempt(first["archive_id"])
        manifest.mark_verified(first["archive_id"], remote_size=len(payload))
        second = manifest.register(local, remote_path="/paper.pdf", provider="drive")
        assert second["archive_id"] == first["archive_id"]
        assert second["verified"] is True
        assert second["status"] == "verified"
        assert len(manifest.items()) == 1


def test_legacy_v1_sha_keyed_manifest_migrates_in_memory_and_on_next_save(tmp_path):
    local = tmp_path / "legacy.bin"
    local.write_bytes(b"legacy")
    digest = sha256_file(str(local))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({
        "version": 1,
        "items": {
            digest: {
                "local_path": str(local),
                "remote_path": "/legacy.bin",
                "provider": "drive",
                "size": len(b"legacy"),
                "sha256": digest,
                "status": "verified",
                "verified": True,
                "attempts": 1,
                "last_error": "",
                "updated_at": 1,
            }
        },
    }), encoding="utf-8")

    manifest = ArchiveManifest(str(path))
    item = manifest.get(digest)
    assert item is not None
    assert item["archive_id"].startswith("a_")
    assert item["verified"] is True
    manifest.mark_local_deleted(item["archive_id"])
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["version"] == 2
    assert list(stored["items"].keys()) == [item["archive_id"]]


def test_checksum_is_stable():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "x.txt")
        with open(path, "wb") as handle:
            handle.write(b"same")
        assert sha256_file(path) == sha256_file(path)
