"""
point 10 + 11 — hypothesis ki quality ka regression test.

Ye do purani galtiyon ko pakadta hai:

    * PATLE evidence par bhi 2-3 hypotheses maangi jaati thi (flat default 2),
      isliye "hypothesis" ke naam par andaaza chhapta tha. Ab `evidence_gate()`
      ginti karta hai aur wajah insaani bhasha mein deta hai.
    * LLM (quota/429) mar jaaye to section mein khaali dhaancha jaata tha. Ab
      system khud deterministic research plan banata hai — aur wo plan khud ko
      hypothesis NAHI bolta.

Saath hi point 11 ke CHHE zaroori hisse (support, counter-evidence, assumptions,
falsification test, required experiment/simulation, confidence) alag-alag naape
jaate hain — `missing_fields` se.

Offline: koi network, koi API key, koi pytest.
`python3 tests/test_hypothesis_quality.py`
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import hypothesis as HY                    # noqa: E402
from research_engine.hypothesis import (EvidenceGate,           # noqa: E402
                                        ExperimentStructure,
                                        Hypothesis,
                                        HypothesisEngine,
                                        evidence_gate)
from research_engine.models import (EvidencePack,               # noqa: E402
                                    SourceRecord, SourceType)

PASSED = 0
FAILED = 0
ENGINE = HypothesisEngine()


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


def src(sid: str, relevance: float, level: str = "", *, rejected: str = "",
        retracted: bool = False, title: str = "") -> SourceRecord:
    """Ek source jismein sirf wahi cheezein set hain jo gate dekhta hai."""
    return SourceRecord(
        title=title or f"source {sid}", url=f"http://{sid.lower()}",
        snippet="Superconducting transition temperature measurement. " * 3,
        source_type=SourceType.PAPER, read_level=level,
        full_text_chars=40000 if level == "full_text" else 0,
        relevance_score=relevance, quality_score=0.5,
        rejected_reason=rejected, retracted=retracted, source_id=sid)


def pack_of(*sources) -> EvidencePack:
    return EvidencePack(sources=list(sources))


# ── gate ─────────────────────────────────────────────────────────────────────
def test_gate_thresholds():
    print("\ngate — kitni hypotheses banana imaandaar hai")
    g = evidence_gate(None)
    eq("pack hi nahi → 0 allowed", g.allowed, 0)
    check("aur wajah likhi hai", "ek bhi source retrieve nahi hua" in g.reason,
          g.reason)
    eq("sufficient bhi False", g.sufficient, False)

    g = evidence_gate(pack_of(src("S1", 0.05), src("S2", 0.10)))
    eq("mile par ek bhi relevant nahi → 0 allowed", g.allowed, 0)
    check("wajah relevance floor ka naam leti hai", "0.25" in g.reason, g.reason)
    eq("total ginti chhupayi nahi gayi", g.total_sources, 2)

    g = evidence_gate(pack_of(src("S1", 0.8, "snippet")))
    eq("1 patla relevant source → sirf 1", g.allowed, 1)
    check("wajah 'patla' kehti hai", "patla" in g.reason, g.reason)

    g = evidence_gate(pack_of(src("S1", 0.8, "abstract"), src("S2", 0.6, "snippet")))
    eq("2 relevant + 1 gehra → 2", g.allowed, 2)
    eq("par ye 3 ke layak nahi", g.sufficient, False)

    strong = pack_of(src("S1", 0.8, "full_text"), src("S2", 0.7, "abstract"),
                     src("S3", 0.6, "snippet"))
    g = evidence_gate(strong)
    eq("3 relevant + 2 gehre → 3+ ka evidence", g.sufficient, True)
    eq("allowed kam se kam 3", g.allowed, 3)
    eq("full text ki ginti bhi alag", g.full_text_sources, 1)


def test_gate_ignores_junk_and_retracted():
    print("\ngate — junk aur retracted source ginti mein nahi aate")
    p = pack_of(src("S1", 0.8, "full_text"),
                src("S2", 0.9, "abstract", rejected="domain mismatch: health "
                                                    "statistics"),
                src("S3", 0.9, "full_text", retracted=True))
    g = evidence_gate(p)
    eq("reject hua aur retracted hata kar 1 hi bacha", g.relevant_sources, 1)
    eq("isliye sirf 1 hypothesis", g.allowed, 1)
    eq("total mein teeno dikhte hain (chhupaya nahi)", g.total_sources, 3)


def test_gate_conflict_route():
    print("\ngate — takraav wala raasta (wahi jagah jahan hypothesis chahiye)")
    p = pack_of(src("S1", 0.7, "abstract"), src("S2", 0.6, "snippet"))
    g = evidence_gate(p, contradictions=[{"summary": "S1 vs S2"}])
    eq("takraav ho to 2 relevant + 1 gehra bhi kaafi", g.sufficient, True)
    check("aur wajah takraav ka naam leti hai", "takraav" in g.reason, g.reason)
    g2 = evidence_gate(p)
    eq("bina takraav wahi pack sirf 2 tak", g2.allowed, 2)


def test_gate_request_and_target():
    print("\ngate — user ki request aur target ka hisaab")
    strong = pack_of(src("S1", 0.8, "full_text"), src("S2", 0.7, "abstract"),
                     src("S3", 0.6, "snippet"))
    g = evidence_gate(strong, requested=5)
    eq("5 maangi aur evidence strong → 5 allowed", g.allowed, 5)
    eq("target bhi 5", g.target, 5)
    eq("kami nahi", g.short_of_request, False)

    g = evidence_gate(pack_of(src("S1", 0.8, "snippet")), requested=3)
    eq("3 maangi par evidence 1 ka → allowed 1", g.allowed, 1)
    eq("target 1", g.target, 1)
    eq("aur ye kami darj hoti hai", g.short_of_request, True)

    g = evidence_gate(strong)
    eq("request na ho to target 1 (default 2 nahi)", g.target, 1)
    check("par allowed 3 hai — matlab evidence ki chhat alag hai",
          g.allowed == 3, g.to_dict())

    d = evidence_gate(strong, requested=3).to_dict()
    for key in ("requested", "allowed", "target", "sufficient",
                "relevant_sources", "deep_sources", "full_text_sources",
                "contradictions", "total_sources", "reason", "short_of_request"):
        check(f"to_dict mein {key} hai", key in d)


FULL = """## Hypothesis 1
- Statement: Hydride lattice ki stiffness hi moderate pressure par Tc ki chhat tay karti hai
- Simple explanation: Humara idea ye hai ki hydrogen ke halke atom bahut tezi se
  hilte hain, aur yahi tez hilna bijli ko bina rukawat behne mein madad karta hai.
  Jaise halki cheez ko hilana aasan hota hai, waise hi halke atom zyada madad karte hain.
