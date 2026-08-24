"""Contradiction must be claim-span grounded and accounting-safe."""
from __future__ import annotations

from research_engine import claim_verification as CV
from research_engine import final_quality_gate as FQ
from research_engine.contradiction import ContradictionEngine
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


def _source(source_id: str) -> SourceRecord:
    return SourceRecord(
        title=f"Fixture {source_id}",
        url=f"https://example.org/{source_id}",
        snippet="",
        source_type=SourceType.PAPER,
        connector="fixture",
        read_level="full_text",
        full_text_chars=50000,
        peer_reviewed=True,
        quality_score=0.90,
        relevance_score=0.95,
        source_id=source_id,
    )


def _pack(passages: list[tuple[str, str, str]]) -> EvidencePack:
    source_ids: list[str] = []
    for source_id, _text, _locator in passages:
        if source_id not in source_ids:
            source_ids.append(source_id)
    return EvidencePack(
        sources=[_source(source_id) for source_id in source_ids],
        passages=[Passage(source_id=source_id, text=text, locator=locator)
                  for source_id, text, locator in passages],
    )


def test_inconsistent_with_is_opposition_not_false_consistent_support():
    stance, cues = ContradictionEngine().stance(EXACT_OPPOSE)
    assert stance == "OPPOSE"
    assert "inconsistent with" in cues
    assert "consistent with" not in cues


def test_distant_opposing_paragraph_cannot_bleed_into_selected_claim_span():
    checked = CV.verify_claim(
        LINE_S1,
        _pack([
            ("S1", SUPPORT_SPAN, "p.2 ¶1"),
            ("S1", DISTANT_OPPOSE, "p.9 ¶4"),
        ]),
        claim_id="CL001",
        critical=True,
    )
    assert checked.status("C") == CV.PASS
    assert checked.canonical_span["locator"] == "p.2 ¶1"
    assert checked.contradicted is False
    assert checked.contradiction_span == {}
    assert checked.result == CV.CLAIM_SUPPORTED
    assert checked.supporting_source_id == "S1"


def test_exact_opposing_span_marks_contradiction_with_source_and_locator():
    checked = CV.verify_claim(
        LINE_S1,
        _pack([("S1", EXACT_OPPOSE, "p.7 ¶2")]),
        claim_id="CL001",
        critical=True,
    )
    assert checked.contradicted is True
    assert checked.result == CV.CLAIM_CONTRADICTED
    assert checked.contradiction_span["source_id"] == "S1"
    assert checked.contradiction_span["locator"] == "p.7 ¶2"
    assert "no significant" in checked.contradiction_span["passage"].lower()
    assert checked.contradiction_span["claim_stance"] == "SUPPORT"
    assert checked.contradiction_span["source_stance"] == "OPPOSE"
    assert checked.supporting_source_id == ""


def test_mutating_exact_opposing_span_removes_contradiction():
    opposite = CV.verify_claim(
        LINE_S1, _pack([("S1", EXACT_OPPOSE, "p.7 ¶2")]),
        claim_id="CL001", critical=True)
    neutral = CV.verify_claim(
        LINE_S1, _pack([("S1", NEUTRAL_MUTATION, "p.7 ¶2")]),
        claim_id="CL001", critical=True)
    assert opposite.contradicted is True
    assert opposite.contradiction_span
    assert neutral.contradicted is False
    assert neutral.contradiction_span == {}


def test_contradicted_strong_claim_cannot_count_as_verified_support():
    pack = _pack([
        ("S1", SUPPORT_SPAN, "p.2 ¶1"),
        ("S2", EXACT_OPPOSE, "p.7 ¶2"),
    ])
    answer = f"## Seedha jawab\n- [ESTABLISHED FACT] {CLAIM_TEXT} [S1][S2]\n"
    report = CV.verify_answer(answer, pack)
    claim = report.claims[0]
    assert report.total == 1
    assert claim.contradicted is True
    assert any(row["passes_ae"] for row in claim.source_checks)
    assert report.strong_claims_passed == 0
    assert report.strong_claims_failed == 1
    assert report.critical_same_source_ae_passed == 0
    assert report.claim_verification_achievement is False
    assert report.supporting_source_ids(critical_only=True) == []
    assert claim.supporting_source_id == ""

    payload = report.to_dict()
    assert payload["critical_contradicted_claims"] == 1
    assert payload["critical_contradiction_spans_complete"] is True
    row = payload["critical_claim_spans"][0]
    assert row["same_source_ae_passed"] is False
    assert row["verified_support"] is False
    assert row["contradiction_span"]["source_id"] == "S2"
    assert row["contradiction_span"]["locator"] == "p.7 ¶2"

    context = quality_context(pack=pack, answer_text=answer, verification=report)
    assert context["critical_contradicted_claims"] == 1
    assert context["critical_contradiction_spans_complete"] is True


def _run_contradiction_gate(span: dict, complete: bool = True):
    state = FQ._Evaluation()
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
                "contradiction_span": span,
            }],
            "critical_claims": 1,
            "critical_claims_same_source_ae_passed": 0,
            "claim_verification_achievement": False,
            "critical_contradicted_claims": 1,
            "critical_contradiction_spans_complete": complete,
        },
        FQ.QualityContract(),
    )
    return state, {issue.code for issue in state.issues}


def test_final_gate_requires_exact_span_for_critical_contradiction():
    state, codes = _run_contradiction_gate({})
    assert state.checks["critical_contradictions_have_exact_spans"] is False
    assert "CONTRADICTION_SPAN_MISSING" in codes


def test_nonempty_but_unattributable_contradiction_span_still_fails():
    state, codes = _run_contradiction_gate({"note": "opposite"})
    assert state.checks["critical_contradictions_have_exact_spans"] is False
    assert "CONTRADICTION_SPAN_MISSING" in codes


def test_complete_exact_opposite_span_passes_contradiction_provenance_check():
    span = {
        "source_id": "S2",
        "locator": "p.7 ¶2",
        "passage": EXACT_OPPOSE,
        "claim_stance": "SUPPORT",
        "source_stance": "OPPOSE",
    }
    state, codes = _run_contradiction_gate(span)
    assert state.checks["critical_contradictions_have_exact_spans"] is True
    assert "CONTRADICTION_SPAN_MISSING" not in codes
