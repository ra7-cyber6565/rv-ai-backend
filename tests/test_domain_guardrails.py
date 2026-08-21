"""Independent ChatGPT regression tests for Claude's domain/relevance hardening.

These are intentionally offline and focus on the exact failure mode seen in the
superconductivity benchmark plus cross-domain false-positive/false-negative risk.
"""
from __future__ import annotations

from research_engine.domain import detect
from research_engine.models import SourceRecord, SourceType
from research_engine.relevance import RelevanceEngine


def _source(title: str, snippet: str = "", url: str = "https://example.org/paper") -> SourceRecord:
    return SourceRecord(
        title=title,
        snippet=snippet,
        url=url,
        source_type=SourceType.PAPER,
        peer_reviewed=True,
    )


def test_superconductivity_domain_wins_over_generic_materials_words():
    plan = detect(
        "Can ambient-pressure room-temperature superconductors become practical materials for grids and motors?"
    )
    assert plan.key == "superconductivity"
    assert plan.strict is True


def test_room_temperature_ferroelectricity_is_hard_rejected_for_superconductivity():
    query = "ambient pressure room temperature superconductivity"
    engine = RelevanceEngine()
    source = _source(
        "Room Temperature Ferroelectricity and Ferromagnetism in a 2D Material",
        "A monolayer multiferroic shows anomalous Hall response and stable polarization.",
    )
    assert engine.score_relevance(source, query) == 0.0
    assert source.rejected_reason


def test_prosthetic_biocomposite_is_hard_rejected_for_superconductivity():
    query = "room temperature superconductors for future power systems"
    engine = RelevanceEngine()
    source = _source(
        "Hybrid Biocomposites from Luffa and Banana Fibres for a Prosthetic Socket",
        "Mechanical testing of natural-fibre composite laminates for a prosthetic leg.",
    )
    assert engine.score_relevance(source, query) == 0.0
    assert source.domain_verdict.get("rejected") is True


def test_real_superconductivity_paper_survives_domain_gate():
    query = "ambient pressure room temperature superconductivity hydrides"
    engine = RelevanceEngine()
    source = _source(
        "High-temperature superconductivity in lanthanum hydrides under pressure",
        "We report superconducting transitions, critical temperature Tc, pressure dependence and hydride phases.",
    )
    score = engine.score_relevance(source, query)
    assert score > 0.0
    assert source.domain_verdict.get("rejected") is False


def test_medical_subject_trigger_prevents_false_rejection_of_diabetes_paper():
    query = "Can type 2 diabetes go into long-term remission after treatment?"
    engine = RelevanceEngine()
    source = _source(
        "Long-term remission of type 2 diabetes after weight-loss intervention",
        "Clinical outcomes and remission were measured during follow-up.",
        url="https://pubmed.ncbi.nlm.nih.gov/example",
    )
    score = engine.score_relevance(source, query)
    assert engine.plan_of(query).key == "medicine_health"
    assert score > 0.0
    assert not source.rejected_reason


def test_ml_for_superconductor_discovery_keeps_superconductivity_as_primary_domain():
    query = "Use machine learning models to discover new high-temperature superconductors and predict Tc"
    plan = detect(query)
    assert plan.key == "superconductivity"
    assert any(r.key == "cs_ml" for r in plan.rivals)


def test_superconductivity_router_drops_health_connectors_but_keeps_scholarly():
    plan = detect("room temperature superconductivity")
    keep, dropped = plan.route([
        "arxiv", "openalex", "who_gho", "world_bank", "data_gov_in", "zenodo"
    ])
    assert "arxiv" in keep
    assert "openalex" in keep
    assert "zenodo" in keep
    assert {"who_gho", "world_bank", "data_gov_in"}.issubset(set(dropped))


def test_generic_unknown_domain_does_not_hard_reject_everything():
    plan = detect("Why do people sometimes change their mind after learning new information?")
    if not plan.is_known:
        verdict = plan.assess("Belief updating and information", "A general explanatory article")
        assert verdict.rejected is False
