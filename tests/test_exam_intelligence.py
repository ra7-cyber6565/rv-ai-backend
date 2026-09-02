"""Deterministic acceptance tests for the exam-intelligence engine.

The tests deliberately use dated synthetic papers.  They prove temporal
leakage, calibration honesty and source provenance without fetching a real exam
or pretending to know an examiner's private thoughts.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api import exam_routes
from research_engine.exam_intelligence import (
    ExamDataError,
    ExamIntelligenceEngine,
    ExamLedgerStore,
)
from utils.body_limit import request_body_limit


def _syllabus(count: int = 10):
    return [
        {
            "topic_id": f"T{i}",
            "subject": "Math" if i < count // 2 else "Reasoning",
            "chapter": f"Chapter {i // 2}",
            "topic": f"Topic {i}",
            "official_weight": 1.0,
        }
        for i in range(count)
    ]


def _paper(index: int, *, topic_count: int = 10, available_offset: int = 0):
    held = date(2016 + index, 1, 15)
    topic_ids = [f"T{index % topic_count}", f"T{(index + 2) % topic_count}"]
    return {
        "paper_id": f"P{index}",
        "held_on": held.isoformat(),
        "available_from": (held + timedelta(days=available_offset)).isoformat(),
        "source_id": f"OFFICIAL-P{index}",
        "source_url": f"https://exam.example.org/papers/{index}",
        "questions": [
            {
                "question_id": f"P{index}-Q{j}",
                "text": f"Official question {index}-{j} on {topic_id}",
                "topic_ids": [topic_id],
                "marks": 2,
                "question_type": "mcq" if j == 0 else "statement",
                "cognitive_level": "application" if j else "recall",
            }
            for j, topic_id in enumerate(topic_ids)
        ],
    }


def _analyze(papers, *, as_of="2030-01-01", syllabus=None, top_k=4, **extra):
    syllabus_published_at = extra.pop("syllabus_published_at", "2015-01-01")
    return ExamIntelligenceEngine().analyze(
        exam_name="Railway SI example",
        as_of=as_of,
        target_exam_date="2030-06-01",
        syllabus=syllabus or _syllabus(),
        papers=papers,
        syllabus_version="official-v1",
        syllabus_published_at=syllabus_published_at,
        top_k=top_k,
        **extra,
    )


def test_future_or_not_yet_available_paper_is_excluded_before_scoring():
    usable = _paper(0)
    future = _paper(14)
    result = _analyze([usable, future], as_of="2020-01-01")

    assert result["data_quality"]["usable_papers"] == 1
    assert result["leakage_guard"]["future_records_excluded"] == 1
    assert result["leakage_guard"]["passed"] is True
    assert all(row["paper_id"] != future["paper_id"] for row in result["source_ledger"])


def test_walk_forward_splits_train_only_on_information_available_before_holdout():
    papers = [_paper(i) for i in range(8)]
    result = _analyze(papers, as_of="2025-01-01")
    splits = result["walk_forward_backtest"]["splits"]

    assert splits
    for split in splits:
        assert split["latest_training_date"] < split["held_out_date"]
        assert split["training_paper_count"] >= 2
        assert split["future_information_used"] is False


def test_small_history_never_gets_a_fake_calibrated_probability():
    result = _analyze([_paper(i) for i in range(4)], as_of="2025-01-01")
    assert result["walk_forward_backtest"]["calibration"]["status"] == "NOT_CALIBRATED"
    assert all(row["calibrated_probability"] is None for row in result["study_priorities"])
    assert "probability" not in result["honesty_boundary"]["allowed_claims"]


def test_sufficient_walk_forward_history_exposes_empirical_intervals_not_certainty():
    result = _analyze([_paper(i) for i in range(10)], as_of="2030-01-01")
    calibration = result["walk_forward_backtest"]["calibration"]
    assert calibration["status"] == "CALIBRATED_ON_WALK_FORWARD_HISTORY"
    assert calibration["outcome_pairs"] >= 60
    assert calibration["method"] == "fixed-bin empirical frequency with Wilson interval"
    estimated = [row for row in result["study_priorities"] if row["calibrated_probability"]]
    assert estimated
    for row in estimated:
        estimate = row["calibrated_probability"]
        assert 0 <= estimate["observed_frequency"] <= 1
        assert estimate["interval_low"] <= estimate["observed_frequency"] <= estimate["interval_high"]
        assert estimate["label"] == "BACKTEST-OBSERVED FREQUENCY — NOT A GUARANTEE"


def test_examiner_section_reports_observable_patterns_not_mind_reading():
    result = _analyze([_paper(i) for i in range(8)], as_of="2025-01-01")
    pattern = result["examiner_pattern_analysis"]
    combined = repr(pattern).lower()
    assert pattern["inference_boundary"] == "OBSERVABLE PAPER-SELECTION PATTERNS ONLY"
    assert "private thought" in combined
    assert "mind read" not in combined
    assert "confirmed" not in combined


def test_original_exam_hypotheses_are_separate_and_falsifiable():
    result = _analyze([_paper(i) for i in range(9)], as_of="2030-01-01")
    hypotheses = result["app_original_exam_hypotheses"]
    assert hypotheses
    assert all(row["label"] == "APP-ORIGINAL EXAM HYPOTHESIS" for row in hypotheses)
    assert all(row["status"] == "UNTESTED — TEST NEXT" for row in hypotheses)
    for row in hypotheses:
        for field in (
            "falsification_rule", "prospective_test", "primary_endpoint",
            "analysis_metric", "success_threshold", "failure_threshold",
            "replication_plan", "safety_ethics", "strongest_counterevidence",
        ):
            assert row[field], (row["hypothesis_id"], field)
        assert row["human_review_required"] is True
    assert "app_original_exam_hypotheses" not in result["existing_evidence"]


def test_unknown_topic_mapping_fails_closed_instead_of_silent_guessing():
    bad = _paper(0)
    bad["questions"][0]["topic_ids"] = ["NOT-IN-SYLLABUS"]
    with pytest.raises(ExamDataError, match="unknown syllabus topic"):
        _analyze([bad])


def test_paper_claimed_available_before_exam_is_blocked_as_possible_leak():
    paper = _paper(0)
    paper["available_from"] = "2015-01-01"
    with pytest.raises(ExamDataError, match="possible leaked"):
        _analyze([paper])


def test_syllabus_published_after_backtest_period_blocks_calibration_claim():
    result = _analyze(
        [_paper(i) for i in range(10)],
        as_of="2030-01-01",
        syllabus_published_at="2028-01-01",
    )
    assert result["leakage_guard"]["syllabus_hindsight_risk"] is True
    assert result["walk_forward_backtest"]["calibration"]["status"] == "BLOCKED_BY_SYLLABUS_HINDSIGHT_RISK"
    assert all(row["calibrated_probability"] is None for row in result["study_priorities"])


def test_source_ledger_preserves_exact_paper_provenance_and_access_assumptions():
    paper = _paper(0)
    paper.pop("available_from")
    result = _analyze([paper])
    ledger = result["source_ledger"]
    assert ledger[0]["source_id"] == "OFFICIAL-P0"
    assert ledger[0]["source_url"] == "https://exam.example.org/papers/0"
    assert ledger[0]["availability_assumption"] == "held_on used because available_from was not supplied"
    assert result["data_quality"]["availability_dates_assumed"] == 1
    assert "NOT INDEPENDENTLY FETCHED" in ledger[0]["source_reference_status"]


def test_unknown_availability_dates_block_probability_even_with_many_papers():
    papers = [_paper(i) for i in range(10)]
    for paper in papers:
        paper.pop("available_from")
    result = _analyze(papers, as_of="2030-01-01")
    assert result["walk_forward_backtest"]["calibration"]["status"] == \
        "BLOCKED_BY_UNKNOWN_AVAILABILITY_DATES"
    assert all(row["calibrated_probability"] is None
               for row in result["study_priorities"])


def test_chapter_and_question_pattern_outputs_are_not_exact_question_predictions():
    result = _analyze([_paper(i) for i in range(8)], as_of="2025-01-01")
    assert result["chapter_priorities"]
    assert result["question_pattern_blueprint"]
    assert all(
        row["score_label"] == "AGGREGATED STUDY PRIORITY — NOT PROBABILITY"
        for row in result["chapter_priorities"]
    )
    assert all("exact question predict nahi" in row["practice_rule"]
               for row in result["question_pattern_blueprint"])


def test_backtest_compares_model_against_frozen_raw_frequency_baseline():
    result = _analyze([_paper(i) for i in range(9)], as_of="2030-01-01")
    backtest = result["walk_forward_backtest"]
    assert backtest["mean_raw_frequency_baseline_recall"] is not None
    assert backtest["mean_recall_delta_vs_raw_frequency"] is not None
    assert all("recall_delta_vs_raw_frequency" in split for split in backtest["splits"])


def test_private_source_url_is_not_echoed_to_the_public_result():
    paper = _paper(0)
    paper["source_url"] = "http://127.0.0.1/private-paper"
    result = _analyze([paper])
    assert result["source_ledger"][0]["source_url"] == ""
    assert "UNSAFE_SOURCE_URL_REMOVED" in result["source_ledger"][0]["warnings"]


def test_ledger_store_is_project_isolated_bounded_and_returns_latest(tmp_path):
    store = ExamLedgerStore(root=tmp_path, max_records_per_project=2)
    first = {"analysis_id": "A1", "value": 1}
    second = {"analysis_id": "A2", "value": 2}
    third = {"analysis_id": "A3", "value": 3}
    store.save("project-one", first)
    store.save("project-one", second)
    store.save("project-one", third)
    store.save("project-two", {"analysis_id": "B1"})

    assert store.latest("project-one")["analysis_id"] == "A3"
    assert [row["analysis_id"] for row in store.history("project-one")] == ["A2", "A3"]
    assert store.latest("project-two")["analysis_id"] == "B1"


def test_corrupt_exam_ledger_fails_closed_instead_of_erasing_history(tmp_path):
    store = ExamLedgerStore(root=tmp_path)
    path = store._path("project-one")
    # pytest's ``tmp_path`` already exists; keep this setup portable across
    # local and GitHub-hosted runners while still creating missing parents.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ExamDataError, match="corrupted"):
        store.save("project-one", {"analysis_id": "A1"})
    assert path.read_text(encoding="utf-8") == "{not valid json"


def test_exam_route_guards_before_engine_and_never_exposes_storage_path(monkeypatch, tmp_path):
    called = {"engine": 0}

    def deny(*_args):
        raise HTTPException(status_code=404, detail="Project session nahi mila")

    class SpyEngine:
        def analyze(self, **_kwargs):
            called["engine"] += 1
            return {}

    monkeypatch.setattr(exam_routes, "require_project_access", deny)
    monkeypatch.setattr(exam_routes, "ExamIntelligenceEngine", lambda: SpyEngine())
    request = exam_routes.ExamIntelligenceRequest(
        exam_name="RPF SI",
        project_id="p_" + "x" * 24,
        as_of="2030-01-01",
        syllabus=_syllabus(4),
        papers=[_paper(0, topic_count=4)],
    )
    with pytest.raises(HTTPException) as exc:
        exam_routes.analyze_exam(request, "wrong")
    assert exc.value.status_code == 404
    assert called["engine"] == 0


def test_exam_request_schema_and_raw_body_are_bounded():
    with pytest.raises(ValidationError):
        exam_routes.ExamIntelligenceRequest(
            exam_name="x" * 201,
            project_id="p_" + "x" * 24,
            syllabus=_syllabus(2),
            papers=[_paper(0, topic_count=2)],
        )
    assert request_body_limit("POST", "/api/v1/exam-intelligence/analyze") == 4 * 1024 * 1024
