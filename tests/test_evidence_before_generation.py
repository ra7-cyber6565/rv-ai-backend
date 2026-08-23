"""Regression tests for literal evidence-before-generation grounding."""
from __future__ import annotations

from research_engine.evidence_before_generation import prepare_evidence_first_prompt
from research_engine.models import EvidencePack, Passage, SourceRecord, SourceType
from research_engine.synthesizer import FinalSynthesizer


QUESTION = "What superconducting transition temperature does LaH10 show at 170 GPa?"
SUPPORT = (
    "Electrical resistance measurements show that lanthanum hydride LaH10 has "
    "a superconducting transition temperature of 250 K at a pressure of 170 GPa. "
    "Magnetic susceptibility tracks the same transition in the experiment."
)
DISTRACTOR = (
    "A botanical field survey catalogued alpine moss species, leaf shape, soil "
    "moisture, flowering time, and seasonal rainfall across mountain transects."
)


def _source(sid: str, text: str, *, relevance: float = 0.9,
            quality: float = 0.8, read_level: str = "full_text",
            retracted=False, rejected_reason: str = "") -> SourceRecord:
    return SourceRecord(
        title=f"Fixture {sid}",
        url=f"https://example.org/{sid}",
        snippet=text,
        connector="fixture",
        source_type=SourceType.PAPER,
        source_id=sid,
        relevance_score=relevance,
        quality_score=quality,
        read_level=read_level,
        full_text_chars=20000 if read_level == "full_text" else 0,
        peer_reviewed=True,
        retracted=retracted,
        rejected_reason=rejected_reason,
    )


def _pack() -> EvidencePack:
    good = _source("S1", "source-level fallback should not replace exact passage")
    junk = _source("S2", DISTRACTOR, relevance=0.05, quality=0.9)
    return EvidencePack(
        question=QUESTION,
        sources=[good, junk],
        passages=[
            Passage(source_id="S1", text=SUPPORT, locator="p.42 ¶3"),
            Passage(source_id="S2", text=DISTRACTOR, locator="p.9 ¶1"),
        ],
    )


def test_preselection_uses_exact_passage_locator_and_is_deterministic():
    pack = _pack()
    reduced_a, block_a, audit_a = prepare_evidence_first_prompt(QUESTION, pack)
    reduced_b, block_b, audit_b = prepare_evidence_first_prompt(QUESTION, pack)

    assert audit_a == audit_b
    assert block_a == block_b
    assert audit_a["selected_span_count"] == 1
    assert audit_a["strong_eligible_count"] == 1
    row = audit_a["selected"][0]
    assert row["source_id"] == "S1"
    assert row["locator"] == "p.42 ¶3"
    assert row["strong_eligible"] is True
    assert len(row["passage_hash"]) == 16
    assert reduced_a.sources[0].snippet == SUPPORT
    assert reduced_a.sources[0].locator == "p.42 ¶3"
    assert reduced_a.passages[0].text == SUPPORT


def test_preselection_does_not_mutate_original_pack_or_borrow_distractor_text():
    pack = _pack()
    original_snippet = pack.by_id("S1").snippet
    original_count = len(pack.sources)

    reduced, block, audit = prepare_evidence_first_prompt(QUESTION, pack)

    assert len(pack.sources) == original_count
    assert pack.by_id("S1").snippet == original_snippet
    assert audit["original_pack_mutated"] is False
    assert [s.source_id for s in reduced.sources] == ["S1"]
    assert DISTRACTOR not in block


def test_retracted_or_rejected_sources_never_seed_the_draft():
    retracted = _source("S1", SUPPORT, retracted=True)
    rejected = _source("S2", SUPPORT, rejected_reason="off_topic")
    pack = EvidencePack(
        question=QUESTION,
        sources=[retracted, rejected],
        passages=[
            Passage(source_id="S1", text=SUPPORT, locator="p.1"),
            Passage(source_id="S2", text=SUPPORT, locator="p.2"),
        ],
    )

    reduced, block, audit = prepare_evidence_first_prompt(QUESTION, pack)

    assert reduced.sources == []
    assert audit["selected_span_count"] == 0
    assert audit["strong_claims_pre_draft_allowed"] is False
    assert "NO ELIGIBLE EVIDENCE SPAN" in block


def test_abstract_can_seed_source_reported_but_not_strong_fact():
    abstract = _source("S3", SUPPORT, read_level="abstract")
    pack = EvidencePack(
        question=QUESTION,
        sources=[abstract],
        passages=[Passage(source_id="S3", text=SUPPORT, locator="abstract")],
    )

    reduced, block, audit = prepare_evidence_first_prompt(QUESTION, pack)

    assert [s.source_id for s in reduced.sources] == ["S3"]
    assert audit["selected_span_count"] == 1
    assert audit["strong_eligible_count"] == 0
    assert audit["strong_claims_pre_draft_allowed"] is False
    assert "strong_eligible=no" in block


def test_final_synthesizer_prompt_is_reduced_to_preselected_exact_spans():
    pack = _pack()
    synth = FinalSynthesizer()

    prompt = synth.prompt(QUESTION, "analysis text", "", "", pack, {})

    assert "EVIDENCE-FIRST DRAFTING CONTRACT (SYSTEM-OWNED)" in prompt
    assert "do not invent a claim and search for a citation afterwards" in prompt
    assert "source=[S1] locator=p.42 ¶3" in prompt
    assert SUPPORT in prompt
    assert DISTRACTOR not in prompt
    assert "[S2]" not in prompt
    assert synth.last_evidence_preselection["selected_span_count"] == 1
    assert synth.last_evidence_preselection["strong_eligible_count"] == 1
    assert synth.last_evidence_preselection["final_same_source_ae_still_required"] is True


def test_no_selected_span_makes_model_prompt_explicitly_fail_closed():
    source = _source("S8", DISTRACTOR, relevance=0.01, quality=0.9)
    pack = EvidencePack(
        question=QUESTION,
        sources=[source],
        passages=[Passage(source_id="S8", text=DISTRACTOR, locator="p.3")],
    )
    synth = FinalSynthesizer()

    prompt = synth.prompt(QUESTION, "analysis text", "", "", pack, {})

    assert "NO ELIGIBLE EVIDENCE SPAN WAS PRESELECTED" in prompt
    assert "Strong factual claims are prohibited" in prompt
    assert "(Koi source retrieve nahi hua.)" in prompt
    assert synth.last_evidence_preselection["selected_span_count"] == 0
    assert synth.last_evidence_preselection["strong_claims_pre_draft_allowed"] is False