- Reasoning: Step 1 — [S1] mein 250 K mila. Step 2 — wahi lattice [S2] mein kam Tc deta hai.
- Supporting evidence: [S1] 170 GPa par 250 K report karta hai
- Counter-evidence: [S2] mein same lattice par Tc 30 K kam mila
- Novelty: pehle ye farak pressure calibration par daala gaya tha
- Assumptions: pressure calibration dono papers mein same tareeke se hui hai
- Prediction: H-H distance 5% ghatane par Tc 20 K badhega
  Falsification: reject if no change in Tc after compression
- Required experiment: diamond anvil cell mein 10 sample, 4-probe resistance aur
  magnetic susceptibility dono, ek control sample bina hydrogen ke
- Falsification test: agar H-H distance ghatane par Tc same rahe to hypothesis khatam
- Risks: high pressure setup mein diamond failure ka khatra
- Confidence: MEDIUM
"""

THIN = """## Hypothesis 1
- Statement: Is compound mein room temperature superconductivity ho sakti hai
- Prediction: kuch to badlega
- Confidence: LOW
"""


def test_new_labels_are_parsed():
    print("\nparsing — point 11 ke naye label")
    h = ENGINE.parse(FULL)[0]
    check("counter-evidence alag field mein aaya",
          "Tc 30 K kam" in h.contradicting_evidence, h.contradicting_evidence)
    check("required experiment alag field mein aaya",
          "diamond anvil" in h.experiment, h.experiment)
    check("falsification test alag field mein aaya",
          "same rahe" in h.falsification, h.falsification)
    check("prediction ki continuation line prediction ke andar hi rahi",
          "Falsification: reject if no change" in h.prediction_text,
          h.prediction_text)


def test_label_spellings_are_normalized():
    print("\nparsing — label ki spelling se farak nahi padna chahiye")
    for label, field in (("Counter evidence", "contradicting_evidence"),
                         ("Counter-Evidence", "contradicting_evidence"),
                         ("Evidence against", "contradicting_evidence"),
                         ("Required simulation", "experiment"),
                         ("Experimental plan", "experiment"),
                         ("How to falsify", "falsification")):
        text = (f"## Hypothesis 1\n- Statement: koi ek line ka testable statement "
                f"yahan hai\n- {label}: yahi wali value aani chahiye\n")
        h = ENGINE.parse(text)[0]
        check(f"'{label}' → {field}",
              "yahi wali value" in getattr(h, field), getattr(h, field))


def test_common_markdown_hypothesis_headings_split_into_three_blocks():
    text = """## H1 — pehla idea
