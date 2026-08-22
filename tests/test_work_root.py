"""Offline tests for configured working storage."""
from __future__ import annotations

import asyncio
import os
import tempfile

from utils.upload_safety import configured_work_root, ensure_work_root, save_upload_stream


class FakeUpload:
    def __init__(self, data: bytes, filename: str = "sample.pdf"):
        self.data = data
        self.offset = 0
        self.filename = filename

    async def read(self, size: int = -1) -> bytes:
        if self.offset >= len(self.data):
            return b""
        if size < 0:
            size = len(self.data) - self.offset
        end = min(len(self.data), self.offset + size)
        chunk = self.data[self.offset:end]
        self.offset = end
        return chunk


def test_configured_work_root_is_optional():
    assert configured_work_root({}) is None


def test_new_data_root_takes_precedence_over_legacy_alias():
    with tempfile.TemporaryDirectory() as parent:
        newer = os.path.join(parent, "new")
        older = os.path.join(parent, "old")
        actual = configured_work_root({
            "INFINITY_DATA_ROOT": newer,
            "INFINITY_WORK_ROOT": older,
        })
        assert actual == os.path.abspath(newer)


def test_configured_work_root_creates_temp_subdir():
    with tempfile.TemporaryDirectory() as parent:
        root = os.path.join(parent, "InfinityResearchAI")
        temp_root = ensure_work_root({"INFINITY_DATA_ROOT": root})
        assert temp_root == os.path.abspath(os.path.join(root, "temp"))
        assert os.path.isdir(temp_root)


def test_streamed_upload_stays_inside_configured_root():
    with tempfile.TemporaryDirectory() as parent:
        root = os.path.join(parent, "workspace")
        path = asyncio.run(
            save_upload_stream(FakeUpload(b"hello"), max_bytes=100, work_root=root)
        )
        try:
            common = os.path.commonpath([os.path.abspath(path), os.path.abspath(root)])
            assert common == os.path.abspath(root)
        finally:
            import shutil
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)
