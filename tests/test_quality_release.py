"""The final quality score is enforced, not merely reported."""
from __future__ import annotations

import copy

from api import job_routes
from research_engine.quality_release import enforce_quality_release


def _answer(*, verified: bool = False) -> str:
    parts = [
        "## Seedha jawab\n\nDirect supported answer.",
        "## Research se kya pata chala?\n\nEstablished result [S1].",
        "## Evidence kya kehta hai?\n\nSupport [S1], counter context [S2].",
        "## Iske against kya mila?\n\nIndependent counter-search result [S2].",
        "## Kya abhi unknown hai?\n\nBounded unknowns.",
        "## Final conclusion\n\nEvidence-based conclusion.",
        "## Sources\n\n[S1] primary one; [S2] primary two.",
    ]
    if verified:
        parts.append("Evidence ka level: ✅ VERIFIED — do sources")
    return "\n\n".join(parts)


def _source(source_id: str, relevance: float = 0.9) -> dict:
    return {
        "source_id": source_id,
        "title": f"Relevant primary {source_id}",
        "url": f"https://example.org/{source_id}",
        "relevance_score": relevance,
        "read_level": "full_text",
    }


def _complete_result(*, verified: bool = False) -> dict:
    return {
        "status": "COMPLETE",
        "answer": _answer(verified=verified),
        "evidence_level": "✅ VERIFIED" if verified else "MODERATE EVIDENCE",
        "sources": [_source("S1"), _source("S2", 0.85)],
        "requested_ledger": {"items": [], "unmet": []},
        "verification": {"invalid_citations": [], "fabricated_citations": 0},
        "label_report": {"a_e_failed": 0, "entailment_blocked": 0},
        "contradictions": [],
        "hypotheses": [],
        "coverage": {
            "avg_relevance": 0.875,
            "on_topic_sources": 2,
            "directly_relevant_sources": 2,
            "sources_retrieved": 2,
            "sources_cited": 2,
            "sources_supporting_critical_claims": 2,
            "retracted_sources": 0,
        },
        "quality_contract": {
            "hypotheses_requested": 0,
            "original_hypotheses_required": False,
            "calculations_required": False,
            "counter_search_required": True,
        },
        "quality_context": {
            "counter_search_performed": True,
            "directly_relevant_sources": 2,
            "sources_retrieved": 2,
            "sources_cited": 2,
            "sources_supporting_critical_claims": 2,
            "unsupported_critical_claims": 0,
            "critical_no_source_claims": 0,
            "access_depth_mismatches": 0,
            "critical_claim_spans_complete": True,
            "critical_claim_evidence_spans": [
                {"claim_id": "C1", "source_id": "S1", "passage": "Exact support"}
            ],
            "numeric_confidence_calibrated": False,
            "recovery_used": False,
        },
    }


def _issue_codes(response: dict) -> set[str]:
    return {item["code"] for item in response["quality_gate"]["issues"]}


def test_clean_complete_result_passes_100_without_repair():
    original = _complete_result()
    response = enforce_quality_release(original)
    assert response["quality_gate"]["score"] == 100
    assert response["quality_gate"]["release_ready"] is True
    assert response["quality_repairs"] == []
    assert response["status"] == "COMPLETE"
    assert response["evidence_level"] == "MODERATE EVIDENCE"


def test_enforcement_never_mutates_persisted_original_even_deeply():
    original = _complete_result(verified=True)
    before = copy.deepcopy(original)
    response = enforce_quality_release(original)
    assert original == before
    assert response is not original
    assert response["quality_context"] is not original["quality_context"]


def test_false_verified_badge_and_evidence_level_are_actually_downgraded():
    result = _complete_result(verified=True)
    result["quality_context"]["counter_search_performed"] = False
    response = enforce_quality_release(result)
    assert response["quality_gate"]["verified_allowed"] is False
    assert response["quality_gate"]["score"] <= 30
    assert "FALSE_VERIFIED_BADGE" in _issue_codes(response)
    assert "VERIFIED" not in response["evidence_level"]
    assert "✅ VERIFIED" not in response["answer"]
    assert "UNCONFIRMED" in response["answer"]
    assert response["quality_repairs"] == [
        "evidence_level_downgraded",
        "answer_verified_badge_downgraded",
    ]


def test_complete_status_becomes_partial_when_mandatory_section_is_missing():
    result = _complete_result()
    result["answer"] = result["answer"].replace("## Kya abhi unknown hai?", "### Small limit note")
    response = enforce_quality_release(result)
    assert response["status"] == "PARTIAL"
    assert response["quality_gate"]["answer_complete"] is False
    assert "MANDATORY_SECTION_MISSING" in _issue_codes(response)
    assert "answer_status_downgraded_to_partial" in response["quality_repairs"]
    assert response["status_reason"].startswith("Final quality gate:")


