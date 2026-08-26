"""#116 — LAB stage: app apni hi hypothesis ko KHUD test kare.

Naapa gaya defect (2026-08-26): hypothesis ban jaati thi, uske saath
"UNTESTED" likh diya jaata tha, aur bas. intel ki maang thi — "phir un par
research kro, khud ko 3-4 tarike se test kro, tab jawab do", aur hypothesis
hataane par bhi "kya strong proof h ye kaam nhi krega" likha ho.

Is file ke kaam:
  1. paanchon recipe (numeric_formula / threshold / direction /
     proportion_interval / walk_forward) ka nateeja pin karo,
  2. paanchon status ka matlab alag rahe — budget khatam hona ya kill switch
     "data nahi mila" NAHI hai,
  3. rollup ka kram: ek TESTED_FAIL kisi bhi TESTED_PASS par bhaari hai,
  4. jhoothe verdict ke do asli trap (Hinglish word order, bina unit ke
     number) verdict na de payein — galat TESTED_PASS/FAIL sabse bada nuksaan
     hai, "test nahi hua" usse behtar hai,
  5. lab ka pass hona kabhi "proven" na bane (`is_established_fact` False,
     `real_world_experiment_pending` True hamesha),
  6. stage ka kharcha ₹0 aur zero Gemini call rahe, aur wiring (orchestrator →
     ResearchResult → synthesizer) sach me judi ho.
"""
import inspect
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import answer_order, lab, orchestrator  # noqa: E402
from research_engine import synthesizer_claude  # noqa: E402
from research_engine.exam_intelligence import _wilson  # noqa: E402
from research_engine.models import ResearchResult  # noqa: E402


class _Src:
    """EvidencePack ka sirf wahi hissa jo lab padhta hai."""

    def __init__(self, source_id, title="", snippet="", full_text=""):
        self.source_id = source_id
        self.title = title
        self.snippet = snippet
        self.full_text = full_text


class _Pack:
    def __init__(self, *sources):
        self.sources = list(sources)


def _hyp(hid, statement, **extra):
    row = {"hypothesis_id": hid, "statement": statement}
    row.update(extra)
    return row


def _first(report, index=0):
    return report["hypotheses"][index]


def _codes(block):
    return [t["reason_code"] for t in block["tests"]]


# ── 1. status vocabulary aur rollup ka kram ──────────────────────────────────

def test_five_statuses_exist_and_are_distinct():
    """Paanch alag naam — chaar se kaam nahi chalta.

    NOT_RUN alag hai kyunki budget khatam hona / kill switch / andar ka error
    "data nahi mila" nahi hai. Dono ko ek naam dena user se jhooth hai.
    """
    assert lab.LAB_STATUSES == ("TESTED_PASS", "TESTED_FAIL", "DATA_MISSING",
                                "NOT_TESTABLE_HERE", "NOT_RUN")
    assert len(set(lab.LAB_STATUSES)) == 5


def test_rollup_one_fail_beats_any_pass():
    """Ek ulta nateeja poore hypothesis ko fail karta hai."""
    def res(status):
        return lab.TestResult(spec_id="s", hypothesis_id="h", recipe="threshold",
                              status=status, what="w")

    assert lab.rollup([res(lab.TESTED_PASS), res(lab.TESTED_PASS),
                       res(lab.TESTED_FAIL)]) == lab.TESTED_FAIL
    assert lab.rollup([res(lab.TESTED_PASS),
                       res(lab.DATA_MISSING)]) == lab.TESTED_PASS
    assert lab.rollup([res(lab.DATA_MISSING),
                       res(lab.NOT_TESTABLE_HERE)]) == lab.DATA_MISSING
    assert lab.rollup([res(lab.NOT_TESTABLE_HERE),
                       res(lab.NOT_RUN)]) == lab.NOT_TESTABLE_HERE
    # Khaali list par bhi PASS nahi — "kuch nahi chala" PASS nahi hota.
    assert lab.rollup([]) == lab.NOT_TESTABLE_HERE


def test_wilson_interval_agrees_with_exam_intelligence():
    """Do jagah ek hi hisaab — dono ka nateeja alag hua to koi ek jhooth hai.

    `exam_intelligence._wilson` ko import nahi kiya gaya (wo module network
    safety + process lock kheenchta hai), isliye lab ki apni copy hai. Ye test
    unhe bandh kar rakhta hai.
    """
    for successes, total in ((0, 5), (1, 7), (12, 20), (19, 20), (50, 50),
                             (3, 11), (7, 9)):
        assert lab.wilson_interval(successes, total) == _wilson(successes, total)


