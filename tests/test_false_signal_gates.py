"""
#114 — JHOOTHE SIGNAL ke teen taale (contradiction / calculation / novelty).

Live report me teen jhooth ban rahe the:
  1. do sources ka sirf topic ka naam mil raha tha, phir bhi "takraav" likha ja
     raha tha (ek source ne to wo cheez maapi bhi nahi thi);
  2. citation list aur padhe hue number ("Tc = 250 K") se CalculationRecord ban
     jaata tha, aur uspar "math model nahi bana" jaisa verdict aata tha;
  3. imaandaar INKAAR ("ye 100% new nahi hai") bhi banned-phrase gina jaata tha.

Ye file teeno taale dono taraf se pinned karti hai: jhooth ruke, aur sach
(asli takraav, asli hisaab, asli jhoothi novelty) bilkul na ruke.

Offline: koi network, koi Gemini. `tests/run_pytest_style_suites.py` isse
uthata hai; seedha bhi chalta hai.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import physics_checks as pc                      # noqa: E402
from research_engine.contradiction import (CONTRA_NOT_EVALUATED,      # noqa: E402
                                           CONTRA_REJECT_CODES,
                                           CONTRA_REJECT_WHY,
                                           CONTRA_WEAK_QUESTION_LINK,
                                           ContradictionEngine)
from research_engine.hypothesis import forbidden_novelty_phrases      # noqa: E402
from research_engine.models import EvidencePack, SourceRecord         # noqa: E402


def _src(sid: str, title: str, snippet: str, year: int = 2023) -> SourceRecord:
    """Har source ka domain alag — warna independence_key ek ho jaati hai."""
    s = SourceRecord(source_id=sid, title=title,
                     url=f"https://ex-{sid.lower()}.org/{sid}", snippet=snippet)
    s.year = year
    s.peer_reviewed = True
    return s


def _pack(question: str, a: SourceRecord, b: SourceRecord) -> EvidencePack:
    return EvidencePack(question=question, sources=[a, b])


# ── A. contradiction — "maapa hi nahi" aur "ulta nikla" ek baat nahi ─────────

VIT_A = _src("V1", "Vitamin D and fracture risk: a randomised trial",
             "Vitamin D supplementation reduces risk of hip fracture "
             "significantly.")
VIT_B = _src("V2", "Vitamin D and fracture risk: a second randomised trial",
             "Vitamin D supplementation showed no significant effect on hip "
             "fracture risk.")
VIT_Q = "does vitamin D supplementation reduce fracture risk"


def test_a_real_opposite_result_pair_is_still_a_contradiction():
    """Sabse zaroori pin: naye gate ne asli takraav ko nahi maara."""
    eng = ContradictionEngine()
    found = eng.detect(_pack(VIT_Q, VIT_A, VIT_B))
    assert len(found) == 1, [c.summary for c in found]
    assert found[0].kind == "STANCE"
    assert found[0].valid is True
    assert eng.rejection_report()["rejected"] == 0


def test_a_source_that_never_measured_the_thing_is_not_a_contradiction():
    audit = _src("W2", "Minimum wage compliance audit methodology",
                 "The audit did not measure employment; it does not report "
                 "youth outcomes at all.")
    effect = _src("W1", "Minimum wage and youth employment in 12 states",
                  "The minimum wage increase is associated with a 4% "
                  "employment gain.")
    eng = ContradictionEngine()
    found = eng.detect(_pack("minimum wage effect on youth employment",
                             effect, audit))
    assert found == []
    report = eng.rejection_report()
    assert report["rejected"] == 1
    assert report["counts"][CONTRA_NOT_EVALUATED] == 1


def test_a_manual_that_only_says_out_of_scope_cannot_oppose_a_measurement():
    manual = _src("H2", "Cable handling manual for superconductivity labs",
                  "The manual does not cover pressure cell maintenance for "
                  "hydride superconductivity rigs.")
    measured = _src("H1", "Hydride superconductivity under high pressure",
                    "Superconductivity is detected at 250 K in the hydride "
                    "sample under 170 GPa pressure.")
    eng = ContradictionEngine()
    assert eng.detect(_pack("room temperature superconductivity in hydrides",
                            measured, manual)) == []
    assert eng.rejection_report()["counts"][CONTRA_NOT_EVALUATED] == 1


def test_a_null_result_with_an_out_of_scope_aside_still_opposes():
    """
    Occurrence-level niyam ka pin. "did not reduce" asli ulta nateeja hai;
    usi vaakya me "did not measure bone density" sirf scope ki baat hai.
    Pehla wala scope-cue ke andar nahi hai, isliye stance OPPOSE rehni chahiye.
    """
    eng = ContradictionEngine()
    stance, _cues = eng.stance(
        "The drug did not reduce fracture risk; the study did not measure "
        "bone density.")
    assert stance == "OPPOSE", stance


def test_only_scope_wording_gives_the_not_evaluated_stance():
    eng = ContradictionEngine()
    stance, cues = eng.stance("The audit does not report youth outcomes and "
                              "employment was not measured.")
    assert stance == "NOT_EVALUATED", stance
    assert cues, "cue ka naam bhi aana chahiye"


def test_a_thin_topic_only_link_is_rejected_with_its_own_code():
    calib = _src("D2", "Telescope calibration pipeline for dark matter surveys",
                 "The calibration pipeline did not detect any systematic drift "
                 "in the dark matter survey photometry.")
    halo = _src("D1", "Galaxy rotation curves and dark matter halos",
                "For 175 galaxies the observed rotation curves cannot be "
                "fitted with baryons alone, so a dark matter halo is required.")
    eng = ContradictionEngine()
    assert eng.detect(_pack("dark matter evidence in galaxy rotation curves",
                            halo, calib)) == []
    counts = eng.rejection_report()["counts"]
    assert counts[CONTRA_WEAK_QUESTION_LINK] == 1


# Hinglish sawaal + English sources — root suite ka asli shape. Ye jodaa naye
# coverage gate ne kha liya tha (dono taraf 3/8 = 0.375), isliye ab pinned hai.
HING_Q = "kya AI training data ka bias real-world discrimination badha sakta hai?"
HING_SUPPORT = _src(
    "G1", "Gender Shades: accuracy disparities in commercial gender "
          "classification",
    "Error rates are far higher for darker-skinned women, which confirms "
    "systematic bias in training data.", year=2018)
HING_OPPOSE = _src(
    "G2", "Study finds no significant association between training data "
          "composition and downstream discrimination",
    "Across 12 deployments the authors report no significant effect and no "
    "association between dataset composition and measured discrimination.")


def test_a_hinglish_question_still_finds_the_english_stance_conflict():
    """
    Sawaal Hinglish hai, sources English — 8 stems mein "badha"/"sakta" jaise
    shabd koi English paper match hi nahi kar sakta. Gate ka kaam nakli jodaa
    rokna hai, sawaal ki bhasha ki saza dena nahi.
    """
    eng = ContradictionEngine()
    found = eng.detect(_pack(HING_Q, HING_SUPPORT, HING_OPPOSE))
    assert len(found) == 1, [c.reject_code for c in eng.last_rejected]
    assert found[0].kind == "STANCE"
    assert found[0].valid is True
    assert eng.rejection_report()["rejected"] == 0


def test_two_shared_words_on_a_long_question_is_still_too_thin():
    """
    Sirf topic ka NAAM ("training data") chhoo lene se kaam nahi chalta — sawaal
    ka doosra sira (bias/discrimination) bhi chhoona padta hai. Warna gate
    kaagzi ho jaata.
    """
    thin = _src("G3", "Cooling telemetry in GPU racks",
                "Rack telemetry from one training data centre shows no "
                "significant effect on fan wear.")
    eng = ContradictionEngine()
    assert eng.detect(_pack(HING_Q, HING_SUPPORT, thin)) == []
    assert eng.rejection_report()["counts"][CONTRA_WEAK_QUESTION_LINK] == 1


def test_touching_two_separate_parts_of_the_question_is_enough():
    """
    Mile-juli bhasha ka pin: sawaal ke 14 stems mein 9 Hindi shabd hain, isliye
    English paper ka coverage 40% tak pahunch hi nahi sakta. Do alag hisse
    chhoona kaafi hona chahiye.
    """
    q = ("Indus valley civilisation ke shehron ka patan monsoon ke badlav se "
         "hua ya vyapar toot jaane se?")
    claim = _src("A1", "Weakening monsoon and the deurbanisation of Indus "
                       "valley settlements",
                 "Settlement counts in the Ghaggar-Hakra plain fall by 71% "
                 "within the interval of monsoon weakening.")
    counter = _src("A2", "Monsoon weakening did not drive Indus "
                         "deurbanisation",
                   "Excavation of nine eastern sites shows settlement "
                   "continuity through the interval of monsoon weakening, so "
                   "climate did not drive deurbanisation everywhere.")
    eng = ContradictionEngine()
    found = eng.detect(_pack(q, claim, counter))
    assert len(found) == 1, [c.reject_code for c in eng.last_rejected]
    assert found[0].kind == "STANCE"


def test_a_measured_change_is_a_positive_finding_not_neutral():
    """"fall by 71%" ek naapa hua daawa hai — NEUTRAL nahi."""
    eng = ContradictionEngine()
    stance, cues = eng.stance("Settlement counts fall by 71% within this "
                              "window.")
    assert stance == "SUPPORT", (stance, cues)
    # ...par akela "drop test" jaisa topic-shabd support nahi banta
    assert eng.stance("The drop test rig was rebuilt.")[0] == "NEUTRAL"


def test_three_words_from_one_side_of_a_long_question_are_not_enough():
    """
    Hataye gaye teesre raaste ka pin (2026-08-27). Pehle "3 alag stem chhoo
    liye" bhi link maan liya jaata tha; us se ye housing-law review — jo AI ya
    training data ka naam bhi nahi leti — Gender Shades ke khilaaf khadi ho
    jaati (3/8 = 0.375 stem, sawaal ka sirf ek hissa). Ab wo raasta nahi hai,
    isliye ye nakli jodaa reject hona chahiye.
    """
    off_side = _src("R1", "Real-world discrimination in housing: a legal review",
                    "The review reports no significant effect of local "
                    "ordinances on complaint volume.")
    eng = ContradictionEngine()
    assert eng.detect(_pack(HING_Q, HING_SUPPORT, off_side)) == []
    assert eng.rejection_report()["counts"][CONTRA_WEAK_QUESTION_LINK] == 1


def test_a_source_that_echoes_the_whole_short_question_is_kept():
    """
    Doosra raasta (coverage): sawaal ka ek hi hissa hai, par source usi hisse ke
    teeno shabd bol raha hai — "training data bias" par likha paper sach me isi
    baat par hai, usse rokna over-blocking hota.
    """
    q = "AI training data bias"
    one_part = _src("P1", "Training data bias in commercial classifiers",
                    "The audit shows that training data bias increased error "
                    "rates for darker-skinned women.")
    counter = _src("P2", "Training data bias and downstream error rates",
                   "Across 12 deployments there is no significant effect of "
                   "training data bias on measured error rates.")
    eng = ContradictionEngine()
    found = eng.detect(_pack(q, one_part, counter))
    assert len(found) == 1, [c.reject_code for c in eng.last_rejected]


def test_a_short_question_can_pass_on_coverage_alone():
    """
    Coverage raasta ka apna pin: chhota sawaal, ek hissa, do shabd — par sawaal
    ka 40% se zyada chhoota hai, isliye link asli hai.
    """
    q = "vitamin D fracture risk"
    a = _src("K1", "Hip fracture outcomes after supplementation",
             "Supplementation reduces risk of hip fracture in the treated arm.")
    b = _src("K2", "Hip fracture outcomes in a second cohort",
             "There was no significant effect on fracture risk.")
    eng = ContradictionEngine()
    found = eng.detect(_pack(q, a, b))
    assert len(found) == 1, [c.reject_code for c in eng.last_rejected]


def test_every_reject_code_has_its_own_measured_reason():
    assert len(CONTRA_REJECT_CODES) == len(set(CONTRA_REJECT_CODES)) == 7
    for code in CONTRA_REJECT_CODES:
        assert len(CONTRA_REJECT_WHY[code].strip()) > 30, code
    assert len({v.strip() for v in CONTRA_REJECT_WHY.values()}) == 7


def test_not_evaluated_never_becomes_a_neutral_consensus_vote():
    eng = ContradictionEngine()
    report = eng.consensus_report(_pack(
        "minimum wage effect on youth employment",
        _src("C1", "Minimum wage audit methodology",
             "The audit did not measure employment outcomes."),
        _src("C2", "Minimum wage audit scope note",
             "Youth outcomes are outside the scope of this audit.")))
    counts = report["stance_counts"]
    assert counts["NOT_EVALUATED"] == 2, counts
    assert counts["NEUTRAL"] == 0, counts


# ── B. calculation record — bina asli ganit ke record nahi banta ─────────────

REAL_CALC = """## Calculation
Formula: M = v^2 * r / G
Assumption: circular orbit maana gaya hai.
v = 220 km/s
r = 8 kpc
G = 6.6743e-11 m^3/kg/s^2
Result = 8.99e10 solar masses
Uncertainty = 20 percent
"""
REAL_EVIDENCE = "Rotation curves give v = 220 km/s at r = 8 kpc."

CITATION_LIST = """## Sources
S1 = Feynman Lectures Vol 2
S2 = Jung, Collected Works 9
"""
REPORTED_NUMBERS = """## Nateeja
S1 = Nature 2023 ke hisaab se Tc = 250 K report hui hai.
S2 = arXiv preprint me Tc = 294 K likha hai.
"""
SAMPLE_STATS = """## Method
Study me n = 175 galaxies li gayi thi.
p = 0.03 nikla.
"""
FORMULA_ONLY = """## Calculation
Hum M = v^2 * r / G use karenge, jo standard circular-orbit relation hai.
Assumption: spherical distribution.
"""


def test_a_real_calculation_still_produces_one_usable_record():
    recs = pc.extract_calculations(REAL_CALC, question="Milky Way ka mass?",
                                   evidence_text=REAL_EVIDENCE)
    assert len(recs) == 1
    assert recs[0].formula == "M = v^2 * r / G"
    assert set(recs[0].inputs) == {"v", "r", "G"}
    assert pc.usable_calculation_count(recs) == 1


def test_a_citation_list_is_not_a_calculation():
    recs = pc.extract_calculations(CITATION_LIST, question="dark matter?")
    assert recs == []
    skips = pc.calculation_skips(CITATION_LIST, question="dark matter?")
    assert len(skips) == 1
    assert skips[0]["reason_code"] == pc.CALC_SKIP_NO_MATH


def test_numbers_read_out_of_sources_are_not_our_own_calculation():
    recs = pc.extract_calculations(REPORTED_NUMBERS, question="Tc kitna hai?")
    assert recs == []
    skips = pc.calculation_skips(REPORTED_NUMBERS, question="Tc kitna hai?")
    assert [s["reason_code"] for s in skips] == [pc.CALC_SKIP_REPORTED_NUMBER]


def test_a_sample_size_line_is_not_a_calculation():
    assert pc.extract_calculations(SAMPLE_STATS, question="kitni galaxies?") == []


def test_every_skipped_block_says_why_and_shows_its_text():
    answer = REPORTED_NUMBERS + "\n\n" + CITATION_LIST
    skips = pc.calculation_skips(answer, question="Tc kitna hai?")
    assert len(skips) == 2
    codes = {s["reason_code"] for s in skips}
    assert codes == set(pc.CALC_SKIP_CODES)
    for s in skips:
        assert len(s["why"].strip()) > 30, s
        assert s["excerpt"].strip(), s
        assert s["reason_code"] in pc.CALC_SKIP_WHY


def test_a_written_formula_without_numbers_is_still_recorded_not_dropped():
    """Formula likha hai to record banega — usme kami naam le kar likhi hogi."""
    recs = pc.extract_calculations(FORMULA_ONLY, question="Milky Way mass?")
    assert len(recs) == 1
    assert recs[0].formula == "M = v^2 * r / G"
    assert "result" in recs[0].core_missing
    assert pc.usable_calculation_count(recs) == 0


def test_prose_and_citation_words_can_never_become_a_formula():
    block = "S2 = arXiv preprint me Tc\nTc = 294 K\n"
    assert pc._pick_formula(block) == ""
    # asli symbol wala formula isi guard se nahi rukta
    assert pc._pick_formula("M = v^2 * r / G\nv = 220 km/s\n") == "M = v^2 * r / G"


def test_a_block_that_defines_a_long_name_may_still_use_it():
    """Guard prose kaatta hai, lambe naam ko nahi — value di ho to chalega."""
    block = ("energy = mass * c^2\nmass = 2 kg\nc = 3e8 m/s\n"
             "Result = 1.8e17 J\n")
    assert pc._pick_formula(block) == "energy = mass * c^2"


def test_a_calculation_we_could_not_recheck_is_not_counted_as_usable():
    """
    #114 — pehle `recalculation_passed is None` bhi "poora hisaab" gina jaata
    tha. Apna milaan hue bina hisaab poora nahi kehlata.
    """
    rec = pc.CalculationRecord(formula="M = v^2 * r / G",
                               inputs={"v": 220.0}, units={"v": "km/s"},
                               result="8.99e10 solar masses")
    rec.unit_check_passed = True
    rec.sanity_check_passed = True
    rec.recalculation_passed = None
    assert pc.usable_calculation_count([rec]) == 0
    assert pc.calculations_done([rec]) is False
    rec.recalculation_passed = True
    assert pc.usable_calculation_count([rec]) == 1


def test_extraction_that_never_ran_stays_unknown_not_zero():
    assert pc.usable_calculation_count(None) is None
    assert pc.usable_calculation_count([]) == 0


# ── C. novelty guard — imaandaar inkaar ko jhooth na samjho ──────────────────

def test_an_honest_hinglish_denial_of_novelty_is_not_banned():
    assert forbidden_novelty_phrases(
        "Ye idea 100% new nahi hai — PBH literature me pehle se hai.") == []


def test_an_honest_english_denial_of_novelty_is_not_banned():
    assert forbidden_novelty_phrases(
        "This is not 100% new; MOND already covers it.") == []
    assert forbidden_novelty_phrases(
        "We do not claim this is a world first.") == []


def test_a_denial_written_after_the_phrase_also_clears_it():
    """Report ka apna andaaz: phrase ke turant baad 'nahi kaha ja sakta'."""
    assert forbidden_novelty_phrases(
        "Ise world first nahi kaha ja sakta.") == []
    assert forbidden_novelty_phrases(
        "Ye kaam duniya mein pehli baar nahi ho raha.") == []


def test_a_real_novelty_lie_is_still_caught():
    hits = forbidden_novelty_phrases(
        "Ye duniya mein pehli hypothesis hai aur 100% new hai.")
    assert "100% new" in hits
    assert "duniya mein pehli" in hits


def test_the_three_pinned_lies_are_still_reported_together():
    hits = forbidden_novelty_phrases(
        "Ye humne khoj ki, world first breakthrough discovery")
    for phrase in ("humne khoj", "world first", "breakthrough discovery"):
        assert phrase in hits, phrase


def test_a_denial_from_the_previous_sentence_cannot_rescue_a_lie():
    """
    Sabse zaroori pin: window punctuation par rukti hai. Warna koi bhi jhooth
    pehle 'nahi' likh kar bach jaata — guard kaagzi ho jaata.
    """
    assert forbidden_novelty_phrases(
        "Ye purana nahi hai, ye 100% new hai.") == ["100% new"]


def test_a_no_doubt_style_phrase_does_not_count_as_denial():
    assert forbidden_novelty_phrases(
        "Isme koi shak nahi, ye 100% new hai.") == ["100% new"]
    assert forbidden_novelty_phrases(
        "There is no doubt this is a world first.") == ["world first"]


def test_one_bare_occurrence_keeps_the_phrase_banned():
    """Ek jagah inkaar, doosri jagah nanga daawa — phir bhi banned."""
    assert forbidden_novelty_phrases(
        "Ye 100% new nahi hai. Lekin asal mein ye 100% new hai."
    ) == ["100% new"]


def test_a_phrase_that_only_appears_across_two_fields_is_banned_outright():
    """Join se bana phrase — bharosa nahi, isliye bina shart banned."""
    assert forbidden_novelty_phrases("Ye 100%", "new hai") == ["100% new"]


def test_clean_hypothesis_text_reports_nothing():
    assert forbidden_novelty_phrases("Ye ek untested hypothesis hai.") == []
    assert forbidden_novelty_phrases("", None) == []
