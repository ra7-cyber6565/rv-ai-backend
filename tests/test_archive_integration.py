from pathlib import Path

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


def test_destructive_cleanup_requires_checksum_and_holds_manifest_lock():
    cleanup = _read("utils/storage_quota.py")
    assert 'item.get("checksum_verified")' in cleanup
    assert 'reason = "checksum_not_verified"' in cleanup
    assert "with manifest._lock" in cleanup
    assert "manifest.safe_to_delete_local(archive_ref)" in cleanup
    assert "os.remove(path)" in cleanup
    assert "manifest.mark_local_deleted(archive_ref)" in cleanup
    # The three destructive-boundary operations must occur inside the lock in
    # this order so re-upload cannot invalidate verification between them.
    lock = cleanup.index("with manifest._lock")
    check = cleanup.index("manifest.safe_to_delete_local(archive_ref)", lock)
    remove = cleanup.index("os.remove(path)", check)
    mark = cleanup.index("manifest.mark_local_deleted(archive_ref)", remove)
    assert lock < check < remove < mark


def test_google_drive_archive_can_fail_closed_on_encryption_and_sha256():
    provider = _read("storage/google_drive_rclone.py")
    factory = _read("storage/provider_factory.py")
    env = _read(".env.example")
    docs = _read("docs/GOOGLE_DRIVE_ARCHIVE_SETUP.md")

    assert "GOOGLE_DRIVE_ARCHIVE_REQUIRE_CRYPT" in provider
    assert "detect_rclone_remote_type" in provider
    assert '["listremotes", "--long"]' in provider
    assert '["hashsum", "SHA256", target, "--download"]' in provider
    assert "Remote SHA-256 content verification unavailable" in provider
    assert "encrypted_archive_required_but_rclone_crypt_not_verified" in factory
    assert "GOOGLE_DRIVE_ARCHIVE_REQUIRE_CRYPT=false" in env
    assert "matching SHA-256" in docs
