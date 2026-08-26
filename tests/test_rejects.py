"""#117 — reject-list ke tests: hypothesis hataayi to KYUN, naapi hui wajah ke saath.

Ye file `research_engine/rejects.py` (Claude-owned) ka behaviour pin karti hai,
aur uske saath teen jagah ki wiring bhi:
  * `hypothesis.parse()` ke do chup-chaap drops ab record hote hain,
  * `orchestrator` ledger ko LAB ke BAAD banata hai,
  * production synthesizer (ChatGPT-owned facade) tak `reject_report` pahunchta
    hai aur answer me `###` block ban jaata hai.

Niyam jo yahan pin hue hain (intel ki baat ka code-roop):
  1. bina naap ke reject nahi — naap na ho to `unexplained_drop` + warning,
  2. reject = "aage nahi badhaya", DELETE nahi — record aur text rehta hai,
  3. reject ≠ "galat sabit ho gaya" — `is_disproved` hamesha False, aur
     `reopen_if` batata hai wapas kab aa sakti hai,
  4. zero Gemini call, ₹0.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import answer_order, rejects           # noqa: E402


# ── chhote helper ────────────────────────────────────────────────────────────
def _lab_fail_hypothesis(hid="RV-HYP-2", statement="Tc 400 K se zyada hoga."):
    return {
        "hypothesis_id": hid,
        "statement": statement,
        "lab_verdict": "TESTED_FAIL",
        "lab": {
            "verdict_reason": "naapa hua number daawe se ulta nikla",
            "tests": [{"recipe": "threshold", "status": "TESTED_FAIL",
                       "observed": "260 K [S1]", "expected": "> 400 K",
                       "evidence_ids": ["S1"]}],
        },
        "is_testable": True,
        "has_prediction": True,
    }


def _safety_hypothesis(hid="RV-HYP-3"):
    return {"hypothesis_id": hid, "statement": "Ye dawa patient par kaam karegi.",
            "safety_sensitive": True, "risks": "",
            "is_testable": False, "has_prediction": False}


def _kept_hypothesis(hid="RV-HYP-4"):
    return {"hypothesis_id": hid, "statement": "Thin film me Tc kam hoga.",
            "is_testable": True, "has_prediction": True,
            "lab_verdict": "TESTED_PASS", "confidence_band": "MODERATE",
            "provenance": {"facts_used": ["S1", "S2"]}}


# ── 1. naap ke bina reject nahi (poore module ka sabse zaroori guard) ────────
def test_reject_without_measurement_becomes_unexplained_drop():
    reject = rejects.make_reject(hypothesis_id="RV-HYP-1",
                                 reason_code=rejects.LAB_TEST_FAILED,
                                 measured={})
    assert reject.reason_code == rejects.UNEXPLAINED_DROP
    # Asli maanga hua code bhi bhula nahi jaata — wo naap me darj rehta hai.
    assert reject.measured["original_reason_code"] == rejects.LAB_TEST_FAILED
    assert reject.blocking is True


def test_empty_looking_measurement_is_not_a_measurement():
    """Khaali string / None / khaali list — ye naap nahi, dikhawa hai."""
    for fake in ({"observed": ""}, {"observed": None}, {"observed": []},
                 {"a": "", "b": None}):
        reject = rejects.make_reject(reason_code=rejects.SAFETY_RISKS_MISSING,
                                     measured=fake)
        assert reject.reason_code == rejects.UNEXPLAINED_DROP, fake


def test_zero_is_a_real_measurement():
    """0 aur False asli naap hain — inhe 'khaali' maan lena bug hoga."""
    reject = rejects.make_reject(reason_code=rejects.SAFETY_RISKS_MISSING,
                                 measured={"risks_likhe_gaye_chars": 0})
    assert reject.reason_code == rejects.SAFETY_RISKS_MISSING
    other = rejects.make_reject(reason_code=rejects.NOT_TESTABLE_NO_PREDICTION,
                                measured={"is_testable": False})
    assert other.reason_code == rejects.NOT_TESTABLE_NO_PREDICTION


def test_unknown_reason_code_is_not_invented():
    reject = rejects.make_reject(reason_code="kuch_bhi",
                                 measured={"x": 1})
    assert reject.reason_code == rejects.UNEXPLAINED_DROP


def test_unknown_stage_falls_back_to_quality():
    reject = rejects.make_reject(stage="jadoo", reason_code=rejects.LAB_TEST_FAILED,
                                 measured={"lab_verdict": "TESTED_FAIL"})
    assert reject.stage == rejects.STAGE_QUALITY
    assert rejects.STAGES == (rejects.STAGE_PARSE, rejects.STAGE_LAB,
                              rejects.STAGE_QUALITY)


# ── 2. har code ki apni wajah aur apna reopen_if ────────────────────────────
def test_every_code_has_its_own_reason_and_reopen_line():
    assert len(rejects.REJECT_CODES) == 6
    reasons = set()
    reopens = set()
    for code in rejects.REJECT_CODES:
        reject = rejects.make_reject(reason_code=code, measured={"x": 1})
        assert reject.reason.strip(), code
        assert reject.reopen_if.strip(), code
        reasons.add(reject.reason)
        reopens.add(reject.reopen_if)
    # Ek hi jumla sab par chipka dena "wajah batana" nahi hota.
    assert len(reasons) == 6
    assert len(reopens) == 6


def test_reject_is_never_disproved():
    for code in rejects.REJECT_CODES:
        row = rejects.make_reject(reason_code=code, measured={"x": 1}).to_dict()
        assert row["is_disproved"] is False, code
        assert row["app_decision_only"] is True, code
        assert row["reopen_if"].strip(), code


def test_blocking_codes_do_not_include_parse_stage_codes():
    """Cap/no-statement wale block answer tak pahunche hi nahi — wo 'blocking' nahi."""
    assert rejects.OVER_EVIDENCE_CAP not in rejects.BLOCKING_CODES
    assert rejects.NO_STATEMENT_IN_BLOCK not in rejects.BLOCKING_CODES
    assert rejects.LAB_TEST_FAILED in rejects.BLOCKING_CODES
    assert rejects.SAFETY_RISKS_MISSING in rejects.BLOCKING_CODES
    assert rejects.UNEXPLAINED_DROP in rejects.BLOCKING_CODES


# ── 3. LAB (#116) ka fail asli naap ke saath reject banta hai ───────────────
def test_lab_fail_becomes_a_measured_reject():
    out = rejects.lab_rejects([_lab_fail_hypothesis()])
    assert len(out) == 1
    reject = out[0]
    assert reject.reason_code == rejects.LAB_TEST_FAILED
    assert reject.stage == rejects.STAGE_LAB
    # LAB ke apne shabd uthaye jaate hain — apni taraf se number nahi banate.
    assert reject.measured["naapa_gaya"] == "260 K [S1]"
    assert reject.measured["daawa_tha"] == "> 400 K"
    assert reject.measured["recipe"] == "threshold"
    assert reject.evidence_ids == ["S1"]


def test_lab_pass_and_other_verdicts_are_not_rejects():
    for verdict in ("TESTED_PASS", "DATA_MISSING", "NOT_TESTABLE_HERE",
                    "NOT_RUN", ""):
        hypothesis = _lab_fail_hypothesis()
        hypothesis["lab_verdict"] = verdict
        assert rejects.lab_rejects([hypothesis]) == [], verdict


def test_lab_fail_without_test_detail_is_still_measured():
    """Verdict TESTED_FAIL hai par test list gayab — phir bhi naap bachi rehni chahiye."""
    hypothesis = _lab_fail_hypothesis()
    hypothesis["lab"] = {}
    reject = rejects.lab_rejects([hypothesis])[0]
    assert reject.reason_code == rejects.LAB_TEST_FAILED
    assert reject.measured["lab_verdict"] == "TESTED_FAIL"


def test_failing_lab_test_is_picked_not_the_first_one():
    hypothesis = _lab_fail_hypothesis()
    hypothesis["lab"]["tests"] = [
        {"recipe": "numeric_formula", "status": "TESTED_PASS",
         "observed": "1", "expected": "1"},
        {"recipe": "threshold", "status": "TESTED_FAIL",
         "observed": "260 K", "expected": "> 400 K"},
    ]
    reject = rejects.lab_rejects([hypothesis])[0]
    assert reject.measured["recipe"] == "threshold"
    assert reject.measured["naapa_gaya"] == "260 K"


# ── 4. quality reject: sirf do haalat, dono naapi hui ──────────────────────
def test_safety_sensitive_without_risks_is_rejected():
    reject = rejects.quality_rejects([_safety_hypothesis()])[0]
    assert reject.reason_code == rejects.SAFETY_RISKS_MISSING
    assert reject.measured["risks_likhe_gaye_chars"] == 0
    assert reject.measured["kam_se_kam_chahiye_chars"] == rejects.MIN_RISK_CHARS


def test_safety_sensitive_with_real_risks_is_not_rejected():
    hypothesis = _safety_hypothesis()
    hypothesis["risks"] = "Dose zyada hone par liver damage ka risk hai."
    hypothesis["is_testable"] = True
    hypothesis["has_prediction"] = True
    assert rejects.quality_rejects([hypothesis]) == []


def test_untestable_needs_both_missing():
    """Sirf ek field ki kami warning ka kaam hai — reject dono par hota hai."""
    only_testable = {"hypothesis_id": "A", "statement": "x",
                     "is_testable": True, "has_prediction": False}
    only_prediction = {"hypothesis_id": "B", "statement": "y",
                       "is_testable": False, "has_prediction": True}
    both_missing = {"hypothesis_id": "C", "statement": "z",
                    "is_testable": False, "has_prediction": False}
    assert rejects.quality_rejects([only_testable]) == []
    assert rejects.quality_rejects([only_prediction]) == []
    out = rejects.quality_rejects([both_missing])
    assert len(out) == 1
    assert out[0].reason_code == rejects.NOT_TESTABLE_NO_PREDICTION


def test_safety_beats_untestable_and_the_other_code_survives():
    reject = rejects.quality_rejects([_safety_hypothesis()])[0]
    assert reject.reason_code == rejects.SAFETY_RISKS_MISSING
    # Doosri baat chhupti nahi — `also_codes` me darj rehti hai.
    assert reject.also_codes == [rejects.NOT_TESTABLE_NO_PREDICTION]


def test_min_risk_chars_matches_honesty_check():
    """Do jagah do hadd rakhna hi purani galti thi — number ek hi rahe."""
    import research_engine.hypothesis as hypothesis_module

    source = open(hypothesis_module.__file__, "r", encoding="utf-8").read()
    # Poori expression pin karo, warna kahin bhi likha ") < 20" is test ko
    # jhootha green de deta hai (hypothesis.py me aise teen line pehle se hain).
    assert (f'len((h.risks or "").strip()) < {rejects.MIN_RISK_CHARS}:'
            in source)


# ── 5. ledger: dedupe, priority, ginti ──────────────────────────────────────
def test_one_hypothesis_two_problems_is_one_record_with_both_codes():
    hypothesis = _lab_fail_hypothesis()
    hypothesis["safety_sensitive"] = True
    hypothesis["risks"] = ""
    hypothesis["is_testable"] = False
    hypothesis["has_prediction"] = False
    ledger = rejects.build_ledger([hypothesis])
    assert len(ledger["rejected"]) == 1
    row = ledger["rejected"][0]
    # Safety sabse bhaari hai.
    assert row["reason_code"] == rejects.SAFETY_RISKS_MISSING
    assert rejects.LAB_TEST_FAILED in row["also_codes"]
    assert rejects.NOT_TESTABLE_NO_PREDICTION in row["also_codes"]
    # Dono taraf ki naap ek hi record me mil jaati hai.
    assert row["measured"]["risks_likhe_gaye_chars"] == 0
    assert row["measured"]["naapa_gaya"] == "260 K [S1]"


def test_ledger_counts_and_kept_are_measured():
    rows = [_lab_fail_hypothesis(), _safety_hypothesis(), _kept_hypothesis()]
    ledger = rejects.build_ledger(rows)
    assert ledger["ran"] is True
    assert ledger["checked"] == 3
    assert len(ledger["rejected"]) == 2
    assert len(ledger["kept"]) == 1
    assert ledger["counts"] == {rejects.LAB_TEST_FAILED: 1,
                               rejects.SAFETY_RISKS_MISSING: 1}
    assert ledger["blocking"] == 2
    assert ledger["gemini_calls"] == 0
    assert ledger["provider_cost"] == 0
    kept = ledger["kept"][0]
    assert kept["hypothesis_id"] == "RV-HYP-4"
    # Rakhna bhi saboot nahi hai, aur rakhne ki bhi naap jaati hai.
    assert kept["kept_is_not_proof"] is True
    assert kept["measured"]["lab_verdict"] == "TESTED_PASS"
    assert kept["measured"]["evidence_facts_used"] == 2


def test_same_reason_code_twice_is_counted_twice():
    """Ginti sach me badhe — do lab-fail par counts 2 hona chahiye, 1 nahi."""
    rows = [_lab_fail_hypothesis("RV-HYP-1", "Tc 400 K se zyada hoga."),
            _lab_fail_hypothesis("RV-HYP-2", "Tc 500 K se zyada hoga.")]
    ledger = rejects.build_ledger(rows)
    assert ledger["counts"] == {rejects.LAB_TEST_FAILED: 2}
    assert len(ledger["rejected"]) == 2
    joined = " ".join(rejects.reject_limits(ledger))
    assert f"Reject wajah `{rejects.LAB_TEST_FAILED}`: 2" in joined


def test_ledger_never_mutates_input_hypotheses():
    rows = [_lab_fail_hypothesis(), _safety_hypothesis(), _kept_hypothesis()]
    before = [dict(row) for row in rows]
    ledger = rejects.build_ledger(rows)
    rejects.apply_to_hypotheses(rows, ledger)
    assert rows == before


def test_ledger_warns_when_everything_was_rejected():
    ledger = rejects.build_ledger([_lab_fail_hypothesis()])
    joined = " ".join(ledger["warnings"])
    assert "Saari hypotheses reject" in joined
    # Aur wo warning jhootha matlab nahi deti.
    assert "'sawaal ka jawab nahi" in joined


def test_ledger_reports_the_shortfall_with_the_evidence_reason():
    ledger = rejects.build_ledger([_lab_fail_hypothesis(), _kept_hypothesis()],
                                 requested=3,
                                 gate={"reason": "sirf 2 snippet-only source mile"})
    joined = " ".join(ledger["warnings"])
    assert "Aapne 3 maangi thi, 1 aage badhi" in joined
    assert "sirf 2 snippet-only source mile" in joined


def test_no_reject_does_not_mean_all_good():
    ledger = rejects.build_ledger([_kept_hypothesis()])
    assert ledger["rejected"] == []
    assert "'sab sahi" in ledger["note"]
    assert ledger["warnings"] == []


def test_unexplained_drop_raises_a_warning():
    ledger = rejects.build_ledger(
        [], parse_records=[{"reason_code": "over_evidence_cap",
                            "statement": "kuch", "measured": {}}])
    assert ledger["unexplained"] == 1
    assert any("bina naapi hui wajah" in w for w in ledger["warnings"])
    assert ledger["rejected"][0]["reason_code"] == rejects.UNEXPLAINED_DROP


def test_non_dict_rows_do_not_crash_the_ledger():
    ledger = rejects.build_ledger([None, "abc", _kept_hypothesis()],
                                 parse_records=[None, 7])
    assert ledger["checked"] == 1
    assert ledger["rejected"] == []


def test_hypotheses_without_ids_are_still_tracked_by_text():
    rows = [{"statement": "Ye baat naapne layak nahi hai bilkul.",
             "is_testable": False, "has_prediction": False}]
    ledger = rejects.build_ledger(rows)
    assert len(ledger["rejected"]) == 1
    assert ledger["rejected"][0]["hypothesis_id"] == ""
    assert ledger["rejected"][0]["statement"].startswith("Ye baat naapne")
    assert ledger["kept"] == []


# ── 6. parse-stage: chup-chaap drop khatam ─────────────────────────────────
_MODEL_TEXT = """## Hypothesis 1
Statement: Is family ka Tc 250 K se zyada hoga kyunki doping badhti hai.

