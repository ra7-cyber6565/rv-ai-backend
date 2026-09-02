from __future__ import annotations

import os
import tempfile
import threading
import time
from unittest.mock import patch

import pytest

from utils.archive_manifest import ArchiveManifest
from utils.storage_quota import (
    StoragePolicy,
    StorageQuotaError,
    assert_capacity,
    cleanup_verified_archives,
    folder_size_bytes,
)


def test_folder_size_ignores_missing_root():
    assert folder_size_bytes("/definitely/missing/infinity-path") == 0


def test_assert_capacity_blocks_when_app_limit_would_be_exceeded():
    with tempfile.TemporaryDirectory() as root:
        with open(os.path.join(root, "x.bin"), "wb") as handle:
            handle.write(b"x" * 20)
        policy = StoragePolicy(max_local_bytes=25, min_free_bytes=1)
        with patch.dict(os.environ, {"INFINITY_DATA_ROOT": root}, clear=False):
            with pytest.raises(StorageQuotaError):
                assert_capacity(10, policy=policy)


def test_cleanup_deletes_only_checksum_verified_file_inside_root():
    with tempfile.TemporaryDirectory() as root:
        verified = os.path.join(root, "verified.bin")
        pending = os.path.join(root, "pending.bin")
        with open(verified, "wb") as handle:
            handle.write(b"v" * 40)
        with open(pending, "wb") as handle:
            handle.write(b"p" * 50)

        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        v = manifest.register(verified, remote_path="/v.bin", provider="fake")
        p = manifest.register(pending, remote_path="/p.bin", provider="fake")
        manifest.mark_upload_attempt(v["sha256"])
        manifest.mark_verified(
            v["sha256"], remote_size=40, remote_sha256=v["sha256"]
        )

        with patch.dict(os.environ, {"INFINITY_DATA_ROOT": root}, clear=False):
            result = cleanup_verified_archives(manifest, target_reclaim_bytes=1)

        assert result["deleted_count"] == 1
        assert not os.path.exists(verified)
        assert os.path.exists(pending)
        assert manifest.get(v["sha256"])["local_deleted"] is True
        assert manifest.safe_to_delete_local(p["sha256"]) is False


def test_cleanup_refuses_size_only_verified_file():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "size-only.bin")
        with open(path, "wb") as handle:
            handle.write(b"123456")
        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        item = manifest.register(path, remote_path="/size-only.bin", provider="fake")
        manifest.mark_upload_attempt(item["archive_id"])
        manifest.mark_verified(item["archive_id"], remote_size=6)

        with patch.dict(os.environ, {"INFINITY_DATA_ROOT": root}, clear=False):
            result = cleanup_verified_archives(manifest, target_reclaim_bytes=1)

        assert result["deleted_count"] == 0
        assert os.path.exists(path)
        assert any(entry["reason"] == "checksum_not_verified" for entry in result["skipped"])


def test_cleanup_refuses_verified_path_outside_configured_root():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
        path = os.path.join(outside, "outside.bin")
        with open(path, "wb") as handle:
            handle.write(b"safe")
        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        item = manifest.register(path, remote_path="/outside.bin", provider="fake")
        manifest.mark_upload_attempt(item["sha256"])
        manifest.mark_verified(
            item["sha256"], remote_size=4, remote_sha256=item["sha256"]
        )

        with patch.dict(os.environ, {"INFINITY_DATA_ROOT": root}, clear=False):
            result = cleanup_verified_archives(manifest, target_reclaim_bytes=1)

        assert result["deleted_count"] == 0
        assert os.path.exists(path)
        assert any(entry["reason"] == "outside_storage_root" for entry in result["skipped"])


def test_cleanup_holds_manifest_lock_across_final_check_and_delete(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    path = root / "race.bin"
    path.write_bytes(b"race-safe")
    manifest = ArchiveManifest(str(root / "manifest.json"))
    item = manifest.register(
        str(path), remote_path="archive/race.bin", provider="google-drive-rclone"
    )
    manifest.mark_upload_attempt(item["archive_id"])
    manifest.mark_verified(
        item["archive_id"],
        remote_size=path.stat().st_size,
        remote_sha256=item["sha256"],
    )

    start_update = threading.Event()
    update_entered = threading.Event()
    update_done = threading.Event()
    real_remove = os.remove

    def competing_upload():
        start_update.wait(timeout=2)
        update_entered.set()
        manifest.mark_upload_attempt(item["archive_id"])
        update_done.set()

    thread = threading.Thread(target=competing_upload, daemon=True)
    thread.start()

    def guarded_remove(target):
        start_update.set()
        assert update_entered.wait(timeout=1)
        # The competing upload is trying to clear verification now. It must be
        # blocked on the same manifest RLock until local removal + deletion mark
        # finish; otherwise cleanup has a verification-to-delete TOCTOU window.
        time.sleep(0.05)
        assert update_done.is_set() is False
        real_remove(target)

    monkeypatch.setattr("utils.storage_quota.os.remove", guarded_remove)
    monkeypatch.setenv("INFINITY_DATA_ROOT", str(root))
    result = cleanup_verified_archives(manifest, target_reclaim_bytes=1)
    thread.join(timeout=1)

    assert result["deleted_count"] == 1
    assert path.exists() is False
    assert update_done.is_set() is True
    # The delayed new attempt may now make the record unverified, but it was not
    # allowed to alter the remote object before the strongly verified local copy
    # was atomically retired.
    assert manifest.get(item["archive_id"])["verified"] is False