def test_wilson_interval_edges_are_honest():
    assert lab.wilson_interval(4, 0) == (0.0, 1.0)   # bina sample koi range nahi
    low, high = lab.wilson_interval(0, 10)
    assert low == 0.0 and 0.0 < high < 0.4
    low, high = lab.wilson_interval(10, 10)
    assert high == 1.0 and low > 0.6
    # 12/20 par 90% ka daawa range ke BAHAR hai — "fake 90-95%" isi se rukta hai.
    low, high = lab.wilson_interval(12, 20)
    assert not low <= 0.90 <= high
    assert math.isclose(low, 0.3865779423, abs_tol=1e-9)


# ── 2. numeric_formula — hypothesis ka apna hisaab dobara chalao ──────────────

def test_numeric_formula_recomputes_and_passes():
    """Formula + inputs + likha nateeja teeno hypothesis ke — app dobara naapta hai."""
    report = lab.run_lab("test", [_hyp(
        "RV-HYP-1", "Energy nikalti hai.",
        reasoning="E = m * c with m = 3 kg, c = 30 m/s gives E = 90 J")])
    block = _first(report)
    assert block["verdict"] == lab.TESTED_PASS
    test = block["tests"][0]
    assert test["recipe"] == "numeric_formula"
    assert test["reason_code"] == "recomputed_match"
    # Pass hone par bhi ye do line nahi badalti.
    assert test["is_established_fact"] is False
    assert test["real_world_experiment_pending"] is True


def test_numeric_formula_catches_its_own_wrong_arithmetic():
    report = lab.run_lab("test", [_hyp(
        "RV-HYP-2", "Energy nikalti hai.",
        reasoning="E = m * c with m = 3 kg, c = 30 m/s gives E = 200 J")])
    block = _first(report)
    assert block["verdict"] == lab.TESTED_FAIL
    assert block["tests"][0]["reason_code"] == "recomputed_mismatch"


def test_numeric_formula_without_inputs_says_data_missing_not_pass():
    report = lab.run_lab("test", [_hyp("RV-HYP-3", "Kuch hoga.",
                                       reasoning="E = m * c hota hai.")])
    block = _first(report)
    assert block["verdict"] == lab.DATA_MISSING
    assert _codes(block)[0] in ("no_calculation_found", "inputs_missing",
                                "no_stated_result")
    assert block["verdict"] != lab.TESTED_PASS


# ── 3. threshold — evidence ke asli numbers se naapo ─────────────────────────

def test_threshold_pass_uses_evidence_numbers_with_source_ids():
    pack = _Pack(_Src("S1", title="Tc 260 K reported"),
                 _Src("S2", snippet="onset near 265 K"))
    report = lab.run_lab("q", [_hyp("RV-HYP-1",
                                    "Is family ka Tc 250 K se zyada hoga.")],
                         pack=pack)
    block = _first(report)
    assert block["verdict"] == lab.TESTED_PASS
    test = block["tests"][0]
    assert test["recipe"] == "threshold"
    assert test["reason_code"] == "all_measurements_satisfy"
    assert test["expected"] == "> 250 K"
    # Naapa hua number kis source se aaya — ye report me dikhna chahiye.
    assert sorted(test["evidence_ids"]) == ["S1", "S2"]


def test_threshold_fail_when_measurements_contradict():
    pack = _Pack(_Src("S1", title="Tc measured at 180 K"))
    report = lab.run_lab("q", [_hyp("RV-HYP-1",
                                    "Is family ka Tc 250 K se zyada hoga.")],
                         pack=pack)
    block = _first(report)
    assert block["verdict"] == lab.TESTED_FAIL
    assert block["tests"][0]["reason_code"] == "measurements_contradict"


def test_threshold_mixed_evidence_gives_no_verdict():
    """Dono taraf evidence ho to koi ek nateeja nahi — na PASS na FAIL."""
    pack = _Pack(_Src("S1", title="Tc 260 K"), _Src("S2", snippet="Tc only 180 K"))
    report = lab.run_lab("q", [_hyp("RV-HYP-1",
                                    "Is family ka Tc 250 K se zyada hoga.")],
                         pack=pack)
    block = _first(report)
    assert block["verdict"] == lab.DATA_MISSING
    assert block["tests"][0]["reason_code"] == "mixed_evidence_no_verdict"


