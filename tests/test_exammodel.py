"""#171f — EXAM/PADHAI ka contract, uske naap, aur uski lane ka SACH.

#171b ne `exammodel.py` banaya (28-point contract + naap), #171c ne lane
isolation di (gaane/trading ki cheez exam ke jawab me na aaye), #171d ne
exam-study tier banayi (asli me kuch PADHA jaaye), aur #171e ne EXAM LAB banayi
(bana hua paper/plan app KHUD naapta hai). Us poore batch par ab tak koi apna
test file nahi tha — `tests/` me `exammodel` ka naam sirf
`tests/test_lane_isolation.py` me aata tha (3 test).

Is file ka kaam un khatron ke peeche padna hai jo is lane me ASLI me ho sakte
hain:

  1. NAAM vs KAAM — "exam lane chali" likh dena aasan hai. Lane ka reason GINTI
     se banna chahiye; 0 query bani ho to reason me wahi likha ho.
  2. DAROGA GATE — "exam ka stress kaise kam kare" me exam ka naam hai par
     kuch banane/seekhne ki maang nahi; "US100 ka model banao" me banane ki
     maang hai par exam ki koi cheez nahi. Dono par ye lane band rehni chahiye.
     Gate ke DO signal ek hi helper se aane chahiye, warna kal `is_request`
     "haan" kahegi aur `request_reason` "na" ki wajah likhegi.
  3. LABEL vs SEARCH TERM — insaan ke liye "ganit/maths", par syllabus PDF
     "mathematics" naam se indexed hai. Hinglish label search me chala jaaye to
     official syllabus kabhi nahi milega.
  4. LANE MIXING — intel ki saaf shart: "sab mix mt kr dena". SONG/TRADING/
     SCIENCE par is lane ka ek bhi asar nahi, aur exam par gaane ka pehra nahi.
  5. QUERY ≠ EVIDENCE — is stage me network chalta hi nahi.
     `exam_evidence_read` yahan kabhi True nahi hota.
  6. NAAP ≠ ACHCHHA — split ka `ok=True` ka matlab sirf "naap CHAL gayi" hai,
     "paper achchha hai" nahi. Aur naap na chale to share `None` jaata hai —
     0.0 nahi, warna "0% coverage" aur "naapa hi nahi" ek dikhne lagte hain.
  7. JHOOTHA MET — default status NOT_MEASURED hai. Jo point yahan naapa hi
     nahi ja sakta (official key se milaan) wo kabhi MET nahi hota.
  8. DO LAB EK NA HO JAAYEIN — `run_lab` hypothesis test karti hai,
     `run_exam_lab` BANA HUA paper/plan. Verdict ki bhasha, audit ki chhat aur
     limit lines teenon alag rehni chahiye, warna paper ki kami hypothesis ke
     khaate me chali jaayegi.
  9. ADHOORA NUMBER — `numbers=` sirf CHALI hui naap ke saath bahar jaata hai;
     DATA_MISSING ke raste par ek bhi naapa hua number nahi.
"""
import ast
import inspect
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import craft  # noqa: E402
from research_engine import exammodel as em  # noqa: E402
from research_engine import lab  # noqa: E402
from research_engine import songcraft as sc  # noqa: E402
from research_engine import trademodel as tm  # noqa: E402
from research_engine.depth import get_depth_config  # noqa: E402
from research_engine.planner import ResearchPlanner  # noqa: E402
from research_engine.source_discovery import SourceDiscovery  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAPER_Q = ("RPF SI ka practice question paper banao 20 sawaal hindi me, answer "
           "key aur solution bhi do, easy medium hard mix rakho, negative "
           "marking bhi batao, previous year pattern dekh lo")
PLAN_Q = "math basic se strong kaise karun 30 din me roz 2 hour"
SONG_Q = "hindi me ek sad gaana likh do judaai wala"
TRADE_Q = "US100 aur XAUUSD ka intraday scalping model banao"
SCIENCE_Q = "room temperature superconductivity ka evidence kya hai"
STRESS_Q = "exam ka stress kaise kam kare"

PAPER = """
Total marks: 40 | Duration: 60 minutes
Negative marking: 1/4 mark kaategi.
Ye paper practice ke liye hai, kisi board ka official paper nahi hai.

Q1. Ek train 60 km/h se 2 ghante chali. 60 * 2 = ? [2 marks]
(a) 100 (b) 120 (c) 140 (d) 160
Answer: b
Solution: doori = chaal x samay

Q2. Samvidhan ka Article 21 kis adhikar ki baat karta hai?
Answer: jeevan ka adhikar

Q3. Ek train 60 km/h se 2 ghante chali. 60 * 2 = ?
(a) 100 (b) 120 (c) 140 (d) 160
Answer: b

Q4. Sthir vidyut ka SI matrak, aur 12 / 4 = ? [4 marks]
Answer: 3

Q5. Agar A > B aur B > C ho to sabse bada kaun?
Answer: A
"""

SYLLABUS = ("1. Maths: speed time distance\n"
            "2. Polity: fundamental rights\n"
            "3. Physics: electricity\n")

PLAN_TEXT = ("Day 1: Maths basic speed time distance - 60 minutes\n"
             "Day 2: Polity fundamental rights - 90 minutes\n"
             "Day 3: Physics electricity - 700 minutes\n")


def _src(name):
    with open(os.path.join(ROOT, "research_engine", name), "r",
              encoding="utf-8") as handle:
        return handle.read()


def _lane(question, mode="DEEP"):
    planner = ResearchPlanner()
    cls = planner.classify(question)
    return planner.connector_plan(cls, get_depth_config(mode), question)


def _questions(text=PAPER):
    return em.apply_answer_key(em.questions_from_text(text),
                               em.answer_key_from_text(text))


# ── 1. GATE — do signal chahiye, aur dono ek hi jagah se ─────────────────────

def test_a_exam_ask_ko_do_signal_chahiye_hote_hain():
    """Ek akela signal darwaza na khole — na "exam" shabd, na "banao"."""
    assert em.is_request(PAPER_Q) is True
    assert em.is_request(PLAN_Q) is True
    # exam ka naam hai, par kuch banane/seekhne ki maang nahi
    assert em.is_request(STRESS_Q) is False
    # banane ki maang hai, par exam/padhai ki koi cheez nahi
    assert em.is_request(TRADE_Q) is False
    assert em.is_request(SONG_Q) is False
    assert em.is_request(SCIENCE_Q) is False
    assert em.is_request("") is False


def test_a_dono_signal_alag_alag_kaam_karte_hain():
    """Pehla rasta = exam ki cheez + banane ki maang; doosra = subject + seekhna."""
    assert em._exam_signal("mock test paper banao") is True
    # STRESS_Q me exam ka naam HAI — darwaza doosri shart (banane/seekhne ki
    # maang) par band hota hai, pehli par nahi. Yahi do-signal ka asli matlab.
    assert em._exam_signal(STRESS_Q) is True
    assert em._WANT_RE.search(STRESS_Q) is None
    assert em.is_request(STRESS_Q) is False
    assert em._subject_learn_signal(PLAN_Q) is True
    assert em._subject_learn_signal("maths bahut mushkil hai") is False
    # Sirf subject ka naam bhi kaafi nahi, seekhne ki maang chahiye.
    assert em.is_request("maths") is False
    assert bool(em.subject_cues("maths")) is True


def test_a_reason_aur_faisla_ek_hi_signal_se_bante_hain():
    """Kal `is_request` "haan" kahe aur reason "na" ki wajah likhe — wo jhooth hai.

    Naam par bharosa nahi kiya ja sakta, isliye ye naap BEHAVIOURAL hai: dono
    function ko ek hi sawaal-list par chalaya jaata hai aur unka faisla milaya
    jaata hai. Do alag list ban jaana is lane ki sabse mumkin galti hai — aur
    wo yahan pakdi jaayegi chahe implementation kaise bhi likhi ho.
    """
    source = _src("exammodel.py")
    assert source.count("def _exam_signal(") == 1
    assert source.count("def _subject_learn_signal(") == 1
    questions = [PAPER_Q, PLAN_Q, SONG_Q, SCIENCE_Q, TRADE_Q, STRESS_Q, "",
                 "maths", "class 10 maths ka syllabus cover karne ka plan banao",
                 "SSC CGL ke liye maths strong karna hai",
                 "gaana banao par exam jaisa mat likhna",
                 "history padhni hai kaise shuru karun"]
    for question in questions:
        opened = em.is_request(question)
        reason = em.request_reason(question)
        assert opened is ("exam-study lane chali" in reason), question
        assert reason, question
        if opened:
            assert reason != em.NOT_ASKED_REASON, question
    # Har band-darwaze ki apni wajah — sab ek hi line par nahi girte.
    assert em.request_reason(SONG_Q) == em.NOT_ASKED_REASON
    assert em.request_reason(SCIENCE_Q) == em.NOT_ASKED_REASON
    assert "naam nahi" in em.request_reason(TRADE_Q)
    assert "maang nahi" in em.request_reason(STRESS_Q)
    assert em.request_reason(STRESS_Q) != em.request_reason("maths")


