"""
§17 ka test — CALCULATION RECORDS + SANITY CHECKS.

Sabse badi baat jo ye file pakadti hai: dark-matter report mein likha tha
"numeric sanity check kiya gaya", jabki koi hisaab hi nahi tha. Ab aisa text
ZERO records deta hai — daava apne aap check nahi ban jaata.

Offline test: koi network, koi Gemini, koi pytest nahi. Seedha
`python3 tests/test_calculation_records.py` chalao.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import physics_checks as pc                    # noqa: E402
from research_engine import quality_producers as qp                 # noqa: E402
from research_engine.models import EvidencePack, SourceRecord, SourceType  # noqa: E402
from research_engine.synthesizer import FinalSynthesizer             # noqa: E402

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


# ── fixtures ────────────────────────────────────────────────────────────────

GOOD = """## Calculation
Formula: M = v^2 * r / G
Maan kar chale (assumption): circular orbit aur spherical mass distribution.
v = 220 km/s
r = 8 kpc
G = 6.6743e-11 m^3/kg/s^2
Result = 8.99e10 solar masses
Uncertainty = 20 percent
"""

GOOD_EVIDENCE = ("Rotation curve studies report v = 220 km/s at a radius "
                 "r = 8 kpc from the galactic centre.")

# Wahi formula, wahi inputs — par nateeja jaan-boojh kar 100x galat.
WRONG_MATH = GOOD.replace("Result = 8.99e10 solar masses",
                          "Result = 8.99e12 solar masses")

NO_UNITS = """## Calculation
Formula: M = v^2 * r / G
v = 220
r = 8
G = 6.6743e-11
Result = 8.99e10
"""

FORMULA_ONLY = """## Calculation
Hum M = v^2 * r / G use karenge, jo standard circular-orbit relation hai.
Assumption: spherical distribution.
"""

# §17 ka asli target: "check kiya" likha hai, hisaab ek bhi nahi.
CLAIM_ONLY = """## Calculations
Humne numeric sanity check kiya aur unit conversion bhi verify kiya.
Sab values physically plausible hain aur order of magnitude theek hai.
"""

TWO_CALCS = """## Calculation 1
Formula: rho = M / V
M = 12 kg
V = 3.0 m^3
Result = 4.0 kg/m^3

