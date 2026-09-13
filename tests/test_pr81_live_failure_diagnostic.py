"""Offline privacy/contract tests for the receipt-only PR81 live diagnostic."""
from __future__ import annotations

import json

from scripts import diagnose_pr81_trading_failure as diagnostic


def _clean_identity(_root):
    return {"available": True, "clean": True, "revision": "abc123"}


def _write_source(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_failed_acceptance_receipt_is_reused_without_second_research_call(tmp_path, monkeypatch):
    secret = "SECRET provider body and prompt must never be written"
    monkeypatch.setattr(diagnostic, "repository_identity", _clean_identity)
    source = tmp_path / "acceptance.json"
    _write_source(
        source,
        {
            "schema_version": 1,
            "passed": False,
            "failure_code": "trading_max_live_execution_or_evaluation_failed",
            "checks": [
                {
                    "name": "trading_max_live_execution",
                    "passed": False,
                    "detail": secret,
                }
            ],
        },
    )

    report = diagnostic.execute(source)

    assert report["passed"] is False
    assert report["source_receipt_reused"] is True
    assert report["additional_research_calls"] == 0
    assert report["additional_model_calls"] == 0
    assert report["failure_stage"] == "original_acceptance_run"
    assert report["failure_category"] == "trading_max_live_execution_or_evaluation_failed"
    assert report["failed_checks"] == ["trading_max_live_execution"]
    assert report["contains_exception_type_or_function_name"] is False
    assert report["contains_filesystem_path"] is False
    assert secret not in repr(report)


def test_unknown_failure_fields_cannot_become_public_diagnostics(tmp_path, monkeypatch):
    secret = "PRIVATE_EXCEPTION_CLASS_OR_FUNCTION_NAME"
    monkeypatch.setattr(diagnostic, "repository_identity", _clean_identity)
    source = tmp_path / "acceptance.json"
    _write_source(
        source,
        {
            "schema_version": 1,
            "passed": False,
            "failure_code": secret,
            "checks": [
                {"name": secret, "passed": False},
                {"name": "six_specialists_executed", "passed": False},
            ],
            "exception": {
                "type": secret,
                "function": secret,
                "file": "/private/path/" + secret,
            },
        },
    )

    report = diagnostic.execute(source)

    assert report["failure_category"] == "unclassified_failure"
    assert report["failed_checks"] == ["six_specialists_executed"]
    assert secret not in repr(report)


def test_malformed_or_oversized_receipt_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostic, "repository_identity", _clean_identity)
    malformed = tmp_path / "acceptance.json"
    malformed.write_text("{not-json", encoding="utf-8")

    report = diagnostic.execute(malformed)

    assert report["passed"] is False
    assert report["failure_stage"] == "receipt_validation"
    assert report["failure_category"] == "source_receipt_invalid"
    assert report["additional_research_calls"] == 0
    assert report["additional_model_calls"] == 0


def test_success_receipt_stays_success_without_provider_or_research_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostic, "repository_identity", _clean_identity)
    source = tmp_path / "acceptance.json"
    _write_source(
        source,
        {
            "schema_version": 1,
            "passed": True,
            "checks": [
                {"name": "status_complete", "passed": True},
                {"name": "six_specialists_executed", "passed": True},
            ],
        },
    )

    report = diagnostic.execute(source)

    assert report["passed"] is True
    assert report["failure_stage"] == "none"
    assert report["failure_category"] == "none"
    assert report["failed_checks"] == []
    assert report["additional_research_calls"] == 0
    assert report["additional_model_calls"] == 0
