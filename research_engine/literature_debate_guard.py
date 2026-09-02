"""Fail-closed reliability guard for #103 Autonomous Literature Debate.

The base debate engine reconstructs arguments from retrieved text and already
handles mirrors, retractions, prompt injection and missing author metadata. One
additional distinction is needed at the production boundary: an argument being
*present* in available source text is not the same as that source being strong
enough to count toward ``DEBATE_MAP_READY``.

This facade preserves every grounded argument but only counts an argument as
``reliable_current_evidence`` when the same source also clears conservative
access/relevance/source-quality gates. A search snippet, a barely-related
source, retracted historical material, or a source whose quality is not
established can therefore remain visible as context without silently promoting
the debate to "ready".

No model/network call is added and no source text is rewritten.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from .literature_debate import AutonomousLiteratureDebate as _BaseDebate
from .models import EvidencePack, SourceRecord


_MIN_RELEVANCE = 0.25
_MIN_QUALITY = 0.45
_RELIABLE_DEPTHS = {"abstract", "full_text"}
_ROLE_ORDER = (
    "researcher_a_reasoning",
    "researcher_b_critique",
    "researcher_c_replication_failure",
)
_ROLE_LABELS = {
    "researcher_a_reasoning": "Researcher A reasoning",
    "researcher_b_critique": "Researcher B critique",
    "researcher_c_replication_failure": "Researcher C replication failure",
}


def _read_level(source: SourceRecord) -> str:
    try:
        return str(source.reading_level() or "metadata")
    except Exception:
        return "metadata"


def source_reliability(source: SourceRecord | None) -> Tuple[bool, str]:
    """Return whether a source may count toward debate *readiness* and why.

    This is intentionally stricter than "may appear in the debate map". The
    base engine may retain a retracted source as historical context and may show
    shallow text as an available argument. Neither should be allowed to make a
    three-role debate look independently well-supported.
    """
    if source is None:
        return False, "source_missing_from_evidence_pack"
    if source.retracted is True:
        return False, "retracted_historical_context_only"
    if str(getattr(source, "rejected_reason", "") or "").strip():
        return False, "source_rejected"
    verdict = getattr(source, "domain_verdict", None) or {}
    if isinstance(verdict, Mapping) and verdict.get("rejected"):
        return False, "source_rejected"

    level = _read_level(source)
    if level not in _RELIABLE_DEPTHS:
        return False, f"access_depth_{level}_too_shallow_for_readiness"

    relevance = float(getattr(source, "relevance_score", 0.0) or 0.0)
    if relevance < _MIN_RELEVANCE:
        return False, "relevance_below_readiness_gate"

    quality = float(getattr(source, "quality_score", 0.0) or 0.0)
    peer_reviewed = getattr(source, "peer_reviewed", None) is True
    primary = getattr(source, "is_primary", None) is True
    if quality < _MIN_QUALITY and not peer_reviewed and not primary:
        return False, "source_quality_not_established"

    return True, "accepted_current_debate_evidence"


class GuardedAutonomousLiteratureDebate(_BaseDebate):
    """Base grounded debate + independent depth/quality readiness gate."""

    reliability_schema_version = "1.3"

    def reconstruct(self, question: str, pack: EvidencePack, contradictions=()) -> Dict[str, Any]:
        report = super().reconstruct(question, pack, contradictions=contradictions)
        if not isinstance(pack, EvidencePack) or not isinstance(report, dict):
            return report

        role_slots = report.get("role_slots")
        if not isinstance(role_slots, Mapping):
            return report

        # Lexical grounded presence comes from the argument rows themselves. The
        # base engine historically derived ``missing_roles_in_available_text``
        # from *reliable-current* presence, which means a retracted argument was
        # incorrectly reported as absent from the retrieved text even though the
        # row was visibly present. Keep these state machines separate here.
        grounded_presence = {
            role: bool(role_slots.get(role) or [])
            for role in _ROLE_ORDER
        }

        by_id = {
            str(getattr(source, "source_id", "") or ""): source
            for source in (pack.sources or [])
            if str(getattr(source, "source_id", "") or "").strip()
        }
        reliable_origins: set[str] = set()
        full_text_origins: set[str] = set()
        role_presence: Dict[str, bool] = {}
        reliable_count = 0
        downgraded_count = 0

        for role in _ROLE_ORDER:
            rows = role_slots.get(role) or []
            role_has_reliable = False
            for row in rows:
                if not isinstance(row, dict):
                    continue
                source = by_id.get(str(row.get("source_id") or ""))
                allowed, reason = source_reliability(source)
                previous = bool(row.get("reliable_current_evidence"))
                row["reliable_current_evidence"] = bool(allowed)
                row["reliability_reason"] = reason
                if source is not None:
                    row["relevance_score"] = round(float(getattr(source, "relevance_score", 0.0) or 0.0), 4)
                    row["quality_score"] = round(float(getattr(source, "quality_score", 0.0) or 0.0), 4)
                    row["peer_reviewed"] = getattr(source, "peer_reviewed", None)
                if previous and not allowed:
                    downgraded_count += 1
                if not allowed:
                    continue
                reliable_count += 1
                role_has_reliable = True
                origin = str(row.get("independence_key") or "")
                if origin:
                    reliable_origins.add(origin)
                    if source is not None and _read_level(source) == "full_text":
                        full_text_origins.add(origin)
            role_presence[role] = role_has_reliable

        report["role_presence_grounded_available_text"] = grounded_presence
        report["role_presence_reliable"] = role_presence
        report["missing_roles_in_available_text"] = [
            _ROLE_LABELS[role]
            for role in _ROLE_ORDER
            if not grounded_presence.get(role)
        ]
        report["missing_roles_for_ready_debate"] = [
            _ROLE_LABELS[role]
            for role in _ROLE_ORDER
            if not role_presence.get(role)
        ]

        all_arguments = sum(len(role_slots.get(role) or []) for role in _ROLE_ORDER)
        if not all_arguments:
            report["status"] = "INSUFFICIENT_GROUNDED_ARGUMENTS"
        elif all(role_presence.values()) and len(reliable_origins) >= 3:
            report["status"] = "DEBATE_MAP_READY"
        else:
            report["status"] = "PARTIAL_DEBATE"

        coverage = dict(report.get("coverage") or {})
        coverage["reliable_argument_origins"] = len(reliable_origins)
        coverage["full_text_argument_origins"] = len(full_text_origins)
        coverage["arguments_reliable_current"] = reliable_count
        coverage["arguments_downgraded_by_readiness_gate"] = downgraded_count
        report["coverage"] = coverage

        honesty = dict(report.get("honesty") or {})
        honesty["shallow_or_low_quality_arguments_count_as_reliable"] = False
        honesty["reliability_requires_depth_relevance_and_quality"] = True
        honesty["grounded_presence_separate_from_readiness"] = True
        report["honesty"] = honesty

        proof = dict(report.get("maturity_proof") or {})
        proof["quality_and_depth_reliability_gate"] = True
        report["maturity_proof"] = proof
        report["reliability_gate"] = {
            "schema_version": self.reliability_schema_version,
            "minimum_relevance": _MIN_RELEVANCE,
            "minimum_quality_or_strong_metadata": _MIN_QUALITY,
            "reliable_read_levels": sorted(_RELIABLE_DEPTHS),
            "note": (
                "Argument map available text ko preserve karta hai; DEBATE_MAP_READY sirf "
                "un independent origins se banta hai jinka access depth, relevance aur "
                "source-quality gate pass hua."
            ),
        }
        return report


AutonomousLiteratureDebate = GuardedAutonomousLiteratureDebate


__all__ = [
    "AutonomousLiteratureDebate",
    "GuardedAutonomousLiteratureDebate",
    "source_reliability",
]
