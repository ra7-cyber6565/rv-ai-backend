import pytest

from research_engine.historical_context import (
    ActorKnowledgeClaim,
    CausalHistoricalFactor,
    HistoricalEvent,
    HistoricalSourceEvidence,
    PeriodConceptClaim,
    YearRange,
    audit_actor_knowledge,
    audit_causal_chronology,
    audit_period_concept,
    build_historical_context_report,
    historiographic_summary,
    temporal_relation,
)


def _event(event_id="E1", earliest=1914, latest=1914):
    return HistoricalEvent(event_id, "Historical event", YearRange(earliest, latest))


def _source(
    source_id="S1",
    year=1914,
    group="G1",
    *,
    position="SUPPORT",
    primary=True,
    complete=True,
    event_id="E1",
):
    return HistoricalSourceEvidence(
        source_id=source_id,
        publication_year=year,
        independence_group=group,
        evidence_ref=f"archive:{source_id}",
        position=position,
        primary_source=primary,
        provenance_complete=complete,
        describes_event_id=event_id,
    )


def test_year_range_preserves_uncertainty_and_never_invents_exact_date():
    report = build_historical_context_report(
        events=[_event(earliest=1912, latest=1914)],
        sources=[],
    )
    assert report["events"][0]["year_range"] == [1912, 1914]
    assert report["events"][0]["exact_date_claimed"] is False
    assert report["uncertain_ranges_preserved"] is True
    assert report["free_form_date_inference_performed"] is False


def test_temporal_relation_overlap_is_indeterminate_not_guessed():
    assert temporal_relation(YearRange(1900, 1910), YearRange(1905, 1915)) == "OVERLAP_OR_INDETERMINATE"
    assert temporal_relation(YearRange(1900, 1904), YearRange(1905, 1915)) == "BEFORE"
    assert temporal_relation(YearRange(1916, 1920), YearRange(1905, 1915)) == "AFTER"


def test_later_source_cannot_prove_earlier_actor_knowledge():
    claim = ActorKnowledgeClaim(
        claim_id="K1",
        actor_id="A1",
        statement="The actor knew the later-discovered mechanism.",
        knowledge_cutoff_year=1914,
        evidence_source_ids=("S-late",),
    )
    audit = audit_actor_knowledge(claim, [_source("S-late", 1950, primary=False)])
    assert audit["actor_knowledge_gate_passed"] is False
    assert audit["eligible_contemporary_evidence"] == []
    assert audit["hindsight_only_evidence"] == ["S-late"]
    assert audit["later_sources_may_inform_present_interpretation"] is True
    assert audit["later_sources_can_prove_actor_knew_it"] is False
    assert audit["truth_proven"] is False


def test_contemporary_evidence_can_pass_knowledge_gate_but_does_not_prove_truth():
    claim = ActorKnowledgeClaim(
        claim_id="K1",
        actor_id="A1",
        statement="The actor had access to this documented information.",
        knowledge_cutoff_year=1914,
        evidence_source_ids=("S1",),
    )
    audit = audit_actor_knowledge(claim, [_source("S1", 1913)])
    assert audit["actor_knowledge_gate_passed"] is True
    assert audit["eligible_contemporary_evidence"] == ["S1"]
    assert audit["truth_proven"] is False


def test_incomplete_provenance_blocks_actor_knowledge_gate():
    claim = ActorKnowledgeClaim("K1", "A1", "Documented knowledge claim", 1914, ("S1",))
    audit = audit_actor_knowledge(claim, [_source("S1", 1913, complete=False)])
    assert audit["actor_knowledge_gate_passed"] is False
    assert audit["incomplete_provenance"] == ["S1"]


def test_cause_wholly_after_outcome_is_impossible_chronology():
    factor = CausalHistoricalFactor(
        factor_id="F1",
        label="Later policy change",
        active_when=YearRange(1920, 1922),
        alleged_outcome_event_id="E1",
    )
    audit = audit_causal_chronology(factor, _event(earliest=1914, latest=1914))
    assert audit["impossible_causal_order"] is True
    assert audit["temporal_relation"] == "AFTER"
    assert audit["causality_proven"] is False


