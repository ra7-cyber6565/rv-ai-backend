"""Offline regression for the Claude-main + ChatGPT safety-facade integration.

This catches the exact class of merge bug where the latest Claude implementation
exists in the branch but production imports accidentally point at an older base,
or where the orchestrator passes a keyword the safety facade no longer accepts.
No network/model/API key is used.
"""
from __future__ import annotations

from research_engine.claim_labels import downgrade
from research_engine.models import EvidencePack, SourceRecord, SourceType
from research_engine.synthesizer import FinalSynthesizer
from research_engine.verification import VerificationEngine


def _pack() -> EvidencePack:
    text = (
        "Higher urban density reduces per-capita car travel in the reported "
        "analysis. The study reports a 30 percent reduction."
    )
    source = SourceRecord(
        title="Urban density and car travel",
        url="https://example.org/paper",
        snippet=text,
        source_type=SourceType.PAPER,
        peer_reviewed=True,
        read_level="full_text",
        full_text_chars=len(text),
        relevance_score=0.9,
        quality_score=0.8,
    )
    source.source_id = "S1"
    return EvidencePack(
        question="Does higher urban density reduce per-capita car travel?",
        sources=[source],
        topic_terms=["urban", "density", "car", "travel"],
    )


def test_orchestrator_label_keyword_is_accepted_and_strict_gate_can_pass():
    pack = _pack()
    text, report = downgrade(
        "[ESTABLISHED] Higher urban density reduces per-capita car travel [S1].",
        pack,
        check_entailment=True,
    )
    assert "[ESTABLISHED]" in text
    assert report["a_e_checked"] == 1
    assert report["a_e_failed"] == 0


def test_strict_label_gate_fails_closed_when_same_source_does_not_support_claim():
    pack = _pack()
    text, report = downgrade(
        "[FACT] Higher urban density increases per-capita car travel [S1].",
        pack,
        check_entailment=True,
    )
    assert "[FACT]" not in text
    assert "[UNVERIFIED]" in text
    assert report["a_e_failed"] == 1


def test_verification_facade_preserves_claude_physics_and_adds_AE_report():
    pack = _pack()
    report = VerificationEngine().verify(
        "[FACT] Higher urban density reduces per-capita car travel [S1].",
        pack,
        citation_ok=True,
        ungrounded_count=0,
        cited_ids=["S1"],
    ).to_dict()
    assert "physics" in report, "Claude physics/math verification field was lost in facade"
    assert "evidence_verification" in report, "ChatGPT A-E safety field missing"
    assert report["evidence_verification"]["claims_checked"] == 1


def test_synthesizer_facade_keeps_claude_new_sections_and_chatgpt_guard():
    synth = FinalSynthesizer()
    assert callable(getattr(synth, "_claim_check_block", None)), (
        "Claude latest claim-check presentation was lost during facade integration"
    )
    assert hasattr(synth, "presentation_guard"), "ChatGPT presentation guard missing"


if __name__ == "__main__":
    # Keep this file useful in the project's standalone `python tests/test_*.py`
    # loop as well as under pytest.
    test_orchestrator_label_keyword_is_accepted_and_strict_gate_can_pass()
    test_strict_label_gate_fails_closed_when_same_source_does_not_support_claim()
    test_verification_facade_preserves_claude_physics_and_adds_AE_report()
    test_synthesizer_facade_keeps_claude_new_sections_and_chatgpt_guard()
    print("integrated facade regression: PASS")
