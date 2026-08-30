"""Prediction-vs-observation reconciliation for capability #41 Reality Oracle.

The oracle is deliberately narrow: it compares an immutable, pre-registered
prediction contract with a later measurement receipt.  It does not decide that
a hypothesis is universally true merely because one prediction matched.

Security / epistemic boundaries:
* prediction must be frozen before the observation timestamp;
* metric and unit must match exactly;
* observations carry a content digest and explicit provenance fields;
* NaN/Inf, timestamp reversal, missing provenance and tolerance abuse fail closed;
* agreement is reported as MATCH / MISS / INCONCLUSIVE, never as "truth";
* this module does not itself prove an observation is live or authentic.  A
  trusted runtime/live attestor must independently validate that stronger fact.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Tuple


_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_SOURCE_KINDS = {"sensor", "external_api", "dataset", "human_measurement"}
_ALLOWED_RULES = {"absolute", "relative", "interval", "directional"}
_ALLOWED_DIRECTIONS = {">", ">=", "<", "<=", "=="}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


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


def _timestamp(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _safe_sha(value: object, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return text


@dataclass(frozen=True)
class PredictionContract:
    prediction_id: str
    hypothesis_id: str
    metric: str
    unit: str
    rule: str
    target: Optional[float]
    lower: Optional[float]
    upper: Optional[float]
    direction: str
    tolerance: float
    preregistered_at: str
    evaluation_after: str
    protocol_hash: str
    contract_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prediction_id": self.prediction_id,
            "hypothesis_id": self.hypothesis_id,
            "metric": self.metric,
            "unit": self.unit,
            "rule": self.rule,
            "target": self.target,
            "lower": self.lower,
            "upper": self.upper,
            "direction": self.direction,
            "tolerance": self.tolerance,
            "preregistered_at": self.preregistered_at,
            "evaluation_after": self.evaluation_after,
            "protocol_hash": self.protocol_hash,
            "contract_hash": self.contract_hash,
        }


@dataclass(frozen=True)
class ObservationReceipt:
    observation_id: str
    metric: str
    unit: str
    observed_value: float
    observed_at: str
    source_id: str
    source_kind: str
    source_digest: str
    raw_reference: str
    receipt_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "metric": self.metric,
            "unit": self.unit,
            "observed_value": self.observed_value,
            "observed_at": self.observed_at,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "source_digest": self.source_digest,
            "raw_reference": self.raw_reference,
            "receipt_hash": self.receipt_hash,
        }


@dataclass(frozen=True)
class OracleEvaluation:
    prediction_id: str
    observation_id: str
    status: str
    matched: Optional[bool]
    residual: Optional[float]
    normalized_error: Optional[float]
    prediction_contract_hash: str
    observation_receipt_hash: str
    evaluation_hash: str
    observation_authenticity_proven: bool
    live_observation_proven: bool
    truth_proven: bool
    reasons: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prediction_id": self.prediction_id,
            "observation_id": self.observation_id,
            "status": self.status,
            "matched": self.matched,
            "residual": self.residual,
            "normalized_error": self.normalized_error,
            "prediction_contract_hash": self.prediction_contract_hash,
            "observation_receipt_hash": self.observation_receipt_hash,
            "evaluation_hash": self.evaluation_hash,
            "observation_authenticity_proven": self.observation_authenticity_proven,
            "live_observation_proven": self.live_observation_proven,
            "truth_proven": self.truth_proven,
            "reasons": list(self.reasons),
        }


def freeze_prediction_contract(
    *,
    prediction_id: str,
    hypothesis_id: str,
    metric: str,
    unit: str,
    rule: str,
    preregistered_at: str,
    evaluation_after: str,
    protocol_hash: str,
    target: Optional[float] = None,
    lower: Optional[float] = None,
    upper: Optional[float] = None,
    direction: str = "",
    tolerance: float = 0.0,
) -> PredictionContract:
    prediction_id = _safe_id(prediction_id, "prediction_id")
    hypothesis_id = _safe_id(hypothesis_id, "hypothesis_id")
    metric = str(metric or "").strip()
    unit = str(unit or "").strip()
    if not metric or len(metric) > 200 or not unit or len(unit) > 100:
        raise ValueError("metric and unit are required and bounded")
    rule = str(rule or "").strip().lower()
    if rule not in _ALLOWED_RULES:
        raise ValueError("unsupported prediction rule")
    preregistered_at = _timestamp(preregistered_at, "preregistered_at")
    evaluation_after = _timestamp(evaluation_after, "evaluation_after")
    if evaluation_after < preregistered_at:
        raise ValueError("evaluation_after must not precede preregistration")
    protocol_hash = _safe_sha(protocol_hash, "protocol_hash")
    tolerance = _finite(tolerance, "tolerance")
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")

    clean_target = None if target is None else _finite(target, "target")
    clean_lower = None if lower is None else _finite(lower, "lower")
    clean_upper = None if upper is None else _finite(upper, "upper")
    clean_direction = str(direction or "").strip()

    if rule in {"absolute", "relative"}:
        if clean_target is None:
            raise ValueError(f"{rule} rule requires target")
        if clean_lower is not None or clean_upper is not None or clean_direction:
            raise ValueError(f"{rule} rule cannot mix interval/directional fields")
    elif rule == "interval":
        if clean_lower is None or clean_upper is None or clean_lower > clean_upper:
            raise ValueError("interval rule requires lower <= upper")
        if clean_target is not None or clean_direction:
            raise ValueError("interval rule cannot mix target/directional fields")
    elif rule == "directional":
        if clean_target is None or clean_direction not in _ALLOWED_DIRECTIONS:
            raise ValueError("directional rule requires target and valid direction")
        if clean_lower is not None or clean_upper is not None or tolerance != 0.0:
            raise ValueError("directional rule cannot mix interval/tolerance fields")

    payload = {
        "prediction_id": prediction_id,
        "hypothesis_id": hypothesis_id,
        "metric": metric,
        "unit": unit,
        "rule": rule,
        "target": clean_target,
        "lower": clean_lower,
        "upper": clean_upper,
        "direction": clean_direction,
        "tolerance": tolerance,
        "preregistered_at": preregistered_at,
        "evaluation_after": evaluation_after,
        "protocol_hash": protocol_hash,
    }
    return PredictionContract(**payload, contract_hash=_sha(payload))


def make_observation_receipt(
    *,
    observation_id: str,
    metric: str,
    unit: str,
    observed_value: float,
    observed_at: str,
    source_id: str,
    source_kind: str,
    source_digest: str,
    raw_reference: str,
) -> ObservationReceipt:
    observation_id = _safe_id(observation_id, "observation_id")
    source_id = _safe_id(source_id, "source_id")
    metric = str(metric or "").strip()
    unit = str(unit or "").strip()
    if not metric or len(metric) > 200 or not unit or len(unit) > 100:
        raise ValueError("metric and unit are required and bounded")
    value = _finite(observed_value, "observed_value")
    observed_at = _timestamp(observed_at, "observed_at")
    source_kind = str(source_kind or "").strip().lower()
    if source_kind not in _ALLOWED_SOURCE_KINDS:
        raise ValueError("unsupported observation source_kind")
    source_digest = _safe_sha(source_digest, "source_digest")
    raw_reference = str(raw_reference or "").strip()
    if not raw_reference or len(raw_reference) > 2000:
        raise ValueError("raw_reference is required and bounded")
    payload = {
        "observation_id": observation_id,
        "metric": metric,
        "unit": unit,
        "observed_value": value,
        "observed_at": observed_at,
        "source_id": source_id,
        "source_kind": source_kind,
        "source_digest": source_digest,
        "raw_reference": raw_reference,
    }
    return ObservationReceipt(**payload, receipt_hash=_sha(payload))


def _direction_pass(direction: str, observed: float, target: float) -> bool:
    if direction == ">":
        return observed > target
    if direction == ">=":
        return observed >= target
    if direction == "<":
        return observed < target
    if direction == "<=":
        return observed <= target
    return observed == target


def evaluate_reality(
    prediction: PredictionContract,
    observation: ObservationReceipt,
) -> OracleEvaluation:
    reasons = []
    matched: Optional[bool] = None
    residual: Optional[float] = None
    normalized_error: Optional[float] = None

    if observation.metric != prediction.metric:
        reasons.append("metric mismatch")
    if observation.unit != prediction.unit:
        reasons.append("unit mismatch")
    if observation.observed_at < prediction.evaluation_after:
        reasons.append("observation occurred before evaluation window")
    if observation.observed_at < prediction.preregistered_at:
        reasons.append("observation predates prediction preregistration")

    if not reasons:
        value = observation.observed_value
        if prediction.rule == "absolute":
            assert prediction.target is not None
            residual = value - prediction.target
            normalized_error = abs(residual)
            matched = normalized_error <= prediction.tolerance or math.isclose(
                normalized_error, prediction.tolerance, rel_tol=1e-12, abs_tol=1e-15
            )
        elif prediction.rule == "relative":
            assert prediction.target is not None
            residual = value - prediction.target
            denominator = abs(prediction.target)
            if denominator <= 1e-15:
                reasons.append("relative error undefined for near-zero target")
            else:
                normalized_error = abs(residual) / denominator
                matched = normalized_error <= prediction.tolerance or math.isclose(
                    normalized_error, prediction.tolerance, rel_tol=1e-12, abs_tol=1e-15
                )
        elif prediction.rule == "interval":
            assert prediction.lower is not None and prediction.upper is not None
            if value < prediction.lower:
                residual = value - prediction.lower
            elif value > prediction.upper:
                residual = value - prediction.upper
            else:
                residual = 0.0
            normalized_error = abs(residual)
            matched = prediction.lower <= value <= prediction.upper
        else:
            assert prediction.target is not None
            residual = value - prediction.target
            normalized_error = abs(residual)
            matched = _direction_pass(prediction.direction, value, prediction.target)

    if reasons:
        status = "INCONCLUSIVE"
        matched = None
    else:
        status = "MATCH" if matched else "MISS"

    payload = {
        "prediction_id": prediction.prediction_id,
        "observation_id": observation.observation_id,
        "status": status,
        "matched": matched,
        "residual": residual,
        "normalized_error": normalized_error,
        "prediction_contract_hash": prediction.contract_hash,
        "observation_receipt_hash": observation.receipt_hash,
        "observation_authenticity_proven": False,
        "live_observation_proven": False,
        "truth_proven": False,
        "reasons": tuple(reasons),
    }
    return OracleEvaluation(
        **payload,
        evaluation_hash=_sha(payload),
    )
