from research_engine.capture_integrity_wiring import IntegrityPassage
from research_engine.capability_registry import CAPABILITY_BY_ID, ProofKind
from research_engine.claim_verification import (
    GENUINE_SUPPORT,
    SOURCE_REPORTED,
    verify_claim,
)
from research_engine.content_fetcher import ContentFetcher
from research_engine.extraction_integrity import assess_ocr_confidences
from research_engine.models import EvidencePack, SourceRecord, SourceType
from research_engine.translation_verification import (
    TranslationCandidate,
    TranslationVerifier,
    source_text_hash,
)


CLAIM = "The measured temperature was 300 K and pressure was 5 GPa in the experiment."
PASSAGE_TEXT = (
    CLAIM + " The measurement protocol used calibrated instruments and the reported "
    "values were recorded directly during the controlled experimental run."
)


def _source():
    return SourceRecord(
        source_id="S1",
        title="Measurement paper",
        url="https://example.org/paper",
        snippet=PASSAGE_TEXT,
        source_type=SourceType.PAPER,
        read_level="full_text",
        full_text_chars=len(PASSAGE_TEXT),
        relevance_score=0.95,
        quality_score=0.90,
        peer_reviewed=True,
    )


def _pack(integrity):
    source = _source()
    passage = IntegrityPassage(
        source_id="S1",
        text=PASSAGE_TEXT,
        locator="p.1",
        provenance="full_text_excerpt",
        read_level_at_capture="full_text",
        extraction_integrity=dict(integrity),
    )
    return EvidencePack(question="What was measured?", sources=[source], passages=[passage])


def _line():
    return f"[FACT] {CLAIM} [S1]"


def _high_ocr():
    return assess_ocr_confidences(
        [97, 96, 95, 94, 93, 92, 91, 90, 89, 88],
        total_tokens=10,
        nonempty_tokens=10,
        language="eng",
        dpi=300,
    )


def _low_ocr():
    return assess_ocr_confidences(
        [95, 94, 40, 35, 30, 20, 15, 10, 5, 2],
        total_tokens=10,
        nonempty_tokens=10,
        language="eng",
        dpi=200,
    )


def test_registry_requires_production_wiring_for_translation_and_ocr():
    assert ProofKind.WIRING in CAPABILITY_BY_ID[105].required_proofs
    assert ProofKind.WIRING in CAPABILITY_BY_ID[106].required_proofs


def test_integrity_passage_serializes_capture_metadata():
    passage = _pack(_high_ocr()).passages[0]
    payload = passage.to_dict()
    assert payload["extraction_integrity"]["method"] == "ocr"
    assert payload["extraction_integrity"]["quality_label"] == "high"


def test_high_ocr_can_pass_same_source_ae_plus_capture_gate():
    checked = verify_claim(_line(), _pack(_high_ocr()))
    assert checked.verdict == GENUINE_SUPPORT
    assert checked.passes_ae is True
    assert checked.supporting_source_id == "S1"
    assert checked.source_checks[0]["capture_integrity"]["status"] == "pass"
    assert checked.source_checks[0]["capture_integrity"]["blocks_strong_claim"] is False


def test_low_ocr_blocks_verified_support_even_when_a_to_e_pass():
    checked = verify_claim(_line(), _pack(_low_ocr()))
    statuses = {
        item["check"]: item["status"]
        for item in checked.source_checks[0]["checks"]
    }
    assert statuses == {"A": "pass", "B": "pass", "C": "pass", "D": "pass", "E": "pass"}
    assert checked.source_checks[0]["capture_integrity"]["blocks_strong_claim"] is True
    assert checked.source_checks[0]["passes_ae"] is False
    assert checked.passes_ae is False
    assert checked.verdict == SOURCE_REPORTED
    assert checked.supporting_source_id == ""
    assert "capture/transformation integrity" in checked.reason


def _translation_payload(*, good=True):
    source_text = "Die gemessene Temperatur betrug 300 K und der Druck 5 GPa."
    digest = source_text_hash(source_text)
    first = TranslationCandidate(
        translator_id="A",
        text="The measured temperature was 300 K and the pressure was 5 GPa.",
        source_hash=digest,
        source_language="de",
        target_language="en",
        method="model-a",
        revision="r1",
    )
    second_text = (
        "The measured temperature was 300 K and the pressure was 5 GPa."
        if good else
        "The measured temperature was 300 K and the pressure was not reported."
    )
    second = TranslationCandidate(
        translator_id="B",
        text=second_text,
        source_hash=digest,
        source_language="de",
        target_language="en",
        method="model-b",
        revision="r2",
    )
    return TranslationVerifier().verify(
        source_text, [first, second], critical_terms=["temperature", "pressure"]
    ).to_dict()


def test_independently_verified_translation_can_pass_capture_gate():
    checked = verify_claim(_line(), _pack(_translation_payload(good=True)))
    assert checked.passes_ae is True
    assert checked.verdict == GENUINE_SUPPORT
    assert checked.source_checks[0]["capture_integrity"]["status"] == "pass"


def test_translation_disagreement_blocks_verified_support():
    checked = verify_claim(_line(), _pack(_translation_payload(good=False)))
    assert checked.passes_ae is False
    assert checked.verdict == SOURCE_REPORTED
    assert checked.source_checks[0]["capture_integrity"]["blocks_strong_claim"] is True


def test_content_fetcher_excerpt_preserves_chunk_integrity_metadata():
    fetcher = ContentFetcher(allow_network=False)
    integrity = _low_ocr()
    chunks = [
        {
            "locator": "p.7 (OCR)",
            "text": PASSAGE_TEXT,
            "header": "[Source: scan.pdf, Page 7]",
            "extraction_integrity": integrity,
        }
    ]
    picked = fetcher.best_excerpts(chunks, "measured temperature pressure", 1000)
    assert len(picked) == 1
    assert picked[0]["extraction_integrity"]["method"] == "ocr"
    assert picked[0]["extraction_integrity"]["review_required"] is True
