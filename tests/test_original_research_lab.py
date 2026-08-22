"""§12/§13 — "APP ORIGINAL RESEARCH LAB" ka apna alag kamra (Claude-owned).

Live dark-matter run mein app ki apni soch report ke beech mein, established
evidence ke saath mil kar chhap gayi thi — PBH, systematics aur dark-photon
jaise pehle se maujood ideas "humari nayi hypothesis" ban gaye, aur padhne wale
ko lagta tha ki ye bhi research ka nateeja hai. Saath hi Calculations section
bilkul gayab tha, isliye pata hi nahi chalta tha ki hisaab hua tha aur bana
nahi, ya hisaab ki zaroorat hi nahi thi.

Ye file un dono baaton ko regression bana deti hai:

  * lab section ka naam shabd-ba-shabd, uske sar par warning, aur uska content
    evidence sections se alag;
  * app ke idea par pehle disclaimer, phir statement;
  * novelty app ke deterministic label se, model ke shabd se nahi;
  * prior-art search na chali ho to "novelty verified nahi" — "naya hai" nahi;
  * confidence sirf BAND, percentage nahi;
  * Calculations section kabhi gayab nahi — na bane to WAJAH.

Poora offline: koi network, koi model, koi provider call.

Chalane ka tareeka (repo root = backend/):
    PYTHONPATH=. python3 tests/test_original_research_lab.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.answer_order import (LAB_HEADING,          # noqa: E402
                                          LAB_WARNING,
                                          NO_CALC_REASONS,
                                          display_heading, order_note,
                                          order_report, section_body)
from research_engine.hypothesis import (FORBIDDEN_NOVELTY_PHRASES,  # noqa: E402
                                        STATUS)
from research_engine.synthesizer import FinalSynthesizer          # noqa: E402


def _hypo(**over) -> dict:
    h = {
        "hypothesis_id": "RV-HYP-1",
        "statement": "Dwarf galaxy cores mein self-interacting dark matter density flatten karta hai.",
        "simple": "Chhoti galaxy ke beech ka hissa samtal ho jaata hai.",
        "source_claim_disclaimer": ("⚠️ Ye app ka apna idea hai — kisi source ka "
                                    "claim nahi."),
        "mechanism": "Self-scattering se core mein energy transfer hota hai.",
        "supporting_evidence": ["S1"],
        "contradicting_evidence": ["S2"],
        "how_to_test": "Rotation curve fit karo.",
        "falsification_test": "Cusp mile to hypothesis galat.",
        "novelty_status": "NOVELTY UNVERIFIED",
        "novelty_why": "prior-art search is run mein nahi chali",
        "confidence_band": "LOW",
        "confidence": {"reasons": ["sirf 2 direct sources"], "model_said": "85% likely"},
        "status": STATUS,
        "validation_status": "TEST PLAN ONLY — NOT EXECUTED",
        "is_testable": True,
    }
    h.update(over)
    return h


def _lab(**over) -> str:
    """Rendered lab block (sirf app ki soch ka hissa)."""
    hypos = over.pop("hypotheses", [_hypo()])
    return FinalSynthesizer()._hypothesis_section(hypos, **over)


def _answer(lab_head: str = "## " + LAB_HEADING, warning: str = LAB_WARNING) -> str:
    return "\n\n".join([
        "## " + display_heading("direct_answer"), "Seedha jawab yahan.",
        "## " + display_heading("supporting_evidence"), "Evidence [S1].",
        lab_head, warning, "App ka idea yahan.",
        "## " + display_heading("audit"), "Audit yahan.",
        "## " + display_heading("sources"), "- [S1] paper",
    ])


# --- lab section ki alag pehchan ---------------------------------------------

def test_lab_heading_is_word_for_word_and_carries_its_warning():
    report = order_report(_answer())
    assert report["lab_heading_exact"] is True
    assert report["lab_warning_present"] is True
    assert "original_lab" in report["present"]


def test_lab_heading_with_a_softer_name_is_not_accepted_as_the_lab():
    report = order_report(_answer(lab_head="## Humari nayi soch"))
    assert report["lab_heading_exact"] is False
    assert "'%s' heading nahi mili" % LAB_HEADING in order_note(report)


def test_lab_without_the_warning_line_is_reported_not_ignored():
    report = order_report(_answer(warning="Yahan kuch hypotheses hain."))
    assert report["lab_heading_exact"] is True
    assert report["lab_warning_present"] is False
    assert "warning nahi mili" in order_note(report)


def test_app_idea_text_does_not_leak_into_the_evidence_section():
    text = _answer()
    assert "App ka idea yahan." in section_body(text, "original_lab")
    assert "App ka idea yahan." not in section_body(text, "supporting_evidence")
    assert "Evidence [S1]." not in section_body(text, "original_lab")


def test_lab_warning_says_it_is_the_app_s_own_thinking_not_a_finding():
    low = LAB_WARNING.lower()
    assert "khud ki soch" in low
    assert "established fact nahi" in low
    for word in ("proven", "discovery", "fact ki tarah"):
        assert ("**%s**" % word) not in low


# --- hypothesis card: pehle disclaimer, phir idea --------------------------

def test_disclaimer_comes_before_the_statement_in_every_card():
    text = _lab()
    assert "app ka apna idea" in text.lower()
    assert text.index("app ka apna idea") < text.index("Simple words mein")


def test_untested_status_line_is_always_printed():
    text = _lab()
    assert STATUS in text
    assert "abhi real-world test nahi hua" in text
    assert "Validation: TEST PLAN ONLY — NOT EXECUTED." in text


def test_confidence_is_a_band_and_the_model_percentage_is_not_adopted():
    text = _lab()
    assert "**Kitna bharosa (band, percentage nahi):** LOW" in text
    assert "85% likely" in text and "uska andaza hai" in text
    assert "**Kitna bharosa (band, percentage nahi):** 85%" not in text


def test_missing_fields_block_the_word_testable():
    text = _lab(hypotheses=[_hypo(missing_fields=["mechanism", "falsification_test"])])
    assert "poori tarah testable nahi" in text
    assert "mechanism, falsification_test" in text


def test_incomplete_test_plan_is_not_called_a_falsification_test():
    text = _lab(hypotheses=[_hypo(
        experiment_structured={"missing": ["control", "sample size"]})])
    assert "Test plan mein ye hisse nahi aaye" in text
    assert "poora falsification test nahi maana" in text


def test_safety_sensitive_hypothesis_always_carries_the_risk_warning():
    text = _lab(hypotheses=[_hypo(safety_sensitive=True)])
    assert "Safety-sensitive" in text
    assert "expert review aur risk assessment" in text


def test_support_and_counter_evidence_absence_is_named_not_hidden():
    text = _lab(hypotheses=[_hypo(supporting_evidence=[],
                                  contradicting_evidence=[])])
    assert "sirf ek idea hai" in text
    assert "self-check adhoora raha" in text


# --- §14 novelty: app ka label, model ka shabd nahi -------------------------

def test_novelty_status_is_printed_before_the_model_s_own_novelty_words():
    text = _lab(hypotheses=[_hypo(novelty="Ye bilkul naya idea hai")])
    assert text.index("**Novelty status:**") < text.index("Model ne novelty par")


def test_prior_art_search_not_run_means_novelty_is_only_unknown():
    text = _lab(hypotheses=[_hypo(novelty_search={"performed": False})])
    assert "prior-art search nahi chali" in text
    assert "novelty verified nahi" in text
    assert "sirf 'pata nahi' hai" in text


def test_prior_art_search_that_ran_lists_where_it_looked():
    text = _lab(hypotheses=[_hypo(
        novelty_status="POSSIBLY NOVEL",
        novelty_search={"performed": True, "databases": ["arXiv", "EPO"]})])
    assert "**Prior-art search:** hui — databases: arXiv, EPO." in text


def test_no_close_prior_work_is_not_turned_into_a_world_first_claim():
    text = _lab()
    assert "koi close match nahi mila" in text
    assert '"duniya mein pehli" nahi' in text


def test_every_forbidden_novelty_phrase_is_immediately_negated():
    text = _lab(hypotheses=[_hypo(novelty_status="POSSIBLY NOVEL")]).lower()
    for phrase in FORBIDDEN_NOVELTY_PHRASES:
        at = text.find(phrase)
        while at != -1:
            tail = text[at + len(phrase):at + len(phrase) + 14]
            assert "nahi" in tail, "novelty phrase bina inkaar ke: %s" % phrase
            at = text.find(phrase, at + 1)


# --- requested hypotheses: "zaroorat nahi thi" wala jhooth band --------------

def test_asked_but_none_built_never_says_it_was_not_needed():
    text = _lab(hypotheses=[], requests={"hypothesis_count": 3},
                reasons=["reasoning provider quota khatam"])
    assert "zaroorat nahi thi" in text          # sirf inkaar ke roop mein
    assert "wali baat nahi hai — zaroorat thi" in text
    assert "reasoning provider quota khatam" in text
    assert text.lstrip().startswith("❌")


def test_not_asked_and_none_built_is_a_plain_explanation_not_a_failure():
    text = _lab(hypotheses=[], requests={})
    assert "zaroorat nahi padi" in text
    assert "❌" not in text


def test_fewer_hypotheses_than_asked_is_stated_as_incomplete():
    text = _lab(hypotheses=[_hypo()], requests={"hypothesis_count": 3})
    assert "3 maangi thi, 1 ban paayi" in text
    assert "list adhoori hai" in text


# --- §12 Calculations section kabhi gayab nahi -------------------------------

def test_three_no_calculation_reasons_are_three_different_sentences():
    assert len({v.strip() for v in NO_CALC_REASONS.values()}) == 3
    assert set(NO_CALC_REASONS) == {"not_asked", "no_inputs", "no_reasoning"}


def test_calculation_not_asked_says_so_instead_of_vanishing():
    note = FinalSynthesizer()._no_calculation_note(None, None, None)
    assert note.startswith("_Koi calculation is jawab mein nahi hai._")
    assert NO_CALC_REASONS["not_asked"] in note


def test_calculation_asked_but_no_inputs_is_not_the_same_as_not_asked():
    note = FinalSynthesizer()._no_calculation_note(
        None, {"items": [{"key": "calculations"}]}, None)
    assert NO_CALC_REASONS["no_inputs"] in note
    assert NO_CALC_REASONS["not_asked"] not in note


def test_calculation_lost_to_a_dead_reasoning_provider_says_hisaab_hua_hi_nahi():
    class _Pack:
        reasoning_complete = False

    note = FinalSynthesizer()._no_calculation_note(
        _Pack(), None, {"wants_math_model": True})
    assert NO_CALC_REASONS["no_reasoning"] in note
    assert "hisaab hua hi nahi" in note


def test_calculation_section_names_every_missing_part_of_the_hisaab():
    text = FinalSynthesizer()._calculation_section([{"result": "12"}])
    assert "**Formula:** likha hi nahi gaya tha" in text
    assert "kaunsa number kahan se aaya, ye likha nahi gaya tha" in text
    assert "koi assumption likha nahi gaya" in text
    assert "nateeje ka unit nahi likha gaya" in text
    assert "Uncertainty:** nahi di gayi" in text
    assert "Inputs kahan se aaye, ye check nahi ho paaya" in text


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
