"""Regression tests for the final trading-model acceptance boundary."""

from research_engine import trademodel
from research_engine.task_contract import assess_contract, compile_contract
from research_engine.trading_acceptance_guard import audit_thresholds


def _trade_result(*, not_met=(), not_measured=(), answer="", threshold=None):
    report = {
        "asked": True,
        "ran": True,
        "contract_points": trademodel.CONTRACT_POINTS,
        "met_count": max(0, trademodel.CONTRACT_POINTS - len(not_met) - len(not_measured)),
        "not_met_count": len(not_met),
        "not_measured_count": len(not_measured),
        "not_met": list(not_met),
        "not_measured": list(not_measured),
        "threshold_provenance": threshold or {
            "ran": True,
            "actionable_numeric_thresholds": 0,
            "unsupported_count": 0,
            "acceptance_blocked": False,
            "rows": [],
        },
    }
    return {"answer": answer, "trade_contract": report, "requested_ledger": {"items": []}}


def test_missing_final_model_contract_forces_public_task_partial():
    question = "US100 aur XAUUSD ke liye trading model strategy banao"
    contract = compile_contract(question, "MAXIMUM")
    result = _trade_result(not_met=("entry_model_exact",))

    assessed = assess_contract(contract, result)

    assert assessed["assessment"] == "PARTIAL"
    assert assessed["trade_acceptance"]["passed"] is False
    assert "entry_model_exact" in assessed["trade_acceptance"]["gaps"]


def test_explicit_walk_forward_failure_forces_partial():
    question = "US100 trading model banao aur walk-forward test karo"
    contract = compile_contract(question, "MAXIMUM")
    result = _trade_result(not_measured=("walk_forward_validation",))

    assessed = assess_contract(contract, result)

    assert assessed["assessment"] == "PARTIAL"
    assert "walk_forward_validation" in assessed["trade_acceptance"]["gaps"]


def test_python_backtest_script_is_a_real_required_deliverable():
    question = "US100 ke liye Python event-driven backtest script banao"
    contract = compile_contract(question, "MAXIMUM")

    missing = assess_contract(contract, _trade_result(answer="No code was produced."))
    assert missing["assessment"] == "PARTIAL"
    assert "technical_script_python" in missing["trade_acceptance"]["gaps"]

    present = assess_contract(
        contract,
        _trade_result(answer="```python\nimport pandas as pd\nprint('ok')\n```"),
    )
    assert "technical_script_python" not in present["trade_acceptance"]["gaps"]


def test_untraceable_actionable_threshold_blocks_acceptance():
    audit = audit_thresholds(
        "US100 trading model banao",
        "Long if RSI > 55\nStop loss: 0.5 ATR\nTake profit: 2R",
    )

    assert audit["unsupported_count"] == 3
    assert audit["acceptance_blocked"] is True

    contract = compile_contract("US100 trading model banao", "MAXIMUM")
    result = _trade_result(threshold=audit)
    assessed = assess_contract(contract, result)
    assert assessed["assessment"] == "PARTIAL"
    assert "unsupported_numeric_thresholds" in assessed["trade_acceptance"]["gaps"]


def test_instrument_symbol_digits_are_not_thresholds():
    audit = audit_thresholds(
        "US100 trading model banao",
        "US100 entry rule: Proposed, not validated: long if RSI > 55",
    )

    assert audit.get("ticker_digits_excluded") == 1
    assert audit["actionable_numeric_thresholds"] == 1
    assert audit["provisional_count"] == 1
    assert audit["unsupported_count"] == 0


def test_user_supplied_or_explicitly_provisional_threshold_is_not_fake_grounding():
    supplied = audit_thresholds(
        "US100 model banao; long if RSI > 55",
        "Long if RSI > 55",
    )
    assert supplied["user_supplied_count"] == 1
    assert supplied["unsupported_count"] == 0
    assert supplied["truth_proven"] is False

    proposed = audit_thresholds(
        "US100 model banao",
        "Proposed, not validated: long if RSI > 55",
    )
    assert proposed["provisional_count"] == 1
    assert proposed["unsupported_count"] == 0
    assert proposed["truth_proven"] is False


def test_trademodel_public_record_carries_threshold_audit():
    report = trademodel.study(
        "US100 trading model banao",
        "Proposed, not validated: long if RSI > 55",
        sources=(),
        hypotheses=(),
        lab_report={},
    )
    public = trademodel.public_record(report)

    assert public["threshold_provenance"]["ran"] is True
    assert public["threshold_provenance"]["provisional_count"] == 1
    assert public["threshold_provenance"]["unsupported_count"] == 0
