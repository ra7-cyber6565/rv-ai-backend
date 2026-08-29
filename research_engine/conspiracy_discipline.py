"""Neutral conspiracy-hypothesis discipline for capability #120.

This module does not classify prose as a conspiracy theory and does not censor a
hypothesis.  It evaluates an explicitly selected hypothesis lane using the same
scientific obligations as any extraordinary causal claim: precise mechanism,
falsifier, preregistered prediction, disconfirming search, provenance-aware
independent evidence and no inference that mere absence of evidence proves the
claim.
"""
from __future__ import annotations

import hashlib
import json
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
        raise ValueError("hypothesis-discipline payload must be finite JSON-compatible data") from exc
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class HypothesisEvidence:
    evidence_id: str
    source_id: str
    independence_group: str
    supports: bool
    direct_observation: bool = False
    absence_of_expected_evidence: bool = False
    provenance_complete: bool = True

    def normalized(self) -> "HypothesisEvidence":
        return HypothesisEvidence(
            evidence_id=_id(self.evidence_id, "evidence_id"),
            source_id=_id(self.source_id, "source_id"),
            independence_group=_id(self.independence_group, "independence_group"),
            supports=bool(self.supports),
            direct_observation=bool(self.direct_observation),
            absence_of_expected_evidence=bool(self.absence_of_expected_evidence),
            provenance_complete=bool(self.provenance_complete),
        )


@dataclass(frozen=True)
class ConspiracyHypothesisInput:
    hypothesis_id: str
    statement: str
    mechanism: str
    falsifier: str
    preregistered_predictions: Tuple[str, ...]
    evidence: Tuple[HypothesisEvidence, ...]
    disconfirming_search_performed: bool
    alternative_explanations_considered: Tuple[str, ...]


@dataclass(frozen=True)
class ConspiracyDisciplineAssessment:
    hypothesis_id: str
    independent_support_groups: int
    independent_contradiction_groups: int
    blockers: Tuple[str, ...]
    eligible_for_neutral_research: bool
    eligible_for_strong_label: bool
    assessment_hash: str
    absence_of_evidence_treated_as_proof: bool = False
    truth_proven: bool = False


def assess_conspiracy_hypothesis(
    item: ConspiracyHypothesisInput,
    *,
    minimum_independent_support_groups: int = 2,
) -> ConspiracyDisciplineAssessment:
    hypothesis_id = _id(item.hypothesis_id, "hypothesis_id")
    statement = _text(item.statement, "statement")
    mechanism = str(item.mechanism or "").strip()
    falsifier = str(item.falsifier or "").strip()
    predictions = tuple(sorted({_text(value, "preregistered_prediction") for value in item.preregistered_predictions}))
    alternatives = tuple(sorted({_text(value, "alternative_explanation") for value in item.alternative_explanations_considered}))
    if type(minimum_independent_support_groups) is not int or not 1 <= minimum_independent_support_groups <= 100:
        raise ValueError("minimum_independent_support_groups must be 1..100")

    evidence = tuple(row.normalized() for row in item.evidence)
    ids = [row.evidence_id for row in evidence]
    if len(ids) != len(set(ids)):
        raise ValueError("evidence_id values must be unique")
    source_ids = [row.source_id for row in evidence]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("one source cannot be duplicated as independent evidence")

    # Evidence whose entire force is "we expected evidence but did not see it"
    # remains diagnostically useful, but never counts as positive support.
    positive = tuple(
        row for row in evidence
        if row.supports
        and row.provenance_complete
        and not row.absence_of_expected_evidence
    )
    contradictions = tuple(
        row for row in evidence
        if not row.supports and row.provenance_complete
    )
    support_groups = {row.independence_group for row in positive}
    contradiction_groups = {row.independence_group for row in contradictions}

    blockers = []
    if len(mechanism) < 5:
        blockers.append("mechanism_missing")
    elif len(mechanism) > 20_000:
        raise ValueError("mechanism is too long")
    if len(falsifier) < 5:
        blockers.append("falsifier_missing")
    elif len(falsifier) > 20_000:
        raise ValueError("falsifier is too long")
    if not predictions:
        blockers.append("preregistered_prediction_missing")
    if not item.disconfirming_search_performed:
        blockers.append("disconfirming_search_missing")
    if not alternatives:
        blockers.append("alternative_explanation_missing")
    if len(support_groups) < minimum_independent_support_groups:
        blockers.append("insufficient_independent_support")
    if any(not row.provenance_complete for row in evidence):
        blockers.append("incomplete_provenance_present")
    if contradictions:
        blockers.append("contradicting_evidence_present")

    blockers = tuple(sorted(set(blockers)))
    # Neutral research remains allowed even when strong-label criteria fail.
    eligible_for_research = bool(statement)
    strong = not blockers
    payload = {
        "hypothesis_id": hypothesis_id,
        "statement": statement,
        "mechanism": mechanism,
        "falsifier": falsifier,
        "predictions": predictions,
        "alternatives": alternatives,
        "support_groups": sorted(support_groups),
        "contradiction_groups": sorted(contradiction_groups),
        "disconfirming_search": bool(item.disconfirming_search_performed),
        "blockers": blockers,
    }
    return ConspiracyDisciplineAssessment(
        hypothesis_id=hypothesis_id,
        independent_support_groups=len(support_groups),
        independent_contradiction_groups=len(contradiction_groups),
        blockers=blockers,
        eligible_for_neutral_research=eligible_for_research,
        eligible_for_strong_label=strong,
        assessment_hash=_hash(payload),
        absence_of_evidence_treated_as_proof=False,
        truth_proven=False,
    )
