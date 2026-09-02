"""
§16 ka presentation contract check — INSAAN PEHLE, TECHNICAL BAAD MEIN.

Offline test: koi network, koi Gemini, koi pytest nahi. Seedha
`python3 tests/test_answer_structure.py` chalao.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.models import EvidencePack, SourceRecord, SourceType  # noqa: E402
from research_engine.synthesizer import (  # noqa: E402
    CALC_HEADING,
    EMIT_ORDER,
    SECTION_TITLES,
    FinalSynthesizer,
)

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


def build_pack() -> EvidencePack:
    s1 = SourceRecord(
        title="Urban density and travel demand",
        url="https://example.org/a",
        snippet="Higher density areas show 30% lower per-capita car travel.",
        connector="openalex",
        source_type=SourceType.PAPER,
        year=2021,
        peer_reviewed=True,
        methodology="cohort",
        relevance_score=0.81,
    )
    s1.source_id = "S1"
    s1.read_level = "abstract"
    s2 = SourceRecord(
        title="City transport blog",
        url="https://example.com/b",
        snippet="Buses reduce emissions in most cities.",
        connector="tavily",
        source_type=SourceType.WEB,
        relevance_score=0.44,
    )
    s2.source_id = "S2"
    s2.read_level = "snippet"
    pack = EvidencePack(sources=[s1, s2], topic_terms=["density", "travel"])
    pack.reasoning_planned = 4
    pack.reasoning_done = 2          # jaan-boojh kar adhoora run
    return pack


def build_inputs():
    pack = build_pack()
    hypotheses = [{
        "status": "UNTESTED HYPOTHESIS",
        "statement": "Density badhne se per-capita car travel ghatta hai.",
        "simple": "Log paas-paas rehte hain to gaadi kam chalati hai.",
        "reasoning": "Distance kam hone se trips chhote hote hain.",
        "supporting_evidence": ["S1"],
        "contradicting_evidence": [],
        "novelty": "moderate",
        "assumptions": ["Public transport available hai."],
        "prediction": {
            "variables": ["population density", "car km per person"],
            "expected_outcome": "density double hone par car km ~20% kam",
            "measurement_method": "census + odometer survey",
            "falsification_condition": "car km same ya zyada rahe",
        },
        "has_prediction": True,
        "how_to_test": ["Do sheher compare karo."],
        "if_true": ["Zoning policy kaam karegi."],
        "if_false": ["Transport mode share zyada important hai."],
        "is_testable": True,
        "risks": ["Confounding income."],
        "confidence_reasoning_based": "moderate",
        "disclaimer": "UNTESTED HYPOTHESIS — asli validation lab/field test se hi hoga.",
    }]
    verification = {
        "status": "REQUIRES PHYSICAL TEST",
        "checks": [
            {"check": "internal numeric consistency", "passed": False,
             "detail": "30% aur 20% ke beech mismatch."},
            {"check": "citation validity", "passed": True, "detail": "sab IDs valid."},
        ],
        "warnings": ["Ek number match nahi hua."],
        "required_tests": ["Field survey."],
        "statistics": {},
        "data_for_verification": {},
        "limits": ["Simulation nahi chalayi gayi."],
        "note": "Sirf arithmetic check hua.",
    }
    coverage = {
        "sources_used": 2, "independent_sources": 2, "candidates_discovered": 40,
        "documents_from_user": 0, "external_sources": 2,
        "connectors_searched": ["openalex", "crossref", "tavily", "pubmed", "arxiv"],
        "research_rounds": 2,
        "read_levels": {"abstract": 1, "snippet": 1},
        "full_text_chars_read": 0, "full_text_sources_read": 0,
        "honesty_note": "Poora text kisi ka nahi padha gaya.",
        "topic_terms": ["density", "travel"], "avg_relevance": 0.62,
        "on_topic_sources": 1, "offtopic_dropped": 3,
        "relevance_note": "Ek source topic se door tha.",
        "reasoning_passes": {"planned": 4, "done": 2},
        "reasoning_note": "Quota khatam hone se 2 pass nahi chale.",
        "methodologies": {"cohort": 1}, "retracted_sources": [],
        "strong_methodology_sources": ["S1"], "coi_checked_sources": 0,
        "quality_signal_note": "Signals metadata se aaye.",
        "by_source_type": {"paper": 1, "web": 1},
        "peer_reviewed": 1, "full_text_available": 0,
    }
    honesty = {"citations_verified": True, "cited": ["S1"],
               "summary": "Sabhi citations valid hain."}
    consensus = {"level": "mixed", "stance_counts": {"support": 1, "oppose": 1},
                 "independent_supporting_origins": 1,
                 "independent_opposing_origins": 1, "contradictions_found": 1,
                 "note": "Sources aapas mein bant gaye."}
    contradictions = [{
        "kind": "NUMERIC", "source_ids": ["S1", "S2"],
        "detail": "30% vs 12% reduction.",
        "claim_a": "30% kam travel", "claim_b": "12% kam travel",
    }]
    critique = {"weaknesses": [], "missing_evidence": [], "alternative_explanations": []}
    ledger = {
        "any_requested": True,
        "items": [{"what": "3 hypotheses", "got": "1", "ok": False,
                   "why": "Gemini quota khatam ho gaya."},
                  {"what": "mathematical model", "got": "diya gaya", "ok": True,
                   "why": ""}],
        "unmet": [{"what": "3 hypotheses", "got": "1", "ok": False,
                   "why": "Gemini quota khatam ho gaya."}],
        "lines": ["- ❌ 3 hypotheses — mila: 1", "- ✅ mathematical model"],
        "banner": "Aapne 3 hypotheses maangi thi, 1 ban payi.",
    }
    return pack, hypotheses, verification, coverage, honesty, consensus, \
        contradictions, critique, ledger


MODEL_ANSWER = """## Seedha jawab
Haan, density badhne se aam taur par per-capita car travel kam hota hai.

