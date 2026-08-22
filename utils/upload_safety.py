"""Streaming upload helpers.

Large uploads must never be read into RAM in one shot. This module keeps the
size cap honest while writing incrementally to a temporary directory. It is
provider-independent and uses no paid service.

Laptop storage is centralized through ``INFINITY_DATA_ROOT`` (with the older
``INFINITY_WORK_ROOT`` kept as an alias). When an explicit root is configured,
temporary uploads stay under its ``temp`` directory and never silently fall
back to C:.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Mapping, Protocol

from fastapi import HTTPException

from utils.storage_paths import configured_root, ensure_layout


DEFAULT_CHUNK_BYTES = 1024 * 1024  # 1 MiB


class AsyncUpload(Protocol):
    filename: str | None

    async def read(self, size: int = -1) -> bytes: ...


def configured_work_root(env: Mapping[str, str] | None = None) -> str | None:
    """Return explicit laptop storage root for backwards compatibility."""
    root, explicit = configured_root(env)
    return root if explicit else None


def ensure_work_root(env: Mapping[str, str] | None = None) -> str | None:
    """Validate explicit storage and return its temp directory.

    When no explicit laptop root is configured, ``None`` is returned so callers
    can retain normal OS-temp behaviour in isolated development contexts.
    """
    root, explicit = configured_root(env)
    if not explicit:
        return None
    layout = ensure_layout(env)
    return layout["temp"]


def _reserve_configured_capacity(max_bytes: int, *, custom_work_root: bool) -> None:
    """Fail before reading when the configured local workspace is already full.

    This is intentionally skipped for an explicit ``work_root`` argument used by
    isolated tests/callers because storage_quota tracks the configured Infinity
    root, not arbitrary temporary directories.
    """
    if custom_work_root:
        return
    _, explicit = configured_root()
    if not explicit:
        return
    try:
        from utils.storage_quota import StorageQuotaError, assert_capacity
        assert_capacity(max_bytes)
    except StorageQuotaError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc


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
    - rejects new configured-root writes with HTTP 507 when the bounded local
      workspace cannot safely reserve the endpoint's maximum upload size;
    - removes the temporary directory on every failure path;
    - when a storage root is configured, never falls back to another drive.

    The caller owns the returned directory and should remove it after use with
    ``cleanup_upload_path``.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be positive")

    _reserve_configured_capacity(max_bytes, custom_work_root=work_root is not None)

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
