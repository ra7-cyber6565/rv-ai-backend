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


def test_new_archive_upload_attempt_invalidates_old_verification():
    manifest = _read("utils/archive_manifest.py")
    marker = 'item["status"] = "failed" if error else "uploaded_unverified"'
    pos = manifest.index(marker)
    assert 'item["verified"] = False' in manifest[pos:pos + 700]