def test_threshold_without_matching_measurement_is_data_missing():
    pack = _Pack(_Src("S1", title="Sample cost 40 dollars"))
    report = lab.run_lab("q", [_hyp("RV-HYP-1", "Tc 250 K se zyada hoga.")],
                         pack=pack)
    block = _first(report)
    assert block["verdict"] == lab.DATA_MISSING
    assert block["tests"][0]["reason_code"] == "no_matching_measurement"


# ── 4. direction — teen shakal ka joda, aur do jhoothe verdict ke trap ────────

def test_direction_reads_all_three_pair_shapes():
    """arrow / English "from A to B" / Hinglish "A se B tak" — teeno chalein.

    Ye ek asli defect tha: sirf English kram padha jaata tha, isliye
    "20 % se 12 % tak badhegi" par verdict aata hi nahi tha.
    """
    shapes = {
        "arrow": "Yield 20 % → 12 % ghategi.",
        "english": "Yield will decrease from 20 % to 12 %.",
        "hinglish": "Yield 20 % se 12 % tak ghategi.",
    }
    for name, text in shapes.items():
        pair, problem = lab._direction_pair(text)
        assert pair is not None, f"{name}: joda mila hi nahi ({problem})"
        start, end = pair
        assert (start.si, end.si) == (20.0, 12.0), name


def test_direction_fails_when_hypothesis_contradicts_its_own_numbers():
    report = lab.run_lab("q", [_hyp("RV-HYP-4",
                                    "Yield 20 % se 12 % tak badhegi.")])
    block = _first(report)
    assert block["verdict"] == lab.TESTED_FAIL
    test = block["tests"][0]
    assert test["recipe"] == "direction"
    assert test["reason_code"] == "numbers_contradict_direction"
    assert test["observed"] == "20 % → 12 %"


def test_direction_passes_when_numbers_agree():
    report = lab.run_lab("q", [_hyp("RV-HYP-5",
                                    "Yield 12 % se 20 % tak badhegi.")])
    block = _first(report)
    assert block["verdict"] == lab.TESTED_PASS
    assert block["tests"][0]["reason_code"] == "numbers_match_direction"


def test_threshold_claim_never_becomes_a_fake_direction_fail():
    """TRAP 1: "300 K se zyada hoga, kam se kam 280 K" me 300→280 joda NAHI hai.

    Bina end-marker ke isko "ghat raha hai" padh liya jaata tha, aur ek SAHI
    hypothesis TESTED_FAIL ho jaati. Yahan direction spec banni hi nahi chahiye.
    """
    claim = "Is family ka Tc 300 K se zyada hoga, kam se kam 280 K."
    pair, problem = lab._direction_pair(claim)
    assert pair is None
    assert problem in ("pair_not_comparable", "no_baseline_and_outcome_pair")
    specs = lab.plan_specs(_hyp("RV-HYP-6", claim), _Pack(_Src("S1", "Tc 310 K")))
    assert "direction" not in [s.recipe for s in specs]


def test_bare_numbers_without_a_shared_word_make_no_pair():
    """TRAP 2: "Chapter 2 se 5 tak padhne se marks badhenge" — 2→5 marks nahi hai."""
    claim = "Chapter 2 se 5 tak padhne se marks badhenge."
    pair, problem = lab._direction_pair(claim)
    assert pair is None, "bina unit/shabd ke number se verdict nahi banna chahiye"
    assert problem == "pair_not_comparable"
    specs = lab.plan_specs(_hyp("RV-HYP-7", claim))
    assert "direction" not in [s.recipe for s in specs]


def test_bare_quantities_work_when_both_sides_carry_the_same_word():
    """Paise/marks/lakh wale daawe (trading, exam, business) bhi naape jaayein."""
    cases = {
        "Kharcha 100 rupees se 80 rupees tak ghatega.": lab.TESTED_PASS,
        "Marks 40 marks se 75 marks tak badhega.": lab.TESTED_PASS,
        "Turnover 20 lakh se 30 lakh tak badhega.": lab.TESTED_PASS,
        "Loss 5000 rupees se 2000 rupees tak badhega.": lab.TESTED_FAIL,
    }
    for text, expected in cases.items():
        report = lab.run_lab("q", [_hyp("RV-HYP-8", text)])
        assert _first(report)["verdict"] == expected, text


