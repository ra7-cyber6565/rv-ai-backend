from types import SimpleNamespace

from research_engine.depth import get_depth_config
from research_engine.models import ResearchResult
from research_engine.research_assurance import build_research_assurance
from research_engine.synthesizer import FinalSynthesizer


def _pack(independent=8, sources=12):
    return SimpleNamespace(
        sources=[object() for _ in range(sources)],
        independent_source_count=independent,
    )


def _discovered(*, rounds=5, counter=True):
    return {
        "rounds_run": rounds,
        "counter_search_performed": counter,
        "axis_coverage": [
            {"axis_id": "mechanism", "mandatory": True, "status": "COVERED"},
            {"axis_id": "replication", "mandatory": True, "status": "MISSING"},
            {"axis_id": "counter_evidence", "mandatory": True, "status": "COVERED"},
        ],
        "round_metrics": [
            {"round": n, "new_unique_urls": 1 if n < 4 else 0}
            for n in range(1, rounds + 1)
        ],
    }


def _passes(done=True):
    planned = ["analysis", "critique", "hypothesis", "synthesis"]
    return {"planned_passes": planned,
            "done_passes": planned if done else planned[:-1]}


def _verification(passed=3, total=3):
    return {"claim_checks": {
        "critical_claims": total,
        "critical_claims_same_source_ae_passed": passed,
        "unsupported_critical_claims": 0,
        "unverifiable_critical_claims": 0,
        "critical_contradicted_claims": 0,
    }}


def _advanced(*, safe=True):
    return {"hypotheses": [{
        "falsification": {"falsifiable": True},
        "confidence": {"real_world_success_probability": None if safe else 0.95},
        "experiment": {"auto_execution_allowed": False},
    }]}


def _report(**overrides):
    args = {
        "config": get_depth_config("MARATHON"),
        "pack": _pack(),
        "discovered": _discovered(),
        "reading": {"succeeded": 8},
        "passes": _passes(),
        "verification": _verification(),
        "discovery_analysis": _advanced(),
    }
    args.update(overrides)
    return build_research_assurance(**args)


def test_marathon_preset_is_deeper_but_bounded():
    config = get_depth_config("MARATHON")
    assert config.max_sources == 40
    assert config.max_rounds == 5
    assert config.max_fulltext == 16
    assert config.discovery_seconds == 360
    assert config.require_all_rounds is True
    assert config.research_process_target_percent == 90


def test_complete_process_meets_target_without_truth_claim():
    report = _report()
    assert report["target_met"] is True
    assert report["research_process_coverage_percent"] == 100.0
    assert report["global_exhaustiveness_claimed"] is False
    assert report["hypothesis_success_probability_claimed"] is False
    assert "truth probability" in report["not_a_probability"]
    assert report["saturation"]["status"] == "BOUNDED_SATURATION_SIGNAL"


def test_mandatory_gap_blocks_target_even_if_score_reaches_threshold():
    report = _report(discovered=_discovered(counter=False))
    assert report["research_process_coverage_percent"] == 90.0
    assert report["target_met"] is False
    assert "counter_search" in report["mandatory_gaps"]


def test_unfinished_rounds_and_reasoning_are_fail_closed():
    report = _report(discovered=_discovered(rounds=3), passes=_passes(done=False))
    assert report["target_met"] is False
    assert "all_search_rounds" in report["mandatory_gaps"]
    assert "reasoning_passes" in report["mandatory_gaps"]
    assert report["saturation"]["status"] == "ROUNDS_INCOMPLETE"


def test_source_count_cannot_hide_shallow_reading():
    report = _report(pack=_pack(independent=20, sources=40),
                     reading={"succeeded": 2})
    assert report["target_met"] is False
    assert "legal_full_text" in report["mandatory_gaps"]


def test_hypothesis_probability_claim_fails_testability_component():
    report = _report(discovery_analysis=_advanced(safe=False))
    assert report["target_met"] is False
    assert "hypothesis_testability" in report["mandatory_gaps"]


def test_non_marathon_modes_do_not_invent_a_percentage():
    report = _report(config=get_depth_config("MAXIMUM"))
    assert report["active"] is False
    assert "research_process_coverage_percent" not in report


def test_assurance_survives_api_serialization_and_is_honest_in_audit_text():
    assurance = _report()
    payload = ResearchResult(research_assurance=assurance).to_dict()
    assert payload["research_assurance"]["target_met"] is True

    fake_pack = SimpleNamespace(sources=[], quality_signal_note=lambda: "")
    text = FinalSynthesizer()._coverage_section({
        "research_assurance": assurance,
        "sources_used": 0,
        "independent_sources": 0,
        "research_rounds": 5,
    }, fake_pack)
    assert "MARATHON research-process coverage: 100.0%" in text
    assert "truth probability" in text
    assert "profitability" in text
