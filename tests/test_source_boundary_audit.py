"""Run the static source-boundary audit through the authoritative pytest suite."""
from __future__ import annotations

from scripts.audit_source_boundary import run


def test_source_boundary_architecture_is_fully_wired():
    failed = [row for row in run() if not row.passed]
    assert not failed, "; ".join(f"{row.name}: {row.detail}" for row in failed)