## Calculation 2
Formula: E = m * c^2
m = 2 kg
Result = 1.7975e17 J
"""

INVENTED = """## Calculation
Formula: rho = M / V
M = 777 kg
V = 3.0 m^3
Result = 259 kg/m^3
"""

# Formula ke baad likhi hui baat ("se nikalta hai") formula ka hissa nahi hai.
PROSE_FORMULA = """## Calculation
M = v^2 * r / G se nikalta hai
v = 220 km/s
r = 8 kpc
G = 6.6743e-11 m^3/kg/s^2
Result = 8.99e10 solar masses
"""


def build_pack() -> EvidencePack:
    s1 = SourceRecord(
        title="Galactic rotation curve",
        url="https://example.org/rot",
        snippet="v = 220 km/s at r = 8 kpc.",
        connector="openalex",
        source_type=SourceType.PAPER,
        year=2020,
        peer_reviewed=True,
        relevance_score=0.8,
    )
    s1.source_id = "S1"
    s1.read_level = "abstract"
    return EvidencePack(sources=[s1], topic_terms=["milky way", "mass"])


def render(calculations) -> str:
    """Synthesizer se poora answer banwao (§17 block dikhta hai ya nahi)."""
    synth = FinalSynthesizer()
    return synth.assemble(
        gemini_answer=GOOD, pack=build_pack(), evidence_level="🟡 MIXED",
        confidence_note="Evidence bata hua hai.", contradictions=[],
        hypotheses=[], verification={}, coverage={}, honesty={}, consensus={},
        calculations=calculations)


# ── 1. poora sahi hisaab ────────────────────────────────────────────────────

def test_good_calculation() -> None:
    print("\n[1] Sahi hisaab ka poora record")
    recs = pc.extract_calculations(GOOD, question="Milky Way ka mass kitna hai?",
                                   evidence_text=GOOD_EVIDENCE)
    check("ek hi record bana", len(recs) == 1, f"mile {len(recs)}")
    if not recs:
        return
    r = recs[0]
    check("formula nikla", r.formula == "M = v^2 * r / G", repr(r.formula))
    check("teen inputs nikle", set(r.inputs) == {"v", "r", "G"}, str(r.inputs))
    check("units nikle", r.units.get("v") == "km/s" and r.units.get("r") == "kpc",
          str(r.units))
    check("result ka unit nikla", r.units.get("result") == "solar masses",
          str(r.units.get("result")))
    check("assumption nikla", len(r.assumptions) == 1, str(r.assumptions))
    check("uncertainty nikli", "20" in r.uncertainty, repr(r.uncertainty))
    check("result nikla", r.result.startswith("8.99e10"), repr(r.result))
    check("unit check pass", r.unit_check_passed is True, str(r.unit_check_passed))
    check("recalculation pass", r.recalculation_passed is True,
          f"{r.recalculation_passed} / {r.recomputed}")
    check("sanity check pass", r.sanity_check_passed is True,
          str(r.sanity_check_passed))
    check("invented_input False", r.invented_input is False, str(r.invented_input))
    check("record complete", r.is_complete is True, str(r.core_missing))
    check("SI recompute record hua", "(SI)" in r.recomputed, r.recomputed)
    check("koi shikayat nahi", pc.calculation_warnings([r.to_dict()]) == [],
          str(pc.calculation_warnings([r.to_dict()])))
    check("usable ginti 1", pc.usable_calculation_count(recs) == 1)
    check("calculations_done True", pc.calculations_done(recs) is True)


# ── 2. galat arithmetic pakda jaana chahiye ─────────────────────────────────

def test_wrong_arithmetic() -> None:
    print("\n[2] Galat jod-ghatav pakda gaya")
    recs = pc.extract_calculations(WRONG_MATH, question="Milky Way mass?",
                                   evidence_text=GOOD_EVIDENCE)
    check("record bana", len(recs) == 1, f"mile {len(recs)}")
    if not recs:
        return
    r = recs[0]
    check("recalculation FAIL (None nahi)", r.recalculation_passed is False,
          str(r.recalculation_passed))
    check("farak note mein likha", any("farak" in n for n in r.notes),
          str(r.notes))
    check("unit check alag se pass raha", r.unit_check_passed is True,
          str(r.unit_check_passed))
    check("usable ginti 0 (fail hisaab count nahi hota)",
          pc.usable_calculation_count(recs) == 0)
    check("calculations_done False", pc.calculations_done(recs) is False)
    check("warning user ko dikhti hai",
          any("dobara jodne par" in w for w in pc.calculation_warnings(recs)))


# ── 3. unit likha hi nahi → unit check FALSE (None nahi) ────────────────────

def test_missing_units() -> None:
    print("\n[3] Unit missing = check chala aur fail hua")
    recs = pc.extract_calculations(NO_UNITS, question="Milky Way mass?",
                                   evidence_text=GOOD_EVIDENCE)
    check("record bana", len(recs) == 1, f"mile {len(recs)}")
    if not recs:
        return
    r = recs[0]
    check("unit_check_passed False", r.unit_check_passed is False,
          str(r.unit_check_passed))
    check("kaunse input ka unit nahi — naam liya gaya",
          any("unit likha hi nahi" in n for n in r.notes), str(r.notes))
    check("unit bina recalculation ka milaan None",
          r.recalculation_passed is None, str(r.recalculation_passed))
    check("usable ginti 0", pc.usable_calculation_count(recs) == 0)


# ── 4. adhoora record — kya missing hai, naam se ────────────────────────────

def test_incomplete_record() -> None:
    print("\n[4] Sirf formula = adhoora record, missing ka naam")
    recs = pc.extract_calculations(FORMULA_ONLY, question="Milky Way mass?",
                                   evidence_text=GOOD_EVIDENCE)
    check("record bana", len(recs) == 1, f"mile {len(recs)}")
    if not recs:
        return
    r = recs[0]
    check("complete False", r.is_complete is False)
    check("inputs missing bataya",
          any("inputs" in g for g in r.core_missing), str(r.core_missing))
    check("result missing bataya", "result" in r.core_missing, str(r.core_missing))
    check("teen check None hi rahe (jhooth 'pass' nahi)",
          (r.unit_check_passed, r.recalculation_passed,
           r.sanity_check_passed) == (None, None, None),
          f"{r.unit_check_passed}/{r.recalculation_passed}/{r.sanity_check_passed}")
    check("invented_input bhi None (jaancha hi nahi ja saka)",
          r.invented_input is None, str(r.invented_input))
    check("usable ginti 0", pc.usable_calculation_count(recs) == 0)
    check("adhoora hone ki warning aayi",
          any("adhoora" in w for w in pc.calculation_warnings(recs)))


# ── 5. §17 ka asli target: "check kiya" likhna check nahi hai ───────────────

def test_claim_without_calculation() -> None:
    print("\n[5] Sirf daava ('sanity check kiya') = ZERO records")
    recs = pc.extract_calculations(CLAIM_ONLY, question="dark matter kya hai?",
                                   evidence_text="Reviews discuss evidence.")
    check("koi record nahi bana", recs == [], f"mile {len(recs)}")
    check("usable ginti 0, None nahi", pc.usable_calculation_count(recs) == 0)
    check("calculations_done False", pc.calculations_done(recs) is False)
    check("jhoothi warning bhi nahi", pc.calculation_warnings(recs) == [])
    answer = render(pc.calculation_records(CLAIM_ONLY))
    # §12 (2026-08-22) — pehle yahan check tha ki block "chhapa hi nahi". Ab
    # section HAMESHA chhapta hai, kyunki gayab section se user ko pata hi nahi
    # chalta tha ki hisaab hua tha ya nahi. Sakhti ab yahan hai: section ho, par
    # usme koi banaya hua number na ho — sirf WAJAH.
    check("Calculations section phir bhi maujood hai", "## Calculations —" in answer)
    check("koi jhootha hisaab nahi, sirf wajah likhi hai",
          "Koi calculation is jawab mein nahi hai" in answer
          and "### Calculation 1" not in answer)


# ── 6. do hisaab = do record (mile nahi) ────────────────────────────────────

def test_two_calculations_stay_separate() -> None:
    print("\n[6] Do hisaab alag-alag record")
    evidence = "The sample mass M = 12 kg in a volume V = 3.0 m^3, and m = 2 kg."
    recs = pc.extract_calculations(TWO_CALCS, question="density aur energy?",
                                   evidence_text=evidence)
    check("do record bane", len(recs) == 2, f"mile {len(recs)}")
    if len(recs) != 2:
        return
    check("pehla formula density ka", recs[0].formula == "rho = M / V",
          repr(recs[0].formula))
    check("doosra formula energy ka", recs[1].formula == "E = m * c^2",
          repr(recs[1].formula))
    check("dono ka recalculation pass",
          [r.recalculation_passed for r in recs] == [True, True],
          str([r.recalculation_passed for r in recs]))
    check("inputs mix nahi hue", "m" not in recs[0].inputs
          and "M" not in recs[1].inputs,
          f"{recs[0].inputs} / {recs[1].inputs}")
    check("usable ginti 2", pc.usable_calculation_count(recs) == 2)


# ── 7. banaya hua number (invented input) ───────────────────────────────────

def test_invented_input() -> None:
    print("\n[7] Question/source mein na hone wala number pakda gaya")
    recs = pc.extract_calculations(
        INVENTED, question="density kitni hai?",
        evidence_text="The container volume is V = 3.0 m^3.")
    check("record bana", len(recs) == 1, f"mile {len(recs)}")
    if not recs:
        return
    r = recs[0]
    check("invented_input True", r.invented_input is True, str(r.invented_input))
    check("kaunsa number — naam liya gaya",
          any("M" in n for n in r.notes if "apna number" in n), str(r.notes))
    check("phir bhi arithmetic sahi maana gaya",
          r.recalculation_passed is True, str(r.recalculation_passed))
    check("warning mein 'verified input nahi' likha",
          any("verified input nahi" in w for w in pc.calculation_warnings(recs)))


# ── 8. tri-state: None ≠ 0 ──────────────────────────────────────────────────

def test_tri_state_contract() -> None:
    print("\n[8] None matlab 'chala hi nahi', 0 matlab 'chala, kuch nahi mila'")
    check("None -> None", pc.usable_calculation_count(None) is None,
          str(pc.usable_calculation_count(None)))
    check("[] -> 0", pc.usable_calculation_count([]) == 0)
    check("khaali list par done False", pc.calculations_done([]) is False)
    check("None par done False", pc.calculations_done(None) is False)
    check("dict list bhi chalti hai (audit ka format)",
          pc.usable_calculation_count(pc.calculation_records(
              GOOD, question="mass?", evidence_text=GOOD_EVIDENCE)) == 1)
    check("uncertainty line ko result nahi banaya",
          pc.calculation_records(GOOD)[0]["result"].startswith("8.99e10"),
          pc.calculation_records(GOOD)[0]["result"])


# ── 9. formula ke baad ka prose formula mein nahi ghusna chahiye ────────────

def test_prose_after_formula() -> None:
    print("\n[9] 'se nikalta hai' formula ka hissa nahi")
    recs = pc.extract_calculations(PROSE_FORMULA, question="mass?",
                                   evidence_text=GOOD_EVIDENCE)
    check("record bana", len(recs) == 1, f"mile {len(recs)}")
    if not recs:
        return
    check("formula saaf", recs[0].formula == "M = v^2 * r / G",
          repr(recs[0].formula))
    check("prose ke baad bhi recalculation chala",
          recs[0].recalculation_passed is True, str(recs[0].recalculation_passed))


# ── 10. determinism ────────────────────────────────────────────────────────

def test_deterministic() -> None:
    print("\n[10] Do baar chalao, bilkul wahi record")
    a = pc.calculation_records(GOOD + TWO_CALCS, question="mass?",
                               evidence_text=GOOD_EVIDENCE)
    b = pc.calculation_records(GOOD + TWO_CALCS, question="mass?",
                               evidence_text=GOOD_EVIDENCE)
    check("dono run same", a == b)
    check("ginti bhi same", len(a) == len(b) and len(a) >= 2, f"{len(a)}/{len(b)}")


# ── 11. user-facing answer mein formula/units/assumptions/result dikhe ──────

def test_answer_shows_calculation() -> None:
    print("\n[11] Jawab mein hisaab dikhta hai (§17 ki maang)")
    recs = pc.calculation_records(GOOD, question="Milky Way ka mass?",
                                  evidence_text=GOOD_EVIDENCE)
    answer = render(recs)
    check("Calculations section chhapa", "## Calculations —" in answer)
    check("formula dikha", "M = v^2 * r / G" in answer)
    check("inputs units ke saath dikhe",
          "220" in answer and "km/s" in answer and "kpc" in answer)
    check("assumptions dikhe", "circular orbit" in answer)
    check("result dikha", "8.99e10" in answer)
    block = answer[answer.find("## Calculations —"):]
    check("teen check alag-alag dikhe",
          "Unit theek likhe hain?" in block
          and "Dobara jodne par wahi jawab aata hai?" in block
          and "Physical limit / conversion check theek?" in block, block[:600])
    check("input kahan se aaya, wo bhi likha",
          "question ya sources" in answer or "invented" in answer.lower())
    # §12 — None ("hisaab ka record hi nahi") aur [] ("record khaali") dono par
    # section rehta hai, par dono baar sirf wajah likhi jaati hai, hisaab nahi.
    for label, value in (("None", None), ("khaali list", [])):
        blank = render(value)
        check(f"{label} par bhi section maujood", "## Calculations —" in blank)
        check(f"{label} par sirf wajah, koi record nahi",
              "Koi calculation is jawab mein nahi hai" in blank
              and "### Calculation 1" not in blank)


# ── 12. §19 audit — mile hue vs poore hue, do alag ginti ────────────────────

def test_quality_context_fields() -> None:
    print("\n[12] quality_context['calculations'] + do alag ginti")
    recs = pc.calculation_records(GOOD + "\n\n" + WRONG_MATH, question="mass?",
                                  evidence_text=GOOD_EVIDENCE)
    ctx = qp.quality_context(pack=None, answer_text=GOOD, calculations=recs)
    check("records audit mein gaye", len(ctx["calculations"] or []) == 2,
          str(ctx["calculations_count"]))
    check("mile hue = 2", ctx["calculations_count"] == 2)
    check("poore hue = 1 (fail wala count nahi)", ctx["calculations_usable"] == 1,
          str(ctx["calculations_usable"]))
    check("fail hue check = 1", ctx["calculations_failed_checks"] == 1,
          str(ctx["calculations_failed_checks"]))
    check("invented inputs = 0", ctx["calculations_with_invented_inputs"] == 0)
    none_ctx = qp.quality_context(pack=None, answer_text=GOOD, calculations=None)
    check("extraction hi nahi chali -> None",
          none_ctx["calculations"] is None
          and none_ctx["calculations_count"] is None
          and none_ctx["calculations_usable"] is None,
          str(none_ctx["calculations_count"]))
    empty_ctx = qp.quality_context(pack=None, answer_text=CLAIM_ONLY,
                                   calculations=[])
    check("dekha par kuch nahi mila -> 0 (None nahi)",
          empty_ctx["calculations_count"] == 0
          and empty_ctx["calculations_usable"] == 0)
    check("tri-state list mein naam hai",
          {"calculations_usable", "calculations_failed_checks"}
          <= set(qp.TRISTATE_FIELDS))


def main() -> int:
    print("=" * 68)
    print("§17 — CALCULATION RECORDS + SANITY CHECKS (offline)")
    print("=" * 68)
    test_good_calculation()
    test_wrong_arithmetic()
    test_missing_units()
    test_incomplete_record()
    test_claim_without_calculation()
    test_two_calculations_stay_separate()
    test_invented_input()
    test_tri_state_contract()
    test_prose_after_formula()
    test_deterministic()
    test_answer_shows_calculation()
    test_quality_context_fields()
    print("\n" + "=" * 68)
    print(f"PASS: {PASS}   FAIL: {FAIL}")
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
