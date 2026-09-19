"""Round-2 Company collaboration wiring tests.

These are deterministic fixtures: no provider/network call is made. They prove
that public Max keeps independent first passes, then exposes only other validated
specialist drafts to each peer reviewer, accounts the bounded second round, and
fails closed when a required review is unavailable.
"""
from __future__ import annotations

import importlib
import json

from research_engine import research_company as company
from research_engine.depth import get_depth_config
from research_engine.models import EvidencePack, SourceRecord


def _set_model_ready(monkeypatch):
    status_module = importlib.import_module("utils.reasoning_status")
    monkeypatch.setattr(
        status_module,
        "reasoning_status",
        lambda: {"has_model_layer_usable_now": True},
    )


def _packet():
    return EvidencePack(
        sources=[SourceRecord(source_id="S1", title="Source", snippet="Measured evidence")]
    )


def _report(role="role"):
    return json.dumps(
        {
            "summary": f"ROUND1_{role} supported candidate.",
            "claims": [
                {"text": f"Claim from {role}", "source_ids": ["S1"], "kind": "SOURCE_REPORTED"}
            ],
            "hypotheses": [],
            "limitations": [],
            "assumptions": [],
            "contradictions": [],
            "remaining_questions": [],
        }
    )


def _envelope(role="role"):
    return {
        "answer": _report(role),
        "accounting_complete": True,
        "output_truncated": False,
        "accounting": {
            "logical_reasoning_calls": 1,
            "actual_http_attempts": 1,
            "successful_calls": 1,
            "models_tried": ["fixture-model"],
        },
    }


def test_max_round2_reviews_other_specialists_before_chief(monkeypatch):
    _set_model_ready(monkeypatch)
    seen_review_evidence = {}
    calls = []

    def worker(payload):
        role = payload["role"]
        is_review = "ROUND 2 CROSS-REVIEW" in payload["question"]
        calls.append((role, is_review))
        if is_review:
            seen_review_evidence[role] = payload["evidence"]
        return _envelope(role)

    config = get_depth_config("MAXIMUM")
    result = company.run_company("Compare the evidence", _packet(), config, worker=worker)

    assert config.company_agents == 6
    assert config.company_cross_review_agents == 6
    assert config.gemini_calls == 16
    assert result["completed_workers"] == 6
    assert result["completed_cross_reviews"] == 6
    assert result["cross_review_status"] == "REVIEWS_READY"
    assert result["chief_call_budget"] == 4
    assert len(calls) == 12
    assert sum(not review for _role, review in calls) == 6
    assert sum(review for _role, review in calls) == 6

    roles = {role for role, _instruction in company.ROLES}
    for review in result["cross_reviews"]:
        role = review["role"]
        assert set(review["reviewed_roles"]) == roles - {role}
        evidence = seen_review_evidence[role]
        assert f"ROUND1_{role}" not in evidence
        for peer in roles - {role}:
            assert f"ROUND1_{peer}" in evidence

    handoff = company.chief_handoff(result)
    assert "BEGIN_UNTRUSTED_SPECIALIST_CROSS_REVIEWS" in handoff
    assert result["cross_review_handoff_complete"] is True


def test_round2_accounting_is_added_without_changing_legacy_round1(monkeypatch):
    _set_model_ready(monkeypatch)
    config = get_depth_config("MAXIMUM")
    result = company.run_company("Q", _packet(), config, worker=lambda payload: _envelope(payload["role"]))
    company.chief_handoff(result)
    out = {
        "planned_passes": ["analysis"],
        "done_passes": ["analysis"],
        "notes": [],
        "api_accounting": {
            "logical_reasoning_calls": 4,
            "actual_http_attempts": 4,
            "successful_calls": 4,
            "models_tried": ["chief-model"],
        },
    }
    company.attach_company_passes(out, result)

    assert out["calls"] == 16
    assert out["attempts"] == 16
    assert len([p for p in out["done_passes"] if p.startswith("company_cross_review_")]) == 6
    assert "specialist_handoff" in out["done_passes"]
    assert out["api_accounting"]["budget"] == 16
    assert out["api_accounting"]["accounting_complete"] is True


def test_missing_required_cross_review_keeps_specialist_handoff_open(monkeypatch):
    _set_model_ready(monkeypatch)

    def worker(payload):
        if (
            "ROUND 2 CROSS-REVIEW" in payload["question"]
            and payload["role"] == "red_team"
        ):
            return {"error": "worker_deadline", "accounting_complete": False}
        return _envelope(payload["role"])

    result = company.run_company(
        "Q", _packet(), get_depth_config("MAXIMUM"), worker=worker
    )
    handoff = company.chief_handoff(result)
    assert result["cross_review_status"] == "PARTIAL"
    assert result["completed_cross_reviews"] == 5
    assert result["cross_review_handoff_complete"] is False
    assert "CROSS-REVIEW INCOMPLETE" in handoff

    out = {
        "planned_passes": ["analysis"],
        "done_passes": ["analysis"],
        "notes": [],
        "api_accounting": {
            "logical_reasoning_calls": 4,
            "actual_http_attempts": 4,
            "successful_calls": 4,
        },
    }
    company.attach_company_passes(out, result)
    assert "specialist_handoff" not in out["done_passes"]
    assert out["api_accounting"]["counts_are_lower_bounds"] is True


def test_legacy_company_plus_does_not_silently_gain_unbudgeted_second_round(monkeypatch):
    _set_model_ready(monkeypatch)
    config = get_depth_config("COMPANY_PLUS")
    assert config.gemini_calls == 10
    assert getattr(config, "company_cross_review_agents", 0) == 0
    calls = []

    def worker(payload):
        calls.append(payload)
        return _envelope(payload["role"])

    result = company.run_company("Q", _packet(), config, worker=worker)
    assert len(calls) == 6
    assert result["cross_review_requested"] is False
    assert result["chief_call_budget"] == 4


def test_live_evaluator_accepts_real_company_receipt_shape_with_fixture_provider(monkeypatch):
    from scripts.run_pr81_trading_live_acceptance import evaluate_result

    _set_model_ready(monkeypatch)
    result = company.run_company(
        "Compare the evidence", _packet(), get_depth_config("MAXIMUM"),
        worker=lambda payload: _envelope(payload["role"]),
    )
    company.chief_handoff(result)
    receipt = evaluate_result({
        "mode": "MAXIMUM",
        "verification": {"research_company": result},
    })
    checks = {row["name"]: row["passed"] for row in receipt["checks"]}

    assert checks["maximum_mode_executed"] is True
    assert checks["six_specialists_executed"] is True
    assert checks["six_cross_reviews_executed"] is True
    assert checks["specialist_handoff_complete"] is True
    assert checks["cross_review_handoff_complete"] is True
    assert checks["company_accounting_complete"] is True
    # Synthetic Company wiring does not establish live/trading completion.
    assert receipt["passed"] is False