def test_direction_spec_is_never_planned_when_it_cannot_run():
    """Planner aur runner ek hi faisla lete hain (`_direction_pair`).

    Warna report me "test plan hua" dikhta aur nateeja hamesha DATA_MISSING —
    yaani bekaar shor.
    """
    for text in ("Profit badhega.", "Cost kam ho jaayegi.",
                 "Chapter 2 se 5 tak padhne se marks badhenge."):
        specs = [s for s in lab.plan_specs(_hyp("RV-HYP-9", text))
                 if s.recipe == "direction"]
        assert specs == [], text


# ── 5. proportion_interval — "fake 90-95%" ka asli pehredaar ─────────────────

def test_claimed_ninety_percent_fails_against_twelve_of_twenty():
    report = lab.run_lab("q", [_hyp(
        "RV-HYP-10", "12 of 20 samples worked, 90% success expected.")])
    block = _first(report)
    assert block["verdict"] == lab.TESTED_FAIL
    test = block["tests"][0]
    assert test["recipe"] == "proportion_interval"
    assert test["reason_code"] == "claim_outside_interval"
    assert "38.7%" in test["observed"] and "78.1%" in test["observed"]


def test_small_sample_gives_no_verdict_at_all():
    """2/3 par koi bharosemand nateeja nahi — na PASS, na FAIL."""
    report = lab.run_lab("q", [_hyp(
        "RV-HYP-11", "2 of 3 samples worked, 60% success expected.")])
    block = _first(report)
    assert block["verdict"] == lab.DATA_MISSING
    assert block["tests"][0]["reason_code"] == "sample_too_small"


def test_counts_from_evidence_never_become_a_pass_or_fail():
    """Ginti evidence se aayi, percent claim se — dono ko jodna andaaza hoga."""
    pack = _Pack(_Src("S1", snippet="In the trial 12 of 20 devices worked."))
    report = lab.run_lab("q", [_hyp("RV-HYP-12",
                                    "Ye method 90% baar kaam karega.")], pack=pack)
    block = _first(report)
    proportion = [t for t in block["tests"] if t["recipe"] == "proportion_interval"]
    assert proportion, "evidence ki ginti par range to nikalni chahiye"
    assert proportion[0]["reason_code"] == "no_claimed_proportion"
    assert proportion[0]["status"] == lab.DATA_MISSING


def test_nearest_percent_refuses_to_guess_on_a_tie():
    """Do percent barabar door hon to None — guess par hypothesis fail karna galat."""
    left, core, right = "80%" + " " * 6, "12 of 20", " 80%"
    text = left + core + right
    anchor = len(left)
    assert anchor - 0 == (len(left) + len(core) + 1) - anchor  # barabar doori
    assert lab._nearest_percent(text, anchor) is None
    close = "12 of 20 worked, i.e. 60% success."
    assert lab._nearest_percent(close, 0) == 0.60
    # Range se bahar ka percent (150%) proportion nahi ho sakta.
    assert lab._nearest_percent("12 of 20 worked, 150% claim", 0) is None
    # Window ke bahar ka percent bhi nahi ginta.
    assert lab._nearest_percent("12 of 20" + " " * 120 + "60%", 0) is None


# ── 6. walk_forward — jo chala nahi, wo "chal gaya" na likhe ─────────────────

def test_forecast_claim_says_the_backtest_did_not_run():
    report = lab.run_lab("q", [_hyp(
        "RV-HYP-13", "Next year returns forecast 12 % rahega.")])
    block = _first(report)
    walk = [t for t in block["tests"] if t["recipe"] == "walk_forward"]
    assert walk and walk[0]["status"] == lab.DATA_MISSING
    assert walk[0]["reason_code"] == "series_data_missing"
    assert "test ho chuka" in walk[0]["detail"]
    assert any("walk-forward test chalaya hi nahi gaya" in line
               for line in lab.lab_limits(report))


# ── 7. koi test hi na bane — wajah NAAPI hui ho, khaali "UNTESTED" nahi ───────

def test_real_world_experiment_is_named_as_such():
    report = lab.run_lab("q", [_hyp(
        "RV-HYP-14", "Ye compound asar karega.", safety_sensitive=True,
        experiment="Randomized controlled trial with 200 patients.")])
    block = _first(report)
    assert block["verdict"] == lab.NOT_TESTABLE_HERE
    assert block["verdict_reason"] == "needs_real_world_experiment"
    # Safety-sensitive par risk note compulsory hai (non-negotiable).
    assert block["requires_risk_review"] is True
    assert "qualified review" in block["risk_note"]


