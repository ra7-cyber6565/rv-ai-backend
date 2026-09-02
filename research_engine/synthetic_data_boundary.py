"""Lineage-safe synthetic data boundary for capability #110.

Synthetic data can be useful for training, stress tests and simulation, but it
must not be silently relabelled as real evidence.  This module resolves a bounded
artifact DAG, detects lineage laundering/cycles/unknown provenance, and allows a
real-world validation claim only when every declared validation/holdout artifact
has effective REAL lineage.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple

_ID = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_LINEAGES = {"REAL", "SYNTHETIC", "MIXED", "UNKNOWN"}
_ROLES = {"TRAIN", "VALIDATION", "HOLDOUT", "STRESS", "REFERENCE"}
_MAX = 10_000


def _id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID.fullmatch(text):
        raise ValueError(f"{field} is empty or invalid")
    return text


def _hash(value: Any) -> str:
    try:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("synthetic-boundary payload must be finite JSON-compatible data") from exc
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class DataArtifact:
    artifact_id: str
    declared_lineage: str
    role: str
    parent_ids: Tuple[str, ...] = ()
    generator_id: str = ""
    source_ref: str = ""

    def normalized(self) -> "DataArtifact":
        lineage = str(self.declared_lineage or "").strip().upper()
        role = str(self.role or "").strip().upper()
        if lineage not in _LINEAGES:
            raise ValueError("declared_lineage is invalid")
        if role not in _ROLES:
            raise ValueError("role is invalid")
        parents = tuple(sorted({_id(item, "parent_id") for item in self.parent_ids}))
        artifact_id = _id(self.artifact_id, "artifact_id")
        if artifact_id in parents:
            raise ValueError("artifact cannot be its own parent")
        generator = str(self.generator_id or "").strip()
        source = str(self.source_ref or "").strip()
        if lineage == "SYNTHETIC" and not generator:
            raise ValueError("synthetic artifact requires generator_id")
        if lineage == "REAL" and not parents and not source:
            raise ValueError("root REAL artifact requires source_ref")
        return DataArtifact(artifact_id, lineage, role, parents, generator, source)


@dataclass(frozen=True)
class ArtifactLineageResult:
    artifact_id: str
    declared_lineage: str
    effective_lineage: str
    role: str
    synthetic_ancestor: bool
    unknown_ancestor: bool
    violations: Tuple[str, ...]


@dataclass(frozen=True)
class SyntheticBoundaryReport:
    artifacts: Tuple[ArtifactLineageResult, ...]
    violations: Tuple[str, ...]
    validation_artifact_ids: Tuple[str, ...]
    real_world_validation_eligible: bool
    report_hash: str
    synthetic_evidence_can_prove_real_world_effect: bool = False
    truth_proven: bool = False


def enforce_synthetic_boundary(artifacts: Sequence[DataArtifact]) -> SyntheticBoundaryReport:
    if isinstance(artifacts, (str, bytes, bytearray)) or not isinstance(artifacts, Sequence):
        raise ValueError("artifacts must be a finite sequence")
    if not 1 <= len(artifacts) <= _MAX:
        raise ValueError(f"artifacts must contain 1..{_MAX} items")
    rows = tuple(item.normalized() for item in artifacts)
    by_id = {item.artifact_id: item for item in rows}
    if len(by_id) != len(rows):
        raise ValueError("artifact_id values must be unique")
    for item in rows:
        missing = [parent for parent in item.parent_ids if parent not in by_id]
        if missing:
            raise ValueError(
                f"artifact {item.artifact_id} references unknown parents: {', '.join(missing)}"
            )

    state: Dict[str, int] = {}
    memo: Dict[str, Tuple[str, bool, bool, Tuple[str, ...]]] = {}

    def resolve(artifact_id: str):
        if artifact_id in memo:
            return memo[artifact_id]
        marker = state.get(artifact_id, 0)
        if marker == 1:
            raise ValueError("artifact lineage graph contains a cycle")
        state[artifact_id] = 1
        item = by_id[artifact_id]
        parents = [resolve(parent) for parent in item.parent_ids]
        parent_effective = {value[0] for value in parents}
        synthetic_ancestor = any(value[1] or value[0] in {"SYNTHETIC", "MIXED"} for value in parents)
        unknown_ancestor = any(value[2] or value[0] == "UNKNOWN" for value in parents)
        violations = []

        if item.declared_lineage == "UNKNOWN":
            effective = "UNKNOWN"
            unknown_ancestor = True
        elif item.declared_lineage == "SYNTHETIC":
            effective = "SYNTHETIC"
            synthetic_ancestor = True
        elif item.declared_lineage == "MIXED":
            effective = "MIXED"
            synthetic_ancestor = True
            if not item.parent_ids:
                violations.append("MIXED artifact requires lineage parents")
        else:  # REAL
            if synthetic_ancestor or parent_effective & {"SYNTHETIC", "MIXED"}:
                effective = "MIXED"
                synthetic_ancestor = True
                violations.append("synthetic lineage cannot be relabelled REAL")
            elif unknown_ancestor or "UNKNOWN" in parent_effective:
                effective = "UNKNOWN"
                unknown_ancestor = True
                violations.append("REAL lineage depends on unknown provenance")
            else:
                effective = "REAL"

        memo[artifact_id] = (
            effective,
            synthetic_ancestor,
            unknown_ancestor,
            tuple(sorted(set(violations))),
        )
        state[artifact_id] = 2
        return memo[artifact_id]

    results = []
    all_violations = []
    validation_ids = []
    for item in sorted(rows, key=lambda row: row.artifact_id):
        effective, synthetic_ancestor, unknown_ancestor, violations = resolve(item.artifact_id)
        if item.role in {"VALIDATION", "HOLDOUT"}:
            validation_ids.append(item.artifact_id)
            if effective != "REAL":
                all_violations.append(
                    f"{item.artifact_id}: {item.role} effective lineage is {effective}, not REAL"
                )
        all_violations.extend(f"{item.artifact_id}: {value}" for value in violations)
        results.append(ArtifactLineageResult(
            artifact_id=item.artifact_id,
            declared_lineage=item.declared_lineage,
            effective_lineage=effective,
            role=item.role,
            synthetic_ancestor=synthetic_ancestor,
            unknown_ancestor=unknown_ancestor,
            violations=violations,
        ))

    if not validation_ids:
        all_violations.append("no REAL validation or holdout artifact was declared")
    all_violations = tuple(sorted(set(all_violations)))
    eligible = not all_violations and bool(validation_ids)
    payload = {
        "artifacts": [item.__dict__ for item in results],
        "violations": all_violations,
        "validation_ids": sorted(validation_ids),
        "eligible": eligible,
    }
    return SyntheticBoundaryReport(
        artifacts=tuple(results),
        violations=all_violations,
        validation_artifact_ids=tuple(sorted(validation_ids)),
        real_world_validation_eligible=eligible,
        report_hash=_hash(payload),
        synthetic_evidence_can_prove_real_world_effect=False,
        truth_proven=False,
    )