def test_a_bade_akshar_wale_shabd_exam_ka_naam_nahi_ban_jaate():
    """"PDF me MATH ka paper banao" — na PDF exam hai, na MATH exam ka naam."""
    assert em.exam_names("PDF me MATH ka paper banao") == []
    assert em.exam_names(PAPER_Q) == ["RPF", "SI"]
    for stop in ("PDF", "MATH", "OMR", "MCQ"):
        assert stop in em._ACRONYM_STOP
    # Naam ki list poori nahi hai — aur ye baat record me likhi jaati hai.
    assert em.EXAM_LIST_IS_NOT_EXHAUSTIVE is True
    assert em.SUBJECT_LIST_IS_NOT_EXHAUSTIVE is True


# ── 2. ASK PARSE — jo maanga gaya wahi likha jaaye ───────────────────────────

def test_b_paper_wali_farmaish_ke_sab_hisse_padhe_jaate_hain():
    ask = em.ask_of(PAPER_Q)
    assert ask.asked is True
    assert ask.kind == em.KIND_PAPER
    assert ask.exams == ("RPF", "SI")
    assert ask.language == em.LANG_HINDI
    assert ask.question_count == 20
    assert ask.wants_answer_key is True
    assert ask.wants_solutions is True
    assert ask.wants_difficulty_mix is True
    assert ask.wants_past_pattern is True
    # Paper ki farmaish me subject ka naam nahi tha — jhootha subject nahi bhara.
    assert ask.subjects == ()
    # Ye field TUPLE hain — baad me koi list bana kar chupke se badal na de,
    # kyunki list mutable hoti hai aur ek jagah ka append doosri jagah dikh
    # jaata. Sirf to_dict() insaan ke liye list banata hai.
    assert isinstance(ask.exams, tuple) and isinstance(ask.subjects, tuple)
    assert ask.to_dict()["exams"] == ["RPF", "SI"]


def test_b_plan_wali_farmaish_din_aur_ghante_padhti_hai():
    ask = em.ask_of(PLAN_Q)
    assert ask.kind == em.KIND_PLAN
    assert ask.subjects == ("maths",)
    assert ask.subject_labels == ("ganit/maths",)
    assert ask.level == "basic"
    assert ask.days_available == 30
    assert ask.duration_minutes == 120     # "roz 2 hour"
    assert ask.question_count == 0


def test_b_ask_ka_record_imaandaari_ke_flag_bhi_le_kar_jaata_hai():
    """`to_dict` me sirf farmaish nahi — "ye official nahi hai" bhi jaata hai."""
    row = em.ask_of(PAPER_Q).to_dict()
    assert row["paper_is_practice_only"] is True
    assert row["answer_key_is_app_made"] is True
    assert row["exam_list_is_not_exhaustive"] is True
    assert row["subject_list_is_not_exhaustive"] is True
    assert row["kind"] == em.KIND_PAPER


def test_b_level_kind_aur_bhasha_alag_alag_padhe_jaate_hain():
    assert em.level_of("class 10 maths") == "class-10"
    assert em.level_of("tier-2 ka paper") == "tier-2"
    assert em.level_of("prelims ka syllabus") == "prelim"
    assert em.level_of("basic se strong karna hai") == "basic"
    assert em.level_of("advanced level chahiye") == "advanced"
    assert em.kind_of(PAPER_Q) == em.KIND_PAPER
    assert em.kind_of(PLAN_Q) == em.KIND_PLAN
    assert em.kind_of("gaana banao") == em.KIND_NONE
    assert em.language_of(PAPER_Q) == em.LANG_HINDI
    assert em.language_of("english me paper do") == em.LANG_ENGLISH
    assert em.language_of("hindi and english dono me") == em.LANG_BOTH
    # Bhasha na maangi ho to khaali — apni marzi ki bhasha nahi maan li jaati.
    assert em.language_of("paper banao") == ""


# ── 3. LANE QUERY — kis naam se dhoonda jaayega ──────────────────────────────

def test_c_search_me_english_naam_jaata_hai_hinglish_label_nahi():
    """Insaan ke liye "ganit/maths", par board ka syllabus "mathematics" hai.

    Label ko search term samajh lena is lane ki chup-chaap maut hai: query
    banti dikhti hai par official syllabus PDF kabhi nahi milta.
    """
    ask = em.ask_of(PLAN_Q)
    queries = [row["query"] for row in em.lane_queries(ask)]
    assert queries[0] == "mathematics official syllabus notification pdf"
    assert em._SUBJECT_SEARCH["maths"] == "mathematics"
    assert em._SUBJECT_LABELS["maths"] == "ganit/maths"
    assert em._subject_terms(ask) == ["mathematics"]
    for query in queries:
        assert "ganit" not in query


def test_c_pattern_wali_query_sirf_exam_ke_saath_banti_hai():
    """#171d ka niyam: "exam pattern marks negative marking" ka matlab EXAM hai.

    "math strong karna hai" par ye query banana bekaar hai — koi exam hi nahi
    likha. Ye rule context ka hai, keyword ka nahi.
    """
    plan_queries = [row["query"] for row in em.lane_queries(em.ask_of(PLAN_Q))]
    assert not any("exam pattern" in query for query in plan_queries)
    paper_queries = [row["query"] for row in em.lane_queries(em.ask_of(PAPER_Q))]
    assert "RPF SI exam pattern marks negative marking official" in paper_queries
    # Subject ke saath exam ka naam aa jaaye to query BANTI hai.
    both = em.ask_of("SSC CGL ke liye maths strong karna hai paper bhi banao")
    assert any("exam pattern" in row["query"] for row in em.lane_queries(both))


def test_c_official_pehle_aur_lane_baari_baari_aati_hain():
    """Ek hi lane saari query kha jaaye to padhai ek-tarfa ho jaati hai."""
    rows = em.lane_queries(em.ask_of(PAPER_Q))
    lanes = [row["lane"] for row in rows]
    assert lanes[0] == em.LANE_OFFICIAL
    assert lanes[:3] == [em.LANE_OFFICIAL, em.LANE_TEXTBOOK, em.LANE_PRACTICE]
    assert set(lanes) <= set(em.STUDY_LANES)
    plan_lanes = [row["lane"] for row in em.lane_queries(em.ask_of(PLAN_Q))]
    assert plan_lanes[:3] == [em.LANE_OFFICIAL, em.LANE_TEXTBOOK,
                              em.LANE_PEDAGOGY]
    # Pedagogy ki query kisi exam ke naam par nahi — "kaise padhein" ki research.
    assert len(em._PEDAGOGY_QUERIES) == 4


def test_c_query_na_dohrayi_jaayein_aur_chhat_maani_jaaye():
    ask = em.ask_of(PLAN_Q)
    rows = em.lane_queries(ask)
    queries = [row["query"] for row in rows]
    assert len(queries) == len(set(queries))
    assert len(em.lane_queries(ask, limit=2)) == 2
    assert len(em.lane_queries(ask, limit=1)) == 1
    # NAAPA HUA SACH: `_dedup` ka break append ke BAAD chalta hai, isliye
    # limit=0 par bhi ek row nikalti hai. Ye asli caller (depth config 4 ya 12)
    # ke liye bemaani hai, par jhooth likhne se accha hai ki naapa hua sach
    # pinned rahe — kal koi ise 5 bana de to ye test pakdega.
    assert len(em.lane_queries(ask, limit=0)) == 1
    assert len(em.lane_queries(ask, limit=-3)) == 1
    assert len(em.lane_queries(ask, limit=99)) <= em.MAX_STUDY_QUERIES
    assert em.MAX_STUDY_QUERIES == 12
    assert em.QUICK_STUDY_QUERIES == 4


def test_c_lead_query_official_ko_aage_rakhti_hai():
    lead = em.lead_queries(em.ask_of(PAPER_Q))
    assert lead[0] == "RPF SI official syllabus notification pdf"
    assert "RPF SI exam pattern marks negative marking official" in lead
    assert len(lead) == 3


def test_c_farmaish_na_ho_to_ek_bhi_query_nahi_banti():
    """Gaane/science ki farmaish par ye lane ek shabd bhi kharch na kare."""
    assert em.lane_queries(None) == []
    assert em.lane_queries(em.ask_of(SONG_Q)) == []
    assert em._study_groups(em.ask_of(SCIENCE_Q)) == []
    assert em.lead_queries(None) == []


