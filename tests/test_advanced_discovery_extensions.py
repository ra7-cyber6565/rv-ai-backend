"""Production-wiring tests for additive advanced-discovery capabilities."""
from __future__ import annotations

from types import SimpleNamespace

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


def _triple_result(value: float, task_id: str = "T1"):
    return {
        "schema_version": "1.0",
        "capability_id": 40,
        "capability": "Triple Independent Implementation",
        "status": "TRIPLE_AGREEMENT",
        "all_requested_tasks_agree": True,
        "results": [{
            "task_id": task_id,
            "status": "TRIPLE_AGREEMENT",
            "verified": True,
            "implementations": [
                {"backend": "python_sandbox", "ok": True, "value": value},
                {"backend": "rscript", "ok": True, "value": value, "runtime_observed": True},
                {"backend": "independent_decimal_math", "ok": True, "value": value},
            ],
            "pairwise_agreement": {
                "python_vs_r": True,
                "python_vs_math": True,
                "r_vs_math": True,
            },
            "abs_tolerance": 0.01,
            "rel_tolerance": 0.001,
        }],
        "maturity_proof": {
            "production_module": True,
            "fail_closed_contract": True,
            "real_r_runtime_observed_this_run": True,
            "hardware_validation": False,
            "live_independent_validation": False,
            "max_or_verified_real_world_claim": False,
        },
    }


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
    triple = report["triple_independent_implementation"]
    assert triple["status"] == "NO_TASKS"
    assert triple["all_requested_tasks_agree"] is False
    assert triple["task_adapter"]["status"] == "NO_DERIVABLE_CHECKS"
    assert report["autonomous_literature_debate"]["status"] == "INSUFFICIENT_GROUNDED_ARGUMENTS"
    assert report["extension_integration"]["capabilities"] == [40, 103]
    assert report["extension_integration"]["base_discovery_preserved"] is True
    assert report["extension_integration"]["triple_task_adapter_wired"] is True
    assert report["extension_integration"]["expected_value_gate_wired"] is True


def test_injected_40_and_103_engines_receive_existing_pipeline_inputs():
    class SpyTriple:
        policy = SimpleNamespace(max_tasks=12)

        def __init__(self):
            self.seen = None

        def run(self, tasks):
            self.seen = list(tasks)
            return _triple_result(2.0, task_id="manual")

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
    verification = dict(verification)
    verification["triple_implementation_tasks"] = [{
        "task_id": "manual",
        "expression": "1 + 1",
        "variables": {},
    }]
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

    assert triple.seen == verification["triple_implementation_tasks"]
    assert debate.seen == (QUESTION, pack, contradictions)
    assert report["triple_independent_implementation"]["capability_id"] == 40
    assert report["triple_independent_implementation"]["status"] == "TRIPLE_AGREEMENT"
    assert report["triple_independent_implementation"]["task_adapter"]["source"] == "explicit"
    assert report["autonomous_literature_debate"]["capability_id"] == 103
    assert report["autonomous_literature_debate"]["status"] == "PARTIAL_DEBATE"


def test_normalized_verification_arithmetic_is_automatically_wired_into_40():
    class AgreeingTriple:
        policy = SimpleNamespace(max_tasks=12)

        def __init__(self):
            self.seen = None

        def run(self, tasks):
            self.seen = list(tasks)
            return _triple_result(20.0, task_id=tasks[0]["task_id"])

    planner, plan, pack, verification = _inputs()
    verification = dict(verification)
    verification["checks"] = [{"check": "12 + 8 = 20", "passed": True, "detail": "ok"}]
    triple = AgreeingTriple()
    report = IntegratedScientificDiscoveryEngine(planner, triple_engine=triple).analyze(
        question=QUESTION,
        plan=plan,
        pack=pack,
        hypotheses=[],
        contradictions=[],
        verification=verification,
    )

    assert len(triple.seen) == 1
    assert triple.seen[0]["expression"] == "12 + 8"
    assert triple.seen[0]["expected_value"] == 20.0
    result = report["triple_independent_implementation"]
    assert result["status"] == "TRIPLE_AGREEMENT"
    assert result["task_adapter"]["status"] == "DERIVED_TASKS"
    assert result["task_adapter"]["derived"] is True
    assert result["expected_values_checked"] == 1
    assert result["expected_values_matched"] == 1
    assert result["all_expected_values_match"] is True
    assert result["results"][0]["claim_value_matches_expected"] is True


def test_three_backends_agreeing_on_wrong_rhs_is_claim_mismatch_not_pass():
    class WrongButInternallyAgreeingTriple:
        policy = SimpleNamespace(max_tasks=12)

        def run(self, tasks):
            return _triple_result(21.0, task_id=tasks[0]["task_id"])

    planner, plan, pack, verification = _inputs()
    verification = dict(verification)
    verification["checks"] = [{"check": "12 + 8 = 20", "passed": False, "detail": "wrong"}]
    report = IntegratedScientificDiscoveryEngine(
        planner, triple_engine=WrongButInternallyAgreeingTriple()
    ).analyze(
        question=QUESTION,
        plan=plan,
        pack=pack,
        hypotheses=[],
        contradictions=[],
        verification=verification,
    )

    result = report["triple_independent_implementation"]
    assert result["status"] == "CLAIM_MISMATCH"
    assert result["all_requested_tasks_agree"] is False
    assert result["implementations_all_agree"] is True
    assert result["all_expected_values_match"] is False
    assert result["results"][0]["status"] == "CLAIM_MISMATCH"
    assert result["results"][0]["verified"] is False


def test_40_auxiliary_failure_is_fail_closed_without_destroying_base_report():
    class ExplodingTriple:
        policy = SimpleNamespace(max_tasks=12)

        def run(self, tasks):
            raise RuntimeError("secret internal path /tmp/do-not-leak")

    planner, plan, pack, verification = _inputs()
    verification = dict(verification)
    verification["triple_implementation_tasks"] = [{
        "task_id": "T1", "expression": "1 + 1", "variables": {}
    }]
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
    assert triple["all_expected_values_match"] is False
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
