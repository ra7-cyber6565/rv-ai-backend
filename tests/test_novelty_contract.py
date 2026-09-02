"""§14/§15 — novelty ka contract: "naya" kehna sabse aasan jhooth hai.

Live dark-matter run mein app ne PBH, modeling systematics aur dark photon ko
"humari nayi hypothesis" bana diya tha — teenon decades purane ideas hain — aur
prior-art search chali hi nahi thi. Ye file wahi galti regression bana deti hai:

  * jaana-pehchana idea kabhi "possibly novel" nahi ban sakta;
  * "POSSIBLY NOVEL" sirf tab jab prior-art search SACH mein chali ho;
  * search na chali ho to jawab "NOVELTY UNVERIFIED" hai — "naya" nahi;
  * novelty label sirf chhe whitelisted shabdon mein se ek hi ho sakta hai;
  * khaali prior-work list ka matlab "match nahi mila", "prior work nahi hai" nahi.

Poora offline aur deterministic: koi network, koi model, koi provider call.

Chalane ka tareeka (repo root = backend/):
    PYTHONPATH=. python3 tests/test_novelty_contract.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.hypothesis import (KNOWN_IDEA_PATTERNS,      # noqa: E402
                                        closest_prior_work,
                                        forbidden_novelty_phrases,
                                        known_idea_hits,
                                        novelty_assessment, novelty_queries)
from research_engine.models import (NOVELTY_DUPLICATE,            # noqa: E402
                                    NOVELTY_KNOWN, NOVELTY_KNOWN_VARIANT,
                                    NOVELTY_MINOR, NOVELTY_POSSIBLE,
                                    NOVELTY_STATES, NOVELTY_UNVERIFIED)


class _Src:
    """Sirf wahi attributes jo closest_prior_work padhta hai."""

    def __init__(self, source_id: str, title: str, snippet: str = "", venue: str = ""):
        self.source_id = source_id
        self.title = title
        self.snippet = snippet
        self.venue = venue


_NEW_IDEA = ("Cluster outskirts mein velocity anisotropy se lensing residual ka "
             "seedha rishta banta hai")


def _prior(similarity: float, source_id: str = "S7") -> list:
    """Ek banaya hua prior-work row (similarity seedha diya gaya)."""
    return [{"source_id": source_id, "title": "Prior work",
             "similarity": similarity, "same": "dono me common: lensing",
             "difference": "is hypothesis me extra: anisotropy"}]


# --- whitelist ---------------------------------------------------------------

def test_every_verdict_stays_inside_the_six_whitelisted_labels():
    cases = []
    for statement in (_NEW_IDEA, "PBH dark matter ka hissa hai", ""):
        for searched in (None, False, True):
            for sim in (None, 0.1, 0.4, 0.6, 0.9):
                prior = _prior(sim) if sim is not None else None
                cases.append(novelty_assessment(statement, prior=prior,
                                                prior_art_searched=searched))
    assert cases
    for result in cases:
        assert result["novelty_status"] in NOVELTY_STATES, result["novelty_status"]


def test_possibly_novel_label_carries_its_own_caveat():
    assert "NO CLOSE MATCH FOUND" in NOVELTY_POSSIBLE
    assert "NOVEL" in NOVELTY_POSSIBLE and "PROVEN" not in NOVELTY_POSSIBLE.upper()


# --- prior-art search: teen imaandaar jawab ----------------------------------

def test_search_never_ran_is_unverified_not_novel():
    out = novelty_assessment(_NEW_IDEA, prior_art_searched=None)
    assert out["novelty_status"] == NOVELTY_UNVERIFIED
    assert out["novelty_search"]["performed"] is None
    assert out["novelty_search"]["close_match_found"] is None
    assert "'Nayi hai' likhna yahan jhooth hota" in out["why"]


def test_search_that_failed_to_run_is_also_not_novel():
    out = novelty_assessment(_NEW_IDEA, prior_art_searched=False)
    assert out["novelty_status"] == NOVELTY_UNVERIFIED
    assert out["novelty_search"]["performed"] is False


def test_possibly_novel_needs_a_search_that_actually_ran():
    out = novelty_assessment(_NEW_IDEA, prior_art_searched=True,
                             databases=["arXiv", "EPO"])
    assert out["novelty_status"] == NOVELTY_POSSIBLE
    assert out["novelty_search"]["databases"] == ["arXiv", "EPO"]
    assert "'duniya me pehli baar' NAHI" in out["why"]


def test_empty_prior_list_means_no_match_found_not_no_prior_work():
    out = novelty_assessment(_NEW_IDEA, prior=[], prior_art_searched=True)
    assert out["closest_prior_work"] == []
    assert out["novelty_search"]["closest_similarity"] is None
    assert "humari search me nahi mila" in out["why"]


# --- jaane-pehchane ideas (live run ki asli galti) ---------------------------

def test_the_three_ideas_that_were_wrongly_called_new_are_known_now():
    for statement in ("Primordial black hole population dark matter explain karti hai",
                      "Dark photon coupling se signal banta hai",
                      "Modeling systematic error se rotation curve mismatch hota hai"):
        out = novelty_assessment(statement, prior_art_searched=True)
        assert out["novelty_status"] in (NOVELTY_KNOWN, NOVELTY_KNOWN_VARIANT), statement
        assert out["novelty_status"] != NOVELTY_POSSIBLE
        assert out["known_idea_hits"], statement


def test_a_known_idea_stays_known_even_when_the_search_did_run():
    out = novelty_assessment("MOND galaxy rotation ko fit karta hai",
                             prior_art_searched=True, databases=["arXiv"])
    assert out["novelty_status"] == NOVELTY_KNOWN
    assert "Ise app ki nayi soch batana galat hoga" in out["why"]


def test_a_numeric_twist_on_a_known_idea_is_a_variant_not_a_new_idea():
    out = novelty_assessment("Axion mass 12 micro-eV par signal dikhega",
                             prior_art_searched=True)
    assert out["novelty_status"] == NOVELTY_KNOWN_VARIANT
    assert "idea nayi nahi hai" in out["why"]


def test_known_idea_matching_ignores_spacing_and_hyphens():
    assert known_idea_hits("self interacting  dark matter core")
    assert known_idea_hits("self-interacting dark matter core")
    assert known_idea_hits("f(r) gravity")


def test_known_idea_hits_do_not_repeat_the_same_reason():
    hits = known_idea_hits("PBH aur primordial black hole dono")
    whys = [h["why_known"] for h in hits]
    assert len(whys) == len(set(whys))


def test_known_idea_list_names_a_real_reason_for_every_entry():
    for pattern, why in KNOWN_IDEA_PATTERNS.items():
        assert pattern == pattern.lower(), pattern
        assert len(why.strip()) > 12, pattern


# --- similarity ki teen seedhi lines ----------------------------------------

def test_near_identical_prior_work_is_a_duplicate_not_a_hypothesis():
    out = novelty_assessment(_NEW_IDEA, prior=_prior(0.86), prior_art_searched=True)
    assert out["novelty_status"] == NOVELTY_DUPLICATE
    assert "lagbhag yahi baat pehle se hai" in out["why"]


def test_close_prior_work_is_only_a_minor_modification():
    out = novelty_assessment(_NEW_IDEA, prior=_prior(0.60), prior_art_searched=True)
    assert out["novelty_status"] == NOVELTY_MINOR
    assert out["novelty_search"]["close_match_found"] is True


def test_a_nearby_line_of_work_makes_it_a_known_variant():
    out = novelty_assessment(_NEW_IDEA, prior=_prior(0.40), prior_art_searched=True)
    assert out["novelty_status"] == NOVELTY_KNOWN_VARIANT
    assert out["novelty_search"]["close_match_found"] is False


def test_duplicate_check_runs_even_when_the_search_flag_is_unknown():
    out = novelty_assessment(_NEW_IDEA, prior=_prior(0.9), prior_art_searched=None)
    assert out["novelty_status"] == NOVELTY_DUPLICATE
    assert out["novelty_search"]["performed"] is None


# --- prior work ka record ----------------------------------------------------

def test_closest_prior_work_reports_what_is_same_and_what_differs():
    rows = closest_prior_work(
        "velocity anisotropy lensing residual cluster outskirts",
        [_Src("S1", "Weak lensing residual in cluster outskirts"),
         _Src("S2", "Exoplanet transit photometry calibration")])
    assert rows and rows[0]["source_id"] == "S1"
    assert rows[0]["same"].startswith("dono me common:")
    assert rows[0]["difference"]
    assert rows[0]["similarity"] >= (rows[-1]["similarity"] if len(rows) > 1 else 0)


def test_sources_with_no_usable_text_are_skipped_not_scored():
    rows = closest_prior_work("velocity anisotropy lensing",
                              [_Src("S9", ""), _Src("S1", "lensing anisotropy")])
    assert [r["source_id"] for r in rows] == ["S1"]


def test_no_sources_at_all_returns_an_empty_record():
    assert closest_prior_work("kuch bhi", []) == []
    assert closest_prior_work("kuch bhi", None) == []


# --- prior-art queries: audit ke liye deterministic --------------------------

def test_five_different_prior_art_queries_are_produced():
    queries = novelty_queries(_NEW_IDEA, "anisotropy se residual",
                              "dark matter kya hai")
    assert len(queries) == 5
    assert len({q.lower() for q in queries}) == 5


def test_prior_art_queries_include_a_counter_side_axis():
    joined = " ".join(novelty_queries(_NEW_IDEA, "anisotropy")).lower()
    assert "review" in joined and "ruled out" in joined
    assert "mechanism" in joined


def test_prior_art_queries_are_the_same_on_every_run():
    first = novelty_queries(_NEW_IDEA, "anisotropy", "dark matter")
    second = novelty_queries(_NEW_IDEA, "anisotropy", "dark matter")
    assert first == second


def test_assessment_keeps_the_queries_it_was_given():
    out = novelty_assessment(_NEW_IDEA, prior_art_searched=True,
                             queries=["q1 lensing residual", "q2 anisotropy"])
    assert out["novelty_search"]["queries"] == ["q1 lensing residual",
                                               "q2 anisotropy"]


def test_assessment_records_queries_even_when_none_were_passed():
    out = novelty_assessment(_NEW_IDEA, prior_art_searched=False)
    assert len(out["novelty_search"]["queries"]) == 5


# --- shabd jo kabhi nahi ------------------------------------------------------

def test_forbidden_discovery_words_are_reported_by_name():
    found = forbidden_novelty_phrases("Ye humne khoj ki, world first breakthrough discovery")
    assert "humne khoj" in found and "world first" in found
    assert "breakthrough discovery" in found


def test_clean_text_reports_no_forbidden_words():
    assert forbidden_novelty_phrases("Ye ek untested hypothesis hai.") == []


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
