from copy import deepcopy

from research_engine.quality_release import enforce_quality_release
from research_engine.structured_answer import enforce_result, extract_outline


def _question() -> str:
    numbered = "\n\n".join(
        f"### {i}. Domain {i} Deep Explanation\nExplain domain {i} completely."
        for i in range(1, 17)
    )
    return (
        numbered
        + "\n\n## Final Challenge\nCompare two people over 20 years."
        + "\n\n## Mandatory Evidence Standard\nSeparate evidence from speculation."
        + "\n\n## Ultimate Question\nGive the integrated causal model."
    )


def _answer(*, missing_number: int | None = None) -> str:
    rows = []
    for item in extract_outline(_question()):
        if item.get("number") == missing_number:
            continue
        rows.append(
            f"**{item['label']}**\n"
            "Seedha answer. Mechanism, evidence, competing explanation, limitation aur meaning."
        )
    return "\n\n".join(rows)


def _base_result(*, status: str = "COMPLETE", missing_number: int | None = 10) -> dict:
    return {
        "question": _question(),
        "answer": _answer(missing_number=missing_number),
        "status": status,
        "status_reason": "",
        "warnings": [],
        "missing_sections": [],
        "coverage": {},
        "requested_ledger": {
            "any_requested": False,
            "items": [],
            "unmet": [],
            "lines": [],
            "banner": "",
        },
        "contract_ledger": {
            "items": [],
            "failed": [],
            "unknown": [],
            "mandatory_missing": [],
            "answer_complete": True,
            "verified_allowed": True,
            "result_state": "COMPLETE",
            "lines": [],
        },
        "research_state": {
            "job_status": "FINISHED",
            "answer_state": "COMPLETE",
            "evidence_state": "MODERATE",
            "novelty_state": "NOVELTY UNVERIFIED",
            "reasons": {},
            "conflicts": [],
            "verified_allowed": True,
            "explain": {"answer_state": "jo maanga gaya tha, wo saara diya gaya"},
        },
    }


def test_missing_one_of_19_parts_hard_blocks_complete_and_is_machine_readable():
    original = _base_result()
    untouched = deepcopy(original)

    result = enforce_result(original)

    assert original == untouched
    assert result["status"] == "PARTIAL"
    audit = result["coverage"]["structured_answer"]
    assert audit["required"] is True
    assert audit["items_total"] == 19
    assert audit["items_covered"] == 18
    assert audit["complete"] is False
    assert audit["missing"] == ["10. Domain 10 Deep Explanation"]
    assert result["missing_sections"] == ["10. Domain 10 Deep Explanation"]
    assert "18/19" in result["status_reason"]
    assert "**PARTIAL — STRUCTURED COVERAGE**" in result["answer"]

    assert result["requested_ledger"]["unmet"][-1]["ok"] is False
    assert result["contract_ledger"]["answer_complete"] is False
    assert result["contract_ledger"]["verified_allowed"] is False
    assert result["contract_ledger"]["result_state"] == "PARTIAL"
    assert result["research_state"]["answer_state"] == "PARTIAL"
    assert result["research_state"]["verified_allowed"] is False


def test_structured_hard_block_is_idempotent_and_banner_cannot_self_satisfy_audit():
    once = enforce_result(_base_result())
    twice = enforce_result(once)

    assert twice == once
    assert twice["answer"].count("**PARTIAL — STRUCTURED COVERAGE**") == 1
    assert twice["coverage"]["structured_answer"]["items_covered"] == 18
    assert twice["coverage"]["structured_answer"]["missing"] == [
        "10. Domain 10 Deep Explanation"
    ]


def test_full_19_of_19_answer_keeps_complete_status():
    result = enforce_result(_base_result(missing_number=None))

    assert result["status"] == "COMPLETE"
    assert result["coverage"]["structured_answer"]["complete"] is True
    assert result["coverage"]["structured_answer"]["items_covered"] == 19
    assert result["missing_sections"] == []
    assert "PARTIAL — STRUCTURED COVERAGE" not in result["answer"]


def test_existing_research_incomplete_status_is_never_weakened_to_partial():
    result = enforce_result(_base_result(status="RESEARCH INCOMPLETE"))

    assert result["status"] == "RESEARCH INCOMPLETE"
    assert result["coverage"]["structured_answer"]["complete"] is False
    assert result["missing_sections"] == ["10. Domain 10 Deep Explanation"]
    assert "PARTIAL — STRUCTURED COVERAGE" not in result["answer"]


def test_quality_release_rechecks_old_quality_enforced_result_instead_of_bypassing_guard():
    legacy = _base_result()
    legacy["quality_enforced"] = True
    legacy["quality_gate"] = {"contract_version": "1.0", "answer_complete": True}

    result = enforce_quality_release(legacy)

    assert result["status"] == "PARTIAL"
    assert result["coverage"]["structured_answer"]["complete"] is False
    assert result["quality_gate"]["answer_complete"] is False
    issue_codes = {item["code"] for item in result["quality_gate"]["issues"]}
    assert "REQUESTED_DELIVERABLE_MISSING" in issue_codes
