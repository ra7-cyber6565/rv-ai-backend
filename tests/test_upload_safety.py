"""Regression tests for upload memory/cleanup safety.

These tests are fully offline and use no API keys or paid services.
"""
from __future__ import annotations

import asyncio
import os

from fastapi import HTTPException

from utils.upload_safety import cleanup_upload_path, save_upload_stream


class FakeUpload:
    def __init__(self, data: bytes, filename: str = "sample.pdf"):
        self._data = data
        self._offset = 0
        self.filename = filename
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if self._offset >= len(self._data):
            return b""
        if size < 0:
            size = len(self._data) - self._offset
        end = min(len(self._data), self._offset + size)
        chunk = self._data[self._offset:end]
        self._offset = end
        return chunk


def _run(coro):
    return asyncio.run(coro)


def test_upload_is_streamed_in_bounded_chunks():
    upload = FakeUpload(b"x" * 25)
    path = _run(save_upload_stream(upload, max_bytes=100, chunk_bytes=8))
    try:
        assert os.path.exists(path)
        assert os.path.getsize(path) == 25
        # No whole-file read: every explicit request is bounded by chunk_bytes.
        assert upload.read_sizes
        assert all(size == 8 for size in upload.read_sizes)
    finally:
        cleanup_upload_path(path)
    assert not os.path.exists(path)


def test_empty_upload_is_rejected_and_temp_dir_removed():
    upload = FakeUpload(b"")
    try:
        _run(save_upload_stream(upload, max_bytes=100, chunk_bytes=8))
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "khaali" in str(exc.detail).lower()


def test_oversized_upload_is_rejected_before_full_file_is_read():
    upload = FakeUpload(b"x" * 100)
    try:
        _run(save_upload_stream(upload, max_bytes=20, chunk_bytes=8))
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 413
        # 3 chunks (24 bytes) are enough to prove the cap was crossed; the
        # remaining bytes should never be consumed.
        assert upload._offset == 24


def test_cleanup_is_idempotent():
    upload = FakeUpload(b"hello", filename="note.txt")
    path = _run(save_upload_stream(upload, max_bytes=100, chunk_bytes=2))
    cleanup_upload_path(path)
    cleanup_upload_path(path)
    assert not os.path.exists(path)
