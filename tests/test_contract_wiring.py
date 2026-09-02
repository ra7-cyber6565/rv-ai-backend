"""#178g — FARMAISH ke do contract ASLI ME CHALTE HAIN ya sirf likhe pade hain.

#171 ke baad ek imaandaar kami reh gayi thi: `exammodel.gate()` aur
`trademodel.study()` bane hue the, unke naap bhi bane the, par orchestrator un
tak ja hi nahi raha tha — contract sirf LAB recipe ke raste se ghoomta tha.
Matlab: "34 naap ka contract" file me tha, jawab me nahi. #178d/#178e/#178f ne
wo raste jode (orchestrator → synthesizer → ResearchResult). Ye file un raston
ke peeche padi hai, un khatron ke saath jo ASLI me ho sakte hain:

  1. RASTA CHUP-CHAAP KAT JAANA — kal koi `exam_contract` ka kwarg hata de aur
     sab test phir bhi green rahein. Isliye call ke ANDAR (bracket-match se)
     naapa jaata hai, poori file me needle dikh jaane par nahi.
  2. TEEN REPORT EK NA HO JAAYEIN — `lab_report` HYPOTHESIS ka test hai,
     `exam_lab_report` BANE HUE paper/plan ka, aur ye do FARMAISH ka hisaab.
     Heading, shabd aur audit ki chhat chaaron ki alag rehni chahiye; ek bhi
     jodi barabar ho gayi to "app ne test paas kiya" aur "farmaish ka aadha
     hissa naapa hi nahi gaya" ek jaise padhe jaayenge.
  3. CHHAT SE BURI KHABAR KATNA — `MAX_AUDIT_LIMIT_LINES` khaali call se banaya
     jaaye to asli run me aane wali AAKHRI line (jo batati hai ki kaunse point
     naape hi nahi ja sake) kat jaati hai. Chhat sabse BURE haal se banni
     chahiye.
  4. LANE MIXING — intel ki saaf shart: "sab mix mt kr dena". Gaane/science ke
     jawab me exam ya trading ka contract ek shabd bhi na chhape, aur exam ke
     jawab me trading ka na chhape.
  5. "KHAALI" KA MATLAB — `{}` matlab stage CHALI HI NAHI; `wanted: False`
     matlab farmaish is lane ki nahi thi. Dono ko ek jaisa padhna jhooth hai.
  6. ₹0 AUR OFFLINE — dono contract me na Gemini call hai, na network.
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import exammodel as em  # noqa: E402
from research_engine import lab  # noqa: E402
from research_engine import trademodel as tm  # noqa: E402
from research_engine.models import EvidencePack, ResearchResult  # noqa: E402
from research_engine.synthesizer_claude import FinalSynthesizer  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXAM_Q = ("RPF SI ka practice question paper banao 20 sawaal hindi me, answer "
          "key aur solution bhi do, easy medium hard mix rakho")
TRADE_Q = ("US100 aur XAUUSD ka intraday scalping model banao 15M context 5M "
           "confirmation 1M entry ke saath")
SONG_Q = "hindi me ek sad gaana likh do judaai wala"
SCIENCE_Q = "room temperature superconductivity ka evidence kya hai"

PAPER = """
Total marks: 40 | Duration: 60 minutes
Ye paper practice ke liye hai, kisi board ka official paper nahi hai.
Q1. 12 + 30 kitna hota hai? (easy)
Ans: 42
Q2. Bharat ka pehla railway budget kis saal aaya? (medium)
Ans: 1924
"""

SPEC = """
Execution chain: 15M context -> 5M confirmation -> 1M entry.
Expectancy 0.31R, profit factor 1.4, out-of-sample test alag data par chala.
Stop loss MAE ke hisaab se, target expectancy par optimise hua.
"""


def _read(name):
    path = os.path.join(ROOT, "research_engine", name)
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _call_args(source, marker):
    """Sirf US CALL ke andar ka text — poori file nahi.

    Ye tareeqa #134 me seekha gaya tha: `"x=x)"` jaisa needle agla kwarg judte
    hi toot jaata hai, behaviour theek hone par bhi.
    """
    call_at = source.index(marker)
    depth, end = 0, call_at
    for pos in range(source.index("(", call_at), len(source)):
        if source[pos] == "(":
            depth += 1
        elif source[pos] == ")":
            depth -= 1
            if depth == 0:
                end = pos
                break
    return source[call_at:end]


def _exam_report():
    return em.gate(EXAM_Q, paper=PAPER, plan=PAPER, syllabus="maths reasoning",
                   sources=[])


def _trade_report():
    return tm.study(TRADE_Q, spec=SPEC, sources=[], hypotheses=[],
                    lab_report={})


def _base():
    return dict(gemini_answer="Ye jawab hai.", evidence_level="MEDIUM",
                confidence_note="", contradictions=[], hypotheses=[],
                verification={}, coverage={}, honesty={}, consensus={})


# ── A. orchestrator dono contract ASLI ME chalata hai ────────────────────────

def test_a_orchestrator_dono_contract_ko_khud_call_karta_hai():
    """#171 ke baad asli kami yahi thi: contract bana tha, chalta nahi tha."""
    orch = _read("orchestrator.py")
    assert "from . import trademodel" in orch
    assert "from . import exammodel" in orch
    assert 'out["exam_contract"] = exammodel.gate(' in orch
    assert 'out["trade_contract"] = trademodel.study(' in orch
    # default keys — stage na chale to khaali dict, gayab key nahi
    assert '"exam_contract": {},' in orch
    assert '"trade_contract": {},' in orch
    # ek hi baar: do jagah call hone par ek copy chup-chaap purani reh jaati hai
    assert orch.count('out["exam_contract"] = exammodel.gate(') == 1
    assert orch.count('out["trade_contract"] = trademodel.study(') == 1
    # dono call asli text ke peeche khade hain — dead code (`if False:`) nahi
    assert "if contract_text:" in orch
    assert 'contract_text = out["final"] or out["analysis"]' in orch


