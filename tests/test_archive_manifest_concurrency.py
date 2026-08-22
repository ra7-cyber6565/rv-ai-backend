"""Concurrency regression for the archive manifest.

Two same-process research/archive threads writing the same JSON ledger must not
silently overwrite one another's read/modify/write update.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from utils.archive_manifest import ArchiveManifest


def test_concurrent_registers_preserve_all_records(tmp_path: Path):
    manifest_path = str(tmp_path / "manifest.json")
    files = []
    for index in range(12):
        path = tmp_path / f"file-{index}.bin"
        path.write_bytes(f"payload-{index}".encode())
        files.append(path)

    def register(path: Path):
        # Separate instances mimic independent request/job code paths that point
        # to the same process-local manifest file.
        manifest = ArchiveManifest(manifest_path)
        return manifest.register(
            str(path),
            remote_path=f"/archive/{path.name}",
            provider="drive",
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(register, files))

    manifest = ArchiveManifest(manifest_path)
    saved = manifest.items()
    assert len(saved) == len(files)
    assert {row["sha256"] for row in saved} == {row["sha256"] for row in records}


def test_concurrent_status_updates_do_not_drop_other_record(tmp_path: Path):
    manifest_path = str(tmp_path / "manifest.json")
    manifest = ArchiveManifest(manifest_path)

    left = tmp_path / "left.bin"
    right = tmp_path / "right.bin"
    left.write_bytes(b"left")
    right.write_bytes(b"right")

    left_item = manifest.register(str(left), remote_path="/left", provider="drive")
    right_item = manifest.register(str(right), remote_path="/right", provider="drive")

    def update_left():
        ArchiveManifest(manifest_path).mark_upload_attempt(left_item["sha256"])

    def update_right():
        ArchiveManifest(manifest_path).mark_upload_attempt(right_item["sha256"], error="offline")

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda fn: fn(), [update_left, update_right]))

    final = ArchiveManifest(manifest_path)
    assert final.get(left_item["sha256"])["status"] == "uploaded_unverified"
    assert final.get(right_item["sha256"])["status"] == "failed"