## Hypothesis 2
Statement: Pressure badhane par Tc aur badhega, 300 K tak ja sakta hai.

## Hypothesis 3
Statement: Thin film me Tc kam ho jaayega, strain lattice badalta hai isliye.

## Hypothesis 4
Statement: Chautha idea bhi isi tarah aage badh sakta hai agar data mile.

## Hypothesis 5
- ok
"""


def test_parse_records_the_over_cap_drop_with_numbers():
    from research_engine.hypothesis import HypothesisEngine

    log = []
    out = HypothesisEngine().parse(_MODEL_TEXT, max_count=3, rejects=log)
    assert len(out) == 3
    assert [row["reason_code"] for row in log] == ["over_evidence_cap"] * 2
    first = log[0]
    assert first["measured"] == {"model_ne_bheji": 5, "cap_allowed": 3,
                                 "block_number": 4}
    # Gire hue block ka daawa bhi dikhta hai — pehle wo kabhi dikhta hi nahi tha.
    assert first["statement"].startswith("Chautha idea")


def test_parse_records_the_no_statement_drop_with_numbers():
    from research_engine.hypothesis import HypothesisEngine

    log = []
    out = HypothesisEngine().parse(_MODEL_TEXT, max_count=5, rejects=log)
    assert len(out) == 4
    assert [row["reason_code"] for row in log] == ["no_statement_in_block"]
    measured = log[0]["measured"]
    assert measured["lines"] == 1
    assert measured["sabse_lambi_line_chars"] == 2
    assert measured["kam_se_kam_chahiye_chars"] == 26


def test_parse_still_works_without_the_rejects_argument():
    """Purane caller na toote — `rejects` optional hai."""
    from research_engine.hypothesis import HypothesisEngine

    engine = HypothesisEngine()
    assert len(engine.parse(_MODEL_TEXT, max_count=3)) == 3
    assert len(engine.parse(_MODEL_TEXT)) == 3
    assert engine.parse("", rejects=[]) == []


def test_parse_rejects_turns_records_into_measured_rows():
    out = rejects.parse_rejects([
        {"reason_code": "over_evidence_cap", "statement": "chautha",
         "index": 4, "measured": {"model_ne_bheji": 4, "cap_allowed": 3}},
        {"reason_code": "no_statement_in_block", "statement": "",
         "index": 5, "measured": {"block_chars": 4}},
    ])
    assert [r.reason_code for r in out] == ["over_evidence_cap",
                                            "no_statement_in_block"]
    assert all(r.stage == rejects.STAGE_PARSE for r in out)
    assert out[0].index == 4


def test_parse_stage_rejects_come_before_lab_and_quality_ones():
    ledger = rejects.build_ledger(
        [_lab_fail_hypothesis()],
        parse_records=[{"reason_code": "over_evidence_cap", "statement": "chautha",
                        "measured": {"model_ne_bheji": 4, "cap_allowed": 3}}])
    codes = [row["reason_code"] for row in ledger["rejected"]]
    assert codes == [rejects.OVER_EVIDENCE_CAP, rejects.LAB_TEST_FAILED]


# ── 7. hypothesis dicts par nishaan — hataye bina ─────────────────────────
def test_apply_marks_but_never_deletes():
    rows = [_lab_fail_hypothesis(), _kept_hypothesis()]
    ledger = rejects.build_ledger(rows)
    marked = rejects.apply_to_hypotheses(rows, ledger)
    assert len(marked) == 2
    bad, good = marked
    assert bad["rejected"] is True
    assert bad["reject_reason_code"] == rejects.LAB_TEST_FAILED
    assert bad["reject_reason"].strip()
    assert bad["reject_reopen_if"].strip()
    assert bad["reject_measured"]["naapa_gaya"] == "260 K [S1]"
    # Purani keys aur statement jaise the waise hi hain — kuch mita nahi.
    assert bad["statement"] == "Tc 400 K se zyada hoga."
    assert bad["lab_verdict"] == "TESTED_FAIL"
    assert bad["is_disproved"] is False
    # Jo bachi, uske paas bhi keys hain (UI ko "key hi nahi" na dekhna pade).
    assert good["rejected"] is False
    assert good["reject_reason_code"] == ""
    assert good["reject_measured"] == {}


def test_apply_without_ledger_marks_everyone_as_not_rejected():
    marked = rejects.apply_to_hypotheses([_lab_fail_hypothesis()], None)
    assert marked[0]["rejected"] is False
    assert marked[0]["is_disproved"] is False


def test_reject_map_only_keeps_rows_with_ids():
    ledger = rejects.build_ledger(
        [{"statement": "bina id wali baat jo naapi nahi ja sakti.",
          "is_testable": False, "has_prediction": False}])
    assert rejects.reject_map(ledger) == {}
    assert rejects.reject_map(None) == {}


# ── 8. answer ka `###` block ───────────────────────────────────────────────
def test_reject_section_is_a_sub_heading_not_a_top_section():
    """`##` karne se answer_order ek extra top-level section gin leta hai."""
    assert rejects.REJECT_SUBHEADING.startswith("### ")
    assert not answer_order._TOP_HEADING_RE.match(rejects.REJECT_SUBHEADING)


def test_reject_section_prints_reason_measurement_and_reopen():
    rows = [_lab_fail_hypothesis(), _safety_hypothesis()]
    text = rejects.reject_section(rejects.build_ledger(rows))
    assert rejects.REJECT_SUBHEADING in text
    assert "RV-HYP-2" in text
    assert "aage nahi badhaya" in text
    # Sirf label "- Kyun:" pin karna kaafi nahi tha — wajah ki jagah "dekh lo"
    # likh dene par bhi test green ho jaata tha. Isliye poori wajah pin ki hai.
    assert ("- Kyun: App ne khud (#116 LAB) iska hisaab chalaya aur naapa hua "
            "number daawe se ulta nikla" in text)
    assert ("- Kyun: Ye medical/chemical/biological ya safety se judi baat hai "
            "par risks/safety check likhe hi nahi gaye" in text)
    assert "- Naap: lab_verdict=TESTED_FAIL" in text
    assert "naapa_gaya=260 K [S1]" in text
    assert "daawa_tha=> 400 K" in text
    assert "- Kis source par naapa: [S1]" in text
    assert "- Wapas kab aa sakti hai:" in text
    assert rejects.NOT_TESTABLE_NO_PREDICTION in text     # also_codes bhi dikhe


def test_reject_section_says_reject_is_not_disproof():
    text = rejects.reject_section(rejects.build_ledger([_lab_fail_hypothesis()]))
    assert "'galat sabit ho gaya' NAHI hai" in text


def test_reject_section_is_empty_when_nothing_was_rejected():
    assert rejects.reject_section(None) == ""
    assert rejects.reject_section({}) == ""
    assert rejects.reject_section(rejects.build_ledger([_kept_hypothesis()])) == ""


def test_reject_section_names_blocks_that_had_no_id():
    text = rejects.reject_section(rejects.build_ledger(
        [], parse_records=[{"reason_code": "no_statement_in_block",
                            "statement": "",
                            "measured": {"block_chars": 4, "lines": 1}}]))
    assert "(bina naam wala block)" in text
    assert "block_chars=4" in text


def test_measured_line_drops_empty_values_only():
    line = rejects._measured_line({"a": 0, "b": "", "c": None, "d": [],
                                   "e": False, "f": "x"})
    assert "a=0" in line and "e=False" in line and "f=x" in line
    assert "b=" not in line and "c=" not in line and "d=" not in line


# ── 9. audit lines — ginti, boilerplate nahi ───────────────────────────────
def test_reject_limits_are_counted_not_boilerplate():
    rows = [_lab_fail_hypothesis(), _safety_hypothesis(), _kept_hypothesis()]
    lines = rejects.reject_limits(rejects.build_ledger(rows))
    joined = " ".join(lines)
    assert "2 hypothesis reject hui, 1 aage badhi" in joined
    assert f"Reject wajah `{rejects.LAB_TEST_FAILED}`: 1" in joined
    assert f"Reject wajah `{rejects.SAFETY_RISKS_MISSING}`: 1" in joined
    assert "'galat sabit' nahi hai" in joined


def test_reject_limits_flag_unexplained_drops_as_a_bug():
    ledger = rejects.build_ledger(
        [], parse_records=[{"reason_code": "over_evidence_cap",
                            "statement": "x", "measured": {}}])
    joined = " ".join(rejects.reject_limits(ledger))
    # Ginti wali line pin karo. Sirf "khula bug hai" dhoondhne par line badal kar
    # "Sab drop ki wajah mil gayi" likh dene par bhi test green reh jaata tha.
    assert ledger["unexplained"] == 1
    assert "1 drop ki naapi hui wajah nahi mili" in joined
    assert "ye khula bug hai, ise 'quality check' nahi maana ja sakta" in joined


def test_reject_limits_empty_when_ledger_did_not_run():
    assert rejects.reject_limits(None) == []
    assert rejects.reject_limits({}) == []
    assert rejects.reject_limits({"ran": False, "rejected": [{"a": 1}]}) == []


def test_reject_limits_say_zero_rejects_is_not_verification():
    lines = rejects.reject_limits(rejects.build_ledger([_kept_hypothesis()]))
    assert any("'sab verified'" in line for line in lines)


# ── 10. models + orchestrator wiring ──────────────────────────────────────
def test_research_result_carries_the_reject_ledger():
    from research_engine.models import ResearchResult

    empty = ResearchResult(question="q").to_dict()
    assert empty["rejects"] == {}
    filled = ResearchResult(question="q", rejects={"ran": True}).to_dict()
    assert filled["rejects"] == {"ran": True}


def test_orchestrator_builds_the_ledger_after_lab_and_forwards_it():
    """Ledger LAB ke BAAD bane — warna TESTED_FAIL reject hi nahi ban paayega."""
    import research_engine.orchestrator as orchestrator_module

    source = open(orchestrator_module.__file__, "r", encoding="utf-8").read()
    assert "from . import rejects" in source
    assert '"rejects": {}' in source
    assert "rejects=parse_rejects" in source
    merge_at = source.index("lab.merge_into_hypotheses")
    build_at = source.index("rejects.build_ledger")
    apply_at = source.index("rejects.apply_to_hypotheses")
    assert merge_at < build_at < apply_at
    assert "reject_report=passes.get(\"rejects\")" in source
    assert "rejects=passes.get(\"rejects\")" in source
    # Warnings user tak jaayein, chup-chaap na rahein.
    assert 'out["errors"].extend(out["rejects"].get("warnings") or [])' in source


# ── 11. end-to-end: production facade se answer me pahunchta hai ──────────
def _answer_with_rejects(reject_report, hypotheses):
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
    return FinalSynthesizer().assemble(
        gemini_answer="Tc 260 K ke aas paas bataya gaya hai [S1].", pack=pack,
        evidence_level="🟡 MIXED", confidence_note="Evidence bata hua hai.",
        contradictions=[], hypotheses=hypotheses, verification={}, coverage={},
        honesty={}, consensus={}, reject_report=reject_report)


def test_reject_block_reaches_the_final_answer():
    rows = [_lab_fail_hypothesis()]
    ledger = rejects.build_ledger(rows)
    marked = rejects.apply_to_hypotheses(rows, ledger)
    answer = _answer_with_rejects(ledger, marked)
    assert rejects.REJECT_SUBHEADING in answer
    # Card ke upar ka nishaan (ye line sirf card par aati hai).
    assert "REJECT — aage nahi badhaya:" in answer
    # `###` block ki naap wali line (ye sirf reject_section me hai).
    assert "- Naap: lab_verdict=TESTED_FAIL" in answer
    # Audit me ginti (ye sirf reject_limits se aati hai).
    assert "1 hypothesis reject hui, 0 aage badhi" in answer
    # Ledger na ho to purana behaviour — kuch toota nahi.
    plain = _answer_with_rejects(None, rows)
    assert rejects.REJECT_SUBHEADING not in plain
    assert "REJECT — aage nahi badhaya:" not in plain
    assert "- Naap: lab_verdict=TESTED_FAIL" not in plain
    assert len(plain) > 200


def test_answer_top_sections_do_not_change_when_rejects_run():
    rows = [_lab_fail_hypothesis()]
    ledger = rejects.build_ledger(rows)
    marked = rejects.apply_to_hypotheses(rows, ledger)

    def headings(text):
        return [line for line in text.splitlines()
                if answer_order._TOP_HEADING_RE.match(line)]

    assert headings(_answer_with_rejects(ledger, marked)) == \
        headings(_answer_with_rejects(None, rows))


def test_facade_forwards_new_kwargs_to_claude_owned_synthesizer():
    """ChatGPT-owned facade `**kwargs` forward karta hai — us bharose ko pin karo."""
    import inspect

    from research_engine.synthesizer import FinalSynthesizer as Facade
    from research_engine.synthesizer_claude import FinalSynthesizer as Base

    assert issubclass(Facade, Base)
    kinds = [p.kind for p in
             inspect.signature(Facade.assemble).parameters.values()]
    assert inspect.Parameter.VAR_KEYWORD in kinds
    assert "reject_report" in inspect.signature(Base.assemble).parameters
