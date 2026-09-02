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


def test_base_advanced_discovery_contract_is_preserved_when_extensions_are_added():
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
    assert report["autonomous_literature_debate"]["status"] == "INSUFFICIENT_GROUNDED_ARGUMENTS"
    assert report["extension_integration"]["capabilities"] == [40, 103]
    assert report["extension_integration"]["base_discovery_preserved"] is True


def test_injected_40_and_103_engines_receive_existing_pipeline_inputs():
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

    class SpyDebate:
        def __init__(self):
            self.seen = None

        def reconstruct(self, question, pack, contradictions=()):
            self.seen = (question, pack, contradictions)
            return {
                "schema_version": "1.0",
                "capability_id": 103,
                "status": "PARTIAL_DEBATE",
                "role_slots": {},
                "debate_map": {"nodes": [], "edges": []},
            }

    planner, plan, pack, verification = _inputs()
    triple = SpyTriple()
    debate = SpyDebate()
    contradictions = [{"summary": "fixture contradiction"}]
    report = IntegratedScientificDiscoveryEngine(
        planner,
        triple_engine=triple,
        literature_debate=debate,
    ).analyze(
        question=QUESTION,
        plan=plan,
        pack=pack,
        hypotheses=[],
        contradictions=contradictions,
        verification=verification,
    )

    assert triple.seen is verification
    assert debate.seen == (QUESTION, pack, contradictions)
    assert report["triple_independent_implementation"]["capability_id"] == 40
    assert report["triple_independent_implementation"]["status"] == "TRIPLE_AGREEMENT"
    assert report["autonomous_literature_debate"]["capability_id"] == 103
    assert report["autonomous_literature_debate"]["status"] == "PARTIAL_DEBATE"


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
    # One auxiliary failure must not prevent the other capability from running.
    assert report["autonomous_literature_debate"]["status"] == "INSUFFICIENT_GROUNDED_ARGUMENTS"


def test_103_auxiliary_failure_is_fail_closed_without_destroying_base_or_40():
    class ExplodingDebate:
        def reconstruct(self, question, pack, contradictions=()):
            raise RuntimeError("secret debate failure /home/private")

    planner, plan, pack, verification = _inputs()
    report = IntegratedScientificDiscoveryEngine(
        planner, literature_debate=ExplodingDebate()
    ).analyze(
        question=QUESTION,
        plan=plan,
        pack=pack,
        hypotheses=[],
        contradictions=[],
        verification=verification,
    )

    assert report["status"] == "NO_TESTABLE_HYPOTHESES"
    assert report["triple_independent_implementation"]["status"] == "NO_TASKS"
    debate = report["autonomous_literature_debate"]
    assert debate["status"] == "ASSESSMENT_ERROR"
    assert debate["role_slots"] == {
        "researcher_a_reasoning": [],
        "researcher_b_critique": [],
        "researcher_c_replication_failure": [],
    }
    assert debate["maturity_proof"]["systematic_review_completeness_proven"] is False
    assert debate["maturity_proof"]["live_independent_validation_proven"] is False
    assert "/home/private" not in repr(report)
