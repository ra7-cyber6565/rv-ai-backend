"""
"Aapne kya maanga tha" vs "kya sach mein mila" — ledger ka test.

Kyun ye test hai (2026-08-20 ke live MAXIMUM run se): us prompt mein saaf likha
tha "kam se kam 3 nayi hypotheses", "mathematical/optimization model banao" aur
"second-order effects ki chain (technology → behaviour → economy → society →
environment)". Report mein teeno nahi aaye, aur report ne unke MISSING hone ka
zikr bhi nahi kiya — ulta likha "nayi hypothesis generate nahi ki gayi (zaroorat
nahi thi)". Wo jhooth tha: zaroorat thi, Gemini ki quota khatam ho gayi thi.

Yahan teen cheezein pakadi jaati hain:
    1. Prompt se explicit requests theek nikalti hain (rule-based, zero cost).
    2. "Mila ya nahi" ka faisla ANSWER KE TEXT se hota hai, dave se nahi.
    3. Poora pipeline jud kar: jo maanga tha aur nahi mila, wo jawab mein saaf
       likha jaata hai — aur jo research ke andar ban chuka tha par final answer
       se gir gaya, wo wapas laaya jaata hai.

Koi network, koi Gemini key. Chalao:
    python3 tests/test_requested_deliverables.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import gemini_reasoning  # noqa: E402
from research_engine.models import SourceRecord, SourceType  # noqa: E402
from research_engine.orchestrator import DeepResearchEngine  # noqa: E402
from research_engine.requested import (  # noqa: E402
    any_explicit, build_ledger, chain_steps, hypothesis_count, looks_like_chain,
    looks_like_math_model, math_variables, parse_requests, prompt_block,
)
from scripts.run_live_zero_cost_gate import LIVE_QUESTION  # noqa: E402

# intel ka asli prompt (chhota kiya hua, par maangi hui cheezein wahi hain)
REAL_PROMPT = (
    "Sheher ki population density badhne se logon ke travel aur energy use par "
    "kya asar padta hai? Kam se kam 3 nayi testable hypotheses banao. "
    "Population density, travel distance, transport mode share, energy "
    "consumption, emissions, road capacity aur travel time ko variables banakar "
    "ek mathematical/optimization model banao. Second-order effects ki poori "
    "chain bhi do: technology → behaviour → economy → society → environment. "
    "Aakhir mein apne hi jawab par red team karo."
)
PLAIN_PROMPT = "Intermittent fasting ka type 2 diabetes par kya asar hota hai?"


# ── 1. prompt se requests nikalna ────────────────────────────────────────────
def test_real_prompt_yields_every_explicit_request():
    r = parse_requests(REAL_PROMPT)
    assert r["hypothesis_count"] == 3, r["hypothesis_count"]
    assert r["wants_hypotheses"] is True
    assert r["wants_math_model"] is True
    assert r["wants_second_order"] is True
    assert r["wants_red_team"] is True
    assert any_explicit(r) is True


def test_plain_prompt_asks_for_nothing_extra():
    """Jo maanga nahi gaya, uski jhoothi kami dikhana bhi galat hai."""
    r = parse_requests(PLAIN_PROMPT)
    assert r["hypothesis_count"] == 0
    assert r["wants_math_model"] is False
    assert r["wants_second_order"] is False
    assert r["wants_red_team"] is False
    assert any_explicit(r) is False
    assert prompt_block(r) == ""


def test_hypothesis_count_reads_digits_words_and_devanagari():
    assert hypothesis_count("kam se kam 3 nayi hypotheses banao") == 3
    assert hypothesis_count("teen nayi hypothesis do") == 3
    assert hypothesis_count("कम से कम ३ नई परिकल्पनाएँ बनाओ") == 3
    assert hypothesis_count("at least 4 hypotheses") == 4
    # ginti nahi likhi, par shabd hai → kam se kam ek
    assert hypothesis_count("ek hypothesis banao") == 1
    assert hypothesis_count("hypothesis generate karo") == 1
    assert hypothesis_count("sirf summary chahiye") == 0


def test_live_release_question_requests_three_testable_hypotheses():
    """Production question ka exact wording dobara kabhi 3 ko 1 na padhe."""
    requests = parse_requests(LIVE_QUESTION)
    assert requests["wants_hypotheses"] is True
    assert requests["hypothesis_count"] == 3, requests
    assert hypothesis_count("3 nayi falsifiable hypotheses do") == 3


def test_variables_come_from_the_prompt_not_from_imagination():
    variables = math_variables(REAL_PROMPT)
    lowered = [v.lower() for v in variables]
    for must in ("population density", "travel distance", "transport mode share",
                 "energy consumption", "emissions", "road capacity",
                 "travel time"):
        assert must in lowered, f"{must} gum: {variables}"
    # stop-phrase na ho to kuch bhi invent nahi hota
    assert math_variables("ek mathematical model banao") == []


def test_chain_steps_are_read_from_the_arrow_chain():
    steps = [s.lower() for s in chain_steps(REAL_PROMPT)]
    assert steps[:5] == ["technology", "behaviour", "economy", "society",
                         "environment"], steps
    assert chain_steps("second order effects bhi batao") == []


def test_prompt_block_repeats_the_demands_with_exact_headings():
    block = prompt_block(parse_requests(REAL_PROMPT))
    assert "3 nayi hypotheses ZAROORI hain" in block
    assert "## Mathematical Model" in block
    assert "## Second-Order Effects" in block
    assert "population density" in block.lower()
    assert "red-team" in block.lower()


# ── 2. "mila ya nahi" — text se, dave se nahi ────────────────────────────────
def test_math_model_detection_needs_real_equations():
    talk = ("Hum ek mathematical model bana sakte hain jo density aur travel ko "
            "jodta hai. Ye model bahut useful hoga.")
    assert looks_like_math_model(talk) is False, "sirf baat karna model nahi hai"
    real = ("Car_km = a * (1 / D) + b * M\n"
            "E = Car_km * f_energy + T_km * g_energy\n")
    assert looks_like_math_model(real) is True
    single_with_words = ("Objective function: minimize E\n"
                        "E = w1 * energy + w2 * time\n")
    assert looks_like_math_model(single_with_words) is True


def test_chain_detection_needs_an_actual_chain():
    assert looks_like_chain("Iske second-order effects bhi honge.") is False
    assert looks_like_chain("technology → behaviour → economy → society") is True
    assert looks_like_chain("First-order effect ye hai; second-order effect wo "
                            "hai.") is True


# ── 3. ledger ────────────────────────────────────────────────────────────────
def test_ledger_marks_short_delivery_as_unmet_with_the_real_reason():
    requests = parse_requests(REAL_PROMPT)
    ledger = build_ledger(
        requests,
        delivered={"hypotheses": 1, "math_model": False, "second_order": False,
                   "red_team": False},
        reasons=["Gemini quota (429) ki wajah se 3 mein se 1 pass chala."])
    assert ledger["any_requested"] is True
    assert len(ledger["items"]) == 4, ledger["items"]
    assert len(ledger["unmet"]) == 4
    hyp = ledger["items"][0]
    assert hyp["got"] == "1" and hyp["ok"] is False
    assert "1/3" in hyp["why"]
    assert "429" in hyp["why"], hyp["why"]
    assert "AAPKI REQUEST POORI NAHI HUI" in ledger["banner"]
    # banner mein ye bhi likha ho ki neeche wala hissa asli hai
    assert "'ho gaya' maan kar aage mat badho" in ledger["banner"]


def test_ledger_is_quiet_when_everything_was_delivered():
    requests = parse_requests(REAL_PROMPT)
    ledger = build_ledger(
        requests,
        delivered={"hypotheses": 3, "math_model": True, "second_order": True,
                   "red_team": True})
    assert ledger["unmet"] == []
    assert ledger["banner"] == ""
    assert all("✅" in line for line in ledger["lines"]), ledger["lines"]


def test_ledger_stays_empty_when_nothing_was_asked():
    ledger = build_ledger(parse_requests(PLAIN_PROMPT), delivered={})
    assert ledger["any_requested"] is False
    assert ledger["items"] == [] and ledger["banner"] == ""


def test_ledger_never_invents_a_reason():
    ledger = build_ledger({"wants_math_model": True}, delivered={},
                          reasons=[])
    assert ledger["unmet"], ledger
    assert "Wajah record nahi hui" in ledger["unmet"][0]["why"]


# ── 4. recovery: jo research mein ban chuka tha, wo wapas aata hai ───────────
ANALYSIS_WITH_EXTRAS = """## Factual Findings
- Density badhne par per-capita car travel kam hota hai [S1].

