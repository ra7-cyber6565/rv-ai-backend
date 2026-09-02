"""Offline tests for operator archive status/retry/cleanup contracts."""
from __future__ import annotations

from pathlib import Path

from api import archive_routes
from utils.archive_manifest import ArchiveManifest


def test_cleanup_endpoint_deletes_only_checksum_verified_and_hides_paths(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("INFINITY_DATA_ROOT", str(root))

    verified = root / "verified.bin"
    unverified = root / "unverified.bin"
    verified.write_bytes(b"verified bytes")
    unverified.write_bytes(b"keep bytes")

    manifest = ArchiveManifest(str(root / "archive-manifest.json"))
    good = manifest.register(
        str(verified),
        remote_path="research-results/verified.bin",
        provider="google-drive-rclone",
    )
    manifest.mark_upload_attempt(good["archive_id"])
    manifest.mark_verified(
        good["archive_id"],
        remote_size=verified.stat().st_size,
        remote_sha256=good["sha256"],
    )
    manifest.register(
        str(unverified),
        remote_path="research-results/unverified.bin",
        provider="google-drive-rclone",
    )
    monkeypatch.setattr(archive_routes.archive_runtime, "manifest", manifest)

    result = archive_routes.cleanup_archive(target_mb=1, _admin=None)

    assert result["deleted_count"] == 1
    assert result["reclaimed_bytes"] == len(b"verified bytes")
    assert not verified.exists()
    assert unverified.exists()
    assert "matching remote SHA-256" in result["rule"]
    dumped = repr(result)
    assert str(verified) not in dumped
    assert str(unverified) not in dumped
    assert "verified.bin" not in dumped
    assert "unverified.bin" not in dumped


def test_size_only_verified_record_is_reported_but_not_deleted(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("INFINITY_DATA_ROOT", str(root))
    local = root / "size-only.bin"
    local.write_bytes(b"keep until checksum")
    manifest = ArchiveManifest(str(root / "manifest.json"))
    item = manifest.register(
        str(local),
        remote_path="research-results/size-only.bin",
        provider="google-drive-rclone",
    )
    manifest.mark_upload_attempt(item["archive_id"])
    manifest.mark_verified(item["archive_id"], remote_size=local.stat().st_size)
    monkeypatch.setattr(archive_routes.archive_runtime, "manifest", manifest)

    result = archive_routes.cleanup_archive(target_mb=1, _admin=None)
    assert result["deleted_count"] == 0
    assert result["skipped_by_reason"].get("checksum_not_verified") == 1
    assert local.exists()
    assert "size-only.bin" not in repr(result)


def test_archive_operational_routes_are_all_admin_guarded_in_source():
    root = Path(__file__).resolve().parents[1]
    text = (root / "api" / "archive_routes.py").read_text(encoding="utf-8")
    assert 'def archive_status(_admin: None = Depends(require_admin))' in text
    assert "def retry_archive(" in text
    assert "def cleanup_archive(" in text
    # Retry and cleanup put dependency on their multiline signatures; status is
    # inline. Three operator routes = at least three dependency declarations.
    assert text.count("Depends(require_admin)") >= 3


def test_cleanup_response_is_aggregate_only_even_when_nothing_is_eligible(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("INFINITY_DATA_ROOT", str(root))
    local = root / "private-name.bin"
    local.write_bytes(b"not archived")
    manifest = ArchiveManifest(str(root / "manifest.json"))
    manifest.register(
        str(local),
        remote_path="private/remote-name.bin",
        provider="google-drive-rclone",
    )
    monkeypatch.setattr(archive_routes.archive_runtime, "manifest", manifest)

    result = archive_routes.cleanup_archive(target_mb=1, _admin=None)
    assert result["deleted_count"] == 0
    assert result["skipped_by_reason"].get("not_verified") == 1
    assert "private-name.bin" not in repr(result)
    assert "remote-name.bin" not in repr(result)
    assert local.exists()
