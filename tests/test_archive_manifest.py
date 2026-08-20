"""Offline regression tests for safe archive deletion rules."""
from __future__ import annotations

import os
import tempfile

import pytest

from utils.archive_manifest import ArchiveManifest, sha256_file


def test_file_is_not_deletable_before_remote_verification():
    with tempfile.TemporaryDirectory() as root:
        local = os.path.join(root, "paper.pdf")
        with open(local, "wb") as handle:
            handle.write(b"research-data")
        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        item = manifest.register(local, remote_path="/papers/paper.pdf", provider="terabox")
        assert manifest.safe_to_delete_local(item["sha256"]) is False
        manifest.mark_upload_attempt(item["sha256"])
        assert manifest.safe_to_delete_local(item["sha256"]) is False


def test_matching_remote_size_allows_verified_state():
    with tempfile.TemporaryDirectory() as root:
        local = os.path.join(root, "book.pdf")
        payload = b"abc" * 100
        with open(local, "wb") as handle:
            handle.write(payload)
        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        item = manifest.register(local, remote_path="/books/book.pdf", provider="terabox")
        manifest.mark_upload_attempt(item["sha256"])
        manifest.mark_verified(item["sha256"], remote_size=len(payload))
        assert manifest.safe_to_delete_local(item["sha256"]) is True


def test_wrong_remote_size_never_verifies():
    with tempfile.TemporaryDirectory() as root:
        local = os.path.join(root, "data.bin")
        with open(local, "wb") as handle:
            handle.write(b"12345")
        manifest = ArchiveManifest(os.path.join(root, "manifest.json"))
        item = manifest.register(local, remote_path="/data/data.bin", provider="terabox")
        manifest.mark_upload_attempt(item["sha256"])
        with pytest.raises(RuntimeError):
            manifest.mark_verified(item["sha256"], remote_size=4)
        assert manifest.safe_to_delete_local(item["sha256"]) is False


def test_checksum_is_stable():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "x.txt")
        with open(path, "wb") as handle:
            handle.write(b"same")
        assert sha256_file(path) == sha256_file(path)
