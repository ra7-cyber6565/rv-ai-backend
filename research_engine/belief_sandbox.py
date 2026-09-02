"""Isolated belief sandbox for capability #119.

Candidate beliefs may be explored without mutating canonical scientific memory.
Even a fully passing sandbox assessment only becomes *eligible for an explicit
promotion proposal*; this module never edits a canonical belief store itself.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Sequence, Tuple

_ID = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")


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


def _hash(value: Any) -> str:
    try:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("belief sandbox payload must be finite JSON-compatible data") from exc
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class CandidateBelief:
    belief_id: str
    statement: str
    evidence_ids: Tuple[str, ...]
    independent_groups: Tuple[str, ...]
    falsifier: str
    preregistered_predictions: Tuple[str, ...]
    resolved_predictions: int = 0
    falsification_attempts: int = 0
    contradictions: Tuple[str, ...] = ()


@dataclass(frozen=True)
class BeliefSandboxAssessment:
    belief_id: str
    blockers: Tuple[str, ...]
    promotion_proposal_eligible: bool
    sandbox_hash: str
    canonical_state_mutated: bool = False
    truth_proven: bool = False


def assess_sandbox_belief(
    belief: CandidateBelief,
    *,
    minimum_evidence: int = 2,
    minimum_independent_groups: int = 2,
    minimum_falsification_attempts: int = 1,
    minimum_resolved_predictions: int = 1,
) -> BeliefSandboxAssessment:
    belief_id = _id(belief.belief_id, "belief_id")
    statement = _text(belief.statement, "statement")
    evidence = tuple(sorted({_id(item, "evidence_id") for item in belief.evidence_ids}))
    groups = tuple(sorted({_id(item, "independent_group") for item in belief.independent_groups}))
    predictions = tuple(sorted({_text(item, "preregistered_prediction") for item in belief.preregistered_predictions}))
    contradictions = tuple(sorted({_text(item, "contradiction") for item in belief.contradictions}))
    falsifier = str(belief.falsifier or "").strip()

    for field, value in (
        ("minimum_evidence", minimum_evidence),
        ("minimum_independent_groups", minimum_independent_groups),
        ("minimum_falsification_attempts", minimum_falsification_attempts),
        ("minimum_resolved_predictions", minimum_resolved_predictions),
        ("resolved_predictions", belief.resolved_predictions),
        ("falsification_attempts", belief.falsification_attempts),
    ):
        if type(value) is not int or value < 0 or value > 1_000_000:
            raise ValueError(f"{field} must be a bounded nonnegative integer")
    if belief.resolved_predictions > len(predictions):
        raise ValueError("resolved_predictions cannot exceed preregistered predictions")

    blockers = []
    if len(evidence) < minimum_evidence:
        blockers.append("insufficient_evidence")
    if len(groups) < minimum_independent_groups:
        blockers.append("insufficient_independence")
    if len(falsifier) < 5:
        blockers.append("falsifier_missing")
    elif len(falsifier) > 20_000:
        raise ValueError("falsifier is too long")
    if not predictions:
        blockers.append("preregistered_prediction_missing")
    if belief.resolved_predictions < minimum_resolved_predictions:
        blockers.append("insufficient_resolved_predictions")
    if belief.falsification_attempts < minimum_falsification_attempts:
        blockers.append("insufficient_falsification_attempts")
    if contradictions:
        blockers.append("unresolved_contradictions")

    blockers = tuple(sorted(set(blockers)))
    payload = {
        "belief_id": belief_id,
        "statement": statement,
        "evidence": evidence,
        "groups": groups,
        "falsifier": falsifier,
        "predictions": predictions,
        "resolved_predictions": belief.resolved_predictions,
        "falsification_attempts": belief.falsification_attempts,
        "contradictions": contradictions,
        "blockers": blockers,
    }
    return BeliefSandboxAssessment(
        belief_id=belief_id,
        blockers=blockers,
        promotion_proposal_eligible=not blockers,
        sandbox_hash=_hash(payload),
        canonical_state_mutated=False,
        truth_proven=False,
    )
