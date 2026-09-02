"""Epistemic claim-insurance gate for capability #95.

This is not monetary insurance and never guarantees truth.  It makes risky
research claims carry an explicit downside contract: independent evidence,
falsifier, revalidation trigger, monitoring signal and rollback/containment plan.
The higher the declared impact, the stricter the minimum evidence floor.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Sequence, Tuple

_ID = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_MAX_ITEMS = 4096


def _id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID.fullmatch(text):
        raise ValueError(f"{field} is empty or invalid")
    return text


def _text(value: object, field: str, minimum: int = 5) -> str:
    text = str(value or "").strip()
    if len(text) < minimum or len(text) > 20_000:
        raise ValueError(f"{field} length is invalid")
    return text


def _unit(value: object, field: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be finite and in [0,1]")
    return number


def _hash(value: Any) -> str:
    try:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("claim-insurance payload must be finite JSON-compatible data") from exc
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class ClaimInsuranceInput:
    claim_id: str
    statement: str
    impact_if_wrong: float
    supporting_evidence_ids: Tuple[str, ...]
    independent_groups: Tuple[str, ...]
    uncertainty_upper_bound: float
    falsifier: str
    revalidation_trigger: str
    monitoring_signal: str
    rollback_plan: str
    strong_label_requested: bool = True


@dataclass(frozen=True)
class ClaimInsuranceAssessment:
    claim_id: str
    impact_if_wrong: float
    required_support_count: int
    required_independent_groups: int
    blockers: Tuple[str, ...]
    eligible_for_operational_reliance: bool
    strong_label_allowed_by_insurance_gate: bool
    assessment_hash: str
    truth_guaranteed: bool = False
    monetary_insurance: bool = False


def assess_claim_insurance(item: ClaimInsuranceInput) -> ClaimInsuranceAssessment:
    claim_id = _id(item.claim_id, "claim_id")
    statement = _text(item.statement, "statement")
    impact = _unit(item.impact_if_wrong, "impact_if_wrong")
    uncertainty = _unit(item.uncertainty_upper_bound, "uncertainty_upper_bound")

    evidence = tuple(sorted({_id(value, "supporting_evidence_id") for value in item.supporting_evidence_ids}))
    groups = tuple(sorted({_id(value, "independent_group") for value in item.independent_groups}))
    if len(evidence) > _MAX_ITEMS or len(groups) > _MAX_ITEMS:
        raise ValueError("claim-insurance evidence budget exceeded")

    # Impact-adaptive minimums; deliberately discrete and auditable.
    if impact >= 0.8:
        required_support, required_groups, max_uncertainty = 3, 2, 0.25
    elif impact >= 0.5:
        required_support, required_groups, max_uncertainty = 2, 2, 0.40
    else:
        required_support, required_groups, max_uncertainty = 1, 1, 0.60

    blockers = []
    if len(evidence) < required_support:
        blockers.append("insufficient_supporting_evidence")
    if len(groups) < required_groups:
        blockers.append("insufficient_independent_evidence")
    if uncertainty > max_uncertainty:
        blockers.append("uncertainty_exceeds_impact_tolerance")

    required_text = (
        ("falsifier_missing", item.falsifier),
        ("revalidation_trigger_missing", item.revalidation_trigger),
        ("monitoring_signal_missing", item.monitoring_signal),
        ("rollback_plan_missing", item.rollback_plan),
    )
    normalized_text = {}
    for blocker, value in required_text:
        text = str(value or "").strip()
        normalized_text[blocker] = text
        if len(text) < 5:
            blockers.append(blocker)
        elif len(text) > 20_000:
            raise ValueError(f"{blocker} text is too long")

    blockers = tuple(sorted(set(blockers)))
    eligible = not blockers
    strong_allowed = bool(item.strong_label_requested and eligible)
    payload = {
        "claim_id": claim_id,
        "statement": statement,
        "impact": impact,
        "evidence": evidence,
        "groups": groups,
        "uncertainty": uncertainty,
        "required_support": required_support,
        "required_groups": required_groups,
        "falsifier": normalized_text["falsifier_missing"],
        "revalidation": normalized_text["revalidation_trigger_missing"],
        "monitoring": normalized_text["monitoring_signal_missing"],
        "rollback": normalized_text["rollback_plan_missing"],
        "blockers": blockers,
        "eligible": eligible,
    }
    return ClaimInsuranceAssessment(
        claim_id=claim_id,
        impact_if_wrong=impact,
        required_support_count=required_support,
        required_independent_groups=required_groups,
        blockers=blockers,
        eligible_for_operational_reliance=eligible,
        strong_label_allowed_by_insurance_gate=strong_allowed,
        assessment_hash=_hash(payload),
        truth_guaranteed=False,
        monetary_insurance=False,
    )