## Research se kya pata chala?
### Fact
Ek 2021 study mein 30% kami mili [S1].
### Inference
Iska matlab distance kam hone se trips chhote hote hain.

## Ye kyun hota hai?
Kaam aur ghar paas ho to log paidal ya bus se chale jaate hain.

## Mathematical Model
Car km = a * (1/density) + b * mode_share.

## Second-Order Effects
Technology → behaviour → economy → society → environment ka chain.

## Evidence kya kehta hai?
Do sources mile, ek paper aur ek blog.

## Iske against kya mila?
Blog ne chhota effect bataya.

## Kya abhi unknown hai?
Income ka asar alag nahi kiya gaya.

## Final conclusion
Density kaam karti hai, par akeli kaafi nahi.

Bina heading ka ek line, jo phenki nahi jani chahiye.
"""


def main() -> int:
    synth = FinalSynthesizer()
    pack, hyps, ver, cov, hon, cons, contra, crit, ledger = build_inputs()
    report = synth.assemble(
        gemini_answer=MODEL_ANSWER, pack=pack, evidence_level="MIXED",
        confidence_note="Evidence bata hua hai.", contradictions=contra,
        hypotheses=hyps, verification=ver, coverage=cov, honesty=hon,
        consensus=cons, discovery_note="40 candidates mile.",
        quota_note="3/3 calls used", critique=crit,
        warnings=["Ek pass nahi chala."], ledger=ledger,
        label_report={"downgraded": 1, "note": "Ek claim SOURCE-REPORTED kar diya."},
        notes=["Quota khatam."], usage_note="3 calls",
        requests={"hypotheses": 3},
    )

    print("\n[1] Section order aur presence")
    # "### Sources ke beech ka farak" bhi "## Sources" ko match kar leta hai,
    # isliye heading ko line ki shuruaat se dhoondte hain.
    padded = "\n" + report

    def pos(title: str) -> int:
        return padded.find(f"\n## {title}\n")

    positions = []
    for title in SECTION_TITLES:
        check(f"section maujood: {title}", pos(title) >= 0)
    # §12 (2026-08-22) — SECTION_TITLES ka index ab sirf pehchan hai, chhapne ka
    # kram `EMIT_ORDER` deta hai (app ki apni hypotheses conclusion ke BAAD, aur
    # Sources sabse aakhir). Pehle yahan index-order hi expected order tha.
    positions = [pos(SECTION_TITLES[i]) for i in EMIT_ORDER]
    check("order §12 ke mutabik ascending hai",
          positions == sorted(positions) and -1 not in positions,
          str(positions))
    check("Calculations section hamesha maujood hai", pos(CALC_HEADING) >= 0)
    check("Calculations counterevidence ke baad aur Unknowns se pehle hai",
          pos(SECTION_TITLES[4]) < pos(CALC_HEADING) < pos(SECTION_TITLES[7]))
    check("hisaab na banne ki WAJAH likhi hai",
          "Koi calculation is jawab mein nahi hai" in report)
    check("APP ORIGINAL RESEARCH LAB ki heading bilkul wahi hai",
          "\n## APP ORIGINAL RESEARCH LAB\n" in padded)
    check("LAB section par warning sabse pehle hai",
          "app ki KHUD ki soch hai" in
          padded.split("\n## APP ORIGINAL RESEARCH LAB\n", 1)[1][:400])
    check("pehla section Seedha jawab hai",
          report.lstrip().startswith("## Seedha jawab"))

    print("\n[2] Technical cheezein main answer se pehle nahi")
    first = report[:report.find(f"## {SECTION_TITLES[1]}")]
    for bad in ("[PASS]", "[FAIL]", "Evidence Pack", "Connector Status",
                "pipeline", "diagnostic"):
        check(f"'{bad}' Seedha jawab mein nahi hai", bad not in first)
    # §12 — aakhir ke do section: pehle audit, phir Sources. Pehle iska ulta
    # tha; ye badlaav jaan-boojh kar hai.
    check("audit aur Sources sabse aakhir mein hain (audit pehle)",
          0 < pos(SECTION_TITLES[10]) < pos(SECTION_TITLES[9])
          and pos(SECTION_TITLES[9]) == max(positions))
    check("numbers-check audit mein hai, head mein nahi",
          "consistency" not in first)

    print("\n[3] Extra sections main answer ke saath aayi")
    math_pos = report.find("Mathematical model")
    chain_pos = report.find("second-order effects")
    check("mathematical model render hua", math_pos > 0)
    check("second-order chain render hua", chain_pos > 0)
    check("dono supporting-evidence section se pehle hain",
          0 < math_pos < report.find(f"## {SECTION_TITLES[3]}")
          and 0 < chain_pos < report.find(f"## {SECTION_TITLES[3]}"))

    print("\n[4] Sub-headings apni jagah, leftover phenka nahi gaya")
    section1 = report[pos(SECTION_TITLES[1]):pos(SECTION_TITLES[2])]
    check("### Fact section 1 ke andar hi raha", "### Fact" in section1)
    check("### Inference section 1 ke andar hi raha", "### Inference" in section1)
    check("bare label ko §7 wala matlab mil gaya",
          "Fact — jo research se already support hota hai" in section1)
    check("Fact/Inference/Hypothesis ka matlab bhi samjhaya gaya",
          "jo baat research se already support hoti hai" in section1)
    check("bina-heading line bachi hui hai",
          "Bina heading ka ek line" in report)
    unknown = synth.assemble(
        gemini_answer="## Seedha jawab\nHaan.\n\n## Meri apni ek nayi heading\n"
                      "Ye content kisi canonical section mein fit nahi hota.",
        pack=pack, evidence_level="WEAK", confidence_note="", contradictions=[],
        hypotheses=[], verification=ver, coverage=cov, honesty=hon, consensus=cons)
    check("anjaan heading ka content Extra notes mein aata hai",
          "Extra notes" in unknown
          and "kisi canonical section mein fit nahi hota" in unknown)

    # Model kabhi poori report `###` se likhta hai — tab wahi main level hai.
    h3 = synth.assemble(
        gemini_answer="### Seedha jawab\nHaan bilkul.\n\n### Ye kyun hota hai?\n"
                      "Kyunki distance kam ho jaata hai.\n\n#### Example\nEk chhota "
                      "sheher socho.",
        pack=pack, evidence_level="WEAK", confidence_note="", contradictions=[],
        hypotheses=[], verification=ver, coverage=cov, honesty=hon, consensus=cons)
    check("### wali report bhi theek parse hoti hai",
          "Haan bilkul." in h3.split(f"## {SECTION_TITLES[1]}")[0]
          and "Kyunki distance kam ho jaata hai." in h3)
    check("#### Example apne parent section mein raha",
          "Ek chhota sheher socho." in
          h3.split(f"## {SECTION_TITLES[3]}")[0].split(f"## {SECTION_TITLES[2]}")[-1])

    print("\n[5] Hypothesis §6 template")
    check("Simple words mein: hai", "Simple words mein:" in report)
    check("UNTESTED status hai", "UNTESTED" in report)
    check("raw prediction dict leak nahi hua",
          "'variables'" not in report and "{'" not in report)
    check("prediction human shabdon mein hai",
          "Measure kya karna hai" in report or "Kya dikhna chahiye" in report)

    print("\n[6] §15 imaandaari — adhoora run chhupaya nahi gaya")
    check("preliminary/adhoora batAya gaya",
          "preliminary" in report.lower() or "poora nahi" in report
          or "complete nahi" in report)
    check("ledger ka unmet item dikha", "3 hypotheses" in report)

    print("\n[7] §14 access levels")
    # §9 (2026-08-22): access-depth vocabulary sirf paanch label rakhta hai —
    # METADATA ONLY / SNIPPET ONLY / ABSTRACT ONLY / RELEVANT SECTIONS REVIEWED /
    # FULL TEXT ACCESSED (models.ACCESS_DEPTH_ALLOWED). Purana "ABSTRACT
    # REVIEWED" jaan-boojh kar hataya gaya: "reviewed" se lagta tha ki paper
    # padh kar check kiya gaya, jabki sirf summary mili thi.
    for word in ("ABSTRACT ONLY", "SNIPPET ONLY"):
        check(f"{word} explain hua", word in report)
    check("full-text ka jhooth nahi bola",
          "FULL-TEXT VERIFIED" not in report or "poora text padha gaya" in report)

    print("\n[8] §11 audit human-readable")
    check("audit mein human heading hai",
          "Numbers" in report or "number" in report)
    check("limits tail maujood hai", "bypass nahi kiya gaya" in report)
    check("independent human experts disclaimer hai",
          "independent " + "human experts" in report)

    print("\n[9] extractive_summary fallback")
    summary = synth.extractive_summary("Density ka asar?", pack)
    check("fallback Seedha jawab se shuru hota hai",
          summary.startswith("## Seedha jawab"))
    check("fallback S1 quote karta hai", "S1" in summary)
    check("fallback saaf batata hai ki model nahi chala",
          "nahi chala" in summary)

    print("\n[10] Model section missing ho to khaali heading nahi, naam list")
    thin = synth.assemble(
        gemini_answer="## Seedha jawab\nHaan.", pack=pack,
        evidence_level="WEAK", confidence_note="", contradictions=[],
        hypotheses=[], verification=ver, coverage=cov, honesty=hon,
        consensus=cons,
    )
    # EXPECTATION JAAN-BOOJH KAR BADLI GAYI (§10, 2026-08-20): pehle yahan
    # placeholder line ("Reasoning model ne ye section nahi diya") maangi jaati
    # thi. Naya niyam: khaali section chhapta hi nahi — uska NAAM ek jagah
    # (top banner + audit ka "Kaunse hisse nahi ban paaye") likha jaata hai.
    check("khaali section ki heading nahi chhapti",
          "## Ye kyun hota hai?" not in thin)
    check("chhode hue section ka naam imaandaari se likha hai",
          "Ye kyun hota hai?" in thin and "nahi ban paaye" in thin)
    check("purana placeholder text hat gaya",
          "Reasoning model ne ye section nahi diya" not in thin)
    check("purane kwargs ke bina bhi assemble chalta hai",
          thin.lstrip().startswith("## Seedha jawab"))

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


def test_answer_structure_checks_all_pass():
    """
    pytest ke liye entry point (2026-08-21).

    CI `pytest -q tests/test_answer_structure.py` chalati hai, par is file ke
    saare check `main()` ke ANDAR the — yaani pytest is file se 0 test collect
    karta tha aur step chup-chaap green ho jaata tha. "Test chal gaya" aur "test
    hai hi nahi" — dono ek jaise dikhte the. Ab pytest bhi wahi 51 check chalata
    hai jo `python3 tests/test_answer_structure.py` chalata hai.
    """
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