def test_overlapping_causal_ranges_are_indeterminate_not_false_precision():
    factor = CausalHistoricalFactor(
        factor_id="F1",
        label="Slow institutional change",
        active_when=YearRange(1912, 1916),
        alleged_outcome_event_id="E1",
    )
    audit = audit_causal_chronology(factor, _event(earliest=1914, latest=1915))
    assert audit["impossible_causal_order"] is False
    assert audit["chronology_indeterminate"] is True
    assert audit["temporal_relation"] == "OVERLAP_OR_INDETERMINATE"


def test_period_concept_without_contemporary_evidence_flags_presentism():
    claim = PeriodConceptClaim(
        concept_id="C1",
        concept="A modern analytical category",
        attribution_event_id="E1",
        contemporary_evidence_source_ids=("S-late",),
    )
    audit = audit_period_concept(claim, _event(), [_source("S-late", 2000, primary=False)])
    assert audit["anachronism_or_presentism_risk"] is True
    assert audit["period_concept_gate_passed"] is False
    assert audit["retrospective_only_sources"] == ["S-late"]
    assert audit["retrospective_language_proves_period_actor_used_concept"] is False


def test_period_concept_with_period_evidence_can_pass_context_gate_only():
    claim = PeriodConceptClaim(
        concept_id="C1",
        concept="A documented period category",
        attribution_event_id="E1",
        contemporary_evidence_source_ids=("S1",),
    )
    audit = audit_period_concept(claim, _event(), [_source("S1", 1914)])
    assert audit["period_concept_gate_passed"] is True
    assert audit["anachronism_or_presentism_risk"] is False
    assert audit["truth_proven"] is False


def test_same_independence_group_cannot_inflate_historiographic_support():
    summary = historiographic_summary([
        _source("S1", 1914, "G1", position="SUPPORT"),
        _source("S2", 1915, "G1", position="SUPPORT"),
        _source("S3", 1920, "G2", position="CHALLENGE", primary=False),
    ])
    assert summary["source_count"] == 3
    assert summary["effective_independent_groups_by_position"]["SUPPORT"] == 1
    assert summary["effective_independent_groups_by_position"]["CHALLENGE"] == 1
    assert summary["historiographic_disagreement_present"] is True
    assert summary["consensus_proves_truth"] is False


def test_full_report_surfaces_all_three_historical_blocker_classes():
    report = build_historical_context_report(
        events=[_event()],
        sources=[_source("S-late", 1950, primary=False)],
        knowledge_claims=[ActorKnowledgeClaim(
            "K1", "A1", "Actor knew a later-discovered fact", 1914, ("S-late",)
        )],
        causal_factors=[CausalHistoricalFactor(
            "F1", "Post-event cause", YearRange(1920, 1920), "E1"
        )],
        concept_claims=[PeriodConceptClaim(
            "C1", "Modern category", "E1", ("S-late",)
        )],
    )
    assert report["blockers"] == {
        "impossible_causal_order": 1,
        "hindsight_only_actor_knowledge": 1,
        "anachronism_or_presentism_risk": 1,
    }
    assert report["truth_proven"] is False
    assert report["consensus_proves_truth"] is False
    assert len(report["report_hash"]) == 64


def test_report_is_deterministic():
    args = dict(
        events=[_event()],
        sources=[_source()],
        knowledge_claims=[ActorKnowledgeClaim(
            "K1", "A1", "Documented period knowledge", 1914, ("S1",)
        )],
    )
    assert build_historical_context_report(**args) == build_historical_context_report(**args)


def test_invalid_ranges_and_unknown_event_references_fail_closed():
    with pytest.raises(ValueError, match="earliest cannot be later"):
        YearRange(1915, 1914).normalized()

    with pytest.raises(ValueError, match="unknown event_id"):
        build_historical_context_report(
            events=[_event()],
            sources=[_source(event_id="MISSING")],
        )
