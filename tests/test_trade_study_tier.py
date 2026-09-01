"""#150d — TRADE-STUDY TIER: query banna, aur uske baare me SACH bolna.

#150b ne trading model ka 34-point contract banaya (kya naapa jaayega), #150c ne
lane isolation di (gaane ki cheez trading answer me na aaye). Par dono ke baad
bhi ek badi cheez baaki thi: trading ki farmaish par app KUCH ALAG PADHTA HI
NAHI tha. Domain profile `economics` nikalta tha aur uski curated intents
("minimum wage employment effect labour market gdp") scalping ke liye bekaar
hain. Ye lane wo gap bharti hai — exchange/regulator ka document, microstructure
ka paper, aur jis concept ka naam liya gaya uska ASLI empirical test.

Is lane ke apne khatre hain, aur poori file unke peeche padi hai:

  1. NAAM vs KAAM — "institutional-first lane chali" likh dena aasan hai. Ek
     baar aisa hua bhi tha: instrument ka naam na aane par 0 query banti thi aur
     reason phir bhi "lane chali (0 query)" kehta tha. Reason ab GINTI se banta
     hai, daawe se nahi.
  2. BUDGET CHORI — trade lane gaane ke teen lane (craft/listener/music) ya
     asli sawaal ka slot kha le, to naapi hui coverage chup-chaap gir jaati hai.
  3. LANE MIXING — intel ki saaf shart: "sab mix mt kr dena model mangu to
     gaane waali cheeje work krti dikhe to answer khraab ho jaaye". SONG/PLAN/
     SCIENCE par is lane ka ek bhi asar nahi hona chahiye.
  4. NAAM SE SACH — ICT/SMC/Wyckoff ki query banti hai iska matlab wo concept
     sach maan liya gaya NAHI hai; query hi "empirical test" dhoondh rahi hai.
  5. QUERY ≠ EVIDENCE — is stage me network chalta hi nahi. `trade_evidence_read`
     yahan kabhi True nahi hota, na koi live trade, na broker, na order book.
  6. USER KI MAANGI HUI SAKHTI — walk-forward/monte-carlo user ne KHUD maanga
     tha; wo budget ki chhat se bahar girna nahi chahiye.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import craft  # noqa: E402
from research_engine import market_data as md  # noqa: E402
from research_engine import songcraft as sc  # noqa: E402
from research_engine import trademodel as tm  # noqa: E402
from research_engine.depth import get_depth_config  # noqa: E402
from research_engine.planner import ResearchPlanner  # noqa: E402
from research_engine.source_discovery import SourceDiscovery  # noqa: E402

TRADE_Q = ("US100 aur XAUUSD ka intraday scalping trading model banao, 15M "
           "context 5M confirmation 1M entry, walk forward aur monte carlo bhi "
           "karo, order block aur fair value gap ko test karo")
THIN_Q = "ek scalping setup banao 5M chart par"
MODEL_ONLY_Q = "us100 ka scalping model banao"
OB_Q = "order block ka rule banao"
STUDY_Q = "US100 ke order flow par research kya kehti hai"
SONG_Q = "hindi me ek sad gaana likh do judaai wala"
PLAN_Q = "mujhe ek plan banao padhai ka"
JEWEL_Q = "gold jewellery ka design banao"
SCIENCE_Q = "room temperature superconductivity ka evidence kya hai"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name):
    with open(os.path.join(ROOT, "research_engine", name), "r",
              encoding="utf-8") as handle:
        return handle.read()


def _lane(question, mode="DEEP"):
    planner = ResearchPlanner()
    cls = planner.classify(question)
    return planner.connector_plan(cls, get_depth_config(mode), question)


# ── 1. FARMAISH pehchanna — ticker aur concept ke naam se bhi ────────────────

def test_a_ticker_name_alone_can_make_it_a_trading_ask():
    """`_TRADE_RE` me "us100" nahi tha — pehle ye farmaish chhoot jaati thi."""
    assert tm.instrument_cues("US100 ka model banao") == ["us100"]
    assert tm.is_request("US100 ka model banao") is True
    assert tm.is_request("nas100 ka setup bana do") is True
    assert tm.is_request("XAUUSD ka intraday plan bana do") is True


def test_a_concept_name_alone_can_make_it_a_trading_ask():
    """"order block ka rule banao" — trading ka ek bhi aam shabd nahi hai."""
    assert tm.concept_cues(OB_Q) == ["order block"]
    assert tm.is_request(OB_Q) is True
    assert tm.is_request("fair value gap ka rule bana do") is True
    assert tm.is_request("wyckoff accumulation phase ka model banao") is True


def test_the_build_word_is_still_needed_and_a_research_ask_stays_research():
    """Do signal ka taala pehle jaisa hai — naam aana kaafi nahi.

    Ye fixture #150c se aaya hai aur wahi rehna chahiye: "research kya kehti
    hai" me instrument ka naam hai par kuch BANANE ki maang nahi.
    """
    assert tm.instrument_cues(STUDY_Q) == ["us100"]
    assert tm.is_request(STUDY_Q) is False
    assert tm.is_request("us100 aaj kaisa chal raha hai") is False
    assert tm.is_request("order block kya hota hai") is False


def test_the_words_kept_out_of_the_cue_tables_are_kept_out_on_purpose():
    """Ye list badhi to "gold jewellery ka design banao" trading ban jaayega.

    Har shabd yahan is wajah se BAHAR hai ki aam bhasha me uska doosra matlab
    hai — "gold/sona" (dhaatu), "es/nq/gc" (do-teen akshar), "spring" (mausam),
    "imbalance" (aam shabd), "walk forward" (aage badhna).
    """
    tables = tm._TICKER_CUES + tm._CONCEPT_CUES
    for word in ("gold", "sona", "es", "nq", "gc", "ndx", "spring", "upthrust",
                 "imbalance", "walk forward", "price", "chart", "market"):
        assert word not in tables
    assert tm.is_request(JEWEL_Q) is False
    assert tm.is_request("sone ka bhav badhega ya nahi") is False
    assert tm.is_request("spring season ka poster banao") is False


def test_song_plan_and_science_asks_never_look_like_a_trading_ask():
    """Lane isolation ka pehla darwaza yahi hai."""
    for question in (SONG_Q, PLAN_Q, SCIENCE_Q, JEWEL_Q):
        assert tm.is_request(question) is False
        assert tm.instrument_cues(question) == []
        assert tm.concept_cues(question) == []
        assert tm.ask_of(question).asked is False


def test_both_public_gates_read_one_signal_not_two_lists():
    """`is_request` aur `request_reason` alag ho jaayein to naap jhooth bolega."""
    assert "_trade_signal(text)" in _src("trademodel.py")
    for question in (TRADE_Q, THIN_Q, OB_Q):
        assert tm.is_request(question) is True
        assert tm.request_reason(question) == tm.ask_of(question).reason
        assert tm.request_reason(question) != tm.NOT_ASKED_REASON
    for question in (SONG_Q, SCIENCE_Q, STUDY_Q):
        assert tm.is_request(question) is False
        assert "lane nahi kholi" in tm.request_reason(question)


def test_the_cue_match_survives_case_and_extra_spacing():
    """User "NAS 100" likhe ya "nas100" — jawab ek hi hona chahiye."""
    assert tm.is_request("NAS 100 ka model BANA do") is True
    assert tm.is_request("XAU/USD ka scalping model banao") is True
    assert tm.instrument_cues("mujhe US 100 chahiye") == ["us 100"]


# ── 2. LANE QUERY — kram, chhat, aur "kuch bana hi nahi" ka sach ─────────────

def test_no_ask_means_no_query_at_all():
    """Bina farmaish ek bhi query banna khud budget ki chori hai."""
    assert tm.lane_queries(None) == []
    assert tm.lane_queries(tm.ask_of(SONG_Q)) == []
    assert tm.lead_queries(tm.ask_of(SCIENCE_Q)) == []
    assert tm._study_groups(tm.ask_of(PLAN_Q)) == []


def test_the_first_query_is_the_exchange_s_own_document():
    """Institutional-first ka matlab sirf kram hai — aur wo kram naapa gaya."""
    rows = tm.lane_queries(tm.ask_of(TRADE_Q))
    assert rows[0]["lane"] == tm.LANE_WEB
    venue = [term for item in tm.INSTRUMENTS for term in item.venue_terms]
    assert rows[0]["query"] in venue
    assert rows[0]["why"] == tm._WHY_VENUE


def test_two_instruments_share_the_venue_slots_instead_of_one_eating_them():
    """US100 aur XAUUSD dono maange gaye the — dono ka document chahiye.

    Flat kram me pehle instrument ke saare venue term nikal jaate the aur doosre
    ka ek bhi slot chhat ke andar nahi aata tha.
    """
    ask = tm.ask_of(TRADE_Q)
    web = [row["query"] for row in tm.lane_queries(ask)
           if row["lane"] == tm.LANE_WEB]
    assert len(web) >= 2
    first = [item for item in tm.INSTRUMENTS
             if item.instrument_id == "us100"][0]
    second = [item for item in tm.INSTRUMENTS
              if item.instrument_id == "xauusd"][0]
    assert web[0] in first.venue_terms
    assert web[1] in second.venue_terms


def test_an_ask_without_any_instrument_still_reads_theory_and_the_concept():
    """Pehle yahan lane KHAALI lautti thi — farmaish maani, padha kuch nahi."""
    rows = tm.lane_queries(tm.ask_of(OB_Q))
    assert len(rows) == tm.MAX_STUDY_QUERIES
    lanes = {row["lane"] for row in rows}
    assert tm.LANE_WEB not in lanes
    assert lanes == {tm.LANE_BOOKS, tm.LANE_PAPERS}
    thin = tm.lane_queries(tm.ask_of(THIN_Q))
    assert len(thin) >= 5
    assert {row["lane"] for row in thin} == {tm.LANE_PAPERS}


def test_the_concept_query_carries_the_word_the_user_actually_wrote():
    """Group ka chhota naam ("ict") search me maanga hua concept kha jaata tha."""
    rows = tm.lane_queries(tm.ask_of(OB_Q))
    books = [row["query"] for row in rows if row["lane"] == tm.LANE_BOOKS]
    assert books == ["order block " + tm.CONCEPT_QUERY_SUFFIX]
    wyck = tm.lane_queries(tm.ask_of("wyckoff spring ka model banao"))
    assert ["wyckoff " + tm.CONCEPT_QUERY_SUFFIX] == [
        row["query"] for row in wyck if row["lane"] == tm.LANE_BOOKS]


def test_the_concept_query_hunts_a_test_and_never_states_the_concept_is_true():
    """Naam se koi concept sach nahi hota — query hi ye baat kehti hai."""
    assert tm.CONCEPT_QUERY_SUFFIX == ("empirical test statistical evidence out "
                                       "of sample")
    for row in tm.lane_queries(tm.ask_of(OB_Q)):
        if row["lane"] == tm.LANE_BOOKS:
            assert row["query"].endswith(tm.CONCEPT_QUERY_SUFFIX)
            assert row["why"] == tm._WHY_CONCEPT
    assert tm.CONCEPTS_EARN_THEIR_PLACE is True


def test_the_rigour_the_user_demanded_himself_survives_the_ceiling():
    """walk-forward/monte-carlo user ne KHUD maanga tha.

    Flat kram me theory ki 9 query pehle nikal jaati thi aur ye do chhat ke
    bahar gir jaati thin — yaani maangi hui cheez ka source hi nahi padha jaata.
    """
    queries = [row["query"] for row in tm.lane_queries(tm.ask_of(TRADE_Q))]
    assert tm._DEMAND_QUERY["walk_forward"] in queries
    assert tm._DEMAND_QUERY["monte_carlo"] in queries
    # aur wo theory ki doosri query se PEHLE aata hai — yahi round-robin ka faayda
    assert (queries.index(tm._DEMAND_QUERY["walk_forward"])
            < queries.index(tm.THEORY_QUERIES[1]))
    assert tm.THEORY_QUERIES[3] not in queries


def test_every_row_says_which_lane_and_why_in_plain_words():
    """Bina "why" ke lane ek aur bina wajah ka kharcha ban jaata hai."""
    whys = {tm._WHY_VENUE, tm._WHY_LIQUIDITY, tm._WHY_THEORY, tm._WHY_CONCEPT,
            tm._WHY_DEMAND}
    for question in (TRADE_Q, THIN_Q, OB_Q):
        for row in tm.lane_queries(tm.ask_of(question)):
            assert set(row) == {"query", "lane", "why"}
            assert row["lane"] in tm.STUDY_LANES
            assert row["why"] in whys
            assert row["query"] == " ".join(row["query"].split())
            assert len(row["query"]) > 8


def test_the_same_query_never_ships_twice():
    """Do baar wahi query = do baar wahi kharcha aur do baar wahi ginti."""
    rows = tm._dedup([{"query": "abc def ghi", "lane": "web", "why": "w"},
                      {"query": "  ABC   DEF ghi ", "lane": "papers",
                       "why": "x"},
                      {"query": "", "lane": "web", "why": "y"},
                      {"query": "jkl mno pqr", "lane": "books", "why": "z"}],
                     99)
    assert [row["query"] for row in rows] == ["abc def ghi", "jkl mno pqr"]
    for question in (TRADE_Q, OB_Q, THIN_Q):
        queries = [row["query"] for row in tm.lane_queries(tm.ask_of(question))]
        assert len(queries) == len(set(q.lower() for q in queries))


def test_the_ceiling_is_small_and_a_bad_limit_can_not_open_it():
    """Chhat na ho to ek farmaish 24 network call kha jaaye."""
    assert tm.MAX_STUDY_QUERIES == 10
    assert tm.MAX_STUDY_QUERIES < tm.MAX_QUERIES
    ask = tm.ask_of(TRADE_Q)
    assert len(tm.lane_queries(ask)) == 10
    assert len(tm.lane_queries(ask, limit=3)) == 3
    assert tm.lane_queries(ask, limit=0) == []
    assert tm.lane_queries(ask, limit=-5) == []
    assert len(tm.lane_queries(ask, limit=99)) <= tm.MAX_QUERIES


def test_the_round_one_lead_queries_stay_purely_institutional():
    """Round 1 ke teen slot me exchange/regulator ka document chahiye.

    Yahan round-robin JAAN-BOOJH KAR nahi hai: round 1 sabse kam mila-jula
    source se shuru hona chahiye. Isliye ye do function alag hain.
    """
    lead = tm.lead_queries(tm.ask_of(TRADE_Q), limit=3)
    venue = [term for item in tm.INSTRUMENTS for term in item.venue_terms]
    assert len(lead) == 3
    assert all(query in venue for query in lead)
    assert tm.lead_queries(tm.ask_of(TRADE_Q), limit=1) == lead[:1]


def test_the_lead_falls_back_to_the_concept_test_when_no_instrument_is_named():
    """Instrument ka naam na ho to round 1 khaali nahi jaana chahiye."""
    lead = tm.lead_queries(tm.ask_of(OB_Q), limit=3)
    assert lead[0] == "order block " + tm.CONCEPT_QUERY_SUFFIX
    assert lead[1] in tm.THEORY_QUERIES
    assert tm.lead_queries(tm.ask_of(THIN_Q), limit=3)[0] == tm.THEORY_QUERIES[0]


# ── 3. ROUND 1 — bekaar macro-econ intent ki JAGAH, base query ke BAAD ───────

def test_the_cleaned_question_still_leads_round_one():
    """Base query girti to poora sawaal hi search se nikal jaata."""
    planner = ResearchPlanner()
    cls = planner.classify(TRADE_Q)
    queries = planner.search_queries(TRADE_Q, cls, round_no=1)
    assert queries[0] == planner.clean_query(TRADE_Q)
    assert len(queries) <= 4


def test_the_macro_economics_intents_are_replaced_not_joined():
    """Jodne se paper connector ka fan-out badhta hai — jagah lena hi theek tha.

    `discover()` queries ko slice nahi karta, isliye ek extra base query seedha
    network tasks badha deti hai.
    """
    planner = ResearchPlanner()
    cls = planner.classify(TRADE_Q)
    queries = planner.search_queries(TRADE_Q, cls, round_no=1)
    venue = [term for item in tm.INSTRUMENTS for term in item.venue_terms]
    assert queries[1:] and all(query in venue for query in queries[1:])
    joined = " ".join(queries).lower()
    for leaked in ("minimum wage", "labour market", "gdp", "unemployment"):
        assert leaked not in joined


def test_a_thin_trading_ask_gets_theory_instead_of_lens_guesswork():
    """Instrument ka naam na ho to bhi round 1 kaam ki cheez maange."""
    planner = ResearchPlanner()
    for question in (THIN_Q, OB_Q):
        queries = planner.search_queries(question, planner.classify(question),
                                         round_no=1)
        assert queries[0] == planner.clean_query(question)
        assert len(queries) <= 4
        assert any(query in tm.THEORY_QUERIES or
                   query.endswith(tm.CONCEPT_QUERY_SUFFIX)
                   for query in queries[1:])


def test_round_one_of_every_other_kind_of_ask_is_untouched():
    """Ye lane sirf trading par khulti hai — baaki sab jaisa tha waisa hi."""
    planner = ResearchPlanner()
    for question in (SONG_Q, PLAN_Q, SCIENCE_Q, JEWEL_Q, STUDY_Q):
        queries = planner.search_queries(question, planner.classify(question),
                                         round_no=1)
        assert queries[0] == planner.clean_query(question)
        joined = " ".join(queries)
        assert tm.CONCEPT_QUERY_SUFFIX not in joined
        for theory in tm.THEORY_QUERIES:
            assert theory not in queries


def test_the_science_ask_keeps_its_own_curated_intents():
    """Ek naapa hua fixture: superconductivity ki query girni nahi chahiye."""
    planner = ResearchPlanner()
    queries = planner.search_queries(SCIENCE_Q, planner.classify(SCIENCE_Q),
                                     round_no=1)
    assert len(queries) == 4
    joined = " ".join(queries).lower()
    assert "superconduct" in joined
    assert "microstructure" not in joined


# ── 4. PLAN ka disclosure — ginti se banta hai, daawe se nahi ────────────────

def test_the_plan_carries_the_queries_and_a_separate_lane_dict():
    plan = _lane(TRADE_Q)
    lane = plan["trade_study_lane"]
    assert len(plan["trade_study"]) == tm.MAX_STUDY_QUERIES
    assert lane["wanted"] is True and lane["is_trade_request"] is True
    assert lane["query_count"] == len(plan["trade_study"])
    assert lane["lanes"] == [row["lane"] for row in plan["trade_study"]]
    assert lane["reasons"] == [row["why"] for row in plan["trade_study"]]
    assert lane["ask"]["instruments"] == ["us100", "xauusd"]


def test_the_reason_is_built_from_the_real_count_not_from_a_claim():
    """Yahi wo jhooth tha jo pakda gaya: "lane chali (0 query)".

    Ab reason me lane-wise ginti chhapti hai, aur wo ginti wahi list se aati hai
    jo discovery ko bheji ja rahi hai.
    """
    plan = _lane(TRADE_Q)
    lane = plan["trade_study_lane"]
    assert "trade-study lane chali (10 query;" in lane["reason"]
    assert "web:3" in lane["reason"] and "books:1" in lane["reason"]
    assert "papers:6" in lane["reason"]
    counted = sum(int(part.split(":")[1]) for part in
                  lane["reason"].split("(10 query; ")[1].split(")")[0].split(", "))
    assert counted == lane["query_count"]


def test_when_no_venue_document_was_asked_for_the_reason_says_so():
    """Har haalat me "exchange ka document pehle" likhna naam-vs-kaam ka farak."""
    for question in (THIN_Q, OB_Q):
        lane = _lane(question)["trade_study_lane"]
        assert lane["query_count"] > 0
        assert lane["institutional_first"] is False
        assert "koi jaana-pehchana instrument naam se nahi aaya" in lane["reason"]
        assert "exchange/regulator ka apna document sabse pehle" not in \
            lane["reason"]
        assert tm.LANE_WEB not in lane["lanes"]


def test_the_institutional_first_flag_is_measured_not_declared():
    """Hardcoded True us ask par jhooth hota jahan venue query hi nahi bani."""
    assert _lane(TRADE_Q)["trade_study_lane"]["institutional_first"] is True
    assert _lane(OB_Q)["trade_study_lane"]["institutional_first"] is False
    assert _lane(SONG_Q)["trade_study_lane"]["institutional_first"] is False
    src = _src("planner.py")
    assert '"institutional_first": bool(' in src


def test_a_non_trading_ask_gets_an_empty_lane_and_says_why():
    for question in (SONG_Q, PLAN_Q, SCIENCE_Q, JEWEL_Q, STUDY_Q):
        plan = _lane(question)
        lane = plan["trade_study_lane"]
        assert plan["trade_study"] == []
        assert lane["wanted"] is False and lane["is_trade_request"] is False
        assert lane["query_count"] == 0 and lane["lanes"] == []
        assert lane["ask"] == {}
        assert "lane nahi kholi" in lane["reason"]
        assert "lane chali" not in lane["reason"]


def test_query_banna_padhna_nahi_hai_and_the_flags_say_it():
    """Is stage me network chalta hi nahi — chaar jhande naam se seema batate hain."""
    lane = _lane(TRADE_Q)["trade_study_lane"]
    assert lane["trade_evidence_read"] is False
    assert lane["live_tested"] is False and lane["broker_connected"] is False
    assert lane["order_book_read"] is False and lane["tick_data_read"] is False
    assert lane["financial_advice"] is False
    assert lane["backtest_is_not_future"] is True
    assert lane["concepts_earn_their_place"] is True
    assert lane["gemini_calls"] == 0 and lane["network_used"] is False
    assert lane["not_financial_advice"] == tm.NOT_ADVICE_NOTE


def test_depth_shrinks_the_lane_and_never_closes_it():
    """Purana niyam: "depth lane band nahi karti, chhoti karti hai"."""
    quick = _lane(TRADE_Q, "QUICK")
    deep = _lane(TRADE_Q, "DEEP")
    assert len(quick["trade_study"]) == 3
    assert len(deep["trade_study"]) == tm.MAX_STUDY_QUERIES
    assert quick["trade_study_lane"]["wanted"] is True
    assert quick["trade_study_lane"]["query_count"] == 3
    assert "3 query;" in quick["trade_study_lane"]["reason"]
    # chhoti hone par bhi pehla slot institutional hi rehta hai
    assert quick["trade_study"][0]["lane"] == tm.LANE_WEB


def test_the_trade_lane_never_borrows_the_song_lanes_budget():
    """Craft/listener/music ki naapi hui coverage se ek slot bhi nahi jaana."""
    song = _lane(SONG_Q)
    assert len(song["craft_study"]) > 0
    assert song["trade_study"] == []
    trade = _lane(TRADE_Q)
    assert trade["craft_study"] == []
    assert trade.get("listener_study", []) == []
    assert trade.get("music_study", []) == []
    assert tm.MAX_STUDY_QUERIES != sc.MAX_STUDY_QUERIES


def test_a_song_ask_and_a_trade_ask_never_switch_places():
    """intel ki shart: "sab mix mt kr dena"."""
    assert craft.detect(SONG_Q)["is_request"] is True
    assert craft.detect(TRADE_Q)["is_request"] is False
    assert tm.is_request(SONG_Q) is False
    joined = " ".join(row["query"] for row in _lane(TRADE_Q)["trade_study"])
    for word in ("lyric", "gaana", "song", "melody", "tempo", "raag"):
        assert word not in joined.lower()


# ── 5. MARKET SERIES lane — model ki farmaish bhi ek asli wajah hai ──────────

def test_a_ticker_name_now_counts_as_a_market_signal():
    """`_MARKET_RE` me "us100"/"xauusd" nahi tha — series lane band rehti thi."""
    assert md.market_intent("us100 ka historical data chahiye")["wanted"] is True
    assert md.market_intent("xauusd ka daily data 2020 se")["wanted"] is True
    assert md._TICKER_RE.search("nas100") is not None
    assert md._TICKER_RE.search("gold jewellery") is None


def test_the_model_ask_is_a_separate_key_and_never_merged():
    """"user ne series maangi" aur "model ke liye series chahiye" do baatein hain.

    Ek key me mila dena wahi jhooth hota jise #133/#134 me rokha gaya tha.
    Poora TRADE_Q me user khud "walk forward" jaisi cheez maangta hai, isliye
    us par series_ask bhi sach hai — do key ka farq dikhane ke liye ek aisi
    farmaish chahiye jisme instrument aur model ho, par waqt-ke-saath-number
    ki maang khud user ne na ki ho.
    """
    got = md.market_intent(TRADE_Q, domain_key="economics", trade_ask=True)
    assert got["model_ask"] is True
    assert got["wanted"] is True
    assert got["not_financial_advice"] == md.NOT_ADVICE_NOTE

    lean = md.market_intent(MODEL_ONLY_Q, domain_key="economics", trade_ask=True)
    assert lean["model_ask"] is True
    assert lean["series_ask"] is False
    assert lean["market_signal"] is True
    assert lean["wanted"] is True
    assert "trading model banane ki farmaish hai" in lean["reason"]
    assert lean["not_financial_advice"] == md.NOT_ADVICE_NOTE


def test_the_two_older_reasons_are_byte_identical_to_before():
    """Purani do wajah ka text badla to purane naap ka matlab badal jaata."""
    v1 = md.market_intent("us100 ka historical data 2015 se")
    assert v1["reason"] == ("market data lane chali — sawaal me market/economic "
                           "cheez ka naam bhi hai aur waqt ke saath number ki "
                           "maang bhi")
    v2 = md.market_intent("iska trend 2010 se dikhao", domain_key="economics")
    assert v2["reason"] == ("market data lane chali — field economics/finance "
                            "nikla aur sawaal waqt ke saath number maang raha hai")
    assert v1["model_ask"] is False and v2["model_ask"] is False


def test_the_model_ask_alone_can_not_open_the_lane_without_an_instrument():
    """Bina instrument koi series kaam ki nahi — API call bekaar jaati."""
    got = md.market_intent(THIN_Q, domain_key="", trade_ask=True)
    assert got["model_ask"] is True
    assert got["market_signal"] is False
    assert got["wanted"] is False
    assert _lane(THIN_Q)["markets"] == []
    assert _lane(OB_Q)["markets"] == []


def test_the_trade_ask_flag_comes_from_the_planner_not_a_second_list():
    """Do jagah do list banti to ek din dono alag jawab dene lagti.

    `market_data.py` me `trademodel` ka naam comment me likha hai (ye batane ke
    liye ki list wahan hai) — par IMPORT nahi hona chahiye, warna do module ek
    doosre ko import karke cycle bana dete aur list bhi do jagah pal jaati.
    """
    md_src = _src("market_data.py")
    assert "from .trademodel" not in md_src
    assert "from . import trademodel" not in md_src
    assert "import trademodel" not in md_src
    assert "trademodel." not in md_src.replace("`trademodel.", "")
    assert "trade_ask: bool = False" in md_src
    assert "trade_ask = bool(trademodel.is_request(trade_text))" in _src(
        "planner.py")
    assert _lane(TRADE_Q)["market_intent"]["model_ask"] is True
    assert _lane(TRADE_Q)["markets"] != []
    # Aur planner ke disclosure me bhi do key ALAG rehni chahiye: is ask me user
    # ne series maangi hi nahi, sirf model maanga hai.
    lean = _lane(MODEL_ONLY_Q)["market_intent"]
    assert lean["model_ask"] is True
    assert lean["series_ask"] is False


# ── 6. DISCOVERY TIER — alag label, alag budget, kisi ka slot nahi ───────────

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
    plan = {"web": True, "papers": ["semantic_scholar"], "books": ["open_library"],
            "datasets": [], "patents": [], "markets": [],
            "trade_study": entries}
    plan.update(plan_extra or {})
    tasks = discovery._tasks(["primary question"], plan, per_connector, max_web)
    return [label for label, _fn in tasks], tasks, spy


def test_each_lane_gets_its_own_label_that_names_the_tier():
    """Label me tier ka naam na ho to log me ye kharcha kisi ke khaate me chala jaata."""
    labels, _tasks, _spy = _tasks_for([
        {"query": "Nasdaq-100 index methodology", "lane": "web"},
        {"query": "market microstructure limit order book", "lane": "papers"},
        {"query": "order block empirical test", "lane": "books"},
    ])
    assert "trade_study_web" in labels
    assert "trade_study_papers" in labels
    assert "trade_study_books" in labels
    assert labels.index("trade_study_web") < labels.index("trade_study_papers")
    assert not any(label.startswith("craft_study") for label in labels)


def test_each_lane_actually_reaches_its_own_kind_of_source():
    """Label sahi ho par query galat connector par jaaye — ye chhupa jhooth hai.

    Concept (ICT/SMC/Wyckoff) ka likha hua KITAAB/course me milta hai, aur
    microstructure ka kaam PAPER me. Dono spy alag hain, isliye routing ulta
    hone par (books↔papers) ye test RED hota hai — label wahi rehta hai.
    """
    discovery = SourceDiscovery()
    papers_spy, books_spy, web_spy = _Spy(), _Spy(), _Spy()
    papers_spy.name, books_spy.name, web_spy.name = "papers", "books", "web"
    discovery.papers.by_name = lambda name: papers_spy
    discovery.books.by_name = lambda name: books_spy
    discovery.web = web_spy
    plan = {"web": True, "papers": ["semantic_scholar"], "books": ["open_library"],
            "datasets": [], "patents": [], "markets": [],
            "trade_study": [
                {"query": "Nasdaq-100 index methodology", "lane": "web"},
                {"query": "market microstructure limit order book", "lane": "papers"},
                {"query": "order block empirical test", "lane": "books"}]}
    for label, fn in discovery._tasks(["primary question"], plan, 3, 5):
        if label.startswith("trade_study"):
            fn()
    assert "order block empirical test" in books_spy.seen
    assert "order block empirical test" not in papers_spy.seen
    assert "market microstructure limit order book" in papers_spy.seen
    assert "market microstructure limit order book" not in books_spy.seen
    assert "Nasdaq-100 index methodology" not in books_spy.seen
    assert "Nasdaq-100 index methodology" not in papers_spy.seen


def test_no_trade_study_key_means_no_extra_task_at_all():
    """Har sawaal par ye tier chalna hi is lane ki sabse badi galti hoti."""
    labels, _tasks, _spy = _tasks_for([])
    assert not any(label.startswith("trade_study") for label in labels)
    discovery = SourceDiscovery()
    plan = {"web": True, "papers": [], "books": [], "datasets": [],
            "patents": [], "markets": []}
    labels2 = [label for label, _fn in discovery._tasks(["q"], plan, 3, 5)]
    assert not any(label.startswith("trade_study") for label in labels2)


def test_the_budget_of_this_tier_is_small_and_its_own():
    """Ek query se 5 record maangna asli sawaal ka budget kha jaata hai."""
    labels, tasks, spy = _tasks_for([
        {"query": "market microstructure limit order book", "lane": "papers"}],
        per_connector=9, max_web=9)
    for label, fn in tasks:
        if label.startswith("trade_study"):
            fn()
    assert spy.limits and max(spy.limits) <= 2


def test_the_same_query_is_never_fanned_out_twice():
    labels, _tasks, _spy = _tasks_for([
        {"query": "Nasdaq-100 index methodology", "lane": "web"},
        {"query": "  nasdaq-100 INDEX methodology ", "lane": "papers"},
        {"query": "", "lane": "papers"},
    ])
    assert len([l for l in labels if l.startswith("trade_study")]) == 1


def test_the_tier_can_never_ship_more_than_the_ceiling():
    entries = [{"query": f"query number {n} of the trade study lane",
                "lane": "papers"} for n in range(40)]
    labels, _tasks, _spy = _tasks_for(entries)
    trade = [label for label in labels if label.startswith("trade_study")]
    assert len(trade) == tm.MAX_STUDY_QUERIES


def test_a_plain_string_entry_is_treated_as_a_web_query():
    """Purane shape se aane wali list chup-chaap gir na jaaye."""
    labels, _tasks, _spy = _tasks_for(["Nasdaq-100 index methodology"])
    assert labels.count("trade_study_web") == 1


def test_with_the_web_lane_off_the_query_is_dropped_not_relabelled():
    """Lane band ho to naam badal kar chupke se chalana bhi jhooth hota."""
    labels, _tasks, _spy = _tasks_for(
        [{"query": "Nasdaq-100 index methodology", "lane": "web"}],
        plan_extra={"web": False})
    assert not any(label.startswith("trade_study") for label in labels)


def test_the_lyrics_guard_is_deliberately_absent_from_this_tier():
    """Gaane ka pehra trading ki query par lagana KHUD lane mixing hota.

    Ye faisla source me likha hua hai, taaki koi "consistency" ke naam par
    songcraft ka guard yahan na jod de. Isliye do baatein naapi jaati hain:
    naam comment me MAUJOOD hona chahiye (faisla likha hua hai), par kaam me
    (call ya set) nahi — naam ka zikr hona aur guard lagna do alag cheez hai.
    """
    src = _src("source_discovery.py")
    assert "trade_study_" in src
    block = src.split("# TRADING MODEL ka TRADE-STUDY")[1].split(
        "return tasks")[0]
    assert "is_lyrics_hunt" in block and "seen_craft" in block
    assert "is_lyrics_hunt(" not in block
    assert "seen_craft.add" not in block
    assert "in seen_craft" not in block
    assert "seen_listener" not in block.replace("seen_listener`", "")
    assert "sab mix mt kr dena" in src


# ── 7. WIRING ke pin, ₹0 aur ek jaisa jawab ──────────────────────────────────

def test_the_planner_wiring_is_pinned_where_it_matters():
    """Ye chaar line hat jaayein to lane chup-chaap band ho jaati hai."""
    src = _src("planner.py")
    assert "from . import trademodel" in src
    assert "trade_lead = list(trademodel.lead_queries(" in src
    # #171d me is line ke saath exam lane bhi juda (`trade_lead or exam_lead
    # or intents`). Needle CHHOTI ki gayi hai, kamzor nahi: `trade_lead` abhi
    # bhi PEHLA hona chahiye. Agar koi ise hataaye ya exam ko aage kar de to
    # ye assert usi tarah toot jaayega jaise pehle tootta tha — trading ka
    # kram exam lane ke aane se badalna hi nahi chahiye tha.
    assert "qs = [base] + (trade_lead or exam_lead" in src
    assert '"trade_study": trade_queries,' in src
    assert "if trade_queries:" in src


def test_the_discovery_wiring_is_pinned_where_it_matters():
    src = _src("source_discovery.py")
    assert "from . import trademodel" in src
    assert "trade_limit = max(1, min(2, max_per_connector))" in src
    assert 'tasks.append(("trade_study_" + lane,' in src
    assert "trademodel.MAX_STUDY_QUERIES" in src


def test_the_two_query_builders_are_pinned_and_stay_separate():
    src = _src("trademodel.py")
    assert "def lane_queries(" in src and "def lead_queries(" in src
    assert "return _dedup(rows, limit)" in src
    assert "pick = next((cue for cue in cues if cue.lower() in matched)" in src


def test_this_whole_lane_costs_zero_and_answers_the_same_way_twice():
    """0 Gemini call, 0 network, koi randomness nahi."""
    assert tm.GEMINI_CALLS == 0 and tm.NETWORK_USED is False
    assert tm.DETERMINISTIC is True and tm.PROVIDER_COST == "₹0"
    ask = tm.ask_of(TRADE_Q)
    assert tm.lane_queries(ask) == tm.lane_queries(tm.ask_of(TRADE_Q))
    assert tm.lead_queries(ask) == tm.lead_queries(tm.ask_of(TRADE_Q))
    first = _lane(TRADE_Q)["trade_study_lane"]
    second = _lane(TRADE_Q)["trade_study_lane"]
    assert first == second


def test_the_older_study_plan_still_works_and_is_not_replaced():
    """#150b ka kaam hataya nahi gaya — ye tier uske UPAR bani hai."""
    ask = tm.ask_of(TRADE_Q)
    plan = tm.study_plan(ask)
    assert plan["asked"] is True
    assert len(plan["queries"]) <= tm.MAX_QUERIES
    assert plan["institutional_queries"]
    lane = [row["query"] for row in tm.lane_queries(ask)]
    assert set(lane) <= set(plan["queries"])
    assert len(lane) < len(plan["queries"])


