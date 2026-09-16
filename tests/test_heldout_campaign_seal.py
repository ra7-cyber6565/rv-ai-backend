from __future__ import annotations

import copy

import pytest

from tools import heldout_campaign_seal as seal
from utils.research_runtime import digest

BASE = "1" * 40
CAND = "2" * 40


def _pack():
    return {
        "schema_version": 1,
        "task_pack_id": "holdout-v1",
        "split": "untouched_holdout",
        "used_for_tuning": False,
        "tasks": [
            {"task_id": "t1", "question": "Question one"},
            {"task_id": "t2", "question": "Question two"},
        ],
    }


def _capture(revision, prefix):
    rows = []
    for i, task_id in enumerate(("t1", "t2")):
        rows.append({
            "task_id": task_id,
            "trial": 0,
            "revision": revision,
            "execution_kind": "LIVE",
            "mode": "MAXIMUM",
            "http_budget": 24,
            "seconds_budget": 60.0,
            "latency_seconds": 3.0 + i,
            "output_sha256": digest({"output": f"{prefix}-{i}"}),
            "actual_http_attempts": 8,
            "logical_reasoning_calls": 7,
            "architecture_pass": True,
            "raw_result": {"answer": f"PRIVATE {prefix} answer {i}"},
        })
    return {
        "schema_version": 1,
        "kind": "HELDOUT_BLIND_GENERATION_CAPTURE_PRIVATE",
        "split": "untouched_holdout",
        "used_for_tuning": False,
        "task_pack_sha256": digest(_pack()),
        "revision": revision,
        "execution_kind": "LIVE",
        "mode": "MAXIMUM",
        "rows": rows,
    }


def _grades(capture, score, grader="HUMAN"):
    rows = []
    for row in capture["rows"]:
        rows.append({
            "task_id": row["task_id"],
            "trial": row["trial"],
            "output_sha256": row["output_sha256"],
            "grader": grader,
            "task_success": score,
            "coverage": 0.9,
            "citation_support": 0.9,
            "abstention_appropriate": 0.9,
            "private_rationale": "PRIVATE GRADER NOTES",
        })
    return {"schema_version": 1, "rows": rows}


def _build(**overrides):
    pack = _pack()
    base = _capture(BASE, "base")
    cand = _capture(CAND, "cand")
    grader_spec = {"schema_version": 1, "grader": "human-v1", "rubric_version": "frozen"}
    kwargs = dict(
        task_pack=pack,
        expected_task_pack_sha256=digest(pack),
        baseline_capture=base,
        candidate_capture=cand,
        baseline_grades=_grades(base, 0.5),
        candidate_grades=_grades(cand, 0.8),
        grader_spec=grader_spec,
        expected_grader_spec_sha256=digest(grader_spec),
        campaign_id="campaign-001",
        attest_outputs_frozen_before_grading=True,
        attest_targets_hidden_during_generation=True,
        attest_grader_frozen_before_candidate_scoring=True,
    )
    kwargs.update(overrides)
    return seal.build_release_inputs(**kwargs)


def test_seal_emits_release_gate_rows_without_private_output_or_grade_text():
    manifest, baseline, candidate, campaign, receipt = _build()
    blob = str((manifest, baseline, candidate, campaign, receipt))
    assert "Question one" not in blob
    assert "PRIVATE base answer" not in blob
    assert "PRIVATE cand answer" not in blob
    assert "PRIVATE GRADER NOTES" not in blob
    assert manifest["task_ids"] == ["t1", "t2"]
    assert campaign["baseline_revision"] == BASE
    assert campaign["candidate_revision"] == CAND
    assert len(baseline) == len(candidate) == 2
    assert all(row["grader"] == "HUMAN" for row in baseline + candidate)
    assert all(len(row["grade_sha256"]) == 64 for row in baseline + candidate)
    assert receipt["raw_outputs_in_receipt"] is False
    assert receipt["raw_grades_in_receipt"] is False
    assert receipt["release_decision_performed"] is False


def test_grade_must_bind_exact_captured_output_hash():
    pack = _pack()
    base = _capture(BASE, "base")
    bad_grades = _grades(base, 0.5)
    bad_grades["rows"][0]["output_sha256"] = "a" * 64
    with pytest.raises(seal.CampaignSealError, match="not bound"):
        _build(baseline_capture=base, baseline_grades=bad_grades)


def test_paired_budget_mismatch_fails_closed():
    cand = _capture(CAND, "cand")
    cand["rows"][0]["http_budget"] = 25
    with pytest.raises(seal.CampaignSealError, match="matched budgets"):
        _build(candidate_capture=cand, candidate_grades=_grades(cand, 0.8))


def test_same_revision_and_coverage_mismatch_fail_closed():
    cand = _capture(BASE, "cand")
    with pytest.raises(seal.CampaignSealError, match="must differ"):
        _build(candidate_capture=cand, candidate_grades=_grades(cand, 0.8))

    cand = _capture(CAND, "cand")
    cand["rows"].pop()
    with pytest.raises(seal.CampaignSealError, match="coverage differs"):
        _build(candidate_capture=cand, candidate_grades=_grades(cand, 0.8))


def test_false_attestation_and_mutated_grader_spec_are_rejected():
    with pytest.raises(seal.CampaignSealError, match="attestations"):
        _build(attest_grader_frozen_before_candidate_scoring=False)

    spec = {"schema_version": 1, "grader": "human-v1", "rubric_version": "changed"}
    with pytest.raises(seal.CampaignSealError, match="grader spec changed"):
        _build(grader_spec=spec)


def test_grader_provenance_must_match_within_each_pair():
    cand = _capture(CAND, "cand")
    cand_grades = _grades(cand, 0.8, grader="DETERMINISTIC")
    with pytest.raises(seal.CampaignSealError, match="same grader provenance"):
        _build(candidate_capture=cand, candidate_grades=cand_grades)


def test_private_grade_note_changes_grade_hash_without_leaking_note():
    manifest, baseline1, candidate1, campaign, receipt = _build()
    base = _capture(BASE, "base")
    grades = _grades(base, 0.5)
    grades2 = copy.deepcopy(grades)
    grades2["rows"][0]["private_rationale"] = "different private rationale"
    _, baseline2, _, _, _ = _build(baseline_capture=base, baseline_grades=grades2)
    assert baseline1[0]["grade_sha256"] != baseline2[0]["grade_sha256"]
    assert "different private rationale" not in str(baseline2)