def test_a_exam_gate_bounded_calculator_ke_saath_chalti_hai():
    """`evaluate=` na jude to ginti wale sawaal ka chalna kabhi naapa nahi jaata."""
    orch = _read("orchestrator.py")
    args = _call_args(orch, 'out["exam_contract"] = exammodel.gate(')
    assert "evaluate=" in args
    assert "SafeNumericExecutor" in args
    assert "NumericExecutionPolicy" in args
    assert "sources=" in args
    # `eval(`/`exec(` yahan aa jaana seedha khatra hai — bounded calculator hi
    # is app me numeric kaam karta hai.
    assert "eval(" not in args.replace("evaluate(", "")
    assert "exec(" not in args


def test_a_trade_contract_lab_ke_baad_chalta_hai():
    """LAB se pehle chala to 5 LAB-waale point hamesha NOT_MEASURED reh jaate."""
    orch = _read("orchestrator.py")
    lab_at = orch.index('out["lab"] = ')
    trade_at = orch.index('out["trade_contract"] = trademodel.study(')
    assert lab_at < trade_at
    args = _call_args(orch, 'out["trade_contract"] = trademodel.study(')
    assert "lab_report=" in args
    assert 'out.get("lab")' in args
    assert 'hypotheses=out["hypotheses"]' in args
    assert "spec=" in args


def test_a_synthesizer_aur_result_ka_wiring_apni_jagah_hai():
    """Ye static naap wiring chup-chaap kat jaane se bachati hai."""
    orch = _read("orchestrator.py")
    assert 'exam_contract_report=passes.get("exam_contract") or {},' in orch
    assert 'trade_contract_report=passes.get("trade_contract") or {},' in orch
    assert "exam_contract=exammodel.public_record(" in orch
    assert "trade_contract=trademodel.public_record(" in orch
    # purane lane ka wiring bhi waise hi rehna chahiye (jagah nahi cheeni gayi)
    assert 'exam_lab_report=passes.get("exam_lab") or {},' in orch
    assert "music_study=music_study.public_record(" in orch
    models = _read("models.py")
    assert "exam_contract: Dict = field(default_factory=dict)" in models
    assert "trade_contract: Dict = field(default_factory=dict)" in models


def test_a_audit_call_ke_andar_dono_report_jaati_hain():
    """Naap CALL ke andar hoti hai — poori file me needle dikhne par nahi."""
    syn = _read("synthesizer_claude.py")
    args = _call_args(syn, "self._audit_section(")
    for needle in ("exam_contract_report=exam_contract_report",
                   "trade_contract_report=trade_contract_report",
                   "exam_lab_report=exam_lab_report"):
        assert needle in args, needle
        assert args.count(needle) == 1, needle
    for needle in ("exam_contract_report: Optional[Dict] = None",
                   "trade_contract_report: Optional[Dict] = None"):
        # do jagah: `_audit_section` aur `assemble` — dono me
        assert syn.count(needle) == 2, needle
    assert "exam_contract_lines(exam_contract_report)" in syn
    assert "trade_contract_lines(trade_contract_report)" in syn


