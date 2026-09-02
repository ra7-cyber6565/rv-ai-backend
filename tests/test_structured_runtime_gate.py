from research_engine import ResearchResult


QUESTION = """
### 1. Consciousness and Self
### 2. Brain and Behaviour
### 3. Evolution and Culture
### 4. Information and Language
### 5. Game Theory and Society
### 6. Strategy and Agency
## Final Challenge
## Mandatory Evidence Standard
## Ultimate Question
""".strip()


def _answer(labels):
    return "\n\n".join(f"**{label}**\nSimple explanation." for label in labels)


ALL_LABELS = [
    "1. Consciousness and Self",
    "2. Brain and Behaviour",
    "3. Evolution and Culture",
    "4. Information and Language",
    "5. Game Theory and Society",
    "6. Strategy and Agency",
    "Final Challenge",
    "Mandatory Evidence Standard",
    "Ultimate Question",
]


def test_missing_structured_part_downgrades_complete_result():
    result = ResearchResult(
        question=QUESTION,
        answer=_answer(ALL_LABELS[:-1]),
        status="COMPLETE",
        research_state={"answer_state": "COMPLETE", "evidence_state": "MODERATE"},
    ).to_dict()

    assert result["status"] == "PARTIAL"
    assert "Ultimate Question" in result["missing_sections"]
    audit = result["coverage"]["structured_answer"]
    assert audit["required"] is True
    assert audit["complete"] is False
    assert audit["items_covered"] == len(ALL_LABELS) - 1
    assert audit["items_total"] == len(ALL_LABELS)
    assert result["research_state"]["answer_state"] == "PARTIAL"
    assert result["research_state"]["evidence_state"] == "MODERATE"
    assert "PARTIAL — STRUCTURED COVERAGE GAP" in result["answer"]
    assert any("STRUCTURED COVERAGE GAP" in w for w in result["warnings"])


def test_all_structured_parts_keep_complete_status():
    result = ResearchResult(
        question=QUESTION,
        answer=_answer(ALL_LABELS),
        status="COMPLETE",
        research_state={"answer_state": "COMPLETE"},
    ).to_dict()

    assert result["status"] == "COMPLETE"
    assert result["missing_sections"] == []
    assert result["coverage"]["structured_answer"]["complete"] is True
    assert "STRUCTURED COVERAGE GAP" not in result["answer"]
    assert result["research_state"]["answer_state"] == "COMPLETE"


def test_normal_short_question_is_not_forced_into_structured_gate():
    result = ResearchResult(
        question="Why is the sky blue?",
        answer="Rayleigh scattering explains most of it.",
        status="COMPLETE",
    ).to_dict()

    assert result["status"] == "COMPLETE"
    assert result["missing_sections"] == []
    assert result["coverage"]["structured_answer"]["required"] is False
    assert "STRUCTURED COVERAGE GAP" not in result["answer"]


def test_existing_incomplete_status_never_gets_upgraded_or_replaced():
    result = ResearchResult(
        question=QUESTION,
        answer=_answer(ALL_LABELS[:2]),
        status="RESEARCH INCOMPLETE",
        status_reason="reasoning model failed",
        missing_passes=["synthesis"],
        research_state={"answer_state": "FAILED"},
    ).to_dict()

    assert result["status"] == "RESEARCH INCOMPLETE"
    assert result["status_reason"].startswith("reasoning model failed")
    assert result["missing_passes"] == ["synthesis"]
    assert result["missing_sections"]
    assert result["research_state"]["answer_state"] == "FAILED"
