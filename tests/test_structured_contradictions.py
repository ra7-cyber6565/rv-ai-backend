"""§11 — takraav ka structured contract: nakli contradiction report nahi hoti.

Live dark-matter run mein "contradictions" wahan dikhaye gaye the jahan sirf
publication year alag tha (S11 vs S12), aur do bilkul alag topic ke papers ko
aamne-saamne khada kar diya gaya tha. Ye file un galtiyon ko regression bana
deti hai:

  * sirf saal ka farq → YEAR_ONLY par reject, report mein nahi;
  * ek taraf pakka daawa + doosri taraf "ho sakta hai" → GENERIC_CONFIDENCE;
  * topic hi common nahi → NO_SHARED_PROPOSITION;
  * adhoora schema kabhi takraav nahi ban sakta;
  * reject hui jodi phenki nahi jaati — audit ke liye bachti hai;
  * asli takraav ke saath proposition, dono claims aur evidence spans jaate hain;
  * saal ka farq sirf context note hai — "naya isliye sahi" kabhi nahi;
  * method ka farq compare NAHI ho paaya, to report mein line gayab nahi hoti —
    wajah likhi jaati hai ("dono ki study design ka record nahi mila").

Poora offline aur deterministic: koi network, koi model, koi provider call.

Chalane ka tareeka (repo root = backend/):
    PYTHONPATH=. python3 tests/test_structured_contradictions.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.consensus_gate import CONSENSUS_UNAVAILABLE   # noqa: E402
from research_engine.contradiction import (CONTRA_GENERIC_CONFIDENCE,  # noqa: E402
                                           CONTRA_NO_OPPOSITE,
                                           CONTRA_NO_PROPOSITION,
                                           CONTRA_NOT_EVALUATED,
                                           CONTRA_REJECT_CODES,
                                           CONTRA_REJECT_WHY,
                                           CONTRA_TOPIC_MISMATCH,
                                           CONTRA_WEAK_QUESTION_LINK,
                                           CONTRA_YEAR_ONLY,
                                           METHOD_CMP_COMPARED,
                                           METHOD_CMP_SAME_LEVEL,
                                           METHOD_CMP_UNKNOWN, Contradiction,
                                           ContradictionEngine)
from research_engine.models import EvidencePack, SourceRecord      # noqa: E402

_Q = "kya vitamin D supplementation fracture incidence kam karta hai"

_SUPPORT = ("In this cohort the intervention was effective and significantly "
            "improved bone density.")
_OPPOSE = ("The trial found no significant effect on fracture incidence and no "
           "association with bone density.")
_HEDGED = ("The observed bone density pattern may reflect other factors; "
           "further research on fracture incidence is needed.")


def _src(source_id: str, snippet: str, *, title: str = None, year: int = None,
         domain: str = None, peer: bool = True, locator: str = "") -> SourceRecord:
    return SourceRecord(
        title=title or "Vitamin D supplementation and fracture incidence",
        url="https://%s/p/%s" % (domain or ("host-%s.org" % source_id.lower()), source_id),
        snippet=snippet, year=year, peer_reviewed=peer, locator=locator,
        source_id=source_id, read_level="abstract",
    )


def _pack(*sources: SourceRecord, question: str = _Q) -> EvidencePack:
    return EvidencePack(question=question, sources=list(sources))


def _detect(*sources: SourceRecord, question: str = _Q):
    engine = ContradictionEngine()
    found = engine.detect(_pack(*sources, question=question))
    return engine, found


# --- reject codes: ginne-layak, free-text nahi -------------------------------

def test_five_reject_codes_each_carry_their_own_reason():
    # #114 ne do naye code jode (scope aur kamzor question-link), isliye 5 se 7.
    # Ginti badhi hai — koi purana code hataya nahi gaya.
    assert len(CONTRA_REJECT_CODES) == 7
    assert len(set(CONTRA_REJECT_CODES)) == 7
    for code in CONTRA_REJECT_CODES:
        assert len(CONTRA_REJECT_WHY[code].strip()) > 30, code
    assert len({v.strip() for v in CONTRA_REJECT_WHY.values()}) == 7
    for old in (CONTRA_YEAR_ONLY, CONTRA_TOPIC_MISMATCH, CONTRA_NO_OPPOSITE,
                CONTRA_GENERIC_CONFIDENCE, CONTRA_NO_PROPOSITION):
        assert old in CONTRA_REJECT_CODES, old
    assert CONTRA_NOT_EVALUATED in CONTRA_REJECT_CODES
    assert CONTRA_WEAK_QUESTION_LINK in CONTRA_REJECT_CODES


def test_year_only_reason_denies_that_newer_means_correct():
    why = CONTRA_REJECT_WHY[CONTRA_YEAR_ONLY]
    assert "sirf date se kisi evidence ka weight tay nahi" in why
    assert "takraav nahi hai" in why


# --- §3 ki asli galti: saal ka farq takraav ban gaya tha ---------------------

def test_year_gap_alone_is_rejected_and_never_reported():
    engine, found = _detect(_src("S1", _SUPPORT, year=2009),
                            _src("S2", _HEDGED, year=2021))
    assert found == []
    assert len(engine.last_rejected) == 1
    rejected = engine.last_rejected[0]
    assert rejected.kind == "RECENCY"
    assert rejected.reject_code == CONTRA_YEAR_ONLY
    assert rejected.reject_reason == CONTRA_REJECT_WHY[CONTRA_YEAR_ONLY]
    assert rejected.valid is False


def test_confidence_difference_without_a_year_gap_is_its_own_reject_code():
    engine, found = _detect(_src("S1", _SUPPORT, year=2019),
                            _src("S2", _HEDGED, year=2020))
    assert found == []
    assert [c.reject_code for c in engine.last_rejected] == [CONTRA_GENERIC_CONFIDENCE]
    assert engine.last_rejected[0].opposing_direction is False
    assert "koi ulta nateeja nahi" in engine.last_rejected[0].reject_reason


def test_hedged_pair_is_recorded_even_when_the_years_are_missing():
    engine, found = _detect(_src("S1", _SUPPORT), _src("S2", _HEDGED))
    assert found == []
    assert engine.last_rejected, "jodi chup-chaap gayab nahi honi chahiye"


def test_two_papers_on_different_questions_do_not_contradict_each_other():
    off_topic = _src("S2", "Calibration of the telescope pipeline did not "
                           "improve throughput; no significant effect was seen.",
                     title="Telescope pipeline calibration residuals",
                     domain="calibration.example.org")
    engine, found = _detect(_src("S1", _SUPPORT), off_topic)
    assert found == []
    assert [c.reject_code for c in engine.last_rejected] == [CONTRA_NO_PROPOSITION]
    assert engine.last_rejected[0].normalized_proposition == ""


def test_two_copies_of_the_same_work_are_not_a_conflict():
    a = _src("S1", _SUPPORT, domain="mirror.example.org")
    b = _src("S2", _OPPOSE, domain="mirror.example.org")
    engine, found = _detect(a, b)
    assert a.independence_key == b.independence_key
    assert found == []
    assert engine.last_rejected == []


# --- asli takraav: poora schema, dono claims, dono spans ---------------------

def test_a_real_opposing_pair_is_reported_with_the_full_schema():
    engine, found = _detect(_src("S1", _SUPPORT, year=2018),
                            _src("S2", _OPPOSE, year=2019))
    assert len(found) == 1
    c = found[0]
    assert c.kind == "STANCE"
    assert c.valid is True and c.reject_code == ""
    assert c.schema_complete() is True
    assert c.opposing_direction is True
    assert c.normalized_proposition
    assert "effective" in c.source_a_claim.lower()
    assert "no significant effect" in c.source_b_claim.lower()
    assert sorted(c.source_ids) == ["S1", "S2"]
    assert engine.last_rejected == []


def test_evidence_spans_name_both_sources_and_stay_honest_about_the_locator():
    _, found = _detect(_src("S1", _SUPPORT, locator="Page 4"),
                       _src("S2", _OPPOSE))
    spans = found[0].evidence_spans
    assert [sp["source_id"] for sp in spans] == ["S1", "S2"]
    assert spans[0]["ref"] == "S1 Page 4"
    assert spans[1]["locator"] == "abstract/snippet"
    assert all(sp["passage"] for sp in spans)


def test_dict_form_carries_the_spans_the_refs_and_the_rule_based_warning():
    _, found = _detect(_src("S1", _SUPPORT, locator="Page 4"),
                       _src("S2", _OPPOSE))
    data = found[0].to_dict()
    assert data["evidence_span_refs"] == ["S1 Page 4", "S2 abstract/snippet"]
    assert len(data["evidence_spans"]) == 2
    assert data["schema_complete"] is True
    assert data["opposing_direction"] is True
    assert "manually verify karna zaroori hai" in data["note"]


def test_wording_that_barely_overlaps_is_flagged_as_a_scope_caveat():
    thin = _src("S2", "Cholecalciferol dosing showed no significant effect.",
                title="Cholecalciferol dosing and bone outcomes",
                domain="dosing.example.org")
    _, found = _detect(_src("S1", _SUPPORT), thin,
                       question="vitamin D cholecalciferol supplementation bone outcomes")
    assert len(found) == 1
    assert found[0].severity in ("LOW", "MEDIUM")
    assert "scope compare karo" in found[0].detail


def test_a_pair_with_no_shared_words_cannot_produce_a_proposition():
    nothing_shared = _src("S2", "Cholecalciferol dosing showed no significant effect.",
                          title="Cholecalciferol dosing outcomes",
                          domain="dosing.example.org")
    engine, found = _detect(_src("S1", _SUPPORT), nothing_shared,
                            question="vitamin D cholecalciferol supplementation outcomes")
    assert found == []
    assert [c.reject_code for c in engine.last_rejected] == [CONTRA_NO_PROPOSITION]


def test_both_peer_reviewed_and_same_wording_makes_it_high_severity():
    _, found = _detect(_src("S1", _SUPPORT), _src("S2", _OPPOSE))
    assert found[0].severity == "HIGH"


def test_method_difference_is_left_empty_instead_of_claiming_same_method():
    _, found = _detect(_src("S1", _SUPPORT), _src("S2", _OPPOSE))
    assert found[0].method_difference == ""
    assert "method same" not in found[0].to_dict()["detail"].lower()


def test_empty_method_difference_still_says_why_it_could_not_be_compared():
    """
    Khaali `method_difference` par report se line gayab ho jaati thi — padhne
    wale ko lagta tha ki method dekha gaya aur farq nahi mila. Ab wajah alag
    field mein jaati hai.
    """
    _, found = _detect(_src("S1", _SUPPORT), _src("S2", _OPPOSE))
    data = found[0].to_dict()
    assert data["method_difference"] == ""
    assert data["method_comparison_status"] == METHOD_CMP_UNKNOWN
    why = data["method_comparison_why"]
    assert "record nahi mila" in why
    # Ulta: line saaf mana karti hai ki "method same tha" kaha ja sakta hai.
    assert "jhooth" in why.lower()


def test_same_level_designs_are_not_reported_as_unknown():
    a = _src("S1", _SUPPORT)
    b = _src("S2", _OPPOSE)
    a.methodology = "cohort"
    b.methodology = "case_control"          # dono ka rank 3 — ek hi level
    _, found = _detect(a, b)
    data = found[0].to_dict()
    assert data["method_difference"] == ""
    assert data["method_comparison_status"] == METHOD_CMP_SAME_LEVEL
    assert "ek hi level" in data["method_comparison_why"]


def test_a_real_design_gap_is_reported_as_compared():
    a = _src("S1", _SUPPORT)
    b = _src("S2", _OPPOSE)
    a.methodology = "meta_analysis"
    b.methodology = "case_report"
    _, found = _detect(a, b)
    data = found[0].to_dict()
    assert data["method_comparison_status"] == METHOD_CMP_COMPARED
    assert "stronger design" in data["method_difference"]
    assert data["method_comparison_why"] == data["method_difference"]


def test_numeric_conflict_also_carries_a_method_status():
    _, found = _detect(_src("S1", _NUM_A), _src("S2", _NUM_B))
    data = found[0].to_dict()
    assert found[0].kind == "NUMERIC"
    assert data["method_comparison_status"] in (METHOD_CMP_UNKNOWN,
                                                METHOD_CMP_SAME_LEVEL,
                                                METHOD_CMP_COMPARED)
    assert data["method_comparison_why"].strip() != ""


def test_report_prints_a_method_line_even_when_nothing_could_be_compared():
    from research_engine.synthesizer_claude import FinalSynthesizer
    _, found = _detect(_src("S1", _SUPPORT), _src("S2", _OPPOSE))
    text = FinalSynthesizer()._contradiction_section([c.to_dict() for c in found])
    assert "_Method ka farq:_" in text
    assert "record nahi mila" in text


# --- numbers ka takraav ------------------------------------------------------

_NUM_A = "Across the cohort, fracture incidence fell in 68% of the bone density subgroup."
_NUM_B = "Across the same cohort, fracture incidence fell in 12% of the bone density subgroup."


def test_a_wide_percentage_gap_on_one_topic_is_a_numeric_conflict():
    _, found = _detect(_src("S1", _NUM_A), _src("S2", _NUM_B))
    assert len(found) == 1
    assert found[0].kind == "NUMERIC"
    assert found[0].schema_complete() is True
    assert "definitions check karo" in found[0].detail


def test_a_small_percentage_gap_is_not_turned_into_a_conflict():
    close_b = _NUM_B.replace("12%", "63%")
    _, found = _detect(_src("S1", _NUM_A), _src("S2", close_b))
    assert found == []


def test_percentages_from_unrelated_documents_are_never_compared():
    other = _src("S2", "Only 12% of the museum pottery fragments were preserved.",
                 title="Museum pottery preservation survey",
                 domain="pottery.example.org")
    _, found = _detect(_src("S1", _NUM_A), other)
    assert found == []


# --- adhoora schema kabhi takraav nahi ---------------------------------------

def _full() -> dict:
    return {"kind": "STANCE", "summary": "s",
            "source_ids": ["S1", "S2"],
            "normalized_proposition": "Takraav is baat par hai",
            "source_a_claim": "S1 kehta hai haan",
            "source_b_claim": "S2 kehta hai na",
            "opposing_direction": True}


def test_a_complete_record_is_the_only_shape_that_counts_as_a_contradiction():
    assert Contradiction(**_full()).schema_complete() is True


def test_every_single_missing_field_breaks_schema_completeness():
    holes = {
        "normalized_proposition": "",
        "source_a_claim": "",
        "source_b_claim": "",
        "opposing_direction": None,
        "source_ids": ["S1"],
    }
    for field_name, broken in holes.items():
        payload = _full()
        payload[field_name] = broken
        assert Contradiction(**payload).schema_complete() is False, field_name


def test_direction_that_was_never_checked_is_not_treated_as_opposing():
    payload = _full()
    payload["opposing_direction"] = False
    assert Contradiction(**payload).schema_complete() is False
    payload["opposing_direction"] = None
    assert Contradiction(**payload).schema_complete() is False


def test_validate_names_the_exact_reason_for_each_broken_record():
    engine = ContradictionEngine()
    cases = [
        (CONTRA_YEAR_ONLY, dict(_full(), kind="RECENCY")),
        (CONTRA_GENERIC_CONFIDENCE, dict(_full(), kind="CONFIDENCE")),
        (CONTRA_NO_PROPOSITION, dict(_full(), normalized_proposition="")),
        (CONTRA_NO_OPPOSITE, dict(_full(), opposing_direction=False)),
        (CONTRA_TOPIC_MISMATCH, dict(_full(), source_b_claim="")),
    ]
    for code, payload in cases:
        out = engine._validate(Contradiction(**payload))
        assert out.valid is False, code
        assert out.reject_code == code, code
        assert out.reject_reason == CONTRA_REJECT_WHY[code], code


# --- reject hui jodi phenki nahi jaati --------------------------------------

def test_rejection_report_counts_every_code_and_keeps_examples():
    engine, _ = _detect(_src("S1", _SUPPORT, year=2009),
                        _src("S2", _HEDGED, year=2021))
    report = engine.rejection_report()
    assert report["rejected"] == 1
    assert report["counts"][CONTRA_YEAR_ONLY] == 1
    assert set(report["counts"]) == set(CONTRA_REJECT_CODES)
    assert report["why"] == CONTRA_REJECT_WHY
    assert len(report["examples"]) == 1
    assert report["examples"][0]["reject_code"] == CONTRA_YEAR_ONLY


def test_rejection_report_shows_at_most_five_examples():
    engine = ContradictionEngine()
    engine.last_rejected = [engine._validate(Contradiction(**dict(_full(), kind="RECENCY")))
                            for _ in range(9)]
    report = engine.rejection_report()
    assert report["rejected"] == 9
    assert len(report["examples"]) == 5


def test_a_fresh_run_does_not_inherit_the_previous_run_s_rejections():
    engine = ContradictionEngine()
    engine.detect(_pack(_src("S1", _SUPPORT, year=2009),
                        _src("S2", _HEDGED, year=2021)))
    assert engine.last_rejected
    engine.detect(_pack(_src("S1", _SUPPORT), _src("S2", _OPPOSE)))
    assert engine.last_rejected == []


def test_a_pack_too_small_to_compare_reports_nothing_and_does_not_crash():
    engine = ContradictionEngine()
    assert engine.detect(_pack(_src("S1", _SUPPORT))) == []
    assert engine.detect(_pack()) == []
    assert engine.last_rejected == []


# --- saal ka farq sirf context ----------------------------------------------

def test_year_gap_is_written_as_context_not_as_a_weight_rule():
    engine = ContradictionEngine()
    note = engine._temporal_comparison(_src("S1", _SUPPORT, year=2005),
                                       _src("S2", _OPPOSE, year=2020))
    assert "ye sirf context hai" in note
    assert "zyada weight nahi milta" in note
    for lie in ("preference", "newer evidence ko", "naya isliye sahi"):
        assert lie not in note.lower()


def test_a_small_year_gap_produces_no_context_note_at_all():
    engine = ContradictionEngine()
    assert engine._temporal_comparison(_src("S1", _SUPPORT, year=2019),
                                       _src("S2", _OPPOSE, year=2020)) is None
    assert engine._temporal_comparison(_src("S1", _SUPPORT),
                                       _src("S2", _OPPOSE, year=2020)) is None


def test_the_year_note_travels_as_context_never_as_the_reason():
    _, found = _detect(_src("S1", _SUPPORT, year=2004),
                       _src("S2", _OPPOSE, year=2021))
    assert found[0].context_notes
    assert "sirf context hai" in found[0].context_notes[0]
    assert found[0].kind == "STANCE"


# --- stance: "not effective" kabhi "effective" nahi --------------------------

def test_a_negated_claim_is_never_read_as_support():
    engine = ContradictionEngine()
    assert engine.stance("The drug was not effective in this trial")[0] == "OPPOSE"
    assert engine.stance("No measurable improvement in throughput")[0] == "OPPOSE"


def test_a_null_result_is_not_softened_into_mixed_by_a_topic_word():
    engine = ContradictionEngine()
    stance, cues = engine.stance("Minimum wage increases showed no significant "
                                 "effect on employment")
    assert stance == "OPPOSE"
    assert cues


def test_text_with_no_claim_words_stays_neutral_rather_than_guessing():
    engine = ContradictionEngine()
    assert engine.stance("Dataset description and instrument list")[0] == "NEUTRAL"
    assert engine.stance("")[0] == "NEUTRAL"


# --- consensus: chali hi nahi vs chali aur kuch nahi mila --------------------

def test_analysis_never_run_is_recorded_differently_from_run_and_empty():
    engine = ContradictionEngine()
    pack = _pack(_src("S1", _SUPPORT), _src("S2", _OPPOSE))
    never = engine.consensus_report(pack, contradictions=None)
    ran = engine.consensus_report(pack, contradictions=[])
    assert never["contradiction_analysis_done"] is False
    assert ran["contradiction_analysis_done"] is True


def test_a_failed_gate_prints_the_fixed_sentence_and_keeps_the_raw_level():
    engine = ContradictionEngine()
    report = engine.consensus_report(_pack(_src("S1", _SUPPORT), _src("S2", _OPPOSE)),
                                     contradictions=[])
    assert report["gate_passed"] is False
    assert report["level"] == CONSENSUS_UNAVAILABLE
    assert report["level_if_gate_passed"]
    assert report["unmet_conditions"]


def main() -> int:
    failed = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        try:
            func()
        except AssertionError as exc:                  # noqa: PERF203
            failed += 1
            print("  [FAIL] %s -> %s" % (name, exc))
        except Exception as exc:                       # noqa: BLE001
            failed += 1
            print("  [ERROR] %s -> %s: %s" % (name, type(exc).__name__, exc))
        else:
            print("  [PASS] %s" % name)
    print("\n%s — %d failed" % ("FAIL" if failed else "ok", failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
