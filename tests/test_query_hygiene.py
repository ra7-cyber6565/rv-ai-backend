"""
#112 ke tests — junk / meta-instruction shabd search query na banein.

Kya pin hota hai (naam nahi, BEHAVIOUR):
  * intel ke asli prompt par base query me topic aata hai, junk nahi
  * junk ki EK list hai (query_builder usi ko use karta hai)
  * jaan-boojh kar chhode gaye shabd (advance/plan/point/key) junk NAHI hain
  * junk-only query provider tak nahi jaati, aur "kyu nahi gayi" naap ke saath
    likha jaata hai — chup-chaap drop nahi
  * chhota sawaal gutt nahi jaata (khaali query = 0 result)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import query_builder as qb          # noqa: E402
from research_engine import query_hygiene as qh          # noqa: E402
from research_engine.planner import ResearchPlanner      # noqa: E402

# intel ka asli prompt — isi par defect naapa gaya tha.
MEGA = ("ache se dhyaan se kaam kro ok jldi kro or abb kaam suru kro or kaam "
        "adwance hona chahiye sab. mujhe superconductivity par room temperature "
        "ke naye dawe samjhao, 3-4 hypothesis banao aur har ek ko test karo, "
        "phir batao kaunsi strong hai")

JUNK_IN_MEGA = ("kaam", "ache", "dhyaan", "jldi", "jaldi", "abb", "suru",
                "adwance")


# ── 1. junk list — kaun andar, kaun jaan-boojh kar bahar ────────────────────
def test_intel_ke_prompt_ka_har_junk_shabd_list_me_hai():
    for word in JUNK_IN_MEGA:
        assert qh.is_junk_word(word), word


def test_junk_check_case_aur_space_se_nahi_bachta():
    assert qh.is_junk_word("  KAAM  ")
    assert qh.is_junk_word("Dhyaan")
    assert not qh.is_junk_word("")
    assert not qh.is_junk_word(None)


def test_devanagari_junk_bhi_pakda_jaata_hai():
    for word in ("काम", "ध्यान", "जल्दी", "बनाओ", "कौनसा", "हिसाब"):
        assert qh.is_junk_word(word), word


def test_intel_ke_baaki_hukum_wale_shabd_bhi_junk_hain():
    """"pura research karke btao", "hisaab lgao", "proof do", "roz" — sab hukum."""
    for word in ("pura", "poora", "karke", "hisaab", "hisab", "proof",
                 "imaandaari", "dedo", "bhejo", "dikhao", "likh", "padho",
                 "soch", "samjhe", "roz", "rozana", "ok", "plz"):
        assert qh.is_junk_word(word), word


def test_topic_ban_sakne_wale_shabd_junk_nahi_hain():
    """Ye faisla file me likha hai — topic maar dena junk se zyada nuksaan hai."""
    for word in ("advance", "advanced", "plan", "schedule", "point", "key",
                 "pattern", "previous", "water", "pure", "business", "math"):
        assert not qh.is_junk_word(word), word


# ── 2. EK paribhasha — do list hi purani galti thi ───────────────────────────
def test_query_builder_ka_meta_set_junk_ko_khud_me_leta_hai():
    """Ginti, relevance aur query — teeno ek hi JUNK list par chalein."""
    missing = sorted(w for w in qh.JUNK if w not in qb._ALWAYS_META)
    assert missing == [], missing
    assert qh.JUNK <= set(qb._META)


def test_junk_shabd_query_builder_ke_scoring_me_topic_nahi_bante():
    """Junk shabd `_META` me hain, isliye lambe prompt par unka wazan nahi."""
    for word in ("kaam", "dhyaan", "banao", "kaunsa"):
        assert word in qb._META, word
        assert word in qb._ALWAYS_META, word
    terms = qb.topic_terms(
        "ache se dhyaan se kaam kro or jldi se battery ka thermal runaway "
        "samjhao, 3-4 hypothesis banao aur har ek ko test karo")
    assert terms[:3] == ["battery", "thermal", "runaway"], terms


def test_sirf_ank_wale_token_query_me_nahi_jaate():
    """"3-4 hypothesis banao" ka "3-4" search term nahi hai."""
    got = qb._tokens(qb.normalize("3-4 hypothesis 1,000 2026 covid-19 u-235"))
    assert "3-4" not in got
    assert "1,000" not in got
    assert "2026" not in got
    # ...par ank+akshar wale asli naam bache rehte hain
    assert "covid-19" in got
    assert "u-235" in got


# ── 3. intel ka asli prompt — naapa hua defect wapas na aaye ────────────────
def test_mega_prompt_ki_base_query_me_topic_aata_hai_junk_nahi():
    """Pehle ye query "kaam ache dhyaan jaldi abb suru adwance" thi (topic_shabd=0)."""
    query = ResearchPlanner().clean_query(MEGA)
    # Poori query pin ki hai — sirf "superconductivity andar hai" check karne par
    # "har", "3-4" jaise kachre wapas aa sakte the aur test green rehta.
    assert query == "superconductivity room temperature dawe strong", query
    for junk in JUNK_IN_MEGA:
        assert junk not in query.split(), f"{junk} phir query me aa gaya: {query}"
    assert qh.query_verdict(query)["ok"]


def test_mega_prompt_ka_pehla_topic_term_asli_topic_hai():
    """Pehle topic 8ve number par tha — 7 junk shabd uske aage the."""
    terms = qb.topic_terms(MEGA)
    assert terms == ["superconductivity", "room", "temperature", "dawe",
                     "strong"], terms
    assert not [t for t in terms if qh.is_junk_word(t)], terms


def test_mega_prompt_ki_query_me_ginti_ka_token_nahi_jaata():
    assert "3-4" not in ResearchPlanner().clean_query(MEGA)


def test_chhota_sawaal_gutta_nahi_hai():
    """Sab kaat dena = khaali query = 0 result. Isliye topic bachna zaroori."""
    planner = ResearchPlanner()
    assert "cancer" in planner.clean_query(
        "cancer ki nai dawa par research kya kehti hai")
    # "point" junk nahi hai, isliye ye query poori bachti hai
    assert planner.clean_query(
        "boiling point of water at high altitude") == \
        "boiling point water high altitude"
    # itna chhota sawaal ki safai ke baad kuch bachta hi nahi — chheda nahi jaata
    assert planner.clean_query("kaunsa business karu") == "kaunsa business karu"
    assert qh.query_verdict("kaunsa business karu")["ok"]


# ── 4. content_tokens — kya "topic shabd" ginta hai ─────────────────────────
def test_content_tokens_junk_stop_aur_steering_teeno_hataata_hai():
    """Teen alag list — junk, function shabd, steering — teeno lagni chahiye.

    Function shabd 3+ akshar wale rakhe hain ("kya", "hona", "chahiye"), warna
    tokenizer khud hi 2-akshar wale ("ke", "se") uda deta hai aur stop-list ka
    kaam test hi nahi hota.
    """
    got = qh.content_tokens("kaam ache superconductivity kya hona chahiye "
                            "ke contradictory findings dhyaan se")
    assert got == ["superconductivity"], got


def test_steering_shabd_akela_topic_nahi_ginta():
    """Round 2/3 me planner khud ye shabd jodta hai — inse base topic nahi banta."""
    assert qh.content_tokens(
        "contradictory findings criticism limitations") == []
    assert not qh.query_verdict(
        "contradictory findings criticism limitations")["ok"]


def test_junk_tokens_wahi_shabd_lautata_hai_jo_mile():
    assert sorted(set(qh.junk_tokens("kaam ache superconductivity dhyaan"))) == \
        ["ache", "dhyaan", "kaam"]
    assert qh.junk_tokens("room temperature superconductivity") == []


# ── 5. gate — kaunsi query provider tak nahi jaati, aur kis naap par ────────
def test_junk_only_query_naap_ke_saath_roki_jaati_hai():
    verdict = qh.query_verdict("kaam ache dhyaan jaldi abb suru adwance")
    assert verdict["ok"] is False
    assert verdict["reason"] == qh.DROP_NO_CONTENT
    assert verdict["measured"]["topic_shabd"] == 0
    assert verdict["measured"]["junk_shabd"] == 7
    assert verdict["measured"]["junk_mile"] == \
        "abb, ache, adwance, dhyaan, jaldi, kaam, suru"


def test_bahut_chhoti_query_bhi_roki_jaati_hai():
    verdict = qh.query_verdict("ok")
    assert verdict["reason"] == qh.DROP_TOO_SHORT
    assert verdict["measured"]["chars"] == 2


def test_theek_query_par_naap_topic_ke_saath_aata_hai():
    verdict = qh.query_verdict("room temperature superconductivity")
    assert verdict["ok"] is True
    assert verdict["reason"] == qh.OK == ""
    assert verdict["measured"]["topic_shabd"] == 3
    assert verdict["measured"]["junk_shabd"] == 0
    assert verdict["measured"]["topic_mile"] == \
        "room, temperature, superconductivity"


# ── 6. filter_queries — kram, duplicate, aur "chup-chaap nahi" ──────────────
def test_filter_junk_hataata_hai_aur_kram_wahi_rakhta_hai():
    records = []
    got = qh.filter_queries(
        ["paper banao", "room temperature superconductivity",
         "karun step", "dark matter direct detection"], records)
    assert got == ["room temperature superconductivity",
                   "dark matter direct detection"]
    assert [r["query"] for r in records] == ["paper banao", "karun step"]
    assert all(r["reason"] == qh.DROP_NO_CONTENT for r in records)


def test_hataayi_hui_query_ka_record_naap_ke_saath_likha_jaata_hai():
    records = []
    qh.filter_queries(["paper banao"], records)
    assert len(records) == 1
    assert records[0]["measured"]["junk_mile"] == "banao"
    assert records[0]["line"] == (
        'Ye search query nahi bheji (query_me_koi_topic_shabd_nahi): '
        '"paper banao" — chars=11, shabd=2, topic_shabd=0, junk_shabd=1, '
        'junk_mile=banao')


def test_duplicate_query_dobara_nahi_jaati_par_likhi_jaati_hai():
    records = []
    got = qh.filter_queries(
        ["room temperature superconductivity",
         "Room Temperature Superconductivity"], records)
    assert got == ["room temperature superconductivity"]
    assert [r["reason"] for r in records] == [qh.DROP_DUPLICATE]


def test_saari_query_junk_nikle_to_bhi_research_band_nahi_hoti():
    """Khaali query list = "ek bhi source nahi dekha" — wo chup-chaap maar dena hai."""
    records = []
    got = qh.filter_queries(["paper banao", "karun step"], records)
    assert got == ["paper banao"]          # pehli phir bhi jaati hai
    assert len(records) == 2               # ...par jhoothi safai nahi hoti


def test_khaali_ya_none_list_par_kuch_nahi_tootta():
    assert qh.filter_queries(None) == []
    assert qh.filter_queries([]) == []
    assert qh.filter_queries(["", "   "]) == []


# ── 7. drop_lines — audit me ginti, boilerplate nahi ────────────────────────
def test_drop_lines_ginti_ke_saath_shuru_hoti_hai():
    records = []
    qh.filter_queries(["paper banao", "karun step", "ok"], records)
    lines = qh.drop_lines(records, limit=4)
    assert lines[0] == ("3 search query nahi bheji gayi (junk/meta shabd ya "
                        "duplicate) — neeche naap ke saath.")
    assert any("paper banao" in line for line in lines)
    assert any("junk_mile=karun, step" in line for line in lines)
    assert any("query_bahut_chhoti" in line for line in lines)


def test_kuch_nahi_hataaya_to_audit_me_koi_line_nahi():
    assert qh.drop_lines([]) == []
    assert qh.drop_lines(None) == []


def test_drop_lines_limit_se_zyada_line_nahi_deti():
    records = [{"query": f"q{i} banao", "reason": qh.DROP_NO_CONTENT,
                "measured": {"chars": 9}, "line": f"line {i}"}
               for i in range(9)]
    lines = qh.drop_lines(records, limit=3)
    assert lines[0].startswith("9 search query nahi bheji gayi")
    assert len(lines) == 4          # 1 ginti + 3 detail


# ── 8. safai ke function — query khaali kabhi nahi karte ────────────────────
def test_strip_junk_junk_hataata_hai_par_topic_chhodta_hai():
    assert qh.strip_junk(
        "kaam ache room temperature superconductivity dhyaan") == \
        "room temperature superconductivity"


def test_strip_junk_topic_bachne_layak_na_ho_to_text_chhedta_hi_nahi():
    """"kaunsa business karu" par sab kaatna = khaali query = 0 result."""
    assert qh.strip_junk("kaunsa karu") == "kaunsa karu"
    assert qh.strip_junk("") == ""


def test_tidy_query_function_shabd_bhi_hataata_hai():
    """clean_query ke chhote raaste par "jo / ho / bhi" query me bach jaate the."""
    got = qh.tidy_query(
        "hindi me gaana banao jo feeling aur human psychology ho")
    assert got == "hindi gaana feeling human psychology"


def test_tidy_query_keep_min_se_kam_bache_to_poori_safai_chhod_deti_hai():
    assert qh.tidy_query("kaunsa business karu") == "kaunsa business karu"


def test_is_junk_query_wahi_faisla_deta_hai_jo_verdict():
    for query in ("kaam ache dhyaan", "paper banao", "ok", ""):
        assert qh.is_junk_query(query) is True, query
    for query in ("room temperature superconductivity", "kaunsa business karu"):
        assert qh.is_junk_query(query) is False, query


# ── 9. orchestrator wiring — gate poore round par lagta hai ─────────────────
def _orchestrator_src() -> str:
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "research_engine", "orchestrator.py")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_gate_axis_query_jud_jaane_ke_BAAD_lagta_hai():
    """Axis query bhi isi base se banti hai, isliye gate unke baad chalna chahiye."""
    src = _orchestrator_src()
    axis_add = src.index("axis_queries.setdefault(")
    gate = src.index("query_hygiene.filter_queries(queries, query_drops)")
    send = src.index('self._track(job_id, "DISCOVERING"')
    assert axis_add < gate < send


def test_roki_hui_query_discovery_se_bahar_aati_hai():
    src = _orchestrator_src()
    assert '"query_drops": query_drops,' in src
    assert 'discovered.get("query_drops")' in src


def test_roki_hui_query_user_ke_warning_me_likhi_jaati_hai():
    """Chup-chaap drop nahi — audit me naap ke saath line jaati hai."""
    src = _orchestrator_src()
    block = src[src.index('discovered.get("query_drops")'):]
    assert "query_hygiene.drop_lines(query_drops)" in block[:400]
    assert "warnings.append(line)" in block[:400]


def test_planner_base_query_par_bhi_gate_lagata_hai():
    """Poori line pin ki hai — `if False and ...` likh kar gate band karna bhi
    pakda jaana chahiye, sirf naam dhoondhna kaafi nahi."""
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "research_engine", "planner.py")
    with open(path, encoding="utf-8") as handle:
        src = handle.read().replace("\r\n", "\n")
    assert "\n        cleaned = query_hygiene.tidy_query(cleaned)\n" in src
    assert "\n        if query_hygiene.is_junk_query(cleaned):\n" in src
    assert ("\n            if len(topic) >= 3 and not "
            "query_hygiene.is_junk_query(topic):\n" in src)


def test_topic_wale_sawaal_ki_base_query_kabhi_junk_only_nahi_hoti():
    """Hukum + topic mile hue sawaal — base query me topic bachna chahiye."""
    planner = ResearchPlanner()
    questions = [
        "ache se dhyaan se kaam kro or superconductivity samjhao",
        "jldi kro abb suru kro or dark matter detection par btao",
        "pura kaam karke btado ki insulin resistance kaise hoti hai",
        "kaunsa business karu ok jldi btao",
    ]
    for question in questions:
        query = planner.clean_query(question)
        assert not qh.is_junk_query(query), (question, query)


def test_sirf_hukum_wale_sawaal_par_bhi_query_khaali_nahi_hoti():
    """Topic hi nahi hai to gate jhootha topic nahi banata — par query khaali
    bhi nahi chhodta, warna search 0 result deta hai."""
    query = ResearchPlanner().clean_query("ache se kaam kro jldi")
    assert query.strip() != ""
    assert qh.is_junk_query(query) is True


# ── 10. intel ke baaki asli sawaal — har ek me topic bachta hai ─────────────
def test_har_asli_sawaal_ki_query_me_topic_bachta_hai():
    planner = ResearchPlanner()
    cases = {
        "ache se dhyaan se kaam kro or trading model banao jo nifty par chale":
            ("trading", "nifty"),
        "jldi se RPF SI ka exam paper banao pura syllabus ke saath":
            ("rpf", "exam"),
        "math basic se strong kaise karun step by step batao":
            ("math",),
        "hindi me gaana banao jo feeling aur human psychology samjhe":
            ("gaana", "psychology"),
    }
    for question, must in cases.items():
        query = planner.clean_query(question).casefold()
        assert not qh.is_junk_query(query), question
        for word in must:
            assert word in query, (question, query)


# ── 11. ₹0 aur ek jaisa faisla ────────────────────────────────────────────────
def test_faisla_har_baar_ek_jaisa_hai():
    planner = ResearchPlanner()
    first = planner.clean_query(MEGA)
    for _ in range(3):
        assert planner.clean_query(MEGA) == first
    assert qh.query_verdict(first) == qh.query_verdict(first)


def test_ye_safai_bina_gemini_bina_network_hoti_hai():
    """Shabd dekhkar faisla — koi provider call nahi, isliye ₹0."""
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "research_engine", "query_hygiene.py")
    with open(path, encoding="utf-8") as handle:
        src = handle.read().casefold()
    for banned in ("import requests", "import httpx", "import openai",
                   "google.generativeai", "genai.", "generate_content",
                   "urllib.request", "http://", "https://"):
        assert banned not in src, banned
