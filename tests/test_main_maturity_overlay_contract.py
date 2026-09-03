"""Fail-closed integration contract for latest-main maturity + branch hardening.

This test exists because a history-only merge can look up-to-date while an old
integration tree silently deletes newer production wiring.  The contract is
pure static/offline: it proves the branch still contains the current main
scientific wiring while allowing additive security/storage overlays.
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_latest_main_package_maturity_wiring_is_preserved():
    init = _read("research_engine/__init__.py")
    required = (
        "_install_causal_counterfactual_wiring",
        "_install_mechanistic_reasoning_wiring",
        "_install_capture_integrity_wiring",
        "_install_evidence_capture_integrity",
        "_install_runtime_capability_wiring",
        "_install_literature_debate_wiring",
        "_install_discovery_frontier_wiring",
        "_install_neural_symbolic_wiring",
        "_install_world_model_wiring",
        "_install_technology_readiness_wiring",
        "_install_manufacturing_reality_wiring",
        "_install_historical_context_wiring",
        "_install_epistemic_stress_wiring",
        "_install_economic_reality_wiring",
    )
    missing = [name for name in required if name not in init]
    assert not missing, f"latest-main maturity wiring disappeared: {missing}"


def test_latest_main_orchestrator_scientific_bridges_are_preserved():
    orchestrator = _read("research_engine/orchestrator.py")
    required = (
        "build_runtime_evidence_packet",
        "build_runtime_experiment_packet",
        "KnowledgeWatch",
        "update_from_research_run",
        "analyze_evidence_pack",
        "ScientificDiscoveryEngine",
    )
    missing = [name for name in required if name not in orchestrator]
    assert not missing, f"production orchestrator lost maturity bridges: {missing}"


def test_extraction_and_verification_integrity_wiring_is_not_downgraded():
    ocr = _read("research_engine/processing/ocr_processor.py")
    document = _read("research_engine/processing/document_processor.py")
    verification = _read("research_engine/verification.py")
    assert "assess_ocr_confidences" in ocr
    assert "extraction_integrity" in ocr
    assert "native_text_integrity" in document
    assert "extraction_integrity" in document
    assert '"F_capture_integrity"' in verification
    assert "A-E + capture-integrity F" in verification


def test_obsolete_parallel_maturity_adapters_do_not_return():
    obsolete = (
        "research_engine/advanced_discovery_integrated.py",
        "research_engine/capability_maturity.py",
        "research_engine/literature_debate_guard.py",
        "research_engine/triple_task_adapter.py",
        "scripts/audit_advanced_integration.py",
    )
    present = [path for path in obsolete if (ROOT / path).exists()]
    assert not present, f"superseded duplicate maturity adapters returned: {present}"


def test_branch_source_hardening_is_additive_not_a_maturity_replacement():
    source_guard = _read("research_engine/source_prompt_guard.py")
    assert "POTENTIAL-INJECTION-DATA>" in source_guard
    assert "install_local_reasoning_guard" in source_guard
    assert "_install_source_properties" in source_guard
    assert "_install_dedup_semantics" in source_guard
    # Latest main owns the formal literature-debate engine. The source guard may
    # strengthen work/origin identity, but must not re-install the superseded
    # AutonomousLiteratureDebate monkey patch.
    assert "_install_literature_debate_semantics()" not in source_guard
    assert "IntegratedScientificDiscoveryEngine" not in source_guard
