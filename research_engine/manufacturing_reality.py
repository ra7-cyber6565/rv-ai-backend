"""Evidence-driven manufacturing reality engine for capability #71.

The engine evaluates explicit manufacturing requirements against exact evidence
receipts.  It does not infer manufacturability from a design description and it
does not treat simulation/model output as measured process capability.

Supported requirement families:
- PROCESS_CAPABILITY: computes Cp/Cpk from measured mean/stddev/spec limits;
- YIELD: checks observed accepted/total counts against a minimum yield;
- TOLERANCE_VERIFICATION: checks measured values against explicit limits;
- QUALITATIVE_GATE: requires an explicit pass/fail receipt for material,
  assembly, supplier, inspection, or process-window evidence.

A software audit can expose blockers but cannot prove factory execution,
hardware authenticity, certification, or production readiness by itself.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence, Tuple

_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_KINDS = {"PROCESS_CAPABILITY", "YIELD", "TOLERANCE_VERIFICATION", "QUALITATIVE_GATE"}
_ENVIRONMENTS = {"ANALYTICAL", "SIMULATION", "LAB", "PILOT", "PRODUCTION"}
_MAX_ROWS = 10_000


def _id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is empty or invalid")
    return text


def _finite(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ManufacturingRequirement:
    requirement_id: str
    requirement_kind: str
    unit: str = "unitless"
    lower_spec: float | None = None
    upper_spec: float | None = None
    minimum_cpk: float | None = None
    minimum_yield: float | None = None
    minimum_sample_size: int = 1
    require_measured: bool = True
    require_hardware_observed: bool = True
    require_independent: bool = False
    require_production_environment: bool = False

    def normalized(self) -> "ManufacturingRequirement":
        kind = str(self.requirement_kind or "").strip().upper()
        if kind not in _KINDS:
            raise ValueError("requirement_kind is invalid")
        if type(self.minimum_sample_size) is not int or not 1 <= self.minimum_sample_size <= 10_000_000:
            raise ValueError("minimum_sample_size must be an integer in 1..10000000")
        lower = None if self.lower_spec is None else _finite(self.lower_spec, "lower_spec")
        upper = None if self.upper_spec is None else _finite(self.upper_spec, "upper_spec")
        cpk = None if self.minimum_cpk is None else _finite(self.minimum_cpk, "minimum_cpk")
        minimum_yield = None if self.minimum_yield is None else _finite(self.minimum_yield, "minimum_yield")
        if lower is not None and upper is not None and upper <= lower:
            raise ValueError("upper_spec must be greater than lower_spec")
        if cpk is not None and cpk < 0:
            raise ValueError("minimum_cpk must be non-negative")
        if minimum_yield is not None and not 0 <= minimum_yield <= 1:
            raise ValueError("minimum_yield must be in [0,1]")
        if kind in {"PROCESS_CAPABILITY", "TOLERANCE_VERIFICATION"} and (lower is None or upper is None):
            raise ValueError(f"{kind} requires lower_spec and upper_spec")
        if kind == "PROCESS_CAPABILITY" and cpk is None:
            raise ValueError("PROCESS_CAPABILITY requires minimum_cpk")
        if kind == "YIELD" and minimum_yield is None:
            raise ValueError("YIELD requires minimum_yield")
        return ManufacturingRequirement(
            requirement_id=_id(self.requirement_id, "requirement_id"),
            requirement_kind=kind,
            unit=_id(self.unit, "unit"),
            lower_spec=lower,
            upper_spec=upper,
            minimum_cpk=cpk,
            minimum_yield=minimum_yield,
            minimum_sample_size=self.minimum_sample_size,
            require_measured=bool(self.require_measured),
            require_hardware_observed=bool(self.require_hardware_observed),
            require_independent=bool(self.require_independent),
            require_production_environment=bool(self.require_production_environment),
        )


@dataclass(frozen=True)
class ManufacturingEvidence:
    evidence_id: str
    requirement_id: str
    environment: str
    provenance_ref: str
    sample_size: int = 1
    measured: bool = False
    hardware_observed: bool = False
    independent: bool = False
    reproducible: bool = False
    mean: float | None = None
    stddev: float | None = None
    accepted_count: int | None = None
    total_count: int | None = None
    measured_values: Tuple[float, ...] = ()
    explicit_pass: bool | None = None

    def normalized(self) -> "ManufacturingEvidence":
        environment = str(self.environment or "").strip().upper()
        if environment not in _ENVIRONMENTS:
            raise ValueError("environment is invalid")
        provenance = str(self.provenance_ref or "").strip()
        if not 3 <= len(provenance) <= 20_000:
            raise ValueError("provenance_ref is missing or too long")
        if type(self.sample_size) is not int or not 1 <= self.sample_size <= 10_000_000:
            raise ValueError("sample_size must be an integer in 1..10000000")
        mean = None if self.mean is None else _finite(self.mean, "mean")
        stddev = None if self.stddev is None else _finite(self.stddev, "stddev")
        if stddev is not None and stddev <= 0:
            raise ValueError("stddev must be > 0")
        accepted = self.accepted_count
        total = self.total_count
        if accepted is not None or total is not None:
            if type(accepted) is not int or type(total) is not int or total <= 0 or not 0 <= accepted <= total:
                raise ValueError("accepted_count/total_count are invalid")
        values = tuple(_finite(item, "measured_values") for item in self.measured_values)
        if len(values) > _MAX_ROWS:
            raise ValueError("measured_values exceeds bounded size")
        return ManufacturingEvidence(
            evidence_id=_id(self.evidence_id, "evidence_id"),
            requirement_id=_id(self.requirement_id, "requirement_id"),
            environment=environment,
            provenance_ref=provenance,
            sample_size=self.sample_size,
            measured=bool(self.measured),
            hardware_observed=bool(self.hardware_observed),
            independent=bool(self.independent),
            reproducible=bool(self.reproducible),
            mean=mean,
            stddev=stddev,
            accepted_count=accepted,
            total_count=total,
            measured_values=values,
            explicit_pass=self.explicit_pass if isinstance(self.explicit_pass, bool) else None,
        )


@dataclass(frozen=True)
class ManufacturingAudit:
    requirement_id: str
    requirement_kind: str
    passed: bool
    blockers: Tuple[str, ...]
    evidence_ids: Tuple[str, ...]
    cp: float | None = None
    cpk: float | None = None
    observed_yield: float | None = None
    out_of_tolerance_count: int | None = None


@dataclass(frozen=True)
class ManufacturingRealityReport:
    audits: Tuple[ManufacturingAudit, ...]
    all_requirements_passed: bool
    report_sha256: str
    simulation_promoted_to_measurement: bool = False
    factory_execution_proven: bool = False
    hardware_authenticity_proven: bool = False
    external_certification_claimed: bool = False
    manufacturability_truth_proven: bool = False


def _evidence_blockers(requirement: ManufacturingRequirement, rows: Sequence[ManufacturingEvidence]) -> list[str]:
    blockers: list[str] = []
    if not rows:
        return ["evidence_missing"]
    if sum(row.sample_size for row in rows) < requirement.minimum_sample_size:
        blockers.append("sample_size_below_requirement")
    if requirement.require_measured and not all(row.measured for row in rows):
        blockers.append("measured_evidence_missing")
    if requirement.require_hardware_observed and not all(row.hardware_observed for row in rows):
        blockers.append("hardware_observation_missing")
    if requirement.require_independent and not any(row.independent for row in rows):
        blockers.append("independent_evidence_missing")
    if requirement.require_production_environment and not any(row.environment == "PRODUCTION" for row in rows):
        blockers.append("production_environment_evidence_missing")
    return blockers


def audit_manufacturing_reality(
    *,
    requirements: Sequence[ManufacturingRequirement],
    evidence: Sequence[ManufacturingEvidence],
) -> ManufacturingRealityReport:
    if isinstance(requirements, (str, bytes, bytearray)) or not isinstance(requirements, Sequence):
        raise ValueError("requirements must be a finite sequence")
    if isinstance(evidence, (str, bytes, bytearray)) or not isinstance(evidence, Sequence):
        raise ValueError("evidence must be a finite sequence")
    if not requirements or len(requirements) > _MAX_ROWS:
        raise ValueError("requirements must contain 1..10000 rows")
    if len(evidence) > _MAX_ROWS:
        raise ValueError("evidence exceeds bounded size")
    specs = tuple(item.normalized() for item in requirements)
    rows = tuple(item.normalized() for item in evidence)
    if len({item.requirement_id for item in specs}) != len(specs):
        raise ValueError("requirement_id values must be unique")
    if len({item.evidence_id for item in rows}) != len(rows):
        raise ValueError("evidence_id values must be unique")
    known = {item.requirement_id for item in specs}
    if any(item.requirement_id not in known for item in rows):
        raise ValueError("evidence references unknown requirement_id")

    audits = []
    for spec in specs:
        matching = tuple(row for row in rows if row.requirement_id == spec.requirement_id)
        blockers = _evidence_blockers(spec, matching)
        cp = cpk = observed_yield = None
        out_count = None

        if spec.requirement_kind == "PROCESS_CAPABILITY":
            usable = [row for row in matching if row.mean is not None and row.stddev is not None]
            if not usable:
                blockers.append("process_statistics_missing")
            else:
                # Fail closed on inconsistent studies: every supplied usable study
                # must meet the threshold, not merely the most favorable one.
                cp_values = []
                cpk_values = []
                for row in usable:
                    width = spec.upper_spec - spec.lower_spec  # type: ignore[operator]
                    cp_i = width / (6.0 * row.stddev)  # type: ignore[operator]
                    cpk_i = min(
                        (spec.upper_spec - row.mean) / (3.0 * row.stddev),  # type: ignore[operator]
                        (row.mean - spec.lower_spec) / (3.0 * row.stddev),  # type: ignore[operator]
                    )
                    cp_values.append(cp_i)
                    cpk_values.append(cpk_i)
                cp = min(cp_values)
                cpk = min(cpk_values)
                if cpk < spec.minimum_cpk:  # type: ignore[operator]
                    blockers.append("cpk_below_requirement")
        elif spec.requirement_kind == "YIELD":
            count_rows = [row for row in matching if row.accepted_count is not None]
            if not count_rows:
                blockers.append("yield_counts_missing")
            else:
                accepted = sum(row.accepted_count for row in count_rows)  # type: ignore[arg-type]
                total = sum(row.total_count for row in count_rows)  # type: ignore[arg-type]
                observed_yield = accepted / total
                if observed_yield < spec.minimum_yield:  # type: ignore[operator]
                    blockers.append("yield_below_requirement")
        elif spec.requirement_kind == "TOLERANCE_VERIFICATION":
            values = [value for row in matching for value in row.measured_values]
            if not values:
                blockers.append("measured_values_missing")
            else:
                out_count = sum(not (spec.lower_spec <= value <= spec.upper_spec) for value in values)  # type: ignore[operator]
                if out_count:
                    blockers.append("out_of_tolerance_observations")
        else:
            if not matching or any(row.explicit_pass is not True for row in matching):
                blockers.append("explicit_gate_not_passed")

        blockers = sorted(set(blockers))
        audits.append(ManufacturingAudit(
            requirement_id=spec.requirement_id,
            requirement_kind=spec.requirement_kind,
            passed=not blockers,
            blockers=tuple(blockers),
            evidence_ids=tuple(sorted(row.evidence_id for row in matching)),
            cp=cp,
            cpk=cpk,
            observed_yield=observed_yield,
            out_of_tolerance_count=out_count,
        ))

    payload = [asdict(item) for item in audits]
    return ManufacturingRealityReport(
        audits=tuple(audits),
        all_requirements_passed=all(item.passed for item in audits),
        report_sha256=_hash(payload),
    )
