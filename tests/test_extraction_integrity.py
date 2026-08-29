from research_engine.extraction_integrity import (
    assess_ocr_confidences,
    native_text_integrity,
    passage_integrity_gate,
)
from research_engine.processing.ocr_processor import OCRProcessor


def test_high_ocr_quality_is_usable_but_not_called_accuracy_probability():
    result = assess_ocr_confidences(
        [96, 95, 94, 93, 92, 91, 90, 89, 88, 87],
        total_tokens=10,
        nonempty_tokens=10,
        language="eng",
        dpi=300,
    )
    assert result["quality_label"] == "high"
    assert result["review_required"] is False
    assert result["token_coverage"] == 1.0
    assert "NOT a calibrated probability" in result["confidence_semantics"]
    gate = passage_integrity_gate(result)
    assert gate["status"] == "pass"
    assert gate["blocks_strong_claim"] is False


def test_low_tail_blocks_even_when_some_words_are_high_confidence():
    result = assess_ocr_confidences(
        [99, 98, 97, 96, 95, 40, 35, 20, 10, 5],
        total_tokens=10,
        nonempty_tokens=10,
    )
    assert result["quality_label"] == "low"
    assert result["review_required"] is True
    assert result["low_confidence_fraction"] >= 0.5
    assert passage_integrity_gate(result)["blocks_strong_claim"] is True


def test_missing_or_invalid_confidence_fails_closed_to_review():
    result = assess_ocr_confidences(
        [-1, "-1", "nan", None], total_tokens=8, nonempty_tokens=4
    )
    assert result["quality_label"] == "unknown"
    assert result["valid_confidence_words"] == 0
    assert result["review_required"] is True
    assert passage_integrity_gate(result)["blocks_strong_claim"] is True


def test_native_capture_does_not_claim_source_truth():
    result = native_text_integrity(engine="pdf_native_text")
    assert result["quality_label"] == "native"
    assert "NOT source truth" in result["confidence_semantics"]
    gate = passage_integrity_gate(result)
    assert gate["status"] == "pass"
    assert gate["blocks_strong_claim"] is False


def test_unknown_transformation_method_blocks_strong_claim():
    gate = passage_integrity_gate({"method": "mystery_transform"})
    assert gate["status"] == "unknown"
    assert gate["blocks_strong_claim"] is True


class _Output:
    DICT = "DICT"


class _FakeTesseract:
    Output = _Output

    @staticmethod
    def image_to_data(_image, lang, output_type):
        assert lang == "eng"
        assert output_type == "DICT"
        return {
            "text": ["Measured", "temperature", "was", "300", "K"],
            "conf": ["96", "95", "94", "93", "92"],
            "block_num": [1, 1, 1, 1, 1],
            "par_num": [1, 1, 1, 1, 1],
            "line_num": [1, 1, 1, 1, 1],
        }


def test_ocr_processor_uses_image_to_data_and_emits_integrity_ledger():
    processor = OCRProcessor(lang="eng", dpi=250)
    captured = processor._ocr_image(_FakeTesseract, object())
    assert captured["text"] == "Measured temperature was 300 K"
    integrity = captured["integrity"]
    assert integrity["method"] == "ocr"
    assert integrity["engine"] == "tesseract"
    assert integrity["dpi"] == 250
    assert integrity["quality_label"] == "high"
