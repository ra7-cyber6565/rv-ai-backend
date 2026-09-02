from pathlib import Path
import os
import subprocess

import pytest

from storage.google_drive_rclone import detect_rclone_remote_type
from utils.archive_manifest import ArchiveManifest, sha256_file
from utils.storage_quota import cleanup_verified_archives

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_main_wires_archive_router_but_keeps_health_status_cheap():
    main = _read("main.py")
    assert "from api.archive_routes import router as archive_router" in main
    assert "include_router(archive_router" in main
    assert '"cloud_archive": provider_status()' in main
    assert "archive_runtime.public_status()" not in main
    assert "/api/v1/archive/status" in main


def test_archive_runtime_persists_intent_before_worker_submission():
    text = _read("storage/archive_runtime.py")
    enqueue = text.index("self.retry_queue.enqueue(")
    submit = text.index("self._ensure_executor().submit(", enqueue)
    assert enqueue < submit
    assert "delete_local=False" in text
    assert '"local_auto_delete": False' in text


def test_completed_job_result_is_connected_to_archive_intent():
    jobs = _read("utils/research_jobs.py")
    assert "self._record_archive_intent_locked(job, final_path)" in jobs
    assert 'return f"research-results/{job.job_id}.json.gz"' in jobs
    assert "if not self._delete_result_file_locked(old):" in jobs


def test_archive_retry_endpoint_requires_admin_guard():
    routes = _read("api/archive_routes.py")
    assert '@router.get("/archive/status")' in routes
    assert '@router.post("/archive/retry"' in routes
    assert "Depends(require_admin)" in routes


def test_new_archive_upload_attempt_invalidates_old_verification_and_checksum():
    manifest = _read("utils/archive_manifest.py")
    marker = 'item["status"] = "failed" if error else "uploaded_unverified"'
    pos = manifest.index(marker)
    window = manifest[pos:pos + 1000]
    assert 'item["verified"] = False' in window
    assert 'item["checksum_verified"] = False' in window
    assert 'item["verification_method"] = ""' in window


def test_destructive_cleanup_requires_real_checksum_proof(monkeypatch, tmp_path):
    """Size-only cloud verification must never authorize local deletion.

    This deliberately exercises the public cleanup boundary instead of asserting
    one variable name in its source. Refactors are allowed; weakening checksum
    safety is not.
    """
    root = tmp_path / "runtime"
    root.mkdir()
    local = root / "result.json.gz"
    local.write_bytes(b"research-result-v1")

    manifest = ArchiveManifest(str(tmp_path / "manifest.json"))
    item = manifest.register(
        str(local), remote_path="research-results/result.json.gz", provider="fake-cloud"
    )
    archive_id = item["archive_id"]

    monkeypatch.setattr("utils.storage_quota.configured_root", lambda: (str(root), True))

    # Observing the right size proves existence only. It is intentionally too
    # weak for destructive cleanup.
    manifest.mark_verified(archive_id, remote_size=local.stat().st_size)
    blocked = cleanup_verified_archives(
        manifest, target_reclaim_bytes=local.stat().st_size
    )
    assert local.exists()
    assert blocked["deleted_count"] == 0
    assert any(row.get("reason") == "checksum_not_verified" for row in blocked["skipped"])

    # The exact same record becomes deletable only after a matching SHA-256 is
    # independently recorded by the provider boundary.
    digest = sha256_file(str(local))
    manifest.mark_verified(
        archive_id,
        remote_size=local.stat().st_size,
        remote_sha256=digest,
    )
    cleaned = cleanup_verified_archives(
        manifest, target_reclaim_bytes=len(b"research-result-v1")
    )
    assert not local.exists()
    assert cleaned["deleted_count"] == 1
    assert manifest.get(archive_id)["local_deleted"] is True


def test_destructive_cleanup_holds_manifest_lock_across_check_remove_and_mark():
    """Keep the TOCTOU critical section explicit at the destructive boundary."""
    cleanup = _read("utils/storage_quota.py")
    lock = cleanup.index("with manifest._lock")
    check = cleanup.index("manifest.safe_to_delete_local(archive_ref)", lock)
    remove = cleanup.index("os.remove(path)", check)
    mark = cleanup.index("manifest.mark_local_deleted(archive_ref)", remove)
    assert lock < check < remove < mark


def test_rclone_remote_type_detection_uses_safe_local_metadata_command(monkeypatch):
    """Verify the exact argv contract without depending on source formatting."""
    detect_rclone_remote_type.cache_clear()
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append((list(cmd), dict(kwargs)))
        return subprocess.CompletedProcess(cmd, 0, stdout="secure: crypt\n", stderr="")

    monkeypatch.setattr("storage.google_drive_rclone.subprocess.run", fake_run)
    assert detect_rclone_remote_type("/safe/rclone", "secure", 8) == "crypt"
    assert seen and seen[0][0] == ["/safe/rclone", "listremotes", "--long"]
    assert seen[0][1]["shell"] is False
    assert seen[0][1]["stdin"] is subprocess.DEVNULL


def test_google_drive_archive_can_fail_closed_on_encryption_and_sha256():
    provider = _read("storage/google_drive_rclone.py")
    factory = _read("storage/provider_factory.py")
    env = _read(".env.example")
    docs = _read("docs/GOOGLE_DRIVE_ARCHIVE_SETUP.md")

    assert "GOOGLE_DRIVE_ARCHIVE_REQUIRE_CRYPT" in provider
    assert '_bool_env("GOOGLE_DRIVE_ARCHIVE_REQUIRE_CRYPT", True)' in provider
    assert "detect_rclone_remote_type" in provider
    assert '"hashsum", "SHA256", target, "--download"' in provider
    assert "Remote SHA-256 content verification unavailable" in provider
    assert '_bool_env("GOOGLE_DRIVE_ARCHIVE_REQUIRE_CRYPT", True)' in factory
    assert "encrypted_archive_required_but_rclone_crypt_not_verified" in factory
    assert "GOOGLE_DRIVE_ARCHIVE_REQUIRE_CRYPT=true" in env
    assert "matching SHA-256" in docs
