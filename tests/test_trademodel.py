"""#150b — TRADE MODEL: farmaish ka naap, 34-point contract, aur imaandaar FAIL.

intel ne 30 section ka "US100 + XAUUSD Deep-Research Scalping Model Challenge"
diya tha, aur saath me ek saaf shart: "sab mix mt kr dena — model mangu to
gaane waali cheeje work krti dikhe to answer khraab ho jaaye". Isliye is file
me teen alag sach pin hote hain:

  1. DARWAZA — trading ki lane do signal se khulti hai (trading ki cheez ka naam
     + kuch BANANE ki maang), ek se nahi. Gaane ki farmaish par lane khulti hi
     nahi, aur `not_asked()` ka record `wanted: False` se pehchana jaata hai.
     `study()` ke record me `wanted` key JAAN-BOOJH KAR nahi hai — "darwaza band
     tha" aur "lane chali par kuch nahi mila" kabhi ek jaise na dikhein.
  2. NAAP — har contract point ka default MET nahi, NOT_MEASURED hai. Khaali
     spec par 0 MET aata hai, "sab theek" nahi. Aur teen jagah FAIL structurally
     zaroori hai: 90%+ win rate ka daawa, bina-number wale discretionary shabd,
     aur order-flow ka edge (jiska data is app me padha hi nahi jaata).
  3. LAB SE NATEEJA — walk-forward / monte carlo / robustness / baseline ka
     status spec ke likhe daawe se nahi, LAB ke asli test rows se aata hai.
     Spec me daawa + LAB me 0 test = NOT_MET, MET nahi.

Ek aur baat jo yahan naapi jaati hai: `trademodel` ka status vocabulary
`craft` ke barabar hona chahiye par import se nahi — do module ek doosre ko
bandhak na banayein. Isliye test literal se pin karta hai.

0 Gemini call, 0 network, koi randomness nahi.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import craft  # noqa: E402
from research_engine import market_data  # noqa: E402
from research_engine import trademodel as tm  # noqa: E402

TRADE_ASK = ("US100 aur XAUUSD ke liye deep-research scalping model banao. "
             "Final execution 15M context -> 5M confirmation -> 1M entry. "
             "Kam se kam 7 alag competing hypotheses test karo, walk forward, "
             "monte carlo, parameter robustness, baseline se muqabla, red team, "
             "microstructure. ICT SMC Wyckoff sab check karo. Dono instrument "
             "alag alag padho.")
SONG_ASK = "mujhe sad hindi gaana likh do, punjabi dancing style me"


class Src:
    """Source ka sirf wahi hissa jo trademodel padhta hai."""

    def __init__(self, sid, url, source_type, read_level):
        self.source_id = sid
        self.url = url
        self.source_type = source_type
        self.read_level = read_level


# Ek "poora" spec — iska kaam sirf ek hai: sabit karna ki koi bhi contract point
# MARA HUA check nahi hai (jise kabhi MET nahi kiya ja sakta). Ye spec asli
# research ka nateeja NAHI hai; ye naap ka fixture hai.
RICH_SPEC = """
## US100 (Nasdaq-100 CFD/futures) ka apna hissa
US100 15M context: trend filter EMA 50 slope > 0.02% per bar.
US100 5M confirmation: pullback depth 30-50% of prior 15M leg.
US100 1M entry trigger: break of 1M swing high by 2 points.
US100 sample size = 1840 trades, expectancy 0.11R.
## XAUUSD (COMEX gold) ka apna hissa
XAUUSD 15M context: ATR percentile >= 40.
XAUUSD 5M confirmation: VWAP reclaim within 3 bars.
XAUUSD 1M entry trigger: 1M close above 15M level + 0.8 ATR.
XAUUSD sample size = 1210 trades, expectancy 0.09R.

## Research data
Daily and 4H bias, 1H structure, 30M liquidity map, 5 years of data.
Tick data 0 padha gaya, order book 0 padha gaya (source nahi hai).
Futures: CME Micro E-mini open interest 3 series. Macro: CPI, NFP, FOMC 42 events.
Volatility: ATR and VIX 20-day percentile. Options: implied volatility 30 day.
Intermarket: DXY correlation -0.62.

## Theory
Market microstructure and price discovery: 4 papers padhe (full text).
Auction market theory value area: 2 papers. Liquidity and adverse selection: 3.
Behavioural finance intraday: 1 paper. Execution algorithm impact: 2 papers.

## Concepts
ICT fair value gap: define if bar[i-1].low > bar[i+1].high and gap >= 0.5 ATR.
ICT tested against baseline random entry: 1840 trades, sample size n = 1840.
SMC order block: define if 3-bar base with volume >= 150% of 20-bar mean.
SMC compared with baseline breakout: expectancy 0.04R vs 0.02R.
Wyckoff spring: define if low < prior swing low by >= 0.3 ATR and close back
above within 2 bars.
Wyckoff versus benchmark ORB: 0.06R vs 0.03R, sample size 640.
Market profile value area: define if TPO count >= 70% of session, POC +/- 1 ATR.
Market profile vs baseline random: 0.05R vs 0.02R, n = 720.
VWAP band: define if price >= VWAP + 2 sigma, reversion measured over 12 bars.
VWAP compared to benchmark hold: 0.03R vs 0.01R, sample size 980.
"""
RICH_SPEC += """
## Hypotheses
H1 liquidity sweep reversal: sweep of prior 15M extreme then 5M reclaim.
H2 opening range continuation: ORB with 30M range and volume expansion.
H3 VWAP mean reversion: 2 sigma band fade in low volatility regime.
H4 momentum ignition: 1M volume spike with 3-bar directional persistence.
H5 macro release fade: post-CPI 5-15M window mean reversion.
H6 intermarket confirmation: DXY divergence gating XAUUSD longs.
H7 regime switching meta model: volatility state selects sub-model.
H8 New hypothesis generated in this research: 15M failed-auction rotation.
H9 New hypothesis generated in this research: 1M spread-widening exhaustion.
H10 New hypothesis generated in this research: session-handoff imbalance decay.

## Regime
Regime detection: volatility state 3 buckets (ATR percentile < 30, 30-70, > 70).
Trending vs ranging classified by 15M ADX >= 22. Rule runs before every entry.

