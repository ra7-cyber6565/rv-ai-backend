"""
EVIDENCE-AXIS GUARD ka test — "ek shabd se poora curated set nahi milta", aur
"app ki apni label-bhasha research target nahi hoti".

Asli failure jo ye file pakadti hai (2026-08-25, intel ke 819-word human-agency
mega-question ka LIVE run):

  * Sawaal me `cosmology` shabd EK baar aaya tha — wo bhi lens-list ke andar
    ("quantum mechanics, 'frequency/vibration' claims and cosmology"). Purana
    `axis_set_for` (`best_hits = 0`, `hits > best_hits`) us EK hit par poora
    15-axis `dark_matter` set de deta tha. Naapa gaya nateeja: 18 axes me 17
    MISSING, queries jaise `all:"dark matter" AND all:"attention" AND
    all:"recoil"`, relevance gate ne 305 source `required_axis` par reject kiye,
    bache 40 source (copula preprints, earthquake ground motion, LNG terminal,
    LiDAR), avg relevance 0.46 < 0.65 floor → contract fail → PARTIAL. Yaani
    PARTIAL literature ki kami nahi, is misroute ka nateeja tha.

  * Aur galat curated set milne par `axes_for` generic `mechanism`/`quantitative`
    axes bhi hata deta tha — theek wahi do axes jo asli sawaal par fit hote.

  * Uske ALL-CAPS label vocabulary (ESTABLISHED, SOURCE-REPORTED, INFERENCE,
    SPECULATION) aur pabandi wale shabd (RAM, DRM) MANDATORY evidence axis ban
    gaye, aur audit me user ko jhoothi shortfall dikhi: "12 naam se maange gaye
    target → 10/12 par kaam hua — in par kuch nahi mila: SPECULATION, DRM".

Ye file dono halat pakadti hai AUR ulti galti bhi: asli dark-matter /
superconductivity sawaal ka set girna nahi chahiye, aur `CIA` jaisa asli naam
filter nahi hona chahiye.

Offline test: koi network, koi Gemini, koi pytest nahi. Seedha
`python3 tests/test_evidence_axis_guard.py` chalao.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import evidence_axes as ax                       # noqa: E402

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


# intel ke asli sawaal ka chhota par wafadaar roop: multi-domain, lamba, aur
# `cosmology` sirf EK baar — lens-list ke andar.
MEGA = (
    "Next 20 years me main apni truth-seeking capacity aur personal agency ko "
    "maximize karna chahta hun. Is par poori deep research karo aur har lens se "
    "dekho: cognitive science of attention and memory, neuroplasticity and skill "
    "acquisition, attention residue and context switching, decision theory and "
    "game theory, Jungian depth psychology and individuation, Hermeticism and the "
    "esoteric traditions, comparative mysticism, sociology of institutions, "
    "history of secret societies and Freemasonry, declassified intelligence "
    "programs including CIA remote viewing, propaganda and information warfare, "
    "media theory, behavioural economics and incentive design, network effects, "
    "power laws, complexity science, second-order effects, systems thinking, "
    "mental models, geopolitical realism and great-power competition, quantum "
    "mechanics, \"frequency/vibration\" claims and cosmology. Biology shapes "
    "environment, environment shapes culture, culture shapes language, language "
    "shapes attention, attention shapes beliefs, beliefs shape action. Is chain "
    "ko explicitly trace karo. Label everything: ESTABLISHED, SOURCE-REPORTED, "
    "INFERENCE, SPECULATION. Har claim par evidence span do. Agar RAM ya timeout "
    "ki dikkat ho to bata do, adhoora jawab poora mat kehna. DRM ya paywall "
    "bypass mat karna."
)

# Asli dark-matter sawaal — 4 alag trigger. Ye girna NAHI chahiye.
REAL_DM = ("dark matter ke saboot par deep research karo — rotation curves, CMB, "
           "BBN, Bullet Cluster, lensing, MOND aur primordial black holes")

# Chhota sawaal, ek hi trigger — yahan ek hit KAAFI hai.
SHORT_DM = "dark matter ka saboot kya hai?"

# Asli superconductivity sawaal — 2 trigger.
REAL_SC = "LK-99 ka critical temperature kitna hai aur replication hui ya nahi?"

# Wahi label-bhasha Title Case me likhi hui — app ke multi-word label
# ("STRONG EVIDENCE", "SOURCE REPORTED", "MIXED EVIDENCE", "ESTABLISHED FACT")
# proper-pair ban kar bhi target nahi bane. Yahan koi pabandi wala vaakya nahi
# hai, isliye sirf label-vocabulary hi inhe rok sakti hai.
TITLE_CASE_LABELS = (
    "Dark matter par research karo. Har claim par Strong Evidence ya Source "
    "Reported label lagao, Mixed Evidence aur Established Fact bhi alag rakho. "
    "Bullet Cluster ka data zaroor dekho."
)


def test_one_incidental_word_does_not_win_a_curated_set() -> None:
    """Lambe sawaal me ek akela trigger poora 15-axis set nahi jitata."""
    verdict = ax.axis_set_verdict(MEGA)
    check("mega-question me 'cosmology' ka sirf 1 hit naapa gaya",
          verdict["hits"] == 1, str(verdict["hits"]))
    check("matched trigger naam se likha gaya hai (audit padh sakta hai)",
          verdict["matched_triggers"] == ["cosmology"],
          str(verdict["matched_triggers"]))
    check("set generic hai, dark_matter nahi", verdict["set"] == "generic",
          str(verdict["set"]))
    check("demote hone ka flag lagta hai", verdict.get("demoted") is True)
    check("reason me token ginti aur nishaan dono hain",
          "202" in str(verdict["reason"]) or str(verdict["tokens"]) in str(verdict["reason"]),
          str(verdict["reason"]))
    ids = [a.axis_id for a in ax.axes_for(MEGA)]
    check("ek bhi dark-matter axis nahi aaya",
          not any(i in ids for i in ("rotation_curves", "cmb", "bbn", "lensing",
                                     "bullet_cluster", "direct_detection")), str(ids))


def test_demoted_question_gets_its_generic_axes_back() -> None:
    """
    Doosra aadha defect: galat curated set milne par mechanism/quantitative hat
    jaate the. Generic par girne ka poora faayda tab hi hai jab ye wapas aayein.
    """
    ids = [a.axis_id for a in ax.axes_for(MEGA)]
    for axis_id in ("mechanism", "quantitative", "replication", "counter_evidence"):
        check(f"'{axis_id}' axis wapas aaya", axis_id in ids, str(ids))
    check("axis set itna chhota hai ki poora ho sakta hai (<= 8)",
          len(ids) <= 8, str(len(ids)))


def test_real_field_question_keeps_its_curated_set() -> None:
    """Ulti galti: asli field sawaal generic par girna nahi chahiye."""
    dm = ax.axis_set_verdict(REAL_DM)
    check("asli dark-matter sawaal par set dark_matter hi hai",
          dm["set"] == "dark_matter", str(dm["set"]))
    check("uske 2 se zyada nishaan mile", int(dm["hits"]) >= 2, str(dm["hits"]))
    check("demote nahi hua", not dm.get("demoted"))
    ids = [a.axis_id for a in ax.axes_for(REAL_DM)]
    for axis_id in ("rotation_curves", "cmb", "bbn", "lensing", "bullet_cluster"):
        check(f"dark-matter axis '{axis_id}' maujood hai", axis_id in ids)

    sc = ax.axis_set_verdict(REAL_SC)
    check("asli superconductivity sawaal par set superconductivity hai",
          sc["set"] == "superconductivity", str(sc["set"]))


def test_short_question_still_wins_on_a_single_hit() -> None:
    """Chhote sawaal me ek shabd hi poora topic hota hai — wahan guard chup rahe."""
    verdict = ax.axis_set_verdict(SHORT_DM)
    check("chhota sawaal 40 token se kam hai",
          int(verdict["tokens"]) < ax._INCIDENTAL_SET_MIN_TOKENS,
          str(verdict["tokens"]))
    check("ek hit par bhi dark_matter set milta hai",
          verdict["set"] == "dark_matter" and verdict["hits"] == 1,
          f"{verdict['set']}/{verdict['hits']}")
    check("demote nahi hua", not verdict.get("demoted"))


def test_thresholds_are_pinned() -> None:
    """
    Ye do number hi poora faisla chalate hain. Inhe chupke se badal dena
    behaviour badal dega, isliye test me pin hain.
    """
    check("ek se zyada nishaan chahiye (_MIN_SET_SIGNALS == 2)",
          ax._MIN_SET_SIGNALS == 2, str(ax._MIN_SET_SIGNALS))
    check("40 token se chhota sawaal guard se achhoota hai",
          ax._INCIDENTAL_SET_MIN_TOKENS == 40,
          str(ax._INCIDENTAL_SET_MIN_TOKENS))


def test_app_label_vocabulary_is_never_a_research_target() -> None:
    """ESTABLISHED / SOURCE-REPORTED / INFERENCE / SPECULATION naam nahi hain."""
    names = ax.named_entities(MEGA)
    upper = {n.upper() for n in names}
    for word in ("ESTABLISHED", "SOURCE-REPORTED", "INFERENCE", "SPECULATION"):
        check(f"'{word}' entity nahi bana", word not in upper, str(names))
    ids = [a.axis_id for a in ax.axes_for(MEGA)]
    for axis_id in ("named_established", "named_inference", "named_speculation",
                    "named_source_reported"):
        check(f"'{axis_id}' axis nahi bana", axis_id not in ids, str(ids))

    # Title Case me likhe multi-word label bhi target nahi bante — aur is
    # sawaal me koi pabandi nahi hai, to sirf label-vocabulary hi rok sakti hai.
    pairs = ax.named_entities(TITLE_CASE_LABELS)
    for pair in ("Strong Evidence", "Source Reported", "Mixed Evidence",
                 "Established Fact"):
        check(f"'{pair}' (Title Case label) entity nahi bana",
              pair not in pairs, str(pairs))
    check("usi sawaal me asli naam 'Bullet Cluster' bacha",
          "Bullet Cluster" in pairs, str(pairs))
    check("Title Case sawaal me koi pabandi-vaakya nahi tha (filter label se hua)",
          ax._constraint_sentences(TITLE_CASE_LABELS) == [],
          str(ax._constraint_sentences(TITLE_CASE_LABELS)))


def test_label_vocabulary_is_derived_not_hand_typed() -> None:
    """
    Naya claim label jodne par ye parat KHUD badhni chahiye — warna kal ka label
    phir se jhoothi shortfall banayega.
    """
    from research_engine import models
    ax._LABEL_VOCAB_CACHE = None
    models._LABEL_TO_CLAIM["ZZTESTLABEL"] = models.ClaimType.UNKNOWN
    try:
        ax._LABEL_VOCAB_CACHE = None
        vocab = ax._derived_label_vocab()
        check("naya label bina evidence_axes.py badle vocabulary me aa gaya",
              "ZZTESTLABEL" in vocab)
        check("naya label entity nahi banta",
              "ZZTESTLABEL" not in {n.upper() for n in
                                    ax.named_entities("ZZTESTLABEL par saboot do")})
    finally:
        models._LABEL_TO_CLAIM.pop("ZZTESTLABEL", None)
        ax._LABEL_VOCAB_CACHE = None
    check("purani vocabulary me test ka label bacha nahi",
          "ZZTESTLABEL" not in ax._derived_label_vocab())


def test_words_the_user_forbade_are_constraints_not_targets() -> None:
    """"DRM ya paywall bypass mat karna" — DRM pabandi hai, target nahi."""
    names = {n.upper() for n in ax.named_entities(MEGA)}
    check("'DRM' entity nahi bana", "DRM" not in names, str(sorted(names)))
    check("'RAM' entity nahi bana", "RAM" not in names, str(sorted(names)))
    check("pabandi wale vaakya pehchane gaye",
          len(ax._constraint_sentences(MEGA)) >= 2,
          str(ax._constraint_sentences(MEGA)))
    solo = ax.named_entities("VPN mat use karna, GPU par hi chalao")
    check("kal ka naya pabandi-shabd bhi filter hota hai (list nahi, vyakaran)",
          "VPN" not in {n.upper() for n in solo}, str(solo))


def test_a_genuinely_asked_name_survives() -> None:
    """
    Over-filtering ka test: CIA uske sawaal me asli target hai (declassified
    programs), koi label nahi aur koi mana nahi. Wo girna nahi chahiye.
    """
    names = {n.upper() for n in ax.named_entities(MEGA)}
    check("'CIA' entity bacha", "CIA" in names, str(sorted(names)))
    ids = [a.axis_id for a in ax.axes_for(MEGA)]
    check("'named_cia' axis bana", "named_cia" in ids, str(ids))
    named = ax.named_entities("XENONnT aur LZ ke data se dark matter direct "
                              "detection par research karo, Bullet Cluster bhi dekho")
    check("XENONnT jaisa asli instrument bacha", "XENONnT" in named, str(named))
    check("Bullet Cluster jaisa proper pair bacha", "Bullet Cluster" in named,
          str(named))


def test_everything_is_deterministic() -> None:
    """Ek hi sawaal, do baar — bilkul wahi nateeja (koi API call nahi)."""
    first = (ax.axis_set_verdict(MEGA)["set"],
             tuple(a.axis_id for a in ax.axes_for(MEGA)),
             tuple(ax.named_entities(MEGA)))
    second = (ax.axis_set_verdict(MEGA)["set"],
              tuple(a.axis_id for a in ax.axes_for(MEGA)),
              tuple(ax.named_entities(MEGA)))
    check("dono run ek jaise", first == second, f"{first} != {second}")


def main() -> int:
    print("=" * 70)
    print("EVIDENCE-AXIS GUARD — ek shabd se set nahi, label se target nahi")
    print("=" * 70)
    test_one_incidental_word_does_not_win_a_curated_set()
    test_demoted_question_gets_its_generic_axes_back()
    test_real_field_question_keeps_its_curated_set()
    test_short_question_still_wins_on_a_single_hit()
    test_thresholds_are_pinned()
    test_app_label_vocabulary_is_never_a_research_target()
    test_label_vocabulary_is_derived_not_hand_typed()
    test_words_the_user_forbade_are_constraints_not_targets()
    test_a_genuinely_asked_name_survives()
    test_everything_is_deterministic()
    print("\n" + "=" * 70)
    print(f"PASS: {PASS}   FAIL: {FAIL}")
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
