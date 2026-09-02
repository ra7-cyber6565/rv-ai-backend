from research_engine.capture_integrity_wiring import IntegrityPassage
from research_engine.capability_registry import CAPABILITY_BY_ID, ProofKind
from research_engine.claim_verification import (
    GENUINE_SUPPORT,
    SOURCE_REPORTED,
    verify_claim,
)
from research_engine.content_fetcher import ContentFetcher
from research_engine.extraction_integrity import assess_ocr_confidences
from research_engine.models import EvidencePack, Passage, SourceRecord, SourceType
from research_engine.translation_verification import (
    TranslationCandidate,
    TranslationVerifier,
    source_text_hash,
)
from research_engine.verification import VerificationEngine


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


def _pack(integrity, *, locator="p.1", passage_cls=IntegrityPassage):
    source = _source()
    kwargs = dict(
        source_id="S1",
        text=PASSAGE_TEXT,
        locator=locator,
        provenance="full_text_excerpt",
        read_level_at_capture="full_text",
    )
    if passage_cls is IntegrityPassage:
        kwargs["extraction_integrity"] = dict(integrity)
    passage = passage_cls(**kwargs)
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


def test_high_ocr_can_pass_same_source_ae_plus_separate_capture_gate():
    checked = verify_claim(_line(), _pack(_high_ocr()))
    assert checked.verdict == GENUINE_SUPPORT
    assert checked.passes_ae is True
    assert checked.passes_verified_support is True
    assert checked.capture_integrity_passed is True
    assert checked.supporting_source_id == "S1"
    path = checked.source_checks[0]
    assert path["passes_ae"] is True
    assert path["capture_integrity"]["status"] == "pass"
    assert path["capture_integrity_passed"] is True
    assert path["passes_verified_support"] is True
    payload = checked.to_dict()
    assert payload["same_source_ae_passed"] is True
    assert payload["capture_integrity_passed"] is True
    assert payload["verified_support"] is True


def test_low_ocr_blocks_verified_support_without_rewriting_a_to_e_truth():
    checked = verify_claim(_line(), _pack(_low_ocr()))
    statuses = {
        item["check"]: item["status"]
        for item in checked.source_checks[0]["checks"]
    }
    assert statuses == {"A": "pass", "B": "pass", "C": "pass", "D": "pass", "E": "pass"}
    path = checked.source_checks[0]
    assert path["passes_ae"] is True
    assert checked.passes_ae is True
    assert path["capture_integrity"]["blocks_strong_claim"] is True
    assert path["capture_integrity_passed"] is False
    assert path["passes_verified_support"] is False
    assert checked.capture_integrity_passed is False
    assert checked.passes_verified_support is False
    assert checked.verdict == SOURCE_REPORTED
    assert checked.supporting_source_id == ""
    assert "capture/transformation integrity" in checked.reason
    payload = checked.to_dict()
    assert payload["same_source_ae_passed"] is True
    assert payload["capture_integrity_passed"] is False
    assert payload["verified_support"] is False


def test_declared_ocr_with_missing_integrity_ledger_fails_closed():
    checked = verify_claim(
        _line(),
        _pack({}, locator="p.1 (OCR)", passage_cls=IntegrityPassage),
    )
    path = checked.source_checks[0]
    assert path["passes_ae"] is True
    assert path["capture_integrity"]["status"] == "missing_integrity_metadata"
    assert path["capture_integrity"]["blocks_strong_claim"] is True
    assert checked.passes_verified_support is False
    assert checked.verdict == SOURCE_REPORTED


def test_legacy_native_passage_without_transform_hint_keeps_compatibility():
    checked = verify_claim(_line(), _pack({}, passage_cls=Passage))
    path = checked.source_checks[0]
    assert path["passes_ae"] is True
    assert path["capture_integrity"]["status"] == "unknown"
    assert path["capture_integrity"]["blocks_strong_claim"] is False
    assert checked.passes_verified_support is True
    assert checked.verdict == GENUINE_SUPPORT


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
    assert checked.passes_verified_support is True
    assert checked.verdict == GENUINE_SUPPORT
    assert checked.source_checks[0]["capture_integrity"]["status"] == "pass"


def test_translation_disagreement_blocks_verified_support_but_not_a_to_e():
    checked = verify_claim(_line(), _pack(_translation_payload(good=False)))
    assert checked.passes_ae is True
    assert checked.passes_verified_support is False
    assert checked.verdict == SOURCE_REPORTED
    path = checked.source_checks[0]
    assert path["passes_ae"] is True
    assert path["capture_integrity"]["blocks_strong_claim"] is True
    assert path["passes_verified_support"] is False


def test_integrated_verification_engine_exposes_f_capture_gate():
    high = VerificationEngine().verify(
        _line(), _pack(_high_ocr()), citation_ok=True, ungrounded_count=0,
        hypotheses=[], cited_ids=["S1"], question="What was measured?",
    )
    high_ev = high.evidence_verification
    assert high_ev["checks"]["F_capture_integrity"] is True
    assert high_ev["gate_passed"] is True

    low = VerificationEngine().verify(
        _line(), _pack(_low_ocr()), citation_ok=True, ungrounded_count=0,
        hypotheses=[], cited_ids=["S1"], question="What was measured?",
    )
    low_ev = low.evidence_verification
    assert low_ev["checks"]["F_capture_integrity"] is False
    assert low_ev["gate_passed"] is False
    assert low_ev["items"][0]["capture_integrity"] is False
    assert low.status != "SOURCE GROUNDED"


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