## Session
Session expectancy: London 0.13R (n = 620 trades), New York 0.08R (n = 810),
Asian -0.02R (n = 410). Sample size per session likha hai.

## Macro event windows
Pre-news 15M: avoid. Release 0-1M: avoid. 1-5M: wait. 5-15M: trade (0.14R).
15-60M: trade (0.07R). Har window ka faisla likha hai.

## Intermarket
DXY vs XAUUSD correlation -0.62 in high volatility regime, -0.18 in low
volatility regime — rishta regime dependent hai aur low-vol me tootta hai.
Redundant with ATR filter 0.71 of the time.

## Information theory
Mutual information between 15M imbalance and 1M return = 0.031 bits.
Conditional information given ATR state = 0.012 bits. Entropy reduction 2.4%.
Redundancy between order-imbalance proxy and momentum = 0.68.

## Game theory
Game theory: market maker incentive is inventory control, HFT incentive is
adverse-selection avoidance, CTA incentive is trend persistence, retail flow is
liquidity for dealer hedging. Payoff asymmetry measured at 0.6 of events.

## Leakage
Data leakage check: only information available at t used, point-in-time data,
no repainting indicator, no future candle. 4 checks run, all pass, no leakage.
"""
RICH_SPEC += """
## Costs
Spread 0.8 points modelled. Commission 0.35 per side. Slippage 0.4 points.
Latency 120 ms. News slippage 3.0 points in release window.
Net expectancy after all costs 0.06R.

## Failure classification
Loss class counts: regime mismatch 210, stop too tight 168, cost drag 95,
news shock 41, late entry 132. Har haar ki wajah class me daali gayi.

## Red team
Data mining: 14 variants tested, multiple testing adjusted.
Leakage: rechecked, no look ahead. Sample size 3050 trades total.
One year only? No — 5 years, multiple years tested. One session only? No, all
sessions. Costs included. One threshold? No, parameter sweep of 9 values.
Survivorship: contract roll handled. Fake causal story avoided, mechanism proof
only where measured. Structural change and edge decay monitored. Cherry picking
avoided, no best-window selection.

## Entry model
WHERE: at 15M level +/- 0.3 ATR. WHEN: London and New York sessions only.
WHY: measured 15M imbalance edge. DIRECTION: long if 15M slope > 0.
TRIGGER: 1M close beyond level by 2 points. INVALIDATION: 5M close back inside.
STOP LOSS: 1.2 ATR, MAE distribution 80th percentile 1.05 ATR.
TAKE PROFIT: 1R partial 50%, 2R runner, trailing after 1.5R, time exit 40 min,
target chosen by expectancy 0.11R not win rate. average R 1.4.
NO-TRADE: pre-news 15M, ATR percentile > 90, spread > 1.5 points.

## Final spec
Final spec per instrument. Trading hours 12:00-20:00 UTC. Position size 0.5%
risk per trade. News rule: avoid 15M pre-release. No-trade rule: 3 listed.
Expected expectancy 0.11R with confidence interval +/- 0.04R. Sample size 1840.

## Performance
Win rate 47%, average win/loss 1.6, expectancy 0.11R, profit factor 1.34,
Sharpe 1.1, Sortino 1.5, max drawdown 14%, tail loss 4.2R, risk of ruin 0.8%.

## Evidence labels
[EVIDENCE-A] session expectancy differences.
[EVIDENCE-B] regime dependence of intermarket correlation.
[EVIDENCE-C] macro window fade.
[EVIDENCE-D] 1M spread-widening exhaustion (research hypothesis).
[EVIDENCE-E] ICT fair value gap edge failed out of sample — no edge, rejected.