# ── 8. REASON ka har ankda ASLI ginti se aaye ────────────────────────────────

def _reason_counts(reason):
    """Reason me likhe `lane:n` jode nikaalo — jo app ne KHUD likhe hain."""
    out = {}
    for chunk in reason.replace(";", " ").replace("(", " ").replace(")",
                                                                   " ").split():
        if ":" in chunk:
            lane, _sep, num = chunk.strip(",").partition(":")
            if num.isdigit():
                out[lane] = int(num)
    return out


def test_the_lane_counts_written_in_the_reason_match_the_real_queries():
    """Ginti likh dena aasan hai — yahan wo ASLI list se milaayi jaati hai.

    Ye naap us mutation ke liye hai jahan `detail` ko hardcode kar diya jaaye
    ("web:3, papers:6, books:1"). Aisa hone par reason sach lagta hai par kaam
    kuch aur hota — wahi naam-vs-kaam ka farak jo is project me mana hai.
    """
    for question in (TRADE_Q, OB_Q, THIN_Q, MODEL_ONLY_Q):
        plan = _lane(question)
        rows = plan["trade_study"]
        real = {}
        for row in rows:
            lane = str(row.get("lane") or "")
            real[lane] = real.get(lane, 0) + 1
        reason = plan["trade_study_lane"]["reason"]
        written = _reason_counts(reason)
        assert written == real, (question, written, real)
        assert sum(written.values()) == len(rows)
        assert f"{len(rows)} query" in reason


