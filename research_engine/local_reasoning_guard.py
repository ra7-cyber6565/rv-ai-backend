"""Fail-closed source-safety guard for deterministic no-model reasoning.

The model prompt path already treats retrieved/uploaded text as untrusted data,
but the quota fallback in ``local_reasoning.py`` does not use a prompt at all: it
selects source sentences directly and can therefore accidentally echo an
instruction-like sentence or rely on a retracted source when every hosted model
is unavailable. That is exactly the path that must stay safest during quota
outages.

This additive guard patches pure deterministic helpers so that:

* instruction-like source sentences and hidden controls are never echoed by the
  no-model answer path;
* ordinary evidence from the same mixed source remains usable;
* rejected or explicitly retracted/withdrawn sources cannot become fallback
  findings, conclusions, preselected evidence or QUICK backup snippets;
* an all-retracted/all-rejected pack degrades to UNKNOWN/no-usable-source wording
  rather than crashing after filtering.

No network/model call is made and no evidence state is upgraded.
"""
from __future__ import annotations

from typing import Sequence

from . import local_reasoning as _local
from .source_prompt_guard import _clean_controls, looks_instruction_like

_ORIGINAL_PRESELECTED = _local._preselected_findings
_ORIGINAL_CONCLUSION = _local._conclusion
_ORIGINAL_QUICK = _local.quick_answer
_INSTALLED = False


def _source_allowed(source) -> bool:
    if source is None:
        return False
    if str(getattr(source, "rejected_reason", "") or "").strip():
        return False
    if getattr(source, "retracted", None) is True:
        return False
    return True


def _safe_sentences(source) -> list[str]:
    cleaned = _clean_controls(getattr(source, "snippet", "") or "")
    return [
        sent for sent in _local._sentences(cleaned)
        if sent and not looks_instruction_like(sent)
    ]


def _safe_best_sentence(source, terms: Sequence[str], cues: Sequence[str] = ()) -> str:
    """Choose only non-instruction source sentences; keep normal text usable."""
    if not _source_allowed(source):
        return ""
    best = ""
    best_score = -1
    for sent in _safe_sentences(source):
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
        if not _source_allowed(source):
            continue
        score = -(
            float(getattr(source, "combined_score", 0.0) or 0.0)
            or float(getattr(source, "relevance_score", 0.0) or 0.0)
        )
        rows.append((score, index, source))
    rows.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in rows]


def _safe_preselected_findings(manifest, pack, terms, limit: int = 2):
    rows = _ORIGINAL_PRESELECTED(manifest, pack, terms, limit=limit)
    return [
        (source, text) for source, text in rows
        if _source_allowed(source) and text and not looks_instruction_like(text)
    ][: max(1, int(limit))]


def _safe_conclusion(question, pack, lang, evidence_manifest=None):
    if not _safe_ordered(pack):
        return _local._t(lang, "no_sources")
    return _ORIGINAL_CONCLUSION(
        question, pack, lang, evidence_manifest=evidence_manifest
    )


def _safe_search_wrapper(searcher):
    finder = searcher or _local._free_search

    def wrapped(query: str, limit: int = 3):
        try:
            records = list(finder(query, limit=limit) or [])
        except TypeError:
            records = list(finder(query) or [])
        safe = []
        for record in records:
            if not _source_allowed(record):
                continue
            if not _safe_sentences(record):
                continue
            safe.append(record)
            if len(safe) >= max(1, int(limit)):
                break
        return safe

    return wrapped


def _safe_quick_answer(message: str, searcher=None, language: str = "", cause: str = "quota"):
    """QUICK source fallback cannot fall back again to a hostile raw snippet."""
    return _ORIGINAL_QUICK(
        message,
        searcher=_safe_search_wrapper(searcher),
        language=language,
        cause=cause,
    )


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _local._best_sentence = _safe_best_sentence
    _local._ordered = _safe_ordered
    _local._preselected_findings = _safe_preselected_findings
    _local._conclusion = _safe_conclusion
    _local.quick_answer = _safe_quick_answer
    _INSTALLED = True


def installed() -> bool:
    return bool(
        _INSTALLED
        and _local._best_sentence is _safe_best_sentence
        and _local._ordered is _safe_ordered
        and _local.quick_answer is _safe_quick_answer
    )


__all__ = ["install", "installed"]
