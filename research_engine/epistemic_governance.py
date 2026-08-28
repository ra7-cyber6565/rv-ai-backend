"""Deterministic epistemic governance for research conclusions.

This module turns several blueprint ideas into explicit fail-closed structures:
uncertainty decomposition (#84), hierarchical truth (#129), best-alternative
explanations (#130), what-would-change-my-mind (#131), evidence frontier
(#132), open questions (#134), personalized research standards (#138),
anti-confirmation (#140), measured-vs-inferred separation (#141), and the final
evidence packet (#142).

It does not create evidence.  It only classifies and gates supplied evidence,
contradictions, alternatives and uncertainty.  Confidence is never interpreted
as probability that a claim is true.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Sequence, Tuple


_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_ALLOWED_EPISTEMIC_TYPES = {
    "MEASURED",
    "OBSERVED",
    "DERIVED",
    "INFERRED",
    "LITERATURE_REPORT",
    "SPECULATIVE",
}
_MAX_ITEMS = 10_000


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is empty or invalid")
    return text


def _text(value: object, field: str, *, minimum: int = 3, maximum: int = 20_000) -> str:
    text = str(value or "").strip()
    if not minimum <= len(text) <= maximum:
        raise ValueError(f"{field} length is invalid")
    return text


def _unit_interval(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be finite and in [0,1]")
    return number


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
        raise ValueError("epistemic payload must be finite JSON-compatible data") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class UncertaintyDecomposition:
    measurement: float = 0.0
    sampling: float = 0.0
    model: float = 0.0
    epistemic: float = 0.0
    distribution_shift: float = 0.0
    unknown_unknown_allowance: float = 0.0

    def normalized(self) -> "UncertaintyDecomposition":
        values = {
            name: _unit_interval(getattr(self, name), f"uncertainty.{name}")
            for name in self.__dataclass_fields__
        }
        return UncertaintyDecomposition(**values)

    @property
    def combined_upper_bound(self) -> float:
        """Conservative bounded union; not a probability the claim is false."""
        normalized = self.normalized()
        survival = 1.0
        for name in normalized.__dataclass_fields__:
            survival *= 1.0 - float(getattr(normalized, name))
        return min(1.0, max(0.0, 1.0 - survival))


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    description: str
    epistemic_type: str
    source_id: str
    independent_group: str
    supports_claim: bool
    primary_source: bool = False

    def normalized(self) -> "EvidenceItem":
        epistemic_type = str(self.epistemic_type or "").strip().upper()
        if epistemic_type not in _ALLOWED_EPISTEMIC_TYPES:
            raise ValueError("unsupported epistemic_type")
        return EvidenceItem(
            evidence_id=_safe_id(self.evidence_id, "evidence_id"),
            description=_text(self.description, "description"),
            epistemic_type=epistemic_type,
            source_id=_safe_id(self.source_id, "source_id"),
            independent_group=_safe_id(self.independent_group, "independent_group"),
            supports_claim=bool(self.supports_claim),
            primary_source=bool(self.primary_source),
        )


@dataclass(frozen=True)
class AlternativeExplanation:
    alternative_id: str
    statement: str
    mechanism: str
    discriminating_predictions: Tuple[str, ...]
    evidence_fit: float
    contradiction_penalty: float = 0.0

    def normalized(self) -> "AlternativeExplanation":
        predictions = tuple(
            sorted({_text(item, "discriminating_prediction", minimum=5) for item in self.discriminating_predictions})
        )
        if not predictions:
            raise ValueError("alternative explanation needs a discriminating prediction")
        return AlternativeExplanation(
            alternative_id=_safe_id(self.alternative_id, "alternative_id"),
            statement=_text(self.statement, "alternative.statement", minimum=5),
            mechanism=_text(self.mechanism, "alternative.mechanism", minimum=5),
            discriminating_predictions=predictions,
            evidence_fit=_unit_interval(self.evidence_fit, "alternative.evidence_fit"),
            contradiction_penalty=_unit_interval(
                self.contradiction_penalty, "alternative.contradiction_penalty"
            ),
        )


@dataclass(frozen=True)
class ResearchStandard:
    min_supporting_evidence: int = 1
    min_primary_sources: int = 0
    min_independent_groups: int = 1
    require_disconfirming_search: bool = True
    require_falsifier: bool = True
    require_alternative_explanation: bool = True

    def normalized(self) -> "ResearchStandard":
        for name in (
            "min_supporting_evidence",
            "min_primary_sources",
            "min_independent_groups",
        ):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= _MAX_ITEMS:
                raise ValueError(f"{name} must be a bounded nonnegative integer")
        return self

    def tightened_by(self, personalized: "ResearchStandard") -> "ResearchStandard":
        """Personalization may tighten universal standards, never weaken them."""
        base = self.normalized()
        custom = personalized.normalized()
        return ResearchStandard(
            min_supporting_evidence=max(base.min_supporting_evidence, custom.min_supporting_evidence),
            min_primary_sources=max(base.min_primary_sources, custom.min_primary_sources),
            min_independent_groups=max(base.min_independent_groups, custom.min_independent_groups),
            require_disconfirming_search=(
                base.require_disconfirming_search or custom.require_disconfirming_search
            ),
            require_falsifier=base.require_falsifier or custom.require_falsifier,
            require_alternative_explanation=(
                base.require_alternative_explanation or custom.require_alternative_explanation
            ),
        )


@dataclass(frozen=True)
class ClaimAssessment:
    claim_id: str
    statement: str
    claim_epistemic_type: str
    hierarchical_status: str
    confidence: float
    uncertainty: UncertaintyDecomposition
    supporting_evidence_ids: Tuple[str, ...]
    contradicting_evidence_ids: Tuple[str, ...]
    independent_support_groups: Tuple[str, ...]
    primary_support_count: int
    alternatives: Tuple[AlternativeExplanation, ...]
    what_would_change_my_mind: Tuple[str, ...]
    evidence_frontier: Tuple[str, ...]
    open_questions: Tuple[str, ...]
    anti_confirmation_complete: bool
    standard_passed: bool
    blockers: Tuple[str, ...]
    assessment_hash: str
    confidence_is_truth_probability: bool = False
    truth_proven: bool = False


@dataclass(frozen=True)
class FinalEvidencePacket:
    packet_id: str
    assessments: Tuple[ClaimAssessment, ...]
    counts_by_hierarchical_status: Mapping[str, int]
    measured_claim_ids: Tuple[str, ...]
    inferred_claim_ids: Tuple[str, ...]
    unresolved_claim_ids: Tuple[str, ...]
    packet_hash: str
    all_standards_passed: bool
    truth_proven: bool = False


def _hierarchical_status(
    claim_type: str,
    support: Sequence[EvidenceItem],
    contradictions: Sequence[EvidenceItem],
) -> str:
    if not support:
        return "UNSUPPORTED"
    if contradictions:
        return "CONTESTED"
    types = {item.epistemic_type for item in support}
    independent_groups = {item.independent_group for item in support}
    if claim_type in {"MEASURED", "OBSERVED"} and types & {"MEASURED", "OBSERVED"}:
        return "MEASURED_OR_OBSERVED"
    if len(independent_groups) >= 2 and types & {"MEASURED", "OBSERVED", "LITERATURE_REPORT"}:
        return "SUPPORTED"
    if claim_type == "DERIVED":
        return "DERIVED"
    if claim_type in {"INFERRED", "LITERATURE_REPORT"}:
        return "INFERENCE_OR_REPORT"
    return "SPECULATIVE"


def assess_claim(
    *,
    claim_id: str,
    statement: str,
    claim_epistemic_type: str,
    confidence: float,
    uncertainty: UncertaintyDecomposition,
    evidence: Sequence[EvidenceItem],
    alternatives: Sequence[AlternativeExplanation] = (),
    what_would_change_my_mind: Sequence[str] = (),
    evidence_frontier: Sequence[str] = (),
    open_questions: Sequence[str] = (),
    disconfirming_search_performed: bool = False,
    standard: ResearchStandard = ResearchStandard(),
) -> ClaimAssessment:
    claim_id = _safe_id(claim_id, "claim_id")
    statement = _text(statement, "claim.statement", minimum=5)
    claim_type = str(claim_epistemic_type or "").strip().upper()
    if claim_type not in _ALLOWED_EPISTEMIC_TYPES:
        raise ValueError("unsupported claim_epistemic_type")
    confidence_value = _unit_interval(confidence, "confidence")
    uncertainty = uncertainty.normalized()
    standard = standard.normalized()

    if isinstance(evidence, (str, bytes, bytearray)) or not isinstance(evidence, Sequence):
        raise ValueError("evidence must be a finite sequence")
    if len(evidence) > _MAX_ITEMS:
        raise ValueError("evidence item limit exceeded")
    normalized_evidence = tuple(item.normalized() for item in evidence)
    ids = [item.evidence_id for item in normalized_evidence]
    if len(set(ids)) != len(ids):
        raise ValueError("evidence_id values must be unique")
    support = tuple(item for item in normalized_evidence if item.supports_claim)
    contradictions = tuple(item for item in normalized_evidence if not item.supports_claim)

    normalized_alternatives = tuple(
        sorted((item.normalized() for item in alternatives), key=lambda item: item.alternative_id)
    )
    if len({item.alternative_id for item in normalized_alternatives}) != len(normalized_alternatives):
        raise ValueError("alternative_id values must be unique")

    falsifiers = tuple(sorted({_text(item, "falsifier", minimum=5) for item in what_would_change_my_mind}))
    frontier = tuple(sorted({_text(item, "evidence_frontier", minimum=5) for item in evidence_frontier}))
    questions = tuple(sorted({_text(item, "open_question", minimum=5) for item in open_questions}))
    groups = tuple(sorted({item.independent_group for item in support}))
    primary_count = sum(1 for item in support if item.primary_source)

    blockers = []
    if len(support) < standard.min_supporting_evidence:
        blockers.append("insufficient_supporting_evidence")
    if primary_count < standard.min_primary_sources:
        blockers.append("insufficient_primary_sources")
    if len(groups) < standard.min_independent_groups:
        blockers.append("insufficient_independent_support")
    if standard.require_disconfirming_search and not disconfirming_search_performed:
        blockers.append("disconfirming_search_missing")
    if standard.require_falsifier and not falsifiers:
        blockers.append("what_would_change_my_mind_missing")
    if standard.require_alternative_explanation and not normalized_alternatives:
        blockers.append("alternative_explanation_missing")

    # A direct contradiction is not automatically false, but it must block an
    # unqualified complete assessment until surfaced/resolved.
    if contradictions:
        blockers.append("contradicting_evidence_present")
    status = _hierarchical_status(claim_type, support, contradictions)
    anti_confirmation_complete = bool(disconfirming_search_performed and (contradictions or normalized_alternatives))
    if standard.require_disconfirming_search and not anti_confirmation_complete:
        blockers.append("anti_confirmation_incomplete")

    blockers = sorted(set(blockers))
    payload = {
        "claim_id": claim_id,
        "statement": statement,
        "claim_epistemic_type": claim_type,
        "hierarchical_status": status,
        "confidence": confidence_value,
        "uncertainty": {
            name: getattr(uncertainty, name) for name in uncertainty.__dataclass_fields__
        },
        "supporting_evidence_ids": sorted(item.evidence_id for item in support),
        "contradicting_evidence_ids": sorted(item.evidence_id for item in contradictions),
        "independent_support_groups": groups,
        "primary_support_count": primary_count,
        "alternatives": [
            {
                "alternative_id": item.alternative_id,
                "statement": item.statement,
                "mechanism": item.mechanism,
                "discriminating_predictions": item.discriminating_predictions,
                "evidence_fit": item.evidence_fit,
                "contradiction_penalty": item.contradiction_penalty,
            }
            for item in normalized_alternatives
        ],
        "what_would_change_my_mind": falsifiers,
        "evidence_frontier": frontier,
        "open_questions": questions,
        "anti_confirmation_complete": anti_confirmation_complete,
        "blockers": blockers,
    }
    return ClaimAssessment(
        claim_id=claim_id,
        statement=statement,
        claim_epistemic_type=claim_type,
        hierarchical_status=status,
        confidence=confidence_value,
        uncertainty=uncertainty,
        supporting_evidence_ids=tuple(sorted(item.evidence_id for item in support)),
        contradicting_evidence_ids=tuple(sorted(item.evidence_id for item in contradictions)),
        independent_support_groups=groups,
        primary_support_count=primary_count,
        alternatives=normalized_alternatives,
        what_would_change_my_mind=falsifiers,
        evidence_frontier=frontier,
        open_questions=questions,
        anti_confirmation_complete=anti_confirmation_complete,
        standard_passed=not blockers,
        blockers=tuple(blockers),
        assessment_hash=_hash(payload),
    )


def build_final_evidence_packet(
    packet_id: str,
    assessments: Sequence[ClaimAssessment],
) -> FinalEvidencePacket:
    packet_id = _safe_id(packet_id, "packet_id")
    if isinstance(assessments, (str, bytes, bytearray)) or not isinstance(assessments, Sequence):
        raise ValueError("assessments must be a finite sequence")
    if not 1 <= len(assessments) <= _MAX_ITEMS:
        raise ValueError(f"assessments must contain 1..{_MAX_ITEMS} items")
    ordered = tuple(sorted(assessments, key=lambda item: item.claim_id))
    if len({item.claim_id for item in ordered}) != len(ordered):
        raise ValueError("claim_id values must be unique")

    counts: Dict[str, int] = {}
    measured = []
    inferred = []
    unresolved = []
    for item in ordered:
        counts[item.hierarchical_status] = counts.get(item.hierarchical_status, 0) + 1
        if item.claim_epistemic_type in {"MEASURED", "OBSERVED"}:
            measured.append(item.claim_id)
        elif item.claim_epistemic_type in {"INFERRED", "SPECULATIVE", "LITERATURE_REPORT"}:
            inferred.append(item.claim_id)
        if not item.standard_passed or item.hierarchical_status in {"UNSUPPORTED", "CONTESTED"}:
            unresolved.append(item.claim_id)

    payload = {
        "packet_id": packet_id,
        "assessment_hashes": [item.assessment_hash for item in ordered],
        "counts_by_hierarchical_status": dict(sorted(counts.items())),
        "measured_claim_ids": measured,
        "inferred_claim_ids": inferred,
        "unresolved_claim_ids": unresolved,
    }
    return FinalEvidencePacket(
        packet_id=packet_id,
        assessments=ordered,
        counts_by_hierarchical_status=dict(sorted(counts.items())),
        measured_claim_ids=tuple(measured),
        inferred_claim_ids=tuple(inferred),
        unresolved_claim_ids=tuple(unresolved),
        packet_hash=_hash(payload),
        all_standards_passed=all(item.standard_passed for item in ordered),
        truth_proven=False,
    )
