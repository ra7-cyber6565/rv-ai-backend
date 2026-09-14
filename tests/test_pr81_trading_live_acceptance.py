"""Offline tests for the fixed PR #81 Max trading live acceptance evaluator."""

from scripts.run_pr81_trading_live_acceptance import evaluate_trading_result
import json
import pytest


_REQUIRED = [
    "entry_model_exact",
    "final_spec_tradeable",
    "baseline_tournament",
    "no_leakage",
    "realistic_costs",
    "walk_forward_validation",
]


def _result(*, status="COMPLETE", assessment="COMPLETE", script="SATISFIED",
            gaps=(), unsupported=0, prepared=True, truncated=False,
            chief_done=("analysis", "synthesis"), missing_passes=()):
    from research_engine import trademodel
    from research_engine.trading_acceptance_guard import enforce
    from scripts.run_pr81_trading_live_acceptance import TRADING_LIVE_QUESTION

    code = "\n".join([
        "import csv", "",
        "def backtest(rows, commission):",
        "    pnl = []",
        "    for previous, current in zip(rows, rows[1:]):",
        "        position = int(previous['close'] > previous['open'])",
        "        pnl.append(position * (current['close'] - current['open']) - commission)",
        "    return pnl",
    ])
    # Fixture-only code/measurements. This is not a validated trading strategy.
    fence = chr(96) * 3
    answer = "Model fixture.\n\n" + (fence + "python\n" + code + "\n" + fence if script == "SATISFIED" else "Script missing.")
    answer += "".join("\nEntry RSI > " + str(60 + i) for i in range(unsupported))
    missing = [g for g in gaps if g in trademodel.CONTRACT_IDS]
    data = {
        "question": TRADING_LIVE_QUESTION, "status": status, "answer": answer,
        "missing_passes": list(missing_passes), "task_contract": {"assessment": assessment},
        "trade_contract": {
            "ran": True, "asked": True, "contract_points": 34, "met_count": 34 - len(missing),
            "not_met_count": 0, "not_measured_count": len(missing),
            "not_met": [], "not_measured": missing, "live_tested": False,
        },
        "runtime_execution": {"available": True, "event_durability": "SQLITE_TRANSACTION",
                              "cancelled": False, "reserved_http_attempts": 8},
        "research_company": {
            "requested_workers": 6, "completed_workers": 6, "accounting_complete": True,
            "workers": [
                {"role": role, "worker_id": "fixture-" + role, "status": "DRAFT_READY",
                 "accounting_complete": True, "provider_output_capture_complete": True,
                 "accounting": {"actual_http_attempts": 1, "successful_calls": 1}}
                for role in ("evidence", "validation", "mechanism", "red_team", "data_quality", "implementation")
            ],
            "handoff_prepared": prepared, "handoff_truncated_roles": ["validation"] if truncated else [],
            "chief_execution": {"done_passes": list(chief_done),
                                "accounting": {"actual_http_attempts": 2, "successful_calls": 2}},
            "independent_scientific_replication": False, "experiments_performed_by_workers": False,
        },
    }
    out = enforce(data)
    # Deliberately permit false COMPLETE fixtures to exercise the evaluator.
    out["status"] = status
    return out


def _check(record, name):
    return next(row["passed"] for row in record["checks"] if row["name"] == name)


def test_complete_structural_max_trading_result_passes_live_evaluator():
    record = evaluate_trading_result(_result())

    assert record["passed"] is True
    assert record["contains_answer_or_source_text"] is False
    assert record["contains_credentials"] is False
    assert len(record["summary"]["answer_sha256"]) == 64


def test_missing_python_script_is_not_accepted_even_when_partial_is_honest():
    record = evaluate_trading_result(_result(
        status="PARTIAL",
        assessment="PARTIAL",
        script="MISSING",
        gaps=("technical_script_python",),
    ))

    assert record["passed"] is False
    assert _check(record, "python_script_delivered") is False
    assert _check(record, "missing_deliverables_fail_closed") is True


def test_missing_deliverable_cannot_be_labeled_complete():
    record = evaluate_trading_result(_result(
        status="COMPLETE",
        assessment="COMPLETE",
        gaps=("walk_forward_validation",),
    ))

    assert record["passed"] is False
    assert _check(record, "missing_deliverables_fail_closed") is False


def test_unsupported_threshold_is_acceptable_only_as_fail_closed_partial():
    honest = evaluate_trading_result(_result(
        status="PARTIAL",
        assessment="PARTIAL",
        gaps=("unsupported_numeric_thresholds",),
        unsupported=2,
    ))
    false_complete = evaluate_trading_result(_result(
        status="COMPLETE",
        assessment="COMPLETE",
        unsupported=2,
    ))

    assert honest["passed"] is True
    assert _check(honest, "unsupported_thresholds_fail_closed") is True
    assert false_complete["passed"] is False
    assert _check(false_complete, "unsupported_thresholds_fail_closed") is False


