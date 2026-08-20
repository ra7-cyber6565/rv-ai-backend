"""Streaming upload helpers.

Large uploads must never be read into RAM in one shot. This module keeps the
size cap honest while writing incrementally to a temporary directory. It is
provider-independent and uses no paid service.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from typing import Protocol

from fastapi import HTTPException


DEFAULT_CHUNK_BYTES = 1024 * 1024  # 1 MiB


class AsyncUpload(Protocol):
    filename: str | None

    async def read(self, size: int = -1) -> bytes: ...


async def save_upload_stream(
    upload: AsyncUpload,
    *,
    max_bytes: int,
    prefix: str = "infinity_upload_",
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
) -> str:
    """Stream an upload to disk and return the temporary file path.

    Guarantees:
    - never buffers the whole upload in application memory;
    - rejects empty files with HTTP 400;
    - rejects files above ``max_bytes`` with HTTP 413;
    - removes the temporary directory on every failure path.

    The caller owns the returned directory and should remove it after use with
    ``cleanup_upload_path``.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be positive")

    extension = os.path.splitext(upload.filename or "")[1].lower() or ".bin"
    directory = tempfile.mkdtemp(prefix=prefix)
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
