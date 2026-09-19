"""Safety/diagnostic tests for PR81 same-run specialist telemetry."""

from scripts.run_pr81_trading_live_acceptance import _worker_diagnostics


def test_worker_diagnostics_exposes_only_safe_enums_and_counters():
    company = {
        "workers": [
            {
                "status": "FAILED",
                "error": "worker_deadline",
                "accounting_complete": False,
                "accounting": {"actual_http_attempts": 2, "successful_calls": 0},
                "elapsed_seconds": 180.01,
            },
            {
                "status": "DRAFT_READY",
                "error": "",
                "accounting_complete": True,
                "accounting": {"actual_http_attempts": 1, "successful_calls": 1},
                "provider_output_capture_complete": True,
                "report": {"summary": "PRIVATE MODEL TEXT"},
                "elapsed_seconds": 12.5,
            },
            {
                "status": "provider said SECRET=abc",
                "error": "API key SECRET=abc raw provider body",
                "accounting_complete": True,
                "accounting": {"actual_http_attempts": 3, "successful_calls": 0},
                "elapsed_seconds": 4,
            },
        ]
    }

    report = _worker_diagnostics(company)
    rendered = repr(report)

    assert report["status_counts"] == {"DRAFT_READY": 1, "FAILED": 1, "other": 1}
    assert report["error_counts"] == {"none": 1, "other": 1, "worker_deadline": 1}
    assert report["accounting_complete_workers"] == 2
    assert report["provider_http_attempts"] == 6
    assert report["provider_successful_calls"] == 1
    assert report["workers_with_validated_report"] == 1
    assert report["workers_with_complete_output_capture"] == 1
    assert report["max_worker_elapsed_seconds"] == 180.01
    assert report["contains_private_text"] is False
    assert "SECRET" not in rendered
    assert "PRIVATE MODEL TEXT" not in rendered
    assert "raw provider body" not in rendered
