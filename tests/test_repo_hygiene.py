"""Static repo-hygiene regression for generated/runtime data."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_TRACKED_RUNTIME = (
    "knowledge_graph.json",
    "knowledge_store.json",
    "error_log.txt",
    "research_memory/default.json",
    "research_memory/offline_test.json",
)


def test_generated_runtime_files_are_not_present_in_source_tree():
    present = [path for path in FORBIDDEN_TRACKED_RUNTIME if (ROOT / path).exists()]
    assert not present, f"generated runtime files must not ship in source tree: {present}"


def test_gitignore_keeps_runtime_files_out_after_first_run():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8-sig")
    required = (
        "runtime_data/",
        "research_memory/*.json",
        "knowledge_graph.json",
        "knowledge_store.json",
        "error_log.txt",
        "*.log",
        "models/",
        "cache/",
        "temp/",
        "uploads/",
        "archive/",
    )
    missing = [entry for entry in required if entry not in text]
    assert not missing, missing