def test_the_reason_never_says_the_lane_ran_when_it_produced_nothing():
    """0 query par "lane chali" likhna wahi purana jhooth hai.

    Aaj ye haalat aam sawaal se aati nahi (farmaish mani to theory ki query
    hamesha banti hai), isliye branch ko SEEDHA chalaya jaata hai: query banane
    wala hissa khaali list de, aur dekho planner kya likhta hai. Guard hata dene
    par ye test RED hota hai.
    """
    planner = ResearchPlanner()
    real = tm.lane_queries
    try:
        tm.lane_queries = lambda ask=None, limit=tm.MAX_STUDY_QUERIES: []
        plan = planner.connector_plan(planner.classify(TRADE_Q),
                                      get_depth_config("DEEP"), TRADE_Q)
    finally:
        tm.lane_queries = real
    lane = plan["trade_study_lane"]
    assert plan["trade_study"] == []
    assert lane["wanted"] is False and lane["query_count"] == 0
    assert lane["is_trade_request"] is True
    assert lane["institutional_first"] is False
    assert "ek bhi query nahi bani" in lane["reason"]
    assert "lane chali" not in lane["reason"]
    assert "trade-study lane" in lane["reason"]
    # Aur ye baat aage bhi imaandaar rehni chahiye: koi source padha nahi gaya.
    assert lane["trade_evidence_read"] is False
