"""
ANCHOR SCOPE ka test — "app ka apna banaya anchor zaroori evidence axis tay
nahi kar sakta", aur "bina naap wale web opinion ko 'pata nahi' bacha nahi
sakta".

Asli failure jo ye file pakadti hai (2026-08-25, dark-matter acceptance
benchmark DM-01 x3 variants + DM-02 ka live-shape run):

  * `RelevanceEngine.axes_of()` sawaal ke saath lens ka SCORING ANCHOR jod kar
    axis list maangta tha. Us prompt ka anchor app ki hi contract-bhasha se bana
    tha: "har hypothesis observations calculation limitations counterevidence
    falsification confidence". Wo joda hua anchor apna ek alag facet ban jaata
    tha (3 -> 4), aur 4 facet par upar wali parat curated 17 dark-matter axes ki
    jagah keyword-facet axes (facet_f1..f4) rakh deti hai.

  * Nateeja naapa gaya: exoplanet ka TESS paper "facet_f2 (calculation)" par
    `required_axis` ok ho gaya -> proposition verdict False se True -> rule A ka
    SUBJECT_MISSING hard reject chala hi nahi -> wo paper **0.000 se 0.438** par
    pack me ghus gaya, uncited_sources 2 se 3 ho gaye. Yaani app ke apne shabd
    hi research target ban gaye aur ek decoy ko evidence bana diya.

  * Usi parat se rule B (NO_DATA_WEB) me bhi rissav tha: facet axes ke saath
    tri-state verdict False se **None** ho jaata tha, aur purani shart sirf
    `is False` dekhti thi. Isliye "A blog opinion: consciousness is just
    neuroplasticity vibes" (na peer-review, na ek bhi naap) 0.0 se **0.3122** par
    zinda ho gaya aur average relevance me ginne laga.

Ilaaj do niyam hai, aur ye file dono ko pin karti hai:
  1. Axis chunaav INSAAN ke sawaal se hota hai. Anchor sirf JOD sakta hai (jab
     raw sawaal par koi field-set hi na mile — Hindi/Devanagari sawaal), curated
     axes ki jagah le nahi sakta.
  2. Bina naap wale non-peer-reviewed web page ko sirf SAAF "HAAN, ye sawaal ki
     baat test karta hai" bacha sakta hai — "pata nahi" nahi.

Ulti galti bhi dekhi jaati hai: cross-lingual rescue (#81) girna nahi chahiye,
aur jis web page me naap ya peer-review ya saaf verdict hai wo marna nahi
chahiye.

Offline test: koi network, koi Gemini, koi pytest nahi. Seedha
`python3 tests/test_relevance_anchor_scope.py` chalao.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import evidence_axes as ax                       # noqa: E402
from research_engine import facets as facets_mod                      # noqa: E402
from research_engine import relevance as R                            # noqa: E402
from research_engine.models import SourceRecord, SourceType           # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition: bool, extra: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def _axes(question: str, anchor: str = "") -> tuple:
    """Naya engine, diya hua anchor, aur uske axis id."""
    engine = R.RelevanceEngine()
    engine.set_scoring_anchor(anchor)
    return tuple(a.axis_id for a in engine.axes_of(question))


# ── asli DM-01 prompt (benchmark ka hi text) ────────────────────────────────
# Isme dono cheezein hain jo cascade ke liye zaroori thi: asli sawaal, aur
# instruction-poonchh jisse app ka apna anchor banta hai.
PROMPT = (
    "Dark matter ke baare mein ab tak ka sabse mazboot evidence kya hai — "
    "galaxy rotation curves, gravitational lensing, CMB power spectrum aur "
    "Bullet Cluster observations kya kehte hain, aur kaunse dave abhi confirm "
    "nahi hue? Iske saath Milky Way ke liye local dark matter density ka "
    "calculation dikhao, big bang nucleosynthesis (BBN) aur large scale "
    "structure (LSS) ka evidence bhi lo, dwarf galaxies ka data, direct "
    "detection experiments ke results, primordial black hole (PBH) "
    "constraints, aur MOND ki strengths aur limitations dono likho. "
    "Systematics alag se likho. Rotation curves vs lensing vs CMB ki ek "
    "comparison table banao — evidence strength aur systematics par tulna "
    "karo. Counterevidence alag section mein do. Evidence graph bhi banao. "
    "Kam se kam 3 nayi hypotheses banao, unko alag section mein rakho, novelty "
    "audit karo, har hypothesis ka experiment aur falsification test likho, "
    "honest confidence do, aur sabse aakhir mein exact source aur API "
    "accounting report do."
)

# Us prompt par naapa gaya asli lens scoring anchor (lenses.scoring_query).
CONTRACT_ANCHOR = ("har hypothesis observations calculation limitations "
                   "counterevidence falsification confidence")

# Dusri app-bhasha jo anchor me aa sakti hai — teenon par axis nahi badalna
# chahiye.
OTHER_APP_ANCHORS = (
    "established source-reported inference speculation",
    "novelty audit prediction experiment confidence unknowns",
    "sources api accounting run status partial",
)


def test_the_measured_facet_crossing_is_real() -> None:
    """Pehle wo halat pin karo jisme defect paida hua tha.

    Agar ye check girta hai to matlab prompt/facet ka dhaancha badal gaya hai —
    tab neeche wale axis check jhoothe-hare ho sakte hain, isliye ye sabse pehle
    hai.
    """
    print("\n[1] anchor jodne se facet ginti badhti hai (yahi trigger tha)")
    raw = facets_mod.build(PROMPT)
    expanded = facets_mod.build(PROMPT + " " + CONTRACT_ANCHOR)
    check("raw sawaal ke 3 facet", len(raw) == 3, f"{len(raw)}")
    check("anchor jodne par 4+ facet (threshold paar)", len(expanded) >= 4,
          f"{len(expanded)}")
    check("naya facet anchor ke apne shabdon ka hai",
          any("hypothesis" in (f.label or "") or "confidence" in f.terms
              for f in expanded[len(raw):]),
          str([f.label for f in expanded]))


def test_app_anchor_never_replaces_curated_axes() -> None:
    print("\n[2] app ka anchor curated axes ki jagah nahi le sakta")
    raw = _axes(PROMPT)
    with_anchor = _axes(PROMPT, CONTRACT_ANCHOR)
    check("bina anchor curated dark-matter set mila",
          "rotation_curves" in raw and len(raw) >= 10, str(raw[:4]))
    check("anchor ke saath axis list bilkul wahi rehti hai",
          raw == with_anchor, f"{raw} != {with_anchor}")
    check("keyword-facet axis kabhi mandatory nahi bante",
          not any(a.startswith("facet_") for a in with_anchor),
          str(with_anchor))
    for anchor in OTHER_APP_ANCHORS:
        check(f"app-bhasha anchor axis nahi badalta: {anchor[:28]}",
              _axes(PROMPT, anchor) == raw)


def test_anchor_cannot_switch_the_set_to_another_field() -> None:
    """Anchor doosre field ki vocabulary le aaye to bhi axis set nahi badalta.

    (Domain plan ka apna raasta alag sawaal hai — yahan sirf axis chunaav pin
    hai, kyunki §6 ka `required_axis` isi se aata hai.)
    """
    print("\n[3] anchor ki vocabulary se axis SET nahi badalta")
    question = ("Dark matter ka asli saboot kya hai aur galaxy rotation curves "
                "kya kehti hain?")
    rival = ("superconductivity critical temperature meissner effect cooper "
             "pairs resistivity transition ambient pressure hydride")
    check("raw sawaal ka set dark_matter hai",
          ax.axis_set_for(question)[0] == "dark_matter")
    check("anchor jodne par set superconductivity ban jaata hai (khatra asli hai)",
          ax.axis_set_for(question + " " + rival)[0] == "superconductivity")
    check("phir bhi axis list sawaal wali hi rehti hai",
          _axes(question, rival) == _axes(question),
          str(_axes(question, rival)[:4]))


def test_anchor_can_still_add_for_a_devanagari_question() -> None:
    """#81 ka faayda bachana hai: jahan raw sawaal se kuch nahi milta, wahan
    anchor JOD sakta hai."""
    print("\n[4] Devanagari sawaal par anchor ab bhi curated set laa sakta hai")
    hindi = ("डार्क मैटर के सबूत क्या हैं और घूमती हुई आकाशगंगाओं से "
             "क्या पता चलता है?")
    real_anchor = ("dark matter rotation curves gravitational lensing cosmic "
                   "microwave background")
    bare = _axes(hindi)
    helped = _axes(hindi, real_anchor)
    check("bina anchor sirf generic axes milte hain",
          ax.axis_set_for(hindi)[0] == "generic" and "mechanism" in bare,
          str(bare))
    check("anchor ke saath curated dark-matter axes mil jaate hain",
          "rotation_curves" in helped and len(helped) > len(bare),
          str(helped[:4]))


def test_empty_anchor_is_a_provable_no_op() -> None:
    print("\n[5] anchor khaali ho to axes_of == axes_for(sawaal)")
    for question in (PROMPT,
                     "High temperature superconductivity ka mechanism kya hai?",
                     "Indus valley ke shehron ke patan ka kya saboot hai?"):
        expected = tuple(a.axis_id for a in ax.axes_for(question))
        check(f"no-op: {question[:34]}", _axes(question) == expected)


def test_axes_survive_anchor_changes_and_stay_deterministic() -> None:
    print("\n[6] anchor badalne par cache jhooth nahi bolta")
    engine = R.RelevanceEngine()
    first = tuple(a.axis_id for a in engine.axes_of(PROMPT))
    engine.set_scoring_anchor(CONTRACT_ANCHOR)
    with_anchor = tuple(a.axis_id for a in engine.axes_of(PROMPT))
    engine.set_scoring_anchor("")
    back = tuple(a.axis_id for a in engine.axes_of(PROMPT))
    engine.set_scoring_anchor(CONTRACT_ANCHOR)
    again = tuple(a.axis_id for a in engine.axes_of(PROMPT))
    check("anchor lagne ke baad bhi wahi list", first == with_anchor)
    check("anchor hatane ke baad bhi wahi list", first == back)
    check("dobara lagane par bhi wahi list (deterministic)", again == first)


def _web(title: str, snippet: str, **kw) -> SourceRecord:
    data = dict(title=title, snippet=snippet, url="https://opinion.example.com/x",
                connector="web", source_type=SourceType.WEB, peer_reviewed=False)
    data.update(kw)
    return SourceRecord(**data)


def _score(source: SourceRecord, question: str, anchor: str = "") -> tuple:
    engine = R.RelevanceEngine()
    engine.set_scoring_anchor(anchor)
    value = engine.score_relevance(source, question)
    parts = source.relevance_parts or {}
    return value, parts.get("reject_code")


def test_offtopic_decoy_stays_dead_with_the_anchor_set() -> None:
    """DM-01 ka asli decoy — anchor lage hone par bhi 0.0 par hi rehna chahiye."""
    print("\n[7] exoplanet decoy anchor ke saath bhi evidence nahi banta")
    decoy = SourceRecord(
        title="TESS transit photometry of a warm Neptune orbiting a bright K dwarf",
        url="https://arxiv.org/abs/2101.00001", connector="arxiv",
        source_type=SourceType.PAPER, peer_reviewed=True,
        snippet=("We report the transit detection of a warm Neptune with an "
                 "orbital period of 8.4 days around a bright K dwarf, combining "
                 "TESS photometry with radial velocity follow up to measure a "
                 "planet mass of 21 Earth masses and a radius of 4.2 Earth "
                 "radii."))
    for anchor, tag in (("", "bina anchor"),
                        (CONTRACT_ANCHOR, "anchor ke saath")):
        value, code = _score(decoy, PROMPT, anchor)
        check(f"{tag}: score 0.0", value == 0.0, str(value))
        check(f"{tag}: SUBJECT_MISSING par gira", code == "SUBJECT_MISSING",
              str(code))


DM_Q = ("What is the evidence for dark matter in galaxies and how do rotation "
        "curves and gravitational lensing constrain it?")


def test_unknown_verdict_does_not_rescue_a_number_free_web_page() -> None:
    """Rule B ka asli matlab: 'pata nahi' bachaav nahi hai."""
    print("\n[8] bina naap wala web opinion 'pata nahi' par bhi zinda nahi hota")
    opinion = _web("Dark matter and galaxy rotation: my personal opinion",
                   "Short note, no data.")
    engine = R.RelevanceEngine()
    verdict = engine.proposition_check(opinion, DM_Q)["tests_proposition"]
    check("iska proposition verdict sach me tri-state None hai",
          verdict is None, str(verdict))
    value, code = _score(opinion, DM_Q)
    check("score 0.0", value == 0.0, str(value))
    check("NO_DATA_WEB par gira", code == "NO_DATA_WEB", str(code))


def test_pages_that_earn_their_place_are_not_touched() -> None:
    """Ulti galti: rule B jaayaz page nahi maar sakta."""
    print("\n[9] naap / peer-review / saaf verdict — teenon bachaate hain")
    measured = _web("Dark matter and galaxy rotation: measured survey results",
                    "Short note, we found 220 km/s.")
    value, code = _score(measured, DM_Q)
    check("ek naap hone par bacha", value > 0.0 and code is None,
          f"{value} {code}")

    peer = _web("Dark matter and galaxy rotation: my personal opinion",
                "Short note, no data.", peer_reviewed=True)
    value, code = _score(peer, DM_Q)
    check("peer-reviewed hone par bacha", value > 0.0 and code is None,
          f"{value} {code}")

    explainer = _web(
        "Dark matter in galaxies: how flat rotation curves explain the missing mass",
        ("This explainer describes the mechanism by which unseen mass causes "
         "flat rotation curves in spiral galaxies, and concludes that lensing "
         "observations point the same way."))
    engine = R.RelevanceEngine()
    verdict = engine.proposition_check(explainer, DM_Q)["tests_proposition"]
    value, code = _score(explainer, DM_Q)
    check("saaf 'HAAN' verdict hai", verdict is True, str(verdict))
    check("bina number wala explainer bhi saaf HAAN par bacha",
          value > 0.0 and code is None, f"{value} {code}")


def test_reject_reason_is_written_in_plain_words() -> None:
    """User ko code nahi, wajah dikhni chahiye."""
    print("\n[10] gire hue source ki wajah insaani bhasha me hai")
    opinion = _web("Dark matter and galaxy rotation: my personal opinion",
                   "Short note, no data.")
    engine = R.RelevanceEngine()
    engine.score_relevance(opinion, DM_Q)
    parts = opinion.relevance_parts or {}
    rows = parts.get("rejections") or []
    why = (rows[0].get("why") if rows else "") or ""
    detail = (rows[0].get("detail") if rows else "") or ""
    check("rejection ka record bana", len(rows) == 1, str(rows))
    check("code ke saath 'why' bhi hai", len(why) > 20, why)
    check("detail me 'evidence nahi, raay hai' likha hai",
          "raay" in detail, detail)
    check("traceback / exception text nahi hai",
          "Traceback" not in detail and "Error" not in detail, detail)


def test_anchor_cannot_switch_the_domain_plan() -> None:
    """Axis ke saath FIELD ka faisla bhi insaan ke sawaal se hona chahiye.

    Naapa hua rissav (2026-08-25): `plan_of` bhi `expanded_query` se jaata tha,
    isliye anchor me doosre field ki vocabulary aane par poora domain badal
    jaata tha — asli rotation-curve paper `DOMAIN_MISMATCH` par 0.7224 se **0.0**
    gir gaya tha, aur superconductivity ka paper 0.5362 par bach gaya tha.
    """
    print("\n[11] anchor field (domain plan) nahi badal sakta")
    question = ("Dark matter ka asli saboot kya hai aur galaxy rotation curves "
                "kya kehti hain?")
    rival = ("superconductivity critical temperature meissner effect cooper "
             "pairs resistivity transition ambient pressure hydride")
    real = SourceRecord(
        title="Flat rotation curves of 175 spiral galaxies imply a dark matter halo",
        url="https://arxiv.org/abs/2101.00002", connector="arxiv",
        source_type=SourceType.PAPER, peer_reviewed=True,
        snippet=("We measure rotation velocities of 220 km/s at 20 kpc in 175 "
                 "spiral galaxies and find the mass discrepancy grows with "
                 "radius."))
    decoy = SourceRecord(
        title=("Resistivity transition and Meissner effect in a hydride "
               "superconductor at 250 K"),
        url="https://arxiv.org/abs/2101.00003", connector="arxiv",
        source_type=SourceType.PAPER, peer_reviewed=True,
        snippet=("We report a critical temperature of 250 K under 170 GPa with "
                 "a sharp resistivity drop."))

    engine = R.RelevanceEngine()
    engine.set_scoring_anchor(rival)
    check("rival anchor ke saath bhi field sawaal wala hi rehta hai",
          engine.plan_of(question).key == R.RelevanceEngine().plan_of(question).key,
          engine.plan_of(question).key)
    value, code = _score(real, question, rival)
    check("asli rotation-curve paper zinda rehta hai",
          value > 0.5 and code is None, f"{value} {code}")
    value, code = _score(decoy, question, rival)
    check("doosre field ka paper anchor ke bal par nahi ghusta",
          value == 0.0 and code == "DOMAIN_MISMATCH", f"{value} {code}")


def test_anchor_still_gives_a_devanagari_question_its_field() -> None:
    print("\n[12] Devanagari sawaal ko anchor ab bhi field de sakta hai")
    hindi = ("डार्क मैटर के सबूत क्या हैं और घूमती हुई आकाशगंगाओं से "
             "क्या पता चलता है?")
    engine = R.RelevanceEngine()
    check("bina anchor koi field profile match nahi hota",
          engine.plan_of(hindi).is_known is False, engine.plan_of(hindi).key)
    helped = R.RelevanceEngine()
    helped.set_scoring_anchor("dark matter rotation curves gravitational lensing")
    plan = helped.plan_of(hindi)
    check("anchor ke saath field mil jaata hai", plan.is_known is True, plan.key)
    check("rescue ke baad bhi plan ka sawaal insaan ka hi hai",
          plan.question == hindi, plan.question[:60])


def test_app_words_never_become_the_search_query() -> None:
    """`DomainPlan.question` aage seedha search query banta hai (unknown field
    par `search_intents()` usi ko query bana deta hai). Isliye anchor ke shabd
    plan ke sawaal me nahi ghus sakte — warna live wali `all:"har hypothesis"` /
    `all:"source-reported"` jaisi junk query banti hai."""
    print("\n[13] app ke contract shabd search query nahi ban sakte")
    hindi = ("डार्क मैटर के सबूत क्या हैं और घूमती हुई आकाशगंगाओं से "
             "क्या पता चलता है?")
    for question, tag in ((hindi, "Devanagari (field unknown)"),
                          (PROMPT, "asli DM prompt")):
        engine = R.RelevanceEngine()
        engine.set_scoring_anchor(CONTRACT_ANCHOR)
        plan = engine.plan_of(question)
        check(f"{tag}: plan ka sawaal insaan ka hai",
              plan.question == question, plan.question[-70:])
        queries = " ".join(str(i.get("query") or "")
                           for i in plan.search_intents()).lower()
        bad = [w for w in ("hypothesis", "falsification", "counterevidence",
                           "confidence", "limitations") if w in queries]
        check(f"{tag}: search query me contract shabd nahi", not bad,
              f"{bad} | {queries[:90]}")


def main() -> int:
    print("=" * 70)
    print("ANCHOR SCOPE — app ke shabd research target nahi bante")
    print("=" * 70)
    test_the_measured_facet_crossing_is_real()
    test_app_anchor_never_replaces_curated_axes()
    test_anchor_cannot_switch_the_set_to_another_field()
    test_anchor_can_still_add_for_a_devanagari_question()
    test_empty_anchor_is_a_provable_no_op()
    test_axes_survive_anchor_changes_and_stay_deterministic()
    test_offtopic_decoy_stays_dead_with_the_anchor_set()
    test_unknown_verdict_does_not_rescue_a_number_free_web_page()
    test_pages_that_earn_their_place_are_not_touched()
    test_reject_reason_is_written_in_plain_words()
    test_anchor_cannot_switch_the_domain_plan()
    test_anchor_still_gives_a_devanagari_question_its_field()
    test_app_words_never_become_the_search_query()
    print("\n" + "=" * 70)
    print(f"PASS: {PASS}   FAIL: {FAIL}")
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
