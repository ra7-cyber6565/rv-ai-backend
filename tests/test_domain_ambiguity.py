"""Regression tests for strict-domain false positives from ambiguous triggers."""
from __future__ import annotations

from research_engine.domain import anchor_terms, detect


def test_tc_alone_does_not_activate_strict_superconductivity_domain():
    plan = detect("TC ka full form kya hota hai?")
    assert plan.key != "superconductivity"
    assert plan.strict is False
    assert "superconduct" not in " ".join(anchor_terms("TC ka full form kya hota hai?", fallback=True)).lower()


def test_critical_temperature_of_ferromagnet_is_not_forced_into_superconductivity():
    plan = detect("What is the critical temperature of a ferromagnet phase transition?")
    assert plan.key != "superconductivity", plan.to_dict()


def test_single_nickelate_material_question_prefers_materials_domain_when_available():
    plan = detect("nickelate crystal structure and thin film material properties")
    assert plan.key == "materials_physics", plan.to_dict()


def test_two_weak_superconductivity_signals_can_still_keep_science_context():
    plan = detect("hydride critical temperature under pressure")
    assert plan.key == "superconductivity", plan.to_dict()


def test_explicit_superconductor_keyword_always_keeps_superconductivity():
    plan = detect("What is Tc in high temperature superconductors?")
    assert plan.key == "superconductivity"
    assert plan.strict is True


def test_cooper_pair_is_specific_enough_for_superconductivity():
    plan = detect("How does Cooper pair formation work?")
    assert plan.key == "superconductivity"