# ── 4. PARSER — bane hue paper/plan ko asli me PADHNA ────────────────────────

def test_d_paper_ke_sawaal_ginti_ke_saath_padhe_jaate_hain():
    questions = _questions()
    assert [q.number for q in questions] == [1, 2, 3, 4, 5]
    first = questions[0]
    assert first.options == ("a", "b", "c", "d")
    assert isinstance(first.options, tuple)
    assert first.marks == 2.0
    assert first.answer == "b"
    assert first.solution
    # Q2 ke saath koi option nahi tha — jhoothe option nahi ban gaye.
    assert questions[1].options == ()
    assert questions[1].solution == ""
    # Insaan ke liye list, andar tuple — dono ek saath sach.
    assert first.to_dict()["options"] == ["a", "b", "c", "d"]


def test_d_alag_answer_key_block_aur_inline_answer_ek_nahi_hain():
    """Inline "Answer: b" question ke saath padha jaata hai.

    Alag "Answer key" block se aayi key hi `answer_key_from_text` deti hai —
    dono ko ek karna is naap ko andha kar deta: key ke bina bane paper me bhi
    "key mil gayi" dikhta.
    """
    assert em.answer_key_from_text(PAPER) == {}
    keyed = PAPER + "\nAnswer key:\n1. b\n2. c\n"
    assert em.answer_key_from_text(keyed) == {1: "b", 2: "c"}
    # Key block se aane par question par chipak jaati hai.
    questions = em.apply_answer_key(em.questions_from_text(keyed),
                                   em.answer_key_from_text(keyed))
    assert questions[1].answer == "c"


def test_d_syllabus_aur_plan_ki_row_alag_alag_padhi_jaati_hain():
    topics = em.syllabus_topics(SYLLABUS)
    assert topics == ["Maths: speed time distance", "Polity: fundamental rights",
                      "Physics: electricity"]
    rows = em.plan_rows_from_text(PLAN_TEXT)
    assert [row["label"] for row in rows] == ["Day 1", "Day 2", "Day 3"]
    assert [row["minutes"] for row in rows] == [60.0, 90.0, 700.0]
    assert em.plan_rows_from_text("") == []
    assert em.syllabus_topics("") == []


# ── 5. NAAP — "chal gayi" ka matlab "achchha hai" NAHI ───────────────────────

def test_e_naap_chalne_ka_matlab_paper_achchha_hona_nahi_hai():
    """`ok` sirf ye kehta hai ki naap CHAL gayi — verdict LAB ki chhat deti hai.

    Ye is file ka sabse zaroori farak hai: `ok=True` par bhi coverage 0 ho
    sakti hai, aur us haalat me LAB ka verdict FAIL hi hona chahiye.
    """
    coverage = em.coverage_split(em.syllabus_topics(SYLLABUS), _questions())
    assert coverage.ok is True
    assert coverage.topics == 3
    assert coverage.covered == 0
    assert coverage.covered_share == 0.0
    assert coverage.full_coverage is False
    assert len(coverage.uncovered) == 3
    assert coverage.covered_share < em.LAB_MIN_COVERAGE_SHARE


def test_e_naap_na_chale_to_share_khaali_jaata_hai_zero_nahi():
    """"0% coverage" aur "naapa hi nahi gaya" ek dikhein — wo jhooth hai."""
    empty = em.coverage_split([], _questions())
    assert empty.ok is False
    assert empty.reason_code == em.NO_SYLLABUS
    assert empty.covered_share is None
    assert empty.full_coverage is None
    assert empty.paper_too_small is None
    no_paper = em.coverage_split(em.syllabus_topics(SYLLABUS), [])
    assert no_paper.reason_code == em.NO_PAPER
    assert no_paper.covered_share is None


def test_e_difficulty_ka_naap_proxy_hai_aur_ye_chhupaya_nahi_jaata():
    split = em.difficulty_split(_questions())
    assert split.ok is True
    row = split.to_dict()
    # "Proxy hai" ka elaan record me jaata hai — chhupaya nahi jaata.
    assert row["is_proxy"] is True
    assert em.DIFFICULTY_IS_PROXY is True
    assert row["counts"] == {"easy": 1, "medium": 1, "hard": 3}
    assert row["bands_used"] == 3
    assert row["mixed"] is True
    assert sum(row["counts"].values()) == 5
    # Ek band me 80% se zyada ho to mix nahi maana jaata.
    assert em.LAB_MAX_BAND_SHARE == 0.8
    thin = em.difficulty_split(_questions()[:2])
    assert thin.ok is False
    assert thin.reason_code == em.FEW_QUESTIONS
    assert em.MIN_QUESTIONS_FOR_SPLIT == 4


def test_e_ek_jaise_do_sawaal_pakde_jaate_hain_shabd_ke_overlap_se():
    split = em.duplicate_split(_questions())
    row = split.to_dict()
    assert row["duplicate_pairs"] == 1
    assert row["pairs"][0]["left"] == 1
    assert row["pairs"][0]["right"] == 3
    assert row["pairs"][0]["similarity"] == 1.0
    assert row["threshold"] == em.DUPLICATE_SIMILARITY == 0.8
    assert row["clean"] is False
    assert em.LAB_MAX_DUPLICATE_PAIRS == 0


def test_e_ginti_wala_sawaal_bina_calculator_ke_naapa_hua_nahi_kehlata():
    """Apna calculator likh kar "check ho gaya" kehna jhooth hai."""
    without = em.solvability_split(_questions())
    assert without.ok is False
    assert without.reason_code == em.NO_EVALUATOR
    assert without.solved_share is None
    assert without.all_solvable is None

    def _ok(expression):
        return {"ok": True, "value": 0.0}

    with_eval = em.solvability_split(_questions(), evaluate=_ok)
    assert with_eval.ok is True
    assert with_eval.checked >= 2          # Q1/Q3 me "60 * 2", Q4 me "12 / 4"
    assert with_eval.solved == with_eval.checked
    assert with_eval.all_solvable is True
    assert em.expressions_in(_questions()[0]) == ["60 * 2"]

    def _bad(expression):
        return {"ok": False, "error": "syntax"}

    broken = em.solvability_split(_questions(), evaluate=_bad)
    assert broken.ok is True
    assert broken.solved == 0
    assert broken.all_solvable is False
    assert broken.failed and broken.failed[0]["error"] == "syntax"
    # Evaluator khud phat jaaye to bhi naap chalti hai — question fail hota hai.
    def _boom(expression):
        raise ValueError("nope")

    assert em.solvability_split(_questions(), evaluate=_boom).solved == 0


def test_e_plan_ka_time_budget_aur_roz_ki_hadd_alag_naapi_jaati_hai():
    """Total time me fit ho jaana kaafi nahi — ek din 700 minute insaani nahi hai."""
    rows = em.plan_rows_from_text(PLAN_TEXT)
    split = em.plan_time_split(rows, 30 * 120)
    row = split.to_dict()
    assert row["total_minutes"] == 850.0
    assert row["minutes_available"] == 3600.0
    assert row["fits"] is True              # kul time me aa jaata hai
    assert row["worst_day"] == "Day 3"
    assert row["worst_day_minutes"] == 700.0
    assert row["daily_ceiling"] == float(em.DAILY_MINUTES_CEILING) == 600.0
    assert row["day_realistic"] is False    # ...par ek din ki hadd toot gayi
    assert em.plan_time_split([], 3600).reason_code == em.NO_PLAN
    assert em.plan_time_split(rows, 0).reason_code == em.NO_TIME_BUDGET


def test_e_kram_aur_aadat_alag_alag_naape_jaate_hain():
    """"basic pehle" aur "practice + revision" do alag baatein hain."""
    rows = em.plan_rows_from_text(PLAN_TEXT)
    order = em.order_split(rows)
    assert order["ok"] is True
    assert order["basic_first"] is True
    habit = em.habit_split(rows)
    assert habit["practice_rows"] == 0
    assert habit["review_rows"] == 0
    assert habit["both"] is False
    better = em.plan_rows_from_text(
        "Day 1: basic concepts - 60 minutes\n"
        "Day 2: practice questions - 60 minutes\n"
        "Day 3: revision aur mock test review - 60 minutes\n")
    habit2 = em.habit_split(better)
    assert habit2["practice_rows"] >= 1
    assert habit2["review_rows"] >= 1
    assert habit2["both"] is True
    # Sirf practice = aadat adhoori. "Dono hain" bolna yahan seedha jhooth hota,
    # isliye ek taraf ki ginti par `both` kabhi True nahi hota.
    only_practice = em.habit_split(em.plan_rows_from_text(
        "Day 1: practice questions - 60 minutes\n"
        "Day 2: practice set lagao - 60 minutes\n"))
    assert only_practice["practice_rows"] >= 1
    assert only_practice["review_rows"] == 0
    assert only_practice["both"] is False
    # Advanced pehle rakha jaaye to kram ka naap RED bolta hai.
    reversed_rows = em.plan_rows_from_text(
        "Day 1: advanced problems - 60 minutes\n"
        "Day 2: basic concepts - 60 minutes\n")
    assert em.order_split(reversed_rows)["basic_first"] is False