## Final decision
Final model diya gaya hai, aur missing: tick/order-book data missing, isliye
order flow ka daawa nahi kiya gaya. Long if and short if rules above.
"""

RICH_SOURCES = [
    Src("S1", "https://www.cmegroup.com/education/microstructure.pdf",
        "document", "full_text"),
    Src("S2", "https://www.nasdaqtrader.com/market-structure.pdf",
        "document", "claims"),
    Src("S3", "https://www.federalreserve.gov/econres/feds/x.pdf",
        "paper", "full_text"),
    Src("S4", "https://arxiv.org/abs/q-fin.0001", "paper", "full_text"),
    Src("S5", "https://blog.example.com/ict", "web", "snippet"),
]
# LAB ke asli test rows. Status vocabulary `lab.py` ka hai — yahan literal se
# likha gaya hai, import se nahi, taaki dono module ek doosre ko bandhak na banayein.
RICH_LAB = {"hypotheses": [{"tests": [
    {"recipe": "walk_forward", "status": "TESTED_PASS"},
    {"recipe": "monte_carlo", "status": "TESTED_PASS"},
    {"recipe": "parameter_robustness", "status": "TESTED_PASS"},
    {"recipe": "baseline_tournament", "status": "TESTED_PASS"},
]}]}


def _full_report():
    return tm.study(TRADE_ASK, RICH_SPEC, RICH_SOURCES, [], RICH_LAB)


def _status(report, point_id):
    for row in report.get("checks") or ():
        if row.get("point_id") == point_id:
            return row["status"]
    raise AssertionError("point report me hi nahi mila: " + point_id)


def _row(report, point_id):
    for row in report.get("checks") or ():
        if row.get("point_id") == point_id:
            return row
    raise AssertionError("point report me hi nahi mila: " + point_id)


def _measure(spec="", sources=(), hypotheses=(), lab=None, question=TRADE_ASK):
    """Sirf naap — gate khula maan kar, taaki ek point alag se naapa ja sake."""
    return tm.measure(tm.ask_of(question), spec, sources, hypotheses, lab)


# ── 1. DARWAZA: do signal chahiye, ek nahi ───────────────────────────────────
def test_gate_needs_both_signals():
    assert tm.is_request(TRADE_ASK) is True
    # sirf trading ki baat = padhne ka sawaal, model ki farmaish nahi
    assert tm.is_request("scalping kya hoti hai samjhao") is False
    # sirf "banao" = koi bhi cheez, trading nahi
    assert tm.is_request("mujhe ek plan banao padhai ka") is False
    assert tm.is_request("") is False


def test_gate_reasons_are_four_different_sentences():
    reasons = {
        tm.request_reason(TRADE_ASK),
        tm.request_reason("scalping kya hoti hai"),
        tm.request_reason("ek plan banao"),
        tm.request_reason("aaj mausam kaisa hai"),
    }
    assert len(reasons) == 4
    assert tm.request_reason("aaj mausam kaisa hai") == tm.NOT_ASKED_REASON


def test_song_ask_never_opens_trade_lane():
    record = tm.study(SONG_ASK, RICH_SPEC, RICH_SOURCES, [], RICH_LAB)
    assert record["wanted"] is False
    assert record["asked"] is False
    assert record["ran"] is False
    assert record["checks"] == []
    assert record["queries"] == []
    assert record["guidance_blocks"] == []
    # spec bhara hua tha phir bhi ek bhi point MET nahi hua — lane hi nahi khuli
    assert "met_count" not in record


def test_not_asked_carries_wanted_but_study_record_does_not():
    closed = tm.not_asked(SONG_ASK)
    assert closed["wanted"] is False
    open_record = _full_report()
    # Ye key ka HONA hi asli farak hai: "darwaza band tha" vs "lane chali".
    assert "wanted" not in open_record
    assert open_record["ran"] is True


def test_ask_of_closed_gate_is_empty_but_says_why():
    ask = tm.ask_of(SONG_ASK)
    assert ask.asked is False
    assert ask.instruments == ()
    assert ask.chain == ()
    assert ask.demands == ()
    assert ask.reason == tm.NOT_ASKED_REASON


# ── 2. FARMAISH PADHNA ───────────────────────────────────────────────────────
def test_chain_is_context_confirmation_entry_in_that_order():
    ask = tm.ask_of(TRADE_ASK)
    assert ask.chain == (("context", "15M"), ("confirmation", "5M"),
                         ("entry", "1M"))


def test_execution_word_next_to_15m_does_not_steal_entry():
    # "Final execution 15M context" me `execution` 15M ke bilkul paas hai.
    # Phir bhi entry 1M hi rehna chahiye, warna chain jhoothi ban jaati hai.
    ask = tm.ask_of(TRADE_ASK)
    chain = dict(ask.chain)
    assert chain["entry"] == "1M"
    assert chain["context"] == "15M"


def test_timeframe_word_boundary_15m_is_not_1m():
    ask = tm.ask_of("15M chart par trading model banao")
    assert "15M" in ask.timeframes
    assert "1M" not in ask.timeframes


def test_role_without_timeframe_makes_no_pair():
    ask = tm.ask_of("entry ke rules ke saath trading model banao")
    assert ask.chain == ()


def test_hypothesis_count_from_kam_se_kam():
    assert tm.ask_of(TRADE_ASK).hypothesis_count == 7
    assert tm.ask_of("at least 9 competing hypotheses wala trading model banao"
                     ).hypothesis_count == 9


def test_instruments_and_families_read_from_ask():
    ask = tm.ask_of(TRADE_ASK)
    assert ask.instruments == ("us100", "xauusd")
    assert set(ask.families) == {"index", "metal"}
    assert ask.separate_per_instrument is True


def test_nas100_is_the_same_instrument_as_us100():
    ask = tm.ask_of("NAS100 ke liye scalping trading model banao")
    assert ask.instruments == ("us100",)


def test_style_and_demands_and_concepts_are_named():
    ask = tm.ask_of(TRADE_ASK)
    assert ask.style_id == "scalping"
    for key in ("walk_forward", "monte_carlo", "robustness", "baseline",
                "red_team", "microstructure"):
        assert key in ask.demands
    assert ask.concepts == ("ict", "smc", "wyckoff")


def test_ask_dict_admits_its_lists_are_not_exhaustive():
    data = tm.ask_of(TRADE_ASK).to_dict()
    for key in ("instrument_list_is_not_exhaustive",
                "timeframe_list_is_not_exhaustive",
                "style_list_is_not_exhaustive",
                "concepts_earn_their_place"):
        assert data[key] is True


# ── 3. CONTRACT ka dhaancha ──────────────────────────────────────────────────
def test_contract_points_come_from_the_table_not_a_typed_number():
    assert tm.CONTRACT_POINTS == len(tm.CONTRACT)
    assert tm.CONTRACT_POINTS == 34
    assert len(set(tm.CONTRACT_IDS)) == tm.CONTRACT_POINTS


def test_every_contract_point_has_a_group_and_a_need():
    for point in tm.CONTRACT:
        assert point.group in tm.GROUPS
        assert point.needs.strip()
        assert point.label.strip()


def test_every_point_has_a_measurer_and_measure_refuses_without_one():
    for point_id in tm.CONTRACT_IDS:
        assert point_id in tm._EVALUATORS
    saved = dict(tm._EVALUATORS)
    victim = tm.CONTRACT_IDS[0]
    try:
        del tm._EVALUATORS[victim]
        raised = False
        try:
            _measure(spec=RICH_SPEC)
        except AssertionError as exc:
            raised = True
            assert victim in str(exc)
        assert raised, "bina naap wala point chup-chaap nikal gaya"
    finally:
        tm._EVALUATORS.clear()
        tm._EVALUATORS.update(saved)


def test_empty_spec_gives_zero_met_not_all_ok():
    report = _measure()
    assert report["met_count"] == 0
    # Ye 4 point ASK me maange gaye the aur spec me nahi mile — inka NOT_MET
    # imaandaar hai. Baaki 30 par app chup hai, isliye NOT_MEASURED.
    assert report["not_met_count"] == 4
    assert report["not_measured_count"] == 30
    assert set(report["not_met"]) == {"instrument_scope", "execution_chain",
                                      "concept_definitions",
                                      "no_authority_truth"}


def test_default_status_is_not_measured_not_met():
    assert tm.policy()["default_status"] == tm.NOT_MEASURED
    for row in _measure()["checks"]:
        assert row["status"] in tm.CHECK_STATUSES
        assert row["status"] != tm.MET


def test_rich_spec_leaves_no_dead_check_except_the_blocked_one():
    # Agar koi point kabhi MET ho hi na sake to naap dikhawa hai. Isliye ek
    # "poora" spec par sirf structurally blocked point hi MET se bahar rahe.
    report = _full_report()
    assert report["not_met_count"] == 0
    assert report["not_measured"] == ["order_flow_edge"]
    assert report["met_count"] == tm.CONTRACT_POINTS - 1


# ── 4. NAAP ke auzaar (primitives) ───────────────────────────────────────────
def test_subjective_word_is_allowed_only_when_it_carries_a_number():
    hits = tm.subjective_hits("strong FVG dikha.\n"
                              "good OB = volume >= 150% of 20-bar mean.")
    by_term = {hit["term"]: hit for hit in hits}
    assert by_term["strong fvg"]["quantified"] is False
    assert by_term["good ob"]["quantified"] is True
    # line number bhi aata hai, warna user ko pata hi na chale kahan hai
    assert by_term["strong fvg"]["line_no"] == 1
    assert by_term["good ob"]["line_no"] == 2


def test_entry_slots_has_all_nine_and_partial_stays_partial():
    assert len(tm.ENTRY_SLOTS) == 9
    partial = tm.entry_slots("WHERE: at 15M level. WHEN: London. STOP LOSS: 1 ATR")
    filled = [key for key, value in partial.items() if value]
    assert set(filled) == {"where", "when", "stop"}
    assert len(partial) == 9  # baaki 6 khaali dikhein, gayab na hon


def test_metrics_in_finds_nine_fields_and_win_rate_is_only_one_of_them():
    assert len(tm.METRIC_FIELDS) == 9
    found = tm.metrics_in(RICH_SPEC)
    assert set(name for name, value in found.items() if value) == {
        name for name, _cues in tm.METRIC_FIELDS}
    thin = tm.metrics_in("Win rate 92% hai, bas.")
    assert thin["win_rate"]
    assert not thin["expectancy"]


def test_win_rate_claim_read_from_both_word_orders():
    assert tm.win_rate_claims("win rate 92%") == [92.0]
    assert tm.win_rate_claims("95% win rate") == [95.0]


def test_chased_win_rate_boundary_sits_exactly_on_ninety():
    assert tm.MAX_CREDIBLE_WIN_RATE == 90.0
    assert tm.chased_win_rate("win rate 90%") == [90.0]
    assert tm.chased_win_rate("win rate 89.9%") == []
    assert tm.chased_win_rate("win rate 47%") == []


def test_story_claim_caught_and_evidence_labels_read():
    assert tm.story_claims("institutions hunted my stop loss")
    assert tm.story_claims("bas price upar gaya") == []
    assert tm.evidence_labels_in("[EVIDENCE-A] x [EVIDENCE-E] y") == ["A", "E"]
    assert tm.evidence_labels_in("EVIDENCE A ke hisaab se") == []


def test_original_hypothesis_counted_from_label_not_from_hope():
    assert tm.original_hypothesis_count([], "kuch naya socha hai") == 0
    two = (tm.ORIGINAL_HYPOTHESIS_LABEL + ": a\n"
           + tm.ORIGINAL_HYPOTHESIS_LABEL + ": b")
    assert tm.original_hypothesis_count([], two) == 2


# ── 5. EVALUATOR: har point apna sach khud naapta hai ────────────────────────
def test_instrument_scope_needs_each_instrument_to_have_its_own_numbers():
    one_side = ("US100 15M context, sample size 1840 trades, "
                "expectancy 0.11R.")
    row = _row(_measure(spec=one_side), "instrument_scope")
    assert row["status"] == tm.NOT_MET
    assert "xauusd" in row["reason"]


def test_execution_chain_must_go_big_to_small():
    ask_q = ("1M context -> 5M confirmation -> 15M entry wala "
             "US100 trading model banao")
    row = _row(_measure(spec="1M 5M 15M", question=ask_q), "execution_chain")
    assert row["status"] == tm.NOT_MET
    assert "kram" in row["reason"]


def test_execution_chain_not_measured_when_ask_itself_was_vague():
    row = _row(_measure(spec=RICH_SPEC,
                        question="US100 ke liye scalping model banao"),
               "execution_chain")
    assert row["status"] == tm.NOT_MEASURED


def test_order_flow_edge_can_never_be_met_and_is_fail_if_claimed():
    assert "order_flow_edge" in tm.STRUCTURALLY_BLOCKED
    silent = _row(_measure(spec="kuch aur likha hai"), "order_flow_edge")
    assert silent["status"] == tm.NOT_MEASURED
    assert silent["blocked_by"]
    claimed = _row(_measure(
        spec="Order flow footprint delta se edge mila, 0.05R better."),
        "order_flow_edge")
    assert claimed["status"] == tm.NOT_MET
    # aur poore RICH_SPEC par bhi — jahan sab kuch bhara hai — MET nahi hota
    assert _status(_full_report(), "order_flow_edge") == tm.NOT_MEASURED


def test_honest_order_flow_denial_is_not_read_as_a_claim():
    honest = _row(_measure(spec="tick/order-book data missing, isliye order "
                                "flow ka daawa nahi kiya gaya."),
                  "order_flow_edge")
    assert honest["status"] == tm.NOT_MEASURED


def test_hypothesis_shortfall_is_never_rounded_up():
    few = _row(_measure(spec="H1 liquidity sweep. H2 ORB. H3 VWAP fade."),
               "competing_hypotheses")
    assert few["status"] == tm.NOT_MET
    assert "7" in few["reason"] and "3" in few["reason"]
    one = _row(_measure(spec=tm.ORIGINAL_HYPOTHESIS_LABEL + ": ek hi hai"),
               "original_hypotheses")
    assert one["status"] == tm.NOT_MET


def test_silence_about_leakage_is_not_a_clean_bill():
    quiet = _row(_measure(spec="model ke rules likhe hain"), "no_leakage")
    assert quiet["status"] == tm.NOT_MEASURED
    # sirf sawaal uthana bhi jawab nahi hai
    named = _row(_measure(spec="Data leakage check kiya gaya, sab theek."),
                 "no_leakage")
    assert named["status"] == tm.NOT_MET


def test_ninety_percent_win_rate_fails_even_with_all_nine_metrics():
    greedy = RICH_SPEC.replace("Win rate 47%", "Win rate 92%")
    report = _measure(spec=greedy, sources=RICH_SOURCES, lab=RICH_LAB)
    assert _status(report, "performance_metrics") == tm.NOT_MET
    assert report["chased_win_rate"] == [92.0]
    # baaki 9 metric maujood hone ke baawajood — ginti se jhooth nahi dhakta
    assert len([name for name, value in
                tm.metrics_in(greedy).items() if value]) == 9


def test_entry_model_partial_is_not_met_and_names_the_empty_slots():
    row = _row(_measure(spec="WHERE: level. WHEN: London. STOP LOSS: 1.2 ATR."),
               "entry_model_exact")
    assert row["status"] == tm.NOT_MET
    for slot in ("why", "direction", "trigger", "invalidation", "target",
                 "no_trade"):
        assert slot in row["reason"]


def test_evidence_labels_without_a_single_failure_is_not_met():
    only_wins = ("[EVIDENCE-A] a [EVIDENCE-B] b [EVIDENCE-C] c "
                 "[EVIDENCE-D] naya hypothesis hai")
    row = _row(_measure(spec=only_wins), "evidence_labels_ae")
    assert row["status"] == tm.NOT_MET
    # D = "abhi test hi nahi hui" — ye haar ka saboot nahi hai
    assert "[evidence-d]" not in tm._NEGATIVE_RESULT_CUES
    assert "[evidence-e]" in tm._NEGATIVE_RESULT_CUES


def test_no_labels_at_all_is_not_measured_not_a_fail_of_labels():
    row = _row(_measure(spec="model ke rules likhe hain"),
               "evidence_labels_ae")
    assert row["status"] == tm.NOT_MEASURED


def test_final_decision_not_measured_when_neither_refused_nor_delivered():
    row = _row(_measure(spec="thoda data dekha, aage dekhenge"),
               "honest_final_decision")
    assert row["status"] == tm.NOT_MEASURED


def test_refusal_alone_is_honest_even_with_many_failed_points():
    honest = ("Kaafi saboot nahi mila. missing: tick data, order book. "
              "Isliye final model nahi bana.")
    report = _measure(spec=honest)
    assert _status(report, "honest_final_decision") == tm.MET
    # ...aur ye inkaar hai, delivery nahi — cue ke peechhe ka "nahi" padha gaya
    assert tm._delivered_cue_hits(tm._norm("final model nahi bana")) == []
    assert tm._delivered_cue_hits(tm._norm("final model diya gaya")) == [
        "final model"]


def test_a_missing_line_cannot_hide_a_failed_point():
    # RICH_SPEC me "missing:" ki line hai. Usme sirf win-rate ka jhooth ghusa
    # dein to inkaar ki line us fail ko dhak nahi sakti.
    greedy = RICH_SPEC.replace("Win rate 47%", "Win rate 92%")
    row = _row(_measure(spec=greedy, sources=RICH_SOURCES, lab=RICH_LAB),
               "honest_final_decision")
    assert row["status"] == tm.NOT_MET
    assert "performance_metrics" in row["reason"]


# ── 6. LAB SE NATEEJA: daawa nahi, chala hua test ────────────────────────────
_LAB_POINTS = (("walk_forward_validation", "walk_forward"),
               ("monte_carlo_risk", "monte_carlo"),
               ("parameter_robustness", "parameter_robustness"),
               ("baseline_tournament", "baseline_tournament"))


def test_lab_points_take_their_verdict_from_lab_rows_not_from_the_spec():
    for point_id, recipe in _LAB_POINTS:
        lab_ok = {"hypotheses": [{"tests": [{"recipe": recipe,
                                             "status": "TESTED_PASS"}]}]}
        assert _status(_measure(spec=RICH_SPEC, lab=lab_ok),
                       point_id) == tm.MET
        # spec me daawa, LAB me 0 test = NOT_MET (likha hua naap nahi hai)
        assert _status(_measure(spec=RICH_SPEC, lab=None),
                       point_id) == tm.NOT_MET
        # na daawa na test = NOT_MEASURED
        assert _status(_measure(spec="", lab=None),
                       point_id) == tm.NOT_MEASURED


def test_lab_test_that_ran_and_failed_is_not_met_not_hidden():
    for point_id, recipe in _LAB_POINTS:
        lab_bad = {"hypotheses": [{"tests": [{"recipe": recipe,
                                              "status": "TESTED_FAIL"}]}]}
        row = _row(_measure(spec=RICH_SPEC, lab=lab_bad), point_id)
        assert row["status"] == tm.NOT_MET
        assert "pass" in row["reason"].lower()


def test_lab_recipe_status_counts_runs_and_passes_separately():
    assert tm.lab_recipe_status(RICH_LAB, "walk_forward") == (1, 1)
    assert tm.lab_recipe_status({}, "walk_forward") == (0, 0)
    ran_failed = {"hypotheses": [{"tests": [{"recipe": "walk_forward",
                                             "status": "TESTED_FAIL"}]}]}
    assert tm.lab_recipe_status(ran_failed, "walk_forward") == (1, 0)


# ── 7. SOURCE ki ginti source se, daawe se nahi ──────────────────────────────
def test_institutional_source_counted_by_host_not_by_word():
    rows = tm.institutional_sources(RICH_SOURCES)
    assert [row["source_id"] for row in rows] == ["S1", "S2", "S3"]
    # blog par "ICT" likha hona official document nahi banata
    assert all(row["host"] != "blog.example.com" for row in rows)


def test_academic_source_counted_by_type_and_deep_read_by_level():
    assert [row["source_id"] for row in tm.academic_sources(RICH_SOURCES)] == [
        "S3", "S4"]
    assert tm.ACADEMIC_SOURCE_TYPES == ("paper",)
    # snippet padhna "asli tark padha" nahi hai
    assert len(tm.deeply_read(RICH_SOURCES)) == 4
    assert tm.DEEP_READ_LEVELS == ("claims", "full_text")


def test_zero_sources_is_not_measured_but_wrong_sources_is_not_met():
    for point_id in ("institutional_sources", "academic_sources"):
        assert _status(_measure(spec=RICH_SPEC), point_id) == tm.NOT_MEASURED
        only_blog = _measure(spec=RICH_SPEC, sources=[RICH_SOURCES[4]])
        assert _status(only_blog, point_id) == tm.NOT_MET
        assert _status(_measure(spec=RICH_SPEC, sources=RICH_SOURCES),
                       point_id) == tm.MET


# ── 8. QUERY: gate band to ek bhi query nahi ──────────────────────────────────
def test_no_query_when_the_lane_is_shut():
    assert tm.study_queries(tm.ask_of(SONG_ASK)) == []
    assert tm.prompt_block(tm.ask_of(SONG_ASK)) == ""


def test_venue_terms_come_first_and_queries_are_deduped_and_capped():
    queries = tm.study_queries(tm.ask_of(TRADE_ASK))
    us100 = [item for item in tm.INSTRUMENTS if item.instrument_id == "us100"][0]
    assert queries[:3] == list(us100.venue_terms)
    assert len(queries) == len(set(queries))
    assert len(queries) <= tm.MAX_QUERIES
    assert tm.MAX_QUERIES == 24


def test_study_plan_says_zero_gemini_and_institutional_first():
    plan = tm.study_plan(tm.ask_of(TRADE_ASK))
    assert plan["gemini_calls"] == 0
    assert plan["network_used"] is False
    assert plan["institutional_first"] is True
    assert plan["queries"]
    assert plan["institutional_queries"]


# ── 9. JAWAB me buri khabar pehle ─────────────────────────────────────────────
def test_section_lines_are_empty_when_nothing_was_measured():
    assert tm.section_lines({}) == []
    assert tm.section_lines({"checks": []}) == []


def test_not_met_is_printed_before_met():
    greedy = RICH_SPEC.replace("Win rate 47%", "Win rate 92%")
    report = _measure(spec=greedy, sources=RICH_SOURCES, lab=RICH_LAB)
    text = "\n".join(tm.section_lines(report))
    assert "performance_metrics" in text
    first_bad = text.index("performance_metrics")
    first_good = text.index("realistic_costs")
    assert first_bad < first_good, "buri khabar ko MET ke baad chhupaya gaya"


def test_ninety_percent_claim_gets_its_own_warning_line():
    greedy = RICH_SPEC.replace("Win rate 47%", "Win rate 92%")
    report = _measure(spec=greedy, sources=RICH_SOURCES, lab=RICH_LAB)
    text = "\n".join(tm.section_lines(report))
    assert "92" in text
    assert "90" in text


def test_limits_never_exceed_their_own_measured_ceiling():
    report = _full_report()
    assert len(report["limits"]) <= tm.MAX_AUDIT_LIMIT_LINES
    assert report["max_audit_limit_lines"] == tm.MAX_AUDIT_LIMIT_LINES
    # chhat sabse bure haal se naapi gayi hai, khaali call se nahi — warna
    # "ye point naapa nahi gaya" wali line hi kat jaati
    assert tm.MAX_AUDIT_LIMIT_LINES > len(tm.limits())


def test_blocked_point_and_unmeasured_points_are_named_in_limits():
    text = "\n".join(_full_report()["limits"])
    assert "order_flow_edge" in text
    assert "LIVE_TESTED=False" in text
    assert "ORDER_BOOK_READ=False" in text


def test_policy_admits_the_default_and_the_blocked_point():
    policy = tm.policy()
    assert policy["default_status"] == tm.NOT_MEASURED
    assert policy["gemini_calls"] == 0
    assert policy["network_used"] is False
    assert policy["provider_cost"] == "₹0"
    assert "order_flow_edge" in policy["structurally_blocked"]
    assert policy["contract_points"] == tm.CONTRACT_POINTS


# ── 10. PUBLIC RECORD: buri khabar hi bachti hai ─────────────────────────────
def test_public_record_keeps_bad_news_and_drops_the_pass_list():
    record = tm.public_record(_full_report())
    assert record["not_measured"] == ["order_flow_edge"]
    assert record["not_met"] == []
    assert record["met_count"] == tm.CONTRACT_POINTS - 1
    # "kaunse point pass hue" ki poori list bahar nahi jaati — us list ko log
    # trophy ki tarah padhte hain. Fail aur naapa-nahi-gaya hamesha jaata hai.
    assert "met" not in record
    assert "checks" not in record
    assert record["status_vocabulary"] == [tm.MET, tm.NOT_MET, tm.NOT_MEASURED]
    assert len(record["limit_lines"]) <= tm.MAX_AUDIT_LIMIT_LINES


def test_public_record_echoes_wanted_only_for_a_closed_lane():
    closed = tm.public_record(tm.not_asked(SONG_ASK))
    assert closed["wanted"] is False
    assert closed["reason"] == tm.NOT_ASKED_REASON
    assert "wanted" not in tm.public_record(_full_report())


def test_guidance_block_exists_on_a_trade_ask_and_never_promises_profit():
    blocks = _full_report()["guidance_blocks"]
    assert blocks and isinstance(blocks[0], str)
    text = blocks[0].lower()
    assert "contract" in text
    for promise in ("guaranteed", "sure profit", "pakka profit", "100% win"):
        assert promise not in text


# ── 11. DO MODULE, EK ZUBAAN — par bandhak nahi ──────────────────────────────
def test_status_words_match_craft_without_importing_them():
    # Barabar hona chahiye taaki UI ek hi zubaan padhe. Par yahan literal se
    # pin hai — agar kal `craft` apna naam badle to test bolega, chup nahi
    # rahega, aur `trademodel` uska bandhak bhi nahi banega.
    assert tm.MET == craft.MET == "MET"
    assert tm.NOT_MET == craft.NOT_MET == "NOT_MET"
    assert tm.NOT_MEASURED == craft.NOT_MEASURED == "NOT_MEASURED"


def test_the_two_market_notes_are_the_same_objects_market_data_uses():
    # Ye JAAN-BOOJH KAR import se aaye hain: do jagah do alag "ye advice nahi
    # hai" line likhna, ek jagah ka sudhaar doosri jagah na pahunchna hai.
    assert tm.NOT_ADVICE_NOTE is market_data.NOT_ADVICE_NOTE
    assert tm.BACKTEST_NOTE is market_data.BACKTEST_NOTE


def test_lab_status_strings_are_pinned_by_literal_here():
    assert RICH_LAB["hypotheses"][0]["tests"][0]["status"] == "TESTED_PASS"
    assert tm.lab_recipe_status(RICH_LAB, "walk_forward") == (1, 1)


def test_zero_gemini_zero_network_and_the_same_answer_twice():
    first = _full_report()
    second = _full_report()
    assert first["gemini_calls"] == 0
    assert first["network_used"] is False
    assert first["deterministic"] is True
    assert first["provider_cost"] == "₹0"
    assert first["live_tested"] is False
    assert first["broker_connected"] is False
    assert first["financial_advice"] is False
    assert first["checks"] == second["checks"]
    assert first["section_lines"] == second["section_lines"]
    assert first["queries"] == second["queries"]


# ── 12. TEEN STRUCTURAL FAIL: ye teen jagah PASS ho hi nahi sakti ────────────
def test_one_unquantified_word_fails_an_otherwise_perfect_spec():
    dirty = RICH_SPEC + "\nStrong FVG par entry lo, clear liquidity dekh kar."
    report = _measure(spec=dirty, sources=RICH_SOURCES, lab=RICH_LAB)
    row = _row(report, "subjective_terms_banned")
    assert row["status"] == tm.NOT_MET
    assert "strong fvg" in row["reason"]
    assert "clear liquidity" in row["reason"]
    # line number bina naap ke shabd ke saath jaata hai
    assert "@L" in row["reason"]
    assert report["subjective_unquantified"]
    # aur wahi spec bina un shabdon ke MET hota hai — check zinda hai
    assert _status(_full_report(), "subjective_terms_banned") == tm.MET


def test_concept_is_never_true_because_someone_famous_said_so():
    row = _row(_measure(spec="ICT SMC Wyckoff sahi hote hain, sab pro use "
                             "karte hain."), "no_authority_truth")
    assert row["status"] == tm.NOT_MET
    assert tm.CONCEPTS_EARN_THEIR_PLACE is True


def test_stop_hunt_story_without_a_payoff_argument_fails():
    row = _row(_measure(spec="institutions hunted my stop, smart money "
                             "grabbed liquidity."), "game_theory")
    assert row["status"] == tm.NOT_MET


# ── 13. LANE ISOLATION: gaane ka ek shabd bhi trading jawab me nahi ──────────
def test_no_song_vocabulary_anywhere_in_a_trade_report():
    report = _full_report()
    text = ("\n".join(report["section_lines"]) + "\n"
            + "\n".join(report["limits"]) + "\n"
            + "\n".join(report["guidance_blocks"]) + "\n"
            + "\n".join(report["queries"])).lower()
    for word in ("gaana", "lyric", "antara", "mukhda", "chorus", "raag",
                 "taal", "singer", "mood arc", "punjabi"):
        assert word not in text, "gaane ka shabd trading jawab me aa gaya: " + word


# ── 14. MUTATION SE NIKLI KAMZORIYAN: har taala apne test se bandha ──────────
# Neeche ka har test ek asli mutation ke jawab me likha gaya hai. `trademodel.py`
# ki us ek line ko todne par ye test RED hona chahiye — warna wo line sirf likhi
# hui hai, naapi hui nahi. Koi purana test badla nahi gaya, sirf jodha gaya hai.
def test_chain_pair_needs_role_and_timeframe_close_together():
    # doori ki seema (CHAIN_WINDOW_CHARS) hat jaaye to koi bhi jodi ban jaayegi
    far = "context ke baare me poora hissa alag likha gaya hai aur 15M chart"
    assert tm.CHAIN_WINDOW_CHARS < len(far)
    assert tm._chain_in(far) == []
    assert tm._chain_in("context 15M") == [("context", "15M")]


def test_one_timeframe_cannot_fill_two_roles_of_the_chain():
    # "context confirmation 15M" me ek hi timeframe hai — chain ke do role usse
    # nahi bhare ja sakte, warna 15M -> 15M -> 15M bhi "chain" lagne lagegi.
    pairs = tm._chain_in("context confirmation 15M")
    assert len(pairs) == 1
    assert [name for _role, name in pairs] == ["15M"]


def test_timeframes_come_back_smallest_first():
    assert tm.ask_of(TRADE_ASK).timeframes == ("1M", "5M", "15M")


def test_two_instruments_alone_mean_a_separate_study():
    assert tm.ask_of("US100 aur XAUUSD ka scalping model banao"
                     ).separate_per_instrument is True
    assert tm.ask_of("US100 ka scalping model banao"
                     ).separate_per_instrument is False


def test_unknown_status_from_an_evaluator_collapses_to_not_measured():
    point_id = "research_timeframes"
    original = tm._EVALUATORS[point_id]
    try:
        tm._EVALUATORS[point_id] = lambda ctx: {"status": "SAB THEEK",
                                                "observed": "kuch bhi"}
        row = _row(_measure(RICH_SPEC, RICH_SOURCES, [], RICH_LAB), point_id)
    finally:
        tm._EVALUATORS[point_id] = original
    assert row["status"] == tm.NOT_MEASURED
    assert "pehchana nahi gaya" in row["reason"]


def test_three_way_needs_a_number_not_just_the_word():
    named = tm._three_way("Spread aur commission ka zikr hai", ("spread",),
                          "lagat", "need")
    assert named["status"] == tm.NOT_MET
    silent = tm._three_way("kuch aur hi likha hai", ("spread",),
                           "lagat", "need")
    assert silent["status"] == tm.NOT_MEASURED


def test_coverage_below_the_minimum_is_not_met():
    groups = (("spread", ("spread",)), ("slippage", ("slippage",)),
              ("latency", ("latency",)))
    thin = tm._coverage("spread 0.8 points modelled", groups, 3,
                        "lagat", "need")
    assert thin["status"] == tm.NOT_MET
    empty = tm._coverage("kuch bhi nahi", groups, 3, "lagat", "need")
    assert empty["status"] == tm.NOT_MEASURED


def test_single_instrument_ask_never_gets_a_separate_study_verdict():
    row = _row(_measure(RICH_SPEC, RICH_SOURCES, [], RICH_LAB,
                        question="US100 ke liye scalping model banao"),
               "instrument_scope")
    assert row["status"] == tm.NOT_MEASURED


def test_both_instruments_named_but_only_one_carries_numbers():
    spec = ("US100 15M context trend filter slope 0.02.\n"
            "XAUUSD bhi isi tarah chalega.")
    row = _row(_measure(spec), "instrument_scope")
    assert row["status"] == tm.NOT_MET
    assert "apna number nahi" in row["reason"]


def test_theory_names_without_a_deeply_read_source_is_not_met():
    spec = ("Market microstructure and price discovery padha.\n"
            "Liquidity aur adverse selection.")
    shallow = [Src("S9", "https://x.example.com/a", "web", "snippet")]
    row = _row(_measure(spec, shallow), "theory_base")
    assert row["status"] == tm.NOT_MET
    assert "padha hi nahi gaya" in row["reason"]


def test_concept_definition_without_a_number_is_not_met():
    row = _row(_measure("ICT fair value gap: define if gap bada ho to entry "
                        "karo.", question="ICT ka trading model banao"),
               "concept_definitions")
    assert row["status"] == tm.NOT_MET
    assert "number ke saath nahi" in row["reason"]


def test_one_defined_concept_does_not_cover_an_undefined_one():
    spec = ("ICT fair value gap: define if gap >= 0.5 ATR.\n"
            "SMC order block bhi dekha gaya.")
    row = _row(_measure(spec, question="ICT aur SMC ka trading model banao"),
               "concept_definitions")
    assert row["status"] == tm.NOT_MET
    assert "smc" in row["reason"].lower()


def test_baseline_without_sample_size_does_not_earn_a_concept_its_place():
    row = _row(_measure("ICT fair value gap compared with baseline random "
                        "entry.", question="ICT ka trading model banao"),
               "no_authority_truth")
    assert row["status"] == tm.NOT_MET
    assert "sample size" in row["reason"]


def test_seven_names_for_one_idea_are_not_seven_hypotheses():
    hyp = [{"statement": "ek hi baat"} for _ in range(7)]
    row = _row(_measure("", (), hyp), "competing_hypotheses")
    assert row["status"] == tm.NOT_MET
    assert "dohra" in row["reason"]


def test_unlabelled_hypothesis_is_not_counted_as_our_own():
    assert tm.original_hypothesis_count([{"statement": "kuch bhi"}], "") == 0
    labelled = [{"statement": tm.ORIGINAL_HYPOTHESIS_LABEL + ": kuch naya"}]
    assert tm.original_hypothesis_count(labelled, "") == 1


def test_a_story_survives_even_next_to_real_incentive_reasoning():
    spec = ("Game theory: market maker incentive inventory control, payoff "
            "0.6.\ninstitutions hunted my stop isliye ulta gaya.")
    row = _row(_measure(spec), "game_theory")
    assert row["status"] == tm.NOT_MET
    assert "bina-saboot kahani" in row["reason"]


def test_nine_filled_slots_do_not_pardon_a_discretionary_word():
    row = _row(_measure(RICH_SPEC + "\nclear liquidity dekh kar entry.\n",
                        RICH_SOURCES, [], RICH_LAB), "entry_model_exact")
    assert row["status"] == tm.NOT_MET
    assert "clear liquidity" in row["reason"]


def test_two_numbers_do_not_fill_the_performance_point():
    row = _row(_measure("Win rate 47%, expectancy 0.11R."),
               "performance_metrics")
    assert row["status"] == tm.NOT_MET
    assert "profit_factor" in row["reason"]


def test_two_evidence_labels_are_not_enough_variety():
    spec = "[EVIDENCE-A] a\n[EVIDENCE-B] b\nICT edge failed out of sample."
    row = _row(_measure(spec), "evidence_labels_ae")
    assert row["status"] == tm.NOT_MET


# Model de bhi diya aur 92% win rate ka daawa bhi — dono ek saath.
DELIVERED_WITH_HOLES = ("Final spec: long if 15M slope > 0. Entry rule "
                        "chalao. Win rate 92% mila.")


def test_delivering_a_model_while_points_failed_is_not_honest():
    row = _row(_measure(DELIVERED_WITH_HOLES), "honest_final_decision")
    assert row["status"] == tm.NOT_MET
    assert "zikr inkaar me nahi hua" in row["reason"]


def test_chased_win_rate_warning_reaches_the_answer_section():
    lines = tm.section_lines(_measure(DELIVERED_WITH_HOLES))
    warn = [line for line in lines if "Chetavni" in line and "92.0" in line]
    assert len(warn) == 1


def test_story_claim_warning_reaches_the_answer_section():
    report = _measure("Game theory incentive 0.6 payoff.\n"
                      "institutions hunted my stop.")
    warn = [line for line in tm.section_lines(report)
            if "Bina saboot ki kahani mili" in line]
    assert len(warn) == 1
    assert "institutions hunted my stop" in warn[0]


def test_structurally_blocked_point_is_named_in_the_limits():
    blocked = [line for line in tm.limits(_measure(DELIVERED_WITH_HOLES))
               if "MET ho hi nahi sakta" in line]
    assert len(blocked) == 1
    assert "order_flow_edge" in blocked[0]


def test_public_record_carries_the_failed_point_names():
    report = _measure(DELIVERED_WITH_HOLES)
    record = tm.public_record(report)
    assert record["not_met"] == list(report["not_met"])
    assert record["not_met"]


def test_a_repeated_concept_does_not_produce_a_repeated_query():
    # TRADE_ASK me sahi mein koi duplicate nahi banta, isliye dedup ko naapne ke
    # liye ek hi concept do baar diya gaya hai.
    ask = tm.TradeAsk(asked=True, instruments=("us100",),
                      concepts=("ict", "ict"))
    queries = tm.study_queries(ask)
    assert len(queries) == len({q.lower() for q in queries})
    assert len([q for q in queries if q.lower().startswith("ict ")]) == 1


def test_closed_lane_plan_says_wanted_false():
    assert tm.study_plan(tm.ask_of(SONG_ASK))["wanted"] is False


def test_prompt_block_actually_renders_contract_points():
    block = tm.prompt_block(tm.ask_of(TRADE_ASK))
    rendered = [line for line in block.splitlines()
                if line.startswith("  - ")
                and any(pid + ":" in line for pid in tm.CONTRACT_IDS)]
    assert tm.PROMPT_MAX_POINTS > 0
    assert len(rendered) == tm.PROMPT_MAX_POINTS










