"""Production evidence-before-generation checks must fail closed."""
from __future__ import annotations

from dataclasses import replace

from research_engine import final_quality_gate as FQ
from research_engine.requested import quality_contract


class _Depth:
    name = "DEEP"


def _base_context() -> dict:
    return {
        "unsupported_critical_claims": 0,
        "critical_no_source_claims": 0,
        "access_depth_mismatch_count": 0,
        "critical_claim_spans_complete": True,
        "critical_claim_evidence_spans": [{"claim_id": "CL001"}],
        "critical_claims": 1,
        "critical_claims_same_source_ae_passed": 1,
        "claim_verification_achievement": True,
        "critical_claim_coverage_complete": True,
        "unverifiable_critical_claims": 0,
        "critical_contradicted_claims": 0,
    }


def _run_claim_gate(ctx: dict, spec: FQ.QualityContract):
    state = FQ._Evaluation()
    FQ.FinalQualityGate._check_claims(
        state,
        "## Seedha jawab\n[ESTABLISHED FACT] bounded claim [S1]",
        {"fabricated_citations": 0},
        {"a_e_failed": 0, "entailment_blocked": 0},
        ctx,
        spec,
    )
    return state, {issue.code for issue in state.issues}


def test_production_request_contract_requires_evidence_first_audit():
    raw = quality_contract("What does the evidence show?", _Depth(), requests={})
    assert raw["evidence_first_required"] is True
    assert FQ.QualityContract.from_mapping(raw).evidence_first_required is True


def test_legacy_standalone_contract_remains_explicitly_opt_in():
    assert FQ.QualityContract().evidence_first_required is False
    assert FQ.QualityContract.from_mapping({}).evidence_first_required is False


def test_production_gate_missing_evidence_first_audit_fails_closed():
    spec = replace(FQ.QualityContract(), evidence_first_required=True)
    state, codes = _run_claim_gate(_base_context(), spec)
    assert state.checks["evidence_first_audit_present"] is False
    assert state.checks["critical_claims_preselected_before_generation"] is False
    assert state.checks["evidence_first_achievement"] is False
    assert "EVIDENCE_FIRST_AUDIT_MISSING" in codes


def test_deleting_one_audit_field_cannot_create_a_release_pass():
    spec = replace(FQ.QualityContract(), evidence_first_required=True)
    ctx = _base_context()
    ctx.update({
        "evidence_first_required": True,
        "critical_claim_preselection_complete": True,
        "critical_claims_preselected_span_unmatched": 0,
        "evidence_first_achievement": True,
    })
    for field in (
        "evidence_first_required",
        "critical_claim_preselection_complete",
        "critical_claims_preselected_span_unmatched",
        "evidence_first_achievement",
    ):
        mutated = dict(ctx)
        del mutated[field]
        state, codes = _run_claim_gate(mutated, spec)
        assert state.checks["evidence_first_audit_present"] is False
        assert "EVIDENCE_FIRST_AUDIT_MISSING" in codes


def test_false_evidence_first_achievement_blocks_final_gate():
    spec = replace(FQ.QualityContract(), evidence_first_required=True)
    ctx = _base_context()
    ctx.update({
        "evidence_first_required": True,
        "critical_claim_preselection_complete": True,
        "critical_claims_preselected_span_unmatched": 0,
        "evidence_first_achievement": False,
    })
    state, codes = _run_claim_gate(ctx, spec)
    assert state.checks["evidence_first_audit_present"] is True
    assert state.checks["critical_claims_preselected_before_generation"] is True
    assert state.checks["evidence_first_achievement"] is False
    assert "EVIDENCE_FIRST_ACHIEVEMENT_MISSING" in codes


def test_complete_nonvacuous_evidence_first_audit_passes_contract_checks():
    spec = replace(FQ.QualityContract(), evidence_first_required=True)
    ctx = _base_context()
    ctx.update({
        "evidence_first_required": True,
        "critical_claim_preselection_complete": True,
        "critical_claims_preselected_span_unmatched": 0,
        "evidence_first_achievement": True,
    })
    state, codes = _run_claim_gate(ctx, spec)
    assert state.checks["evidence_first_audit_present"] is True
    assert state.checks["critical_claims_preselected_before_generation"] is True
    assert state.checks["evidence_first_achievement"] is True
    assert "EVIDENCE_FIRST_AUDIT_MISSING" not in codes
    assert "CRITICAL_CLAIM_NOT_PRESELECTED" not in codes
    assert "EVIDENCE_FIRST_ACHIEVEMENT_MISSING" not in codes


def test_partial_critical_coverage_is_a_hard_quality_failure():
    spec = replace(FQ.QualityContract(), evidence_first_required=True)
    ctx = _base_context()
    ctx.update({
        "critical_claims": 6,
        "critical_claims_same_source_ae_passed": 3,
        "claim_verification_achievement": True,
        "critical_claim_coverage_complete": False,
        "unsupported_critical_claims": 2,
        "unverifiable_critical_claims": 1,
        "critical_contradicted_claims": 0,
        "evidence_first_required": True,
        "critical_claim_preselection_complete": True,
        "critical_claims_preselected_span_unmatched": 0,
        "evidence_first_achievement": True,
    })
    state, codes = _run_claim_gate(ctx, spec)
    assert state.checks["verified_critical_claim_achievement"] is True
    assert state.checks["verified_critical_claim_coverage_complete"] is False
    assert "CRITICAL_CLAIM_COVERAGE_INCOMPLETE" in codes
