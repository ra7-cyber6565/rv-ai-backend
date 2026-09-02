"""Fail-closed source-safety guard for deterministic no-model reasoning.

The model prompt path already treats retrieved/uploaded text as untrusted data,
but the quota fallback in ``local_reasoning.py`` does not use a prompt at all: it
selects source sentences directly and can therefore accidentally echo an
instruction-like sentence or rely on a retracted source when every hosted model
is unavailable.  That is exactly the path that must stay safest during quota
outages.

This additive guard patches only two pure deterministic helpers:

* ``_best_sentence`` skips instruction-like source sentences and hidden control
  characters while preserving ordinary evidence from the same source;
* ``_ordered`` excludes sources already rejected by relevance and sources with
  an explicit retraction/withdrawal signal.

No network/model call is made and no evidence state is upgraded.
"""
from __future__ import annotations

from typing import Sequence

from . import local_reasoning as _local
from .source_prompt_guard import _clean_controls, looks_instruction_like

_ORIGINAL_BEST = _local._best_sentence
_ORIGINAL_ORDERED = _local._ordered
_INSTALLED = False


def _safe_best_sentence(source, terms: Sequence[str], cues: Sequence[str] = ()) -> str:
    """Choose only non-instruction source sentences; keep normal text usable."""
    best = ""
    best_score = -1
    cleaned = _clean_controls(getattr(source, "snippet", "") or "")
    for sent in _local._sentences(cleaned):
        if looks_instruction_like(sent):
            continue
        score = _local._score_sentence(sent, terms)
        if cues:
            low = sent.lower()
            if not any(cue in low for cue in cues):
                continue
            score += 2
        if score > best_score:
            best = sent
            best_score = score
    return _local._clean(best)


def _safe_ordered(pack):
    """Never let rejected/retracted sources become quota-fallback evidence."""
    rows = []
    for index, source in enumerate(getattr(pack, "sources", []) or []):
        if str(getattr(source, "rejected_reason", "") or "").strip():
            continue
        if getattr(source, "retracted", None) is True:
            continue
        score = -(
            float(getattr(source, "combined_score", 0.0) or 0.0)
            or float(getattr(source, "relevance_score", 0.0) or 0.0)
        )
        rows.append((score, index, source))
    rows.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in rows]


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _local._best_sentence = _safe_best_sentence
    _local._ordered = _safe_ordered
    _INSTALLED = True


def installed() -> bool:
    return bool(_INSTALLED and _local._best_sentence is _safe_best_sentence)


__all__ = ["install", "installed"]
