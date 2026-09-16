from __future__ import annotations

from utils.railway_volume_status import railway_runtime_volume_status
from utils.storage_paths import public_storage_status


def test_non_railway_runtime_stays_unattested():
    status = railway_runtime_volume_status({}, durable_root="/data")
    assert status == {
        "railway_runtime": False,
        "railway_volume_attached": False,
        "railway_volume_mount_matches_durable_root": False,
        "persistent_volume_ready": False,
    }


def test_railway_runtime_without_volume_fails_closed():
    status = railway_runtime_volume_status(
        {
            "RAILWAY_PROJECT_ID": "project-1",
            "RAILWAY_SERVICE_ID": "service-1",
        },
        durable_root="/data",
    )
    assert status["railway_runtime"] is True
    assert status["railway_volume_attached"] is False
    assert status["railway_volume_mount_matches_durable_root"] is False
    assert status["persistent_volume_ready"] is False


def test_both_official_volume_markers_and_exact_mount_are_required():
    partial = railway_runtime_volume_status(
        {
            "RAILWAY_PROJECT_ID": "project-1",
            "RAILWAY_VOLUME_MOUNT_PATH": "/data",
        },
        durable_root="/data",
    )
    assert partial["railway_volume_attached"] is False
    assert partial["persistent_volume_ready"] is False

    matching = railway_runtime_volume_status(
        {
            "RAILWAY_PROJECT_ID": "project-1",
            "RAILWAY_VOLUME_NAME": "infinity-data",
            "RAILWAY_VOLUME_MOUNT_PATH": "/data",
        },
        durable_root="/data",
    )
    assert matching["railway_volume_attached"] is True
    assert matching["railway_volume_mount_matches_durable_root"] is True
    assert matching["persistent_volume_ready"] is True


def test_wrong_mount_never_becomes_persistence_ready():
    status = railway_runtime_volume_status(
        {
            "RAILWAY_ENVIRONMENT_ID": "env-1",
            "RAILWAY_VOLUME_NAME": "infinity-data",
            "RAILWAY_VOLUME_MOUNT_PATH": "/mnt/other",
        },
        durable_root="/data",
    )
    assert status["railway_runtime"] is True
    assert status["railway_volume_attached"] is True
    assert status["railway_volume_mount_matches_durable_root"] is False
    assert status["persistent_volume_ready"] is False


def test_public_storage_status_adds_only_path_free_railway_attestation():
    raw = {
        "available": True,
        "explicit": True,
        "split": True,
        "ephemeral_available": True,
        "disk_total_bytes": 1000,
        "disk_free_bytes": 500,
        "ephemeral_disk_total_bytes": 2000,
        "ephemeral_disk_free_bytes": 1500,
        "railway_runtime": True,
        "railway_volume_attached": True,
        "railway_volume_mount_matches_durable_root": True,
        "persistent_volume_ready": True,
        "root": "/data",
        "ephemeral_root": "/tmp/infinity_ai",
        "railway_volume_name": "must-not-leak",
        "railway_volume_mount_path": "/data",
    }
    public = public_storage_status(raw)
    assert public["railway_runtime"] is True
    assert public["railway_volume_attached"] is True
    assert public["railway_volume_mount_matches_durable_root"] is True
    assert public["persistent_volume_ready"] is True
    assert "/data" not in str(public)
    assert "/tmp/infinity_ai" not in str(public)
    assert "must-not-leak" not in str(public)


def test_legacy_non_railway_public_shape_is_unchanged():
    public = public_storage_status(
        {
            "available": True,
            "explicit": False,
            "split": False,
            "disk_total_bytes": 1000,
            "disk_free_bytes": 250,
        }
    )
    assert public == {
        "available": True,
        "explicit_root_configured": False,
        "disk_total_bytes": 1000,
        "disk_free_bytes": 250,
        "disk_free_percent": 25.0,
    }
