"""Independence-aware autonomous literature debate foundation (#103).

The engine debates *documented literature positions*, not model personalities.
It is deliberately neutral about which position is true.  Exact/syndicated
content, declared independence groups and genealogy are collapsed before an
independent-position count is produced.  Retraction, incomplete provenance or
explicitly weak evidence may remain visible for audit but cannot become strong
independent support.

This is a deterministic debate/audit engine.  It does not prove truth,
scientific consensus, replication, or independent validation merely by running.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple


_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_MAX_POSITIONS = 10_000
_MAX_PARENTS = 100
_MAX_TEXT = 20_000
_QUALITY = {"STRONG", "USABLE", "WEAK", "UNKNOWN"}


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("literature debate payload must be finite JSON-compatible data") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is empty or invalid")
    return text


def _text(value: object, field: str, *, required: bool = True) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field} is required")
    if len(text) > _MAX_TEXT:
        raise ValueError(f"{field} exceeds bounded length")
    return text


def _sha256(value: object, field: str) -> str:
    text = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ValueError(f"{field} must be a SHA-256 hex digest")
    return text


@dataclass(frozen=True)
class LiteraturePosition:
    source_id: str
    proposition_id: str
    position_id: str
    position_text: str
    independence_key: str
    content_hash: str
    evidence_ref: str
    quality: str = "UNKNOWN"
    retracted: bool = False
    provenance_complete: bool = True
    parent_source_ids: Tuple[str, ...] = ()

    def normalized(self) -> "LiteraturePosition":
        quality = str(self.quality or "UNKNOWN").strip().upper()
        if quality not in _QUALITY:
            raise ValueError("quality must be STRONG/USABLE/WEAK/UNKNOWN")
        parents = tuple(sorted({_safe_id(item, "parent_source_id") for item in self.parent_source_ids}))
        if len(parents) > _MAX_PARENTS:
            raise ValueError("parent_source_ids exceeds bounded size")
        source_id = _safe_id(self.source_id, "source_id")
        if source_id in parents:
            raise ValueError("source cannot depend on itself")
        return LiteraturePosition(
            source_id=source_id,
            proposition_id=_safe_id(self.proposition_id, "proposition_id"),
            position_id=_safe_id(self.position_id, "position_id"),
            position_text=_text(self.position_text, "position_text"),
            independence_key=_safe_id(self.independence_key, "independence_key"),
            content_hash=_sha256(self.content_hash, "content_hash"),
            evidence_ref=_text(self.evidence_ref, "evidence_ref"),
            quality=quality,
            retracted=bool(self.retracted),
            provenance_complete=bool(self.provenance_complete),
            parent_source_ids=parents,
        )

    @property
    def eligible_for_strong_count(self) -> bool:
        return (
            not self.retracted
            and self.provenance_complete
            and self.quality in {"STRONG", "USABLE"}
        )


@dataclass(frozen=True)
class DebateComponent:
    component_id: str
    position_id: str
    source_ids: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    eligible_source_ids: Tuple[str, ...]
    collapsed_copy_count: int
    strong_count_eligible: bool


@dataclass(frozen=True)
class CrossExamination:
    challenge_id: str
    proposition_id: str
    left_position_id: str
    right_position_id: str
    left_component_id: str
    right_component_id: str
    question: str
    answer_known: bool = False


@dataclass(frozen=True)
class PropositionDebate:
    proposition_id: str
    source_count: int
    position_count: int
    effective_components: int
    eligible_components: int
    components: Tuple[DebateComponent, ...]
    cross_examinations: Tuple[CrossExamination, ...]
    status: str
    unresolved: bool
    report_hash: str
    consensus_proves_truth: bool = False
    truth_proven: bool = False
    independent_validation_proven: bool = False


@dataclass(frozen=True)
class LiteratureDebateReport:
    proposition_count: int
    source_count: int
    debates: Tuple[PropositionDebate, ...]
    unresolved_propositions: Tuple[str, ...]
    insufficient_propositions: Tuple[str, ...]
    report_hash: str
    consensus_proves_truth: bool = False
    truth_proven: bool = False
    independent_validation_proven: bool = False


def _components(rows: Sequence[LiteraturePosition]) -> Tuple[DebateComponent, ...]:
    """Collapse dependence transitively by declared group, exact content, genealogy.

    Genealogy edges are conservative: if one included source names another
    included source as a parent, both are a single effective evidence component.
    This prevents a citation chain from masquerading as independent replication.
    """
    by_id = {row.source_id: row for row in rows}
    parent: Dict[str, str] = {row.source_id: row.source_id for row in rows}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a == b:
            return
        if a > b:
            a, b = b, a
        parent[b] = a

    by_group: Dict[str, str] = {}
    by_content: Dict[str, str] = {}
    for row in sorted(rows, key=lambda item: item.source_id):
        previous = by_group.get(row.independence_key)
        if previous is None:
            by_group[row.independence_key] = row.source_id
        else:
            union(previous, row.source_id)
        previous = by_content.get(row.content_hash)
        if previous is None:
            by_content[row.content_hash] = row.source_id
        else:
            union(previous, row.source_id)
        for parent_id in row.parent_source_ids:
            if parent_id in by_id:
                union(row.source_id, parent_id)

    grouped: Dict[Tuple[str, str], list[LiteraturePosition]] = {}
    for row in rows:
        grouped.setdefault((row.position_id, find(row.source_id)), []).append(row)

    output = []
    for (position_id, _root), members in sorted(grouped.items()):
        source_ids = tuple(sorted(item.source_id for item in members))
        eligible = tuple(sorted(item.source_id for item in members if item.eligible_for_strong_count))
        refs = tuple(sorted({item.evidence_ref for item in members}))
        digest = _hash({
            "position_id": position_id,
            "source_ids": source_ids,
            "evidence_refs": refs,
        })
        output.append(DebateComponent(
            component_id=f"component-{digest[:16]}",
            position_id=position_id,
            source_ids=source_ids,
            evidence_refs=refs,
            eligible_source_ids=eligible,
            collapsed_copy_count=max(0, len(source_ids) - 1),
            strong_count_eligible=bool(eligible),
        ))
    return tuple(output)


def _cross_examinations(
    proposition_id: str,
    components: Sequence[DebateComponent],
) -> Tuple[CrossExamination, ...]:
    eligible = [item for item in components if item.strong_count_eligible]
    output = []
    for index, left in enumerate(eligible):
        for right in eligible[index + 1:]:
            if left.position_id == right.position_id:
                continue
            payload = {
                "proposition_id": proposition_id,
                "left": left.component_id,
                "right": right.component_id,
            }
            digest = _hash(payload)
            output.append(CrossExamination(
                challenge_id=f"cross-exam-{digest[:16]}",
                proposition_id=proposition_id,
                left_position_id=left.position_id,
                right_position_id=right.position_id,
                left_component_id=left.component_id,
                right_component_id=right.component_id,
                question=(
                    "Kaunsa pre-specified observable result ya methodological difference "
                    f"{left.position_id} ko {right.position_id} se discriminate karega, "
                    "aur kya cited evidence us discriminator ko actually measure karta hai?"
                ),
                answer_known=False,
            ))
    return tuple(output)


def debate_literature(positions: Sequence[LiteraturePosition]) -> LiteratureDebateReport:
    if isinstance(positions, (str, bytes, bytearray)) or not isinstance(positions, Sequence):
        raise ValueError("positions must be a finite sequence")
    if not 1 <= len(positions) <= _MAX_POSITIONS:
        raise ValueError(f"positions must contain 1..{_MAX_POSITIONS} items")
    normalized = tuple(item.normalized() for item in positions)
    if len({item.source_id for item in normalized}) != len(normalized):
        # One source may have multiple positions across propositions, so the true
        # unique key includes proposition.  Duplicate same-source same-proposition
        # rows are ambiguous and rejected below.
        keys = {(item.source_id, item.proposition_id) for item in normalized}
        if len(keys) != len(normalized):
            raise ValueError("same source cannot submit multiple positions for one proposition")

    by_prop: Dict[str, list[LiteraturePosition]] = {}
    for row in normalized:
        by_prop.setdefault(row.proposition_id, []).append(row)

    debates = []
    unresolved = []
    insufficient = []
    for proposition_id, rows in sorted(by_prop.items()):
        components = _components(rows)
        eligible_components = [item for item in components if item.strong_count_eligible]
        eligible_positions = {item.position_id for item in eligible_components}
        cross = _cross_examinations(proposition_id, components)

        if len(eligible_components) < 2:
            status = "INSUFFICIENT_INDEPENDENT_EVIDENCE"
            insufficient.append(proposition_id)
            is_unresolved = True
        elif len(eligible_positions) < 2:
            status = "ONE_SIDED_LITERATURE"
            insufficient.append(proposition_id)
            is_unresolved = True
        else:
            status = "DISPUTED_UNRESOLVED"
            unresolved.append(proposition_id)
            is_unresolved = True

        payload = {
            "proposition_id": proposition_id,
            "source_count": len(rows),
            "positions": sorted({item.position_id for item in rows}),
            "components": [
                {
                    "component_id": item.component_id,
                    "position_id": item.position_id,
                    "source_ids": item.source_ids,
                    "eligible": item.strong_count_eligible,
                }
                for item in components
            ],
            "cross_examinations": [item.challenge_id for item in cross],
            "status": status,
        }
        debates.append(PropositionDebate(
            proposition_id=proposition_id,
            source_count=len(rows),
            position_count=len({item.position_id for item in rows}),
            effective_components=len(components),
            eligible_components=len(eligible_components),
            components=components,
            cross_examinations=cross,
            status=status,
            unresolved=is_unresolved,
            report_hash=_hash(payload),
        ))

    report_payload = {
        "debates": [item.report_hash for item in debates],
        "source_count": len(normalized),
        "unresolved": sorted(unresolved),
        "insufficient": sorted(insufficient),
    }
    return LiteratureDebateReport(
        proposition_count=len(debates),
        source_count=len(normalized),
        debates=tuple(debates),
        unresolved_propositions=tuple(sorted(unresolved)),
        insufficient_propositions=tuple(sorted(insufficient)),
        report_hash=_hash(report_payload),
    )


def report_to_dict(report: LiteratureDebateReport) -> Dict[str, Any]:
    return {
        "proposition_count": report.proposition_count,
        "source_count": report.source_count,
        "debates": [
            {
                "proposition_id": debate.proposition_id,
                "source_count": debate.source_count,
                "position_count": debate.position_count,
                "effective_components": debate.effective_components,
                "eligible_components": debate.eligible_components,
                "components": [
                    {
                        "component_id": component.component_id,
                        "position_id": component.position_id,
                        "source_ids": list(component.source_ids),
                        "evidence_refs": list(component.evidence_refs),
                        "eligible_source_ids": list(component.eligible_source_ids),
                        "collapsed_copy_count": component.collapsed_copy_count,
                        "strong_count_eligible": component.strong_count_eligible,
                    }
                    for component in debate.components
                ],
                "cross_examinations": [
                    {
                        "challenge_id": item.challenge_id,
                        "left_position_id": item.left_position_id,
                        "right_position_id": item.right_position_id,
                        "left_component_id": item.left_component_id,
                        "right_component_id": item.right_component_id,
                        "question": item.question,
                        "answer_known": item.answer_known,
                    }
                    for item in debate.cross_examinations
                ],
                "status": debate.status,
                "unresolved": debate.unresolved,
                "report_hash": debate.report_hash,
                "consensus_proves_truth": False,
                "truth_proven": False,
                "independent_validation_proven": False,
            }
            for debate in report.debates
        ],
        "unresolved_propositions": list(report.unresolved_propositions),
        "insufficient_propositions": list(report.insufficient_propositions),
        "report_hash": report.report_hash,
        "consensus_proves_truth": False,
        "truth_proven": False,
        "independent_validation_proven": False,
    }
