from research_engine import trademodel
from research_engine import trading_acceptance_guard as guard
import pytest


def contract(*, not_met=(), not_measured=()):
    not_met = list(not_met)
    not_measured = list(not_measured)
    return {
        "asked": True,
        "ran": True,
        "contract_points": trademodel.CONTRACT_POINTS,
        "met_count": trademodel.CONTRACT_POINTS - len(not_met) - len(not_measured),
        "not_met_count": len(not_met),
        "not_measured_count": len(not_measured),
        "not_met": not_met,
        "not_measured": not_measured,
        "live_tested": False,
    }


def test_non_trading_result_is_not_downgraded():
    data = {
        "question": "Photosynthesis ko simple Hindi me samjhao",
        "answer": "Paudhe roshni se urja banate hain.",
        "status": "COMPLETE",
        "coverage": {},
    }
    out = guard.enforce(data)
    assert out["status"] == "COMPLETE"
    assert out["coverage"]["trading_acceptance"]["required"] is False


def test_trading_model_without_trade_contract_is_partial():
    data = {
        "question": "US100 ke liye scalping trading model banao",
        "answer": "Yeh ek idea hai.",
        "status": "COMPLETE",
        "coverage": {},
    }
    out = guard.enforce(data)
    assert out["status"] == "PARTIAL"
    audit = out["coverage"]["trading_acceptance"]
    assert "trade_contract_not_run" in audit["missing_contract_points"]
    assert "TRADING ACCEPTANCE GAP" in out["answer"]


def test_malformed_trade_contract_cannot_imply_all_points_met():
    out = guard.enforce({
        "question": "US100 trading model banao",
        "answer": "A model-like answer.",
        "status": "COMPLETE",
        "coverage": {},
        "trade_contract": {"asked": True, "ran": True, "not_met": [], "not_measured": []},
    })
    audit = out["coverage"]["trading_acceptance"]
    assert audit["trade_contract_partition_valid"] is False
    assert "trade_contract_status_partition_invalid" in audit["missing_contract_points"]
    assert out["status"] == "PARTIAL"


def test_requested_walk_forward_must_be_measured_not_merely_described():
    data = {
        "question": "US100 trading model banao aur walk-forward validation karo",
        "answer": "Model aur validation ka prose description.",
        "status": "COMPLETE",
        "coverage": {},
        "trade_contract": contract(not_measured=("walk_forward_validation",)),
    }
    out = guard.enforce(data)
    audit = out["coverage"]["trading_acceptance"]
    assert "walk_forward_validation" in audit["required_contract_points"]
    assert "walk_forward_validation" in audit["missing_contract_points"]
    assert out["status"] == "PARTIAL"


def test_requested_python_backtest_script_needs_actual_technical_code_block():
    question = "US100 trading model banao aur Python backtest script do"
    missing = guard.enforce({
        "question": question,
        "answer": "Python script bana sakte hain, yahan explanation hai.",
        "status": "COMPLETE",
        "coverage": {},
        "trade_contract": contract(),
    })
    assert "technical_backtest_script" in missing["coverage"]["trading_acceptance"]["missing_contract_points"]
    assert missing["status"] == "PARTIAL"

    code = """```python
import pandas as pd

def backtest(frame):
    position = 0
    pnl = []
    for row in frame.itertuples():
        entry = row.Close > row.Open
        if entry:
            position = 1
        stop = row.Low
        target = row.High
        pnl.append((target - stop) * position)
    return pd.Series(pnl).sum()
```"""
    delivered = guard.enforce({
        "question": question,
        "answer": "Model specification follows.\n\n" + code,
        "status": "COMPLETE",
        "coverage": {},
        "trade_contract": contract(),
    })
    assert delivered["coverage"]["trading_acceptance"]["script_delivered"] is True
    assert "technical_backtest_script" not in delivered["coverage"]["trading_acceptance"]["missing_contract_points"]
    assert delivered["status"] == "COMPLETE"


def test_multiple_instruments_require_separate_instrument_scope():
    data = {
        "question": "US100 aur XAUUSD ke liye alag-alag trading model banao",
        "answer": "One combined model.",
        "status": "COMPLETE",
        "coverage": {},
        "trade_contract": contract(not_met=("instrument_scope",)),
    }
    out = guard.enforce(data)
    audit = out["coverage"]["trading_acceptance"]
    assert "instrument_scope" in audit["required_contract_points"]
    assert "instrument_scope" in audit["missing_contract_points"]
    assert out["status"] == "PARTIAL"


def test_complete_delivery_does_not_claim_profitability_or_live_testing():
    question = "US100 trading model banao"
    out = guard.enforce({
        "question": question,
        "answer": "Exact model specification with explicit entry and no-trade rules.",
        "status": "COMPLETE",
        "coverage": {},
        "trade_contract": contract(),
    })
    audit = out["coverage"]["trading_acceptance"]
    assert audit["complete"] is True
    assert audit["trade_contract_partition_valid"] is True
    assert audit["profitability_proven"] is False
    assert audit["live_tested"] is False
    assert out["status"] == "COMPLETE"


@pytest.mark.parametrize("answer", [
    "Enter when RSI > 70, calibrated from 100 samples.",
    "Warning: stop loss = 5%, calibrated from 100 trades.",
    "Risk per trade = 5%. Other variables are UNKNOWN.",
    "Entry threshold > 70. " + "Measured rationale " * 100,
])
def test_numbers_and_calibration_claims_are_not_execution_receipts(answer):
    out = guard.enforce({"question": "US100 trading model banao", "answer": answer,
                         "status": "COMPLETE", "trade_contract": contract()})
    assert out["status"] == "PARTIAL"
    assert "unsupported_numeric_trading_thresholds" in out["coverage"]["trading_acceptance"]["missing_contract_points"]


@pytest.mark.parametrize("broken", [
    {"not_met": 2}, {"met_count": True}, {"met_count": 34.9},
    {"not_met": ["entry_model_exact", "entry_model_exact"], "not_met_count": 2, "met_count": 32},
])
def test_corrupt_partitions_fail_closed_without_crashing(broken):
    receipt = contract()
    receipt.update(broken)
    out = guard.enforce({"question": "US100 trading model banao", "answer": "Draft",
                         "status": "COMPLETE", "trade_contract": receipt})
    assert out["status"] == "PARTIAL"
    assert out["coverage"]["trading_acceptance"]["trade_contract_partition_valid"] is False


def test_enforcement_is_idempotent_and_does_not_mutate_original():
    import copy
    data = {"question": "US100 trading model banao", "answer": "Entry threshold > 70.",
            "status": "COMPLETE", "trade_contract": contract(), "warnings": [],
            "research_state": {"answer_state": "COMPLETE", "conflicts": []}}
    before = copy.deepcopy(data)
    first = guard.enforce(data)
    assert data == before
    assert guard.enforce(first) == first