def test_a_dono_module_ka_naam_alias_ke_saath_import_hua_hai():
    """Bina alias `section_lines`/`limits` ek doosre ko dhak dete hain."""
    syn = _read("synthesizer_claude.py")
    assert "from .exammodel import section_lines as exam_contract_lines" in syn
    assert "from .trademodel import section_lines as trade_contract_lines" in syn
    assert "from .exammodel import limits as exam_contract_limits" in syn
    assert "from .trademodel import limits as trade_contract_limits" in syn
    import research_engine.synthesizer_claude as mod
    assert mod.exam_contract_lines is em.section_lines
    assert mod.trade_contract_lines is tm.section_lines
    assert mod.exam_contract_limits is em.limits
    assert mod.trade_contract_limits is tm.limits
    assert mod.EXAM_CONTRACT_MAX_AUDIT_LIMIT_LINES == em.MAX_AUDIT_LIMIT_LINES
    assert mod.TRADE_CONTRACT_MAX_AUDIT_LIMIT_LINES == tm.MAX_AUDIT_LIMIT_LINES


# ── B. chaar report chaar hi rehti hain ──────────────────────────────────────

def test_b_chaaron_report_ki_heading_alag_hai():
    """Ek jaisi heading = padhne wale ke liye do alag sach ek dikhna."""
    headings = [em.SECTION_HEADING, tm.SECTION_HEADING,
                lab.EXAM_LAB_SUBHEADING, lab.LAB_SUBHEADING]
    assert len(set(headings)) == 4
    for heading in headings:
        assert heading.startswith("###")
    # aur naam se pata chale kaunsi kis cheez ki hai
    assert "TRADING" in tm.SECTION_HEADING
    assert "EXAM" in em.SECTION_HEADING or "PADHAI" in em.SECTION_HEADING


def test_b_chaaron_audit_ki_chhat_alag_hai():
    """Chhat ek ho gayi to ek report ki seema doosri ke naap se kategi."""
    ceilings = {
        "exam_contract": em.MAX_AUDIT_LIMIT_LINES,
        "trade_contract": tm.MAX_AUDIT_LIMIT_LINES,
        "exam_lab": lab.EXAM_MAX_AUDIT_LIMIT_LINES,
        "lab": lab.MAX_AUDIT_LIMIT_LINES,
    }
    assert len(set(ceilings.values())) == 4, ceilings
    for name, value in ceilings.items():
        assert value >= 6, (name, value)


def test_b_chhat_sabse_bure_haal_se_banti_hai():
    """Khaali call se banti to "ye point naape hi nahi ja sake" line kat jaati."""
    for mod in (em, tm):
        empty = len(mod.limits({}))
        worst = len(mod.limits({"not_measured": list(mod.CONTRACT_IDS)}))
        assert empty < worst, mod.__name__
        assert mod.MAX_AUDIT_LIMIT_LINES == worst, mod.__name__
        run_lines = mod.limits({"not_measured": ["X1", "X2"]})
        assert len(run_lines) <= mod.MAX_AUDIT_LIMIT_LINES
        assert any("naape hi nahi" in line for line in run_lines)


# ── C. jawab me contract dikhta hai — sirf jab maanga gaya ho ────────────────

def test_c_exam_ka_contract_jawab_me_apni_seema_ke_saath_aata_hai():
    """Section aaye par seema kat jaaye — yahi sabse chupa hua jhooth hai."""
    pack = EvidencePack(question=EXAM_Q, sources=[])
    report = _exam_report()
    text = FinalSynthesizer().assemble(pack=pack, exam_contract_report=report,
                                       **_base())
    assert em.SECTION_HEADING in text
    assert em.NOT_EVIDENCE_LINE in text
    for line in em.limits(report):
        assert line in text                      # chhat kaat nahi rahi
    assert len(em.limits(report)) <= em.MAX_AUDIT_LIMIT_LINES
    # trading ka contract bina maange nahi ugta
    assert tm.SECTION_HEADING not in text