def test_prose_only_hypothesis_says_no_computable_claim():
    report = lab.run_lab("q", [_hyp("RV-HYP-15",
                                    "Ye idea philosophically zyada sangat hai.")])
    block = _first(report)
    assert block["verdict"] == lab.NOT_TESTABLE_HERE
    assert block["verdict_reason"] == "no_computable_claim"
    assert block["tests"] == []


# ── 8. fail-closed: budget, kill switch, unknown recipe, andar ka error ───────

def test_kill_switch_stops_everything_and_says_so():
    report = lab.run_lab("q", [_hyp("RV-HYP-16", "Tc 250 K se zyada hoga.")],
                         pack=_Pack(_Src("S1", "Tc 260 K")), kill_switch=True)
    block = _first(report)
    assert report["ran"] is False and report["kill_switch"] is True
    assert block["verdict"] == lab.NOT_RUN
    assert block["verdict_reason"] == "kill_switch"
    assert report["counts"][lab.NOT_RUN] == 1
    assert report["counts"][lab.TESTED_PASS] == 0


def test_hypothesis_budget_marks_extras_not_run_not_failed():
    policy = lab.LabPolicy(max_hypotheses=2)
    rows = [_hyp(f"RV-HYP-{i}", "Yield 12 % se 20 % tak badhegi.")
            for i in range(4)]
    report = lab.run_lab("q", rows, policy=policy)
    verdicts = [b["verdict"] for b in report["hypotheses"]]
    assert verdicts[:2] == [lab.TESTED_PASS, lab.TESTED_PASS]
    assert verdicts[2:] == [lab.NOT_RUN, lab.NOT_RUN]
    assert report["hypotheses"][2]["verdict_reason"] == "hypothesis_budget"


def test_expired_time_budget_is_not_run_and_is_reported():
    specs = lab.plan_specs(_hyp("RV-HYP-17", "Yield 12 % se 20 % tak badhegi."))
    assert specs
    results = lab.run_specs(specs, deadline=time.monotonic() - 1.0)
    assert [r.status for r in results] == [lab.NOT_RUN] * len(results)
    assert results[0].reason_code == "budget_exhausted"


def test_unknown_recipe_is_not_testable_here():
    spec = lab.TestSpec(spec_id="s", hypothesis_id="h", recipe="teleport",
                        what="kuch bhi")
    result = lab.run_specs([spec])[0]
    assert result.status == lab.NOT_TESTABLE_HERE
    assert result.reason_code == "unknown_recipe"


def test_internal_error_becomes_not_run_never_pass():
    """Andar ka crash kabhi TESTED_PASS na bane — fail-closed."""
    def boom(spec, policy, executor):
        raise ValueError("jaan-boojh kar")

    original = lab.RECIPES["threshold"]
    lab.RECIPES["threshold"] = boom
    try:
        spec = lab.TestSpec(spec_id="s", hypothesis_id="h", recipe="threshold",
                            what="w")
        result = lab.run_specs([spec])[0]
    finally:
        lab.RECIPES["threshold"] = original
    assert result.status == lab.NOT_RUN
    assert result.reason_code == "internal_error"
    # Raw exception text user ko nahi jaata — sirf naam.
    assert "jaan-boojh kar" not in result.detail
    assert "ValueError" in result.detail


def test_no_hypotheses_is_not_a_failure():
    report = lab.run_lab("q", [])
    assert report["ran"] is False
    assert report["hypotheses"] == []
    assert "test fail hua" in report["note"]
    assert lab.lab_report_section(report) == ""
    assert lab.lab_limits(report) == []


# ── 9. kharcha ₹0, zero Gemini call, koi randomness/network/model-code nahi ────

def test_lab_costs_nothing_and_writes_no_code():
    report = lab.run_lab("q", [_hyp("RV-HYP-18", "Tc 250 K se zyada hoga.")],
                         pack=_Pack(_Src("S1", "Tc 260 K")))
    assert report["gemini_calls"] == 0
    assert report["provider_cost"] == 0
    policy = report["policy"]
    assert policy["randomness_used"] is False
    assert policy["network_used"] is False
    assert policy["model_written_code_executed"] is False
    executor = report["executor"]
    assert executor["arbitrary_python"] is False
    assert executor["network"] is False
    assert executor["subprocess"] is False
    assert executor["randomness"] is False
    for test in _first(report)["tests"]:
        assert "model_written_code" not in test or test["model_written_code"] is False