def test_e_marks_time_aur_negative_marking_text_se_padhe_jaate_hain():
    numbers = em.marks_and_time_in(PAPER)
    assert numbers["total_marks"] == 40
    assert numbers["duration_minutes"] == 60.0
    assert em.negative_marking_stated(PAPER) is True
    assert em.negative_marking_stated("Q1. kuch bhi") is False
    honesty = em.not_official_stated(PAPER)
    assert honesty["practice_only"] is True
    assert honesty["not_official"] is True
    assert em.prediction_claims(PAPER) == []
    assert em.score_promises(PAPER) == []
    assert em.prediction_claims("yahi question exam me aayega")
    assert em.score_promises("is plan se selection pakka")


# ── 6. CONTRACT — 28 point, aur har point ka apna naapne wala ────────────────

def test_f_contract_ka_size_aur_hisse_pinned_hain():
    assert em.CONTRACT_POINTS == 28
    assert len(em.CONTRACT) == em.CONTRACT_POINTS
    assert len(em.CONTRACT_IDS) == len(set(em.CONTRACT_IDS))
    assert em.GROUPS == ("scope", "sources", "paper", "plan", "honesty")
    counts = {group: sum(1 for point in em.CONTRACT if point.group == group)
              for group in em.GROUPS}
    assert counts == {"scope": 4, "sources": 4, "paper": 10, "plan": 6,
                      "honesty": 4}
    assert sum(counts.values()) == em.CONTRACT_POINTS
    for point in em.CONTRACT:
        assert point.group in em.GROUPS, point.point_id
        assert point.label and point.needs, point.point_id


def test_f_har_point_ka_naapne_wala_maujood_hai_warna_naap_rukti_hai():
    """Point add karke naap bhool jaana = chup-chaap NOT_MEASURED chhupana.

    `measure()` khud raise karti hai, isliye ye galti kabhi green nahi hoti.
    """
    missing = [pid for pid in em.CONTRACT_IDS if pid not in em._EVALUATORS]
    assert missing == []
    source = inspect.getsource(em.measure)
    assert "raise AssertionError" in source
    saved = em._EVALUATORS.pop("exam_scope")
    try:
        raised = False
        try:
            em.measure(ask=em.ask_of(PAPER_Q), paper=PAPER)
        except AssertionError:
            raised = True
        assert raised is True
    finally:
        em._EVALUATORS["exam_scope"] = saved


def test_f_default_MET_nahi_hota_default_NOT_MEASURED_hota_hai():
    """Naap ka nateeja pehchana na jaaye to jawab NOT_MEASURED — MET nahi."""
    saved = em._EVALUATORS["exam_scope"]
    try:
        em._EVALUATORS["exam_scope"] = lambda ctx: {"status": "SAB_THEEK"}
        record = em.measure(ask=em.ask_of(PAPER_Q), paper=PAPER)
        row = [r for r in record["checks"] if r["point_id"] == "exam_scope"][0]
        assert row["status"] == em.NOT_MEASURED
        assert "NOT_MEASURED" in row["reason"]
        assert "exam_scope" not in record["met"]
    finally:
        em._EVALUATORS["exam_scope"] = saved


def test_f_jo_yahan_naapa_hi_nahi_ja_sakta_wo_kabhi_MET_nahi_hota():
    """Official key se milaan app ke paas hai hi nahi — wo point blocked hai."""
    assert em.STRUCTURALLY_BLOCKED == ("key_matched_official",)
    record = em.measure(ask=em.ask_of(PAPER_Q), paper=PAPER, plan=PLAN_TEXT,
                        syllabus=SYLLABUS)
    row = [r for r in record["checks"]
           if r["point_id"] == "key_matched_official"][0]
    assert row["status"] == em.NOT_MEASURED
    assert row.get("blocked_by")
    assert "key_matched_official" not in record["met"]
    assert record["structurally_blocked"] == ["key_matched_official"]
    for blocked in em.STRUCTURALLY_BLOCKED:
        assert em.CONTRACT_BY_ID[blocked].blocked_by


def test_f_honest_final_decision_sabse_aakhir_me_naapa_jaata_hai():
    """Uska sawaal hi ye hai: "fail hone ke baad bhi de diya?" — kram badla to andha."""
    assert em.CONTRACT_IDS[-1] == "honest_final_decision"
    assert em.CONTRACT[-1].group == "honesty"
    source = inspect.getsource(em.measure)
    assert "SABSE AAKHIR" in source
    # Naap ka kram CONTRACT ke kram se hi chalta hai, apni list se nahi.
    assert "for point in CONTRACT:" in source
    record = em.measure(ask=em.ask_of(PAPER_Q), paper=PAPER)
    assert [row["point_id"] for row in record["checks"]] == list(em.CONTRACT_IDS)


def test_f_naap_ka_record_ginti_bhi_deta_hai_aur_seema_bhi():
    record = em.measure(ask=em.ask_of(PAPER_Q), paper=PAPER, plan=PLAN_TEXT,
                        syllabus=SYLLABUS)
    total = (record["met_count"] + record["not_met_count"]
             + record["not_measured_count"])
    assert total == em.CONTRACT_POINTS
    assert record["questions_parsed"] == 5
    assert record["syllabus_topics"] == 3
    assert record["plan_rows"] == 3
    assert record["schema"] == em.SCHEMA_VERSION == "exammodel-1"
    assert len(record["cannot_measure"]) == len(em.CANNOT_MEASURE) == 4
    assert record["not_official_note"] == em.NOT_OFFICIAL_NOTE


# ── 7. DARWAZA — "band tha" aur "chali par kuch nahi mila" ek nahi ────────────

def test_g_sirf_band_darwaze_ke_record_me_wanted_key_hoti_hai():
    """`wanted` key hi caller ko batati hai ki lane KHULI hi nahi thi."""
    shut = em.not_asked(SONG_Q)
    assert shut["wanted"] is False
    assert shut["asked"] is False
    assert shut["ran"] is False
    assert shut["queries"] == []
    assert shut["checks"] == []
    assert shut["contract_points"] == em.CONTRACT_POINTS
    ran = em.gate(question=PAPER_Q, paper=PAPER, plan=PLAN_TEXT,
                  syllabus=SYLLABUS)
    assert "wanted" not in ran
    assert ran["ran"] is True
    assert ran["asked"] is True
    assert ran["queries"]
    assert len(ran["checks"]) == em.CONTRACT_POINTS
    # Gaane/trading ki farmaish par gate wahi band record deta hai.
    assert em.gate(question=SONG_Q)["wanted"] is False
    assert em.gate(question=TRADE_Q)["wanted"] is False


def test_g_gate_ka_record_query_aur_naap_dono_le_kar_jaata_hai():
    record = em.gate(question=PAPER_Q, paper=PAPER, plan=PLAN_TEXT,
                     syllabus=SYLLABUS)
    assert record["ask"]["kind"] == em.KIND_PAPER
    assert record["reason"] == em.request_reason(PAPER_Q)
    assert record["queries"] == [row["query"]
                                 for row in record["lane_queries"]]
    assert record["lead_queries"] == em.lead_queries(em.ask_of(PAPER_Q))
    assert record["coverage"]["topics"] == 3
    assert record["duplicate"]["duplicate_pairs"] == 1


def test_g_is_stage_me_kharcha_aur_network_dono_zero_rehte_hain():
    """Ye poora lane bina model, bina internet, bina randomness chalta hai."""
    record = em.gate(question=PLAN_Q, plan=PLAN_TEXT)
    assert record["gemini_calls"] == em.GEMINI_CALLS == 0
    assert record["network_used"] == em.NETWORK_USED is False
    assert record["deterministic"] is True
    assert record["provider_cost"] == em.PROVIDER_COST == "₹0"
    assert record["paper_is_practice_only"] is True
    assert record["is_exam_authority"] is False
    assert record["answer_key_is_app_made"] is True
    assert record["question_prediction_promised"] is False
    assert record["score_promised"] is False
    assert record["leaked_paper_used"] is False
    # Dobara chalane par bilkul wahi jawab — koi randomness nahi.
    again = em.gate(question=PLAN_Q, plan=PLAN_TEXT)
    assert again["checks"] == record["checks"]
    assert again["queries"] == record["queries"]


# ── 8. LANE MIXING — kisi ka pehra kisi par nahi ─────────────────────────────

