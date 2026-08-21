"""Offline tests for the optional zero-cost Google Drive rclone adapter."""
from __future__ import annotations

import json
import subprocess

import pytest

from storage.google_drive_rclone import RcloneGoogleDriveProvider


def _provider(monkeypatch, *, runner=None):
    monkeypatch.setattr("storage.google_drive_rclone.shutil.which", lambda _: "/fake/rclone")
    if runner is not None:
        monkeypatch.setattr("storage.google_drive_rclone.subprocess.run", runner)
    return RcloneGoogleDriveProvider(
        remote_name="drive",
        archive_root="InfinityResearchAI",
        executable="rclone",
        timeout_seconds=30,
    )


def test_requires_preconfigured_remote(monkeypatch):
    monkeypatch.delenv("GOOGLE_DRIVE_RCLONE_REMOTE", raising=False)
    monkeypatch.setattr("storage.google_drive_rclone.shutil.which", lambda _: "/fake/rclone")
    with pytest.raises(RuntimeError, match="RCLONE_REMOTE"):
        RcloneGoogleDriveProvider(executable="rclone")


def test_remote_path_traversal_and_remote_switch_are_blocked(monkeypatch):
    provider = _provider(monkeypatch)
    with pytest.raises(ValueError, match="traversal"):
        provider._target("../secret.txt")
    with pytest.raises(ValueError, match="':'"):
        provider._target("other:secret.txt")


def test_stat_reads_size_and_sha256_without_exposing_token(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert kwargs["shell"] is False
        assert cmd[0] == "/fake/rclone"
        payload = {
            "Path": "research/paper.pdf",
            "Name": "paper.pdf",
            "Size": 1234,
            "IsDir": False,
            "ID": "drive-object-id",
            "Hashes": {"MD5": "abcd", "SHA-256": "A1B2C3"},
        }
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    provider = _provider(monkeypatch, runner=fake_run)
    obj = provider.stat("research/paper.pdf")
    assert obj.size == 1234
    assert obj.sha256 == "a1b2c3"
    assert obj.etag == "drive-object-id"


def test_upload_uses_copyto_exact_file_then_stats(monkeypatch, tmp_path):
    local = tmp_path / "paper.pdf"
    local.write_bytes(b"abc")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "copyto":
            assert cmd[2] == str(local.resolve())
            assert cmd[3] == "drive:InfinityResearchAI/research/paper.pdf"
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        assert cmd[1] == "lsjson"
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"Size": 3, "IsDir": False, "Hashes": {}}),
            stderr="",
        )

    provider = _provider(monkeypatch, runner=fake_run)
    out = provider.upload_file(str(local), "research/paper.pdf")
    assert out.size == 3
    assert [call[1] for call in calls] == ["copyto", "lsjson"]


def test_failure_keeps_raw_rclone_stderr_private(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            9,
            stdout="",
            stderr="oauth_token=VERY-SECRET provider-account@example.com",
        )

    provider = _provider(monkeypatch, runner=fake_run)
    with pytest.raises(RuntimeError) as captured:
        provider.stat("research/paper.pdf")
    text = str(captured.value)
    assert "VERY-SECRET" not in text
    assert "provider-account" not in text
    assert "exit=9" in text


def test_status_contains_no_oauth_material(monkeypatch):
    provider = _provider(monkeypatch)
    status = provider.status()
    assert status["configured"] is True
    assert status["remote_name"] == "drive"
    assert "token" not in repr(status).lower()
    assert "secret" not in repr(status).lower()
