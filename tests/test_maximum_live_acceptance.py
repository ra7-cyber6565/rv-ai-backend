from __future__ import annotations

import copy
import json

import pytest

from tools import maximum_live_acceptance as acceptance


def _accounting(logical=1, outputs=1):
    return {
        "logical_reasoning_calls": logical,
        "passes_with_output": outputs,
        "actual_http_attempts": logical,
        "successful_calls": outputs,
    }


def _worker(role: str):
    return {
        "role": role,
        "status": "DRAFT_READY",
        "error": "",
        "accounting_complete": True,
        "provider_output_capture_complete": True,
        "accounting": _accounting(),
        "report": {
            "status": "DRAFT_READY",
            "experiments_performed": False,
            "summary": "ok",
            "claims": [],
            "hypotheses": [],
            "limitations": [],
            "assumptions": [],
            "contradictions": [],
            "remaining_questions": [],
        },
    }


def _good_result():
    workers = [_worker(role) for role in acceptance.EXPECTED_ROLES]
    company = {
        "schema_version": 1,
        "status": "DRAFTS_READY",
        "requested_workers": 6,
        "completed_workers": 6,
        "logical_call_budget": 10,
        "chief_call_budget": 4,
        "independent_first_passes": True,
        "independent_models_verified": False,
        "independent_scientific_replication": False,
        "experiments_performed_by_workers": False,
        "accounting_complete": True,
        "handoff_prepared": True,
        "handoff_truncated_roles": [],
        "workers": workers,
        "chief_execution": {
            "done_passes": ["analysis", "critique", "hypothesis", "synthesis"],
            "accounting": _accounting(logical=3, outputs=3),
        },
    }
    return {
        "mode": "MAXIMUM",
        "status": "COMPLETE",
        "missing_passes": [],
        "verification": {"research_company": company},
        "api_accounting": {
            "logical_reasoning_calls": 9,
            "actual_http_attempts": 9,
            "accounting_complete": True,
            "counts_are_lower_bounds": False,
            "unknown_worker_usage": 0,
        },
        "answer": "RAW_ANSWER_MUST_NOT_ENTER_RECEIPT",
    }


def test_accepts_exact_six_worker_and_full_chief_receipt():
    receipt = acceptance.validate_maximum_result(_good_result())
    assert receipt["architecture_pass"] is True
    assert receipt["roles"] == list(acceptance.EXPECTED_ROLES)
    assert receipt["chief_done_passes"] == list(acceptance.REQUIRED_CHIEF_PASSES)
    assert receipt["completed_workers"] == 6


def test_five_workers_cannot_pass_as_maximum_company():
    result = _good_result()
    company = result["verification"]["research_company"]
    company["workers"] = company["workers"][:5]
    company["completed_workers"] = 5
    with pytest.raises(acceptance.AcceptanceError, match="6/6"):
        acceptance.validate_maximum_result(result)


def test_partial_worker_fails_closed():
    result = _good_result()
    result["verification"]["research_company"]["workers"][2]["status"] = "PARTIAL"
    with pytest.raises(acceptance.AcceptanceError, match="mechanism"):
        acceptance.validate_maximum_result(result)


def test_truncated_worker_output_fails_closed():
    result = _good_result()
    result["verification"]["research_company"]["workers"][0]["provider_output_capture_complete"] = False
    with pytest.raises(acceptance.AcceptanceError, match="truncated"):
        acceptance.validate_maximum_result(result)


def test_truncated_specialist_handoff_fails_closed():
    result = _good_result()
    result["verification"]["research_company"]["handoff_truncated_roles"] = ["validation"]
    with pytest.raises(acceptance.AcceptanceError, match="handoff"):
        acceptance.validate_maximum_result(result)


def test_configured_chief_budget_without_actual_passes_is_not_proof():
    result = _good_result()
    result["verification"]["research_company"]["chief_execution"] = {
        "done_passes": [],
        "accounting": _accounting(logical=0, outputs=0),
    }
    with pytest.raises(acceptance.AcceptanceError, match="chief did not complete"):
        acceptance.validate_maximum_result(result)


def test_missing_chief_hypothesis_semantic_pass_fails():
    result = _good_result()
    result["verification"]["research_company"]["chief_execution"]["done_passes"].remove("hypothesis")
    with pytest.raises(acceptance.AcceptanceError, match="hypothesis"):
        acceptance.validate_maximum_result(result)


def test_incomplete_worker_accounting_fails_closed():
    result = _good_result()
    result["verification"]["research_company"]["workers"][4]["accounting_complete"] = False
    with pytest.raises(acceptance.AcceptanceError, match="data_quality accounting"):
        acceptance.validate_maximum_result(result)


def test_missing_company_pass_in_final_ledger_fails():
    result = _good_result()
    result["missing_passes"] = ["company_red_team"]
    with pytest.raises(acceptance.AcceptanceError, match="missing"):
        acceptance.validate_maximum_result(result)


def test_receipt_projection_does_not_copy_answer_or_model_payloads():
    result = _good_result()
    secret = "SUPER_PRIVATE_CAPABILITY_OR_RAW_MODEL_TEXT"
    result["answer"] = secret
    result["verification"]["research_company"]["workers"][0]["raw_output_ref"] = secret
    receipt = acceptance.validate_maximum_result(result)
    rendered = json.dumps(receipt, sort_keys=True)
    assert secret not in rendered
    assert "answer" not in receipt


def test_health_requires_zero_cost_and_usable_model():
    health = {
        "status": "healthy",
        "build_revision": "a" * 40,
        "zero_cost_only": True,
        "reasoning_resilience": {"has_model_layer_usable_now": True},
        "storage": {"available": True, "split_storage": True},
    }
    receipt = acceptance.validate_health(health, "a" * 40)
    assert receipt["zero_cost_only"] is True
    assert receipt["model_layer_usable_now"] is True

    bad = copy.deepcopy(health)
    bad["zero_cost_only"] = False
    with pytest.raises(acceptance.AcceptanceError, match="ZERO_COST_ONLY"):
        acceptance.validate_health(bad)

    bad = copy.deepcopy(health)
    bad["reasoning_resilience"]["has_model_layer_usable_now"] = False
    with pytest.raises(acceptance.AcceptanceError, match="usable confirmed model"):
        acceptance.validate_health(bad)


def test_health_revision_pin_fails_closed():
    health = {
        "status": "healthy",
        "build_revision": "b" * 40,
        "zero_cost_only": True,
        "reasoning_resilience": {"has_model_layer_usable_now": True},
        "storage": {},
    }
    with pytest.raises(acceptance.AcceptanceError, match="revision"):
        acceptance.validate_health(health, "c" * 40)
