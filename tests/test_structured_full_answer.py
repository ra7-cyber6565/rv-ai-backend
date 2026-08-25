from research_engine.explain_style import style_block
from research_engine.structured_answer import (
    coverage,
    extract_outline,
    prompt_rule,
    requires_structured_coverage,
)


GRAND_SHAPE = """
## The Grand Unified Human Reality, Consciousness & Strategy Problem

### 1. Consciousness, Self and Inner Reality
Explain consciousness and competing explanations.

### 2. Brain, Attention, Motivation and Behaviour
Explain dopamine, habits and Flow State.

### 3. Evolutionary Foundations
Explain adaptive mechanisms and mismatch.

### 4. Information, Language and Reality Construction
Explain signal/noise, language and identity.

### 5. Culture and Civilization
Explain myths, institutions and incentives.

### 6. Game Theory and Strategic Behaviour
Explain cooperation, defection and coordination.

### 7. Power, Geopolitics and Great-Power Competition
Compare realism with domestic and psychological factors.

### 8. Secret Societies, Power Networks and Conspiracy Claims
Separate documented evidence from speculation.

### 9. CIA Documents and Altered Consciousness Research
Do not confuse investigation with proof.

### 10. Frequency, Vibration and Quantum Claims
Separate physics from metaphor.

### 11. Cosmology and Existential Meaning
Compare scientific and philosophical answers.

### 12. Neville Goddard, Belief and Manifestation
Compare causal models and tests.

### 13. Naval Ravikant, Wealth and Leverage
Test universality versus context.

### 14. Asymmetric Bets and Decision Theory
Include ruin risk and optionality.

### 15. Hedonic Adaptation and the Good Life
Compare pleasure, meaning and mastery.

### 16. Integrated Human Agency Model
Build the integrated causal model.

## Final Challenge
Compare Person A and Person B over 20 years.

## Mandatory Evidence Standard
Separate strong evidence from speculation.

## Ultimate Question
Give the best defensible integrated model and identify important beliefs.
"""


def test_extract_outline_keeps_all_user_high_level_parts_in_source_order():
    outline = extract_outline(GRAND_SHAPE)
    labels = [item["label"] for item in outline]

    assert len(outline) == 19
    assert labels[0] == "1. Consciousness, Self and Inner Reality"
    assert labels[15] == "16. Integrated Human Agency Model"
    assert labels[-3:] == [
        "Final Challenge",
        "Mandatory Evidence Standard",
        "Ultimate Question",
    ]
    assert "The Grand Unified Human Reality, Consciousness & Strategy Problem" not in labels


def test_long_outline_creates_mandatory_simple_answer_map_without_new_headings():
    assert requires_structured_coverage(GRAND_SHAPE) is True
    block = prompt_rule(GRAND_SHAPE)

    assert "FULL COVERAGE CONTRACT" in block
    assert "**1. Consciousness, Self and Inner Reality**" in block
    assert "**16. Integrated Human Agency Model**" in block
    assert "**Ultimate Question**" in block
    assert "Evidence kam ho to item ko hatao MAT" in block
    assert "`##`/`###` mat lagao" in block


def test_simple_explanation_style_is_actually_wired_to_long_outline_contract():
    block = style_block(GRAND_SHAPE, ["1. Seedha Jawab", "2. Established Knowledge"])

    assert "SAMJHANE KA TARIKA" in block
    assert "FULL COVERAGE CONTRACT" in block
    assert "**9. CIA Documents and Altered Consciousness Research**" in block
    assert "Section heading BILKUL jaisi di gayi hai" in block


def test_normal_question_does_not_get_forced_multi_part_outline():
    question = "dopamine loop simple words me samjhao"
    assert requires_structured_coverage(question) is False
    assert prompt_rule(question) == ""
    assert "FULL COVERAGE CONTRACT" not in style_block(question)


def test_outline_delivery_audit_reports_exact_missing_part_without_claiming_truth():
    answer = "\n".join(
        f"**{item['label']}**\nSimple explanation."
        for item in extract_outline(GRAND_SHAPE)
        if item["number"] != 10
    )
    report = coverage(GRAND_SHAPE, answer)

    assert report["required"] is True
    assert report["complete"] is False
    assert report["items_total"] == 19
    assert report["items_covered"] == 18
    assert report["missing"] == ["10. Frequency, Vibration and Quantum Claims"]
    assert "not evidence/truth verification" in report["note"]


def test_outline_delivery_audit_passes_when_every_user_part_is_present():
    answer = "\n".join(
        f"**{item['label']}**\nSimple explanation with evidence/limits where available."
        for item in extract_outline(GRAND_SHAPE)
    )
    report = coverage(GRAND_SHAPE, answer)

    assert report["complete"] is True
    assert report["items_covered"] == report["items_total"] == 19
    assert report["missing"] == []