def test_h_exam_ki_farmaish_par_gaane_wala_taala_nahi_khulta():
    """Gaane ka darwaza `craft.detect` hai — exam ki farmaish par wo band rehta.

    `songcraft` ka koi `is_request` nahi hota (uska rasta craft se hokar aata
    hai), isliye asli darwaze naape jaate hain: craft ka faisla, lyrics-hunt ka
    pehra, aur trading ka gate.
    """
    for question in (PAPER_Q, PLAN_Q):
        detected = craft.detect(question)
        assert detected["is_request"] is False, question
        assert detected["form"] == "", question
        assert tm.is_request(question) is False, question
    # "hindi me" sunkar songcraft bhasha uthaa leta hai — par kisi GAANE ka
    # style (genre) uska nahi banta, aur wo record kabhi bhi khud se lane nahi
    # kholta. Ye farak likha rehna chahiye, chhupana nahi chahiye.
    assert sc.style_of(PAPER_Q).styles == []
    assert sc.style_of(PLAN_Q).asked_anything() is False
    # Exam ki ek bhi query gaane ke lyrics dhoondhne wali nahi lagti.
    for row in em.lane_queries(em.ask_of(PAPER_Q)):
        assert sc.is_lyrics_hunt(row["query"]) is False, row["query"]
    for row in em.lane_queries(em.ask_of(PLAN_Q)):
        assert sc.is_lyrics_hunt(row["query"]) is False, row["query"]


def test_h_gaane_aur_trading_ki_farmaish_par_exam_lane_band_rehti_hai():
    for question in (SONG_Q, TRADE_Q, SCIENCE_Q):
        assert em.is_request(question) is False
        assert em.lane_queries(em.ask_of(question)) == []


def test_h_syllabus_cover_karne_wala_shabd_letter_nahi_ban_jaata():
    """"syllabus cover karne ka plan" me "cover" ka matlab cover letter NAHI hai.

    `craft._context_ok` ka kaam yahi hai: do matlab wale cue ko apna context
    laana padta hai. Ye guard tootne par har padhai wale plan par app "cover
    letter" likhne lagta.
    """
    plan_ask = craft.detect("class 10 maths ka syllabus cover karne ka plan banao")
    assert plan_ask["is_request"] is False
    assert plan_ask["reason"] == "no_form_word"
    assert craft._context_ok(["syllabus", "plan"], "cover") is False
    letter_ask = craft.detect("job ke liye cover letter banao")
    assert letter_ask["is_request"] is True
    assert letter_ask["form"] == "letter"
    assert craft._context_ok(["job", "letter"], "cover") is True
    # Gaane ki farmaish par craft ka darwaza jaisa tha waisa hi hai.
    assert craft.detect(SONG_Q)["form"] == "song"


# ── 9. PLANNER — faisla ek jagah, aur reason GINTI se ────────────────────────

def test_i_planner_exam_ask_par_creative_hata_kar_educational_lagata_hai():
    """"paper banao" me "banao" hai — par ye gaana/kavita nahi, padhai hai."""
    planner = ResearchPlanner()
    cls = planner.classify(PAPER_Q)
    assert cls["is_exam_ask"] is True
    assert cls["is_creative"] is False
    assert "creative" not in cls["question_types"]
    assert "educational" in cls["question_types"]
    assert cls["exam_reason"] == em.request_reason(PAPER_Q)
    plan_cls = planner.classify(PLAN_Q)
    assert plan_cls["is_exam_ask"] is True
    assert "educational" in plan_cls["question_types"]
    # Gaane par ye guard chalta hi nahi — creative wahin rehta hai.
    song_cls = planner.classify(SONG_Q)
    assert song_cls["is_exam_ask"] is False
    assert song_cls["is_creative"] is True


def test_i_planner_apni_copy_se_exam_ka_faisla_nahi_leta():
    """Faisla `exammodel` se aata hai — planner me doosri list bani to leak hai."""
    source = _src("planner.py")
    assert "from . import exammodel" in source
    assert "exam_ask = bool(exammodel.is_request(exam_text))" in source
    assert "exammodel.request_reason(" in source
    assert source.count("def _exam_signal(") == 0


def test_i_lane_ka_reason_asli_ginti_se_banta_hai():
    plan = _lane(PLAN_Q)
    lane = plan["exam_study_lane"]
    assert lane["is_exam_request"] is True
    assert lane["wanted"] is True
    assert lane["query_count"] == len(plan["exam_study"]) == 7
    assert f"({lane['query_count']} query" in lane["reason"]
    for name in ("official", "textbook", "pedagogy"):
        count = sum(1 for row in plan["exam_study"] if row.get("lane") == name)
        assert f"{name}:{count}" in lane["reason"]
    # Jo lane chali hi nahi, uski ginti reason me nahi likhi jaati.
    assert "practice:0" not in lane["reason"]


def test_i_official_first_jhanda_behaviour_se_banta_hai():
    """Hardcoded True likhna us ask par jhooth hota jahan exam ka naam hi nahi."""
    plan = _lane(PAPER_Q)
    lane = plan["exam_study_lane"]
    assert lane["official_first"] is True
    assert plan["exam_study"][0]["lane"] == em.LANE_OFFICIAL
    source = _src("planner.py")
    assert 'exam_queries and exam_queries[0].get("lane")' in source
    assert '"official_first": True' not in source


def test_i_query_ko_evidence_nahi_kaha_jaata():
    """Is stage me network chalta hi nahi — `exam_evidence_read` kabhi True nahi."""
    for question in (PAPER_Q, PLAN_Q):
        lane = _lane(question)["exam_study_lane"]
        assert lane["exam_evidence_read"] is False
        assert lane["gemini_calls"] == 0
        assert lane["network_used"] is False
        assert lane["paper_is_practice_only"] is True
        assert lane["is_exam_authority"] is False
        assert lane["answer_key_is_app_made"] is True
        assert lane["question_prediction_promised"] is False
        assert lane["score_promised"] is False
        assert lane["leaked_paper_used"] is False
        assert lane["not_official_note"] == em.NOT_OFFICIAL_NOTE


def test_i_farmaish_na_ho_to_lane_khaali_aur_saaf_batati_hai():
    plan = _lane(SONG_Q)
    lane = plan["exam_study_lane"]
    assert plan["exam_study"] == []
    assert lane["wanted"] is False
    assert lane["is_exam_request"] is False
    assert lane["query_count"] == 0
    assert lane["lanes"] == []
    assert lane["official_first"] is False
    assert lane["ask"] == {}
    assert lane["reason"] == em.NOT_ASKED_REASON
    # Trading ki farmaish par bhi ye lane band rehti hai.
    assert _lane(TRADE_Q)["exam_study"] == []


def test_i_quick_mode_lane_band_nahi_karta_chhoti_karta_hai():
    """Depth kam ho to kharcha kam — par padhai poori band nahi hoti."""
    deep = _lane(PLAN_Q, "DEEP")["exam_study"]
    quick = _lane(PLAN_Q, "QUICK")["exam_study"]
    assert len(deep) == 7
    assert len(quick) == em.QUICK_STUDY_QUERIES == 4
    assert len(quick) < len(deep)
    assert len(deep) <= em.MAX_STUDY_QUERIES
    # Chhoti lane bhi official document se hi shuru hoti hai.
    assert quick[0]["lane"] == em.LANE_OFFICIAL


def test_i_exam_lane_gaane_aur_trading_ki_lane_ka_budget_nahi_khaati():
    """Ek lane doosri ka slot kha le to naapi hui coverage chup-chaap girti hai."""
    song_plan = _lane(SONG_Q)
    assert song_plan["exam_study"] == []
    assert song_plan.get("craft_study")
    trade_plan = _lane(TRADE_Q)
    assert trade_plan["exam_study"] == []
    assert trade_plan.get("trade_study")
    exam_plan = _lane(PAPER_Q)
    assert exam_plan["exam_study"]
    assert not exam_plan.get("craft_study")
    assert not exam_plan.get("trade_study")


# ── 10. DISCOVERY TIER — apna label, apna budget, sahi connector ─────────────

class _Spy:
    name = "spy"

    def __init__(self):
        self.seen = []
        self.limits = []

    def safe_search(self, query, max_results=3):
        self.seen.append(str(query))
        self.limits.append(int(max_results))
        return {"connector": self.name, "records": [], "count": 0, "error": "",
                "reason": "", "note": "", "seconds": 0.0}

    def search(self, query, limit):
        self.seen.append(str(query))
        self.limits.append(int(limit))
        return {"records": [], "log": []}