def test_specs_record_that_no_model_wrote_code():
    specs = lab.plan_specs(_hyp("RV-HYP-19", "Tc 250 K se zyada hoga."),
                           _Pack(_Src("S1", "Tc 260 K")))
    assert specs
    for spec in specs:
        assert spec.to_dict()["model_written_code"] is False


def test_lab_is_deterministic_on_the_same_input():
    """Do baar chalao, bilkul wahi nateeja — koi randomness nahi."""
    rows = [_hyp("RV-HYP-20", "Tc 250 K se zyada hoga."),
            _hyp("RV-HYP-21", "12 of 20 samples worked, 90% success expected.")]
    pack = _Pack(_Src("S1", "Tc 260 K"), _Src("S2", snippet="Tc 265 K"))
    first = lab.run_lab("q", rows, pack=pack)
    second = lab.run_lab("q", rows, pack=pack)
    assert first == second


def test_lab_never_mutates_the_hypothesis_dicts():
    row = _hyp("RV-HYP-22", "Yield 20 % se 12 % tak badhegi.",
               confidence="MEDIUM", validation="UNTESTED")
    before = dict(row)
    lab.run_lab("q", [row])
    assert row == before


# ── 10. pass hona kabhi "proven" na bane ─────────────────────────────────────

def test_pass_is_never_presented_as_proof():
    report = lab.run_lab("q", [_hyp("RV-HYP-23", "Tc 250 K se zyada hoga.")],
                         pack=_Pack(_Src("S1", "Tc 260 K")))
    block = _first(report)
    assert block["verdict"] == lab.TESTED_PASS
    assert block["is_established_fact"] is False
    assert block["real_world_experiment_pending"] is True
    assert "asli duniya ka experiment abhi bhi baaki" in report["disclaimer"]
    section = lab.lab_report_section(report)
    assert "proof nahi" in section
    assert "sach sabit ho gaya\" NAHI hai" in section
    for word in ("proven", "PROVEN", "established fact", "guaranteed"):
        assert word not in section
    assert any("NAHI hai" in line for line in lab.lab_limits(report))


def test_section_uses_a_sub_heading_so_answer_sections_do_not_change():
    """`### ...` — `##` hota to answer_order ko ek extra section dikhta."""
    assert lab.LAB_SUBHEADING.startswith("### ")
    assert not lab.LAB_SUBHEADING.startswith("## ")
    assert answer_order._TOP_HEADING_RE.match(lab.LAB_SUBHEADING) is None
    assert answer_order._TOP_HEADING_RE.match(
        f"## {answer_order.LAB_HEADING}") is not None


# ── 11. merge — purani keys chhui na jaayein, missing block PASS na bane ──────

def test_merge_adds_lab_without_touching_old_keys():
    rows = [_hyp("RV-HYP-24", "Tc 250 K se zyada hoga.",
                 confidence="MEDIUM", validation="UNTESTED", novelty="UNKNOWN")]
    report = lab.run_lab("q", rows, pack=_Pack(_Src("S1", "Tc 260 K")))
    merged = lab.merge_into_hypotheses(rows, report)
    assert len(merged) == 1
    row = merged[0]
    for key, value in rows[0].items():
        assert row[key] == value, key
    assert row["lab_verdict"] == lab.TESTED_PASS
    assert row["lab"]["is_established_fact"] is False
    assert row["lab"]["real_world_experiment_pending"] is True
    assert rows[0].get("lab") is None      # original dict chhua nahi gaya


def test_merge_marks_missing_blocks_not_run_never_pass():
    rows = [_hyp("RV-HYP-25", "Kuch hoga.")]
    merged = lab.merge_into_hypotheses(rows, {"hypotheses": []})
    assert merged[0]["lab_verdict"] == lab.NOT_RUN
    assert merged[0]["lab"]["verdict_reason"] == "lab_did_not_run"
    merged = lab.merge_into_hypotheses(rows, None)
    assert merged[0]["lab_verdict"] == lab.NOT_RUN


