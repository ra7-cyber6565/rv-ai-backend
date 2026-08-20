"""Streaming upload helpers.

Large uploads must never be read into RAM in one shot. This module keeps the
size cap honest while writing incrementally to a temporary directory. It is
provider-independent and uses no paid service.

When ``INFINITY_WORK_ROOT`` is configured (recommended on the laptop as a D:
folder), temporary upload directories are created there rather than on the
system drive. If that configured root is unavailable, the code fails closed;
it never silently falls back to C:.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Mapping, Protocol

from fastapi import HTTPException


DEFAULT_CHUNK_BYTES = 1024 * 1024  # 1 MiB


class AsyncUpload(Protocol):
    filename: str | None

    async def read(self, size: int = -1) -> bytes: ...


def configured_work_root(env: Mapping[str, str] | None = None) -> str | None:
    """Return the explicitly configured working root, or ``None``.

    No hard-coded D: path is used because the backend also runs on Linux/cloud.
    The laptop can set for example ``INFINITY_WORK_ROOT=D:\\InfinityResearchAI``.
    """
    source = env if env is not None else os.environ
    raw = str(source.get("INFINITY_WORK_ROOT", "")).strip()
    return os.path.abspath(os.path.expanduser(raw)) if raw else None


def ensure_work_root(env: Mapping[str, str] | None = None) -> str | None:
    """Create/validate the configured working root and fail closed if unusable."""
    root = configured_work_root(env)
    if not root:
        return None
    try:
        Path(root).mkdir(parents=True, exist_ok=True)
        probe = Path(root) / ".infinity_write_probe"
        probe.write_bytes(b"ok")
        probe.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 - turn OS detail into a clear error
        raise RuntimeError(
            f"Configured INFINITY_WORK_ROOT is unavailable/unwritable: {root}"
        ) from exc
    return root


async def save_upload_stream(
    upload: AsyncUpload,
    *,
    max_bytes: int,
    prefix: str = "infinity_upload_",
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    work_root: str | None = None,
) -> str:
    """Stream an upload to disk and return the temporary file path.

    Guarantees:
    - never buffers the whole upload in application memory;
    - rejects empty files with HTTP 400;
    - rejects files above ``max_bytes`` with HTTP 413;
    - removes the temporary directory on every failure path;
    - when a work root is configured, never falls back to another drive.

    The caller owns the returned directory and should remove it after use with
    ``cleanup_upload_path``.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be positive")

    root = work_root if work_root is not None else ensure_work_root()
    if root:
        Path(root).mkdir(parents=True, exist_ok=True)

    extension = os.path.splitext(upload.filename or "")[1].lower() or ".bin"
    directory = tempfile.mkdtemp(prefix=prefix, dir=root)
    path = os.path.join(directory, f"upload{extension}")
    total = 0

    try:
        with open(path, "wb") as handle:
            while True:
                chunk = await upload.read(chunk_bytes)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File {max_bytes // (1024 * 1024)}MB se badi hai.",
                    )
                handle.write(chunk)

        if total == 0:
            raise HTTPException(status_code=400, detail="File khaali hai.")
        return path
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def cleanup_upload_path(path: str | None) -> None:
    """Idempotently remove the temporary directory for an uploaded file."""
    if not path:
        return
    directory = os.path.dirname(os.path.abspath(path))
    shutil.rmtree(directory, ignore_errors=True)
