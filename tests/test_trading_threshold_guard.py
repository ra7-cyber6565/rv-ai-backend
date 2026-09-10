from research_engine.task_contract import assess_contract, compile_contract
from research_engine.trading_threshold_guard import assess


QUESTION = "US100 aur XAUUSD ke liye scalping trading model banao"


def test_non_trading_answer_is_out_of_scope():
    report = assess("photosynthesis samjhao", {"answer": "Temperature 25 C example."})
    assert report["active"] is False
    assert report["passed"] is True
    assert report["checked_rule_lines"] == 0


def test_bare_numeric_trading_rule_fails_closed_without_copying_text():
    answer = "Entry trigger: long if ATR > 1.2.\nStop loss: 0.8 ATR."
    report = assess(QUESTION, {"answer": answer})

    assert report["active"] is True
    assert report["passed"] is False
    assert report["checked_rule_lines"] == 2
    assert report["unsupported_rule_lines"] == 2
    assert report["unsupported_line_numbers"] == [1, 2]
    assert all(len(value) == 64 for value in report["unsupported_line_sha256"])
    assert answer not in repr(report)
    assert "Entry trigger" not in repr(report)


def test_provisional_heading_scopes_nearby_numeric_rules():
    answer = (
        "### Provisional test parameters — not measured\n"
        "Entry trigger: ATR > 1.2.\n"
        "Stop loss: 0.8 ATR.\n"
    )
    report = assess(QUESTION, {"answer": answer})

    assert report["passed"] is True
    assert report["checked_rule_lines"] == 2
    assert report["supported_rule_lines"] == 2
    assert report["unsupported_rule_lines"] == 0


def test_source_and_user_provenance_are_accepted_only_locally():
    answer = (
        "[SOURCE-REPORTED] Spread filter: skip above 1.5 points [S2].\n"
        "User-specified constraint: risk per trade 0.5%.\n"
        "Entry trigger: EMA 20 crossover.\n"
    )
    report = assess(QUESTION, {"answer": answer})

    assert report["passed"] is True
    assert report["checked_rule_lines"] == 3
    assert report["supported_rule_lines"] == 3


def test_distant_provisional_word_does_not_bless_later_threshold():
    answer = (
        "Provisional test parameters are discussed here.\n"
        "General notes.\n"
        "More general notes.\n"
        "Entry trigger: ATR > 1.3.\n"
    )
    report = assess(QUESTION, {"answer": answer})

    assert report["passed"] is False
    assert report["unsupported_line_numbers"] == [4]


def test_task_contract_downgrades_unproven_threshold_to_partial():
    contract = compile_contract(QUESTION, "MAXIMUM")
    result = {
        "answer": "Entry trigger: ATR > 1.2.",
        "requested_ledger": {"items": []},
        "contract_ledger": {"items": []},
        "verification": {},
    }
    report = assess_contract(contract, result)

    assert report["assessment"] == "PARTIAL"
    assert "trading_numeric_threshold_provenance" in report["known_missing_deliverables"]
    assert report["trading_numeric_threshold_provenance"]["passed"] is False


def test_task_contract_accepts_explicit_test_parameter_provenance():
    contract = compile_contract(QUESTION, "MAXIMUM")
    result = {
        "answer": "Provisional test parameter: entry trigger ATR > 1.2.",
        "requested_ledger": {"items": []},
        "contract_ledger": {"items": []},
        "verification": {},
    }
    report = assess_contract(contract, result)

    row = next(
        item for item in report["coverage"]
        if item["requirement_id"] == "trading_numeric_threshold_provenance"
    )
    assert row["assessment"] == "SATISFIED"
    assert "trading_numeric_threshold_provenance" not in report["known_missing_deliverables"]