def _tasks_for(entries, plan_extra=None, per_connector=3, max_web=5):
    discovery = SourceDiscovery()
    spy = _Spy()
    discovery.papers.by_name = lambda name: spy
    discovery.books.by_name = lambda name: spy
    discovery.web = spy
    plan = {"web": True, "papers": ["semantic_scholar"],
            "books": ["open_library"], "datasets": [], "patents": [],
            "markets": [], "exam_study": entries}
    plan.update(plan_extra or {})
    tasks = discovery._tasks(["primary question"], plan, per_connector, max_web)
    return [label for label, _fn in tasks], tasks, spy


def test_j_label_me_lane_aur_asli_channel_dono_likhe_jaate_hain():
    """Sirf lane likhna us waqt jhooth hota jab query chup-chaap web par chali jaaye."""
    labels, _tasks, _spy = _tasks_for([
        {"query": "RPF SI official syllabus notification pdf",
         "lane": em.LANE_OFFICIAL},
        {"query": "mathematics textbook chapters list", "lane": em.LANE_TEXTBOOK},
        {"query": "spaced repetition retrieval practice", "lane": em.LANE_PEDAGOGY},
        {"query": "RPF SI previous year question paper pdf",
         "lane": em.LANE_PRACTICE}])
    assert "exam_study_official_web" in labels
    assert "exam_study_textbook_books" in labels
    assert "exam_study_pedagogy_papers" in labels
    assert "exam_study_practice_web" in labels
    assert not any(label.startswith("craft_study") for label in labels)
    assert not any(label.startswith("trade_study") for label in labels)


def test_j_book_connector_na_mile_to_label_jhooth_nahi_bolta():
    """Kitaab ki lane web par giri — label me "web" likha jaana zaroori hai.

    Sirf `exam_study_textbook` likhna us haalat me chhupa jhooth hota: log
    padhne wala samajhta ki kitaab ka connector chala tha.
    """
    discovery = SourceDiscovery()
    spy = _Spy()
    discovery.books.by_name = lambda name: None
    discovery.books.connectors = []
    discovery.papers.by_name = lambda name: None
    discovery.papers.connectors = []
    discovery.web = spy
    plan = {"web": True, "papers": [], "books": [], "datasets": [],
            "patents": [], "markets": [], "exam_study": [
                {"query": "mathematics textbook chapters list",
                 "lane": em.LANE_TEXTBOOK},
                {"query": "spaced repetition retrieval practice",
                 "lane": em.LANE_PEDAGOGY}]}
    labels = [label for label, _fn in discovery._tasks(["primary question"],
                                                      plan, 3, 5)]
    assert "exam_study_textbook_web" in labels
    assert "exam_study_pedagogy_web" in labels
    assert "exam_study_textbook_books" not in labels
    assert "exam_study_pedagogy_papers" not in labels


def test_j_lane_ki_query_asli_me_apne_hi_channel_par_pahunchti_hai():
    """Label sahi ho par query galat connector par jaaye — chhupa jhooth.

    Syllabus/chapter ki baat KITAAB me milti hai, "kaise padhein" ka
    (retrieval practice, spacing) PAPER me. Dono spy alag hain, isliye
    routing ulta hone par (books↔papers) ye test RED hota hai — label wahi
    rehta hai.
    """
    discovery = SourceDiscovery()
    papers_spy, books_spy, web_spy = _Spy(), _Spy(), _Spy()
    papers_spy.name, books_spy.name, web_spy.name = "papers", "books", "web"
    discovery.papers.by_name = lambda name: papers_spy
    discovery.books.by_name = lambda name: books_spy
    discovery.web = web_spy
    plan = {"web": True, "papers": ["semantic_scholar"],
            "books": ["open_library"], "datasets": [], "patents": [],
            "markets": [], "exam_study": [
                {"query": "RPF SI official syllabus notification pdf",
                 "lane": em.LANE_OFFICIAL},
                {"query": "spaced repetition retrieval practice",
                 "lane": em.LANE_PEDAGOGY},
                {"query": "mathematics textbook chapters list",
                 "lane": em.LANE_TEXTBOOK}]}
    for label, fn in discovery._tasks(["primary question"], plan, 3, 5):
        if label.startswith("exam_study"):
            fn()
    assert "mathematics textbook chapters list" in books_spy.seen
    assert "mathematics textbook chapters list" not in papers_spy.seen
    assert "spaced repetition retrieval practice" in papers_spy.seen
    assert "spaced repetition retrieval practice" not in books_spy.seen
    assert "RPF SI official syllabus notification pdf" not in books_spy.seen
    assert "RPF SI official syllabus notification pdf" not in papers_spy.seen


def test_j_exam_study_khaali_ho_to_ek_bhi_extra_task_nahi_banta():
    """Har sawaal par ye tier chalna is lane ki sabse badi galti hoti."""
    labels, _tasks, _spy = _tasks_for([])
    assert not any(label.startswith("exam_study") for label in labels)
    discovery = SourceDiscovery()
    plan = {"web": True, "papers": [], "books": [], "datasets": [],
            "patents": [], "markets": []}
    labels2 = [label for label, _fn in discovery._tasks(["q"], plan, 3, 5)]
    assert not any(label.startswith("exam_study") for label in labels2)


def test_j_is_tier_ka_budget_chhota_aur_apna_hai():
    """Ek query se 5 record maangna asli sawaal ka discovery bhookha rakhta."""
    _labels, tasks, spy = _tasks_for([
        {"query": "spaced repetition retrieval practice",
         "lane": em.LANE_PEDAGOGY},
        {"query": "RPF SI official syllabus notification pdf",
         "lane": em.LANE_OFFICIAL}], per_connector=9, max_web=9)
    for label, fn in tasks:
        if label.startswith("exam_study"):
            fn()
    assert spy.limits and max(spy.limits) <= 2


def test_j_ek_hi_query_do_label_ke_saath_do_baar_nahi_jaati():
    """Casefold dedup: bade-chhote akshar ya space se do call nahi bante."""
    labels, _tasks, _spy = _tasks_for([
        {"query": "RPF SI official syllabus notification pdf",
         "lane": em.LANE_OFFICIAL},
        {"query": "  rpf si OFFICIAL syllabus notification PDF ",
         "lane": em.LANE_PEDAGOGY},
        {"query": "", "lane": em.LANE_TEXTBOOK}])
    assert len([l for l in labels if l.startswith("exam_study")]) == 1


def test_j_tier_apni_chhat_se_zyada_kabhi_nahi_bhejta():
    """`MAX_STUDY_QUERIES` ka slice tier me bhi lagta, sirf planner me nahi."""
    entries = [{"query": f"exam study query number {n} of the lane",
                "lane": em.LANE_PEDAGOGY} for n in range(40)]
    labels, _tasks, _spy = _tasks_for(entries)
    exam_labels = [l for l in labels if l.startswith("exam_study")]
    assert len(exam_labels) == em.MAX_STUDY_QUERIES
    assert em.MAX_STUDY_QUERIES < 40


def test_j_gaane_ka_pehra_exam_ki_query_par_jaan_boojh_kar_nahi_lagta():
    """`is_lyrics_hunt` gaane ki lane ka guard hai — exam par lagana lane mixing.

    "lyrics" jaisa shabd exam ki query me aa sakta hai (English literature ka
    syllabus), aur us par gaane ka pehra lagana exam ka lane band kar deta.
    """
    labels, _tasks, _spy = _tasks_for([
        {"query": "class 10 english poem lyrics syllabus chapters",
         "lane": em.LANE_TEXTBOOK}])
    assert any(label.startswith("exam_study") for label in labels)
    source = _src("source_discovery.py")
    exam_block = source.split("EXAM/PADHAI ka EXAM-STUDY")[1].split(
        "return tasks")[0]
    # Comment me in guard ka naam JAAN-BOOJH KAR likha hai (wajah likhna zaroori
    # hai), isliye naap sirf CHALNE wale code par lagti hai.
    code = "\n".join(line for line in exam_block.splitlines()
                     if not line.strip().startswith("#"))
    assert "is_lyrics_hunt" not in code
    assert "seen_craft" not in code
    assert "seen_trade" not in code
    assert "seen_music" not in code
    # Aur wajah kahin likhi bhi honi chahiye — chup-chaap chhod dena nahi.
    assert "is_lyrics_hunt" in exam_block


# ── 11. DO LAB EK NA HO JAAYEIN — deliverable ka naap vs hypothesis ka naap ──

def _exam_lab(question=PAPER_Q, text=PAPER, syllabus=SYLLABUS, plan=PLAN_TEXT,
              ask=None, **extra):
    return lab.run_exam_lab(question=question, text=text,
                            syllabus_text=syllabus, plan_text=plan,
                            ask=ask if ask is not None else em.ask_of(question),
                            **extra)


