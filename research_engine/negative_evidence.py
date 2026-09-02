"""Evidence-governance primitives for capabilities #81, #82 and #83.

The module makes three boundaries explicit:

* Anti-hallucination: a strong claim cannot cite unknown evidence IDs or promote
  missing/contradicted support merely because model confidence is high.
* Negative evidence: "we did not find it" is not automatically evidence that it
  does not exist. Evidence-of-absence requires a predeclared detection target,
  adequate search coverage/sensitivity and a genuinely negative observation.
* Null results: preregistered null/inconclusive outcomes are immutable research
  outcomes, not failures to be deleted or rewritten as positive findings.

None of these decisions establish universal truth.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Tuple


_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_ALLOWED_CLAIM_LEVELS = {"UNKNOWN", "HYPOTHESIS", "INFERRED", "SUPPORTED", "MEASURED"}
_ALLOWED_NULL_STATUS = {"NULL", "NEGATIVE", "INCONCLUSIVE"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _unit(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be finite and in [0,1]")
    return number


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


@dataclass(frozen=True)
class ClaimGroundingDecision:
    claim_id: str
    requested_level: str
    allowed_level: str
    cited_evidence_ids: Tuple[str, ...]
    verified_evidence_ids: Tuple[str, ...]
    missing_evidence_ids: Tuple[str, ...]
    contradictions_present: bool
    capture_integrity_passed: bool
    blocked: bool
    blockers: Tuple[str, ...]
    model_confidence_overrode_evidence: bool
    truth_proven: bool
    decision_hash: str


def anti_hallucination_gate(
    *,
    claim_id: str,
    requested_level: str,
    cited_evidence_ids: Sequence[str],
    verified_evidence_ids: Sequence[str],
    contradictions_present: bool,
    capture_integrity_passed: bool,
    model_confidence: float,
) -> ClaimGroundingDecision:
    claim_id = _safe_id(claim_id, "claim_id")
    requested = str(requested_level or "").strip().upper()
    if requested not in _ALLOWED_CLAIM_LEVELS:
        raise ValueError("unsupported requested claim level")
    _unit(model_confidence, "model_confidence")
    cited = tuple(sorted({_safe_id(x, "cited_evidence_id") for x in cited_evidence_ids}))
    verified = tuple(sorted({_safe_id(x, "verified_evidence_id") for x in verified_evidence_ids}))
    verified_set = set(verified)
    missing = tuple(sorted(set(cited) - verified_set))
    blockers = []
    if requested in {"SUPPORTED", "MEASURED"} and not cited:
        blockers.append("strong claim has no cited evidence")
    if missing:
        blockers.append("claim cites evidence that is not verified")
    if contradictions_present:
        blockers.append("contradictory evidence remains unresolved")
    if not capture_integrity_passed:
        blockers.append("capture/transformation integrity did not pass")

    if blockers:
        allowed = "HYPOTHESIS" if requested != "UNKNOWN" else "UNKNOWN"
    elif requested == "MEASURED":
        # This gate cannot itself prove direct measurement semantics; its ceiling
        # is SUPPORTED unless a separate measurement gate supplies that label.
        allowed = "SUPPORTED"
        blockers.append("direct measurement requires separate measurement proof")
    else:
        allowed = requested
    payload = {
        "claim_id": claim_id,
        "requested_level": requested,
        "allowed_level": allowed,
        "cited_evidence_ids": cited,
        "verified_evidence_ids": verified,
        "missing_evidence_ids": missing,
        "contradictions_present": bool(contradictions_present),
        "capture_integrity_passed": bool(capture_integrity_passed),
        "blocked": bool(blockers),
        "blockers": blockers,
        "model_confidence_overrode_evidence": False,
        "truth_proven": False,
    }
    return ClaimGroundingDecision(
        claim_id=claim_id,
        requested_level=requested,
        allowed_level=allowed,
        cited_evidence_ids=cited,
        verified_evidence_ids=verified,
        missing_evidence_ids=missing,
        contradictions_present=bool(contradictions_present),
        capture_integrity_passed=bool(capture_integrity_passed),
        blocked=bool(blockers),
        blockers=tuple(blockers),
        model_confidence_overrode_evidence=False,
        truth_proven=False,
        decision_hash=_sha(payload),
    )


@dataclass(frozen=True)
class NegativeEvidenceRecord:
    hypothesis_id: str
    target_observation: str
    search_scope: Tuple[str, ...]
    detection_sensitivity: float
    coverage_fraction: float
    negative_observation: bool
    evidence_of_absence_strength: float
    status: str
    reasons: Tuple[str, ...]
    universal_absence_proven: bool
    record_hash: str


def assess_negative_evidence(
    *,
    hypothesis_id: str,
    target_observation: str,
    search_scope: Sequence[str],
    detection_sensitivity: float,
    coverage_fraction: float,
    negative_observation: bool,
    minimum_sensitivity: float = 0.8,
    minimum_coverage: float = 0.8,
) -> NegativeEvidenceRecord:
    hypothesis_id = _safe_id(hypothesis_id, "hypothesis_id")
    target = str(target_observation or "").strip()
    if not target or len(target) > 2000:
        raise ValueError("target_observation is required and bounded")
    scope = tuple(sorted({_safe_id(x, "search_scope") for x in search_scope}))
    sensitivity = _unit(detection_sensitivity, "detection_sensitivity")
    coverage = _unit(coverage_fraction, "coverage_fraction")
    min_sensitivity = _unit(minimum_sensitivity, "minimum_sensitivity")
    min_coverage = _unit(minimum_coverage, "minimum_coverage")
    reasons = []
    if not scope:
        reasons.append("search scope was not declared")
    if not negative_observation:
        reasons.append("observation was not negative")
    if sensitivity < min_sensitivity:
        reasons.append("detection sensitivity is inadequate")
    if coverage < min_coverage:
        reasons.append("search coverage is inadequate")
    if reasons:
        status = "ABSENCE_OF_EVIDENCE_ONLY"
        strength = 0.0
    else:
        status = "BOUNDED_EVIDENCE_OF_ABSENCE"
        # Conservative product: weakness in either dimension sharply lowers the
        # bounded absence evidence. It is never converted into universal proof.
        strength = sensitivity * coverage
    payload = {
        "hypothesis_id": hypothesis_id,
        "target_observation": target,
        "search_scope": scope,
        "detection_sensitivity": sensitivity,
        "coverage_fraction": coverage,
        "negative_observation": bool(negative_observation),
        "evidence_of_absence_strength": strength,
        "status": status,
        "reasons": reasons,
        "universal_absence_proven": False,
    }
    return NegativeEvidenceRecord(
        hypothesis_id=hypothesis_id,
        target_observation=target,
        search_scope=scope,
        detection_sensitivity=sensitivity,
        coverage_fraction=coverage,
        negative_observation=bool(negative_observation),
        evidence_of_absence_strength=strength,
        status=status,
        reasons=tuple(reasons),
        universal_absence_proven=False,
        record_hash=_sha(payload),
    )


@dataclass(frozen=True)
class NullResult:
    experiment_id: str
    hypothesis_id: str
    protocol_hash: str
    metric: str
    effect_estimate: float
    interval_lower: float
    interval_upper: float
    smallest_effect_of_interest: float
    status: str
    adequately_sensitive: bool
    supports_positive_claim: bool
    proves_no_effect: bool
    result_hash: str


def preserve_null_result(
    *,
    experiment_id: str,
    hypothesis_id: str,
    protocol_hash: str,
    metric: str,
    effect_estimate: float,
    interval_lower: float,
    interval_upper: float,
    smallest_effect_of_interest: float,
) -> NullResult:
    experiment_id = _safe_id(experiment_id, "experiment_id")
    hypothesis_id = _safe_id(hypothesis_id, "hypothesis_id")
    protocol_hash = str(protocol_hash or "").strip().lower()
    if len(protocol_hash) != 64 or any(ch not in "0123456789abcdef" for ch in protocol_hash):
        raise ValueError("protocol_hash must be SHA-256")
    metric = str(metric or "").strip()
    if not metric or len(metric) > 200:
        raise ValueError("metric is required and bounded")
    effect = _finite(effect_estimate, "effect_estimate")
    lower = _finite(interval_lower, "interval_lower")
    upper = _finite(interval_upper, "interval_upper")
    smallest = _finite(smallest_effect_of_interest, "smallest_effect_of_interest")
    if lower > upper:
        raise ValueError("interval_lower must be <= interval_upper")
    if smallest <= 0:
        raise ValueError("smallest_effect_of_interest must be > 0")
    if not lower <= effect <= upper:
        raise ValueError("effect_estimate must lie inside its interval")

    # If the entire interval is inside the predeclared negligible-effect band,
    # this is a bounded negative result. If zero is included but meaningful
    # effects are still compatible, it is a null/inconclusive result.
    negligible = lower >= -smallest and upper <= smallest
    includes_zero = lower <= 0.0 <= upper
    if negligible:
        status = "NEGATIVE"
        adequately_sensitive = True
    elif includes_zero:
        status = "NULL"
        adequately_sensitive = False
    else:
        status = "INCONCLUSIVE"
        adequately_sensitive = False
    if status not in _ALLOWED_NULL_STATUS:
        raise RuntimeError("internal null-result status error")
    payload = {
        "experiment_id": experiment_id,
        "hypothesis_id": hypothesis_id,
        "protocol_hash": protocol_hash,
        "metric": metric,
        "effect_estimate": effect,
        "interval_lower": lower,
        "interval_upper": upper,
        "smallest_effect_of_interest": smallest,
        "status": status,
        "adequately_sensitive": adequately_sensitive,
        "supports_positive_claim": False,
        "proves_no_effect": False,
    }
    return NullResult(
        experiment_id=experiment_id,
        hypothesis_id=hypothesis_id,
        protocol_hash=protocol_hash,
        metric=metric,
        effect_estimate=effect,
        interval_lower=lower,
        interval_upper=upper,
        smallest_effect_of_interest=smallest,
        status=status,
        adequately_sensitive=adequately_sensitive,
        supports_positive_claim=False,
        proves_no_effect=False,
        result_hash=_sha(payload),
    )
