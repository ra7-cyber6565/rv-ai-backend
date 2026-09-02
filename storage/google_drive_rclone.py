"""Google Drive archive provider through the open-source ``rclone`` CLI.

Why this adapter exists:
- TeraBox Open Platform approval is optional/pending and must not block the app.
- rclone uses Google Drive's official OAuth/API flow but keeps credentials out of
  this repository and out of the Android APK.
- no shell is used; every argument is passed as a list to avoid command injection.
- ArchiveCoordinator still performs independent remote stat/size/hash validation
  and controls deletion. This provider never deletes local files.
- at-rest encryption is delegated to rclone's mature ``crypt`` backend and is
  fail-closed by default when Drive archiving is enabled; the app never implements
  or stores its own encryption key material.
- if the remote cannot expose a native SHA-256 (notably rclone crypt), the adapter
  deliberately downloads the logical remote object through rclone and hashes the
  returned plaintext. Size-only verification is not accepted for this provider.

Runtime prerequisites are intentionally external: the user installs rclone and
creates/authenticates a Google Drive remote. No OAuth token or crypt password is
committed here.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Any

from utils.cloud_storage import RemoteObject


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _bool_env(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "true" if default else "false") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off", ""}:
        return False
    # Security-sensitive switches fail closed rather than treating a typo as on.
    return False


def _safe_component_path(value: str, *, allow_empty: bool = False) -> str:
    text = str(value or "").replace("\\", "/").strip().strip("/")
    if not text:
        if allow_empty:
            return ""
        raise ValueError("Google Drive remote path khaali nahi ho sakta")
    if "\x00" in text:
        raise ValueError("Google Drive remote path invalid hai")
    parts = [part for part in PurePosixPath(text).parts if part not in {"", "/"}]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("Google Drive remote path traversal blocked")
    # A colon can be interpreted by rclone as a new remote/backend boundary.
    if any(":" in part for part in parts):
        raise ValueError("Google Drive remote path me ':' allowed nahi hai")
    return "/".join(parts)


@lru_cache(maxsize=16)
def detect_rclone_remote_type(executable: str, remote_name: str, timeout_seconds: int = 8) -> str:
    """Return rclone backend type (e.g. ``drive``/``crypt``) without secrets.

    ``rclone listremotes --long`` is local/config-only and prints remote names +
    backend type; unlike ``rclone config show`` it does not dump OAuth tokens or
    crypt passwords. Empty string means the type could not be verified.
    """
    try:
        result = subprocess.run(
            [str(executable), "listremotes", "--long"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(2, min(30, int(timeout_seconds))),
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return ""
    if result.returncode != 0:
        return ""

    wanted = str(remote_name or "").strip().rstrip(":")
    for raw in (result.stdout or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        # Current rclone prints e.g. ``infinitycrypt: crypt``. Accept generic
        # whitespace/tab separation while never parsing stderr/config secrets.
        parts = line.split()
        if not parts:
            continue
        name = parts[0].rstrip(":")
        if name != wanted:
            continue
        if len(parts) < 2:
            return ""
        return parts[1].strip().lower().rstrip(":")
    return ""


class RcloneGoogleDriveProvider:
    """Provider-neutral archive adapter backed by a configured rclone remote."""

    name = "google-drive-rclone"

    def __init__(
        self,
        *,
        remote_name: str | None = None,
        archive_root: str | None = None,
        executable: str | None = None,
        timeout_seconds: int | None = None,
        require_crypt: bool | None = None,
    ):
        self.remote_name = str(remote_name or os.getenv("GOOGLE_DRIVE_RCLONE_REMOTE", "")).strip()
        if not self.remote_name:
            raise RuntimeError(
                "GOOGLE_DRIVE_RCLONE_REMOTE configure nahi hai. Pehle rclone OAuth remote setup karein."
            )
        if any(ch in self.remote_name for ch in ":/\\\x00"):
            raise ValueError("GOOGLE_DRIVE_RCLONE_REMOTE invalid hai")

        root_value = archive_root if archive_root is not None else os.getenv(
            "GOOGLE_DRIVE_ARCHIVE_ROOT", "InfinityResearchAI"
        )
        self.archive_root = _safe_component_path(root_value, allow_empty=True)

        requested_executable = str(executable or os.getenv("RCLONE_EXE", "rclone")).strip()
        resolved = shutil.which(requested_executable)
        if not resolved and os.path.isfile(requested_executable):
            resolved = os.path.abspath(requested_executable)
        if not resolved:
            raise RuntimeError("rclone executable nahi mila; Google Drive archive provider disabled hai")
        self.executable = resolved
        self.timeout_seconds = int(timeout_seconds or _int_env("RCLONE_TIMEOUT_SECONDS", 1800, 30, 7200))

        self.require_crypt = (
            _bool_env("GOOGLE_DRIVE_ARCHIVE_REQUIRE_CRYPT", True)
            if require_crypt is None else bool(require_crypt)
        )
        self.remote_type = ""
        if self.require_crypt:
            self.remote_type = detect_rclone_remote_type(self.executable, self.remote_name)
            if self.remote_type != "crypt":
                raise RuntimeError(
                    "Encrypted archive required hai, lekin selected rclone remote ko "
                    "'crypt' backend ke roop me verify nahi kiya ja saka. Local file retained hai."
                )

    def _target(self, remote_path: str) -> str:
        safe = _safe_component_path(remote_path)
        joined = f"{self.archive_root}/{safe}" if self.archive_root else safe
        return f"{self.remote_name}:{joined}"

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                [self.executable, *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Google Drive rclone operation timeout hua; local file retained hai") from exc
        except OSError as exc:
            raise RuntimeError("rclone process start nahi ho saka; local file retained hai") from exc
        if result.returncode != 0:
            # Do not reflect raw stderr because provider/config output may contain
            # account details. Technical local logs can inspect rclone separately.
            raise RuntimeError(
                f"Google Drive rclone operation failed (exit={result.returncode}); local file retained hai"
            )
        return result

    def _download_sha256(self, target: str) -> str:
        """End-to-end hash the logical remote bytes through rclone.

        Google Drive normally exposes MD5 rather than SHA-256, and rclone crypt
        intentionally stores no plaintext hashes. ``hashsum --download`` reads
        the remote object through the configured backend (decrypting crypt data)
        and calculates SHA-256 locally. If this cannot complete, verification is
        refused and the local source remains retained/retryable.
        """
        result = self._run(["hashsum", "SHA256", target, "--download"])
        for raw in (result.stdout or "").splitlines():
            match = re.match(r"^\s*([0-9a-fA-F]{64})\s+", raw)
            if match:
                return match.group(1).lower()
        raise RuntimeError(
            "Remote SHA-256 content verification unavailable; local file retained hai"
        )

    def upload_file(self, local_path: str, remote_path: str) -> RemoteObject:
        local = os.path.abspath(local_path)
        if not os.path.isfile(local):
            raise FileNotFoundError(local)
        target = self._target(remote_path)
        # copyto targets exactly one file; no shell expansion or wildcard is used.
        # If remote_name is a verified crypt remote, rclone encrypts filename and
        # content before the underlying Drive remote sees them.
        self._run(["copyto", local, target, "--retries", "1", "--low-level-retries", "2"])
        return self.stat(remote_path)

    def stat(self, remote_path: str) -> RemoteObject:
        target = self._target(remote_path)
        result = self._run(["lsjson", target, "--stat", "--files-only", "--hash"])
        try:
            payload: Any = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError("rclone remote metadata JSON invalid hai; verification refused") from exc
        if not isinstance(payload, dict) or payload.get("IsDir") is True:
            raise RuntimeError("Google Drive remote file metadata nahi mila; verification refused")
        try:
            size = int(payload["Size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Google Drive remote size missing hai; verification refused") from exc

        hashes = payload.get("Hashes") if isinstance(payload.get("Hashes"), dict) else {}
        sha256 = None
        for key, value in hashes.items():
            normalized = str(key).replace("-", "").lower()
            if normalized == "sha256" and value:
                candidate = str(value).lower()
                if re.fullmatch(r"[0-9a-f]{64}", candidate):
                    sha256 = candidate
                    break

        # Never downgrade to size-only verification. This extra read is slower
        # for providers without native SHA-256, but it is the safe boundary that
        # makes later local cleanup defensible.
        if not sha256:
            sha256 = self._download_sha256(target)

        return RemoteObject(
            path=remote_path,
            size=size,
            sha256=sha256,
            etag=str(payload.get("ID") or "") or None,
        )

    def status(self) -> dict[str, object]:
        """Return non-secret configuration readiness; never expose OAuth/crypt secrets."""
        return {
            "provider": self.name,
            "configured": True,
            "remote_name": self.remote_name,
            "archive_root": self.archive_root,
            "rclone_available": bool(self.executable),
            "timeout_seconds": self.timeout_seconds,
            "encryption_required": self.require_crypt,
            "encryption_verified": self.remote_type == "crypt" if self.require_crypt else None,
            "encryption_backend": "rclone-crypt" if self.remote_type == "crypt" else "",
            "content_verification": "sha256-required",
        }


__all__ = ["RcloneGoogleDriveProvider", "detect_rclone_remote_type"]