def test_c_trade_ka_contract_jawab_me_apni_seema_ke_saath_aata_hai():
    pack = EvidencePack(question=TRADE_Q, sources=[])
    report = _trade_report()
    text = FinalSynthesizer().assemble(pack=pack, trade_contract_report=report,
                                       **_base())
    assert tm.SECTION_HEADING in text
    assert tm.NOT_EVIDENCE_LINE in text
    for line in tm.limits(report):
        assert line in text
    assert len(tm.limits(report)) <= tm.MAX_AUDIT_LIMIT_LINES
    assert em.SECTION_HEADING not in text


def test_c_dono_contract_ek_saath_khade_reh_sakte_hain():
    """Ek doosre ko kha jaayein to ek lane ka poora hisaab gayab ho jaata hai."""
    pack = EvidencePack(question=EXAM_Q, sources=[])
    text = FinalSynthesizer().assemble(pack=pack,
                                       exam_contract_report=_exam_report(),
                                       trade_contract_report=_trade_report(),
                                       **_base())
    assert em.SECTION_HEADING in text and tm.SECTION_HEADING in text
    assert text.count(em.SECTION_HEADING) == 1
    assert text.count(tm.SECTION_HEADING) == 1


def test_c_buri_khabar_pehle_chhapti_hai():
    """MET pehle chhap gaya to padhne wala neeche ki kami padhta hi nahi.

    Dhyaan: "NOT MET" ka needle GINTI wali line me bhi hota hai
    ("Ginti: 9 MET / 8 NOT MET / ..."), jo hamesha sabse upar rehti hai —
    isliye kram sirf `**...(` wale BLOCK-heading se naapa jaata hai, warna ye
    test kabhi fail hi nahi hota.
    """
    report = _exam_report()
    body = "\n".join(em.section_lines(report))
    assert report["not_met_count"] > 0 and report["met_count"] > 0
    not_met_block = f"**REH GAYA (NOT MET) ({report['not_met_count']})**"
    met_block = f"**MAANG POORI HUI (MET) ({report['met_count']})**"
    assert not_met_block in body and met_block in body
    assert body.index(not_met_block) < body.index(met_block)
    trade = _trade_report()
    trade_body = "\n".join(tm.section_lines(trade))
    assert trade["not_met_count"] > 0 and trade["met_count"] > 0
    trade_not_met = f"**NOT MET ({trade['not_met_count']})**"
    trade_met = f"**MET ({trade['met_count']})**"
    assert trade_not_met in trade_body and trade_met in trade_body
    assert trade_body.index(trade_not_met) < trade_body.index(trade_met)
    # aur jo naapa hi nahi ja saka, wo MET se pehle
    trade_nm = f"**NAAPA NAHI GAYA ({trade['not_measured_count']})**"
    assert trade_body.index(trade_nm) < trade_body.index(trade_met)


# ── D. lane mixing: gaane/science par ek shabd bhi nahi ─────────────────────

def test_d_gaane_aur_science_ke_jawab_me_contract_chhapta_hi_nahi():
    """intel ki shart: "sab mix mt kr dena"."""
    pack = EvidencePack(question=SONG_Q, sources=[])
    for question in (SONG_Q, SCIENCE_Q):
        exam_closed = em.gate(question, paper=PAPER, plan=PAPER,
                              syllabus="maths", sources=[])
        trade_closed = tm.study(question, spec=SPEC, sources=[], hypotheses=[],
                                lab_report={})
        assert exam_closed.get("wanted") is False, question
        assert trade_closed.get("wanted") is False, question
        assert em.section_lines(exam_closed) == []
        assert tm.section_lines(trade_closed) == []
        text = FinalSynthesizer().assemble(
            pack=pack, exam_contract_report=exam_closed,
            trade_contract_report=trade_closed, **_base())
        assert em.SECTION_HEADING not in text, question
        assert tm.SECTION_HEADING not in text, question
        # band lane ki seema bhi audit me nahi jaani chahiye
        for line in em.limits({}) + tm.limits({}):
            assert line not in text, question


def test_d_kwarg_hi_na_de_to_bhi_kuch_nahi_chhapta():
    """Purane caller (bina naye kwarg) waise hi chalte rehne chahiye."""
    pack = EvidencePack(question=SCIENCE_Q, sources=[])
    text = FinalSynthesizer().assemble(pack=pack, **_base())
    assert em.SECTION_HEADING not in text and tm.SECTION_HEADING not in text
    for line in em.limits({}) + tm.limits({}):
        assert line not in text


