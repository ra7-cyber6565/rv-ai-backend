"""Deterministic contract tests for the fixed PR #81 live acceptance evaluator.

No provider/network call happens here.  Synthetic envelopes only prove that the
release gate cannot pass when one of the measured acceptance dimensions is
missing, and that its public receipt does not copy private answer text.
"""
from copy import deepcopy

from scripts.run_pr81_trading_live_acceptance import (
    CRITICAL_TRADE_POINTS,
    EXPECTED_ROLES,
    REQUIRED_EXPERIMENT_SPEC,
    evaluate_result,
)


def _hypothesis():
    spec = {
        key: (["measured variable"] if key == "measured_variables" else f"value for {key}")
        for key in REQUIRED_EXPERIMENT_SPEC
    }
    return {
        "is_testable": True,
        "has_prediction": True,
        "experiment_spec": spec,
        "experiment_spec_missing": [],
    }


def _worker(role):
    report = {"tool_results": []}
    if role == "implementation":
        # DockerExecutor.run() returns this direct structure; it does not add a
        # generic `tool=isolated_build` key.
        report["tool_results"] = [{
            "state": "EXECUTED",
            "runtime": "python",
            "executor": {"ready": True},
            "automatic_deploy_allowed": False,
            "physical_experiment": False,
            "artifact": {"sha256": "a" * 64},
        }]
    return {
        "role": role,
        "status": "DRAFT_READY",
        "worker_id": "worker-" + role,
        "accounting": {"actual_http_attempts": 1, "successful_calls": 1},
        "accounting_complete": True,
        "report": report,
    }


def _result():
    workers = [_worker(role) for role in sorted(EXPECTED_ROLES)]
    return {
        "status": "COMPLETE",
        "answer": "PRIVATE ANSWER BODY THAT MUST NEVER ENTER THE RECEIPT",
        "coverage": {"mode": "MAXIMUM"},
        "task_contract": {
            "task_types": ["research", "coding", "experiment_design"],
            "explicit_min_workers": 6,
            "assessment": "REQUIRES_COVERAGE_REVIEW",
            "worker_requirement_gap": False,
            "known_missing_deliverables": [],
            "trading_numeric_threshold_provenance": {
                "active": True,
                "passed": True,
                "checked_rule_lines": 4,
                "unsupported_rule_lines": 0,
            },
        },
        "trade_contract": {
            "asked": True,
            "ran": True,
            "contract_points": 34,
            "met_count": 34,
            "not_met_count": 0,
            "not_measured_count": 0,
            "not_met": [],
            "not_measured": [],
            "chased_win_rate": [],
            "live_tested": False,
            "broker_connected": False,
            "financial_advice": False,
        },
        "hypotheses": [_hypothesis(), _hypothesis(), _hypothesis()],
        "verification": {
            "research_company": {
                "workers": workers,
                "completed_workers": 6,
                "requested_workers": 6,
                "handoff_prepared": True,
                "handoff_structured_compaction": True,
                "handoff_worker_roles": sorted(EXPECTED_ROLES),
                "handoff_compacted_roles": ["evidence"],
                "handoff_truncated_roles": [],
                "accounting_complete": True,
                "chief_execution": {
                    "done_passes": ["analysis", "synthesis"],
                    "accounting": {"successful_calls": 2},
                },
                "independent_scientific_replication": False,
                "experiments_performed_by_workers": False,
            }
        },
    }


def _failed_checks(report):
    return {row["name"] for row in report["checks"] if not row["passed"]}


def test_complete_measured_envelope_passes_and_receipt_is_sanitized():
    result = _result()
    report = evaluate_result(result)

    assert report["passed"] is True
    assert report["contains_answer_or_source_text"] is False
    assert report["contains_question_text"] is False
    assert report["contains_credentials"] is False
    assert report["performance_or_profitability_proven"] is False
    assert "PRIVATE ANSWER BODY" not in repr(report)
    assert len(report["summary"]["answer_sha256"]) == 64


def test_creative_misclassification_fails_even_if_everything_else_passes():
    result = _result()
    result["task_contract"]["task_types"].append("creative")
    report = evaluate_result(result)
    assert report["passed"] is False
    assert "coding_not_creative" in _failed_checks(report)


def test_unsupported_numeric_threshold_fails_release_acceptance():
    result = _result()
    result["task_contract"]["trading_numeric_threshold_provenance"].update(
        passed=False, unsupported_rule_lines=1
    )
    report = evaluate_result(result)
    assert report["passed"] is False
    assert "threshold_provenance" in _failed_checks(report)


def test_missing_or_clipped_specialist_handoff_fails():
    result = _result()
    result["verification"]["research_company"]["handoff_truncated_roles"] = ["validation"]
    report = evaluate_result(result)
    assert report["passed"] is False
    assert "specialist_handoff_complete" in _failed_checks(report)


def test_one_incomplete_hypothesis_plan_fails():
    result = _result()
    del result["hypotheses"][1]["experiment_spec"]["statistical_metric"]
    result["hypotheses"][1]["experiment_spec_missing"] = ["statistical_metric"]
    report = evaluate_result(result)
    assert report["passed"] is False
    assert "three_structured_hypotheses" in _failed_checks(report)
    assert report["summary"]["first_three_experiment_missing_counts"][1] == 1


def test_any_critical_trade_contract_gap_fails():
    result = _result()
    missing = sorted(CRITICAL_TRADE_POINTS)[0]
    result["trade_contract"]["not_met"] = [missing]
    result["trade_contract"]["not_met_count"] = 1
    result["trade_contract"]["met_count"] = 33
    report = evaluate_result(result)
    assert report["passed"] is False
    assert "critical_trade_contract" in _failed_checks(report)
    assert report["summary"]["critical_trade_gaps"] == [missing]


def test_missing_isolated_build_receipt_fails():
    result = _result()
    implementation = next(
        row for row in result["verification"]["research_company"]["workers"]
        if row["role"] == "implementation"
    )
    implementation["report"]["tool_results"] = []
    report = evaluate_result(result)
    assert report["passed"] is False
    assert "implementation_build_executed" in _failed_checks(report)
