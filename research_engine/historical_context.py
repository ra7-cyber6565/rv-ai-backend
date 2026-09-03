"""Fail-closed historical-context reasoning for blueprint capability #104.

The engine operates only on explicit structured chronology.  It never extracts
an event date, an actor's knowledge, or a period concept from free-form prose.
Its job is to prevent common historical reasoning errors:

* collapse of uncertain date ranges into invented exact dates;
* hindsight leakage (later evidence attributed to an earlier actor);
* impossible causal chronology (a cause wholly after its alleged outcome);
* presentism/anachronism (a concept attributed before explicit period evidence);
* retrospective scholarship being counted as contemporary eyewitness evidence;
* duplicated/dependent sources inflating historiographic agreement.

A clean audit is not proof that a historical claim is true.  It means only that
these bounded temporal/contextual checks did not find a specified contradiction.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple


_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_MAX_ITEMS = 20_000
_ALLOWED_POSITIONS = {"SUPPORT", "CHALLENGE", "NEUTRAL", "UNKNOWN"}


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
        raise ValueError("historical payload must be finite JSON-compatible data") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _text(value: object, field: str, *, minimum: int = 2, maximum: int = 12_000) -> str:
    text = " ".join(str(value or "").split())
    if not minimum <= len(text) <= maximum:
        raise ValueError(f"{field} length is invalid")
    return text


def _year(value: object, field: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{field} must be an integer astronomical year")
    if not -20_000 <= value <= 20_000:
        raise ValueError(f"{field} is outside supported chronology bounds")
    return value


@dataclass(frozen=True)
class YearRange:
    earliest: int
    latest: int

    def normalized(self) -> "YearRange":
        start = _year(self.earliest, "earliest")
        end = _year(self.latest, "latest")
        if start > end:
            raise ValueError("earliest cannot be later than latest")
        return YearRange(start, end)

    @property
    def exact(self) -> bool:
        normalized = self.normalized()
        return normalized.earliest == normalized.latest


@dataclass(frozen=True)
class HistoricalEvent:
    event_id: str
    label: str
    when: YearRange

    def normalized(self) -> "HistoricalEvent":
        return HistoricalEvent(
            event_id=_safe_id(self.event_id, "event_id"),
            label=_text(self.label, "event.label", minimum=3),
            when=self.when.normalized(),
        )


@dataclass(frozen=True)
class HistoricalSourceEvidence:
    source_id: str
    publication_year: int
    independence_group: str
    evidence_ref: str
    position: str = "UNKNOWN"
    primary_source: bool = False
    provenance_complete: bool = True
    describes_event_id: str = ""

    def normalized(self) -> "HistoricalSourceEvidence":
        position = str(self.position or "").strip().upper()
        if position not in _ALLOWED_POSITIONS:
            raise ValueError("unsupported historiographic position")
        event_id = str(self.describes_event_id or "").strip()
        if event_id:
            event_id = _safe_id(event_id, "describes_event_id")
        return HistoricalSourceEvidence(
            source_id=_safe_id(self.source_id, "source_id"),
            publication_year=_year(self.publication_year, "publication_year"),
            independence_group=_safe_id(self.independence_group, "independence_group"),
            evidence_ref=_text(self.evidence_ref, "evidence_ref", minimum=1, maximum=2_000),
            position=position,
            primary_source=bool(self.primary_source),
            provenance_complete=bool(self.provenance_complete),
            describes_event_id=event_id,
        )


@dataclass(frozen=True)
class ActorKnowledgeClaim:
    claim_id: str
    actor_id: str
    statement: str
    knowledge_cutoff_year: int
    evidence_source_ids: Tuple[str, ...]

    def normalized(self) -> "ActorKnowledgeClaim":
        ids = tuple(sorted({_safe_id(item, "evidence_source_id") for item in self.evidence_source_ids}))
        if not ids:
            raise ValueError("actor knowledge claim needs evidence_source_ids")
        return ActorKnowledgeClaim(
            claim_id=_safe_id(self.claim_id, "claim_id"),
            actor_id=_safe_id(self.actor_id, "actor_id"),
            statement=_text(self.statement, "knowledge.statement", minimum=5),
            knowledge_cutoff_year=_year(self.knowledge_cutoff_year, "knowledge_cutoff_year"),
            evidence_source_ids=ids,
        )


@dataclass(frozen=True)
class CausalHistoricalFactor:
    factor_id: str
    label: str
    active_when: YearRange
    alleged_outcome_event_id: str

    def normalized(self) -> "CausalHistoricalFactor":
        return CausalHistoricalFactor(
            factor_id=_safe_id(self.factor_id, "factor_id"),
            label=_text(self.label, "factor.label", minimum=3),
            active_when=self.active_when.normalized(),
            alleged_outcome_event_id=_safe_id(self.alleged_outcome_event_id, "alleged_outcome_event_id"),
        )


@dataclass(frozen=True)
class PeriodConceptClaim:
    concept_id: str
    concept: str
    attribution_event_id: str
    contemporary_evidence_source_ids: Tuple[str, ...]

    def normalized(self) -> "PeriodConceptClaim":
        ids = tuple(sorted({_safe_id(item, "contemporary_evidence_source_id") for item in self.contemporary_evidence_source_ids}))
        return PeriodConceptClaim(
            concept_id=_safe_id(self.concept_id, "concept_id"),
            concept=_text(self.concept, "concept", minimum=3),
            attribution_event_id=_safe_id(self.attribution_event_id, "attribution_event_id"),
            contemporary_evidence_source_ids=ids,
        )


def temporal_relation(left: YearRange, right: YearRange) -> str:
    """Return a range-safe relation without inventing an exact chronology."""
    a, b = left.normalized(), right.normalized()
    if a.latest < b.earliest:
        return "BEFORE"
    if a.earliest > b.latest:
        return "AFTER"
    if a.earliest == b.earliest and a.latest == b.latest:
        return "SAME_RANGE"
    return "OVERLAP_OR_INDETERMINATE"


def classify_source_for_event(source: HistoricalSourceEvidence, event: HistoricalEvent) -> Dict[str, Any]:
    s, e = source.normalized(), event.normalized()
    if s.publication_year < e.when.earliest:
        temporal_class = "PRE_EVENT"
    elif s.publication_year <= e.when.latest:
        temporal_class = "CONTEMPORARY_OR_DURING_EVENT"
    else:
        temporal_class = "RETROSPECTIVE"
    return {
        "source_id": s.source_id,
        "event_id": e.event_id,
        "temporal_class": temporal_class,
        "publication_year": s.publication_year,
        "event_range": [e.when.earliest, e.when.latest],
        "primary_source": s.primary_source,
        "provenance_complete": s.provenance_complete,
        "truth_proven": False,
    }


def audit_actor_knowledge(
    claim: ActorKnowledgeClaim,
    sources: Sequence[HistoricalSourceEvidence],
) -> Dict[str, Any]:
    item = claim.normalized()
    by_id = {source.normalized().source_id: source.normalized() for source in sources}
    missing = tuple(source_id for source_id in item.evidence_source_ids if source_id not in by_id)
    eligible = []
    hindsight = []
    incomplete = []
    for source_id in item.evidence_source_ids:
        source = by_id.get(source_id)
        if source is None:
            continue
        if not source.provenance_complete:
            incomplete.append(source_id)
            continue
        if source.publication_year > item.knowledge_cutoff_year:
            hindsight.append(source_id)
        else:
            eligible.append(source_id)
    passed = bool(eligible and not missing and not incomplete)
    payload = {
        "claim_id": item.claim_id,
        "actor_id": item.actor_id,
        "knowledge_cutoff_year": item.knowledge_cutoff_year,
        "eligible_contemporary_evidence": sorted(eligible),
        "hindsight_only_evidence": sorted(hindsight),
        "missing_evidence": sorted(missing),
        "incomplete_provenance": sorted(incomplete),
        "actor_knowledge_gate_passed": passed,
        "later_sources_may_inform_present_interpretation": True,
        "later_sources_can_prove_actor_knew_it": False,
        "truth_proven": False,
    }
    return {**payload, "audit_hash": _hash(payload)}


def audit_causal_chronology(
    factor: CausalHistoricalFactor,
    outcome: HistoricalEvent,
) -> Dict[str, Any]:
    cause, event = factor.normalized(), outcome.normalized()
    if cause.alleged_outcome_event_id != event.event_id:
        raise ValueError("factor outcome id does not match supplied event")
    relation = temporal_relation(cause.active_when, event.when)
    impossible = cause.active_when.earliest > event.when.latest
    indeterminate = not impossible and relation in {"OVERLAP_OR_INDETERMINATE", "SAME_RANGE"}
    payload = {
        "factor_id": cause.factor_id,
        "event_id": event.event_id,
        "factor_range": [cause.active_when.earliest, cause.active_when.latest],
        "event_range": [event.when.earliest, event.when.latest],
        "temporal_relation": relation,
        "impossible_causal_order": impossible,
        "chronology_indeterminate": indeterminate,
        "causality_proven": False,
    }
    return {**payload, "audit_hash": _hash(payload)}


def audit_period_concept(
    claim: PeriodConceptClaim,
    event: HistoricalEvent,
    sources: Sequence[HistoricalSourceEvidence],
) -> Dict[str, Any]:
    item, historical_event = claim.normalized(), event.normalized()
    if item.attribution_event_id != historical_event.event_id:
        raise ValueError("concept attribution event id does not match supplied event")
    by_id = {source.normalized().source_id: source.normalized() for source in sources}
    usable = []
    retrospective = []
    missing = []
    for source_id in item.contemporary_evidence_source_ids:
        source = by_id.get(source_id)
        if source is None:
            missing.append(source_id)
            continue
        if not source.provenance_complete:
            continue
        if source.publication_year <= historical_event.when.latest:
            usable.append(source_id)
        else:
            retrospective.append(source_id)
    anachronism_risk = not usable
    payload = {
        "concept_id": item.concept_id,
        "event_id": historical_event.event_id,
        "usable_period_evidence": sorted(usable),
        "retrospective_only_sources": sorted(retrospective),
        "missing_sources": sorted(missing),
        "anachronism_or_presentism_risk": anachronism_risk,
        "period_concept_gate_passed": bool(usable and not missing),
        "retrospective_language_may_describe_today": True,
        "retrospective_language_proves_period_actor_used_concept": False,
        "truth_proven": False,
    }
    return {**payload, "audit_hash": _hash(payload)}


def historiographic_summary(sources: Sequence[HistoricalSourceEvidence]) -> Dict[str, Any]:
    if isinstance(sources, (str, bytes, bytearray)) or not isinstance(sources, Sequence):
        raise ValueError("sources must be a sequence")
    if len(sources) > _MAX_ITEMS:
        raise ValueError("historical source limit exceeded")
    normalized = tuple(source.normalized() for source in sources)
    if len({source.source_id for source in normalized}) != len(normalized):
        raise ValueError("source_id values must be unique")

    # A declared independence group counts once per position.  Multiple books,
    # articles or mirrors in one group cannot manufacture consensus.
    grouped: Dict[str, set[str]] = {position: set() for position in _ALLOWED_POSITIONS}
    primary_groups = set()
    retrospective_groups = set()
    incomplete = []
    for source in normalized:
        if not source.provenance_complete:
            incomplete.append(source.source_id)
            continue
        grouped[source.position].add(source.independence_group)
        if source.primary_source:
            primary_groups.add(source.independence_group)
        else:
            retrospective_groups.add(source.independence_group)
    effective = {key: len(value) for key, value in sorted(grouped.items())}
    active_positions = [key for key in ("SUPPORT", "CHALLENGE") if effective.get(key, 0)]
    payload = {
        "source_count": len(normalized),
        "effective_independent_groups_by_position": effective,
        "primary_independence_groups": len(primary_groups),
        "retrospective_independence_groups": len(retrospective_groups),
        "incomplete_provenance_sources": sorted(incomplete),
        "historiographic_disagreement_present": len(active_positions) >= 2,
        "consensus_proves_truth": False,
        "truth_proven": False,
    }
    return {**payload, "report_hash": _hash(payload)}


def build_historical_context_report(
    *,
    events: Sequence[HistoricalEvent],
    sources: Sequence[HistoricalSourceEvidence],
    knowledge_claims: Sequence[ActorKnowledgeClaim] = (),
    causal_factors: Sequence[CausalHistoricalFactor] = (),
    concept_claims: Sequence[PeriodConceptClaim] = (),
) -> Dict[str, Any]:
    for value, name in (
        (events, "events"),
        (sources, "sources"),
        (knowledge_claims, "knowledge_claims"),
        (causal_factors, "causal_factors"),
        (concept_claims, "concept_claims"),
    ):
        if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
            raise ValueError(f"{name} must be a sequence")
        if len(value) > _MAX_ITEMS:
            raise ValueError(f"{name} exceeds bounded size")

    normalized_events = tuple(event.normalized() for event in events)
    normalized_sources = tuple(source.normalized() for source in sources)
    if len({event.event_id for event in normalized_events}) != len(normalized_events):
        raise ValueError("event_id values must be unique")
    if len({source.source_id for source in normalized_sources}) != len(normalized_sources):
        raise ValueError("source_id values must be unique")
    by_event = {event.event_id: event for event in normalized_events}

    source_context = []
    for source in normalized_sources:
        if source.describes_event_id:
            event = by_event.get(source.describes_event_id)
            if event is None:
                raise ValueError("source describes unknown event_id")
            source_context.append(classify_source_for_event(source, event))

    knowledge = [audit_actor_knowledge(item, normalized_sources) for item in knowledge_claims]
    causality = []
    for factor in causal_factors:
        normalized = factor.normalized()
        event = by_event.get(normalized.alleged_outcome_event_id)
        if event is None:
            raise ValueError("causal factor references unknown event_id")
        causality.append(audit_causal_chronology(normalized, event))
    concepts = []
    for claim in concept_claims:
        normalized = claim.normalized()
        event = by_event.get(normalized.attribution_event_id)
        if event is None:
            raise ValueError("period concept references unknown event_id")
        concepts.append(audit_period_concept(normalized, event, normalized_sources))

    chronology_blockers = sum(1 for row in causality if row["impossible_causal_order"])
    hindsight_blockers = sum(1 for row in knowledge if row["hindsight_only_evidence"] and not row["eligible_contemporary_evidence"])
    presentism_blockers = sum(1 for row in concepts if row["anachronism_or_presentism_risk"])
    body = {
        "events": [
            {
                "event_id": event.event_id,
                "label": event.label,
                "year_range": [event.when.earliest, event.when.latest],
                "exact_date_claimed": event.when.exact,
            }
            for event in normalized_events
        ],
        "source_context": source_context,
        "actor_knowledge_audits": knowledge,
        "causal_chronology_audits": causality,
        "period_concept_audits": concepts,
        "historiography": historiographic_summary(normalized_sources) if normalized_sources else {
            "source_count": 0,
            "effective_independent_groups_by_position": {},
            "historiographic_disagreement_present": False,
            "consensus_proves_truth": False,
            "truth_proven": False,
        },
        "blockers": {
            "impossible_causal_order": chronology_blockers,
            "hindsight_only_actor_knowledge": hindsight_blockers,
            "anachronism_or_presentism_risk": presentism_blockers,
        },
        "uncertain_ranges_preserved": True,
        "free_form_date_inference_performed": False,
        "hindsight_is_historical_knowledge": False,
        "consensus_proves_truth": False,
        "truth_proven": False,
    }
    return {**body, "report_hash": _hash(body)}
