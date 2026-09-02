"""Production-wiring tests for additive advanced-discovery capabilities."""
from __future__ import annotations

import research_engine
from research_engine import advanced_discovery
from research_engine.advanced_discovery_integrated import IntegratedScientificDiscoveryEngine
from research_engine.depth import get_depth_config
from research_engine.models import EvidencePack
from research_engine.planner import ResearchPlanner


QUESTION = "Can a testable materials hypothesis be checked independently?"


def _inputs():
    planner = ResearchPlanner()
    plan = planner.plan(QUESTION, get_depth_config("DEEP"))
    pack = EvidencePack(question=QUESTION, sources=[], rounds_run=1)
    verification = {
        "status": "RESEARCH INCOMPLETE",
        "claim_checks": {"gate_passed": False},
    }
    return planner, plan, pack, verification


def test_package_boundary_installs_integrated_engine_for_direct_module_imports():
    # Orchestrator imports `ScientificDiscoveryEngine` directly from this module.
    # The package boundary must therefore patch that exact exported class, not
    # merely expose a second unused facade elsewhere.
    assert advanced_discovery.ScientificDiscoveryEngine is IntegratedScientificDiscoveryEngine
    assert research_engine.ScientificDiscoveryEngine is IntegratedScientificDiscoveryEngine


def test_base_advanced_discovery_contract_is_preserved_when_40_is_added():
    planner, plan, pack, verification = _inputs()
    report = IntegratedScientificDiscoveryEngine(planner).analyze(
        question=QUESTION,
        plan=plan,
        pack=pack,
        hypotheses=[],
        contradictions=[],
        verification=verification,
    )

    for key in (
        "problem_decomposition", "evidence_graph", "hypotheses", "tournament",
        "weakest_link", "alternative_paths", "recursive_research",
        "reality_ladder", "domain_validation", "simulation_executor",
    ):
        assert key in report
    assert report["status"] == "NO_TESTABLE_HYPOTHESES"
    assert report["triple_independent_implementation"]["status"] == "NO_TASKS"
    assert report["triple_independent_implementation"]["all_requested_tasks_agree"] is False
    assert report["extension_integration"]["capabilities"] == [40]
    assert report["extension_integration"]["base_discovery_preserved"] is True


def test_injected_40_engine_is_called_with_existing_verification_payload():
    class SpyTriple:
        def __init__(self):
            self.seen = None

        def run_from_verification(self, verification):
            self.seen = verification
            return {
                "schema_version": "1.0",
                "capability_id": 40,
                "status": "TRIPLE_AGREEMENT",
                "all_requested_tasks_agree": True,
            }

    planner, plan, pack, verification = _inputs()
    triple = SpyTriple()
    report = IntegratedScientificDiscoveryEngine(planner, triple_engine=triple).analyze(
        question=QUESTION,
        plan=plan,
        pack=pack,
        hypotheses=[],
        contradictions=[],
        verification=verification,
    )

    assert triple.seen is verification
    assert report["triple_independent_implementation"]["capability_id"] == 40
    assert report["triple_independent_implementation"]["status"] == "TRIPLE_AGREEMENT"


def test_40_auxiliary_failure_is_fail_closed_without_destroying_base_report():
    class ExplodingTriple:
        def run_from_verification(self, verification):
            raise RuntimeError("secret internal path /tmp/do-not-leak")

    planner, plan, pack, verification = _inputs()
    report = IntegratedScientificDiscoveryEngine(
        planner, triple_engine=ExplodingTriple()
    ).analyze(
        question=QUESTION,
        plan=plan,
        pack=pack,
        hypotheses=[],
        contradictions=[],
        verification=verification,
    )

    assert report["status"] == "NO_TESTABLE_HYPOTHESES"
    triple = report["triple_independent_implementation"]
    assert triple["status"] == "ASSESSMENT_ERROR"
    assert triple["all_requested_tasks_agree"] is False
    assert triple["maturity_proof"]["hardware_validation"] is False
    assert triple["maturity_proof"]["live_independent_validation"] is False
    assert "/tmp/do-not-leak" not in repr(report)
