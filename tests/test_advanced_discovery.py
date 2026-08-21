"""Offline release tests for the Advanced Scientific Discovery Engine."""
from __future__ import annotations

from research_engine.advanced_discovery import (
    SafeNumericExecutor,
    ScientificDiscoveryEngine,
)
from research_engine.depth import get_depth_config
from research_engine.models import EvidencePack, SourceRecord, SourceType
from research_engine.planner import ResearchPlanner
from research_engine.research_memory import ResearchMemory


QUESTION = (
    "Kya room-temperature superconductivity ambient pressure par possible hai, "
    "aur kaunsa experiment is idea ko galat sabit karega?"
)


def _source(source_id: str, domain: str, title: str, text: str,
            read_level: str = "full_text") -> SourceRecord:
    source = SourceRecord(
        title=title,
        url=f"https://{domain}/{source_id.lower()}",
        snippet=text,
        connector="openalex",
        source_type=SourceType.PAPER,
        peer_reviewed=True,
        is_primary=True,
        read_level=read_level,
        full_text_chars=len(text) if read_level == "full_text" else 0,
        relevance_score=0.9,
        quality_score=0.85,
    )
    source.source_id = source_id
    return source


def _pack(full_text: bool = True) -> EvidencePack:
    level = "full_text" if full_text else "abstract"
    sources = [
        _source(
            "S1", "journal-a.example", "Hydride superconductivity under pressure",
            "Lanthanum hydrides show high critical temperatures under extreme pressure.", level),
        _source(
            "S2", "journal-b.example", "Replication limits of ambient superconductivity",
            "Independent replication did not confirm ambient-pressure room-temperature superconductivity.", level),
        _source(
            "S3", "journal-c.example", "Transport tests for superconducting phases",
            "Zero resistance and a Meissner response must both be measured with matched controls.", level),
    ]
    return EvidencePack(
        question=QUESTION,
        sources=sources,
        rounds_run=3,
        topic_terms=["superconductivity", "ambient", "pressure"],
        search_queries=["ambient pressure superconductivity", "replication criticism"],
    )


def _hypothesis() -> dict:
    return {
        "status": "UNTESTED HYPOTHESIS",
        "statement": "A metastable hydride phase may retain superconductivity after pressure release.",
        "simple": "Pressure se bani phase shayad pressure hatne ke baad kuch samay tikti rahe.",
        "reasoning": "High-pressure phase S1 mein report hui; ambient claim ko replication chahiye.",
        "supporting_evidence": "High-pressure hydride phase [S1] aur transport criteria [S3].",
        "contradicting_evidence": "Ambient-pressure replication fail hui [S2].",
        "novelty": "Pressure-release retention ko controlled time series mein test karta hai.",
        "assumptions": "Phase pressure release ke dauran turant decompose nahi hoti.",
        "prediction": {
            "variables": ["resistance", "magnetic susceptibility", "time after release"],
            "expected_outcome": "Both zero resistance and diamagnetic response persist after release.",
            "measurement_method": "Four-probe transport plus blinded magnetic susceptibility measurement.",
            "falsification_condition": "Either resistance remains finite or Meissner response is absent.",
        },
        "has_prediction": True,
        "how_to_test": "Use matched hydride samples, pressure-release time points and blinded controls.",
        "experiment": "Run repeated four-probe and magnetic measurements before and after pressure release.",
        "falsification_test": "Reject if either zero resistance or Meissner response is not reproduced.",
        "if_true": "A metastable path would merit independent materials replication.",
        "if_false": "The pressure-supported phase does not survive decompression.",
        "risks": "High-pressure apparatus needs qualified laboratory supervision.",
        "confidence_reasoning_based": "LOW",
        "missing_fields": [],
        "is_complete": True,
        "is_testable": True,
    }


def _analysis(full_text: bool = True) -> dict:
    planner = ResearchPlanner()
    plan = planner.plan(QUESTION, get_depth_config("MAXIMUM"))
    verification = {
        "status": "VERIFIED",
        "claim_checks": {"gate_passed": True},
    }
    return ScientificDiscoveryEngine(planner).analyze(
        question=QUESTION,
        plan=plan,
        pack=_pack(full_text),
        hypotheses=[_hypothesis()],
        contradictions=[{"summary": "S1 pressure support conflicts with S2 ambient replication", "sources": ["S1", "S2"]}],
        verification=verification,
    )


def test_safe_numeric_executor_runs_bounded_math():
    result = SafeNumericExecutor().evaluate("sqrt(x ** 2 + y ** 2)", {"x": 3, "y": 4})
    assert result == {"ok": True, "value": 5.0,
                      "expression": "sqrt(x ** 2 + y ** 2)"}


def test_safe_numeric_executor_rejects_arbitrary_python_and_attributes():
    executor = SafeNumericExecutor()
    for payload in (
        "__import__('os').system('id')",
        "open('/etc/passwd').read()",
        "(1).__class__",
        "[x for x in range(10)]",
    ):
        result = executor.evaluate(payload, {"x": 1})
        assert result["ok"] is False, payload
        assert result["error"] in {"unsupported_syntax", "unknown_name"}


def test_safe_numeric_executor_enforces_numeric_bounds():
    executor = SafeNumericExecutor()
    assert executor.evaluate("2 ** 100")["error"] == "power_out_of_bounds"
    assert executor.evaluate("1 / 0")["error"] == "division_by_zero"
    assert executor.evaluate("x + 1", {"x": float("inf")})["error"] == "variable_out_of_bounds"
    assert executor.evaluate("(-1) ** 0.5")["ok"] is False


