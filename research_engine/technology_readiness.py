"""Evidence-driven technology readiness ladder for capability #70.

The ladder is deliberately contiguous: a system cannot jump to a high readiness
level because one impressive demo exists.  Each level needs its own provenance-
bound evidence and progressively stronger environment/integration/independence
requirements.  Physical/hybrid technology additionally requires real hardware
observations at higher levels; simulation alone can never satisfy that boundary.

The 1..9 ladder is an internal audit scale, not a claim of certification by any
external standards body.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Sequence, Tuple

_ID = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_TYPES = {"SOFTWARE", "PHYSICAL", "HYBRID"}
_ENVS = {"ANALYTICAL", "LAB", "RELEVANT", "OPERATIONAL"}
_KINDS = {
    "PRINCIPLE",
    "CONCEPT",
    "EXPERIMENT",
    "SIMULATION",
    "COMPONENT_TEST",
    "PROTOTYPE_TEST",
    "QUALIFICATION",
    "PRODUCTION_OBSERVATION",
}
_MAX_EVIDENCE = 10_000


def _id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID.fullmatch(text):
        raise ValueError(f"{field} is empty or invalid")
    return text


def _hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class ReadinessEvidence:
    evidence_id: str
    supports_level: int
    evidence_kind: str
    environment: str
    provenance_ref: str
    independent: bool = False
    reproducible: bool = False
    integrated_system: bool = False
    hardware_observed: bool = False
    safety_reviewed: bool = False
    production_observed: bool = False

    def normalized(self) -> "ReadinessEvidence":
        evidence_id = _id(self.evidence_id, "evidence_id")
        if type(self.supports_level) is not int or not 1 <= self.supports_level <= 9:
            raise ValueError("supports_level must be an integer in 1..9")
        kind = str(self.evidence_kind or "").strip().upper()
        environment = str(self.environment or "").strip().upper()
        if kind not in _KINDS:
            raise ValueError("evidence_kind is invalid")
        if environment not in _ENVS:
            raise ValueError("environment is invalid")
        provenance = str(self.provenance_ref or "").strip()
        if len(provenance) < 3 or len(provenance) > 20_000:
            raise ValueError("provenance_ref is missing or too long")
        return ReadinessEvidence(
            evidence_id=evidence_id,
            supports_level=self.supports_level,
            evidence_kind=kind,
            environment=environment,
            provenance_ref=provenance,
            independent=bool(self.independent),
            reproducible=bool(self.reproducible),
            integrated_system=bool(self.integrated_system),
            hardware_observed=bool(self.hardware_observed),
            safety_reviewed=bool(self.safety_reviewed),
            production_observed=bool(self.production_observed),
        )


@dataclass(frozen=True)
class ReadinessLevelAudit:
    level: int
    passed: bool
    evidence_ids: Tuple[str, ...]
    blockers: Tuple[str, ...]


@dataclass(frozen=True)
class TechnologyReadinessReport:
    technology_id: str
    technology_type: str
    target_level: int
    achieved_level: int
    target_met: bool
    levels: Tuple[ReadinessLevelAudit, ...]
    report_sha256: str
    external_certification_claimed: bool = False
    truth_proven: bool = False


def _level_requirements(level: int, technology_type: str, rows: Sequence[ReadinessEvidence]) -> Tuple[str, ...]:
    blockers = []
    if not rows:
        return ("no_evidence_for_level",)
    kinds = {row.evidence_kind for row in rows}
    envs = {row.environment for row in rows}

    if level == 1 and "PRINCIPLE" not in kinds:
        blockers.append("principle_evidence_missing")
    if level == 2 and "CONCEPT" not in kinds:
        blockers.append("concept_evidence_missing")
    if level == 3:
        if not kinds & {"EXPERIMENT", "SIMULATION", "COMPONENT_TEST"}:
            blockers.append("proof_of_concept_evidence_missing")
        if not any(row.reproducible for row in rows):
            blockers.append("reproducibility_missing")
    if level == 4:
        if "LAB" not in envs:
            blockers.append("lab_validation_missing")
        if not kinds & {"COMPONENT_TEST", "PROTOTYPE_TEST"}:
            blockers.append("component_test_missing")
        if not any(row.independent and row.reproducible for row in rows):
            blockers.append("independent_reproducible_test_missing")
    if level == 5:
        if not envs & {"RELEVANT", "OPERATIONAL"}:
            blockers.append("relevant_environment_missing")
        if not any(row.independent and row.reproducible for row in rows):
            blockers.append("independent_reproducible_test_missing")
    if level == 6:
        if not envs & {"RELEVANT", "OPERATIONAL"}:
            blockers.append("relevant_environment_missing")
        if not any(row.integrated_system and row.reproducible for row in rows):
            blockers.append("integrated_prototype_missing")
    if level == 7:
        if "OPERATIONAL" not in envs:
            blockers.append("operational_environment_missing")
        if not any(row.integrated_system and row.independent for row in rows):
            blockers.append("independent_operational_prototype_missing")
    if level == 8:
        if "QUALIFICATION" not in kinds:
            blockers.append("qualification_evidence_missing")
        if not any(row.integrated_system and row.independent and row.reproducible for row in rows):
            blockers.append("qualified_integrated_system_missing")
        if technology_type in {"PHYSICAL", "HYBRID"} and not any(row.safety_reviewed for row in rows):
            blockers.append("physical_safety_review_missing")
    if level == 9:
        if "PRODUCTION_OBSERVATION" not in kinds or "OPERATIONAL" not in envs:
            blockers.append("operational_production_evidence_missing")
        if not any(row.production_observed and row.independent for row in rows):
            blockers.append("independent_production_observation_missing")

    if technology_type in {"PHYSICAL", "HYBRID"} and level >= 4:
        if not any(row.hardware_observed for row in rows):
            blockers.append("real_hardware_observation_missing")
    return tuple(sorted(set(blockers)))


def assess_technology_readiness(
    *,
    technology_id: str,
    technology_type: str,
    target_level: int,
    evidence: Sequence[ReadinessEvidence],
) -> TechnologyReadinessReport:
    technology_id = _id(technology_id, "technology_id")
    kind = str(technology_type or "").strip().upper()
    if kind not in _TYPES:
        raise ValueError("technology_type must be SOFTWARE, PHYSICAL, or HYBRID")
    if type(target_level) is not int or not 1 <= target_level <= 9:
        raise ValueError("target_level must be an integer in 1..9")
    if isinstance(evidence, (str, bytes, bytearray)) or not isinstance(evidence, Sequence):
        raise ValueError("evidence must be a finite sequence")
    if len(evidence) > _MAX_EVIDENCE:
        raise ValueError("evidence exceeds bounded size")
    rows = tuple(row.normalized() for row in evidence)
    ids = [row.evidence_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("evidence_id values must be unique")

    by_level: Dict[int, list[ReadinessEvidence]] = {level: [] for level in range(1, 10)}
    for row in rows:
        by_level[row.supports_level].append(row)
    audits = []
    achieved = 0
    chain_open = True
    for level in range(1, 10):
        level_rows = tuple(sorted(by_level[level], key=lambda row: row.evidence_id))
        blockers = _level_requirements(level, kind, level_rows)
        passed = chain_open and not blockers
        if passed:
            achieved = level
        else:
            chain_open = False
            if not blockers:
                blockers = ("lower_readiness_level_not_established",)
        audits.append(ReadinessLevelAudit(
            level=level,
            passed=passed,
            evidence_ids=tuple(row.evidence_id for row in level_rows),
            blockers=blockers,
        ))

    payload = {
        "technology_id": technology_id,
        "technology_type": kind,
        "target_level": target_level,
        "achieved_level": achieved,
        "levels": [audit.__dict__ for audit in audits],
    }
    return TechnologyReadinessReport(
        technology_id=technology_id,
        technology_type=kind,
        target_level=target_level,
        achieved_level=achieved,
        target_met=achieved >= target_level,
        levels=tuple(audits),
        report_sha256=_hash(payload),
        external_certification_claimed=False,
        truth_proven=False,
    )
