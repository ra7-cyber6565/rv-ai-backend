"""Additive AI-1 packet extensions for source-family completeness.

The base AI-1 director owns the exact 15-section contract. This module may add
nested receipts to those sections and top-level machine audit data, but it may
not add/reorder/remove a section or promote any claim grade.
"""
from __future__ import annotations

from typing import Dict, List, Mapping

from .critical_source_anatomy import missing_anatomy_items
from .source_capability_matrix import build_source_capability_matrix

_SECTION_5 = "5. Strongest Sources"
_SECTION_11 = "11. Missing Evidence"
_SECTION_13 = "13. Highest-Value Second-Pass Research Tasks"
_SECTION_14 = "14. Confidence in Research Packet /100"
_SECTION_15 = "15. Exactly What Prevents a Higher Score"

_RESEARCH_DOC_KINDS = {
    "peer_reviewed_article", "review_article", "preprint", "conference_paper", "thesis",
}
_RESEARCH_FAMILIES = {"paper", "thesis_dissertation"}


def _source_map(result: Mapping) -> Dict[str, Mapping]:
    out: Dict[str, Mapping] = {}
    for bucket in ("sources", "citations", "uncited_sources"):
        for source in result.get(bucket) or []:
            if not isinstance(source, Mapping):
                continue
            sid = str(source.get("source_id") or "").strip()
            if sid and sid not in out:
                out[sid] = source
    return out


def _anatomy(source: Mapping) -> Dict:
    verdict = source.get("domain_verdict")
    if not isinstance(verdict, Mapping):
        return {}
    value = verdict.get("critical_source_anatomy")
    return dict(value) if isinstance(value, Mapping) else {}


def _is_critical_research_source(strong_row: Mapping, source: Mapping) -> bool:
    family = str(strong_row.get("source_family") or "")
    kind = str(source.get("doc_kind") or "")
    depth = str(strong_row.get("full_text_status") or "").upper()
    deep = depth in {"FULL TEXT ACCESSED", "RELEVANT SECTIONS REVIEWED"}
    return deep and (family in _RESEARCH_FAMILIES or kind in _RESEARCH_DOC_KINDS)


def _dedupe_dicts(rows: List[Dict], keys: tuple[str, ...]) -> List[Dict]:
    out: List[Dict] = []
    seen = set()
    for row in rows:
        key = tuple(str(row.get(name) or "") for name in keys)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def extend_ai1_packet(question: str, result: Dict) -> Dict:
    """Attach capability + anatomy receipts after base AI-1 packet generation."""
    if not isinstance(result, dict):
        return result
    packet = result.get("ai1_research_packet")
    if not isinstance(packet, dict):
        return result
    sections = packet.get("sections")
    if not isinstance(sections, dict) or len(sections) != 15:
        packet["source_family_extension"] = {
            "valid": False,
            "reason": "base AI-1 exact 15-section packet unavailable",
        }
        return result

    capability = build_source_capability_matrix(result)
    packet["source_capability_matrix"] = capability
    sources = _source_map(result)

    strongest = sections.get(_SECTION_5)
    strongest = strongest if isinstance(strongest, list) else []
    anatomy_missing: List[Dict] = []
    anatomy_attached = 0
    for row in strongest:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("source_id") or "")
        source = sources.get(sid, {})
        anatomy = _anatomy(source)
        if anatomy:
            row["critical_document_anatomy"] = anatomy
            anatomy_attached += 1
        if not _is_critical_research_source(row, source):
            continue
        if not anatomy:
            anatomy_missing.append({
                "code": "MISSING DATA",
                "detail": (
                    "critical deep research source has no structured methods/sample/"
                    "assumptions/findings/limitations/replication anatomy receipt"
                ),
                "source_id": sid,
                "anatomy_field": "all",
            })
            continue
        for gap in missing_anatomy_items(anatomy):
            anatomy_missing.append({**gap, "source_id": sid})

    missing = sections.get(_SECTION_11)
    missing_rows = [dict(row) for row in missing if isinstance(row, Mapping)] if isinstance(missing, list) else []
    missing_rows.extend(anatomy_missing)
    sections[_SECTION_11] = _dedupe_dicts(
        missing_rows, ("code", "source_id", "anatomy_field", "detail"))

    tasks = sections.get(_SECTION_13)
    task_rows = [dict(row) for row in tasks if isinstance(row, Mapping)] if isinstance(tasks, list) else []
    for gap in anatomy_missing:
        task_rows.append({
            "task": "Recover/inspect missing critical-document anatomy",
            "why": str(gap.get("detail") or "critical document anatomy is incomplete"),
            "source_id": str(gap.get("source_id") or ""),
            "anatomy_field": str(gap.get("anatomy_field") or ""),
            "importance": 10,
            "expected_information_gain": 9,
            "priority_score": 90,
            "priority_formula": "Importance × Expected Information Gain",
            "route_to": "AI-1",
        })
    task_rows = _dedupe_dicts(task_rows, ("task", "source_id", "anatomy_field"))
    task_rows.sort(key=lambda row: int(row.get("priority_score") or 0), reverse=True)
    sections[_SECTION_13] = task_rows

    confidence = sections.get(_SECTION_14)
    if isinstance(confidence, dict):
        confidence["source_capability_matrix_valid"] = bool(capability.get("valid"))
        confidence["critical_anatomy_sources_attached"] = anatomy_attached
        confidence["critical_anatomy_gap_count"] = len(anatomy_missing)
        if anatomy_missing:
            confidence["score"] = min(int(confidence.get("score") or 0), 92)
        if not capability.get("valid"):
            confidence["score"] = min(int(confidence.get("score") or 0), 60)

    blockers = sections.get(_SECTION_15)
    blocker_rows = list(blockers) if isinstance(blockers, list) else []
    if anatomy_missing:
        blocker_rows.append(
            f"Critical-document anatomy has {len(anatomy_missing)} unresolved field/source gap(s)."
        )
    if not capability.get("valid"):
        blocker_rows.append(
            "AI-1 source capability matrix import proof is incomplete: "
            + ", ".join(capability.get("missing_required_modules") or [])
        )
    sections[_SECTION_15] = list(dict.fromkeys(str(item) for item in blocker_rows if str(item)))

    packet["source_family_extension"] = {
        "valid": bool(capability.get("valid")) and len(sections) == 15,
        "exact_15_sections_preserved": len(sections) == 15,
        "critical_anatomy_attached": anatomy_attached,
        "critical_anatomy_gap_count": len(anatomy_missing),
        "claim_grades_modified": False,
        "final_answer_generated": False,
    }
    return result


__all__ = ["extend_ai1_packet"]
