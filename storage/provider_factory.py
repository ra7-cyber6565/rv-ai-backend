"""Runtime selection for approved zero-cost archive providers.

The research engine must not know vendor details. This factory is the only place
that turns configuration into a concrete archive provider. Unknown/paid provider
names fail closed; ``none`` is the safe default.

TeraBox is intentionally absent until official API access and zero-cost terms are
confirmed. Google Drive may be enabled through the open-source rclone adapter.
Optional archive encryption uses a user-configured rclone ``crypt`` remote; the
application never implements or stores encryption keys itself.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Any

from storage.google_drive_rclone import (
    RcloneGoogleDriveProvider,
    detect_rclone_remote_type,
)


_ALLOWED = {"none", "google-drive-rclone"}


@dataclass(frozen=True)
class ProviderSelection:
    name: str
    enabled: bool
    reason: str = ""


def _bool_env(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "true" if default else "false") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


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
    """Return non-secret readiness information without provider network login.

    Invalid configuration is intentionally normalized. The raw environment value
    is useful in local logs/errors but must not be reflected by public /health or
    /api responses because environment values are not inherently non-secret.

    When encryption is required, readiness additionally verifies the selected
    rclone remote's backend type using the local-only ``listremotes --long``
    command. OAuth/crypt secrets are never read or returned.
    """
    try:
        name = configured_provider_name()
    except Exception:  # noqa: BLE001 - public status is stable/fail-closed
        return {
            "provider": "invalid",
            "enabled": True,
            "ready": False,
            "reason": "archive_provider_configuration_invalid",
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
        requested_executable = str(os.getenv("RCLONE_EXE", "rclone") or "rclone").strip()
        resolved = shutil.which(requested_executable)
        if not resolved and os.path.isfile(requested_executable):
            resolved = os.path.abspath(requested_executable)
        available = bool(resolved)
        require_crypt = _bool_env("GOOGLE_DRIVE_ARCHIVE_REQUIRE_CRYPT", False)
        crypt_verified = None
        if require_crypt:
            crypt_verified = bool(
                remote
                and resolved
                and detect_rclone_remote_type(str(resolved), remote) == "crypt"
            )
        ready = bool(remote and available and (not require_crypt or crypt_verified is True))
        if not remote or not available:
            reason = "rclone install/authentication configuration incomplete"
        elif require_crypt and crypt_verified is not True:
            reason = "encrypted_archive_required_but_rclone_crypt_not_verified"
        else:
            reason = ""
        return {
            "provider": name,
            "enabled": True,
            "ready": ready,
            "remote_configured": bool(remote),
            "rclone_available": available,
            "encryption_required": require_crypt,
            "encryption_verified": crypt_verified,
            "reason": reason,
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
