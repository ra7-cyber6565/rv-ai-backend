"""Offline tests for the fixed PR #81 Max trading live acceptance evaluator."""

from scripts.run_pr81_trading_live_acceptance import evaluate_trading_result


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
    threshold = {
        "ran": True,
        "unsupported_count": unsupported,
        "acceptance_blocked": unsupported > 0,
    }
    return {
        "status": status,
        "answer": "```python\nprint('bounded backtest')\n```",
        "missing_passes": list(missing_passes),
        "task_contract": {
            "assessment": assessment,
            "coverage": [
                {
                    "requirement_id": "technical_script:python",
                    "assessment": script,
                    "output_reference": "answer",
                }
            ],
            "trade_acceptance": {
                "active": True,
                "script_kind": "python",
                "required_contract_points": list(_REQUIRED),
                "gaps": list(gaps),
                "threshold_provenance": threshold,
            },
        },
        "research_company": {
            "requested_workers": 6,
            "workers": [
                {"role": f"r{i}", "status": "DRAFT_READY"} for i in range(6)
            ],
            "handoff_prepared": prepared,
            "handoff_truncated_roles": ["validation"] if truncated else [],
            "chief_execution": {"done_passes": list(chief_done)},
        },
    }


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