def test_d_exam_ki_farmaish_par_trading_ka_naap_nahi_chalta():
    """Dono gate apne aap band hote hain — ek dusre ke raste par nahi."""
    assert tm.study(EXAM_Q, spec=SPEC, sources=[], hypotheses=[],
                    lab_report={}).get("wanted") is False
    assert em.gate(TRADE_Q, paper=PAPER, plan=PAPER, syllabus="maths",
                   sources=[]).get("wanted") is False


# ── E. "khaali" aur "maangi nahi gayi" do alag baatein ──────────────────────

def test_e_khaali_record_aur_band_lane_ek_jaise_nahi_padhe_jaate():
    for mod in (em, tm):
        assert mod.public_record({}) == {}, mod.__name__
        assert mod.public_record(None) == {}, mod.__name__
        assert mod.public_record("kuch bhi") == {}, mod.__name__
        closed = mod.public_record(mod.not_asked(SONG_Q))
        assert closed["wanted"] is False, mod.__name__
        assert closed["ran"] is False, mod.__name__
        assert closed["reason"], mod.__name__
    # chali hui gate/study par `wanted` key HOTI HI NAHI — yahi darwaza hai jo
    # "kabhi maangi nahi gayi" aur "maangi gayi par kuch nahi mila" ko alag
    # rakhta hai.
    assert "wanted" not in em.public_record(_exam_report())
    assert "wanted" not in tm.public_record(_trade_report())
    assert "wanted" not in _exam_report()
    assert "wanted" not in _trade_report()


def test_e_result_model_record_ko_bina_tootey_leke_jaata_hai():
    import json
    exam = em.public_record(_exam_report())
    trade = tm.public_record(_trade_report())
    result = ResearchResult(question=EXAM_Q, exam_contract=exam,
                            trade_contract=trade)
    data = result.to_dict()
    json.dumps(data)
    assert data["exam_contract"]["contract_points"] == em.CONTRACT_POINTS
    assert data["trade_contract"]["contract_points"] == tm.CONTRACT_POINTS
    assert data["exam_contract"]["not_met"] == exam["not_met"]
    assert data["trade_contract"]["not_measured"] == trade["not_measured"]
    blank = ResearchResult(question=SONG_Q).to_dict()
    assert blank["exam_contract"] == {} and blank["trade_contract"] == {}


def test_e_ginti_ka_jod_contract_ke_kul_point_ke_barabar_hai():
    """Ek point do khaane me gina jaaye to ginti hi jhoothi ho jaati hai."""
    for mod, report in ((em, _exam_report()), (tm, _trade_report())):
        total = (report["met_count"] + report["not_met_count"]
                 + report["not_measured_count"])
        assert total == mod.CONTRACT_POINTS, mod.__name__
        assert len(report["checks"]) == mod.CONTRACT_POINTS, mod.__name__


# ── F. ₹0, offline, aur wahi nateeja har baar ───────────────────────────────

def test_f_dono_contract_me_gemini_aur_network_zero_hai():
    for mod in (em, tm):
        policy = mod.policy()
        assert policy["gemini_calls"] == 0, mod.__name__
        assert policy["network_used"] is False, mod.__name__
        assert policy["deterministic"] is True, mod.__name__
        assert "0" in str(policy["provider_cost"]), mod.__name__
    exam = em.public_record(_exam_report())
    trade = tm.public_record(_trade_report())
    for record in (exam, trade):
        assert record["gemini_calls"] == 0
        assert record["network_used"] is False


def test_f_wahi_input_par_wahi_nateeja():
    """Randomness ho to naap "naap" nahi rehta — aur mutation test bekaar."""
    first_exam, first_trade = _exam_report(), _trade_report()
    for _ in range(3):
        again_exam, again_trade = _exam_report(), _trade_report()
        assert em.section_lines(again_exam) == em.section_lines(first_exam)
        assert em.limits(again_exam) == em.limits(first_exam)
        assert tm.section_lines(again_trade) == tm.section_lines(first_trade)
        assert tm.limits(again_trade) == tm.limits(first_trade)


def test_f_contract_block_khaali_list_par_khaali_string_deta_hai():
    """Yahi ek jagah hai jo "block chhapega ya nahi" tay karti hai."""
    from research_engine.synthesizer_claude import _contract_block
    assert _contract_block([]) == ""
    assert _contract_block(None) == ""
    assert _contract_block(["### X", "", "line"]) == "### X\n\nline"
    body = inspect.getsource(_contract_block)
    # heading yahan se NAHI aati — module ki apni heading hi jaati hai
    assert "###" not in body.split('"""')[-1]
