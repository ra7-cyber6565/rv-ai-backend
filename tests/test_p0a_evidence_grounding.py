"""P0-A regression: evidence-first critical claims must be same-source and non-vacuous."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import claim_verification as CV
from research_engine import final_quality_gate as FQ
from research_engine.models import EvidencePack, Passage, SourceRecord, SourceType
from research_engine.quality_producers import quality_context


CLAIM = (
    "Lanthanum hydride LaH10 shows a superconducting transition temperature "
    "of 250 K at a pressure of 170 GPa"
)
SUPPORT = (
    "Electrical resistance measurements reproducibly show that lanthanum hydride "
    "LaH10 has a superconducting transition temperature of 250 K at 170 GPa. "
    "Magnetic susceptibility measurements independently track the same transition. "
)
UNRELATED = (
    "A botanical field survey catalogued alpine moss species, soil moisture, leaf "
    "shape, flowering time, and seasonal rainfall across mountain transects. "
)


def _source(
    sid: str,
    *,
    text: str = "",
    relevance: float = 0.9,
    quality: float = 0.8,
    read_level: str = "full_text",
) -> SourceRecord:
    return SourceRecord(
        title=f"Fixture {sid}",
        url=f"https://example.org/{sid}",
        snippet=text,
        source_type=SourceType.PAPER,
        connector="fixture",
        read_level=read_level,
        full_text_chars=40000 if read_level == "full_text" else 0,
        peer_reviewed=True,
        quality_score=quality,
        relevance_score=relevance,
        source_id=sid,
    )


def test_cross_source_ae_mixing_cannot_create_genuine_support():
    # A/B/C/D/E can each look good at the aggregate level, but no ONE source
    # satisfies all five. This is the exact false-positive shape P0-A closes.
    s1 = _source("S1", text=UNRELATED * 3, relevance=0.95, quality=0.10,
                 read_level="snippet")          # B only
    s2 = _source("S2", text=SUPPORT * 3, relevance=0.10, quality=0.10,
                 read_level="snippet")          # C only
    s3 = _source("S3", text=UNRELATED * 3, relevance=0.10, quality=0.10,
                 read_level="full_text")        # D only
    s4 = _source("S4", text=UNRELATED * 3, relevance=0.10, quality=0.95,
                 read_level="snippet")          # E only
    pack = EvidencePack(sources=[s1, s2, s3, s4])
    line = f"[ESTABLISHED FACT] {CLAIM} [S1][S2][S3][S4]"
    records = [s1, s2, s3, s4]

    assert CV.check_a(["S1", "S2", "S3", "S4"], records).status == CV.PASS
    assert CV.check_b(records).status == CV.PASS
    assert CV.check_c(line, records, pack)[0].status == CV.PASS
    assert CV.check_d(records).status == CV.PASS
    assert CV.check_e(records).status == CV.PASS

    checked = CV.verify_claim(line, pack, claim_id="CL001", critical=True)
    assert checked.passes_ae is False
    assert checked.verdict != CV.GENUINE_SUPPORT
    assert checked.supporting_source_id == ""
    assert checked.source_checks
    assert all(path["passes_ae"] is False for path in checked.source_checks)


def _passage_pack(text: str) -> EvidencePack:
    source = _source("S9", text="", relevance=0.92, quality=0.88,
                     read_level="full_text")
    pack = EvidencePack(sources=[source])
    pack.passages = [Passage(source_id="S9", text=text * 3, locator="p.42 ¶3")]
    return pack


def test_c_uses_recorded_canonical_span_and_mutation_breaks_support():
    good_pack = _passage_pack(SUPPORT)
    line = f"[ESTABLISHED FACT] {CLAIM} [S9]"
    good = CV.verify_claim(line, good_pack, claim_id="CL001", critical=True)

    assert good.passes_ae is True
    assert good.supporting_source_id == "S9"
    assert good.canonical_span["source_id"] == "S9"
    assert good.canonical_span["locator"] == "p.42 ¶3"
    assert SUPPORT[:60] in good.canonical_span["passage"]

    # Same source metadata/depth/quality, but the exact evidence passage is
    # mutated away. C must no longer borrow support from source-wide metadata.
    bad_pack = _passage_pack(UNRELATED)
    bad = CV.verify_claim(line, bad_pack, claim_id="CL001", critical=True)
    assert bad.status("C") == CV.FAIL
    assert bad.passes_ae is False
    assert bad.supporting_source_id == ""


def test_fulltext_source_badge_cannot_promote_its_display_snippet_to_ae_proof():
    """D belongs to the canonical span, not the later-mutated SourceRecord."""
    source = _source("S9", text=SUPPORT * 3, relevance=0.92, quality=0.88,
                     read_level="full_text")
    source.locator = "p.42 ¶3"
    # No exact Passage exists: only the broad display snippet can drive C.
    pack = EvidencePack(sources=[source], passages=[])
    line = f"[ESTABLISHED FACT] {CLAIM} [S9]"
    checked = CV.verify_claim(line, pack, claim_id="CL001", critical=True)

    assert checked.status("C") == CV.PASS, checked.check("C").detail
    assert checked.canonical_span["span_kind"] == "snippet"
    assert checked.status("D") == CV.FAIL, checked.check("D").detail
    assert checked.passes_ae is False
    assert checked.supporting_source_id == ""


def test_capture_time_snippet_passage_cannot_borrow_later_fulltext_depth():
    source = _source("S9", text="", relevance=0.92, quality=0.88,
                     read_level="full_text")
    pack = EvidencePack(sources=[source], passages=[Passage(
        source_id="S9", text=SUPPORT * 3, locator="search result ¶1",
        provenance="retrieval_excerpt", read_level_at_capture="snippet",
    )])
    line = f"[ESTABLISHED FACT] {CLAIM} [S9]"
    checked = CV.verify_claim(line, pack, claim_id="CL001", critical=True)

    assert checked.status("C") == CV.PASS, checked.check("C").detail
    assert checked.status("D") == CV.FAIL, checked.check("D").detail
    assert checked.passes_ae is False


def test_quality_context_carries_claim_id_locator_and_non_vacuous_achievement():
    pack = _passage_pack(SUPPORT)
    answer = (
        "## Seedha jawab\n"
        f"- [ESTABLISHED FACT] {CLAIM}\n"
        "  reproducibly measured in the cited experiment [S9]\n"
    )
    report = CV.verify_answer(answer, pack)
    assert report.total == 1
    assert report.claims[0].claim_id == "CL001"
    assert report.claims[0].passes_ae is True

    ctx = quality_context(pack=pack, answer_text=answer, verification=report)
    assert ctx["critical_claims"] == 1
    assert ctx["critical_claims_same_source_ae_passed"] == 1
    assert ctx["claim_verification_achievement"] is True
    row = ctx["critical_claim_evidence_spans"][0]
    assert row["claim_id"] == "CL001"
    assert row["supporting_source_id"] == "S9"
    assert row["canonical_span"]["locator"] == "p.42 ¶3"
    assert row["same_source_ae_passed"] is True


def test_zero_over_zero_is_safety_pass_but_not_verification_achievement():
    empty = CV.VerificationReport().to_dict()
    # Backwards-compatible safety meaning: no unsafe strong label escaped.
    assert empty["gate_passed"] is True
    assert empty["gate_applicable"] is False
    # New achievement meaning: zero verified critical claims is not success.
    assert empty["critical_claims"] == 0
    assert empty["critical_claims_same_source_ae_passed"] == 0
    assert empty["claim_verification_achievement"] is False

    ctx = quality_context(pack=EvidencePack(), answer_text="", verification=CV.VerificationReport())
    assert ctx["critical_claims"] == 0
    assert ctx["critical_claims_same_source_ae_passed"] == 0
    assert ctx["claim_verification_achievement"] is False


def test_final_gate_blocks_explicit_zero_over_zero_achievement():
    state = FQ._Evaluation()
    spec = FQ.QualityContract()
    FQ.FinalQualityGate._check_claims(
        state,
        "## Seedha jawab\nHonest partial answer.",
        {"fabricated_citations": 0},
        {"a_e_failed": 0, "entailment_blocked": 0},
        {
            "unsupported_critical_claims": 0,
            "critical_no_source_claims": 0,
            "access_depth_mismatches": 0,
            "critical_claim_spans_complete": None,
            "critical_claim_evidence_spans": [],
            "critical_claims": 0,
            "critical_claims_same_source_ae_passed": 0,
            "claim_verification_achievement": False,
        },
        spec,
    )
    codes = {issue.code for issue in state.issues}
    assert state.checks["verified_critical_claim_achievement"] is False
    assert "CRITICAL_CLAIM_ACHIEVEMENT_MISSING" in codes


def test_pr16_bounded_multiline_claim_keeps_citation_and_same_source_support():
    pack = _passage_pack(SUPPORT)
    answer = (
        "## Seedha jawab\n"
        "- [ESTABLISHED FACT] Lanthanum hydride LaH10 shows a superconducting\n"
        "  transition temperature of 250 K at a pressure of 170 GPa [S9]\n"
        "\n## Unknowns\nMore work remains.\n"
    )
    report = CV.verify_answer(answer, pack)
    assert report.total == 1
    assert report.claims[0].cited_ids == ["S9"]
    assert report.claims[0].passes_ae is True
    assert report.claims[0].canonical_span["locator"] == "p.42 ¶3"
