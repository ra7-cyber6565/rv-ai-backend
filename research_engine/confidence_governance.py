"""Domain-specific calibration and confidence-is-not-truth governance.

Capabilities:
* #43 Domain-Specific Confidence
* #44 Confidence Is Not Truth

The engine learns calibration diagnostics separately per domain from resolved
predictions. It never treats a numeric score as probability that a claim is
true. Sparse/unknown domains are explicitly uncalibrated and are shrunk toward
an empirical prior rather than borrowing confidence from unrelated domains.

The claim-strength gate is orthogonal to calibration: high confidence cannot
upgrade a claim past missing evidence, contradictions, missing independent
validation or an inference/measurement boundary.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


_DOMAIN_RE = re.compile(r"^[A-Za-z0-9_.:/+~-]{1,120}$")
_MAX_SAMPLES = 1_000_000
_ALLOWED_EPISTEMIC = {"UNKNOWN", "HYPOTHESIS", "INFERRED", "SUPPORTED", "MEASURED"}


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


def _probability(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be finite and in [0,1]")
    return number


def _domain(value: object) -> str:
    text = str(value or "").strip().lower()
    if not _DOMAIN_RE.fullmatch(text):
        raise ValueError("domain is invalid")
    return text


@dataclass(frozen=True)
class CalibrationSample:
    domain: str
    predicted_confidence: float
    outcome: bool
    sample_id: str = ""

    def normalized(self) -> "CalibrationSample":
        domain = _domain(self.domain)
        confidence = _probability(self.predicted_confidence, "predicted_confidence")
        sample_id = str(self.sample_id or "").strip()
        if sample_id and (len(sample_id) > 200 or any(ch.isspace() for ch in sample_id)):
            raise ValueError("sample_id is invalid")
        return CalibrationSample(domain, confidence, bool(self.outcome), sample_id)


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_prediction: float
    observed_rate: float
    absolute_gap: float


@dataclass(frozen=True)
class DomainCalibrationProfile:
    domain: str
    sample_count: int
    base_rate: float
    brier_score: float
    expected_calibration_error: float
    bins: Tuple[CalibrationBin, ...]
    status: str
    profile_hash: str
    truth_probability_interpretation_allowed: bool = False


@dataclass(frozen=True)
class CalibratedConfidence:
    domain: str
    raw_score: float
    calibrated_score: float
    profile_status: str
    sample_count: int
    local_bin_count: int
    empirical_bin_rate: Optional[float]
    shrinkage_weight: float
    confidence_is_truth_probability: bool
    reasons: Tuple[str, ...]
    calibration_hash: str


@dataclass(frozen=True)
class ClaimStrengthDecision:
    requested_epistemic_level: str
    allowed_epistemic_level: str
    confidence_score: float
    evidence_sufficient: bool
    independent_validation: bool
    measured_directly: bool
    contradictions_present: bool
    blocked: bool
    blockers: Tuple[str, ...]
    confidence_upgraded_claim: bool
    truth_proven: bool
    decision_hash: str


def fit_domain_profiles(
    samples: Sequence[CalibrationSample],
    *,
    bins: int = 10,
    minimum_domain_samples: int = 20,
) -> Mapping[str, DomainCalibrationProfile]:
    if isinstance(samples, (str, bytes, bytearray)) or not isinstance(samples, Sequence):
        raise ValueError("samples must be a finite sequence")
    if not 1 <= len(samples) <= _MAX_SAMPLES:
        raise ValueError("samples must contain 1..1,000,000 items")
    if type(bins) is not int or not 2 <= bins <= 100:
        raise ValueError("bins must be an integer in [2,100]")
    if type(minimum_domain_samples) is not int or not 1 <= minimum_domain_samples <= _MAX_SAMPLES:
        raise ValueError("minimum_domain_samples is invalid")

    grouped: Dict[str, list[CalibrationSample]] = {}
    ids = set()
    for raw in samples:
        if not isinstance(raw, CalibrationSample):
            raise ValueError("samples must contain CalibrationSample objects")
        sample = raw.normalized()
        if sample.sample_id:
            if sample.sample_id in ids:
                raise ValueError("sample_id values must be unique")
            ids.add(sample.sample_id)
        grouped.setdefault(sample.domain, []).append(sample)

    profiles: Dict[str, DomainCalibrationProfile] = {}
    for domain, rows in sorted(grouped.items()):
        count = len(rows)
        base_rate = sum(1.0 if row.outcome else 0.0 for row in rows) / count
        brier = sum((row.predicted_confidence - (1.0 if row.outcome else 0.0)) ** 2 for row in rows) / count
        bin_rows = []
        weighted_gap = 0.0
        for index in range(bins):
            lower = index / bins
            upper = (index + 1) / bins
            selected = [
                row for row in rows
                if (lower <= row.predicted_confidence < upper)
                or (index == bins - 1 and row.predicted_confidence == 1.0)
            ]
            if not selected:
                continue
            mean_prediction = sum(row.predicted_confidence for row in selected) / len(selected)
            observed_rate = sum(1.0 if row.outcome else 0.0 for row in selected) / len(selected)
            gap = abs(mean_prediction - observed_rate)
            weighted_gap += gap * len(selected) / count
            bin_rows.append(CalibrationBin(
                lower=lower,
                upper=upper,
                count=len(selected),
                mean_prediction=mean_prediction,
                observed_rate=observed_rate,
                absolute_gap=gap,
            ))
        status = "CALIBRATED_HISTORY" if count >= minimum_domain_samples else "SPARSE_HISTORY"
        payload = {
            "domain": domain,
            "sample_count": count,
            "base_rate": base_rate,
            "brier_score": brier,
            "expected_calibration_error": weighted_gap,
            "bins": [bin_.__dict__ for bin_ in bin_rows],
            "status": status,
            "truth_probability_interpretation_allowed": False,
        }
        profiles[domain] = DomainCalibrationProfile(
            domain=domain,
            sample_count=count,
            base_rate=base_rate,
            brier_score=brier,
            expected_calibration_error=weighted_gap,
            bins=tuple(bin_rows),
            status=status,
            profile_hash=_sha(payload),
        )
    return profiles


def calibrate_domain_confidence(
    raw_score: float,
    domain: str,
    profiles: Mapping[str, DomainCalibrationProfile],
    *,
    shrinkage_strength: float = 20.0,
) -> CalibratedConfidence:
    raw = _probability(raw_score, "raw_score")
    domain = _domain(domain)
    shrinkage_strength = float(shrinkage_strength)
    if not math.isfinite(shrinkage_strength) or shrinkage_strength <= 0:
        raise ValueError("shrinkage_strength must be finite and > 0")
    profile = profiles.get(domain)
    if profile is None:
        payload = {
            "domain": domain,
            "raw_score": raw,
            "calibrated_score": 0.5,
            "profile_status": "NO_DOMAIN_HISTORY",
            "sample_count": 0,
            "local_bin_count": 0,
            "empirical_bin_rate": None,
            "shrinkage_weight": 0.0,
            "confidence_is_truth_probability": False,
            "reasons": ["no domain-specific resolved prediction history"],
        }
        return CalibratedConfidence(
            domain=domain,
            raw_score=raw,
            calibrated_score=0.5,
            profile_status="NO_DOMAIN_HISTORY",
            sample_count=0,
            local_bin_count=0,
            empirical_bin_rate=None,
            shrinkage_weight=0.0,
            confidence_is_truth_probability=False,
            reasons=("no domain-specific resolved prediction history",),
            calibration_hash=_sha(payload),
        )

    local = None
    for bin_ in profile.bins:
        if bin_.lower <= raw < bin_.upper or (raw == 1.0 and bin_.upper == 1.0):
            local = bin_
            break
    local_count = local.count if local is not None else 0
    empirical = local.observed_rate if local is not None else profile.base_rate
    weight = local_count / (local_count + shrinkage_strength)
    # The empirical local rate informs calibration but never becomes a truth
    # probability claim. Sparse bins remain strongly shrunk toward domain base.
    local_target = weight * empirical + (1.0 - weight) * profile.base_rate
    history_weight = profile.sample_count / (profile.sample_count + shrinkage_strength)
    calibrated = history_weight * local_target + (1.0 - history_weight) * 0.5
    calibrated = min(1.0, max(0.0, calibrated))
    reasons = []
    if profile.status == "SPARSE_HISTORY":
        reasons.append("domain history is sparse; score remains heavily shrunk")
    if local is None:
        reasons.append("raw score bin has no resolved samples; used domain base rate")
    payload = {
        "domain": domain,
        "raw_score": raw,
        "calibrated_score": calibrated,
        "profile_status": profile.status,
        "sample_count": profile.sample_count,
        "local_bin_count": local_count,
        "empirical_bin_rate": empirical,
        "shrinkage_weight": weight,
        "confidence_is_truth_probability": False,
        "reasons": reasons,
    }
    return CalibratedConfidence(
        domain=domain,
        raw_score=raw,
        calibrated_score=calibrated,
        profile_status=profile.status,
        sample_count=profile.sample_count,
        local_bin_count=local_count,
        empirical_bin_rate=empirical,
        shrinkage_weight=weight,
        confidence_is_truth_probability=False,
        reasons=tuple(reasons),
        calibration_hash=_sha(payload),
    )


def gate_claim_strength(
    *,
    requested_epistemic_level: str,
    confidence_score: float,
    evidence_sufficient: bool,
    independent_validation: bool,
    measured_directly: bool,
    contradictions_present: bool,
) -> ClaimStrengthDecision:
    requested = str(requested_epistemic_level or "").strip().upper()
    if requested not in _ALLOWED_EPISTEMIC:
        raise ValueError("unsupported requested_epistemic_level")
    confidence = _probability(confidence_score, "confidence_score")
    blockers = []
    if not evidence_sufficient:
        blockers.append("evidence_insufficient")
    if contradictions_present:
        blockers.append("contradictions_unresolved")

    if blockers:
        allowed = "HYPOTHESIS" if requested != "UNKNOWN" else "UNKNOWN"
    elif measured_directly:
        allowed = requested if requested in {"UNKNOWN", "HYPOTHESIS", "INFERRED", "SUPPORTED", "MEASURED"} else "MEASURED"
    elif requested == "MEASURED":
        allowed = "SUPPORTED" if independent_validation else "INFERRED"
        blockers.append("direct_measurement_missing")
    elif requested == "SUPPORTED" and not independent_validation:
        allowed = "INFERRED"
        blockers.append("independent_validation_missing")
    else:
        allowed = requested

    # Confidence is advisory calibration metadata only. It never removes any
    # blocker and never lifts ``allowed`` above evidence-derived constraints.
    payload = {
        "requested_epistemic_level": requested,
        "allowed_epistemic_level": allowed,
        "confidence_score": confidence,
        "evidence_sufficient": bool(evidence_sufficient),
        "independent_validation": bool(independent_validation),
        "measured_directly": bool(measured_directly),
        "contradictions_present": bool(contradictions_present),
        "blocked": bool(blockers),
        "blockers": sorted(set(blockers)),
        "confidence_upgraded_claim": False,
        "truth_proven": False,
    }
    return ClaimStrengthDecision(
        requested_epistemic_level=requested,
        allowed_epistemic_level=allowed,
        confidence_score=confidence,
        evidence_sufficient=bool(evidence_sufficient),
        independent_validation=bool(independent_validation),
        measured_directly=bool(measured_directly),
        contradictions_present=bool(contradictions_present),
        blocked=bool(blockers),
        blockers=tuple(sorted(set(blockers))),
        confidence_upgraded_claim=False,
        truth_proven=False,
        decision_hash=_sha(payload),
    )
