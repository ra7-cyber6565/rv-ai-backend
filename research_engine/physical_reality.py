"""Explicit physical-reality constraint engine for capability #69.

This engine audits *supplied structured observations* against explicit numeric
constraints.  It never extracts physical laws from prose and never treats a
simulation/model value as a real measurement.  Passing a constraint therefore
means only that the supplied values are internally compatible with that
constraint; it does not prove the observations are authentic or that the model
matches reality.

Supported constraint families are intentionally small and auditable:
- RANGE: one observation must lie inside [lower, upper];
- LINEAR_BOUNDS: a linear combination must lie inside [lower, upper];
- CONSERVATION: a linear combination must match target within tolerance;
- RATE_LIMIT: two timestamped observations of one variable must respect a
  maximum absolute rate of change.

Every constraint names the exact observation IDs it uses, so there is no hidden
"pick the convenient measurement" behavior.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple

_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_KINDS = {"MEASURED", "CALIBRATED_MEASUREMENT", "SIMULATION", "MODEL", "ASSUMED"}
_CONSTRAINTS = {"RANGE", "LINEAR_BOUNDS", "CONSERVATION", "RATE_LIMIT"}
_MAX_OBSERVATIONS = 20_000
_MAX_CONSTRAINTS = 10_000
_MAX_TERMS = 128


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
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PhysicalObservation:
    observation_id: str
    variable: str
    value: float
    unit: str
    evidence_kind: str
    provenance_ref: str
    timestamp_seconds: float | None = None
    independent: bool = False

    def normalized(self) -> "PhysicalObservation":
        kind = str(self.evidence_kind or "").strip().upper()
        if kind not in _KINDS:
            raise ValueError("evidence_kind is invalid")
        provenance = str(self.provenance_ref or "").strip()
        if not 3 <= len(provenance) <= 20_000:
            raise ValueError("provenance_ref is missing or too long")
        timestamp = None
        if self.timestamp_seconds is not None:
            timestamp = _finite(self.timestamp_seconds, "timestamp_seconds")
        return PhysicalObservation(
            observation_id=_id(self.observation_id, "observation_id"),
            variable=_id(self.variable, "variable"),
            value=_finite(self.value, "value"),
            unit=_id(self.unit, "unit"),
            evidence_kind=kind,
            provenance_ref=provenance,
            timestamp_seconds=timestamp,
            independent=bool(self.independent),
        )

    @property
    def real_measurement(self) -> bool:
        return self.evidence_kind in {"MEASURED", "CALIBRATED_MEASUREMENT"}


@dataclass(frozen=True)
class PhysicalConstraint:
    constraint_id: str
    constraint_type: str
    observation_ids: Tuple[str, ...]
    unit: str
    coefficients: Mapping[str, float] | None = None
    lower: float | None = None
    upper: float | None = None
    target: float | None = None
    tolerance: float | None = None
    max_abs_rate: float | None = None
    require_real_measurement: bool = False

    def normalized(self) -> "PhysicalConstraint":
        constraint_id = _id(self.constraint_id, "constraint_id")
        kind = str(self.constraint_type or "").strip().upper()
        if kind not in _CONSTRAINTS:
            raise ValueError("constraint_type is invalid")
        ids = tuple(_id(item, "observation_id") for item in self.observation_ids)
        if not ids or len(ids) > _MAX_TERMS or len(set(ids)) != len(ids):
            raise ValueError("observation_ids must be unique and bounded")
        unit = _id(self.unit, "unit")
        coefficients = None
        if self.coefficients is not None:
            if not isinstance(self.coefficients, Mapping) or len(self.coefficients) > _MAX_TERMS:
                raise ValueError("coefficients must be a bounded mapping")
            coefficients = {
                _id(key, "coefficient observation_id"): _finite(value, "coefficient")
                for key, value in self.coefficients.items()
            }
        lower = None if self.lower is None else _finite(self.lower, "lower")
        upper = None if self.upper is None else _finite(self.upper, "upper")
        target = None if self.target is None else _finite(self.target, "target")
        tolerance = None if self.tolerance is None else _finite(self.tolerance, "tolerance")
        max_abs_rate = None if self.max_abs_rate is None else _finite(self.max_abs_rate, "max_abs_rate")

        if kind == "RANGE":
            if len(ids) != 1 or lower is None or upper is None or upper < lower:
                raise ValueError("RANGE requires one observation and valid lower/upper")
        elif kind == "LINEAR_BOUNDS":
            if coefficients is None or set(coefficients) != set(ids):
                raise ValueError("LINEAR_BOUNDS coefficients must match observation_ids")
            if lower is None or upper is None or upper < lower:
                raise ValueError("LINEAR_BOUNDS requires valid lower/upper")
        elif kind == "CONSERVATION":
            if coefficients is None or set(coefficients) != set(ids):
                raise ValueError("CONSERVATION coefficients must match observation_ids")
            if target is None or tolerance is None or tolerance < 0:
                raise ValueError("CONSERVATION requires target and non-negative tolerance")
        elif kind == "RATE_LIMIT":
            if len(ids) != 2 or max_abs_rate is None or max_abs_rate < 0:
                raise ValueError("RATE_LIMIT requires two observations and non-negative max_abs_rate")

        return PhysicalConstraint(
            constraint_id=constraint_id,
            constraint_type=kind,
            observation_ids=ids,
            unit=unit,
            coefficients=dict(sorted((coefficients or {}).items())) or None,
            lower=lower,
            upper=upper,
            target=target,
            tolerance=tolerance,
            max_abs_rate=max_abs_rate,
            require_real_measurement=bool(self.require_real_measurement),
        )


@dataclass(frozen=True)
class ConstraintAudit:
    constraint_id: str
    constraint_type: str
    calculated_value: float | None
    calculation_passed: bool
    evidence_sufficient: bool
    verified_constraint: bool
    blockers: Tuple[str, ...]
    observation_ids: Tuple[str, ...]


@dataclass(frozen=True)
class PhysicalRealityReport:
    audits: Tuple[ConstraintAudit, ...]
    all_calculations_passed: bool
    all_evidence_sufficient: bool
    all_constraints_verified: bool
    report_sha256: str
    structured_constraints_only: bool = True
    simulation_promoted_to_measurement: bool = False
    hardware_authenticity_proven: bool = False
    physical_truth_proven: bool = False


def audit_physical_reality(
    *,
    observations: Sequence[PhysicalObservation],
    constraints: Sequence[PhysicalConstraint],
) -> PhysicalRealityReport:
    if isinstance(observations, (str, bytes, bytearray)) or not isinstance(observations, Sequence):
        raise ValueError("observations must be a finite sequence")
    if isinstance(constraints, (str, bytes, bytearray)) or not isinstance(constraints, Sequence):
        raise ValueError("constraints must be a finite sequence")
    if not observations or len(observations) > _MAX_OBSERVATIONS:
        raise ValueError("observations must contain 1..20000 rows")
    if not constraints or len(constraints) > _MAX_CONSTRAINTS:
        raise ValueError("constraints must contain 1..10000 rows")

    normalized = tuple(row.normalized() for row in observations)
    by_id = {row.observation_id: row for row in normalized}
    if len(by_id) != len(normalized):
        raise ValueError("observation_id values must be unique")
    specs = tuple(item.normalized() for item in constraints)
    if len({item.constraint_id for item in specs}) != len(specs):
        raise ValueError("constraint_id values must be unique")

    audits = []
    for spec in specs:
        missing = [item for item in spec.observation_ids if item not in by_id]
        if missing:
            raise ValueError("constraint references unknown observation_id")
        rows = [by_id[item] for item in spec.observation_ids]
        if any(row.unit != spec.unit for row in rows):
            raise ValueError("constraint/observation units must match exactly")
        blockers = []
        if spec.require_real_measurement and not all(row.real_measurement for row in rows):
            blockers.append("real_measurement_missing")

        value: float | None
        if spec.constraint_type == "RANGE":
            value = rows[0].value
            passed = bool(spec.lower <= value <= spec.upper)  # type: ignore[operator]
        elif spec.constraint_type == "LINEAR_BOUNDS":
            value = sum(spec.coefficients[row.observation_id] * row.value for row in rows)  # type: ignore[index]
            passed = bool(spec.lower <= value <= spec.upper)  # type: ignore[operator]
        elif spec.constraint_type == "CONSERVATION":
            value = sum(spec.coefficients[row.observation_id] * row.value for row in rows)  # type: ignore[index]
            passed = abs(value - spec.target) <= spec.tolerance  # type: ignore[operator]
        else:
            first, second = rows
            if first.variable != second.variable:
                raise ValueError("RATE_LIMIT observations must measure the same variable")
            if first.timestamp_seconds is None or second.timestamp_seconds is None:
                raise ValueError("RATE_LIMIT requires timestamps")
            dt = second.timestamp_seconds - first.timestamp_seconds
            if dt <= 0:
                raise ValueError("RATE_LIMIT timestamps must be strictly increasing")
            value = abs(second.value - first.value) / dt
            passed = value <= spec.max_abs_rate  # type: ignore[operator]

        evidence_sufficient = not blockers
        audits.append(ConstraintAudit(
            constraint_id=spec.constraint_id,
            constraint_type=spec.constraint_type,
            calculated_value=value,
            calculation_passed=passed,
            evidence_sufficient=evidence_sufficient,
            verified_constraint=passed and evidence_sufficient,
            blockers=tuple(blockers),
            observation_ids=spec.observation_ids,
        ))

    payload = [asdict(item) for item in audits]
    return PhysicalRealityReport(
        audits=tuple(audits),
        all_calculations_passed=all(item.calculation_passed for item in audits),
        all_evidence_sufficient=all(item.evidence_sufficient for item in audits),
        all_constraints_verified=all(item.verified_constraint for item in audits),
        report_sha256=_hash(payload),
    )