## Mathematical / optimization model
Symbols: D = population density, K = car km per person, M = transport mode share.
K = a * (1 / D) + b * (1 - M)
E = K * f_energy

## Second-order effects chain
technology → behaviour → economy → society → environment
Pehle metro aata hai, phir log gaadi kam chalate hain, phir fuel demand girti hai.

## Source Relevance Check
Sources sawaal se match karte hain.
"""


def test_extract_block_takes_the_body_not_the_heading():
    engine = DeepResearchEngine.__new__(DeepResearchEngine)   # __init__ ke bina
    block = DeepResearchEngine._extract_block(ANALYSIS_WITH_EXTRAS,
                                              DeepResearchEngine._MATH_TITLE_RE)
    assert "K = a * (1 / D)" in block
    assert "Second-order" not in block, "agli heading tak hi rukna chahiye"
    assert not block.startswith("#")
    del engine


def test_recover_extras_brings_back_what_the_final_answer_dropped():
    engine = DeepResearchEngine.__new__(DeepResearchEngine)
    requests = parse_requests(REAL_PROMPT)
    thin_answer = "## Seedha jawab\nDensity badhne se travel kam hota hai [S1]."
    out, notes = engine._recover_extras(requests, thin_answer,
                                       ANALYSIS_WITH_EXTRAS)
    assert "## Mathematical Model" in out
    assert "K = a * (1 / D)" in out
    assert "## Second-Order Effects" in out
    assert "technology → behaviour" in out
    assert looks_like_math_model(out) and looks_like_chain(out)
    assert len(notes) == 2, notes
    assert all("naya kuch nahi likha gaya" in n for n in notes)
    # jo pehle se answer mein hai, use dobara nahi jodte
    again, notes2 = engine._recover_extras(requests, out, ANALYSIS_WITH_EXTRAS)
    assert again == out and notes2 == []


def test_recover_extras_does_nothing_when_analysis_has_nothing():
    engine = DeepResearchEngine.__new__(DeepResearchEngine)
    out, notes = engine._recover_extras(
        parse_requests(REAL_PROMPT), "## Seedha jawab\nHaan.",
        "## Factual Findings\nKuch equations nahi hain yahan.")
    assert out == "## Seedha jawab\nHaan."
    assert notes == []


# ── 5. poora pipeline: ledger jawab tak pahunchta hai ───────────────────────
def _records() -> list:
    rows = [
        ("Urban density and per-capita car travel: a cohort study",
         "https://openalex.org/W101",
         "Higher population density is associated with 30% lower per-capita car "
         "travel and lower transport energy consumption in 40 cities.",
         True, "10.1/density"),
        ("Transport mode share, road capacity and travel time in dense cities",
         "https://doaj.org/article/xyz",
         "Analysis of transport mode share, road capacity, emissions and travel "
         "time across dense urban areas.",
         True, "10.1/modeshare"),
    ]
    return [SourceRecord(title=t, url=u, snippet=s, connector="openalex",
                         source_type=SourceType.PAPER, peer_reviewed=p, doi=d,
                         year=2023, full_text_available=bool(d))
            for t, u, s, p, d in rows]


class _QuotaAfterFirstCall:
    """
    Wahi asli halat: pehli call chal gayi (analysis — jisme math model aur chain
    ban gaye), uske baad 429. Yaani synthesis ka final answer khaali aata hai.
    """

    def __init__(self):
        self.prompts = []

    def __call__(self, brain, prompt, label=""):
        if brain.remaining <= 0:
            raise gemini_reasoning.QuotaExhausted(
                f"call budget ({brain.budget}) khatam — '{label}' skip hua")
        brain.calls_used += 1
        self.prompts.append((label, prompt))
        if label != "analysis":
            brain.errors.append(
                f"{label} failed: ResourceExhausted: 429 quota exceeded")
            return ""
        return ANALYSIS_WITH_EXTRAS + """
