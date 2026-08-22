"""§7/§19 — "check nahi hua" ko kabhi "zero mila" nahi likhna.

Live dark-matter run ka sabse chupa hua jhooth yahi tha: audit mein "numeric
sanity check passed" likha tha jabki ek bhi calculation hui hi nahi thi, aur "18
sources" ko evidence ki taakat ki tarah pesh kiya gaya tha jabki cite sirf 9
hue. Dono galtiyan ek hi jagah se aati hain — producer ne `None` (check chala hi
nahi) aur `0` (chala, kuch nahi mila) ko ek bana diya.

Ye file usi contract ko regression bana deti hai:

  * pack hi na mile to HAR counter `None` rehta hai, 0 nahi;
  * retrieved / cited / unused / screened / opened / full-text alag ginti hain;
  * alag URL alag independent source nahi banata;
  * relevance chali hi nahi vs chali aur floor koi paar nahi kar paaya;
  * strong label bina [S#] wali line pakdi jaati hai (yahi 14 baar hui thi);
  * app ki hypothesis aur established fact ka mix dono taraf se pakda jaata hai;
  * FULL-TEXT VERIFIED label banned hai, aur gehrai ka overclaim pakda jaata hai;
  * number wala confidence dikhte hi calibration `False` ho jaata hai;
  * TRISTATE_FIELDS ka har naam `unknown_fields`/`checked` mein hisaab deta hai;
  * audit block `None` ko "check nahi hua" likhta hai, "0" nahi.

Poora offline aur deterministic: koi network, koi model, koi provider call.

Chalane ka tareeka (repo root = backend/):
    PYTHONPATH=. python3 tests/test_quality_context_producers.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.models import (ACCESS_ABSTRACT,               # noqa: E402
                                    ACCESS_DEPTH_ALLOWED, ACCESS_FULL,
                                    EvidencePack, SourceRecord)
from research_engine.quality_producers import (BANNED_ACCESS_LABEL,  # noqa: E402
                                               COUNTER_DEFINITIONS,
                                               DIRECT_RELEVANCE_FLOOR,
                                               DIRECT_RELEVANCE_FLOOR_STATUS,
                                               TRISTATE_FIELDS,
                                               access_depth_mismatches,
                                               cited_source_ids, context_block,
                                               hypothesis_fact_mix,
                                               hypothesis_report,
                                               independent_families,
                                               no_source_claims,
                                               numeric_confidence_claims,
                                               quality_context,
                                               relevance_gate_report,
                                               rescan_final_answer,
                                               sections_present,
                                               source_counters)
from research_engine.quality_producers import _num                  # noqa: E402


def _src(source_id: str, *, title: str = "", url: str = "", snippet: str = "abc",
         read_level: str = "abstract", relevance: float = 0.0,
         parts: dict = None, rejected: str = "", authors=None,
         methodology: str = "", pages_read: int = 0, pages_total: int = 0
         ) -> SourceRecord:
    return SourceRecord(
        title=title or ("Paper %s" % source_id),
        url=url or ("https://host-%s.org/p/%s" % (source_id.lower(), source_id)),
        snippet=snippet, read_level=read_level, relevance_score=relevance,
        relevance_parts=dict(parts or {}), rejected_reason=rejected,
        authors=list(authors or []), methodology=methodology,
        pages_read=pages_read, pages_total=pages_total, source_id=source_id,
    )


def _pack(*sources: SourceRecord, screened: int = 0,
          proposition: dict = None, reject_codes: dict = None) -> EvidencePack:
    pack = EvidencePack(question="kya dark matter halo rotation curve samjhata hai",
                        sources=list(sources), discovered_count=screened)
    if proposition is not None:
        pack.retrieval_filter["proposition"] = dict(proposition)
    if reject_codes is not None:
        pack.retrieval_filter["reject_codes"] = {"counts": dict(reject_codes)}
    return pack


# --- counters: har ginti ka apna matlab -------------------------------------

def test_every_counter_carries_its_own_written_definition():
    assert len(COUNTER_DEFINITIONS) == 11
    assert len({v.strip() for v in COUNTER_DEFINITIONS.values()}) == 11
    assert "dedup ke baad" in COUNTER_DEFINITIONS["sources_retrieved"]
    assert "alag URL alag family nahi banata" in \
        COUNTER_DEFINITIONS["independent_source_families"]
    assert "independence NAHI" in COUNTER_DEFINITIONS["distinct_urls"]


def test_the_relevance_floor_travels_with_its_provisional_status():
    out = source_counters()
    assert out["relevance_floor"] == DIRECT_RELEVANCE_FLOOR
    assert out["relevance_floor_status"] == DIRECT_RELEVANCE_FLOOR_STATUS
    assert "provisional" in out["relevance_floor_status"]


def test_no_evidence_pack_leaves_every_counter_unknown_instead_of_zero():
    out = source_counters()
    for key in COUNTER_DEFINITIONS:
        assert out[key] is None, key
    assert out["note"] == "evidence pack hi nahi mila — koi counter chala nahi"
    assert out["average_relevance"] is None
    assert out["families"] is None


def test_retrieved_count_is_never_reused_as_the_cited_count():
    out = source_counters(_pack(_src("S1"), _src("S2"), _src("S3")),
                          answer_text="Rotation curve flat rehti hai [S1].")
    assert out["sources_retrieved"] == 3
    assert out["sources_cited"] == 1
    assert out["sources_unused"] == 2
    assert out["unused_ids"] == ["S2", "S3"]
    assert out["cited_ids"] == ["S1"]


def test_a_citation_whose_source_is_not_in_the_pack_is_counted_apart():
    out = source_counters(_pack(_src("S1")),
                          answer_text="Ye baat [S1] aur [S99] dono kehte hain.")
    assert out["sources_cited"] == 1
    assert out["citations_without_source"] == 1
    assert out["citations_without_source_ids"] == ["S99"]


def test_screened_and_retrieved_are_two_different_numbers():
    out = source_counters(_pack(_src("S1"), _src("S2"), screened=18))
    assert out["sources_screened"] == 18
    assert out["sources_retrieved"] == 2


def test_screening_that_was_never_recorded_stays_unknown():
    assert source_counters(_pack(_src("S1")))["sources_screened"] is None


def test_opened_and_full_text_counts_follow_the_real_read_level():
    out = source_counters(_pack(_src("S1", read_level="metadata"),
                                _src("S2", read_level="abstract"),
                                _src("S3", read_level="full_text")))
    assert out["sources_retrieved"] == 3
    assert out["sources_opened"] == 2
    assert out["sources_full_text"] == 1


def test_cited_ids_keep_writing_order_and_drop_duplicates():
    assert cited_source_ids("[S3] phir [S1] phir [S3] dobara") == ["S3", "S1"]
    assert cited_source_ids("") == []


# --- relevance: chali hi nahi vs chali aur kuch nahi mila --------------------

def test_relevance_that_never_ran_leaves_both_counts_unknown():
    out = source_counters(_pack(_src("S1"), _src("S2")))
    assert out["directly_relevant_sources"] is None
    assert out["directly_relevant_ids"] is None
    assert out["average_relevance"] is None


def test_relevance_that_ran_and_found_nothing_above_the_floor_is_a_real_zero():
    out = source_counters(_pack(_src("S1", relevance=0.21),
                                _src("S2", relevance=0.19)))
    assert out["directly_relevant_sources"] == 0
    assert out["directly_relevant_ids"] == []
    assert out["average_relevance"] == 0.2


def test_a_source_that_fails_the_proposition_test_is_not_directly_relevant():
    out = source_counters(_pack(_src("S1", relevance=0.91,
                                     parts={"tests_proposition": False}),
                                _src("S2", relevance=0.72)))
    assert out["directly_relevant_ids"] == ["S2"]


def test_a_rejected_source_is_never_counted_as_directly_relevant():
    out = source_counters(_pack(_src("S1", relevance=0.88,
                                     rejected="off-topic: calibration paper"),
                                _src("S2", relevance=0.66)))
    assert out["directly_relevant_ids"] == ["S2"]
    assert out["sources_retrieved"] == 2


def test_average_relevance_of_cited_sources_is_reported_separately():
    out = source_counters(_pack(_src("S1", relevance=0.80),
                                _src("S2", relevance=0.20)),
                          answer_text="Sirf pehla source cite hua [S1].")
    assert out["average_relevance"] == 0.5
    assert out["average_relevance_cited"] == 0.8


# --- independence: alag URL alag source nahi ---------------------------------

def test_two_urls_from_the_same_group_and_method_are_one_family():
    same = [_src("S1", authors=["Rubin, Vera C."], methodology="cohort",
                 url="https://mirror-one.example.org/a"),
            _src("S2", authors=["Vera C. Rubin"], methodology="cohort",
                 url="https://mirror-two.example.org/b")]
    out = source_counters(_pack(*same))
    assert out["independent_source_families"] == 1
    assert out["distinct_urls"] == 2
    assert list(independent_families(same).values()) == [["S1", "S2"]]


def test_a_different_method_from_the_same_group_is_its_own_family():
    out = source_counters(_pack(_src("S1", authors=["Rubin, Vera"], methodology="rct"),
                                _src("S2", authors=["Rubin, Vera"], methodology="cohort")))
    assert out["independent_source_families"] == 2


def test_supporting_critical_claims_stays_unknown_until_it_is_passed_in():
    pack = _pack(_src("S1"))
    assert source_counters(pack)["sources_supporting_critical_claims"] is None
    assert source_counters(pack, supporting_critical=[]
                           )["sources_supporting_critical_claims"] == 0
    assert source_counters(pack, supporting_critical=["S1"]
                           )["sources_supporting_critical_claims"] == 1


# --- bina source ke dave (asli run mein 14 baar) -----------------------------

_STRONG_LINE = ("[ESTABLISHED FACT] Dark matter halo galaxy rotation curve ko "
                "poori tarah samjha deta hai.")


def test_a_strong_label_without_any_citation_is_flagged_as_critical():
    hits = no_source_claims("## Supporting evidence\n" + _STRONG_LINE)
    assert len(hits) == 1
    assert hits[0]["kind"] == "strong_without_citation"
    assert hits[0]["critical"] is True


def test_the_same_strong_line_with_a_citation_is_not_flagged():
    line = _STRONG_LINE.replace("deta hai.", "deta hai [S1].")
    assert no_source_claims("## Supporting evidence\n" + line) == []


def test_an_explicit_no_source_label_is_flagged_with_its_own_kind():
    hits = no_source_claims("## Aur baatein\n[NO-SOURCE] Ye baat kisi paper se "
                            "nahi aayi, model ne khud likhi thi.")
    assert [h["kind"] for h in hits] == ["no_source_label"]
    assert hits[0]["critical"] is False


def test_a_no_source_line_inside_an_evidence_section_becomes_critical():
    hits = no_source_claims("## Seedha jawab\n[NO-SOURCE] Halo ka density "
                            "profile is tarah ka hota hai, aisa maana jaata hai.")
    assert hits[0]["critical"] is True


def test_very_short_lines_are_not_scanned_as_claims():
    assert no_source_claims("## Seedha jawab\n[NO-SOURCE] chhota.") == []


# --- hypothesis aur fact ka mix (dono taraf se) ------------------------------

_LAB = "## APP ORIGINAL RESEARCH LAB"


def test_a_fact_label_inside_the_lab_section_is_the_worst_kind_of_mix():
    mix = hypothesis_fact_mix(_LAB + "\n[ESTABLISHED FACT] Humara idea galaxy "
                                     "core ko samtal karta hai, ye pakka hai.")
    assert mix["count"] == 1
    assert mix["details"][0]["kind"] == "hypothesis_labelled_as_fact"


def test_a_hypothesis_label_inside_an_evidence_section_is_also_a_mix():
    mix = hypothesis_fact_mix("## Supporting evidence\n[HYPOTHESIS] Self-"
                              "interacting dark matter core ko samtal karta hai.")
    assert [d["kind"] for d in mix["details"]] == ["hypothesis_inside_evidence_section"]


def test_a_hypothesis_label_inside_the_lab_is_exactly_where_it_belongs():
    mix = hypothesis_fact_mix(_LAB + "\n[HYPOTHESIS] Self-interacting dark "
                                     "matter core ko samtal kar sakta hai.")
    assert mix["count"] == 0
    assert mix["details"] == []


# --- §9 access depth: overclaim aur banned label ------------------------------

def test_an_access_check_that_could_not_run_returns_none_not_an_empty_list():
    assert access_depth_mismatches(None, "kuch text") is None
    assert access_depth_mismatches(_pack(_src("S1")), "   ") is None
    assert access_depth_mismatches(_pack(_src("S1")), "koi label nahi") == []


def test_the_banned_full_text_verified_label_is_caught_anywhere():
    hits = access_depth_mismatches(
        _pack(_src("S1")), "Ye claim %s hai [S1]." % BANNED_ACCESS_LABEL)
    assert [h["kind"] for h in hits] == ["banned_label"]
    assert hits[0]["claimed"] == BANNED_ACCESS_LABEL
    assert "poora text padhna claim verify karna NAHI hai" in hits[0]["why"]


def test_the_banned_label_is_not_one_of_the_five_allowed_depth_labels():
    assert BANNED_ACCESS_LABEL not in ACCESS_DEPTH_ALLOWED
    assert len(ACCESS_DEPTH_ALLOWED) == 5


def test_claiming_full_text_for_an_abstract_only_source_is_an_overclaim():
    pack = _pack(_src("S1", read_level="abstract"))
    hits = access_depth_mismatches(pack, "Is source ka %s tha [S1], isliye "
                                        "poora data mila." % ACCESS_FULL)
    assert [h["kind"] for h in hits] == ["depth_overclaim"]
    assert hits[0]["claimed"] == ACCESS_FULL
    assert hits[0]["actual"] == ACCESS_ABSTRACT
    assert hits[0]["source_id"] == "S1"


def test_claiming_less_than_what_was_actually_read_is_not_a_mismatch():
    pack = _pack(_src("S1", read_level="full_text"))
    assert access_depth_mismatches(pack, "Humne sirf %s dekha [S1]."
                                  % ACCESS_ABSTRACT) == []


def test_partly_read_pages_are_not_reported_as_full_text_access():
    src = _src("S1", read_level="full_text", pages_read=18, pages_total=30)
    assert src.access_depth() != ACCESS_FULL
    hits = access_depth_mismatches(_pack(src), "Poora %s tha [S1]." % ACCESS_FULL)
    assert [h["kind"] for h in hits] == ["depth_overclaim"]


# --- §18 number wala confidence ----------------------------------------------

def test_a_percentage_next_to_a_confidence_word_is_recorded():
    hits = numeric_confidence_claims("Is nateeje par humara confidence 92% hai.")
    assert len(hits) == 1
    assert "92%" in hits[0]["numbers"]


def test_a_percentage_with_no_confidence_word_is_left_alone():
    assert numeric_confidence_claims("Sample ka 92% hissa female tha.") == []


# --- §19 tri-state contract ---------------------------------------------------

def test_tristate_field_names_are_unique_and_every_one_reaches_the_context():
    assert len(TRISTATE_FIELDS) == len(set(TRISTATE_FIELDS))
    ctx = quality_context()
    for name in TRISTATE_FIELDS:
        assert name in ctx, name
    assert set(ctx["checked"]) == set(TRISTATE_FIELDS)


def test_an_empty_run_reports_the_checks_as_not_done_at_all():
    ctx = quality_context()
    unknown = ctx["unknown_fields"]
    assert set(unknown) <= set(TRISTATE_FIELDS)
    for name in ("directly_relevant_sources", "calculations_count",
                 "counter_search_performed", "contradictions_rejected",
                 "relevance_gate_ran", "hypothesis_schema_complete",
                 "independent_source_families", "recovery_used"):
        assert name in unknown, name
        assert ctx["checked"][name] is False, name


def test_a_check_that_ran_and_said_no_leaves_the_unknown_list():
    ctx = quality_context(counter_search=False, recovery_used=False)
    assert ctx["counter_search_performed"] is False
    assert "counter_search_performed" not in ctx["unknown_fields"]
    assert ctx["checked"]["recovery_used"] is True


def test_calculations_that_were_never_looked_for_are_unknown_not_zero():
    never = quality_context()
    assert never["calculations_count"] is None
    assert never["calculations_usable"] is None
    assert never["calculations_failed_checks"] is None
    assert never["calculations_with_invented_inputs"] is None
    ran = quality_context(calculations=[])
    assert ran["calculations_count"] == 0
    assert ran["calculations_usable"] == 0
    assert "calculations_count" not in ran["unknown_fields"]


def test_a_calculation_with_a_failed_check_is_counted_on_its_own_line():
    ctx = quality_context(calculations=[
        {"result": "12", "unit_check_passed": False},
        {"result": "7", "invented_input": True}])
    assert ctx["calculations_count"] == 2
    assert ctx["calculations_failed_checks"] == 1
    assert ctx["calculations_with_invented_inputs"] == 1
    assert ctx["calculations_usable"] < ctx["calculations_count"]


def test_a_numeric_confidence_claim_flips_calibration_to_false():
    ctx = quality_context(answer_text="Humara confidence 90% hai is nateeje par.")
    assert ctx["numeric_confidence_calibrated"] is False
    assert ctx["numeric_confidence_claims"]


def test_with_no_numeric_claim_the_calibration_question_stays_unknown():
    ctx = quality_context(answer_text="Confidence band LOW rakha gaya hai.")
    assert ctx["numeric_confidence_claims"] == []
    assert ctx["numeric_confidence_calibrated"] is None
    assert "numeric_confidence_calibrated" in ctx["unknown_fields"]


def test_contradiction_rejections_stay_unknown_until_the_report_arrives():
    assert quality_context()["contradictions_rejected"] is None
    ctx = quality_context(contradiction_rejections={"rejected": 2,
                                                   "counts": {"YEAR_ONLY": 2}})
    assert ctx["contradictions_rejected"] == 2
    assert ctx["contradiction_reject_codes"] == {"YEAR_ONLY": 2}


def test_contradiction_analysis_never_run_is_not_zero_contradictions():
    never = quality_context()
    assert never["contradictions_present"] is None
    assert never["contradictions"] is None
    assert never["contradictions_schema_complete"] is None
    ran = quality_context(contradictions=[])
    assert ran["contradictions_present"] == 0


def test_an_incomplete_contradiction_record_is_reported_as_incomplete():
    ctx = quality_context(contradictions=[{"summary": "s", "schema_complete": False}])
    assert ctx["contradictions_schema_complete"] is False


def test_the_evidence_graph_is_unknown_until_claim_verification_runs():
    assert quality_context()["evidence_graph_complete"] is None
    assert quality_context(evidence_graph=False)["evidence_graph_complete"] is False


# --- §6 relevance gate --------------------------------------------------------

def test_a_gate_that_never_ran_is_a_skeleton_not_a_row_of_zeroes():
    empty = relevance_gate_report(None)
    assert empty["ran"] is False
    assert empty["tests_proposition"] is None
    assert empty["does_not_test"] is None
    assert relevance_gate_report(_pack(_src("S1")))["ran"] is False


def test_the_gate_result_is_read_straight_out_of_the_pack():
    pack = _pack(_src("S1"), _src("S2"),
                 proposition={"dimensions": ["entity", "mechanism", "measure"],
                              "tests_proposition": 2, "does_not_test": 5,
                              "undecided": 1,
                              "failed_dimensions": {"mechanism": 4},
                              "note": "proposition-test chala"},
                 reject_codes={"OFF_TOPIC": 3})
    gate = relevance_gate_report(pack)
    assert gate["ran"] is True
    assert gate["tests_proposition"] == 2
    assert gate["does_not_test"] == 5
    assert gate["reject_codes"] == {"OFF_TOPIC": 3}
    ctx = quality_context(pack=pack)
    assert ctx["relevance_gate_ran"] is True
    assert ctx["sources_testing_proposition"] == 2
    assert ctx["relevance_reject_codes"] == {"OFF_TOPIC": 3}


def test_a_pack_without_a_gate_record_keeps_the_proposition_count_unknown():
    ctx = quality_context(pack=_pack(_src("S1")))
    assert ctx["sources_testing_proposition"] is None
    assert ctx["relevance_gate_ran"] is None
    assert ctx["sources_retrieved"] == 1


# --- §13-§18 hypothesis ka hisaab --------------------------------------------

def _hypo(**over) -> dict:
    h = {"hypothesis_id": "RV-HYP-1", "statement": "s", "provenance": "app",
         "mechanism": "m", "source_claim_disclaimer": "app ka apna idea",
         "prediction": "p", "novelty_status": "NOVELTY UNVERIFIED",
         "closest_prior_work": [{"source_id": "S1"}],
         "confidence": {"band": "LOW"},
         "validation_status": "TEST PLAN ONLY — NOT EXECUTED"}
    h.update(over)
    return h


def test_a_hypothesis_step_that_never_ran_is_unknown_on_every_line():
    out = hypothesis_report(None)
    assert out["ran"] is None
    assert out["count"] is None
    assert out["schema_complete"] is None
    assert out["novelty_counts"] is None
    ctx = quality_context()
    assert ctx["hypothesis_report"] is None
    assert ctx["hypotheses_present"] is None


def test_a_hypothesis_step_that_ran_and_built_nothing_is_a_real_zero():
    out = hypothesis_report([])
    assert out["ran"] is True
    assert out["count"] == 0
    assert out["schema_complete"] is True
    assert quality_context(hypotheses=[])["hypotheses_present"] == 0


def test_a_missing_field_makes_the_hypothesis_record_incomplete():
    out = hypothesis_report([_hypo(mechanism="")])
    assert out["schema_complete"] is False
    assert out["incomplete_ids"] == ["RV-HYP-1"]


def test_possibly_novel_without_a_search_that_ran_is_counted():
    out = hypothesis_report([_hypo(
        novelty_status="POSSIBLY NOVEL — NO CLOSE MATCH FOUND",
        novelty_search={"performed": None})])
    assert out["claimed_novel_without_search"] == 1
    ok = hypothesis_report([_hypo(
        novelty_status="POSSIBLY NOVEL — NO CLOSE MATCH FOUND",
        novelty_search={"performed": True})])
    assert ok["claimed_novel_without_search"] == 0


def test_a_novelty_label_outside_the_whitelist_is_named_out_loud():
    out = hypothesis_report([_hypo(novelty_status="BILKUL NAYA")])
    assert out["forbidden_novelty_labels"] == ["RV-HYP-1: BILKUL NAYA"]


def test_a_known_idea_hit_is_carried_into_the_report():
    out = hypothesis_report([_hypo(known_idea_hits=[{"pattern": "pbh"}])])
    assert out["known_ideas_flagged"] == ["RV-HYP-1"]


def test_a_safety_sensitive_hypothesis_without_risk_text_is_flagged():
    out = hypothesis_report([_hypo(safety_sensitive=True, risks="")])
    assert out["missing_risk_checks"] == ["RV-HYP-1"]
    safe = hypothesis_report([_hypo(
        safety_sensitive=True,
        risks="Dose escalation par expert review aur risk assessment zaroori hai.")])
    assert safe["missing_risk_checks"] == []


def test_confidence_bands_are_counted_and_numeric_confidence_is_visible():
    out = hypothesis_report([_hypo(), _hypo(hypothesis_id="RV-HYP-2",
                                            confidence={"band": "LOW",
                                                        "numeric_allowed": True})])
    assert out["confidence_bands"] == {"LOW": 2}
    assert out["numeric_confidence"] == 1


# --- audit block: None kabhi 0 nahi -------------------------------------------

def test_unknown_numbers_are_printed_as_check_nahi_hua():
    assert _num(None) == "check nahi hua"
    assert _num(0) == "0"


def test_no_context_at_all_refuses_to_print_counts():
    text = context_block(None)
    assert "Quality counters chale hi nahi" in text
    assert "jhoothi ginti dene se behtar hai" in text


def test_the_block_says_retrieval_count_is_not_evidence_strength():
    text = context_block(quality_context(pack=_pack(_src("S1"), _src("S2")),
                                        answer_text="Ek baat [S1]."))
    assert "Retrieval ki ginti evidence ki taakat NAHI hai" in text
    assert "retrieved): 2" in text and "cite hue: 1" in text


def test_an_empty_run_prints_check_nahi_hua_instead_of_zeroes():
    text = context_block(quality_context())
    assert "check nahi hua" in text
    assert "In cheezon ka check HO HI NAHI SAKA" in text


def test_the_block_refuses_to_say_no_contradictions_when_nothing_was_checked():
    text = context_block(quality_context())
    assert "Takraav ki jaanch is run mein chali hi nahi" in text
    assert "koi takraav nahi mila\" likhna galat hota" in text


def test_the_block_refuses_to_say_zero_sources_test_the_question():
    text = context_block(quality_context(pack=_pack(_src("S1"))))
    assert "proposition-test is run mein chala hi nahi" in text
    assert "0 likhna galat hota" in text


def test_the_block_names_the_hypothesis_step_when_it_never_ran():
    assert "hypothesis ka step is run mein chala hi nahi" in \
        context_block(quality_context())


# --- final answer par doosra scan --------------------------------------------

def test_a_rescan_without_a_final_answer_changes_nothing():
    ctx = quality_context()
    assert rescan_final_answer(ctx, None, "") is ctx
    assert rescan_final_answer(None, None, "kuch text") is None


def test_the_rescan_catches_a_numeric_confidence_that_only_the_final_text_has():
    ctx = quality_context(answer_text="Sirf band likha tha: LOW.")
    assert ctx["numeric_confidence_calibrated"] is None
    out = rescan_final_answer(ctx, None,
                              "## Seedha jawab\nAakhir mein confidence 88% likh diya.")
    assert out["numeric_confidence_calibrated"] is False
    assert out["sections_present"] == ["Seedha jawab"]
    assert "numeric_confidence_calibrated" not in out["unknown_fields"]


def test_section_titles_drop_numbering_and_emoji_but_keep_the_words():
    assert sections_present("## 3. 🔬 Evidence kya kehta hai?") == \
        ["Evidence kya kehta hai?"]
    assert sections_present("#### chhota heading\n## APP ORIGINAL RESEARCH LAB") == \
        ["APP ORIGINAL RESEARCH LAB"]


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