def test_discovery_output_contains_every_advanced_layer():
    report = _analysis()
    assert report["status"] == "ASSESSMENT_READY"
    for key in (
        "problem_decomposition", "evidence_graph", "hypotheses", "tournament",
        "weakest_link", "alternative_paths", "recursive_research",
        "reality_ladder", "domain_validation", "simulation_executor",
    ):
        assert key in report
    assert report["human_review_required"] is True
    assert report["global_novelty_claimed"] is False
    assert report["real_world_success_probability_claimed"] is False


def test_problem_decomposition_uses_domain_branches_and_counter_evidence():
    block = _analysis()["problem_decomposition"]
    assert block["domain"] == "superconductivity"
    assert block["sub_questions"]
    assert block["domain_branches"]
    assert block["required_counter_evidence"] is True


def test_evidence_graph_only_uses_real_source_ids():
    graph = _analysis()["evidence_graph"]
    node_ids = {node["id"] for node in graph["nodes"]}
    assert {"S1", "S2", "S3", "H1"}.issubset(node_ids)
    assert {edge["from"] for edge in graph["edges"]}.issubset(node_ids)
    assert any(edge["relation"] == "supports" for edge in graph["edges"])
    assert any(edge["relation"] == "challenges" for edge in graph["edges"])


def test_novelty_screen_never_claims_global_novelty():
    novelty = _analysis()["hypotheses"][0]["novelty"]
    assert novelty["global_novelty_proven"] is False
    assert "global" in novelty["note"].lower() or "patent" in novelty["note"].lower()


def test_falsification_and_virtual_experiment_stay_design_only():
    entry = _analysis()["hypotheses"][0]
    assert entry["falsification"]["falsifiable"] is True
    assert entry["falsification"]["reject_if"]
    assert entry["experiment"]["status"] == "DESIGN_ONLY"
    assert entry["experiment"]["auto_execution_allowed"] is False


def test_confidence_is_capped_without_full_text_and_is_not_probability():
    confidence = _analysis(full_text=False)["hypotheses"][0]["confidence"]
    assert confidence["score"] <= 0.45
    assert confidence["real_world_success_probability"] is None
    assert any(cap["reason"] == "no full text was read" for cap in confidence["caps"])


def test_tournament_score_is_priority_not_truth_probability():
    tournament = _analysis()["tournament"]
    assert tournament["winner"] == "H1"
    assert tournament["ranking"][0]["rank"] == 1
    assert "probability" in tournament["ranking"][0]["note"]


def test_recursive_plan_is_bounded_and_never_auto_executes():
    loop = _analysis()["recursive_research"]
    assert loop["max_additional_iterations"] <= 2
    assert loop["execute_automatically"] is False


def test_reality_ladder_cannot_jump_to_deployment_from_literature():
    ladder = _analysis()["reality_ladder"]
    assert 1 <= ladder["level"] <= 3
    assert ladder["max_inferred_without_experiment"] == 3


def test_domain_validation_never_approves_real_world_use():
    validation = _analysis()["domain_validation"]
    assert validation["domain"] == "superconductivity"
    assert validation["passed_for_real_world_use"] is False
    assert "unit/physical-limit checks" in validation["requirements_before_real_world_use"]


def test_no_hypothesis_is_reported_honestly():
    planner = ResearchPlanner()
    report = ScientificDiscoveryEngine(planner).analyze(
        question=QUESTION,
        plan=planner.plan(QUESTION, get_depth_config("DEEP")),
        pack=_pack(),
        hypotheses=[],
        contradictions=[],
        verification={"status": "RESEARCH INCOMPLETE", "claim_checks": {"gate_passed": False}},
    )
    assert report["status"] == "NO_TESTABLE_HYPOTHESES"
    assert report["tournament"]["winner"] == ""
    assert report["reality_ladder"]["level"] == 1


def test_discovery_memory_is_compact_deduplicated_and_recalled(tmp_path):
    memory = ResearchMemory("advanced", directory=str(tmp_path))
    report = _analysis()
    memory.remember_discovery(QUESTION, report)
    memory.remember_discovery(QUESTION, report)
    assert memory.save() is True
    reloaded = ResearchMemory("advanced", directory=str(tmp_path))
    data = reloaded.load()
    assert len(data["discoveries"]) == 1
    assert "evidence_graph" not in data["discoveries"][0]
    assert reloaded.recall_discoveries(QUESTION)[0]["winner"] == "H1"
    assert "discovery checkpoint" in reloaded.context_note(QUESTION)


def test_legacy_memory_without_discoveries_key_still_loads_and_saves(tmp_path):
    memory = ResearchMemory("legacy", directory=str(tmp_path))
    memory._data = {
        "project_id": "legacy", "runs": [], "hypotheses": [],
        "dead_ends": [], "seen_urls": [],
    }
    assert memory.recall_discoveries(QUESTION) == []
    assert memory.save() is True
    assert ResearchMemory("legacy", directory=str(tmp_path)).load()["discoveries"] == []


def test_numeric_executor_policy_has_no_external_side_effects():
    policy = SafeNumericExecutor().policy_report()
    assert policy["arbitrary_python"] is False
    assert policy["imports"] is False
    assert policy["filesystem"] is False
    assert policy["network"] is False
    assert policy["subprocess"] is False
    assert policy["randomness"] is False
