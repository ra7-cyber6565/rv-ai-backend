"""P0-C: live release gate must not accept vacuous/post-hoc claim success."""
from __future__ import annotations

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import run_live_zero_cost_gate as live


def _base_result():
    return {
        "status": "COMPLETE",
        "coverage": {"on_topic_sources": 3, "full_text_sources_read": 1},
        "verification": {
            "claim_checks": {
                "gate_passed": True,
                "strong_claims_checked": 1,
                "strong_claims_passed": 1,
                "critical_claims": 1,
                "critical_claims_same_source_ae_passed": 1,
                "claim_verification_achievement": True,
                "critical_claim_coverage_complete": True,
                "unsupported_critical_claims": 0,
                "unverifiable_critical_claims": 0,
                "critical_contradicted_claims": 0,
            },
            "evidence_first_audit": {
                "evidence_first_required": True,
                "preselected_evidence_spans_count": 3,
                "preselected_strong_eligible_spans": 2,
                "critical_claims_preselected_span_matched": 1,
                "critical_claims_preselected_span_unmatched": 0,
                "critical_claim_preselection_complete": True,
                "evidence_first_achievement": True,
            },
        },
        "sources": [{"id": "S1"}, {"id": "S2"}, {"id": "S3"}],
        "invalid_citations": [],
        "citations": [{"source_id": "S1"}],
        "hypotheses": [{"id": "H1"}, {"id": "H2"}, {"id": "H3"}],
        "discovery": {
            "status": "ASSESSMENT_READY",
            "tournament": {"winner": "H1"},
            "global_novelty_claimed": False,
            "real_world_success_probability_claimed": False,
            "human_review_required": True,
        },
        "evidence_level": "MIXED",
        "answer": "Safe structural fixture answer [S1]",
        "warnings": [],
        "api_accounting": {},
    }


def _checks(evaluation):
    return {row["name"]: row for row in evaluation["checks"]}


def test_complete_nonvacuous_preselected_fixture_passes_live_gate():
    evaluation = live.evaluate_result(_base_result())
    checks = _checks(evaluation)
    assert evaluation["passed"] is True
    assert checks["claim_gate"]["passed"] is True
    assert checks["claim_verification_achievement"]["passed"] is True
    assert checks["critical_claim_coverage"]["passed"] is True
    assert checks["evidence_first_achievement"]["passed"] is True


def test_vacuous_zero_over_zero_claim_gate_fails_live_release():
    result = _base_result()
    claims = result["verification"]["claim_checks"]
    claims.update({
        "gate_passed": True,
        "strong_claims_checked": 0,
        "strong_claims_passed": 0,
        "critical_claims": 0,
        "critical_claims_same_source_ae_passed": 0,
        "claim_verification_achievement": False,
    })
    audit = result["verification"]["evidence_first_audit"]
    audit.update({
        "critical_claims_preselected_span_matched": 0,
        "critical_claim_preselection_complete": True,
        "evidence_first_achievement": False,
    })
    evaluation = live.evaluate_result(result)
    checks = _checks(evaluation)
    assert checks["claim_gate"]["passed"] is True  # safety only
    assert checks["claim_verification_achievement"]["passed"] is False
    assert checks["evidence_first_achievement"]["passed"] is False
    assert evaluation["passed"] is False


def test_same_source_claim_without_preselection_fails_live_release():
    result = _base_result()
    audit = result["verification"]["evidence_first_audit"]
    audit.update({
        "critical_claims_preselected_span_matched": 0,
        "critical_claims_preselected_span_unmatched": 1,
        "critical_claim_preselection_complete": False,
        "evidence_first_achievement": False,
    })
    evaluation = live.evaluate_result(result)
    checks = _checks(evaluation)
    assert checks["claim_verification_achievement"]["passed"] is True
    assert checks["evidence_first_achievement"]["passed"] is False
    assert evaluation["passed"] is False


def test_partial_three_of_six_critical_coverage_fails_live_release():
    """The live 3/6 incident must never be reported as a release PASS again."""
    result = _base_result()
    claims = result["verification"]["claim_checks"]
    claims.update({
        "critical_claims": 6,
        "critical_claims_same_source_ae_passed": 3,
        "claim_verification_achievement": True,
        "critical_claim_coverage_complete": False,
        "unsupported_critical_claims": 2,
        "unverifiable_critical_claims": 1,
        "critical_contradicted_claims": 0,
    })
    evaluation = live.evaluate_result(result)
    checks = _checks(evaluation)
    assert checks["claim_verification_achievement"]["passed"] is True
    assert checks["critical_claim_coverage"]["passed"] is False
    assert "3/6" in checks["critical_claim_coverage"]["detail"]
    assert evaluation["passed"] is False


def test_missing_p0b_audit_fails_closed_not_legacy_passes():
    result = _base_result()
    del result["verification"]["evidence_first_audit"]
    evaluation = live.evaluate_result(result)
    checks = _checks(evaluation)
    assert checks["evidence_first_achievement"]["passed"] is False
    assert evaluation["passed"] is False


def test_receipt_summary_contains_only_structural_evidence_metrics():
    result = _base_result()
    secret_passage = "PRIVATE SOURCE PASSAGE MUST NOT ENTER RECEIPT"
    result["verification"]["evidence_first_audit"]["claim_matches"] = [{
        "claim_id": "CL001",
        "passage": secret_passage,
        "source_url": "https://private.example/secret",
    }]
    evaluation = live.evaluate_result(result)
    summary = evaluation["summary"]
    assert summary["critical_claims"] == 1
    assert summary["critical_claims_same_source_ae_passed"] == 1
    assert summary["claim_verification_achievement"] is True
    assert summary["critical_claim_coverage_complete"] is True
    assert summary["unsupported_critical_claims"] == 0
    assert summary["unverifiable_critical_claims"] == 0
    assert summary["critical_contradicted_claims"] == 0
    assert summary["evidence_first_required"] is True
    assert summary["preselected_evidence_spans_count"] == 3
    assert summary["preselected_strong_eligible_spans"] == 2
    assert summary["critical_claims_preselected_span_matched"] == 1
    assert summary["critical_claims_preselected_span_unmatched"] == 0
    assert summary["critical_claim_preselection_complete"] is True
    assert summary["evidence_first_achievement"] is True
    rendered = repr(summary)
    assert secret_passage not in rendered
    assert "private.example" not in rendered
    assert "passage" not in summary
    assert "claim_matches" not in summary


def test_mutating_only_achievement_boolean_breaks_gate():
    result = _base_result()
    mutated = copy.deepcopy(result)
    mutated["verification"]["claim_checks"]["claim_verification_achievement"] = False
    evaluation = live.evaluate_result(mutated)
    assert _checks(evaluation)["claim_verification_achievement"]["passed"] is False
    assert evaluation["passed"] is False
