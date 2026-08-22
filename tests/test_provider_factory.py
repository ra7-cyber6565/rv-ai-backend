"""Offline tests for the zero-cost archive provider factory."""
from __future__ import annotations

import pytest

from storage.provider_factory import build_provider, configured_provider_name, provider_status


def test_default_provider_is_disabled(monkeypatch):
    monkeypatch.delenv("CLOUD_ARCHIVE_PROVIDER", raising=False)
    assert configured_provider_name() == "none"
    assert build_provider() is None
    status = provider_status()
    assert status["provider"] == "none"
    assert status["enabled"] is False
    assert status["ready"] is True


def test_google_drive_aliases_normalize(monkeypatch):
    for alias in ("google-drive", "gdrive", "drive", "google-drive-rclone"):
        monkeypatch.setenv("CLOUD_ARCHIVE_PROVIDER", alias)
        assert configured_provider_name() == "google-drive-rclone"


def test_unknown_or_paid_sounding_provider_fails_closed(monkeypatch):
    for name in ("s3", "dropbox", "premium-drive", "terabox"):
        monkeypatch.setenv("CLOUD_ARCHIVE_PROVIDER", name)
        with pytest.raises(RuntimeError, match="approved zero-cost"):
            configured_provider_name()
        status = provider_status()
        # Explicit-but-invalid configuration is treated as enabled/not-ready so
        # /health degrades rather than silently pretending archive was disabled.
        assert status["enabled"] is True
        assert status["ready"] is False
        assert status["provider"] == "invalid"
        assert name not in repr(status).lower()
        assert status["reason"] == "archive_provider_configuration_invalid"


def test_invalid_provider_status_never_reflects_arbitrary_env_value(monkeypatch):
    marker = "private-env-value-do-not-reflect"
    monkeypatch.setenv("CLOUD_ARCHIVE_PROVIDER", marker)
    status = provider_status()
    assert marker not in repr(status)
    assert status == {
        "provider": "invalid",
        "enabled": True,
        "ready": False,
        "reason": "archive_provider_configuration_invalid",
    }


def test_drive_status_does_not_expose_remote_secret_material(monkeypatch):
    monkeypatch.setenv("CLOUD_ARCHIVE_PROVIDER", "google-drive-rclone")
    monkeypatch.setenv("GOOGLE_DRIVE_RCLONE_REMOTE", "drive")
    monkeypatch.setenv("RCLONE_EXE", "rclone")
    monkeypatch.setattr("storage.provider_factory.shutil.which", lambda _: "/fake/rclone")
    status = provider_status()
    assert status["provider"] == "google-drive-rclone"
    assert status["ready"] is True
    text = repr(status).lower()
    assert "oauth" not in text
    assert "token" not in text
    assert "secret" not in text
    # Status reports only presence/readiness, never the configured rclone remote.
    assert "'drive'" not in text


def test_build_drive_provider_requires_actual_remote_and_executable(monkeypatch):
    monkeypatch.setenv("CLOUD_ARCHIVE_PROVIDER", "google-drive-rclone")
    monkeypatch.delenv("GOOGLE_DRIVE_RCLONE_REMOTE", raising=False)
    monkeypatch.setattr("storage.google_drive_rclone.shutil.which", lambda _: "/fake/rclone")
    with pytest.raises(RuntimeError, match="RCLONE_REMOTE"):
        build_provider()