def test_quality_release_is_idempotent():
    result = _complete_result(verified=True)
    result["quality_context"]["counter_search_performed"] = False
    first = enforce_quality_release(result)
    second = enforce_quality_release(first)
    assert second == first
    assert second["answer"].count("UNCONFIRMED — final quality gate") == 1


def test_legacy_result_gets_gate_without_inventing_a_pass_or_rewriting_plain_answer():
    result = {"answer": "legacy final answer", "sources": []}
    response = enforce_quality_release(result)
    assert response["answer"] == "legacy final answer"
    assert response["quality_gate"]["release_ready"] is False
    assert response["quality_gate"]["verified_allowed"] is False
    assert "NO_SOURCES" in _issue_codes(response)
    assert response["quality_enforced"] is True


def test_no_source_inside_original_hypothesis_is_not_counted_as_main_claim():
    result = _complete_result()
    result["answer"] = result["answer"].replace(
        "## Sources",
        "## APP ORIGINAL RESEARCH LAB\n\nAssumption [NO-SOURCE].\n\n## Sources",
    )
    result["quality_context"].pop("critical_no_source_claims")
    response = enforce_quality_release(result)
    assert "CRITICAL_NO_SOURCE_CLAIM" not in _issue_codes(response)


def test_no_source_in_main_sourced_answer_is_counted_and_blocks_release():
    result = _complete_result()
    result["answer"] = result["answer"].replace(
        "Established result [S1].", "Unsupported critical result [NO-SOURCE]."
    )
    result["quality_context"].pop("critical_no_source_claims")
    response = enforce_quality_release(result)
    assert "CRITICAL_NO_SOURCE_CLAIM" in _issue_codes(response)
    assert response["quality_gate"]["verified_allowed"] is False


def test_boundary_computes_exact_retrieved_and_cited_counts_without_overwriting_producer_values():
    result = _complete_result()
    result["quality_context"].pop("sources_retrieved")
    result["quality_context"].pop("sources_cited")
    response = enforce_quality_release(result)
    assert response["quality_context"]["sources_retrieved"] == 2
    assert response["quality_context"]["sources_cited"] == 2

    result2 = _complete_result()
    result2["quality_context"]["sources_cited"] = 1
    response2 = enforce_quality_release(result2)
    assert response2["quality_context"]["sources_cited"] == 1


def test_relevance_fallback_uses_strict_boundary_threshold_not_old_point_25_floor():
    result = _complete_result()
    result["sources"] = [_source("S1", 0.64), _source("S2", 0.90)]
    result["quality_context"].pop("directly_relevant_sources")
    response = enforce_quality_release(result)
    assert response["quality_context"]["directly_relevant_sources"] == 1


def test_recovered_result_preserves_available_progress_snapshot():
    result = _complete_result()
    progress = {"available": True, "current_stage": "COMPLETE", "log": []}
    response = enforce_quality_release(result, recovery_used=True, progress_snapshot=progress)
    assert response["quality_context"]["recovery_used"] is True
    assert response["quality_context"]["progress_snapshot_preserved"] is True
    assert "RECOVERY_PROGRESS_MISSING" not in _issue_codes(response)


def test_recovered_result_without_progress_snapshot_is_blocked():
    response = enforce_quality_release(
        _complete_result(),
        recovery_used=True,
        progress_snapshot={"available": False},
    )
    assert response["quality_context"]["progress_snapshot_preserved"] is False
    assert "RECOVERY_PROGRESS_MISSING" in _issue_codes(response)


def test_job_result_route_enforces_quality_on_copy_after_progress_is_attached(monkeypatch):
    stored = _complete_result(verified=True)
    stored["quality_context"]["counter_search_performed"] = False
    before = copy.deepcopy(stored)
    monkeypatch.setattr(
        job_routes,
        "_authorized_job",
        lambda *args, **kwargs: {
            "job_id": "job-safe",
            "status": "completed",
            "result": stored,
        },
    )
    monkeypatch.setattr(
        job_routes,
        "get_progress",
        lambda _job_id: {
            "current_stage": "COMPLETE",
            "stages_done": len(job_routes.STAGES),
            "log": [{"stage": "COMPLETE", "note": "answer ready"}],
        },
    )

    response = job_routes.research_job_result("job-safe", "opaque-token")

    assert stored == before
    assert response["research_progress"]["available"] is True
    assert response["quality_enforced"] is True
    assert response["quality_gate"]["verified_allowed"] is False
    assert "✅ VERIFIED" not in response["answer"]


def test_job_result_route_leaves_non_dict_legacy_payload_unchanged(monkeypatch):
    monkeypatch.setattr(
        job_routes,
        "_authorized_job",
        lambda *args, **kwargs: {
            "job_id": "job-safe",
            "status": "completed",
            "result": "legacy string result",
        },
    )
    assert job_routes.research_job_result("job-safe", "opaque-token") == "legacy string result"
