"""Concurrency regression for the archive manifest.

Parallel threads *and* independent backend processes writing the same JSON ledger
must not silently overwrite one another's read/modify/write update.
"""
from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from utils.archive_manifest import ArchiveManifest


ROOT = Path(__file__).resolve().parents[1]


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


def test_independent_process_registers_preserve_every_record(tmp_path: Path):
    """Real subprocesses catch the lost-update bug an RLock cannot catch."""
    manifest_path = str(tmp_path / "manifest.json")
    paths = []
    for index in range(8):
        path = tmp_path / f"process-{index}.bin"
        path.write_bytes(f"process-payload-{index}".encode())
        paths.append(path)

    env = dict(os.environ)
    inherited = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + inherited if inherited else "")
    processes: list[subprocess.Popen[str]] = []
    for path in paths:
        code = (
            "from utils.archive_manifest import ArchiveManifest\n"
            f"m=ArchiveManifest({manifest_path!r})\n"
            f"m.register({str(path)!r}, remote_path={'/archive/' + path.name!r}, provider='drive')\n"
        )
        processes.append(subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=str(ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ))

    failures = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        if process.returncode != 0:
            failures.append((process.returncode, stdout, stderr))
    assert failures == []

    saved = ArchiveManifest(manifest_path).items()
    assert len(saved) == len(paths)
    assert {Path(row["local_path"]).name for row in saved} == {path.name for path in paths}