def test_verdict_for_unknown_id_is_not_run():
    report = lab.run_lab("q", [_hyp("RV-HYP-26", "Tc 250 K se zyada hoga.")],
                         pack=_Pack(_Src("S1", "Tc 260 K")))
    assert lab.verdict_for(report, "RV-HYP-26") == lab.TESTED_PASS
    assert lab.verdict_for(report, "RV-HYP-999") == lab.NOT_RUN
    assert lab.verdict_for(None, "RV-HYP-26") == lab.NOT_RUN


# ── 12. wiring — stage sach me pipeline me juda hai (naam nahi, jagah) ────────

def test_orchestrator_runs_the_lab_after_hypotheses():
    source = inspect.getsource(orchestrator)
    assert "from . import lab" in source
    assert 'out["lab"] = lab.run_lab(' in source
    assert "lab.merge_into_hypotheses(" in source
    # Answer banane wale call me lab ka record jaata hai.
    assert 'lab_report=passes.get("lab")' in source
    # ResearchResult tak bhi (UI/API ko text parse na karna pade).
    assert 'lab=passes.get("lab")' in source
    # Kram: lab hypothesis parse ke BAAD chalta hai.
    assert (source.index("honesty_check(parsed)")
            < source.index('out["lab"] = lab.run_lab('))


def test_research_result_carries_the_lab_block():
    result = ResearchResult().to_dict()
    assert "lab" in result
    assert result["lab"] == {}      # khaali = stage chala hi nahi


def test_synthesizer_accepts_and_prints_the_lab_report():
    params = inspect.signature(synthesizer_claude.FinalSynthesizer.assemble).parameters
    assert "lab_report" in params
    assert params["lab_report"].default is None
    audit = inspect.signature(
        synthesizer_claude.FinalSynthesizer._audit_section).parameters
    assert "lab_report" in audit
    source = inspect.getsource(synthesizer_claude)
    assert "lab_report_section(lab_report)" in source
    assert "lab_limits(lab_report)" in source


def test_lab_section_reaches_the_answer_text():
    """Sirf import nahi — block sach me answer string me aata hai."""
    report = lab.run_lab("q", [_hyp("RV-HYP-27", "Tc 250 K se zyada hoga.")],
                         pack=_Pack(_Src("S1", "Tc 260 K")))
    section = lab.lab_report_section(report)
    assert lab.LAB_SUBHEADING in section
    assert "RV-HYP-27" in section
    assert "TESTED_PASS" in section
    assert "260 K" in section


def test_chatgpt_owned_facade_forwards_the_new_kwarg():
    """`synthesizer.FinalSynthesizer` ChatGPT ka hai — usko chhua nahi gaya.

    Wo `*args, **kwargs` forward karta hai, isliye `lab_report` bina us file
    ko badle Claude-owned assemble tak pahunch jaata hai. Ye test us bharose
    ko pin karta hai: kal wahan signature saaf ho gaya to yahan RED aayega.
    """
    from research_engine import synthesizer as chatgpt_synth
    assert issubclass(chatgpt_synth.FinalSynthesizer,
                      synthesizer_claude.FinalSynthesizer)
    params = inspect.signature(chatgpt_synth.FinalSynthesizer.assemble).parameters
    kinds = {p.kind for p in params.values()}
    assert inspect.Parameter.VAR_KEYWORD in kinds


# ── 13. limits NAAPI hui hon, generic disclaimer nahi ─────────────────────────

def test_limits_are_counted_not_boilerplate():
    rows = [_hyp("RV-HYP-28", "Tc 250 K se zyada hoga."),
            _hyp("RV-HYP-29", "Yield 20 % se 12 % tak badhegi.")]
    report = lab.run_lab("q", rows, pack=_Pack(_Src("S1", "Tc 260 K")))
    limits = lab.lab_limits(report)
    assert any(line.startswith("1 hypothesis") and "pass hui" in line
               for line in limits)
    assert any("1 hypothesis" in line and "FAIL hui" in line for line in limits)
    # Jo hua hi nahi uski line aati hi nahi (ye #116 ka asli point hai).
    assert not any("walk-forward" in line for line in limits)


def test_budget_warning_says_not_run_not_failed():
    policy = lab.LabPolicy(max_wall_seconds=-1.0)
    report = lab.run_lab("q", [_hyp("RV-HYP-30",
                                    "Yield 12 % se 20 % tak badhegi.")],
                         policy=policy)
    assert report["budget_exhausted"] is True
    assert _first(report)["verdict"] == lab.NOT_RUN
    assert any("'fail' nahi, 'nahi hua'" in w for w in report["warnings"])
    assert any("budget khatam" in line for line in lab.lab_limits(report))