## Hypothesis 1
- Statement: Density double hone par per-capita car km ~20% girta hai.
- Simple explanation: Log paas-paas rehte hain to gaadi kam chalani padti hai.
- Reasoning: Distance kam hone se trips chhote hote hain [S1].
- Supporting evidence: [S1] 30% kami milti hai.
- Contradicting evidence: kuch pakka nahi mila.
- Novelty: pehle se partly known ho sakta hai.
- Assumptions: public transport available hai.
- Prediction: density double hone par car km 20% kam; na girna isse galat karega.
- How to test: do sheher ka census + odometer survey compare karo.
- If true: zoning policy kaam karegi.
- If false: mode share zyada important hai.
- Risks: koi safety risk nahi.
- Confidence: MEDIUM
"""


def _fake_discover(records):
    def discover(**kwargs):
        return {"records": list(records),
                "log": [{"connector": "openalex", "count": len(records),
                         "error": "", "reason": "", "note": "", "seconds": 0.3}],
                "connectors_searched": ["openalex", "crossref"],
                "seen_urls": {r.url for r in records}}
    return discover


def _fake_reader(pack_ok: bool = False):
    def enrich(pack, max_sources=3, budget_chars=2400):
        entries = [{"source_id": s.source_id, "ok": False, "chars": 0,
                    "reason": "paywall — koi free route nahi mila",
                    "title": s.title} for s in pack.sources[:max_sources]]
        return {"attempted": len(entries), "succeeded": 0,
                "failed": len(entries), "skipped": 0, "chars_read": 0,
                "note": "full text nahi mila", "entries": entries}
    return enrich


class _FakeVectors:
    last_error = ""

    def retrieve(self, question, project_id, n_results=4):
        return {"context": "", "sources": []}


def _run():
    fake = _QuotaAfterFirstCall()
    original = gemini_reasoning.GeminiReasoning.generate
    gemini_reasoning.GeminiReasoning.generate = \
        lambda self, prompt, label="": fake(self, prompt, label)
    try:
        engine = DeepResearchEngine(project_id="requested-test", enable_kg=False,
                                    enable_memory=False)
        engine.vectors = _FakeVectors()
        engine.discovery.discover = _fake_discover(_records())
        engine.reader.enrich = _fake_reader()
        return engine.research(REAL_PROMPT, depth_mode="MAXIMUM"), fake
    finally:
        gemini_reasoning.GeminiReasoning.generate = original


def test_pipeline_puts_the_ledger_in_the_answer():
    result, fake = _run()
    answer = result["answer"]
    ledger = result["requested_ledger"]
    assert ledger["any_requested"] is True, ledger
    # 3 maangi thi, 1 mili — ye chup-chaap nahi jaana chahiye
    assert any("3 nayi testable hypotheses" in i["what"] for i in ledger["items"])
    assert "3 nayi testable hypotheses" in answer
    assert any("poori nahi hui" in w for w in result["warnings"]), result["warnings"]
    # aur "zaroorat nahi thi" jaisa jhooth kahin nahi hona chahiye
    assert "zaroorat nahi thi" not in answer


def test_pipeline_recovers_math_model_and_chain_from_the_analysis_pass():
    """Quota ne synthesis maar di, par kaam ho chuka tha — wo gum nahi hona chahiye."""
    result, _ = _run()
    answer = result["answer"]
    assert "K = a * (1 / D)" in answer, "math model gum ho gaya"
    assert "technology → behaviour" in answer, "chain gum ho gayi"
    ledger = result["requested_ledger"]
    got = {i["what"].split(" (")[0]: i["ok"] for i in ledger["items"]}
    assert got.get("Mathematical / optimization model") is True, ledger["items"]
    assert got.get("Second-order effects chain") is True, ledger["items"]


def test_pipeline_reports_incomplete_run_and_downgrades_labels():
    result, _ = _run()
    answer = result["answer"]
    # §15 — adhoora run chhupana mana hai
    assert ("preliminary" in answer.lower() or "poora nahi" in answer
            or "complete nahi" in answer), answer[-1500:]
    # 0 full text tha, isliye koi bhi [ESTABLISHED] bacha nahi hona chahiye
    assert "[ESTABLISHED]" not in answer
    assert "UNVERIFIED" in result["evidence_level"] or "MIXED" in result["evidence_level"]
    # insaan pehle
    assert answer.lstrip().startswith("## Seedha jawab"), answer[:80]


# ── §4 ki saat naye demands: naap answer ke text par hota hai ────────────────
# Ye hissa is liye juda (2026-08-22 self-audit): contract in saat cheezon ko
# maang raha tha, par koi bhi code unka jawab NAAP nahi raha tha — isliye ledger
# har run mein "check nahi hua" chhapta tha. "Check nahi hua" imaandaar hai, par
# jab naapna MUMKIN ho tab wo bas aalas hai.
_SPEC_FULL = {
    "dataset_or_sample": "SDSS DR17 ke 1200 dwarf galaxies",
    "control_or_baseline": "matched luminosity control set",
    "measured_variables": ["rotation velocity", "stellar mass"],
    "statistical_metric": "chi-square per dof",
    "success_threshold": "3-sigma se zyada farak",
    "failure_threshold": "1-sigma ke andar",
    "falsification_condition": "flat curve dono set mein same aaye",
}


def _hyp(spec_missing, **extra):
    h = {"hypothesis_id": "RV-HYP-2026-001",
         "experiment": "SDSS DR17 par matched-control comparison",
         "how_to_test": "rotation curve fit karo",
         "experiment_spec": dict(_SPEC_FULL),
         "experiment_spec_missing": list(spec_missing)}
    h.update(extra)
    return h


def test_units_answer_ke_number_se_pakde_jaate_hain():
    """"Units diye gaye hain" likh dena saboot nahi — number ke saath unit chahiye."""
    from research_engine.requested import delivery_evidence

    claim_only = ("Humne saare numbers units ke saath diye hain aur SI units "
                  "ka dhyan rakha hai.")
    assert delivery_evidence({}, claim_only)["units"] is False, \
        "sirf 'units diye hain' kehne par units mile nahi maana ja sakta"
    assert delivery_evidence({}, "T_c 92 K par aata hai.")["units"] is True
    # SI ke baahar wale bhi units hain — paisa, percent, astronomy
    assert delivery_evidence({}, "Lagat ₹45 lakh rahegi.")["units"] is True
    assert delivery_evidence({}, "Efficiency 23% mili.")["units"] is True
    assert delivery_evidence({}, "Doori 8 kpc hai.")["units"] is True


def test_adhoora_test_plan_experiment_design_nahi_ginta():
    """
    §16: plan "bana" tabhi jab kis sample par, kya naapa jayega, aur pass-fail
    ka threshold — teeno hon. Warna "test plan diya gaya" dikhawa hai.
    """
    from research_engine.requested import delivery_evidence

    full = delivery_evidence({}, "Plan neeche hai.", hypotheses=[_hyp([])])
    assert full["experiment_design"] is True
    for gap in ("dataset_or_sample", "measured_variables", "success_threshold"):
        part = delivery_evidence({}, "Plan neeche hai.", hypotheses=[_hyp([gap])])
        assert part["experiment_design"] is False, f"{gap} ke bina plan poora nahi"
    # jo hissa core nahi hai (cost/replication) uske bina plan chal sakta hai
    soft = delivery_evidence({}, "Plan neeche hai.",
                             hypotheses=[_hyp(["cost_and_safety",
                                               "replication_plan"])])
    assert soft["experiment_design"] is True


def test_falsification_sirf_asli_text_par_haan_kehta_hai():
    from research_engine.requested import delivery_evidence

    blank = _hyp([], falsification_test="", if_false="", experiment_spec={})
    assert delivery_evidence({}, "kuch bhi", hypotheses=[blank])[
        "falsification"] is False
    said = _hyp([], falsification_test="", if_false="flat curve dikhe to galat")
    assert delivery_evidence({}, "kuch bhi", hypotheses=[said])[
        "falsification"] is True


def test_hypothesis_engine_na_chale_to_key_hi_nahi_jaati():
    """
    Sabse zaroori niyam: naapa nahi gaya ≠ nahi mila. Hypothesis engine hi na
    chala ho to experiment design par ❌ likhna jhooth hoga — ledger ❔ likhega.
    """
    from research_engine.requested import contract_ledger, delivery_evidence

    d = delivery_evidence({}, "Seedha jawab: haan.")
    assert "experiment_design" not in d and "falsification" not in d
    contract = {"experiment_design_required": True,
                "falsification_required": True,
                "required_sections": [], "counter_search_required": False}
    led = contract_ledger(contract, delivered=d)
    rows = {i["key"]: i for i in led["items"]}
    assert rows["experiment_design"]["ok"] is None
    assert rows["experiment_design"]["got"] == "check nahi hua"
    assert rows["falsification"]["unknown"] is True
    assert any("❔" in line for line in led["lines"])


def test_source_depth_paanch_labels_se_pakda_jaata_hai():
    from research_engine.requested import delivery_evidence

    assert delivery_evidence({}, "S3 — padhne ki gehrai: SNIPPET ONLY")[
        "source_depth"] is True
    assert delivery_evidence({}, "S3 ko poora padha gaya (bharosa karo).")[
        "source_depth"] is False


def test_tulna_ke_pehlu_alag_alag_gine_jaate_hain():
    """"Compare kiya" kehna kaafi nahi — prompt ke har pehlu par ginti hoti hai."""
    from research_engine.requested import (contract_ledger, delivery_evidence,
                                           quality_contract)

    contract = quality_contract(
        "EV vs petrol cars ko cost, emissions and range par compare karo")
    assert contract["comparison_required"] is True
    assert contract["comparison_dimensions"] == ["cost", "emissions", "range"]
    answer = ("EV ki cost zyada hai par emissions kam hain. Range par baat "
              "nahi hui... yahan range shabd hai par pehlu cover hai.")
    partial = delivery_evidence(
        contract, "EV ki cost zyada hai, emissions kam hain.")
    assert partial["comparison_dimensions_covered"] == ["cost", "emissions"]
    led = contract_ledger(contract, delivered=partial)
    row = next(i for i in led["items"] if i["key"] == "comparison")
    assert row["got"] == "2/3 pehlu mile" and row["ok"] is False
    assert "range" in row["why"]
    full = delivery_evidence(contract, answer)
    assert full["comparison_dimensions_covered"] == ["cost", "emissions", "range"]


def test_naam_se_maange_gaye_target_source_titles_mein_bhi_dekhe_jaate_hain():
    from research_engine.requested import delivery_evidence, quality_contract

    contract = quality_contract(
        "Bullet Cluster aur Euclid survey ke data par dark matter evidence dekho")
    targets = contract["named_targets"]
    assert "Bullet Cluster" in targets
    d = delivery_evidence(contract, "Bullet Cluster ka lensing map dekha gaya.",
                          source_titles=["Euclid Q1 weak lensing release"])
    found = d["named_targets_found"]
    assert "Bullet Cluster" in found
    assert any("Euclid" in t for t in found), found


def test_pehlu_ke_naam_mein_command_verb_nahi_ghusta():
    """
    "— evidence strength aur systematics par tulna karo" se pehle
    "systematics par tulna karo" ek "pehlu" ban gaya tha. Pehlu ka naam hi
    galat ho to ledger bhi galat cheez dhoondhta hai.
    """
    from research_engine.requested import (comparison_dimensions,
                                           delivery_evidence, quality_contract)

    q = ("Rotation curves vs lensing vs CMB ki ek comparison table banao — "
         "evidence strength aur systematics par tulna karo.")
    dims = comparison_dimensions(q)
    assert dims == ["evidence strength", "systematics"], dims
    for d in dims:
        for bad in ("tulna", "compare", "karo", "banao"):
            assert bad not in d.lower(), (d, bad)
    contract = quality_contract(q)
    assert contract["comparison_dimensions"] == dims
    d = delivery_evidence(contract, "Evidence strength alag hai; systematics "
                                    "dono taraf bade hain.")
    assert d["comparison_dimensions_covered"] == dims
    # Purane raaste bhi zinda: object-pehle wali list aur khaali list dono.
    assert comparison_dimensions(
        "EV vs petrol cars ko cost, emissions and range par compare karo") == [
            "cost", "emissions", "range"]
    assert comparison_dimensions("Dark matter aur MOND ki tulna karo") == []


def _main() -> int:
    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:                 # noqa: BLE001
            failed += 1
            print(f"  ERR  {name}: {type(exc).__name__}: {exc}")
    print("\nsab pass" if not failed else f"\n{failed} test fail")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
