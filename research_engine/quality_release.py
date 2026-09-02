"""Enforce the final quality gate at a user-facing result boundary.

The evaluator in :mod:`research_engine.final_quality_gate` is deliberately
read-only.  This adapter applies its decision to a copy of a completed result:

* the structured quality report is attached;
* a false VERIFIED/STRONG label is downgraded;
* an answer labelled COMPLETE while mandatory deliverables are missing becomes
  PARTIAL;
* the persisted/in-memory original result is never mutated;
* repeated enforcement is idempotent.

This is not a prose-repair engine.  Missing science remains missing and the
issues remain visible; the adapter only prevents a weak result from being
released with a stronger status than its recorded work permits.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, Mapping, Optional

from .final_quality_gate import CONTRACT_VERSION, evaluate_final_quality


_SOURCE_ID_RE = re.compile(r"\[S(\d+)\]", re.IGNORECASE)
_STRONG_LEVEL_RE = re.compile(r"\b(?:VERIFIED|STRONG(?:\s+EVIDENCE)?)\b", re.IGNORECASE)
_BADGE_LINE_RE = re.compile(
    r"(?im)^(?P<label>\s*(?:Evidence\s+ka\s+level|Saboot\s+ka\s+star)\s*:)[^\n]*"
    r"(?:VERIFIED|STRONG)[^\n]*$"
)
_HYPOTHESIS_BOUNDARY_RE = re.compile(
    r"(?im)^#{1,6}\s+(?:APP\s+ORIGINAL\s+RESEARCH\s+LAB|"
    r"app\s+ki\s+khud\s+generate|humari\s+hypotheses|hypotheses)\b"
)
_NO_SOURCE_RE = re.compile(r"\[NO[- ]SOURCE\]", re.IGNORECASE)


def _mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        return dict(converted) if isinstance(converted, Mapping) else {}
    return {}


def _unique_cited_source_count(result: Mapping[str, Any], answer: str) -> int:
    ids = {match.group(1) for match in _SOURCE_ID_RE.finditer(answer or "")}
    for citation in result.get("citations") or []:
        if not isinstance(citation, Mapping):
            continue
        raw = str(citation.get("source_id") or citation.get("id") or "")
        match = re.fullmatch(r"S?(\d+)", raw, re.IGNORECASE)
        if match:
            ids.add(match.group(1))
    return len(ids)


def _directly_relevant_count(sources: Any, threshold: float = 0.65) -> Optional[int]:
    if not isinstance(sources, list) or not sources:
        return 0
    scored = []
    for source in sources:
        if not isinstance(source, Mapping) or source.get("relevance_score") is None:
            continue
        try:
            scored.append(float(source.get("relevance_score")))
        except (TypeError, ValueError):
            continue
    if not scored:
        return None
    return sum(1 for score in scored if score >= threshold)


def _main_answer_no_source_count(answer: str) -> int:
    """Count NO-SOURCE before the app-hypothesis area.

    App-generated hypotheses may honestly identify unsupported assumptions.  A
    NO-SOURCE marker there must not be confused with an unsupported critical
    claim in the sourced answer.  The producer can always override this
    conservative text fallback with `critical_no_source_claims`.
    """
    match = _HYPOTHESIS_BOUNDARY_RE.search(answer or "")
    main = answer[:match.start()] if match else answer
    return len(_NO_SOURCE_RE.findall(main))


def _prepare_quality_context(
    result: Mapping[str, Any],
    *,
    recovery_used: bool,
    progress_snapshot: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    context = copy.deepcopy(_mapping(result.get("quality_context")))
    coverage = _mapping(result.get("coverage"))
    sources = result.get("sources") if isinstance(result.get("sources"), list) else []
    answer = str(result.get("answer") or "")

    # Exact mechanical counters can be safely supplied at the boundary.  More
    # semantic counters (critical-support sources, entailment, counter-search)
    # must come from their producer; absence deliberately remains absence so
    # the gate fails closed instead of inventing a pass.
    context.setdefault("sources_retrieved", len(sources))
    context.setdefault("sources_cited", _unique_cited_source_count(result, answer))
    direct = _directly_relevant_count(sources)
    if direct is not None:
        context.setdefault("directly_relevant_sources", direct)
    elif coverage.get("directly_relevant_sources") is not None:
        context.setdefault("directly_relevant_sources", coverage.get("directly_relevant_sources"))

    context.setdefault("critical_no_source_claims", _main_answer_no_source_count(answer))
    context["recovery_used"] = bool(context.get("recovery_used") or recovery_used)
    if context["recovery_used"]:
        available = bool(
            isinstance(progress_snapshot, Mapping)
            and progress_snapshot.get("available") is True
        )
        context["progress_snapshot_preserved"] = bool(
            context.get("progress_snapshot_preserved") or available
        )
    return context


def _quality_reason(report: Mapping[str, Any]) -> str:
    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    messages = []
    for issue in issues:
        if not isinstance(issue, Mapping):
            continue
        message = " ".join(str(issue.get("message") or "").split())
        if message and message not in messages:
            messages.append(message)
        if len(messages) == 2:
            break
    if not messages:
        return "Final quality checks release ke liye poore nahi hue."
    return "Final quality gate: " + " ".join(messages)


def _downgrade_badges(answer: str) -> tuple[str, bool]:
    replacement = (
        r"\g<label> ⚠️ UNCONFIRMED — final quality gate ne stronger release "
        r"block ki; structured issues dekhein."
    )
    updated, count = _BADGE_LINE_RE.subn(replacement, answer or "")
    return updated, count > 0


def enforce_quality_release(
    result: Any,
    *,
    recovery_used: bool = False,
    progress_snapshot: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return an independently gated copy of a completed research result."""
    original = _mapping(result)
    response = copy.deepcopy(original)

    prior = _mapping(response.get("quality_gate"))
    if response.get("quality_enforced") is True and prior.get("contract_version") == CONTRACT_VERSION:
        return response

    response["quality_context"] = _prepare_quality_context(
        response,
        recovery_used=recovery_used,
        progress_snapshot=progress_snapshot,
    )
    report = evaluate_final_quality(response, response.get("quality_contract"))
    repairs = []

    if not report.get("verified_allowed"):
        evidence_level = str(response.get("evidence_level") or "")
        if _STRONG_LEVEL_RE.search(evidence_level):
            response["evidence_level"] = (
                "⚠️ UNCONFIRMED — final quality gate blocked stronger release"
            )
            repairs.append("evidence_level_downgraded")

        answer = str(response.get("answer") or "")
        updated, changed = _downgrade_badges(answer)
        if changed:
            response["answer"] = updated
            repairs.append("answer_verified_badge_downgraded")

    current_status = str(response.get("status") or "").strip().upper()
    if not report.get("answer_complete") and current_status == "COMPLETE":
        response["status"] = "PARTIAL"
        response["status_reason"] = _quality_reason(report)
        repairs.append("answer_status_downgraded_to_partial")

    response["quality_gate"] = report
    response["quality_repairs"] = repairs
    response["quality_enforced"] = True
    return response


__all__ = ["enforce_quality_release"]
