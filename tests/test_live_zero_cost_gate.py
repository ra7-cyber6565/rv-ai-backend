"""Tests for the credential-gated live release runner (no live calls)."""
from __future__ import annotations

import pytest

from scripts.run_live_zero_cost_gate import evaluate_result, preflight
from utils.provider_health import provider_health


@pytest.fixture(autouse=True)
def _isolated_provider_health():
    provider_health.clear()
    yield
    provider_health.clear()


def _env(**updates):
    base = {
        "ZERO_COST_ONLY": "true",
        "INFINITY_DATA_ROOT": "D:\\InfinityResearchAI",
        "GEMINI_API_KEY": "",
        "GEMINI_ZERO_COST_CONFIRMED": "false",
        "GROQ_API_KEY": "",
        "GROQ_ZERO_COST_CONFIRMED": "false",
        "OPENROUTER_API_KEY": "",
        "OPENROUTER_MODEL": "openrouter/free",
        "OLLAMA_ENABLED": "false",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
    }
    base.update(updates)
    return base


def _result():
    return {
        "status": "COMPLETE",
        "answer": "Human-first cited answer [S1] without provider diagnostics.",
        "sources": [{"source_id": "S1"}, {"source_id": "S2"}, {"source_id": "S3"}],
        "coverage": {"on_topic_sources": 3, "full_text_sources_read": 1},
        "invalid_citations": [],
        "citations": [{"source_id": "S1"}],
        "verification": {"claim_checks": {"gate_passed": True}},
        "hypotheses": [{"statement": "a"}, {"statement": "b"}, {"statement": "c"}],
        "evidence_level": "STRONG EVIDENCE",
        "warnings": [],
        "discovery": {
            "status": "ASSESSMENT_READY",
            "tournament": {"winner": "H1"},
            "global_novelty_claimed": False,
            "real_world_success_probability_claimed": False,
            "human_review_required": True,
        },
    }


def test_preflight_blocks_when_no_confirmed_model_layer_exists():
    report = preflight(_env())
    assert report["ready"] is False
    assert report["credentials_exposed"] is False
    assert "no confirmed/free model layer is usable now" in report["blockers"]


def test_preflight_blocks_unconfirmed_gemini_key():
    report = preflight(_env(GEMINI_API_KEY="secret-not-printed"))
    assert report["ready"] is False
    assert any("GEMINI_ZERO_COST_CONFIRMED" in item for item in report["blockers"])
    assert "secret-not-printed" not in str(report)


def test_preflight_accepts_explicitly_confirmed_gemini_key():
    report = preflight(_env(
        GEMINI_API_KEY="secret-not-printed",
        GEMINI_ZERO_COST_CONFIRMED="true",
    ))
    assert report["ready"] is True
    assert report["model_layers_usable_now"] == 1
    assert "secret-not-printed" not in str(report)


def test_preflight_requires_explicit_data_root():
    report = preflight(_env(
        INFINITY_DATA_ROOT="",
        OPENROUTER_API_KEY="secret-not-printed",
    ))
    assert report["ready"] is False
    assert "INFINITY_DATA_ROOT must be explicit" in report["blockers"]


def test_healthy_live_result_passes_all_checks_without_storing_answer():
    report = evaluate_result(_result())
    assert report["passed"] is True
    assert all(row["passed"] for row in report["checks"])
    assert "answer" not in report["summary"]
    assert len(report["summary"]["answer_sha256"]) == 64


def test_raw_provider_error_in_public_answer_fails_gate():
    result = _result()
    result["answer"] += " ResourceExhausted grpc_status"
    report = evaluate_result(result)
    row = next(item for item in report["checks"] if item["name"] == "no_raw_provider_error")
    assert row["passed"] is False
    assert report["passed"] is False


def test_live_gate_requires_three_hypotheses_and_advanced_assessment():
    result = _result()
    result["hypotheses"] = result["hypotheses"][:1]
    result["discovery"]["status"] = "NO_TESTABLE_HYPOTHESES"
    report = evaluate_result(result)
    failed = {row["name"] for row in report["checks"] if not row["passed"]}
    assert {"three_hypotheses", "advanced_discovery"}.issubset(failed)


def test_live_gate_never_allows_global_novelty_or_success_probability_claims():
    result = _result()
    result["discovery"]["global_novelty_claimed"] = True
    result["discovery"]["real_world_success_probability_claimed"] = True
    report = evaluate_result(result)
    failed = {row["name"] for row in report["checks"] if not row["passed"]}
    assert {"no_global_novelty_claim", "no_success_probability_claim"}.issubset(failed)
