"""Fail-closed simulation-to-reality gap quantification for capability #127.

The evaluator answers only whether a frozen simulation matches a bounded set of
physical observations within a precommitted protocol.  It deliberately cannot
turn software calculations into hardware proof.  Even a perfect report keeps
``gap_closed=False`` until a separate trusted hardware attestor binds the exact
report to real observations, safety review and repeated physical sessions.

Design invariants
-----------------
* exact model/protocol/sample commitments are SHA-256 bound;
* samples are order-invariant and duplicate IDs are rejected;
* variables and regimes must meet precommitted minimum coverage;
* NRMSE, normalized bias, p95 normalized error and uncertainty coverage are all
  checked, both globally and per regime;
* a small threshold-sensitivity sweep flags boundary-fragile conclusions;
* non-finite values, schema drift and missing hardware receipt references fail
  closed;
* software fit is not physical truth and never mints hardware/safety evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_MAX_VARIABLES = 128
_MAX_SAMPLES = 100_000
_MAX_REGIMES = 256


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
        raise ValueError("payload must be finite JSON-compatible data") from exc


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _sha256(value: object, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return text


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


@dataclass(frozen=True)
class VariableTolerance:
    name: str
    scale: float
    max_nrmse: float
    max_abs_normalized_bias: float
    max_p95_normalized_error: float
    min_uncertainty_coverage: float = 0.80

    def normalized(self) -> "VariableTolerance":
        name = _safe_id(self.name, "variable name")
        scale = _finite(self.scale, f"{name}.scale")
        if scale <= 0:
            raise ValueError("variable scale must be > 0")
        nrmse = _finite(self.max_nrmse, f"{name}.max_nrmse")
        bias = _finite(
            self.max_abs_normalized_bias,
            f"{name}.max_abs_normalized_bias",
        )
        p95 = _finite(
            self.max_p95_normalized_error,
            f"{name}.max_p95_normalized_error",
        )
        coverage = _finite(
            self.min_uncertainty_coverage,
            f"{name}.min_uncertainty_coverage",
        )
        if not (0 < nrmse <= 10 and 0 < bias <= 10 and 0 < p95 <= 20):
            raise ValueError("error tolerances must be positive and bounded")
        if not 0 <= coverage <= 1:
            raise ValueError("min_uncertainty_coverage must be in [0,1]")
        return VariableTolerance(name, scale, nrmse, bias, p95, coverage)


@dataclass(frozen=True)
class SimToRealityProtocol:
    protocol_id: str
    model_hash: str
    variables: Tuple[VariableTolerance, ...]
    min_holdout_samples: int = 20
    min_regimes: int = 2
    min_samples_per_regime: int = 5
    min_distinct_sessions: int = 2
    uncertainty_z: float = 1.96

    def normalized(self) -> "SimToRealityProtocol":
        protocol_id = _safe_id(self.protocol_id, "protocol_id")
        model_hash = _sha256(self.model_hash, "model_hash")
        if not self.variables or len(self.variables) > _MAX_VARIABLES:
            raise ValueError("variables must be a bounded non-empty tuple")
        variables = tuple(item.normalized() for item in self.variables)
        names = [item.name for item in variables]
        if len(set(names)) != len(names):
            raise ValueError("variable names must be unique")
        if type(self.min_holdout_samples) is not int or not 3 <= self.min_holdout_samples <= _MAX_SAMPLES:
            raise ValueError("min_holdout_samples is invalid")
        if type(self.min_regimes) is not int or not 1 <= self.min_regimes <= _MAX_REGIMES:
            raise ValueError("min_regimes is invalid")
        if type(self.min_samples_per_regime) is not int or not 2 <= self.min_samples_per_regime <= _MAX_SAMPLES:
            raise ValueError("min_samples_per_regime is invalid")
        if type(self.min_distinct_sessions) is not int or not 2 <= self.min_distinct_sessions <= 1000:
            raise ValueError("min_distinct_sessions must be >= 2")
        z = _finite(self.uncertainty_z, "uncertainty_z")
        if not 0.5 <= z <= 10:
            raise ValueError("uncertainty_z is outside bounded range")
        return SimToRealityProtocol(
            protocol_id=protocol_id,
            model_hash=model_hash,
            variables=tuple(sorted(variables, key=lambda item: item.name)),
            min_holdout_samples=self.min_holdout_samples,
            min_regimes=self.min_regimes,
            min_samples_per_regime=self.min_samples_per_regime,
            min_distinct_sessions=self.min_distinct_sessions,
            uncertainty_z=z,
        )

    @property
    def protocol_hash(self) -> str:
        normalized = self.normalized()
        return _sha({
            "protocol_id": normalized.protocol_id,
            "model_hash": normalized.model_hash,
            "variables": [vars(item) for item in normalized.variables],
            "min_holdout_samples": normalized.min_holdout_samples,
            "min_regimes": normalized.min_regimes,
            "min_samples_per_regime": normalized.min_samples_per_regime,
            "min_distinct_sessions": normalized.min_distinct_sessions,
            "uncertainty_z": normalized.uncertainty_z,
        })


@dataclass(frozen=True)
class PhysicalComparisonSample:
    sample_id: str
    regime: str
    session_id: str
    timestamp_epoch: float
    predicted: Mapping[str, float]
    observed: Mapping[str, float]
    prediction_uncertainty: Mapping[str, float]
    measurement_uncertainty: Mapping[str, float]
    hardware_receipt_hash: str

    def normalized(self, variables: Sequence[str]) -> "PhysicalComparisonSample":
        expected = set(variables)
        sample_id = _safe_id(self.sample_id, "sample_id")
        regime = _safe_id(self.regime, "regime")
        session_id = _safe_id(self.session_id, "session_id")
        timestamp = _finite(self.timestamp_epoch, "timestamp_epoch")
        if timestamp <= 0:
            raise ValueError("timestamp_epoch must be > 0")
        receipt_hash = _sha256(self.hardware_receipt_hash, "hardware_receipt_hash")

        normalized_maps: Dict[str, Dict[str, float]] = {}
        for field, raw in (
            ("predicted", self.predicted),
            ("observed", self.observed),
            ("prediction_uncertainty", self.prediction_uncertainty),
            ("measurement_uncertainty", self.measurement_uncertainty),
        ):
            if not isinstance(raw, Mapping) or set(raw) != expected:
                raise ValueError(f"{field} keys must exactly match protocol variables")
            values = {name: _finite(raw[name], f"{field}.{name}") for name in variables}
            if "uncertainty" in field and any(value < 0 for value in values.values()):
                raise ValueError(f"{field} cannot contain negative values")
            normalized_maps[field] = dict(sorted(values.items()))

        return PhysicalComparisonSample(
            sample_id=sample_id,
            regime=regime,
            session_id=session_id,
            timestamp_epoch=timestamp,
            predicted=normalized_maps["predicted"],
            observed=normalized_maps["observed"],
            prediction_uncertainty=normalized_maps["prediction_uncertainty"],
            measurement_uncertainty=normalized_maps["measurement_uncertainty"],
            hardware_receipt_hash=receipt_hash,
        )


@dataclass(frozen=True)
class GapMetrics:
    count: int
    nrmse: float
    abs_normalized_bias: float
    p95_normalized_error: float
    uncertainty_coverage: float
    passed: bool

    def to_dict(self) -> dict:
        return vars(self)


@dataclass(frozen=True)
class SimToRealityReport:
    protocol_id: str
    protocol_hash: str
    model_hash: str
    sample_commitment_hash: str
    samples: int
    regimes: Tuple[str, ...]
    sessions: Tuple[str, ...]
    global_metrics: Mapping[str, GapMetrics]
    regime_metrics: Mapping[str, Mapping[str, GapMetrics]]
    structure_sufficient: bool
    software_fit_passed: bool
    threshold_sensitive: bool
    sim_to_reality_gap_quantified: bool
    gap_closed: bool
    hardware_validated: bool
    safety_validated: bool
    external_hardware_attestation_required: bool
    blockers: Tuple[str, ...]
    report_hash: str

    def to_dict(self) -> dict:
        return {
            "protocol_id": self.protocol_id,
            "protocol_hash": self.protocol_hash,
            "model_hash": self.model_hash,
            "sample_commitment_hash": self.sample_commitment_hash,
            "samples": self.samples,
            "regimes": list(self.regimes),
            "sessions": list(self.sessions),
            "global_metrics": {
                key: value.to_dict() for key, value in self.global_metrics.items()
            },
            "regime_metrics": {
                regime: {key: value.to_dict() for key, value in metrics.items()}
                for regime, metrics in self.regime_metrics.items()
            },
            "structure_sufficient": self.structure_sufficient,
            "software_fit_passed": self.software_fit_passed,
            "threshold_sensitive": self.threshold_sensitive,
            "sim_to_reality_gap_quantified": self.sim_to_reality_gap_quantified,
            "gap_closed": self.gap_closed,
            "hardware_validated": self.hardware_validated,
            "safety_validated": self.safety_validated,
            "external_hardware_attestation_required": self.external_hardware_attestation_required,
            "blockers": list(self.blockers),
            "report_hash": self.report_hash,
        }


def _metrics(
    samples: Sequence[PhysicalComparisonSample],
    variable: VariableTolerance,
    *,
    z: float,
    multiplier: float = 1.0,
) -> GapMetrics:
    errors = [sample.predicted[variable.name] - sample.observed[variable.name] for sample in samples]
    normalized_abs = [abs(error) / variable.scale for error in errors]
    nrmse = math.sqrt(sum(error * error for error in errors) / len(errors)) / variable.scale
    bias = abs(sum(errors) / len(errors)) / variable.scale
    p95 = _percentile(normalized_abs, 0.95)
    covered = 0
    for sample, error in zip(samples, errors):
        sigma = math.sqrt(
            sample.prediction_uncertainty[variable.name] ** 2
            + sample.measurement_uncertainty[variable.name] ** 2
        )
        if abs(error) <= z * sigma:
            covered += 1
    coverage = covered / len(samples)
    passed = (
        nrmse <= variable.max_nrmse * multiplier
        and bias <= variable.max_abs_normalized_bias * multiplier
        and p95 <= variable.max_p95_normalized_error * multiplier
        and coverage >= variable.min_uncertainty_coverage
    )
    return GapMetrics(
        count=len(samples),
        nrmse=nrmse,
        abs_normalized_bias=bias,
        p95_normalized_error=p95,
        uncertainty_coverage=coverage,
        passed=passed,
    )


def evaluate_sim_to_reality_gap(
    protocol: SimToRealityProtocol,
    samples: Sequence[PhysicalComparisonSample],
) -> SimToRealityReport:
    """Quantify a frozen simulation against a locked physical holdout.

    ``software_fit_passed`` is a model-fit statement only.  This function always
    returns ``gap_closed=False`` and cannot mint hardware/safety proof.
    """
    protocol = protocol.normalized()
    if isinstance(samples, (str, bytes, bytearray)) or not isinstance(samples, Sequence):
        raise ValueError("samples must be a bounded sequence")
    if not samples or len(samples) > _MAX_SAMPLES:
        raise ValueError("samples must be bounded and non-empty")
    variable_names = tuple(item.name for item in protocol.variables)
    normalized = tuple(sample.normalized(variable_names) for sample in samples)
    ids = [item.sample_id for item in normalized]
    if len(set(ids)) != len(ids):
        raise ValueError("sample_id values must be unique")
    normalized = tuple(sorted(normalized, key=lambda item: item.sample_id))

    regimes = tuple(sorted({item.regime for item in normalized}))
    sessions = tuple(sorted({item.session_id for item in normalized}))
    by_regime = {
        regime: tuple(item for item in normalized if item.regime == regime)
        for regime in regimes
    }
    blockers = []
    if len(normalized) < protocol.min_holdout_samples:
        blockers.append("insufficient_holdout_samples")
    if len(regimes) < protocol.min_regimes:
        blockers.append("insufficient_regime_coverage")
    if len(sessions) < protocol.min_distinct_sessions:
        blockers.append("insufficient_distinct_sessions")
    sparse = [
        regime for regime, rows in by_regime.items()
        if len(rows) < protocol.min_samples_per_regime
    ]
    if sparse:
        blockers.append("insufficient_samples_in_regime:" + ",".join(sparse))
    structure_sufficient = not blockers

    global_metrics = {
        variable.name: _metrics(normalized, variable, z=protocol.uncertainty_z)
        for variable in protocol.variables
    }
    regime_metrics = {
        regime: {
            variable.name: _metrics(rows, variable, z=protocol.uncertainty_z)
            for variable in protocol.variables
        }
        for regime, rows in by_regime.items()
    }
    metric_pass = all(item.passed for item in global_metrics.values()) and all(
        item.passed for metrics in regime_metrics.values() for item in metrics.values()
    )
    software_fit_passed = structure_sufficient and metric_pass

    strict_pass = structure_sufficient and all(
        _metrics(normalized, variable, z=protocol.uncertainty_z, multiplier=0.90).passed
        for variable in protocol.variables
    ) and all(
        _metrics(rows, variable, z=protocol.uncertainty_z, multiplier=0.90).passed
        for rows in by_regime.values() for variable in protocol.variables
    )
    loose_pass = structure_sufficient and all(
        _metrics(normalized, variable, z=protocol.uncertainty_z, multiplier=1.10).passed
        for variable in protocol.variables
    ) and all(
        _metrics(rows, variable, z=protocol.uncertainty_z, multiplier=1.10).passed
        for rows in by_regime.values() for variable in protocol.variables
    )
    threshold_sensitive = strict_pass != loose_pass
    if threshold_sensitive:
        blockers.append("threshold_sensitive_conclusion")

    sample_payload = [
        {
            "sample_id": item.sample_id,
            "regime": item.regime,
            "session_id": item.session_id,
            "timestamp_epoch": item.timestamp_epoch,
            "predicted": item.predicted,
            "observed": item.observed,
            "prediction_uncertainty": item.prediction_uncertainty,
            "measurement_uncertainty": item.measurement_uncertainty,
            "hardware_receipt_hash": item.hardware_receipt_hash,
        }
        for item in normalized
    ]
    sample_hash = _sha(sample_payload)
    base = {
        "protocol_id": protocol.protocol_id,
        "protocol_hash": protocol.protocol_hash,
        "model_hash": protocol.model_hash,
        "sample_commitment_hash": sample_hash,
        "samples": len(normalized),
        "regimes": regimes,
        "sessions": sessions,
        "global_metrics": {key: value.to_dict() for key, value in global_metrics.items()},
        "regime_metrics": {
            regime: {key: value.to_dict() for key, value in metrics.items()}
            for regime, metrics in regime_metrics.items()
        },
        "structure_sufficient": structure_sufficient,
        "software_fit_passed": software_fit_passed,
        "threshold_sensitive": threshold_sensitive,
        "sim_to_reality_gap_quantified": True,
        "gap_closed": False,
        "hardware_validated": False,
        "safety_validated": False,
        "external_hardware_attestation_required": True,
        "blockers": tuple(blockers),
    }
    report_hash = _sha(base)
    return SimToRealityReport(
        protocol_id=protocol.protocol_id,
        protocol_hash=protocol.protocol_hash,
        model_hash=protocol.model_hash,
        sample_commitment_hash=sample_hash,
        samples=len(normalized),
        regimes=regimes,
        sessions=sessions,
        global_metrics=global_metrics,
        regime_metrics=regime_metrics,
        structure_sufficient=structure_sufficient,
        software_fit_passed=software_fit_passed,
        threshold_sensitive=threshold_sensitive,
        sim_to_reality_gap_quantified=True,
        gap_closed=False,
        hardware_validated=False,
        safety_validated=False,
        external_hardware_attestation_required=True,
        blockers=tuple(blockers),
        report_hash=report_hash,
    )


def verify_report_hash(report: Mapping[str, Any]) -> bool:
    """Verify canonical report integrity without trusting its conclusions."""
    if not isinstance(report, Mapping) or "report_hash" not in report:
        return False
    claimed = str(report.get("report_hash") or "").strip().lower()
    if not _SHA256_RE.fullmatch(claimed):
        return False
    payload = dict(report)
    payload.pop("report_hash", None)
    try:
        return _sha(payload) == claimed
    except ValueError:
        return False