def test_k_paanch_recipe_hai_aur_wo_hypothesis_wali_naap_nahi_hain():
    """EXAM LAB apni paanch naap laayi — purani 12 me se ek bhi hataayi nahi."""
    assert lab.EXAM_RECIPES == ("syllabus_coverage", "difficulty_mix",
                                "duplicate_questions", "question_solvability",
                                "plan_time_budget")
    assert len(lab.RECIPES) == 12 + len(lab.EXAM_RECIPES)
    for recipe in lab.EXAM_RECIPES:
        assert recipe in lab.RECIPES
        assert recipe in lab._EXAM_WHAT
    # Paper ki naap paper ke saath, plan ki plan ke saath — dono list disjoint.
    assert set(lab._EXAM_PAPER_RECIPES) | set(lab._EXAM_PLAN_RECIPES) == \
        set(lab.EXAM_RECIPES)
    assert not set(lab._EXAM_PAPER_RECIPES) & set(lab._EXAM_PLAN_RECIPES)


def test_k_verdict_ki_bhasha_hypothesis_wali_se_alag_hai():
    """Ek hi wording dono jagah = paper ki kami hypothesis ke khaate me."""
    assert sorted(lab._EXAM_ROLLUP_REASON) == sorted(lab._ROLLUP_REASON)
    for status, text in lab._EXAM_ROLLUP_REASON.items():
        assert text != lab._ROLLUP_REASON[status]
    assert "paper/plan" in lab._EXAM_ROLLUP_REASON[lab.TESTED_FAIL]
    assert "hypothesis" in lab._ROLLUP_REASON[lab.TESTED_FAIL]
    assert lab.EXAM_LAB_SUBHEADING != lab.LAB_SUBHEADING
    assert lab.EXAM_SUBJECT_ID == "EXAM-DELIVERABLE"
    assert "hypothesis" not in lab.EXAM_SUBJECT_ID.lower()


def test_k_bane_hue_paper_ki_kami_khud_pakdi_jaati_hai():
    """Duplicate Q1↔Q3 aur adhoora coverage — dono FAIL bankar bahar aate hain."""
    report = _exam_lab()
    assert report["ran"] is True
    assert report["verdict"] == lab.TESTED_FAIL
    assert report["verdict_reason"] == lab._EXAM_ROLLUP_REASON[lab.TESTED_FAIL]
    codes = {test["recipe"]: test["status"] for test in report["tests"]}
    assert codes["syllabus_coverage"] == lab.TESTED_FAIL
    assert codes["duplicate_questions"] == lab.TESTED_FAIL
    assert codes["difficulty_mix"] == lab.TESTED_PASS
    assert codes["question_solvability"] == lab.TESTED_PASS
    assert report["counts"][lab.TESTED_FAIL] == 2
    assert report["counts"][lab.TESTED_PASS] == 2
    assert report["material"]["questions"] == 5
    assert report["material"]["topics"] == 3
    assert report["material"]["plan_rows"] == 3
    # PASS ka matlab "asli exam jaisa" kabhi nahi.
    assert report["is_established_fact"] is False
    assert report["real_world_experiment_pending"] is True
    assert report["gemini_calls"] == 0
    assert report["provider_cost"] == 0
    assert report["network_used"] is False


def test_k_time_kitna_mila_ye_likha_na_ho_to_plan_pass_nahi_hota():
    """Default maan kar PASS dena sabse aasaan jhooth hota — wahi band hai."""
    report = _exam_lab()
    row = [t for t in report["tests"] if t["recipe"] == "plan_time_budget"][0]
    assert row["status"] == lab.DATA_MISSING
    assert row["reason_code"] == em.NO_TIME_BUDGET
    assert not (row.get("numbers") or {})
    # Din likhe ho to wahi naap chalti hai (aur 700-minute wali line pakadti hai).
    with_days = lab.run_exam_lab(question=PLAN_Q, text=PLAN_TEXT,
                                 ask=em.ask_of(PLAN_Q))
    plan_row = [t for t in with_days["tests"]
                if t["recipe"] == "plan_time_budget"][0]
    assert plan_row["status"] in (lab.TESTED_PASS, lab.TESTED_FAIL)
    assert plan_row.get("numbers")
    # Kul time fit hai (850 min vs 5400 min) par Day 3 par 700 min ka bojh
    # insaani hadd (600) se bahar hai — yahi wajah likhi jaani chahiye. Sirf
    # "kul time fit hai" dekhkar PASS dena is naap ka sabse aasaan jhooth hai.
    assert plan_row["status"] == lab.TESTED_FAIL
    assert plan_row["reason_code"] == "plan_day_load_above_ceiling"
    assert plan_row["numbers"]["fits"] is True
    assert plan_row["numbers"]["day_realistic"] is False
    assert [t["recipe"] for t in with_days["tests"]] == ["plan_time_budget"]


def test_k_saamaan_na_mile_to_spec_banti_hai_par_pass_nahi():
    """Spec hi na banane se report chup ho jaati aur "sab theek tha" lagta."""
    empty = lab.run_exam_lab(question=PAPER_Q, text="", ask=em.ask_of(PAPER_Q))
    assert empty["verdict"] == lab.DATA_MISSING
    assert empty["ran"] is False
    assert empty["counts"][lab.DATA_MISSING] == 4
    assert empty["counts"][lab.TESTED_PASS] == 0
    assert {t["reason_code"] for t in empty["tests"]} == {em.NO_PAPER,
                                                         em.NO_SYLLABUS}
    assert all(not (t.get("numbers") or {}) for t in empty["tests"])
    assert empty["note"]


def test_k_exam_ki_farmaish_na_ho_to_koi_naap_nahi_banti():
    """Gaane ke jawab par exam LAB chalna hi is stage ki sabse badi galti hoti."""
    song = lab.run_exam_lab(question=SONG_Q, text="ek gaana likha gaya")
    assert song["verdict"] == lab.NOT_TESTABLE_HERE
    # `verdict_reason` yahan CODE hai (machine ke liye), aur uska insaan wala
    # matlab `_EXAM_ROLLUP_REASON` me. Dono ko ek maan lena galat hai.
    assert song["verdict_reason"] == "no_exam_deliverable"
    assert lab._EXAM_ROLLUP_REASON[lab.NOT_TESTABLE_HERE] != song["verdict_reason"]
    assert song["tests"] == []
    assert lab.exam_lab_limits(song) == []
    assert song["ran"] is False
    killed = _exam_lab(kill_switch=True)
    assert killed["verdict"] == lab.NOT_RUN
    assert killed["verdict_reason"] == "kill_switch"
    assert killed["tests"] == []
    assert lab.exam_lab_limits(killed) == []


def test_k_audit_ki_seema_chali_hui_naap_ki_ginti_se_banti_hai():
    """Likhe daawe se nahi — `_exam_ran` PASS/FAIL hi ginta hai."""
    report = _exam_lab()
    limits = lab.exam_lab_limits(report)
    assert len(limits) == 7
    assert limits[0] == em.NOT_OFFICIAL_NOTE
    joined = " ".join(limits)
    assert "PROXY" in joined
    assert "duplicate" in joined.lower()
    assert "2 naap FAIL hui" in joined
    # Jo naap chali hi nahi (plan time budget), uski seema-line nahi banti.
    assert "time-budget naapa gaya hai" not in joined
    assert len(lab.exam_lab_limits(lab.run_exam_lab(
        question=PAPER_Q, text="", ask=em.ask_of(PAPER_Q)))) == 2
    assert lab.exam_lab_limits({}) == []
    assert lab.exam_lab_limits(None) == []


def test_k_audit_chhat_asli_append_site_ki_ginti_par_pinned_hai():
    """Chhat kam hui to sabse aakhir wali line — FAIL ki ginti — kat jaati."""
    source = inspect.getsource(lab.exam_lab_limits)
    appends = source.count("limits.append")
    assert appends == 8
    assert lab.EXAM_MAX_AUDIT_LIMIT_LINES == appends + 1
    assert lab.EXAM_MAX_AUDIT_LIMIT_LINES != lab.MAX_AUDIT_LIMIT_LINES


