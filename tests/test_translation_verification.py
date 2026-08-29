from research_engine.translation_verification import (
    TranslationCandidate,
    TranslationVerifier,
    VERDICT_INSUFFICIENT,
    VERDICT_OK,
    VERDICT_REVIEW,
    source_text_hash,
)
from research_engine.extraction_integrity import passage_integrity_gate


def _candidate(source, translator_id, text, *, method, revision):
    return TranslationCandidate(
        translator_id=translator_id,
        text=text,
        source_hash=source_text_hash(source),
        source_language="de",
        target_language="en",
        method=method,
        revision=revision,
    )


def test_two_independent_agreeing_translations_pass_consistency_gate():
    source = "Die gemessene Temperatur betrug 300 K und der Druck 5 GPa."
    a = _candidate(
        source, "translator-A",
        "The measured temperature was 300 K and the pressure was 5 GPa.",
        method="model-a", revision="r1",
    )
    b = _candidate(
        source, "translator-B",
        "The measured temperature was 300 K and the pressure was 5 GPa.",
        method="model-b", revision="r7",
    )
    result = TranslationVerifier().verify(
        source, [a, b], critical_terms=["temperature", "pressure"]
    )
    assert result.verdict == VERDICT_OK
    assert result.review_required is False
    assert result.truth_proven is False
    payload = result.to_dict()
    assert payload["verification_verdict"] == VERDICT_OK
    assert payload["agreement_score"] == 1.0
    assert payload["disagreement_flags"] == []
    assert passage_integrity_gate(payload)["blocks_strong_claim"] is False


def test_same_translator_identity_is_not_independent_validation():
    source = "Messwert 300 K."
    text = "Measured value 300 K."
    a = _candidate(source, "same", text, method="model-a", revision="r1")
    b = _candidate(source, "same", text, method="model-b", revision="r2")
    result = TranslationVerifier().verify(source, [a, b])
    assert result.verdict == VERDICT_INSUFFICIENT
    assert result.review_required is True


def test_same_implementation_under_two_names_is_flagged():
    source = "Messwert 300 K."
    text = "Measured value 300 K."
    a = _candidate(source, "A", text, method="same-model", revision="same")
    b = _candidate(source, "B", text, method="same-model", revision="same")
    result = TranslationVerifier().verify(source, [a, b])
    assert result.verdict == VERDICT_REVIEW
    assert "translator_implementation_not_distinct" in result.disagreement_flags


def test_source_hash_mismatch_cannot_be_compared_as_same_passage():
    source = "Messwert 300 K."
    a = _candidate(source, "A", "Measured value 300 K.", method="a", revision="1")
    b = TranslationCandidate(
        translator_id="B",
        text="Measured value 300 K.",
        source_hash="0" * 64,
        source_language="de",
        target_language="en",
        method="b",
        revision="2",
    )
    result = TranslationVerifier().verify(source, [a, b])
    assert result.verdict == VERDICT_REVIEW
    assert "source_hash_mismatch" in result.disagreement_flags


def test_number_loss_forces_review_even_when_wording_is_similar():
    source = "Die Temperatur war 300 K und der Druck 5 GPa."
    a = _candidate(
        source, "A",
        "The temperature was 300 K and the pressure was 5 GPa.",
        method="a", revision="1",
    )
    b = _candidate(
        source, "B",
        "The temperature was 300 K and the pressure was measured.",
        method="b", revision="2",
    )
    result = TranslationVerifier().verify(source, [a, b])
    assert result.verdict == VERDICT_REVIEW
    assert "number_disagreement:B" in result.disagreement_flags
    assert passage_integrity_gate(result.to_dict())["blocks_strong_claim"] is True


def test_negation_disagreement_forces_review():
    source = "Das Ergebnis war nicht signifikant."
    a = _candidate(
        source, "A", "The result was not statistically significant.",
        method="a", revision="1",
    )
    b = _candidate(
        source, "B", "The result was statistically significant.",
        method="b", revision="2",
    )
    result = TranslationVerifier().verify(source, [a, b])
    assert result.verdict == VERDICT_REVIEW
    assert any(flag.startswith("negation_disagreement:")
               for flag in result.disagreement_flags)
