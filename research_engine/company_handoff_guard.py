"""Compatibility facade for the canonical specialist -> chief handoff.

Historically this module monkey-patched ``research_company.chief_handoff`` with a
second, independently maintained compaction implementation. That created two
sources of truth: improvements made in ``research_company`` could be silently
overridden at package import time.

The canonical implementation now lives only in ``research_company``. This
module remains installed for backwards compatibility with existing imports and
runtime wiring, but delegates all handoff semantics to that canonical function.
It adds only the legacy machine-readable ``handoff_worker_roles`` metadata used
by acceptance tooling; it does not clip, compact, or reinterpret worker reports.
"""
from __future__ import annotations

from typing import Dict

from . import research_company as _company


# Preserve the real implementation even if this compatibility module is reloaded
# after an earlier install in the same interpreter.
_current = _company.chief_handoff
_CANONICAL_CHIEF_HANDOFF = getattr(_current, "__canonical_chief_handoff__", _current)
_INSTALLED = False


def chief_handoff(company: Dict) -> str:
    """Delegate to the single canonical handoff implementation.

    ``handoff_worker_roles`` is compatibility metadata only. Completion,
    truncation, lossless duplicate compaction, omission accounting, binary
    stripping, and fail-closed semantics all come from ``research_company``.
    """
    prompt = _CANONICAL_CHIEF_HANDOFF(company)
    workers = company.get("workers") if isinstance(company, dict) else []
    company["handoff_worker_roles"] = [
        str(row.get("role"))
        for row in (workers or [])
        if isinstance(row, dict) and str(row.get("role") or "").strip()
    ]
    return prompt


# Make reloads idempotent and let future compatibility layers recover the
# canonical implementation instead of wrapping wrappers indefinitely.
chief_handoff.__canonical_chief_handoff__ = _CANONICAL_CHIEF_HANDOFF


def install() -> None:
    """Keep the old package-import surface without maintaining duplicate logic."""
    global _INSTALLED
    if _INSTALLED and _company.chief_handoff is chief_handoff:
        return
    _INSTALLED = True
    _company.chief_handoff = chief_handoff


install()
