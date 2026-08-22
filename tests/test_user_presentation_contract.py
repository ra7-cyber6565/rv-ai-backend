"""Independent tests for the user's human-first final-answer contract.

These tests intentionally do not depend on Gemini/network. They protect the
453-line presentation requirements from future regressions.
"""
from __future__ import annotations

from research_engine.models import EvidencePack, SourceRecord, SourceType
from research_engine.synthesizer import FinalSynthesizer, SECTION_TITLES


EXPECTED_ORDER = [
    "Seedha jawab",
    "Research se kya pata chala?",
    "Ye kyun hota hai?",
    "Evidence kya kehta hai?",
    "Iske against kya mila?",
    "Humari Hypotheses",
    "Hypothesis ko kaise test karenge?",
    "Kya abhi unknown hai?",
    "Final conclusion",
    "Sources",
    "Research quality / technical audit",
]


def _source(source_id: str, level: str, *, snippet: str = "Useful research evidence") -> SourceRecord:
    s = SourceRecord(
        title=f"Source {source_id}",
        url=f"https://example.org/{source_id.lower()}",
        snippet=snippet,
        source_type=SourceType.PAPER,
        read_level=level,
        relevance_score=0.8,
        quality_score=0.8,
        peer_reviewed=True,
    )
    s.source_id = source_id
    if level == "full_text":
        s.full_text_chars = max(500, len(snippet))
    return s


def test_required_human_first_section_order_is_canonical():
    assert SECTION_TITLES == EXPECTED_ORDER
    assert SECTION_TITLES[0] == "Seedha jawab"
    assert SECTION_TITLES[-2:] == ["Sources", "Research quality / technical audit"]


def test_prompt_explicitly_keeps_internal_technical_junk_out_of_main_answer():
    synth = FinalSynthesizer()
    pack = EvidencePack(question="test", sources=[_source("S1", "abstract")])
    prompt = synth.prompt(
        question="test question",
        analysis="internal analysis",
        critique="",
        hypothesis_text="",
        pack=pack,
        plan={"relevant_fields": ["science"]},
    ).lower()
    for required in (
        "seedha jawab",
        "pipeline",
        "connector",
        "[pass]",
        "[fail]",
        "technical",
        "simple example",
    ):
        assert required in prompt
    assert "system ka andar ka kaam mat likho" in prompt


def test_hypothesis_template_explains_every_required_user_facing_part():
    synth = FinalSynthesizer()
    source = _source("S1", "full_text", snippet="AI signal optimization reduced waiting time.")
    pack = EvidencePack(question="traffic", sources=[source])
    hypothesis = {
        "statement": "Integrated AI traffic control may reduce congestion.",
        "simple": "AI signals aur public transport ko saath optimize kare.",
        "reasoning": "Different transport parts affect each other.",
        "supporting_evidence": ["S1"],
        "contradicting_evidence": ["S1"],
        "risks": ["Bad sensor data"],
        "assumptions": ["Sensors reliable hain"],
        "how_to_test": ["A/B city corridor trial"],
        "prediction": {
            "variables": ["waiting time"],
            "expected_outcome": "waiting time ghatni chahiye",
            "measurement_method": "before/after sensors",
            "falsification_condition": "waiting time same ya zyada rahe",
        },
        "if_true": ["system ko scale kiya ja sakta hai"],
        "if_false": ["signal-only approach reject hogi"],
        "status": "UNTESTED HYPOTHESIS",
        "confidence_reasoning_based": "moderate",
    }
    text = synth._hypothesis_section([hypothesis], pack=pack)
    for phrase in (
        "Simple words mein:",
        "Is idea ko support karne wali research:",
        "Iske against evidence:",
        "Problem / risk:",
        "Humari assumption:",
        "Isko test kaise karenge:",
        "Agar ye sahi hua:",
        "Agar ye galat hua:",
        "Current status: UNTESTED",
    ):
        assert phrase in text


def test_large_pdf_selected_pages_are_never_called_whole_document_read():
    synth = FinalSynthesizer()
    source = _source("S1", "full_text", snippet="Relevant page excerpt about superconductivity.")
    source.pages_read = 7
    source.pages_total = 300
    source.read_note = "300 pages mein se 7 relevant pages process hue."
    pack = EvidencePack(question="superconductivity", sources=[source])

    source_text = synth._sources_section(pack, honesty={"cited": [{"source_id": "S1"}]})
    assert "PARTIAL FULL-TEXT REVIEW" in source_text
    assert "7/300" in source_text
    assert "poora document padha gaya aisa claim nahi" in source_text
    assert "FULL-TEXT VERIFIED — poora text padha gaya" not in source_text

    access_text = synth._access_block({"read_levels": {"full_text": 1}}, pack)
    assert "7/300" in access_text
    assert "poora document ek saath nahi" in access_text
    assert "claim verification alag A-E check" in access_text


def test_full_text_access_does_not_automatically_claim_entailment_verified():
    synth = FinalSynthesizer()
    source = _source("S1", "full_text")
    pack = EvidencePack(question="test", sources=[source])
    text = synth._sources_section(pack)
    assert "FULL-TEXT VERIFIED ACCESS" in text
    assert "claim ka support/entailment alag evidence-verification gate" in text


def test_abstract_snippet_metadata_access_labels_remain_explicit():
    synth = FinalSynthesizer()
    sources = [
        _source("S1", "abstract"),
        _source("S2", "snippet"),
        _source("S3", "metadata", snippet=""),
    ]
    pack = EvidencePack(question="test", sources=sources)
    text = synth._sources_section(pack)
    assert "ABSTRACT REVIEWED" in text
    assert "SNIPPET ONLY" in text
    assert "METADATA ONLY" in text


def test_human_readable_audit_does_not_dump_pass_fail_tokens():
    synth = FinalSynthesizer()
    verification = {
        "status": "UNVERIFIABLE HERE",
        "checks": [
            {"check": "Claim cited text/excerpt se support hoti hai", "passed": False,
             "detail": "claim aur cited excerpt ka support match nahi hua"},
            {"check": "Cited source sawal se relevant hai", "passed": True,
             "detail": "relevance check pass hua"},
        ],
    }
    text = synth._numbers_check(verification)
    assert "[PASS]" not in text
    assert "[FAIL]" not in text
    assert "problem" in text.lower()


def test_access_depth_text_never_equates_full_text_with_automatic_claim_verification():
    synth = FinalSynthesizer()
    pack = EvidencePack(question="test", sources=[_source("S1", "full_text")])
    text = synth._access_block({"read_levels": {"full_text": 1}}, pack).lower()
    assert "automatically verified nahi" in text