def test_evidence_text_keeps_source_ids_and_respects_the_cap():
    pack = _Pack(_Src("S1", title="Tc 260 K"), _Src("S2", snippet="Tc 265 K"))
    text = lab.evidence_text(pack)
    assert "[S1]" in text and "[S2]" in text
    tiny = lab.evidence_text(pack, lab.LabPolicy(max_evidence_chars=12))
    assert len(tiny) <= 12


def test_safety_sensitive_flag_survives_into_every_test_result():
    """Non-negotiable: safety-sensitive par risk review chhoot na jaaye."""
    report = lab.run_lab("q", [_hyp("RV-HYP-31", "Tc 250 K se zyada hoga.",
                                    safety_sensitive=True)],
                         pack=_Pack(_Src("S1", "Tc 260 K")))
    block = _first(report)
    assert block["verdict"] == lab.TESTED_PASS      # pass hone par BHI
    assert block["requires_risk_review"] is True
    assert block["risk_note"] == lab.RISK_REVIEW_NOTE
    assert all(t["requires_risk_review"] is True for t in block["tests"])
    assert lab.RISK_REVIEW_NOTE in lab.lab_report_section(report)


# ── 14. end-to-end: block sach me FINAL answer text me aata hai ──────────────

def _answer_with_lab(lab_report):
    """Production wala synthesizer (ChatGPT-owned facade) se poora answer."""
    from research_engine.models import EvidencePack, SourceRecord, SourceType
    from research_engine.synthesizer import FinalSynthesizer

    source = SourceRecord(
        title="Superconductivity onset at 260 K", url="https://example.org/a",
        snippet="Tc 260 K reported for this family.", connector="openalex",
        source_type=SourceType.PAPER, year=2024, peer_reviewed=True,
        relevance_score=0.8)
    source.source_id = "S1"
    source.read_level = "abstract"
    pack = EvidencePack(sources=[source], topic_terms=["superconductivity"])
    hypotheses = [_hyp("RV-HYP-32", "Is family ka Tc 250 K se zyada hoga.")]
    report = lab.run_lab("Tc kitna hoga?", hypotheses, pack=pack)
    merged = lab.merge_into_hypotheses(hypotheses, report)
    answer = FinalSynthesizer().assemble(
        gemini_answer="Tc 260 K ke aas paas bataya gaya hai [S1].", pack=pack,
        evidence_level="🟡 MIXED", confidence_note="Evidence bata hua hai.",
        contradictions=[], hypotheses=merged, verification={}, coverage={},
        honesty={}, consensus={}, lab_report=lab_report)
    return report, answer


def test_lab_block_appears_in_the_final_answer():
    report, answer = _answer_with_lab(None)
    _, with_lab = _answer_with_lab(report)
    assert lab.LAB_SUBHEADING in with_lab
    assert "RV-HYP-32" in with_lab
    assert "TESTED_PASS" in with_lab
    # Per-test line bhi poori aati hai: recipe + status + naapa + daawa.
    # (Sirf "TESTED_PASS in answer" kaafi nahi — wo disclaimer me bhi hai,
    #  isliye per-test line ko alag se pin kiya.)
    assert "`threshold` | TESTED_PASS" in with_lab
    assert "naapa: 260 K [S1]" in with_lab
    assert "daawa: > 250 K" in with_lab
    # Naapi hui seema audit me bhi jaati hai.
    assert "app ke apne andar ke test" in with_lab
    # LAB ka apna `##` section nahi banta — wo answer_order ka hai.
    assert f"## {answer_order.LAB_HEADING}" in with_lab
    assert f"\n## {lab.LAB_SUBHEADING[4:]}" not in with_lab
    # Purane caller (bina lab_report) par jawab me LAB block nahi aata,
    # aur kuch toota bhi nahi — stage additive hai.
    assert lab.LAB_SUBHEADING not in answer
    assert "TESTED_PASS" not in answer
    assert len(answer) > 200


def test_answer_sections_do_not_change_when_lab_runs():
    """LAB aane se answer ke `##` section na badhein, na ghatein."""
    report, plain = _answer_with_lab(None)
    _, with_lab = _answer_with_lab(report)

    def headings(text):
        return [line for line in text.splitlines()
                if answer_order._TOP_HEADING_RE.match(line)]

    assert headings(with_lab) == headings(plain)






