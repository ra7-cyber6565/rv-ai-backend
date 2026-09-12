"""Offline privacy/contract tests for the failure-only PR81 live diagnostic."""

from scripts import diagnose_pr81_trading_failure as diagnostic


def _clean_identity(_root):
    return {"available": True, "clean": True, "revision": "abc123"}


def test_research_exception_is_structural_and_never_records_message(monkeypatch):
    secret = "SECRET provider body and prompt must never be written"
    monkeypatch.setattr(diagnostic, "repository_identity", _clean_identity)

    def boom():
        raise TimeoutError(secret)

    monkeypatch.setattr(diagnostic.acceptance, "run_live", boom)
    report = diagnostic.execute()

    assert report["passed"] is False
    assert report["failure_stage"] == "research_execution"
    assert report["failure_category"] == "research_execution_exception"
    assert report["exception"]["family"] == "timeout"
    assert report["exception"]["type"] == "TimeoutError"
    assert report["exception"]["message_recorded"] is False
    assert report["contains_exception_message"] is False
    assert secret not in repr(report)


def test_evaluator_exception_is_distinguished_without_raw_text(monkeypatch):
    secret = "PRIVATE ANSWER OR ERROR BODY"
    monkeypatch.setattr(diagnostic, "repository_identity", _clean_identity)
    monkeypatch.setattr(diagnostic.acceptance, "run_live", lambda: {"answer": secret})

    def bad_evaluator(_result):
        raise ValueError(secret)

    monkeypatch.setattr(diagnostic.acceptance, "evaluate_result", bad_evaluator)
    report = diagnostic.execute()

    assert report["passed"] is False
    assert report["failure_stage"] == "acceptance_evaluation"
    assert report["failure_category"] == "acceptance_evaluation_exception"
    assert report["exception"]["type"] == "ValueError"
    assert report["contains_answer_or_source_text"] is False
    assert secret not in repr(report)


def test_measured_contract_gap_records_only_failed_check_names(monkeypatch):
    secret = "PRIVATE ANSWER"
    monkeypatch.setattr(diagnostic, "repository_identity", _clean_identity)
    monkeypatch.setattr(diagnostic.acceptance, "run_live", lambda: {"answer": secret})
    monkeypatch.setattr(
        diagnostic.acceptance,
        "evaluate_result",
        lambda _result: {
            "passed": False,
            "checks": [
                {"name": "six_specialists_executed", "passed": False, "detail": secret},
                {"name": "chief_executed", "passed": True, "detail": secret},
            ],
        },
    )

    report = diagnostic.execute()

    assert report["passed"] is False
    assert report["failure_stage"] == "acceptance_checks"
    assert report["failure_category"] == "measured_contract_gap"
    assert report["failed_checks"] == ["six_specialists_executed"]
    assert report["failed_check_count"] == 1
    assert secret not in repr(report)