def test_expected_consumed_handoff_cannot_remain_missing():
    record = evaluate_trading_result(_result(missing_passes=("specialist_handoff",)))

    assert record["passed"] is False
    assert _check(record, "specialist_handoff_semantics") is False


def test_truncated_handoff_must_not_finish_complete():
    bad = evaluate_trading_result(_result(truncated=True))
    honest = evaluate_trading_result(_result(
        status="PARTIAL",
        assessment="PARTIAL",
        truncated=True,
        gaps=("specialist_handoff",),
        missing_passes=("specialist_handoff",),
    ))

    assert bad["passed"] is False
    assert _check(bad, "specialist_handoff_semantics") is False
    assert _check(honest, "specialist_handoff_semantics") is True


def test_creative_dialogue_contamination_fails(monkeypatch):
    from research_engine import craft

    monkeypatch.setattr(craft, "detect", lambda _question: {"is_request": True})
    record = evaluate_trading_result(_result())

    assert record["passed"] is False
    assert _check(record, "technical_script_not_creative") is False


@pytest.mark.parametrize("defect", [
    "duplicate_worker_id", "duplicate_role", "zero_attempts", "zero_successes",
    "unknown_usage", "truncated_capture", "cancelled_runtime", "no_chief",
    "wrong_question", "fake_replication",
])
def test_live_execution_requires_real_distinct_complete_receipts(defect):
    result = _result()
    company = result["research_company"]
    worker = company["workers"][0]
    if defect == "duplicate_worker_id":
        worker["worker_id"] = company["workers"][1]["worker_id"]
    elif defect == "duplicate_role":
        worker["role"] = company["workers"][1]["role"]
    elif defect == "zero_attempts":
        worker["accounting"]["actual_http_attempts"] = 0
    elif defect == "zero_successes":
        worker["accounting"]["successful_calls"] = 0
    elif defect == "unknown_usage":
        worker["accounting_complete"] = False
    elif defect == "truncated_capture":
        worker["provider_output_capture_complete"] = False
    elif defect == "cancelled_runtime":
        result["runtime_execution"]["cancelled"] = True
    elif defect == "no_chief":
        company["chief_execution"]["accounting"]["successful_calls"] = 0
    elif defect == "wrong_question":
        result["question"] = "A different research question"
    else:
        company["independent_scientific_replication"] = True
    assert evaluate_trading_result(result)["passed"] is False


@pytest.mark.parametrize("answer", ["", "Python script delivered.", "print('backtest')"])
def test_script_flag_cannot_replace_actual_answer_code(answer):
    result = _result()
    result["answer"] = answer
    record = evaluate_trading_result(result)
    assert record["passed"] is False
    assert _check(record, "python_script_delivered") is False


@pytest.mark.parametrize("value", [None, -1, True, "PRIVATE_KEY", {"secret": "PRIVATE_KEY"}])
def test_malformed_threshold_receipts_fail_closed_without_private_output(value):
    result = _result()
    result["coverage"]["trading_acceptance"]["unsupported_numeric_threshold_count"] = value
    record = evaluate_trading_result(result)
    assert record["passed"] is False
    assert "PRIVATE_KEY" not in json.dumps(record)


def test_status_payload_cannot_leak_through_sanitized_receipt():
    result = _result()
    result["status"] = "PRIVATE_KEY"
    result["task_contract"]["assessment"] = "PRIVATE_SOURCE"
    result["answer"] += "\nPRIVATE_ANSWER"
    record = evaluate_trading_result(result)
    assert record["passed"] is False
    assert record["summary"]["status"] == "UNKNOWN"
    assert "PRIVATE" not in json.dumps(record)


def test_honest_synthesis_fallback_requires_missing_analysis_to_remain_visible():
    result = _result(status="PARTIAL", assessment="PARTIAL",
                     chief_done=("synthesis",), missing_passes=("analysis",))
    assert evaluate_trading_result(result)["passed"] is True
    result["missing_passes"] = []
    assert evaluate_trading_result(result)["passed"] is False


def test_partial_is_invariant_evidence_not_successful_backtest_or_quality():
    record = evaluate_trading_result(_result(
        status="PARTIAL", assessment="PARTIAL", gaps=("walk_forward_validation",)))
    assert record["passed"] is True
    assert record["backtest_execution_verified"] is False
    assert record["independent_quality_verified"] is False