def test_k_exam_ki_seema_hypothesis_wale_audit_me_kabhi_nahi_ghulti():
    """Dono ko ek report me ghol dena hi purani galti hai.

    Sirf "limits alag hain" kaafi nahi tha: hypothesis wali report me bhi
    `tests` aur `note` hote hain, isliye use galti se `exam_lab_section()` me
    daal dena par jawab me "apne bane paper/plan ko naapa" chhap sakta tha —
    jo naapa hi nahi gaya. Ab report ki SHAPE se pehchaan hoti hai.
    """
    report = _exam_lab()
    assert lab.exam_lab_limits(report)
    assert lab.lab_limits(report) == []
    assert lab.is_exam_report(report) is True
    hypothesis_report = lab.run_lab(hypotheses=[], question=SCIENCE_Q)
    assert lab.is_exam_report(hypothesis_report) is False
    assert lab.exam_lab_limits(hypothesis_report) == []
    assert lab.exam_lab_section(hypothesis_report) == ""
    # Note/tests wali nakli report bhi exam ka block nahi khol sakti.
    assert lab.exam_lab_section({"note": "kuch", "tests": [{"recipe": "x"}]}) == ""
    assert lab.exam_lab_limits({"tests": [{"recipe": "x"}]}) == []
    assert lab.exam_lab_section({}) == ""
    assert lab.exam_lab_section(None) == ""
    assert lab.is_exam_report(None) is False
    section = lab.exam_lab_section(report)
    assert section.startswith(lab.EXAM_LAB_SUBHEADING)
    assert em.NOT_OFFICIAL_NOTE in section
    assert lab.LAB_SUBHEADING not in section


def test_k_public_record_ginti_deta_hai_daawa_nahi():
    """Khaali report par bhi record BANTA hai — chup rehna sabse aasaan jhooth."""
    blank = lab.exam_lab_public_record({})
    assert blank["ran"] is False
    assert blank["verdict"] == lab.NOT_RUN
    assert blank["tests"] == 0
    assert blank["recipes_ran"] == {recipe: 0 for recipe in lab.EXAM_RECIPES}
    for flag, value in (("paper_is_practice_only", True),
                        ("is_exam_authority", False),
                        ("answer_key_is_app_made", True),
                        ("question_prediction_promised", False),
                        ("score_promised", False),
                        ("leaked_paper_used", False),
                        ("difficulty_is_proxy", True),
                        ("network_used", False),
                        ("randomness_used", False),
                        ("model_written_code_executed", False),
                        ("is_established_fact", False),
                        ("real_world_experiment_pending", True)):
        assert blank[flag] is value, flag
    assert lab.exam_lab_public_record(None) == {"ran": False,
                                                "reason": "no_exam_lab"}
    live = lab.exam_lab_public_record(_exam_lab())
    assert live["ran"] is True
    assert live["recipes_ran"]["plan_time_budget"] == 0
    assert live["recipes_ran"]["syllabus_coverage"] == 1
    assert live["gemini_calls"] == 0
    assert "questions" in live["material"]


def test_k_wahi_farmaish_dobara_wahi_nateeja_deti_hai():
    """Zero randomness ka asli sabooot: do run bit-identical."""
    first, second = _exam_lab(), _exam_lab()
    strip = lambda rec: [(t["recipe"], t["status"], t.get("reason_code"),
                          t.get("computed")) for t in rec["tests"]]
    assert strip(first) == strip(second)
    assert first["counts"] == second["counts"]
    assert first["seed"] == second["seed"]
    assert lab.exam_lab_limits(first) == lab.exam_lab_limits(second)


# ── 12. WIRING — jawab me section sirf exam ki farmaish par ─────────────────

def test_l_synthesizer_dono_jagah_exam_lab_report_leta_hai():
    """Assemble le aur audit na le, to naap ka zikr audit se gayab ho jaata."""
    from research_engine import synthesizer_claude as sc_mod
    for method in (sc_mod.FinalSynthesizer.assemble,
                   sc_mod.FinalSynthesizer._audit_section):
        params = inspect.signature(method).parameters
        assert "exam_lab_report" in params
        assert params["exam_lab_report"].default is None
    body = _src("synthesizer_claude.py")
    # Asli code me ye call do line me toota hua hai, isliye whitespace nikaal
    # kar naapa jaata hai — warna sirf formatting badalne se test jhooth bolta.
    squeezed = re.sub(r"\s+", "", body)
    assert "exam_lab_section(exam_lab_report)" in squeezed
    assert "exam_lab_limits(exam_lab_report)[:EXAM_MAX_AUDIT_LIMIT_LINES]" in squeezed
    # Hypothesis wali chhat exam ki lines par nahi lagni chahiye.
    assert "exam_lab_limits(exam_lab_report)[:MAX_AUDIT_LIMIT_LINES]" not in squeezed
    # Aur ulta bhi: hypothesis wali limits exam ki chhat se na kate.
    assert "lab_limits(lab_report)[:EXAM_MAX_AUDIT_LIMIT_LINES]" not in squeezed


def test_l_orchestrator_exam_lab_sirf_exam_ki_farmaish_par_chalata_hai():
    """Har run par ye stage chalna = kharcha + jhoothi "naap ho gayi" ki line."""
    body = _src("orchestrator.py")
    assert "exammodel.is_request(question)" in body
    assert "lab.run_exam_lab(" in body
    block = body.split("lab.run_exam_lab(")[0].rsplit("if ", 1)[1]
    assert "exammodel.is_request" in block
    assert 'exam_lab_report=passes.get("exam_lab")' in body


# ── 13. ADHOORA NUMBER — `numbers=` sirf CHALI hui naap ke saath ─────────────

_EXAM_RUNNERS = ("_run_syllabus_coverage", "_run_difficulty_mix",
                 "_run_duplicate_questions", "_run_question_solvability",
                 "_run_plan_time_budget")


def _result_calls(func_node):
    """Us function ke andar ke saare `_result(...)` call (nested bhi)."""
    return [node for node in ast.walk(func_node)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id == "_result"]


def _status_name(call):
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Name):
        return call.args[1].id
    for keyword in call.keywords:
        if keyword.arg == "status" and isinstance(keyword.value, ast.Name):
            return keyword.value.id
    return ""


def test_m_naapa_hua_number_kabhi_bina_chali_naap_ke_bahar_nahi_jaata():
    """`numbers=` DATA_MISSING/NOT_RUN par jaana = "naapa hi nahi" ko number de dena.

    Ye AST guard isliye hai ki ye galti aage kabhi bhi ek naye `return` me
    aa sakti hai, aur uska nateeja report me sabse zeharila hota: audit us
    number par bharosa karta hai jo kisi naap se aaya hi nahi.
    """
    tree = ast.parse(_src("lab.py"))
    functions = {node.name: node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}
    for name in _EXAM_RUNNERS:
        assert name in functions, name
        calls = _result_calls(functions[name])
        assert calls, name
        for call in calls:
            has_numbers = any(keyword.arg == "numbers"
                              for keyword in call.keywords)
            status = _status_name(call)
            assert status in ("TESTED_PASS", "TESTED_FAIL"), (name, status)
            assert has_numbers, (name, status)
    # DATA_MISSING ka ek hi darwaza hai, aur wo number bhejta hi nahi.
    missing = functions["_exam_missing"]
    missing_calls = _result_calls(missing)
    assert len(missing_calls) == 1
    assert _status_name(missing_calls[0]) == "DATA_MISSING"
    assert not any(keyword.arg == "numbers"
                   for keyword in missing_calls[0].keywords)
    assert not any(keyword.arg == "computed"
                   for keyword in missing_calls[0].keywords)
    for name in _EXAM_RUNNERS:
        source = inspect.getsource(getattr(lab, name))
        assert "_exam_missing(spec," in source, name


def test_m_har_chali_hui_naap_ke_number_asli_split_se_aate_hain():
    """Haath se bhara dict aur split ka dict alag ho jaayein — chup-chaap drift."""
    report = _exam_lab()
    rows = {test["recipe"]: test for test in report["tests"]}
    questions = _questions()
    # Solvability ka calculator LAB ke bahar se aata hai (`SafeNumericExecutor`),
    # isliye wahi executor yahan bhi diya jaata hai — warna split "no_evaluator"
    # kehta aur ye milaan bemaani ho jaata.
    evaluate = lab.SafeNumericExecutor(lab.NumericExecutionPolicy()).evaluate
    pairs = (("syllabus_coverage",
              em.coverage_split(em.syllabus_topics(SYLLABUS), questions)),
             ("difficulty_mix", em.difficulty_split(questions)),
             ("duplicate_questions", em.duplicate_split(questions)),
             ("question_solvability",
              em.solvability_split(questions, evaluate=evaluate)))
    for recipe, split in pairs:
        assert rows[recipe]["numbers"] == split.to_dict(), recipe
        assert rows[recipe]["numbers"]["ok"] is True, recipe
        # Chali hui naap par koi "kyun nahi chali" wala code nahi hota.
        assert rows[recipe]["numbers"]["reason_code"] == "", recipe
        assert rows[recipe]["status"] in (lab.TESTED_PASS, lab.TESTED_FAIL)
    # "naap chal gayi" ka matlab "achchha hai" nahi — ok True par status FAIL.
    assert rows["syllabus_coverage"]["numbers"]["ok"] is True
    assert rows["syllabus_coverage"]["status"] == lab.TESTED_FAIL
