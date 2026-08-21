"""Runtime selection for approved zero-cost archive providers.

The research engine must not know vendor details. This factory is the only place
that turns configuration into a concrete archive provider. Unknown/paid provider
names fail closed; ``none`` is the safe default.

TeraBox is intentionally absent until official API access and zero-cost terms are
confirmed. Google Drive may be enabled through the open-source rclone adapter.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Any

from storage.google_drive_rclone import RcloneGoogleDriveProvider


_ALLOWED = {"none", "google-drive-rclone"}


@dataclass(frozen=True)
class ProviderSelection:
    name: str
    enabled: bool
    reason: str = ""


def configured_provider_name() -> str:
    raw = str(os.getenv("CLOUD_ARCHIVE_PROVIDER", "none") or "none").strip().lower()
    aliases = {
        "": "none",
        "off": "none",
        "disabled": "none",
        "google-drive": "google-drive-rclone",
        "gdrive": "google-drive-rclone",
        "drive": "google-drive-rclone",
    }
    name = aliases.get(raw, raw)
    if name not in _ALLOWED:
        raise RuntimeError(
            f"Unsupported cloud archive provider '{raw}'. Only explicitly approved zero-cost providers are allowed."
        )
    return name


def provider_status() -> dict[str, Any]:
    """Return non-secret readiness information without forcing provider login."""
    try:
        name = configured_provider_name()
    except Exception as exc:  # noqa: BLE001 - config status should remain readable
        return {
            "provider": "invalid",
            "enabled": False,
            "ready": False,
            "reason": str(exc)[:240],
        }

    if name == "none":
        return {
            "provider": "none",
            "enabled": False,
            "ready": True,
            "reason": "Cloud archive disabled; local verified-retention rules remain active.",
        }

    if name == "google-drive-rclone":
        remote = str(os.getenv("GOOGLE_DRIVE_RCLONE_REMOTE", "") or "").strip()
        executable = str(os.getenv("RCLONE_EXE", "rclone") or "rclone").strip()
        # Do not instantiate when merely asking status: that would fail if rclone
        # is absent and makes health/status endpoints unnecessarily fragile.
        available = bool(shutil.which(executable) or os.path.isfile(executable))
        ready = bool(remote and available)
        return {
            "provider": name,
            "enabled": True,
            "ready": ready,
            "remote_configured": bool(remote),
            "rclone_available": available,
            "reason": "" if ready else "rclone install/authentication configuration incomplete",
        }

    return {"provider": name, "enabled": False, "ready": False, "reason": "unavailable"}


def build_provider():
    """Instantiate the selected provider or return ``None`` when disabled."""
    name = configured_provider_name()
    if name == "none":
        return None
    if name == "google-drive-rclone":
        return RcloneGoogleDriveProvider()
    raise RuntimeError(f"Cloud archive provider not implemented: {name}")
