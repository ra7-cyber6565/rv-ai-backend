"""Production audit wiring for #104 Historical Context Engine.

Only an explicit ``historical_context_inputs`` structure is evaluated.  For API
compatibility it may be supplied either top-level by an internal result builder
or inside the already-existing ``coverage`` mapping.  The adapter never
extracts dates, actor knowledge, causal chronology, or period concepts from
free-form answer/source prose.  Output is audit-only under
``coverage.historical_context`` and cannot upgrade answer status or truth.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence

from .historical_context import (
    ActorKnowledgeClaim,
    CausalHistoricalFactor,
    HistoricalEvent,
    HistoricalSourceEvidence,
    PeriodConceptClaim,
    YearRange,
    build_historical_context_report,
)


_INSTALLED = False
_MAX_INPUTS = 20_000


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping")
    return value


def _sequence(value: object, field: str) -> Sequence[Any]:
    if value is None:
        return ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > _MAX_INPUTS:
            raise ValueError(f"{field} exceeds bounded size")
        return value
    raise ValueError(f"{field} must be a sequence")


def _range(value: object, field: str) -> YearRange:
    item = _mapping(value, field)
    if set(item) != {"earliest", "latest"}:
        raise ValueError(f"{field} requires earliest/latest only")
    return YearRange(earliest=item["earliest"], latest=item["latest"]).normalized()


def _events(values: Sequence[Any]) -> list[HistoricalEvent]:
    out = []
    for index, raw in enumerate(values):
        item = _mapping(raw, f"events[{index}]")
        out.append(HistoricalEvent(
            event_id=item.get("event_id"),
            label=item.get("label"),
            when=_range(item.get("when"), f"events[{index}].when"),
        ).normalized())
    return out


def _sources(values: Sequence[Any]) -> list[HistoricalSourceEvidence]:
    out = []
    for index, raw in enumerate(values):
        item = _mapping(raw, f"sources[{index}]")
        # Parent/citation genealogy has its own SourceIntegrity engine.  Keeping
        # this adapter narrow avoids silently treating a citation edge as a
        # historical-knowledge relation.
        out.append(HistoricalSourceEvidence(
            source_id=item.get("source_id"),
            publication_year=item.get("publication_year"),
            independence_group=item.get("independence_group"),
            evidence_ref=item.get("evidence_ref"),
            position=item.get("position", "UNKNOWN"),
            primary_source=bool(item.get("primary_source", False)),
            provenance_complete=bool(item.get("provenance_complete", False)),
            describes_event_id=item.get("describes_event_id", ""),
        ).normalized())
    return out


def _knowledge(values: Sequence[Any]) -> list[ActorKnowledgeClaim]:
    out = []
    for index, raw in enumerate(values):
        item = _mapping(raw, f"knowledge_claims[{index}]")
        refs = _sequence(item.get("evidence_source_ids"), f"knowledge_claims[{index}].evidence_source_ids")
        out.append(ActorKnowledgeClaim(
            claim_id=item.get("claim_id"),
            actor_id=item.get("actor_id"),
            statement=item.get("statement"),
            knowledge_cutoff_year=item.get("knowledge_cutoff_year"),
            evidence_source_ids=tuple(refs),
        ).normalized())
    return out


def _causal(values: Sequence[Any]) -> list[CausalHistoricalFactor]:
    out = []
    for index, raw in enumerate(values):
        item = _mapping(raw, f"causal_factors[{index}]")
        out.append(CausalHistoricalFactor(
            factor_id=item.get("factor_id"),
            label=item.get("label"),
            active_when=_range(item.get("active_when"), f"causal_factors[{index}].active_when"),
            alleged_outcome_event_id=item.get("alleged_outcome_event_id"),
        ).normalized())
    return out


def _concepts(values: Sequence[Any]) -> list[PeriodConceptClaim]:
    out = []
    for index, raw in enumerate(values):
        item = _mapping(raw, f"concept_claims[{index}]")
        refs = _sequence(
            item.get("contemporary_evidence_source_ids"),
            f"concept_claims[{index}].contemporary_evidence_source_ids",
        )
        out.append(PeriodConceptClaim(
            concept_id=item.get("concept_id"),
            concept=item.get("concept"),
            attribution_event_id=item.get("attribution_event_id"),
            contemporary_evidence_source_ids=tuple(refs),
        ).normalized())
    return out


def _historical_inputs(result: Mapping[str, Any]) -> object:
    if result.get("historical_context_inputs") is not None:
        return result.get("historical_context_inputs")
    coverage = result.get("coverage")
    if isinstance(coverage, Mapping):
        return coverage.get("historical_context_inputs")
    return None


def build_historical_context_packet(result: Mapping[str, Any]) -> Dict[str, Any]:
    raw = _historical_inputs(result)
    if raw is None:
        return {
            "ran": True,
            "status": "NO_STRUCTURED_HISTORICAL_INPUTS",
            "events": [],
            "source_context": [],
            "actor_knowledge_audits": [],
            "causal_chronology_audits": [],
            "period_concept_audits": [],
            "free_form_date_inference_performed": False,
            "truth_proven": False,
            "result_status_upgraded": False,
        }
    data = _mapping(raw, "historical_context_inputs")
    allowed = {"events", "sources", "knowledge_claims", "causal_factors", "concept_claims"}
    if set(data) - allowed:
        raise ValueError("historical_context_inputs contains unsupported fields")

    events = _events(_sequence(data.get("events"), "events"))
    sources = _sources(_sequence(data.get("sources"), "sources"))
    knowledge = _knowledge(_sequence(data.get("knowledge_claims"), "knowledge_claims"))
    causal = _causal(_sequence(data.get("causal_factors"), "causal_factors"))
    concepts = _concepts(_sequence(data.get("concept_claims"), "concept_claims"))
    if not any((events, sources, knowledge, causal, concepts)):
        return {
            "ran": True,
            "status": "NO_STRUCTURED_HISTORICAL_INPUTS",
            "events": [],
            "source_context": [],
            "actor_knowledge_audits": [],
            "causal_chronology_audits": [],
            "period_concept_audits": [],
            "free_form_date_inference_performed": False,
            "truth_proven": False,
            "result_status_upgraded": False,
        }

    report = build_historical_context_report(
        events=events,
        sources=sources,
        knowledge_claims=knowledge,
        causal_factors=causal,
        concept_claims=concepts,
    )
    report.update({
        "ran": True,
        "status": "AUDITED",
        "result_status_upgraded": False,
    })
    return report


def apply_historical_context_wiring(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    coverage = dict(data.get("coverage") or {})
    try:
        packet = build_historical_context_packet(data)
    except Exception as exc:
        packet = {
            "ran": False,
            "status": "ASSESSMENT_ERROR",
            "events": [],
            "source_context": [],
            "actor_knowledge_audits": [],
            "causal_chronology_audits": [],
            "period_concept_audits": [],
            "free_form_date_inference_performed": False,
            "truth_proven": False,
            "result_status_upgraded": False,
            "error": type(exc).__name__,
        }
    coverage["historical_context"] = packet
    data["coverage"] = coverage
    return data


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from . import result_coverage_gate as result_mod

    original_enforce = result_mod.enforce

    def enforce_with_historical_context(result: Dict[str, Any]) -> Dict[str, Any]:
        return apply_historical_context_wiring(original_enforce(result))

    result_mod.enforce = enforce_with_historical_context
