"""Regression: fluent hypothesis mechanisms may not borrow confidence from unrelated cites."""
from __future__ import annotations

from types import SimpleNamespace

from research_engine.hypothesis import Hypothesis, HypothesisEngine, PredictionStructure
from research_engine.hypothesis_evidence_lineage import (
    STATUS_BAD_CITATION,
    STATUS_INFERENCE,
    STATUS_SUPPORTED,
    STATUS_UNSOURCED,
    audit_hypothesis_lineage,
)
from research_engine.models import EvidencePack, SourceRecord, SourceType


def _source(sid: str, text: str) -> SourceRecord:
    source = SourceRecord(
        title=f"Source {sid}",
        url=f"https://example.org/{sid.lower()}",
        snippet=text,
        source_type=SourceType.PAPER,
        peer_reviewed=True,
        read_level="full_text",
        relevance_score=0.9,
        quality_score=0.9,
    )
    source.source_id = sid
    source.full_text_chars = max(1200, len(text))
    return source


def _pack(*sources: SourceRecord) -> EvidencePack:
    return EvidencePack(
        question="Does periodic digital abstinence improve sustained human attention?",
        sources=list(sources),
        topic_terms=["digital", "attention", "dopamine", "cortisol"],
    )


def _prediction() -> PredictionStructure:
    return PredictionStructure(
        variables=["sustained attention score"],
        expected_outcome="treatment group changes by a measurable amount",
        measurement_method="standardized sustained-attention cognitive test",
        falsification_condition="pre-registered effect is absent at the planned endpoint",
    )


def _base_hypothesis(mechanism: str, reasoning: str = "") -> Hypothesis:
    return Hypothesis(
        statement="Periodic digital abstinence changes long-term sustained attention.",
        simple="A weekly offline period may change how steadily a person can focus over time.",
        mechanism=mechanism,
        reasoning=reasoning,
        supporting_evidence="Two retrieved sources motivate the question [S1] [S2].",
        contradicting_evidence="Some evidence suggests effects may be small or context dependent [S2].",
        assumptions="Digital exposure is measured consistently and groups remain comparable.",
        prediction=_prediction(),
        experiment="Randomized controlled study with logged exposure, control group and attention testing.",
        falsification="Reject if the pre-registered attention endpoint shows no meaningful group difference.",
        confidence="HIGH",
    )


def _gate():
    return SimpleNamespace(relevant_sources=4, deep_sources=4, full_text_sources=3)


def test_unrelated_citations_cannot_support_dopamine_receptor_mechanism():
    pack = _pack(
        _source("S1", "Motivational bias and self-deception alter decisions under ambiguous conditions."),
        _source("S2", "Social comparison can influence confidence and decision reports."),
    )
    h = _base_hypothesis(
        "Removing variable-reward digital triggers reduces tonic dopamine firing, "
        "up-regulates post-synaptic dopamine receptors, and lowers cortisol.",
        reasoning="[INFERENCE] The behavioural evidence motivates testing a neurobiological pathway.",
    )
    h.facts_used = ["S1", "S2"]
    audit = audit_hypothesis_lineage(h, pack)
    mechanism = [row for row in audit["steps"] if row["field"] == "mechanism"]
    assert mechanism
    assert mechanism[0]["status"] in {STATUS_UNSOURCED, STATUS_BAD_CITATION}
    assert audit["undisclosed_or_failed_steps"] >= 1
    assert audit["honesty_complete"] is False


def test_explicit_inference_is_not_falsely_reported_as_source_backed():
    pack = _pack(
        _source("S1", "Digital interruptions are associated with task switching."),
        _source("S2", "Attention performance varies with interruption frequency."),
    )
    h = _base_hypothesis(
        "[INFERENCE] Repeated offline periods may change receptor sensitivity over time."
    )
    h.facts_used = ["S1", "S2"]
    audit = audit_hypothesis_lineage(h, pack)
    assert audit["undisclosed_or_failed_steps"] == 0
    assert audit["disclosed_uncertainty_steps"] == 1
    assert audit["steps"][0]["status"] == STATUS_INFERENCE
    assert audit["evidence_complete"] is False


def test_same_source_semantic_support_can_back_a_mechanism_step():
    mechanism = (
        "Scheduled offline periods reduce interruption frequency and increase "
        "uninterrupted sustained-attention practice."
    )
    pack = _pack(
        _source("S1", mechanism + " The study measured both interruption frequency and attention."),
        _source("S2", mechanism + " A replication observed the same behavioural pathway."),
    )
    h = _base_hypothesis(mechanism)
    h.facts_used = ["S1", "S2"]
    audit = audit_hypothesis_lineage(h, pack)
    assert audit["steps"][0]["status"] == STATUS_SUPPORTED
    assert audit["steps"][0]["supporting_source_ids"]
    assert audit["undisclosed_or_failed_steps"] == 0


def test_enrich_caps_confidence_and_serializes_lineage_on_failed_mechanism():
    pack = _pack(
        _source("S1", "Motivational bias changes reported confidence under ambiguity."),
        _source("S2", "Self-deception can alter decisions without measuring dopamine receptors."),
    )
    h = _base_hypothesis(
        "Digital abstinence up-regulates post-synaptic dopamine receptors and "
        "therefore permanently restores attention capacity.",
        reasoning="[INFERENCE] This proposed bridge is not established by the retrieved studies.",
    )
    engine = HypothesisEngine()
    rows = engine.enrich(
        [h],
        question=pack.question,
        pack=pack,
        gate=_gate(),
        contradictions=[{"summary": "reported attention effects disagree"}],
        counter_search_performed=True,
        calculations_done=True,
        prior_art_searched=False,
    )
    assert rows[0].confidence_record is not None
    assert rows[0].confidence_record.band == "VERY LOW"
    assert "MECHANISM_LINEAGE_FAILED" in rows[0].confidence_record.reason_codes
    payload = rows[0].to_dict()
    assert payload["mechanism_evidence_lineage"]["undisclosed_or_failed_steps"] >= 1
    warnings = engine.honesty_check(rows)
    assert any("evidence-lineage fail" in warning for warning in warnings)


def test_disclosed_unsupported_mechanism_cannot_keep_moderate_confidence():
    pack = _pack(
        _source("S1", "Digital interruptions predict task switching frequency."),
        _source("S2", "A second study reports attention costs after interruptions."),
    )
    h = _base_hypothesis(
        "[INFERENCE] Offline periods may alter a still-unknown neural adaptation pathway.",
        reasoning="Evidence on interruption costs motivates the test [S1] [S2].",
    )
    rows = HypothesisEngine().enrich(
        [h], question=pack.question, pack=pack, gate=_gate(),
        contradictions=[{"summary": "effects differ across contexts"}],
        counter_search_performed=True, calculations_done=True,
        prior_art_searched=False,
    )
    assert rows[0].confidence_record.band in {"VERY LOW", "LOW"}
    assert rows[0].confidence_record.band != "MODERATE"
