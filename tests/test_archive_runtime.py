"""Offline tests for storage.archive_runtime crash/retention semantics."""
from __future__ import annotations

import time

from storage.archive_runtime import ArchiveRuntime
from utils.archive_manifest import ArchiveManifest
from utils.archive_retry import ArchiveRetryQueue
from utils.cloud_storage import RemoteObject


class _FakeProvider:
    name = "fake-drive"

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def upload_file(self, local_path: str, remote_path: str) -> RemoteObject:
        data = open(local_path, "rb").read()
        self.objects[remote_path] = data
        return RemoteObject(path=remote_path, size=len(data))

    def stat(self, remote_path: str) -> RemoteObject:
        data = self.objects[remote_path]
        return RemoteObject(path=remote_path, size=len(data))


def _runtime(tmp_path, monkeypatch, *, ready: bool = True):
    monkeypatch.setenv("CLOUD_ARCHIVE_PROVIDER", "google-drive-rclone")
    monkeypatch.setenv("INFINITY_DATA_ROOT", str(tmp_path / "data"))
    provider = _FakeProvider()
    manifest = ArchiveManifest(str(tmp_path / "manifest.json"))
    retry = ArchiveRetryQueue(str(tmp_path / "retry.json"))
    runtime = ArchiveRuntime(
        manifest=manifest,
        retry_queue=retry,
        provider_builder=lambda: provider,
        provider_status_func=lambda: {
            "provider": "fake-drive",
            "enabled": True,
            "ready": ready,
            "remote_configured": ready,
            "rclone_available": ready,
            "reason": "secret-looking detail must not become public",
        },
        max_pending=2,
    )
    return runtime, provider, manifest, retry


def _wait(runtime: ArchiveRuntime, timeout: float = 2.0):
    end = time.time() + timeout
    while time.time() < end:
        if runtime.public_status()["background"]["pending"] == 0:
            return
        time.sleep(0.01)
    raise AssertionError("archive worker timeout")


def test_submit_records_durable_intent_before_background_upload(tmp_path, monkeypatch):
    runtime, _provider, manifest, retry = _runtime(tmp_path, monkeypatch)
    local = tmp_path / "result.json.gz"
    local.write_bytes(b"completed research")

    submitted = runtime.submit_file(str(local), "research-results/job.json.gz")
    assert submitted["enabled"] is True
    assert submitted["intent_recorded"] is True
    assert submitted["accepted"] is True
    # The crash-safe retry record exists synchronously, before we wait for the
    # background upload to finish.
    assert len(retry.items()) == 1

    _wait(runtime)
    rows = manifest.items()
    assert len(rows) == 1
    assert rows[0]["verified"] is True
    assert rows[0]["status"] == "verified"
    assert retry.summary()["pending"] == 0
    assert local.exists()  # archive never auto-deletes local bytes
    runtime.close()


def test_not_ready_provider_keeps_local_and_retry_intent(tmp_path, monkeypatch):
    runtime, _provider, manifest, retry = _runtime(tmp_path, monkeypatch, ready=False)
    local = tmp_path / "result.json.gz"
    local.write_bytes(b"keep me")

    submitted = runtime.submit_file(str(local), "research-results/job.json.gz")
    assert submitted == {
        "enabled": True,
        "accepted": False,
        "intent_recorded": True,
        "reason": "provider_not_ready",
    }
    assert local.exists()
    assert manifest.items() == []
    assert retry.summary()["pending"] == 1
    assert runtime.local_delete_allowed(str(local), "research-results/job.json.gz") is False
    runtime.close()


def test_verified_exact_destination_can_authorize_later_cleanup(tmp_path, monkeypatch):
    runtime, _provider, _manifest, _retry = _runtime(tmp_path, monkeypatch)
    local = tmp_path / "result.json.gz"
    local.write_bytes(b"verified")
    remote = "research-results/exact.json.gz"
    runtime.submit_file(str(local), remote)
    _wait(runtime)

    assert runtime.local_delete_allowed(str(local), remote) is True
    assert runtime.local_delete_allowed(str(local), "research-results/other.json.gz") is False
    runtime.close()


def test_public_status_never_exposes_paths_or_provider_reason(tmp_path, monkeypatch):
    runtime, _provider, _manifest, _retry = _runtime(tmp_path, monkeypatch, ready=False)
    local = tmp_path / "private" / "secret-result.json.gz"
    local.parent.mkdir()
    local.write_bytes(b"private")
    remote = "user-private-folder/secret-result.json.gz"
    runtime.submit_file(str(local), remote)

    status = runtime.public_status()
    dumped = repr(status)
    assert str(local) not in dumped
    assert remote not in dumped
    assert "secret-looking detail" not in dumped
    assert status["archive_required_for_local_cleanup"] is True
    assert status["retry_queue"]["pending"] == 1
    assert status["local_auto_delete"] is False
    runtime.close()


def test_disabled_archive_does_not_create_retry_intent(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUD_ARCHIVE_PROVIDER", "none")
    manifest = ArchiveManifest(str(tmp_path / "manifest.json"))
    retry = ArchiveRetryQueue(str(tmp_path / "retry.json"))
    runtime = ArchiveRuntime(
        manifest=manifest,
        retry_queue=retry,
        provider_builder=lambda: None,
        provider_status_func=lambda: {"provider": "none", "enabled": False, "ready": True},
    )
    local = tmp_path / "local.bin"
    local.write_bytes(b"x")
    submitted = runtime.submit_file(str(local), "unused/local.bin")
    assert submitted["reason"] == "disabled"
    assert submitted["intent_recorded"] is False
    assert retry.summary()["pending"] == 0
    assert runtime.local_delete_allowed(str(local), "unused/local.bin") is True
    runtime.close()
