"""Tests for the credential-gated live release runner (no live calls)."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import scripts.run_live_zero_cost_gate as live_gate
from scripts.run_live_zero_cost_gate import ROOT, evaluate_result, preflight
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
        "verification": {
            "claim_checks": {
                "gate_passed": True,
                "strong_claims_checked": 1,
                "strong_claims_passed": 1,
                "critical_claims": 1,
                "critical_claims_same_source_ae_passed": 1,
                "claim_verification_achievement": True,
            },
            "evidence_first_audit": {
                "evidence_first_required": True,
                "preselected_evidence_spans_count": 1,
                "preselected_strong_eligible_spans": 1,
                "critical_claims_preselected_span_matched": 1,
                "critical_claims_preselected_span_unmatched": 0,
                "critical_claim_preselection_complete": True,
                "evidence_first_achievement": True,
            },
        },
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


def test_validated_preflight_probes_writable_external_storage(tmp_path):
    root = tmp_path / "live-data"
    report = preflight(
        _env(
            INFINITY_DATA_ROOT=str(root),
            INFINITY_MIN_FREE_GB="1",
            OPENROUTER_API_KEY="secret-not-printed",
        ),
        validate_storage=True,
    )
    assert report["ready"] is True
    assert report["storage_validated"] is True
    assert report["storage_ready"] is True
    assert report["storage_free_bytes"] >= report["storage_minimum_free_bytes"]
    assert root.is_dir()
    assert "secret-not-printed" not in str(report)


def test_validated_preflight_rejects_repo_runtime_root_before_live_call():
    report = preflight(
        _env(
            INFINITY_DATA_ROOT=str(ROOT),
            OPENROUTER_API_KEY="secret-not-printed",
        ),
        validate_storage=True,
    )
    assert report["ready"] is False
    assert report["storage_ready"] is False
    assert "INFINITY_DATA_ROOT must be outside the Git repository" in report["blockers"]


def test_validated_preflight_blocks_low_disk_before_live_call(tmp_path, monkeypatch):
    monkeypatch.setattr(
        live_gate.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=4 * 1024 ** 3, used=3 * 1024 ** 3, free=1024 ** 2),
    )
    report = preflight(
        _env(
            INFINITY_DATA_ROOT=str(tmp_path / "live-data"),
            INFINITY_MIN_FREE_GB="1",
            OPENROUTER_API_KEY="secret-not-printed",
        ),
        validate_storage=True,
    )
    assert report["ready"] is False
    assert report["storage_ready"] is False
    assert "runtime storage is below the configured minimum free space" in report["blockers"]


def test_live_exception_writes_sanitized_failure_receipt(tmp_path, monkeypatch, capsys):
    data_root = tmp_path / "live-data"
    receipt = tmp_path / "audit" / "failed.json"
    secret = "provider-secret-and-private-error-must-not-leak"
    env = _env(
        INFINITY_DATA_ROOT=str(data_root),
        INFINITY_MIN_FREE_GB="1",
        OPENROUTER_API_KEY="configured-free-key-not-printed",
    )

    def crash():
        raise RuntimeError(secret)

    monkeypatch.setattr(live_gate, "load_local_env", lambda: None)
    monkeypatch.setattr(live_gate, "run_live", crash)
    with patch.dict(os.environ, env, clear=True):
        return_code = live_gate.main([
            "--execute",
            "--data-root",
            str(data_root),
            "--receipt",
            str(receipt),
        ])

    output = capsys.readouterr().out
    body = json.loads(receipt.read_text(encoding="utf-8"))
    serialized = json.dumps(body, ensure_ascii=False)
    assert return_code == 1
    assert body["passed"] is False
    assert body["failure_code"] == "live_research_execution_failed"
    assert body["contains_answer_or_source_text"] is False
    assert body["contains_credentials"] is False
    assert secret not in output
    assert secret not in serialized
    assert "configured-free-key-not-printed" not in output
    assert "configured-free-key-not-printed" not in serialized


def test_healthy_live_result_passes_all_checks_without_storing_answer():
    report = evaluate_result(_result())
    assert report["passed"] is True
    assert all(row["passed"] for row in report["checks"])
    assert "answer" not in report["summary"]
    assert len(report["summary"]["answer_sha256"]) == 64


def test_unassessed_claim_gate_fails_closed():
    result = _result()
    result["verification"]["claim_checks"] = {}
    report = evaluate_result(result)
    row = next(item for item in report["checks"] if item["name"] == "claim_gate")
    assert row["passed"] is False
    assert report["passed"] is False


def test_live_failure_summary_keeps_only_safe_reasoning_identifiers():
    result = _result()
    result["status"] = "RESEARCH INCOMPLETE"
    result["failure_kind"] = "unknown"
    result["missing_passes"] = ["analysis", "hypothesis", "api_key=secret"]
    result["api_accounting"] = {
        "primary_failure_kind": "unknown",
        "models_tried": [
            "gemma-4-26b-a4b-it", "gemini-2.5-flash", "api_key=secret",
        ],
        "failure_events": [
            {"model": "gemma-4-26b-a4b-it", "label": "analysis",
             "kind": "unknown", "attempt": 1, "detail": "PRIVATE RAW BODY"},
            {"model": "api_key=secret", "label": "analysis",
             "kind": "model_not_found", "attempt": 99},
        ],
    }
    report = evaluate_result(result)
    summary = report["summary"]
    assert summary["failure_kind"] == "unknown"
    assert summary["primary_failure_kind"] == "unknown"
    assert summary["models_tried"] == [
        "gemma-4-26b-a4b-it", "gemini-2.5-flash",
    ]
    assert summary["failure_events"] == [
        {"model": "gemma-4-26b-a4b-it", "label": "analysis",
         "kind": "unknown", "attempt": 1},
        {"model": "", "label": "analysis",
         "kind": "model_not_found", "attempt": 20},
    ]
    assert summary["missing_passes"] == ["analysis", "hypothesis"]
    serialized = json.dumps(summary)
    assert "secret" not in serialized
    assert "PRIVATE RAW BODY" not in serialized


def test_complete_run_marks_old_provider_failure_as_recovered_not_current():
    result = _result()
    result["api_accounting"] = {
        "primary_failure_kind": "request_timeout",
        "models_tried": ["gemma-4-26b-a4b-it"],
        "failure_events": [{
            "model": "gemma-4-26b-a4b-it", "label": "analysis",
            "kind": "request_timeout", "attempt": 1,
        }],
    }
    report = evaluate_result(result)
    summary = report["summary"]
    assert summary["primary_failure_kind"] == ""
    assert summary["recovered_primary_failure_kind"] == "request_timeout"
    assert summary["failure_events"][0]["kind"] == "request_timeout"


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
