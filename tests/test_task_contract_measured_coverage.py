"""Regression tests for explicit-part task completion accounting.

These tests pin the boundary that a positional bullet id (part_1, part_2, ...)
may only be satisfied by an already-measured semantic ledger row.  Surface words
in an answer are never enough.
"""
from research_engine.task_contract import assess_contract, compile_contract


def _result(**statuses):
    return {
        # Historical ledger rows often have no machine key.  Their presence must
        # not mask the keyed quality ledger.
        "requested_ledger": {
            "items": [
                {"what": "human-readable legacy row", "got": "bana", "ok": True}
            ]
        },
        "contract_ledger": {
            "items": [
                {"key": key, "what": key, "got": "measured", "ok": value}
                for key, value in statuses.items()
            ]
        },
        "verification": {},
    }


def _coverage(report):
    return {row["requirement_id"]: row for row in report["coverage"]}


def test_explicit_parts_use_measured_semantic_ledger_not_positional_ids():
    question = (
        "Build a research result:\n"
        "- at least 3 testable hypotheses\n"
        "- mathematical optimization model banao\n"
        "- falsification test plan banao\n"
    )
    contract = compile_contract(question, "MAXIMUM")
    report = assess_contract(
        contract,
        _result(hypotheses=True, math_model=True, red_team=True, falsification=True),
    )
    rows = _coverage(report)

    assert rows["part_1"]["assessment"] == "SATISFIED"
    assert rows["part_2"]["assessment"] == "SATISFIED"
    assert rows["part_3"]["assessment"] == "SATISFIED"
    assert rows["part_1"]["output_reference"] == "contract_ledger:hypotheses"
    assert rows["part_2"]["output_reference"] == "contract_ledger:math_model"
    # The shared parser treats explicit falsification as both adversarial/red-team
    # intent and a falsification deliverable; both measured rows must pass.
    assert rows["part_3"]["measured_keys"] == ["red_team", "falsification"]
    assert report["unresolved_explicit_parts"] == []
    assert report["assessment"] != "PARTIAL"


def test_one_failed_measurement_keeps_corresponding_explicit_part_partial():
    question = (
        "Build a research result:\n"
        "- at least 3 testable hypotheses\n"
        "- mathematical optimization model banao\n"
        "- falsification test plan banao\n"
    )
    contract = compile_contract(question, "MAXIMUM")
    report = assess_contract(
        contract,
        _result(hypotheses=True, math_model=False, red_team=True, falsification=True),
    )
    rows = _coverage(report)

    assert rows["part_1"]["assessment"] == "SATISFIED"
    assert rows["part_2"]["assessment"] == "MISSING"
    assert rows["part_3"]["assessment"] == "SATISFIED"
    assert "part_2" in report["unresolved_explicit_parts"]
    assert "part_2" in report["known_missing_deliverables"]
    assert report["assessment"] == "PARTIAL"


def test_multi_demand_part_requires_every_measured_demand():
    question = (
        "Research this carefully:\n"
        "- mathematical model aur falsification test plan dono banao\n"
    )
    contract = compile_contract(question, "MAXIMUM")
    report = assess_contract(
        contract,
        _result(math_model=True, red_team=True, falsification=False),
    )
    row = _coverage(report)["part_1"]

    assert row["measured_keys"] == ["math_model", "red_team", "falsification"]
    assert row["assessment"] == "MISSING"
    assert report["assessment"] == "PARTIAL"


def test_unmappable_arbitrary_part_remains_not_assessed_never_fake_pass():
    question = (
        "Research this carefully:\n"
        "- explain the exact unusual edge case from the attached private note\n"
    )
    contract = compile_contract(question, "MAXIMUM")
    report = assess_contract(contract, _result())
    row = _coverage(report)["part_1"]

    assert row["assessment"] == "NOT_ASSESSED"
    assert row["output_reference"] is None
    assert "part_1" in report["unresolved_explicit_parts"]
    assert report["assessment"] == "PARTIAL"


def test_recognized_deliverables_read_contract_ledger_even_with_unkeyed_legacy_rows():
    question = "Give at least 3 testable hypotheses and a mathematical model."
    contract = compile_contract(question, "MAXIMUM")
    report = assess_contract(contract, _result(hypotheses=True, math_model=True))
    rows = _coverage(report)

    assert rows["hypotheses"]["assessment"] == "SATISFIED"
    assert rows["math_model"]["assessment"] == "SATISFIED"
    assert rows["hypotheses"]["output_reference"] == "contract_ledger:hypotheses"
    assert rows["math_model"]["output_reference"] == "contract_ledger:math_model"
