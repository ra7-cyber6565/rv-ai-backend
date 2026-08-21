"""
point 12 — maths/physics sanity checks ka regression test.

Ye teen tarah ki galtiyan pakadta hai jo pehle chupchaap nikal jaati thi:

    1. physical limit todna — "-15 K par superconducting", "efficiency 140%".
    2. unit conversion galat — "250 K (23 °C)" (asli mein -23.15 °C).
    3. tulna ulti — "250 K, jo 30 °C se zyada hai" (250 K = -23 °C, yaani kam).

Saath hi ye bhi jaancha jaata hai ki non-quantitative sawal par ye poora check
CHUP rehta hai (warna har jawab ke neeche bekaar physics warning lagti).

Offline: koi network, koi API key, koi pytest.
`python3 tests/test_physics_sanity.py`
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import physics_checks as P                  # noqa: E402
from research_engine.models import (EvidencePack,                # noqa: E402
                                    SourceRecord, SourceType)
from research_engine.verification import VerificationEngine      # noqa: E402

PASSED = 0
FAILED = 0
TC_Q = "kya room temperature superconductor ka Tc kitna hai?"


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name}" + (f" — {extra}" if extra else ""))


def eq(name: str, got, want) -> None:
    check(name, got == want, f"mila {got!r}, chahiye {want!r}")


def named(result: dict, name: str) -> dict:
    """Result ke checks mein se ek check nikaalo (naam se)."""
    for c in result.get("checks", []):
        if c.get("check") == name:
            return c
    return {}


def pack() -> EvidencePack:
    return EvidencePack(sources=[SourceRecord(
        title="High-Tc hydride under pressure", url="http://s1",
        snippet="Tc 250 K at 170 GPa reported.", source_type=SourceType.PAPER,
        read_level="full_text", full_text_chars=40000, relevance_score=0.8,
        quality_score=0.6, source_id="S1")])


# ── parsing ──────────────────────────────────────────────────────────────────
def test_quantities_are_parsed_with_units():
    print("\nparsing — number + unit theek se nikalta hai")
    q = P.parse_quantities("Tc 250 K, pressure 170 GPa, distance 1.2 nm.")
    eq("teen quantity mili", len(q), 3)
    eq("pehli temperature hai", q[0].dimension, "temperature")
    eq("aur SI mein 250 K", round(q[0].si or 0, 2), 250.0)
    eq("doosri pressure hai", q[1].dimension, "pressure")
    eq("170 GPa = 1.7e11 Pa", q[1].si, 1.7e11)
    eq("teesri length hai", q[2].dimension, "length")

    c = P.parse_quantities("Temperature -23.15 °C tak gira.")
    eq("celsius bhi mila", len(c), 1)
    eq("aur K mein convert hua", round(c[0].si or 0, 2), 250.0)

    sci = P.parse_quantities("Pressure 1.7e6 bar tha.")
    eq("scientific notation ek hi number ki tarah padha gaya", len(sci), 1)
    eq("aur value 1.7e6 bar hai", sci[0].value, 1.7e6)

    junk = P.parse_quantities("Isme 5 papers aur 3 datasets the.")
    eq("bina unit ke number quantity nahi maane gaye", len(junk), 0)


def test_is_quantitative_gate():
    print("\ngate — sirf numbers wale sawal par check chale")
    check("kitna wala sawal quantitative hai",
          P.is_quantitative("Tc kitna hota hai?"))
    check("unit wala sawal quantitative hai",
          P.is_quantitative("kya 250 K par superconductivity possible hai?"))
    check("efficiency wala sawal quantitative hai",
          P.is_quantitative("solar panel ki efficiency kya hai?"))
    check("philosophy wala sawal quantitative nahi",
          not P.is_quantitative("kya consciousness sirf dimaag hai?"))
    check("jawab mein 3+ units ho to phir bhi chal jaata hai",
          P.is_quantitative("aisa kyun hota hai?",
                            "250 K, 170 GPa aur 1.2 nm par ye dikha."))


# ── physical limits ──────────────────────────────────────────────────────────
def test_absolute_zero_and_negative_quantities():
    print("\nlimits — 0 K se neeche, negative lambai/pressure")
    r = P.run("Superconducting transition -15 K par dekhi gayi.", TC_Q)
    lim = named(r, "physical limits")
    eq("absolute zero se neeche fail hai", lim.get("passed"), False)
    check("aur detail mein absolute zero ka naam hai",
          "absolute zero" in lim.get("detail", ""), lim.get("detail", ""))
    eq("poora run bhi fail ginta hai", r["failed"] >= 1, True)

    ok = P.run("Sample -23 °C (250 K) par kaam karta hai.", TC_Q)
    eq("-23 °C bilkul valid hai (0 K se upar)",
       named(ok, "physical limits").get("passed"), True)

    neg = P.run("Film ki thickness -12 nm batayi gayi.", "thickness kitni hai?")
    eq("negative lambai fail hai",
       named(neg, "physical limits").get("passed"), False)

    negp = P.run("Pressure -170 GPa par test hua.", "kitna pressure?")
    eq("negative pressure fail hai",
       named(negp, "physical limits").get("passed"), False)


def test_percent_and_light_speed_limits():
    print("\nlimits — 100% ki chhat aur light speed")
    bad = P.run("Is cell ki efficiency 140% tak jaati hai.",
                "efficiency kitni hai?")
    eq("140% efficiency fail hai",
       named(bad, "physical limits").get("passed"), False)
    check("warning mein 100% ki baat hai",
          any("100%" in w for w in bad["warnings"]), str(bad["warnings"]))

    fine = P.run("Is cell ki efficiency 26% hai, cost 40% kam hai.",
                 "efficiency kitni hai?")
    eq("normal percentage theek hai",
       named(fine, "physical limits").get("passed"), True)

    grow = P.run("Market 250% badha aur demand 300% badhi.",
                 "kitna growth hua?")
    eq("efficiency ke bahar 100%+ ko galat nahi kaha gaya",
       named(grow, "physical limits").get("passed"), True)

    fast = P.run("Signal 400000 km/s ki speed se gaya.", "speed kitni thi?")
    eq("light speed se zyada fail hai",
       named(fast, "physical limits").get("passed"), False)


def test_superconductivity_domain_range():
    print("\nlimits — superconductivity ka apna range")
    r = P.run("Superconductivity 5000 K par report hui.", TC_Q)
    sc = named(r, "superconductivity range")
    eq("5000 K ka Tc claim fail hai", sc.get("passed"), False)
    check("detail mein reported range ka zikr hai",
          "250" in sc.get("detail", ""), sc.get("detail", ""))

    ok = P.run("Superconductivity 250 K par 170 GPa mein mili [S1].", TC_Q)
    eq("250 K / 170 GPa range ke andar hai",
       named(ok, "superconductivity range").get("passed"), True)

    other = P.run("Solar panel ki efficiency 26% hai.", "efficiency kitni?")
    eq("non-superconductivity jawab par ye check hi nahi lagta",
       named(other, "superconductivity range"), {})

    nonum = P.run("Superconductivity par bahut kaam ho raha hai, 5 papers mile.",
                  TC_Q)
    check("number na ho to check 'ho hi nahi saka' rehta hai (fail nahi)",
          named(nonum, "superconductivity range").get("passed", "missing")
          in (None, "missing"),
          str(named(nonum, "superconductivity range")))


def test_unit_conversion():
    print("\nconversion — ek hi value do units mein")
    good = P.run("Tc 250 K (-23.15 °C) par mila [S1].", TC_Q)
    eq("sahi conversion pass hai",
       named(good, "unit conversion").get("passed"), True)

    rounded = P.run("Tc 250 K (-23 °C) par mila [S1].", TC_Q)
    eq("thoda round-off (0.15 K) bhi pass hai",
       named(rounded, "unit conversion").get("passed"), True)

    bad = P.run("Tc 250 K (23 °C) par mila [S1].", TC_Q)
    conv = named(bad, "unit conversion")
    eq("galat conversion fail hai", conv.get("passed"), False)
    check("detail mein dono value likhi hain",
          "250 K" in conv.get("detail", "") and "23 °C" in conv.get("detail", ""),
          conv.get("detail", ""))

    pressure = P.run("Pressure 170 GPa (1700000 bar) tha.", "kitna pressure?")
    eq("GPa→bar sahi conversion pass hai",
       named(pressure, "unit conversion").get("passed"), True)

    wrong_p = P.run("Pressure 170 GPa (1.7e7 bar) tha.", "kitna pressure?")
    eq("GPa→bar mein 10x ki galti pakdi gayi",
       named(wrong_p, "unit conversion").get("passed"), False)

    none = P.run("Tc 250 K par mila [S1].", TC_Q)
    eq("mauka na mile to check None rehta hai (fail nahi)",
       named(none, "unit conversion").get("passed"), None)


def test_comparison_direction():
    print("\ntulna — unit convert karke bhi sahi hai ya nahi")
    bad = P.run("Ye material 250 K par kaam karta hai, jo 30 °C se zyada hai.",
                TC_Q)
    comp = named(bad, "comparison direction")
    eq("ulti tulna fail hai", comp.get("passed"), False)
    check("detail mein palta hua rishta likha hai",
          "<" in comp.get("detail", ""), comp.get("detail", ""))

    good = P.run("Ye material 300 K par chalta hai, jo 10 °C se zyada hai.",
                 TC_Q)
    eq("sahi tulna pass hai",
       named(good, "comparison direction").get("passed"), True)

    eng = P.run("Tc 250 K is higher than 77 K of liquid nitrogen.", TC_Q)
    eq("english comparison bhi chalta hai",
       named(eng, "comparison direction").get("passed"), True)

    eng_bad = P.run("Tc 60 K is higher than 77 K of liquid nitrogen.", TC_Q)
    eq("english mein ulti tulna fail hai",
       named(eng_bad, "comparison direction").get("passed"), False)

    none = P.run("Tc 250 K par mila aur pressure 170 GPa tha.", TC_Q)
    eq("tulna hi na ho to check None rehta hai",
       named(none, "comparison direction").get("passed"), None)


def test_non_quantitative_question_stays_silent():
    print("\nchup rehna — non-quantitative sawal par koi physics shor nahi")
    r = P.run("Ye ek philosophy ka sawal hai, iska seedha jawab nahi.",
              "kya consciousness sirf dimaag hai?")
    eq("applicable False hai", r["applicable"], False)
    eq("koi check nahi chala", r["checks"], [])
    eq("koi warning nahi", r["warnings"], [])
    check("wajah insaani bhasha mein likhi hai",
          "numbers/units ka nahi" in r["note"], r["note"])


def test_failure_warning_is_human_and_clear():
    print("\nwarning — insaani bhasha, aur 'verified mat maano'")
    r = P.run("Tc 250 K (23 °C) par mila, efficiency 140% thi.", TC_Q)
    joined = " | ".join(r["warnings"])
    check("warning mein sanity check ka naam hai",
          "sanity check fail" in joined, joined)
    check("aur saaf mana kiya gaya hai ki ise verified maanein",
          "verified mat maanein" in joined, joined)
    for token in ("Traceback", "None", "{", "}", "ValueError"):
        check(f"warning mein '{token}' jaisa raw text nahi",
              token not in joined, joined)


def test_verification_engine_wiring():
    print("\nVerificationEngine — physics checks report mein pahunchte hain")
    v = VerificationEngine()
    p = pack()

    bad = v.verify("Tc 250 K (23 °C) par mila [S1].", p, question=TC_Q).to_dict()
    check("physics block report mein hai", bool(bad.get("physics")), str(bad.keys()))
    eq("aur applicable hai", bad["physics"]["applicable"], True)
    names = [c["check"] for c in bad["checks"]]
    check("unit conversion check checks list mein juda", "unit conversion" in names,
          str(names))
    eq("status numeric galti bata raha hai", bad["status"], "MATH ERROR FOUND")
    check("warning bhi report ke warnings mein aayi",
          any("sanity check fail" in w for w in bad["warnings"]),
          str(bad["warnings"]))

    good = v.verify("Tc 250 K (-23.15 °C) par mila [S1].", p, question=TC_Q).to_dict()
    check("sahi jawab par status MATH ERROR nahi hai",
          good["status"] != "MATH ERROR FOUND", good["status"])
    check("aur koi physics warning nahi",
          not [w for w in good["warnings"] if "sanity check fail" in w],
          str(good["warnings"]))

    plain = v.verify("Is topic par sources abhi kam hain [S1].", p,
                     question="kya consciousness sirf dimaag hai?").to_dict()
    eq("non-quantitative sawal par applicable False",
       plain["physics"]["applicable"], False)

    old = v.verify("Tc 250 K par mila [S1].", p).to_dict()
    check("question na do to bhi crash nahi hota (purana call site safe hai)",
          "physics" in old, str(old.keys()))


def test_report_renders_physics_in_hinglish():
    print("\nreport — sanity check user ki bhasha mein dikhta hai")
    from research_engine.synthesizer import FinalSynthesizer

    v = VerificationEngine()
    synth = FinalSynthesizer()
    bad = v.verify("Tc 250 K (23 °C) par mila [S1].", pack(),
                   question=TC_Q).to_dict()
    text = synth._numbers_check(bad)
    check("problem wali line insaani bhasha mein hai",
          "Ek hi value do units mein alag-alag likhi gayi hai" in text, text[:400])
    check("sanity check ka summary bhi chhapta hai",
          "Maths/physics sanity check:" in text, text[-400:])
    for token in ("passed", "True", "False", "{", "}", "None"):
        check(f"report mein raw '{token}' leak nahi hua", token not in text,
              text[:200])

    quiet = synth._numbers_check(
        v.verify("Is topic par kaam kam hai [S1].", pack(),
                 question="kya consciousness sirf dimaag hai?").to_dict())
    check("non-quantitative sawal par sanity ka section hi nahi aata",
          "Maths/physics sanity check:" not in quiet, quiet[:200])


def test_module_is_zero_cost_and_deterministic():
    print("\n₹0 rule — sab local, aur do baar chalao to wahi jawab")
    import inspect

    source = inspect.getsource(P)
    for token in ("requests.", "httpx", "urlopen", "genai", "openai",
                  "api_key", "http://", "https://", "import random", "random.",
                  "time.time"):
        check(f"module mein '{token}' nahi hai", token not in source)

    answer = "Tc 250 K (23 °C) par mila, jo 30 °C se zyada hai."
    a = P.run(answer, TC_Q)
    b = P.run(answer, TC_Q)
    eq("dono run ka jawab bilkul same", a, b)


def main() -> int:
    print("=" * 68)
    print("point 12 — maths/physics sanity checks")
    print("=" * 68)
    test_quantities_are_parsed_with_units()
    test_is_quantitative_gate()
    test_absolute_zero_and_negative_quantities()
    test_percent_and_light_speed_limits()
    test_superconductivity_domain_range()
    test_unit_conversion()
    test_comparison_direction()
    test_non_quantitative_question_stays_silent()
    test_failure_warning_is_human_and_clear()
    test_verification_engine_wiring()
    test_report_renders_physics_in_hinglish()
    test_module_is_zero_cost_and_deterministic()
    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
