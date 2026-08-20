"""Offline tests for centralized runtime storage routing."""
from __future__ import annotations

import os
import tempfile

from utils.storage_paths import configured_root, ensure_layout


def test_data_root_precedes_legacy_work_root():
    with tempfile.TemporaryDirectory() as parent:
        primary = os.path.join(parent, "primary")
        legacy = os.path.join(parent, "legacy")
        root, explicit = configured_root({
            "INFINITY_DATA_ROOT": primary,
            "INFINITY_WORK_ROOT": legacy,
        })
        assert explicit is True
        assert root == os.path.abspath(primary)


def test_layout_creates_all_runtime_folders_under_explicit_root():
    with tempfile.TemporaryDirectory() as parent:
        root = os.path.join(parent, "InfinityResearchAI")
        layout = ensure_layout({"INFINITY_DATA_ROOT": root})
        assert layout["root"] == os.path.abspath(root)
        for name in (
            "archive", "cache", "knowledge", "logs", "models",
            "research_memory", "temp", "uploads", "vector_db",
        ):
            assert os.path.isdir(layout[name])
            assert os.path.commonpath([layout[name], os.path.abspath(root)]) == os.path.abspath(root)


def test_no_explicit_root_uses_repository_runtime_data_fallback():
    root, explicit = configured_root({})
    assert explicit is False
    assert os.path.basename(root) == "runtime_data"
