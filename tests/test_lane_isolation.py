"""#150c — LANE ISOLATION: trading ka jawab gaane/design ki cheezon se na mile.

intel ki shart shabd-ba-shabd: "sab mix mt kr dena model mangu to gaane waali
cheeje work krti dikhe to answer khraab ho jaaye aesa nhi hona chahiye".

Asli leak `planner.ResearchPlanner.classify()` me tha, gaane ke module me nahi.
`QUESTION_TYPES["creative"]` me nanga shabd "banao" pada hai. "US100 aur XAUUSD
ka scalping model banao" me bhi wahi "banao" hai — isliye trading ki farmaish
`is_creative True` ho jaati thi, `relevant_fields` me **Design** aur **Materials
Science** ghus jaate the, aur ek extra creative sub-question ban jaata tha. Ye
teen cheezein aage reasoning prompt (`gemini_reasoning.py`), hypothesis prompt
(`hypothesis.py`), synthesizer aur search-query building tak jaati hain — yaani
trading ke jawab me design/materials ka rang chadh jaata tha.

Ulta jhooth bhi tha: "gaana likh do" me koi cue-shabd nahi milta, to gaane ki
farmaish khud `is_creative False` aati thi.

Ab faisla nayi keyword list se nahi, un DO module se aata hai jo pehle se yahi
naapte hain — `craft.detect(q)["is_request"]` aur `trademodel.is_request(q)`.
Aur purani keyword-hit hataayi nahi gayi: wo ab `wants_construction` key me
zinda hai, kyunki "user kuch BANWANA chahta hai" aur "user ne creative rachna
maangi hai" do alag baatein hain.

Is file ka sabse important negative test: non-trading "banao" wala sawaal
(gadget banao) aur science wala sawaal — dono ka bartaav 1 bit bhi nahi
badalta. 0 Gemini call, 0 network, koi randomness nahi.

#171c me isi file me exam/padhai ka rasta bhi jud gaya: wahi bimari doosri
jagah thi. "RPF SI ka paper banao" aur "padhai ka plan banao" me bhi wahi nanga
"banao" hai, aur craft.py ke `letter` form me nanga "cover" pada tha — isliye
"syllabus cover karne ka plan banao" creative PATRA ban jaata tha. Ab exam ka
gate `exammodel.is_request(q)` hai aur "cover" cue apna sandarbh maangta hai;
asli cover-letter ki farmaish zinda hai.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import craft  # noqa: E402
from research_engine import exammodel  # noqa: E402
from research_engine import trademodel  # noqa: E402
from research_engine.planner import (  # noqa: E402
    FIELD_MAP,
    QUESTION_TYPES,
    ResearchPlanner,
)

P = ResearchPlanner()

# intel ke 30-section challenge ki asli farmaish ka chhota roop.
TRADE_ASK = ("US100 aur XAUUSD ka intraday scalping trading model banao, "
             "15M context 5M confirmation 1M entry")
# Wahi trading topic, par BANANE ki farmaish ke bina — sirf padhne ki. Dhyaan:
# "strategy"/"model"/"plan" jaise NAAM khud BUILD signal hain (`_BUILD_RE`),
# isliye is line me un me se ek bhi shabd nahi hai.
TRADE_STUDY_ASK = "US100 ke order flow par research kya kehti hai"
SONG_ASK = "hindi me ek sad gaana likh do"
# Non-trading "banao": iska bartaav bilkul nahi badalna chahiye.
#
# #171c ke baad ye ask badla gaya. Pehle yahan "mujhe ek plan banao padhai ka"
# tha — par wo asal me PADHAI ki farmaish hai, aur #171c me exam-study lane usi
# ke liye khuli. Yaani wo ab creative control nahi reh gaya (uska naya, sahi
# bartaav neeche `STUDY_PLAN_ASK` par pin kiya gaya hai). Control ke liye ab
# aisa "banao" liya gaya hai jo na trading ka hai, na padhai ka, na rachna ka.
BUILD_ASK = "mujhe ek naya gadget banao ghar ke liye"
PLAN_ASK = BUILD_ASK          # purana naam zinda, taaki koi test toote nahi
# #171c: padhai ka plan — ab ye exam-study ask hai, creative rachna nahi.
STUDY_PLAN_ASK = "mujhe ek plan banao padhai ka"
SCIENCE_ASK = "room temperature superconductivity ka evidence kya hai"
# Dono farmaish ek saath — yahan creative lane BAND nahi hoti.
BOTH_ASK = "US100 ka scalping model banao aur uspe ek gaana likh do"

CREATIVE_SUB = "kya abhi tak unknown hai aur kaun sa test isse settle karega?"

# Sabse patla trading ask: iska domain profile "economics" nahi banta, isliye
# `financial` type sirf #150c ke append se aa sakta hai — aur "creative" hatane
# ke baad `detected` KHAALI ho jaata hai, jisse fallback bhi naapa jaata hai.
THIN_TRADE_ASK = "ek scalping setup banao 5M chart par"


def _src(rel):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, rel), "r", encoding="utf-8") as fh:
        return fh.read()


# ── 1. trading ki farmaish par creative lane band ─────────────────────────────
def test_trading_model_ki_farmaish_creative_rachna_nahi_hai():
    cls = P.classify(TRADE_ASK)
    assert "creative" not in cls["all_detected_types"]
    assert "creative" not in cls["question_types"]
    assert cls["is_creative"] is False


def test_trading_ask_me_design_aur_materials_science_field_nahi_aate():
    """Field-wise safai — poori list ka safaya nahi."""
    fields = P.classify(TRADE_ASK)["relevant_fields"]
    assert "Design" not in fields
    assert "Materials Science" not in fields
    # `Engineering` creative ka bhi field hai AUR technical ka bhi. Sirf creative
    # ki wajah se aaya hota to jaata; technical ki wajah se ruka hua hai. Blanket
    # `FIELD_MAP["creative"]` hata dene wala code isse bhi gira deta.
    assert "Engineering" in fields
    assert "Engineering" in FIELD_MAP["creative"]
    assert "Engineering" in FIELD_MAP["technical"]


def test_trading_ask_ko_apne_hi_field_milte_hain():
    cls = P.classify(TRADE_ASK)
    assert "financial" in cls["all_detected_types"]
    assert "Economics" in cls["relevant_fields"]
    assert "Finance" in cls["relevant_fields"]


def test_creative_sub_question_trading_jawab_me_nahi_ghusta():
    trade_subs = P.sub_questions(TRADE_ASK)
    assert not any(CREATIVE_SUB in s for s in trade_subs)
    # ...par wahi sub-question apni jagah (non-trading banao) par zinda hai.
    assert any(CREATIVE_SUB in s for s in P.sub_questions(PLAN_ASK))


def test_trading_ask_ki_koi_search_query_design_par_nahi_jaati():
    cls = P.classify(TRADE_ASK)
    queries = P.search_queries(TRADE_ASK, cls, round_no=1)
    assert queries
    for query in queries:
        low = query.lower()
        assert "design" not in low
        assert "materials science" not in low


# ── 2. purana signal gum nahi hua ─────────────────────────────────────────────
def test_banwane_ka_signal_alag_key_me_zinda_hai():
    """"banao" ki hit hataayi nahi gayi — sirf uska naam theek kiya gaya."""
    cls = P.classify(TRADE_ASK)
    assert cls["wants_construction"] is True
    assert cls["is_creative"] is False


def test_banao_shabd_creative_list_se_hataaya_nahi_gaya():
    # Ilaaj list kaat kar nahi kiya gaya — warna har "banao" wala sawaal apna
    # purana Design/Engineering field kho deta.
    assert "banao" in QUESTION_TYPES["creative"]
    assert FIELD_MAP["creative"] == ["Design", "Engineering", "Materials Science"]


def test_har_sawaal_par_wants_construction_key_hoti_hai():
    for ask in (TRADE_ASK, SONG_ASK, PLAN_ASK, SCIENCE_ASK, TRADE_STUDY_ASK):
        cls = P.classify(ask)
        assert "wants_construction" in cls
        assert isinstance(cls["wants_construction"], bool)


# ── 3. gaane ki farmaish ka ulta jhooth bhi theek hua ─────────────────────────
def test_gaane_ki_farmaish_par_creative_flag_zinda_hota_hai():
    """Pehle "gaana likh do" khud `is_creative False` aata tha."""
    cls = P.classify(SONG_ASK)
    assert cls["is_creative"] is True
    assert cls["wants_construction"] is True
    # Aur ye trading ki farmaish nahi hai — dono gate alag hain.
    assert trademodel.is_request(SONG_ASK) is False


def test_dono_farmaish_ek_saath_ho_to_creative_lane_band_nahi_hoti():
    """Model + gaana dono maange gaye — gaane ka haq nahi chhinta."""
    assert trademodel.is_request(BOTH_ASK) is True
    assert bool(craft.detect(BOTH_ASK).get("is_request")) is True
    cls = P.classify(BOTH_ASK)
    assert cls["is_creative"] is True
    assert "creative" in cls["all_detected_types"]


# ── 4. sabse important: baaki kisi sawaal ka bartaav nahi badla ───────────────
def test_non_trading_banao_ask_ka_bartaav_bilkul_wahi_hai():
    cls = P.classify(PLAN_ASK)
    assert cls["all_detected_types"] == ["creative"]
    assert cls["relevant_fields"] == ["Design", "Engineering", "Materials Science"]
    assert cls["is_creative"] is True
    assert cls["wants_construction"] is True


# ── 5. #171c: padhai/exam ki farmaish bhi creative rachna nahi hai ────────────
def test_padhai_ka_plan_creative_rachna_nahi_hai():
    """"plan banao padhai ka" — Design/Materials Science nahi, Education."""
    cls = P.classify(STUDY_PLAN_ASK)
    assert cls["is_exam_ask"] is True
    assert cls["is_creative"] is False
    assert "creative" not in cls["all_detected_types"]
    assert "educational" in cls["all_detected_types"]
    assert "Design" not in cls["relevant_fields"]
    assert "Materials Science" not in cls["relevant_fields"]
    assert "Education" in cls["relevant_fields"]
    # Purana signal gum nahi hua — user kuch banwana hi chahta hai.
    assert cls["wants_construction"] is True


def test_padhai_ki_farmaish_par_creative_sub_question_nahi_banta():
    assert not any(CREATIVE_SUB in s for s in P.sub_questions(STUDY_PLAN_ASK))
    # ...aur wahi sub-question apni jagah (gair-padhai "banao") par zinda hai.
    assert any(CREATIVE_SUB in s for s in P.sub_questions(BUILD_ASK))


def test_exam_ask_par_gaane_wala_ya_trading_wala_taala_nahi_khulta():
    """Ek hi sawaal par teen gate: exam khula, craft aur trade band."""
    for ask in (STUDY_PLAN_ASK,
                "RPF SI ka pura question paper banao 120 question ke saath",
                "class 10 maths ka syllabus cover karne ka plan banao"):
        assert exammodel.is_request(ask) is True, ask
        assert bool(craft.detect(ask).get("is_request")) is False, ask
        assert trademodel.is_request(ask) is False, ask


def test_gaane_aur_trading_ki_farmaish_par_exam_lane_nahi_khulti():
    """Ulta rasta: exam lane doosre lane ke sawaal nahi kha jaati."""
    for ask in (SONG_ASK, BOTH_ASK, TRADE_ASK, THIN_TRADE_ASK, SCIENCE_ASK,
                BUILD_ASK):
        assert exammodel.is_request(ask) is False, ask


def test_exam_lane_ka_faisla_planner_apni_copy_se_nahi_leta():
    """Gate ek hi jagah se aata hai — `exammodel.is_request()` se."""
    src = _src(os.path.join("research_engine", "planner.py"))
    assert "from . import exammodel" in src
    assert "exam_ask = bool(exammodel.is_request(question))" in src
    # Aur craft ki chhoot #171c me bhi wahi hai jo #150c me thi.
    assert "if build_cue and exam_ask and not craft_ask:" in src


def test_cover_shabd_akela_letter_ki_farmaish_nahi_banata():
    """craft.py ka "cover" cue ab apna sandarbh maangta hai.

    Naapa gaya #171c me: "syllabus cover karne ka plan banao" LETTER ban jaata
    tha. Asli cover-letter ki farmaish waise hi zinda rehni chahiye.
    """
    leak = "class 10 maths ka syllabus cover karne ka plan banao"
    assert bool(craft.detect(leak).get("is_request")) is False
    assert craft.detect(leak).get("reason") == "no_form_word"
    real = craft.detect("job ke liye cover letter banao")
    assert real.get("is_request") is True
    assert real.get("form") == "letter"
    # Sirf "letter" shabd par nahi — naukri ka sandarbh bhi chalta hai.
    assert craft.detect("internship ke liye cover banao").get("form") == "letter"


def test_science_sawaal_ko_ye_batch_chhoota_bhi_nahi():
    cls = P.classify(SCIENCE_ASK)
    assert cls["all_detected_types"] == ["scientific"]
    assert cls["is_creative"] is False
    assert cls["wants_construction"] is False
    assert "Design" not in cls["relevant_fields"]


def test_sirf_padhne_wali_trading_farmaish_par_kuch_nahi_banta():
    """Bina BUILD signal ke trading shabd sirf topic hai, farmaish nahi."""
    assert trademodel.is_request(TRADE_STUDY_ASK) is False
    cls = P.classify(TRADE_STUDY_ASK)
    assert cls["wants_construction"] is False
    assert cls["is_creative"] is False
    assert "creative" not in cls["all_detected_types"]


def test_creative_hatane_ke_baad_bhi_sawaal_bina_lane_ka_nahi_bachta():
    """Patla trading ask: strip ke baad `detected` khaali hota hai.

    Yahan teen cheezein ek saath naapi jaati hain, kyunki teeno is ek hi raste
    par hain: (a) khaali hone par `factual` ka fallback lagta hai aur uske
    saath `General Knowledge` field bhi, (b) `financial` type #150c ke append se
    aata hai (is sawaal ka domain profile economics nahi banta), aur (c) uske
    apne field bhi saath aate hain — sirf naam nahi.
    """
    cls = P.classify(THIN_TRADE_ASK)
    assert trademodel.is_request(THIN_TRADE_ASK) is True
    assert bool(craft.detect(THIN_TRADE_ASK).get("is_request")) is False
    assert cls["all_detected_types"] == ["factual", "financial"]
    assert cls["relevant_fields"] == ["General Knowledge", "Economics",
                                      "Finance", "Statistics",
                                      "Political Science"]
    assert cls["is_creative"] is False
    assert cls["wants_construction"] is True


# ── 5. faisla kahan se aata hai (naam nahi, asli code) ────────────────────────
def test_lane_ka_faisla_do_naapne_wale_module_se_aata_hai():
    """Nayi keyword list = agli baar wahi bug. Isliye source par pin.

    `craft` aur `trademodel` — dono pehle se ye naapte hain, aur dono ka gate
    do-signal wala hai. Yahan koi teesri list nahi honi chahiye.
    """
    src = _src("research_engine/planner.py")
    assert "from . import trademodel" in src
    assert 'craft_mod.detect(question) or {}).get("is_request")' in src
    assert "trade_ask = bool(trademodel.is_request(question))" in src
    assert "if build_cue and trade_ask and not craft_ask:" in src
    # `is_creative` aur `wants_construction` do alag lines par nikalte hain.
    assert '"is_creative": craft_ask or "creative" in detected,' in src
    assert '"wants_construction": build_cue or craft_ask,' in src
