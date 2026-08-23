"""P0-C regressions: contradiction must be claim-span grounded and accounting-safe."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import claim_verification as CV
from research_engine import final_quality_gate as FQ
from research_engine.models import EvidencePack, Passage, SourceRecord, SourceType
from research_engine.quality_producers import quality_context


CLAIM_TEXT = (
    "The trial shows that intervention X lowers systolic blood pressure by "
    "12 mmHg after twelve weeks in adults"
)
LINE_S1 = f"[ESTABLISHED FACT] {CLAIM_TEXT} [S1]"

SUPPORT_SPAN = (
    "Among adults assigned intervention X, systolic blood pressure was 12 mmHg "
    "lower than control after twelve weeks. The prespecified primary endpoint "
    "used standardized seated measurements in 240 participants, with blinded "
    "outcome assessment and complete follow-up for the main comparison."
)
DISTANT_OPPOSE = (
    "A secondary exploratory analysis of intervention X in adults reported no "
    "significant effect on systolic blood pressure after twelve weeks. This "
    "secondary paragraph used a different subgroup and was not the prespecified "
    "primary endpoint used for the main claim above."
)
EXACT_OPPOSE = (
    "The trial of intervention X in adults reported no significant effect on "
    "systolic blood pressure after twelve weeks. The prespecified comparison "
    "found no benefit for the intervention, and the observed between-group "
    "difference was small and inconsistent with the claimed 12 mmHg reduction."
)
NEUTRAL_MUTATION = (
    "The trial of intervention X in adults described systolic blood pressure "
    "measurements after twelve weeks. The prespecified comparison and follow-up "
    "procedures were documented, but this paragraph states no directional result "
    "about whether the intervention increased or decreased blood pressure."
)


def _source(sid: str) -> SourceRecord:
    return SourceRecord(
        title=f"Fixture {sid}",
        url=f"https://example.org/{sid}",
        snippet="",
        source_type=SourceType.PAPER,
        connector="fixture",
        read_level="full_text",
        full_text_chars=50000,
        peer_reviewed=True,
        quality_score=0.90,
        relevance_score=0.95,
        source_id=sid,
    )


def _pack(passages: list[tuple[str, str, str]]) -> EvidencePack:
    source_ids = []
    for sid, _text, _locator in passages:
        if sid not in source_ids:
            source_ids.append(sid)
    pack = EvidencePack(sources=[_source(sid) for sid in source_ids])
    pack.passages = [
        Passage(source_id=sid, text=text, locator=locator)
        for sid, text, locator in passages
    ]
    return pack


def test_distant_opposing_paragraph_cannot_bleed_into_selected_claim_span():
    """An opposite paragraph elsewhere in one source must not override C's span."""
    pack = _pack([
        ("S1", SUPPORT_SPAN, "p.2 ¶1"),
        ("S1", DISTANT_OPPOSE, "p.9 ¶4"),
    ])
    checked = CV.verify_claim(LINE_S1, pack, claim_id="CL001", critical=True)

    assert checked.status("C") == CV.PASS
    assert checked.canonical_span["locator"] == "p.2 ¶1"
    assert checked.contradicted is False
    assert checked.contradiction_span == {}
    assert checked.result == CV.CLAIM_SUPPORTED
    assert checked.supporting_source_id == "S1"


def test_exact_opposing_span_marks_contradiction_with_source_and_locator():
    pack = _pack([("S1", EXACT_OPPOSE, "p.7 ¶2")])
    checked = CV.verify_claim(LINE_S1, pack, claim_id="CL001", critical=True)

    assert checked.contradicted is True
    assert checked.result == CV.CLAIM_CONTRADICTED
    assert checked.contradiction_span["source_id"] == "S1"
    assert checked.contradiction_span["locator"] == "p.7 ¶2"
    assert "no significant" in checked.contradiction_span["passage"].lower()
    assert checked.contradiction_span["claim_stance"] == "SUPPORT"
    assert checked.contradiction_span["source_stance"] == "OPPOSE"
    assert checked.supporting_source_id == ""


def test_mutating_exact_opposing_span_removes_contradiction():
    bad = CV.verify_claim(
        LINE_S1,
        _pack([("S1", EXACT_OPPOSE, "p.7 ¶2")]),
        claim_id="CL001",
        critical=True,
    )
    neutral = CV.verify_claim(
        LINE_S1,
        _pack([("S1", NEUTRAL_MUTATION, "p.7 ¶2")]),
        claim_id="CL001",
        critical=True,
    )

    assert bad.contradicted is True
    assert bad.contradiction_span
    assert neutral.contradicted is False
    assert neutral.contradiction_span == {}


def test_contradicted_strong_claim_cannot_count_as_verified_achievement_or_support():
    pack = _pack([
        ("S1", SUPPORT_SPAN, "p.2 ¶1"),
        ("S2", EXACT_OPPOSE, "p.7 ¶2"),
    ])
    answer = (
        "## Seedha jawab\n"
        f"- [ESTABLISHED FACT] {CLAIM_TEXT} [S1][S2]\n"
    )
    report = CV.verify_answer(answer, pack)

    assert report.total == 1
    claim = report.claims[0]
    assert claim.contradicted is True
    # Raw per-source A-E evidence remains auditable, but contradiction blocks
    # accepted support, strong-label success and release achievement.
    assert any(row["passes_ae"] for row in claim.source_checks)
    assert report.strong_claims_passed == 0
    assert report.strong_claims_failed == 1
    assert report.critical_same_source_ae_passed == 0
    assert report.claim_verification_achievement is False
    assert report.supporting_source_ids(critical_only=True) == []
    assert claim.supporting_source_id == ""

    as_dict = report.to_dict()
    assert as_dict["critical_contradicted_claims"] == 1
    assert as_dict["critical_contradiction_spans_complete"] is True
    row = as_dict["critical_claim_spans"][0]
    assert row["contradiction_span"]["source_id"] == "S2"
    assert row["contradiction_span"]["locator"] == "p.7 ¶2"

    ctx = quality_context(pack=pack, answer_text=answer, verification=report)
    assert ctx["critical_contradicted_claims"] == 1
    assert ctx["critical_contradiction_spans_complete"] is True
    assert ctx["critical_claim_evidence_spans"][0]["contradiction_span"]["locator"] == "p.7 ¶2"


def test_final_gate_requires_exact_span_for_explicit_critical_contradiction():
    state = FQ._Evaluation()
    spec = FQ.QualityContract()
    FQ.FinalQualityGate._check_claims(
        state,
        "## Seedha jawab\nContradicted critical claim.",
        {"fabricated_citations": 0},
        {"a_e_failed": 1, "entailment_blocked": 0},
        {
            "unsupported_critical_claims": 1,
            "critical_no_source_claims": 0,
            "access_depth_mismatches": 0,
            "critical_claim_spans_complete": True,
            "critical_claim_evidence_spans": [{
                "claim_id": "CL001",
                "result": CV.CLAIM_CONTRADICTED,
                "canonical_span": {"source_id": "S1", "locator": "p.2 ¶1"},
                "contradiction_span": {},
            }],
            "critical_claims": 1,
            "critical_claims_same_source_ae_passed": 0,
            "claim_verification_achievement": False,
            "critical_contradicted_claims": 1,
            "critical_contradiction_spans_complete": False,
        },
        spec,
    )

    codes = {issue.code for issue in state.issues}
    assert state.checks["critical_contradictions_have_exact_spans"] is False
    assert "CONTRADICTION_SPAN_MISSING" in codes