- Statement: Pehla alag testable statement yahan likha gaya hai

### Hypothesis #2: doosra idea
- Statement: Doosra alag testable statement yahan likha gaya hai

## 3. Hypothesis — teesra idea
- Statement: Teesra alag testable statement yahan likha gaya hai
"""
    parsed = ENGINE.parse(text, max_count=3)
    eq("H1 / Hypothesis #2 / 3. Hypothesis teen blocks hain", len(parsed), 3)
    check("pehla statement alag hai", parsed[0].statement.startswith("Pehla"))
    check("doosra statement alag hai", parsed[1].statement.startswith("Doosra"))
    check("teesra statement alag hai", parsed[2].statement.startswith("Teesra"))


def test_missing_fields_and_completeness():
    print("\nchhe zaroori hisse — kya aaya, kya nahi")
    h = ENGINE.parse(FULL)[0]
    eq("poori hypothesis mein kuch missing nahi", h.missing_fields, [])
    eq("aur wo complete gini jaati hai", h.is_complete, True)

    thin = ENGINE.parse(THIN)[0]
    missing = " | ".join(thin.missing_fields)
    check("support ki kami boli gayi", "evidence" in missing, missing)
    check("counter-evidence ki kami boli gayi",
          "counter-evidence" in missing, missing)
    check("assumptions ki kami boli gayi", "assumptions" in missing, missing)
    check("falsification ki kami boli gayi", "falsification" in missing, missing)
    check("experiment ki kami boli gayi", "experiment" in missing, missing)
    eq("adhoori hypothesis complete nahi hoti", thin.is_complete, False)
    check("confidence thi, isliye uski shikayat nahi",
          not any("confidence" in m for m in thin.missing_fields),
          str(thin.missing_fields))

    d = h.to_dict()
    for key in ("experiment", "falsification_test", "missing_fields",
                "is_complete"):
        check(f"to_dict mein {key} jaata hai", key in d)
    # §16: prediction dict mein chaaron spec naam + purane `text`/`structured`
    # dono rehte hain. Purane consumers `text` aur `structured` par chalte the,
    # wo abhi bhi wahin hain.
    eq("khaali prediction ka shape", Hypothesis().to_dict()["prediction"],
       {"variables": [], "expected_outcome": "", "measurement_method": "",
        "falsification_condition": "", "text": "", "structured": False})
    check("§16 ke experiment naam bhi maujood hain",
          set(ExperimentStructure.SPEC_KEYS) == {
              "dataset_or_sample", "control_or_baseline", "measured_variables",
              "parameter_range", "statistical_metric", "success_threshold",
              "failure_threshold", "falsification_condition",
              "measurement_precision", "replication_plan", "cost_and_safety"},
          str(ExperimentStructure.SPEC_KEYS))


def test_falsification_fallback_chain():
    print("\nfalsification — teen jagah se utha lo, banao mat")
    h = Hypothesis(falsification="agar Tc same rahe to hypothesis galat hai")
    check("explicit field pehle", h.falsification_test.startswith("agar Tc"),
          h.falsification_test)

    h2 = ENGINE.parse("## Hypothesis 1\n- Statement: ek line ka testable statement"
                      "\n- Prediction: Tc badhega compression se\n"
                      "  Falsification: reject if no change in Tc\n")[0]
    check("explicit na ho to prediction ke andar se",
          "reject if no change" in h2.falsification_test, h2.falsification_test)

    h3 = Hypothesis(how_to_test="10 sample par resistance napo; agar koi change "
                                "na dikhe to ye hypothesis galat sabit ho jaayegi")
    check("wo bhi na ho to how-to-test ki falsify wali line",
          "galat sabit" in h3.falsification_test, h3.falsification_test)

    eq("kuch na ho to khaali — banaya nahi jaata",
       Hypothesis(how_to_test="ek study karke dekhenge kya hota hai"
                              " lambi line").falsification_test, "")


def test_experiment_makes_hypothesis_testable():
    print("\nis_testable — 'Required experiment' bhi test design hai")
    h = Hypothesis(experiment="diamond anvil cell mein 10 sample, 4-probe "
                              "resistance measurement")
    eq("sirf experiment field se bhi testable", h.is_testable, True)
    eq("experiment_plan wahi lautata hai", h.experiment_plan, h.experiment)
    h2 = Hypothesis(how_to_test="dekhenge")
    eq("chhota/khokhla test design → untestable", h2.is_testable, False)


def test_honesty_check_names_the_kami():
    print("\nhonesty_check — kami ka NAAM leta hai")
    warnings = " | ".join(ENGINE.honesty_check(ENGINE.parse(THIN)))
    check("adhoori kehne ke saath list bhi hai",
          "adhoori hai" in warnings and "experiment" in warnings, warnings)
    check("counter-evidence ki shikayat ek hi baar aati hai",
          "against koi evidence list nahi hui" in warnings
          and "counter-evidence" not in warnings, warnings)
    eq("poori hypothesis par koi shikayat nahi",
       ENGINE.honesty_check(ENGINE.parse(FULL)), [])


def test_prompt_asks_for_all_six_and_shows_evidence_state():
    print("\nprompt — chhe cheezein maangta hai, aur evidence ki haalat batata hai")
    p = pack_of(src("S1", 0.8, "abstract"))
    gate = evidence_gate(p, requested=3)
    text = ENGINE.prompt("kya room temperature superconductor ban sakta hai?",
                         "analysis text", p, {"relevant_fields": ["physics"]},
                         None, count=3, gate=gate)
    for label in ("Required experiment", "Falsification test",
                  "Contradicting evidence", "Assumptions", "Confidence"):
        check(f"prompt mein '{label}' maanga gaya", label in text)
    check("chhe cheezein wala rule bhi likha hai", "CHHE cheezein" in text, "")
    check("evidence ki ginti prompt mein jaati hai",
          "EVIDENCE KI HAALAT" in text and "1 relevant source" in text, "")
    check("patle evidence par 'kam hypotheses do' bola gaya",
          "kam hypotheses do" in text, "")

    strong = pack_of(src("S1", 0.8, "full_text"), src("S2", 0.7, "abstract"),
                     src("S3", 0.6, "snippet"))
    good = ENGINE.prompt("q", "a", strong, {}, None, count=3,
                         gate=evidence_gate(strong))
    check("strong evidence par ye chetavani nahi jaati",
          "kam hypotheses do" not in good, "")
    check("gate na do to prompt purana hi rehta hai",
          "EVIDENCE KI HAALAT" not in ENGINE.prompt("q", "a", strong, {}), "")
    check("appendix mein bhi format wahi hai",
          "Required experiment" in ENGINE.prompt_appendix(3), "")


def test_engine_gate_wrapper():
    print("\nengine.gate() — wrapper wahi jawab deta hai")
    p = pack_of(src("S1", 0.8, "full_text"), src("S2", 0.7, "abstract"),
                src("S3", 0.6, "snippet"))
    a = ENGINE.gate(p, requested=3)
    b = evidence_gate(p, requested=3)
    eq("dono ek jaise", a.to_dict(), b.to_dict())
    check("aur type bhi wahi", isinstance(a, EvidenceGate))


QUESTION = "kya room temperature superconductor ambient pressure par ban sakta hai?"
PLAN = {"relevant_fields": ["condensed matter physics", "materials science"],
        "sub_questions": ["kaunse hydride ab tak sabse zyada Tc dete hain?"]}


def test_fallback_plan_is_not_a_fake_hypothesis():
    print("\nfallback_plan — LLM ke bina bhi kaam ka, par hypothesis ka daawa nahi")
    p = pack_of(src("S1", 0.8, "snippet", title="LaH10 pressure study"),
                src("S2", 0.6, "abstract", title="Hydride review"))
    fb = ENGINE.fallback_plan(QUESTION, p, [{"summary": "S1 aur S2 ka Tc alag"}],
                              None, PLAN)
    eq("ye hypothesis nahi hai", fb["is_hypothesis"], False)
    check("text khud kehta hai ki AI ki hypothesis nahi hai",
          "hypothesis NAHI hai" in fb["text"], fb["text"][:120])
    check("koi khaali hypothesis template nahi bana",
          "## Hypothesis" not in fb["text"] and "- Statement:" not in fb["text"])
    check("khule sawaal mein takraav aaya",
          any("Tc alag" in q for q in fb["questions"]), fb["questions"])
    check("jo source poora nahi padha, wo bataya gaya",
          any("poora text nahi mil paaya" in q for q in fb["questions"]),
          fb["questions"])
    check("sub-question bhi khula darj hua",
          any("sabse zyada Tc" in q for q in fb["questions"]), fb["questions"])
    check("agla kadam concrete hai", len(fb["steps"]) >= 2, fb["steps"])
    check("ginti wala note saath hai", "relevant source" in fb["note"], fb["note"])
    check("gate ka record bhi jaata hai", "allowed" in fb["gate"], fb["gate"])


def test_fallback_plan_never_leaks_raw_errors():
    print("\nfallback_plan — raw API error kabhi nahi (point 9)")
    p = pack_of(src("S1", 0.8, "snippet"))
    fb = ENGINE.fallback_plan(QUESTION, p, None, None, PLAN)
    blob = fb["text"] + " ".join(fb["questions"]) + " ".join(fb["steps"])
    for bad in ("429", "ResourceExhausted", "quota_metric", "protobuf",
                "Traceback", "google.api_core", "generativelanguage"):
        check(f"'{bad}' text mein nahi hai", bad not in blob)


def test_fallback_plan_zero_source_and_zero_relevant():
    print("\nfallback_plan — 0 source aur 0 relevant, dono ki alag wajah")
    fb = ENGINE.fallback_plan(QUESTION, None, None, None, None)
    check("0 source par retrieval theek karne ki baat",
          any("retrieval theek" in q for q in fb["questions"]), fb["questions"])
    check("aur hypothesis na banane ki wajah likhi hai",
          "ek bhi source retrieve nahi hua" in fb["text"], fb["text"][:160])

    junk = pack_of(src("S1", 0.05), src("S2", 0.02))
    fb2 = ENGINE.fallback_plan(QUESTION, junk, None, None, PLAN)
    check("sab irrelevant → search terms badalne ka kadam",
          any("Search dobara chalao" in s for s in fb2["steps"]), fb2["steps"])


def test_fallback_plan_is_deterministic():
    print("\nfallback_plan — deterministic (do baar chalao, wahi jawab)")
    p = pack_of(src("S1", 0.8, "snippet"), src("S2", 0.6, "abstract"))
    a = ENGINE.fallback_plan(QUESTION, p, None, None, PLAN)
    b = ENGINE.fallback_plan(QUESTION, p, None, None, PLAN)
    eq("text bilkul same", a["text"], b["text"])
    eq("steps bhi same", a["steps"], b["steps"])


def test_fallback_head_does_not_blame_evidence_wrongly():
    print("\nfallback_plan — ilzaam sahi jagah (evidence vs reasoning pass)")
    strong = pack_of(src("S1", 0.8, "full_text"), src("S2", 0.7, "abstract"),
                     src("S3", 0.6, "snippet"))
    fb = ENGINE.fallback_plan(QUESTION, strong, None, None, PLAN)
    check("evidence theek tha to kami reasoning pass ki boli jaati hai",
          "kami reasoning pass mein rahi" in fb["text"], fb["text"][:200])
    thin = ENGINE.fallback_plan(QUESTION, pack_of(src("S1", 0.8, "snippet")),
                               None, None, PLAN)
    check("patle evidence par wajah evidence ki ginti hai",
          "patla hai" in thin["text"], thin["text"][:200])


# ── report mein kaise dikhta hai ─────────────────────────────────────────────
def test_report_shows_plan_instead_of_empty_template():
    print("\nreport — khaali template ki jagah system ka plan")
    from research_engine.synthesizer import FinalSynthesizer

    synth = FinalSynthesizer()
    p = pack_of(src("S1", 0.8, "snippet"))
    fb = ENGINE.fallback_plan(QUESTION, p, None, None, PLAN)
    text = synth._hypothesis_section([], {"hypothesis_count": 3},
                                     ["Gemini ka free quota khatam ho gaya"],
                                     p, fb)
    check("3 maangi thi ye baat pehle aati hai", "3 nayi hypotheses" in text, text[:200])
    check("asli wajah bhi likhi hai", "free quota" in text, text[:400])
    check("aur system ka plan bhi chhapta hai",
          "system ne khud ek research plan" in text, text[-500:])
    check("plan mein agla kadam hai", "Aage ka kaam" in text, text[-500:])
    check("khaali placeholder template nahi", "- Statement:" not in text)

    plain = synth._hypothesis_section([], {}, [], p, None)
    check("plan na ho to purana behaviour waisa hi",
          "zaroorat nahi padi" in plain, plain[:120])


def test_report_discloses_missing_fields_per_hypothesis():
    print("\nreport — har hypothesis ki kami user ko dikhti hai")
    from research_engine.synthesizer import FinalSynthesizer

    synth = FinalSynthesizer()
    thin = [ENGINE.parse(THIN)[0].to_dict()]
    text = synth._hypothesis_section(thin, {}, [], None, None)
    check("kami ki chetavani chhapti hai",
          "ye cheezein nahi aayi" in text, text[-400:])
    check("experiment ka naam liya gaya", "experiment" in text, text[-400:])
    check("⚠️ nishaan hai", "⚠️" in text)

    full = [ENGINE.parse(FULL)[0].to_dict()]
    good = synth._hypothesis_section(full, {}, [], None, None)
    check("poori hypothesis par koi chetavani nahi",
          "ye cheezein nahi aayi" not in good)
    check("experiment alag heading mein aata hai",
          "Zaroori experiment" in good, good[:600])
    check("falsification alag heading mein aata hai",
          "galat sabit kar dega" in good, good[:900])


def test_test_section_uses_plan_when_no_hypothesis():
    print("\ntest-plan section — hypothesis na ho to bhi kaam ka")
    from research_engine.synthesizer import FinalSynthesizer

    synth = FinalSynthesizer()
    p = pack_of(src("S1", 0.8, "snippet"))
    fb = ENGINE.fallback_plan(QUESTION, p, None, None, PLAN)
    text = synth._test_section([], {}, fb)
    check("system ka agla-kadam plan is section mein aata hai",
          "agla-kadam plan" in text, text[:200])
    check("aur wo AI ka idea nahi bataya gaya",
          "AI ka idea nahi" in text, text[:300])

    empty = synth._test_section([], {})
    check("plan na ho to purani line hi rehti hai",
          "koi alag test plan nahi bana" in empty, empty)

    full = [ENGINE.parse(FULL)[0].to_dict()]
    with_h = synth._test_section(full, {}, fb)
    check("hypothesis ho to experiment test plan mein jaata hai",
          "diamond anvil" in with_h, with_h[:400])
    check("falsification bhi test plan mein jaata hai",
          "Galat sabit karne wala result" in with_h, with_h[:600])


def test_module_is_zero_cost_and_offline():
    print("\n₹0 rule — gate aur fallback bina network/paid API ke chalein")
    import inspect

    source = inspect.getsource(HY)
    for token in ("requests.", "httpx", "urlopen", "genai", "openai",
                  "api_key", "http://", "https://"):
        check(f"module mein '{token}' nahi hai", token not in source)
    # Deterministic hona zaroori hai warna do run ka jawab alag aayega aur
    # user ko lagega system "mood" ke hisaab se plan badal raha hai.
    for token in ("import random", "random.", "time.time"):
        check(f"module mein '{token}' nahi hai (deterministic)",
              token not in source)

    p = pack_of(src("S1", 0.8, "abstract"))
    g1 = evidence_gate(p)
    g2 = evidence_gate(pack_of(src("S1", 0.8, "abstract")))
    eq("same input → same reason", g1.reason, g2.reason)


def main() -> int:
    print("=" * 68)
    print("point 10 + 11 — hypothesis quality + evidence gate")
    print("=" * 68)
    test_gate_thresholds()
    test_gate_ignores_junk_and_retracted()
    test_gate_conflict_route()
    test_gate_request_and_target()
    test_new_labels_are_parsed()
    test_label_spellings_are_normalized()
    test_common_markdown_hypothesis_headings_split_into_three_blocks()
    test_missing_fields_and_completeness()
    test_falsification_fallback_chain()
    test_experiment_makes_hypothesis_testable()
    test_honesty_check_names_the_kami()
    test_prompt_asks_for_all_six_and_shows_evidence_state()
    test_engine_gate_wrapper()
    test_fallback_plan_is_not_a_fake_hypothesis()
    test_fallback_plan_never_leaks_raw_errors()
    test_fallback_plan_zero_source_and_zero_relevant()
    test_fallback_plan_is_deterministic()
    test_fallback_head_does_not_blame_evidence_wrongly()
    test_report_shows_plan_instead_of_empty_template()
    test_report_discloses_missing_fields_per_hypothesis()
    test_test_section_uses_plan_when_no_hypothesis()
    test_module_is_zero_cost_and_offline()
    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
