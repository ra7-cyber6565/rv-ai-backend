"""#150h — trade-level backtest ka naap: leakage, ginti, teesri haalat, wiring.

Kyun ye file bani: #150f/#150g ke baad trading ka jawab do NAYE raaste se banta
hai — `market_data.simulate_trades/trade_stats/trade_expectancy` (asli trade),
aur `lab._run_trade_expectancy` → `TestResult.numbers` → `trademodel` ke paanch
contract point. Dono raaste par wahi purani galtiyan sabse aasaani se ghusti
hain, isliye har test yahan ek NAAPA hua jhooth rokta hai:

  - **leakage** — entry, direction, stop aur cost sirf `values[:index]` se banein;
    aage ki koi value entry ka faisla na badle (yahi backtest ka sabse chupa
    jhooth hai, kyunki result shaandaar dikhta hai aur galat hota hai);
  - **"infinite profit factor"** — ek bhi haar na ho to profit factor `None`
    rehna chahiye, aur wo sample "edge mil gaya" ka saboot NAHI hai (teesri
    haalat `NO_LOSS_TO_MEASURE`);
  - **"edge mil gaya"** jab wo sirf ek magic R par zinda ho (`FRAGILE_EDGE`);
  - **chhota sample** — 8 se kam trade par expectancy chhaapna, ya 2 trade wali
    row ko 20 trade wali jaisa dikhana;
  - **cost sirf likhi hui** — `avg_cost_r` wo naap hai jo sabit karti hai cost
    LAGI thi; 0 aane par point NOT_MET hota hai, MET nahi;
  - **`observed` line se faisla** — insaan ke padhne wali line ko wapas parse
    karna "derive, never declare" ka ulta rasta hai, isliye number sirf
    structured `numbers` se aate hain;
  - **purana raasta kamzor ho jaana** — LAB ka trade test na chale to paanchon
    point bilkul wahi purana text-cue nateeja dete hain (`jo phle bna h unko
    htana mt`).

Koi network, koi randomness, koi provider key, koi Gemini call — sab kuch is
file ke andar ki naapi hui series par chalta hai.
"""
import ast
import datetime as dt
import inspect
import os
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import lab, market_data as md, trademodel as tm  # noqa: E402


# ── helpers: sab deterministic, sab is file ke andar ─────────────────────────
def _src(rel):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        rel)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class _Src:
    """EvidencePack ka sirf wahi hissa jo lab/market_data padhte hain."""

    def __init__(self, source_id, series_meta=None):
        self.source_id = source_id
        self.series_meta = series_meta or {}
        self.title = ""
        self.snippet = ""
        self.full_text = ""


class _Pack:
    def __init__(self, *sources):
        self.sources = list(sources)


def _meta(values):
    """Daily ISO date — din badhta hai, isliye `_condense` ise daily hi rakhta hai."""
    day0 = dt.date(2000, 1, 1)
    return {"provider": "test_provider", "series_id": "X",
            "label": "test series", "frequency": "daily", "unit": "%",
            "points": [[(day0 + dt.timedelta(days=i)).isoformat(), float(v)]
                       for i, v in enumerate(values)]}


def _series(values):
    day0 = dt.date(2000, 1, 1)
    points = [md.SeriesPoint(period=(day0 + dt.timedelta(days=i)).isoformat(),
                             order=i, value=float(v), unit="%")
              for i, v in enumerate(values)]
    return md.MarketSeries(points=points, frequency="daily", unit="%",
                           provider="test_provider", series_id="X",
                           label="test series", source_ids=["S1"], note="")


def _walk(n=200, drift=0.35, seed=7):
    """Deterministic LCG walk — jeet AUR haar dono banti hain (yahi zaroori hai).

    Seedhi ramp par ek bhi haar nahi aati, isliye usse loss-side ka koi naap hi
    nahi hota — aur tab PASS/FAIL ka raasta test hi nahi hota.
    """
    out, level, state = [], 100.0, seed
    for _ in range(n):
        state = (state * 1103515245 + 12345) % 2147483648
        shock = ((state % 2001) / 1000.0) - 1.0
        level += drift + 2.2 * shock
        out.append(round(level, 3))
    return out


def _ramp(n=200, step=0.5):
    return [round(100.0 + step * i, 3) for i in range(n)]


def _hyp(hid="RV-HYP-1"):
    return {"hypothesis_id": hid,
            "statement": "Backtest: next year value badhega, forecast 12 %."}


def _run(values):
    return lab.run_lab("cpi forecast", [_hyp()],
                       pack=_Pack(_Src("S1", _meta(values))))


def _trade_test(report, index=0):
    rows = [t for t in report["hypotheses"][index]["tests"]
            if t["recipe"] == "trade_expectancy"]
    assert rows, "trade_expectancy spec hi nahi bani"
    return rows[0]


def _trade(net, gross=None, cost=0.0, kind="target", mae=0.0):
    """Haath se bana ek trade — ginti ka naap uske andar ke number par tikta hai."""
    return md.Trade(entry_index=1, direction=1, entry=100.0, stop_distance=1.0,
                    exit_index=2, exit_price=100.0 + net, exit_kind=kind,
                    gross_r=(net if gross is None else gross), cost_r=cost,
                    net_r=net, mae_r=mae)


# ══ 1. LEAKAGE — entry ka faisla sirf pichhle data se ════════════════════════
def test_entry_pichhle_close_par_hoti_hai_us_bar_ke_close_par_nahi():
    """`values[index]` par entry lena = wo bar dekh kar entry lena (leakage)."""
    values = _walk()
    trades = md.simulate_trades(values, 140)
    assert trades, "is series par ek bhi trade nahi bani — fixture bekaar hai"
    for trade in trades:
        assert trade.entry == values[trade.entry_index - 1]


def test_direction_aur_stop_dono_sirf_history_se_naape_jaate_hain():
    """Formula yahan DOBARA likha gaya hai — function ko apni gawahi nahi milti."""
    values = _walk()
    trade = md.simulate_trades(values, 140)[0]
    history = values[:trade.entry_index]
    moves = [abs(history[i] - history[i - 1]) for i in range(1, len(history))]
    unit = sum(moves) / float(len(moves))
    drift = (history[-1] - history[0]) / (len(history) - 1)
    assert trade.direction == (1 if drift > 0 else (-1 if drift < 0 else 0))
    assert abs(trade.stop_distance - md.TRADE_STOP_UNITS * unit) < 1e-12


def test_pehle_trade_ke_exit_ke_BAAD_ki_value_badle_to_wo_trade_nahi_badalta():
    """Aage ka data badal kar bhi pichhla faisla wahi rehna chahiye."""
    values = _walk()
    base = md.simulate_trades(values, 140)
    assert len(base) >= 2
    changed = list(values)
    for i in range(base[0].exit_index + 1, len(changed)):
        changed[i] = changed[i] * 1.5 + 7.0
    after = md.simulate_trades(changed, 140)
    assert after[0] == base[0]          # frozen dataclass — poora trade barabar


def test_cost_bhi_sirf_entry_price_se_banti_hai():
    """Cost ka hisaab bhi aage ke kisi price se nahi — warna wo bhi leakage hai."""
    values = _walk()
    for trade in md.simulate_trades(values, 140, cost_fraction=0.001):
        expected = abs(0.001 * trade.entry) / trade.stop_distance
        assert abs(trade.cost_r - expected) < 1e-12


def test_past_move_unit_do_se_kam_point_par_zero_hota_hai():
    """0.0 ka matlab "naap nahi", aur usi se trade banna ruk jaata hai."""
    assert md._past_move_unit([]) == 0.0
    assert md._past_move_unit([100.0]) == 0.0
    assert md._past_move_unit([100.0, 102.0]) == 2.0
    assert md._past_move_unit([100.0, 102.0, 101.0]) == 1.5   # |2| aur |-1|


def test_drift_direction_lookback_sirf_aakhri_N_dekhta_hai():
    """Lookback ka matlab hi ye hai ki purana hissa faisle me na aaye."""
    values = [100.0, 90.0, 80.0, 81.0, 82.0, 83.0]
    assert md._drift_direction(values) == -1
    assert md._drift_direction(values, lookback=4) == 1
    assert md._drift_direction([100.0, 100.0]) == 0
    assert md._drift_direction([100.0]) == 0


def test_do_trade_kabhi_overlap_nahi_karte():
    """Overlap hone par ek hi chaal do baar ginti me aa jaati hai."""
    trades = md.simulate_trades(_walk(), 140)
    for before, after in zip(trades, trades[1:]):
        assert after.entry_index > before.exit_index


def test_bilkul_flat_history_par_koi_trade_nahi_banti():
    """Stop ki naap na ho to R-multiple ka koi matlab nahi — trade hi nahi."""
    assert md.simulate_trades([100.0] * 40, 20) == []


# ══ 2. EXIT — close-only data par bura-se-bura maana jaata hai ═══════════════
# Ye chaar value ka train hissa jaan-boojh kar itna saada hai ki naap HAATH SE
# nikaali ja sakti hai: har move 1.0 → unit 1.0, drift +1 → direction +1,
# entry 103.0, stop 1.5 (1.5 × unit), target 3.0 (2R).
_UP = [100.0, 101.0, 102.0, 103.0]
_DOWN = [103.0, 102.0, 101.0, 100.0]


def test_stop_pehle_lagta_hai_chahe_target_agle_bar_par_ho():
    """Pehle stop, phir target — apne haq me maan lena hi sabse meetha jhooth hai."""
    trade = md.simulate_trades(_UP + [101.0, 110.0, 110.0, 110.0, 110.0], 4)[0]
    assert trade.exit_kind == "stop"
    assert trade.exit_index == 4 and trade.exit_price == 101.0
    assert abs(trade.gross_r - (-2.0 / 1.5)) < 1e-12
    assert abs(trade.mae_r - (2.0 / 1.5)) < 1e-12      # MAE stop se pehle naapa


def test_thik_stop_par_pahunchna_bhi_stop_ginta_hai():
    """`-1.5` bilkul stop par hai. Usko "bacha gaya" maanna apne haq ka hisaab hai."""
    trade = md.simulate_trades(_UP + [101.5, 110.0, 110.0], 4)[0]
    assert trade.exit_kind == "stop" and trade.exit_index == 4


def test_target_pehle_aaye_to_target_par_exit():
    trade = md.simulate_trades(_UP + [107.0, 90.0, 90.0, 90.0], 4)[0]
    assert trade.exit_kind == "target" and trade.exit_index == 4
    assert abs(trade.gross_r - (4.0 / 1.5)) < 1e-12
    assert trade.mae_r == 0.0


def test_thik_target_par_pahunchna_target_ginta_hai():
    trade = md.simulate_trades(_UP + [106.0, 90.0, 90.0], 4)[0]
    assert trade.exit_kind == "target" and trade.exit_index == 4


def test_na_stop_na_target_to_max_bars_par_time_exit():
    trade = md.simulate_trades(_UP + [103.2] * 6, 4, max_bars=5)[0]
    assert trade.exit_kind == "time"
    assert trade.exit_index == 8               # index + max_bars - 1
    assert trade.exit_price == 103.2


def test_series_khatam_ho_jaaye_to_exit_aakhri_point_par_ruk_jaata_hai():
    """Series se aage jaana = na-maujood data padhna."""
    values = _UP + [103.2, 103.2]
    trade = md.simulate_trades(values, 4, max_bars=5)[0]
    assert trade.exit_index == len(values) - 1


def test_short_taraf_bhi_wahi_hisaab_ulta_chalta_hai():
    """Sirf long par sahi hisaab aadha hisaab hai."""
    trade = md.simulate_trades(_DOWN + [101.5, 90.0, 90.0], 4)[0]
    assert trade.direction == -1 and trade.entry == 100.0
    assert trade.exit_kind == "stop"
    assert abs(trade.gross_r - (-1.5 / 1.5)) < 1e-12


def test_net_hamesha_gross_minus_cost_hota_hai():
    """Gross ko net kehna hi backtest ka sabse aam jhooth hai."""
    for trade in md.simulate_trades(_walk(), 140):
        assert abs(trade.net_r - (trade.gross_r - trade.cost_r)) < 1e-12
        assert trade.cost_r > 0


# ══ 3. trade_stats — ginti, aur "naap nahi" ka teesra darja ═════════════════
def test_khaali_aur_bhari_naap_ka_dhaancha_bilkul_ek_jaisa_hai():
    """Key gayab hona = padhne wale ko chup-chaap `None` mil jaana."""
    empty = md.trade_stats([])
    full = md.trade_stats([_trade(1.0), _trade(-1.0, kind="stop")])
    assert sorted(empty) == sorted(full)
    assert len(empty) == 15
    assert empty["n_trades"] == 0
    for key in ("win_rate", "expectancy_r", "profit_factor", "sharpe_r",
                "sortino_r", "avg_win_r", "avg_loss_r", "max_drawdown_r",
                "tail_loss_r", "mae_median_r", "mae_p95_r", "avg_cost_r"):
        assert empty[key] is None, key
    assert empty["loss_classes"] == {} and empty["exit_kinds"] == {}


def test_ek_bhi_haar_na_ho_to_profit_factor_None_rehta_hai():
    """"Infinite profit factor" chhaapna hi jhooth hai — wo naap nahi hoti."""
    stats = md.trade_stats([_trade(2.0), _trade(1.0)])
    assert stats["profit_factor"] is None
    assert stats["avg_loss_r"] is None      # loss side ka koi naap hi nahi
    assert stats["win_rate"] == 1.0
    assert stats["max_drawdown_r"] == 0.0   # ek bhi gira nahi
    # Ulti haalat bhi utni hi zaroori hai: ek bhi JEET na ho to jeet ka naap
    # `None` rehna chahiye — 0.0 likh dena "aausat jeet 0R thi" ka jhooth hai.
    only_loss = md.trade_stats([_trade(-1.0, kind="stop")])
    assert only_loss["avg_win_r"] is None
    assert only_loss["win_rate"] == 0.0
    assert only_loss["profit_factor"] == 0.0    # 0 jeet / 1.0 haar — ye naap hui


def test_thik_zero_net_haar_ginti_me_aata_hai_par_uski_class_nahi_banti():
    """0.0 ko jeet maan lena win-rate ko meetha kar deta hai."""
    stats = md.trade_stats([_trade(1.0), _trade(0.0)])
    assert stats["win_rate"] == 0.5             # 0.0 jeet NAHI hai
    assert stats["avg_loss_r"] == 0.0           # loss side me gina gaya
    assert stats["profit_factor"] is None       # par bhaag ke liye loss_sum 0
    assert stats["loss_classes"] == {}          # wajah gadhi nahi gayi
    assert md.Trade(net_r=0.0).loss_class == ""


def test_drawdown_peak_se_naapa_jaata_hai_na_ki_sirf_aakhri_se():
    """Sirf ending equity dekhna beech ka sabse bura din chhupa deta hai."""
    stats = md.trade_stats([_trade(2.0), _trade(-3.0, kind="stop"),
                            _trade(1.0)])
    assert stats["max_drawdown_r"] == 3.0       # peak +2 → equity -1
    assert stats["expectancy_r"] == 0.0


def test_tail_loss_aur_mae_nearest_rank_par_naape_jaate_hain():
    """Interpolation na hone ka matlab: naap kisi ASLI trade ka number hai."""
    nets = [3.0, -2.0, 1.0, -4.0, 0.5]
    stats = md.trade_stats([_trade(v, kind="stop", mae=abs(v)) for v in nets])
    assert stats["tail_loss_r"] == md._percentile(sorted(nets), 0.05)
    assert stats["tail_loss_r"] == -4.0
    maes = sorted(abs(v) for v in nets)
    assert stats["mae_median_r"] == md._percentile(maes, 0.5)
    assert stats["mae_p95_r"] == md._percentile(maes, 0.95)


def test_avg_cost_r_wahi_naap_hai_jo_sabit_karti_hai_cost_lagi_thi():
    """`avg_cost_r == 0` ka matlab cost LAGI HI NAHI — usko MET nahi maana ja sakta."""
    stats = md.trade_stats([_trade(1.0, cost=0.02), _trade(-1.0, cost=0.04,
                                                           kind="stop")])
    assert stats["avg_cost_r"] == round((0.02 + 0.04) / 2.0, 6)
    assert md.trade_stats([_trade(1.0, cost=0.0)])["avg_cost_r"] == 0.0
    free = md.simulate_trades(_walk(), 140, cost_fraction=0.0)
    assert md.trade_stats(free)["avg_cost_r"] == 0.0


def test_ek_trade_par_sharpe_aur_sortino_None_hote_hain():
    """1 trade par risk ki naap "0 risk" nahi, "naap nahi" hoti hai."""
    stats = md.trade_stats([_trade(2.0)])
    assert stats["sharpe_r"] is None and stats["sortino_r"] is None
    assert md._stdev([1.0]) == 0.0


def test_teen_loss_class_naapi_hui_wajah_se_banti_hain_kahani_se_nahi():
    """Haar ki wajah trade ke number se nikalti hai, andaaze se nahi."""
    stops = _trade(-1.4, kind="stop")
    time_exit = _trade(-0.3, kind="time")
    cost_ate = _trade(-0.02, gross=0.01, cost=0.03, kind="time")
    win = _trade(1.9)
    assert stops.loss_class == md.LOSS_STOPPED
    assert time_exit.loss_class == md.LOSS_TIME_EXIT
    assert cost_ate.loss_class == md.LOSS_COST_ONLY
    assert win.loss_class == ""
    stats = md.trade_stats([stops, time_exit, cost_ate, win])
    assert stats["loss_classes"] == {md.LOSS_STOPPED: 1, md.LOSS_TIME_EXIT: 1,
                                     md.LOSS_COST_ONLY: 1}
    assert sum(stats["exit_kinds"].values()) == stats["n_trades"] == 4


# ══ 4. TradeSim — teesri haalat aur ASLI wajah ══════════════════════════════
def _row(r_multiple, expectancy, pf, measured=True, n=20):
    """Haath se bani ek R-setting row — `FRAGILE_EDGE` sirf isi tarah banta hai."""
    row = dict(md.trade_stats([_trade(1.0)]))
    row.update({"r_multiple": float(r_multiple), "measured": bool(measured),
                "reason": "", "n_trades": n, "expectancy_r": expectancy,
                "profit_factor": pf})
    return row


def test_series_hi_na_ho_to_naap_nahi_hoti_aur_wajah_likhi_jaati_hai():
    sim = md.trade_expectancy(None)
    assert sim.ok is False and sim.reason_code == md.NO_SERIES
    assert sim.rows == () and sim.best is None
    assert sim.edge_after_cost is None            # False nahi — faisla hi nahi
    assert sim.robust_share is None               # 0.0 nahi
    assert sim.verdict_reason == md.FEW_TRADES


def test_flat_series_par_stop_ki_naap_hi_nahi_banti():
    """Ye wajah LAB se nahi milti (wahan flat-holdout pehle rok deta hai)."""
    sim = md.trade_expectancy(_series([100.0] * 40))
    assert sim.ok is False and sim.reason_code == md.NO_VOLATILITY
    assert sim.n_train > 0                       # split ho gaya tha, naap nahi hui
    assert sim.edge_after_cost is None


def test_chhote_sample_par_row_likhi_jaati_hai_par_number_bahar_nahi_jaata():
    """2 trade ki "expectancy" 200 trade waali jaisi dikhna hi dhokha hai."""
    sim = md.trade_expectancy(_series(_walk(60)))
    assert sim.reason_code == md.FEW_TRADES
    assert len(sim.rows) == len(md.TRADE_R_MULTIPLES)
    assert sim.usable == 0 and sim.positive == 0
    assert sim.robust_share is None
    for row in sim.rows:
        assert row["measured"] is False
        assert row["reason"] == md.FEW_TRADES
        assert row["n_trades"] < md.TRADE_MIN_TRADES
        for key in ("expectancy_r", "profit_factor", "sharpe_r", "sortino_r",
                    "win_rate"):
            assert row[key] is None, key
    assert sim.to_dict()["loss_side_measured"] is None


def test_ek_bhi_haar_na_hone_par_edge_ka_faisla_hota_hi_nahi():
    """Seedhi ramp: sab jeet. Ye "edge mil gaya" ka saboot NAHI hai."""
    sim = md.trade_expectancy(_series(_ramp()))
    assert sim.ok is True
    assert sim.reason_code == md.NO_LOSS_TO_MEASURE
    assert sim.usable > 0
    assert (sim.best or {})["profit_factor"] is None
    assert sim.edge_after_cost is None            # teesri haalat
    assert sim.to_dict()["loss_side_measured"] is False


def test_cost_ke_baad_expectancy_positive_na_ho_to_wajah_wahi_likhti_hai():
    sim = md.trade_expectancy(_series(_walk(drift=0.0, seed=11)))
    assert sim.ok is True and sim.usable > 0
    assert sim.reason_code == md.NO_EDGE_AFTER_COST
    assert sim.edge_after_cost is False           # naapa gaya, aur nahi mila


def test_edge_sirf_ek_magic_R_par_zinda_ho_to_wo_edge_nahi_ittefaq_hai():
    """Ye haalat kisi natural fixture se nahi aayi — isliye haath se bani hai."""
    rows = (_row(1.0, 0.4, 1.6), _row(1.5, -0.2, 0.8),
            _row(2.0, -0.3, 0.7), _row(3.0, -0.5, 0.5))
    sim = md.TradeSim(ok=True, n_train=140, n_test=60, rows=rows)
    assert sim.usable == 4 and sim.positive == 1
    assert sim.robust_share == 0.25 < sim.min_robust_share
    assert sim.verdict_reason == md.FRAGILE_EDGE
    assert sim.edge_after_cost is False
    strong = md.TradeSim(ok=True, rows=(_row(1.0, 0.4, 1.6), _row(1.5, 0.1, 1.1)))
    assert strong.verdict_reason == "" and strong.edge_after_cost is True
    # Thik chhat par (aadhi settings me edge) shart POORI hoti hai — `>` likh
    # dena isi haalat ko chup-chaap FAIL bana deta hai.
    half = md.TradeSim(ok=True, rows=(_row(1.0, 0.4, 1.6), _row(1.5, -0.2, 0.8)))
    assert half.robust_share == 0.5 == half.min_robust_share
    assert half.verdict_reason == "" and half.edge_after_cost is True


def test_thik_zero_expectancy_edge_nahi_manti_shart_strictly_greater_hai():
    """`>=` likh dena hi "bilkul barabar" ko edge bana deta hai."""
    sim = md.TradeSim(ok=True, rows=(_row(1.0, 0.0, 1.4), _row(1.5, -0.1, 0.9)))
    assert sim.reason_code == "" and sim.verdict_reason == md.NO_EDGE_AFTER_COST
    assert sim.edge_after_cost is False
    flat_pf = md.TradeSim(ok=True, rows=(_row(1.0, 0.3, 1.0),))
    assert flat_pf.verdict_reason == md.NO_EDGE_AFTER_COST
    assert flat_pf.edge_after_cost is False      # profit factor THIK 1.0 par
    assert md.TRADE_MIN_EXPECTANCY_R == 0.0 and md.TRADE_MIN_PROFIT_FACTOR == 1.0


def test_best_sirf_naapi_hui_row_me_se_chunta_hai():
    rows = (_row(1.0, 0.1, 1.2), _row(1.5, None, None, measured=False, n=3),
            _row(2.0, 0.9, 1.9))
    sim = md.TradeSim(ok=True, rows=rows)
    assert sim.usable == 2
    assert (sim.best or {})["r_multiple"] == 2.0
    # Hissa sirf NAAPI HUI settings ka hota hai. Denominator me poori rows le
    # lena robust_share ko chup-chaap patla kar deta hai (2/3 vs 2/2).
    assert sim.positive == 2 and sim.robust_share == 1.0
    assert md.TradeSim(ok=True, rows=(_row(1.0, None, None, measured=False),)).best is None


def test_to_dict_har_baar_chaar_seema_aur_do_imaandaar_jhande_leke_jaata_hai():
    out = md.trade_expectancy(_series(_walk())).to_dict()
    assert out["randomness_used"] is False       # deterministic sim
    assert out["is_established_fact"] is False   # backtest sach nahi banata
    assert out["min_series_points_for_this_test"] == md.TRADE_MIN_SERIES_POINTS
    assert out["close_only_limit"] == md.CLOSE_ONLY_NOTE
    assert out["cost_applied"] == md.TRADE_COST_NOTE
    assert out["past_data_only"] == md.BACKTEST_NOTE
    assert out["not_financial_advice"] == md.NOT_ADVICE_NOTE
    assert out["chosen_r_multiple"] in md.TRADE_R_MULTIPLES
    assert out["loss_side_measured"] is True


# ══ 5. CHHAT — kitna data kaafi hai, ye ek hi jagah tay hota hai ════════════
def test_trade_ke_liye_zaroori_series_ki_lambai_nikaali_gayi_hai_likhi_nahi():
    """133 haath se likha number nahi — 8 trade × 5 bar / held-out hissa hai."""
    expected = int(round(md.TRADE_MIN_TRADES * md.TRADE_MAX_BARS
                         / (1.0 - md.TRAIN_FRACTION)))
    assert md.TRADE_MIN_SERIES_POINTS == expected == 133
    assert md.TRADE_MIN_SERIES_POINTS > md.MIN_SERIES_POINTS


def test_lab_ki_chhat_market_data_se_mirror_hoti_hai_do_jagah_do_value_nahi():
    """Do jagah likhi hui chhat chupke se alag ho jaati hai — phir pata hi nahi
    chalta report kis shart par tiki thi."""
    policy = lab.LabPolicy()
    assert policy.trade_min_trades == md.TRADE_MIN_TRADES
    assert policy.trade_r_multiples == md.TRADE_R_MULTIPLES
    assert policy.trade_stop_units == md.TRADE_STOP_UNITS
    assert policy.trade_max_bars == md.TRADE_MAX_BARS
    assert policy.trade_cost_fraction == md.TRADE_COST_FRACTION
    assert policy.trade_min_robust_share == md.TRADE_MIN_ROBUST_SHARE


# ══ 6. LAB WIRING — nauvi spec chup-chaap na gire ═══════════════════════════
def test_nauvi_spec_banti_hai_aur_cap_use_nahi_kaat_sakti():
    """`add()` cap par CHUP-CHAAP rukta hai — isliye cap ko naapa jaata hai."""
    specs = lab.plan_specs(_hyp(), _Pack(_Src("S1", _meta(_walk()))),
                           lab.LabPolicy(), "cpi forecast")
    recipes = [spec.recipe for spec in specs]
    assert recipes == ["walk_forward", "monte_carlo", "parameter_robustness",
                       "baseline_tournament", "trade_expectancy"]
    assert lab.LabPolicy().max_specs_per_hypothesis >= len(recipes)


def test_series_na_ho_to_trade_spec_banti_hi_nahi():
    specs = lab.plan_specs(_hyp(), _Pack(_Src("S1")), lab.LabPolicy(),
                           "cpi forecast")
    assert "trade_expectancy" not in [spec.recipe for spec in specs]


def test_pass_aur_fail_dono_par_27_naapa_hua_number_bahar_jaata_hai():
    """Number `numbers` me hi jaate hain — `observed` line se nahi nikaale jaate."""
    for values, status in ((_walk(), "TESTED_PASS"),
                           (_walk(drift=0.0, seed=11), "TESTED_FAIL")):
        row = _trade_test(_run(values))
        assert row["status"] == status, values[:1]
        numbers = row["numbers"]
        assert len(numbers) == 27
        assert numbers["close_only"] is True
        assert numbers["edge_after_cost"] is (status == "TESTED_PASS")
        assert numbers["n_trades"] >= md.TRADE_MIN_TRADES
        assert numbers["avg_cost_r"] > 0            # cost sach me lagi thi
        assert numbers["cost_fraction"] == md.TRADE_COST_FRACTION
        assert numbers["stop_units"] == md.TRADE_STOP_UNITS
        assert numbers["max_bars"] == md.TRADE_MAX_BARS
        assert numbers["r_settings_tried"] == len(md.TRADE_R_MULTIPLES)


def test_teeno_naap_nahi_hui_haalat_DATA_MISSING_hain_aur_number_nahi_dete():
    """"Naap nahi hui" ko FAIL likhna hypothesis par jhootha ilzaam hai."""
    for values, reason in ((_ramp(), md.NO_LOSS_TO_MEASURE),
                           ([100.0] * 200, "no_net_move_in_holdout"),
                           (_walk(60), md.FEW_TRADES)):
        report = _run(values)
        row = _trade_test(report)
        assert row["status"] == "DATA_MISSING", reason
        assert row["reason_code"] == reason
        assert not row.get("numbers")
        assert lab._ran_count(report, "trade_expectancy") == 0


def test_chalne_par_hi_trade_wali_seema_line_aati_hai_aur_ek_hi_baar():
    ran = lab.lab_limits(_run(_walk()))
    lines = [line for line in ran if "trade-level expectancy test" in line]
    assert len(lines) == 1
    assert md.CLOSE_ONLY_NOTE in lines[0]
    assert "edge mil gaya" in lines[0]
    assert len(ran) <= lab.MAX_AUDIT_LIMIT_LINES
    not_ran = lab.lab_limits(_run([100.0] * 200))
    assert not [line for line in not_ran if "trade-level expectancy test" in line]


def test_detail_me_chaaron_seema_saath_jaati_hain():
    """Ek bhi note kat jaaye to pass hona "paisa banega" padha jaayega."""
    for values in (_walk(), _walk(drift=0.0, seed=11), _ramp()):
        detail = _trade_test(_run(values))["detail"]
        for note in (md.CLOSE_ONLY_NOTE, md.TRADE_COST_NOTE, md.BACKTEST_NOTE,
                     md.NOT_ADVICE_NOTE):
            assert note in detail


# ══ 7. trademodel ke reader — number kahan se aate hain ═════════════════════
_NUMBERS = {"r_multiple": 2.0, "n_trades": 14, "win_rate": 0.7857,
            "expectancy_r": 1.2833, "profit_factor": 5.354, "sharpe_r": 0.9,
            "sortino_r": 1.2, "avg_win_r": 1.9, "avg_loss_r": -1.0,
            "max_drawdown_r": 1.9098, "tail_loss_r": -1.4447,
            "mae_median_r": 0.3454, "mae_p95_r": 1.4077, "avg_cost_r": 0.0373,
            "cost_fraction": 0.0004, "stop_units": 1.5, "max_bars": 5,
            "loss_classes": {"stopped_out": 2, "time_exit_negative": 1},
            "exit_kinds": {"time": 9, "stop": 2, "target": 3},
            "r_settings_tried": 4, "r_settings_measured": 4,
            "r_settings_positive": 4, "robust_share": 1.0, "n_train": 140,
            "n_test": 60, "edge_after_cost": True, "close_only": True}

_SPEC = """US100 scalping model.
Costs: spread 0.8 point, commission 2 USD per round turn, slippage 0.5 point.
Stop loss research: MAE distribution measured, p95 = 0.7R.
Take profit research: 1R, 2R, 3R compared on expectancy = +0.31R.
Performance: win rate 54%, average win 1.9R, average loss -1.0R, expectancy
0.31R, profit factor 1.6, sharpe 0.9, sortino 1.2, max drawdown 6.4R,
tail loss -2.1R, risk of ruin 3%.
Failure classification: 14 losses were stopped out, 6 were time exits.
"""


def _nums(**over):
    out = dict(_NUMBERS)
    out.update(over)
    return out


def _report(numbers=None, status="TESTED_PASS", recipe=tm.LAB_RECIPE_TRADE,
            mc=True):
    """LAB report ka sirf wahi hissa jo trademodel padhta hai."""
    tests = [{"recipe": recipe, "status": status,
              "numbers": (_nums() if numbers is None else numbers)}]
    if mc:
        tests.append({"recipe": tm.LAB_RECIPE_MONTE_CARLO,
                      "status": "TESTED_PASS"})
    return {"hypotheses": [{"tests": tests}]}


def _points(report, spec=_SPEC):
    res = tm.measure(spec=spec, lab_report=report)
    return {row["point_id"]: row for row in res["checks"]}


def test_jo_test_chala_hi_nahi_uske_number_padhe_hi_nahi_jaate():
    """DATA_MISSING row me number ho bhi (nahi hote) to bhi wo naap nahi hai."""
    assert tm.lab_numbers(_report(status="DATA_MISSING"), tm.LAB_RECIPE_TRADE) == []
    assert tm.lab_numbers(_report(status="NOT_RUN"), tm.LAB_RECIPE_TRADE) == []
    assert tm.lab_numbers(_report(status="TESTED_FAIL"), tm.LAB_RECIPE_TRADE)
    assert tm.LAB_RAN_STATUSES == ("TESTED_PASS", "TESTED_FAIL")


def test_dusri_recipe_ke_number_trade_ke_naap_nahi_ban_sakte():
    assert tm.lab_trade_numbers(_report(recipe="walk_forward")) is None
    assert tm.lab_trade_numbers(_report(recipe="monte_carlo")) is None
    assert tm.lab_trade_numbers(_report()) is not None


def test_khaali_ya_galat_shape_wale_numbers_chup_chaap_naap_nahi_bante():
    assert tm.lab_numbers(_report(numbers={}), tm.LAB_RECIPE_TRADE) == []
    assert tm.lab_numbers(_report(numbers="nope"), tm.LAB_RECIPE_TRADE) == []
    assert tm.lab_numbers(_report(numbers=None), tm.LAB_RECIPE_TRADE)
    assert tm.lab_trade_numbers(None) is None
    assert tm.lab_trade_numbers({}) is None


def test_sabse_bade_sample_wali_naap_chunti_hai_chhoti_nahi():
    """Chhota sample chun lena hi backtest ka sabse aasan dhokha hai."""
    report = _report(numbers=_nums(n_trades=5, expectancy_r=0.1))
    report["hypotheses"].append({"tests": [
        {"recipe": tm.LAB_RECIPE_TRADE, "status": "TESTED_FAIL",
         "numbers": _nums(n_trades=40, expectancy_r=-0.2)}]})
    picked = tm.lab_trade_numbers(report)
    assert picked["n_trades"] == 40      # FAIL wali bhi, kyunki wo BADI hai


def test_barabar_sample_par_behtar_expectancy_wali_naap_chunti_hai():
    report = _report(numbers=_nums(n_trades=9, expectancy_r=0.1))
    report["hypotheses"].append({"tests": [
        {"recipe": tm.LAB_RECIPE_TRADE, "status": "TESTED_PASS",
         "numbers": _nums(n_trades=9, expectancy_r=0.9)}]})
    assert tm.lab_trade_numbers(report)["expectancy_r"] == 0.9


# ══ 8. PAANCH POINT — naap text par BHAARI hai ══════════════════════════════
_FIVE = ("performance_metrics", "stop_loss_research", "take_profit_research",
         "realistic_costs", "failure_classification")


def test_naap_chalne_par_paanchon_point_LAB_ke_number_se_MET_hote_hain():
    """Har MET par nishaan hona zaroori hai — warna text aur naap ek lagte hain."""
    rows = _points(_report())
    for pid in _FIVE:
        assert rows[pid]["status"] == tm.MET, pid
        assert tm._LAB_MEASURED in rows[pid]["observed"], pid
    assert "9/9 metric NAAPA gaya" in rows["performance_metrics"]["observed"]
    assert "14 trade" in rows["stop_loss_research"]["observed"]   # sample bhi
    assert "sirf CLOSE price par" in rows["take_profit_research"]["observed"]


def test_monte_carlo_na_chala_ho_to_naau_me_se_aath_naap_MET_nahi_hoti():
    """Risk-of-ruin ek alag test se aata hai — usko maan lena adhoora naap hai."""
    row = _points(_report(mc=False))["performance_metrics"]
    assert row["status"] == tm.NOT_MET
    assert "8/9 metric" in row["observed"]
    assert "risk_of_ruin" in row["reason"]
    assert tm._LAB_MEASURED not in row["observed"]


def test_koi_ek_metric_None_ho_to_bhi_adhoora_naap_poora_nahi_hota():
    row = _points(_report(numbers=_nums(profit_factor=None)))["performance_metrics"]
    assert row["status"] == tm.NOT_MET
    assert "8/9 metric" in row["observed"]
    assert "profit_factor" in row["reason"]


def test_95_percent_win_rate_ka_daawa_9_of_9_naap_ke_baad_bhi_FAIL_hai():
    """intel ka niyam: win rate ke peechhe nahi bhaagna — naap bhi ise nahi bachati."""
    rows = _points(_report(), _SPEC + "\nWe target a 95% win rate.")
    row = rows["performance_metrics"]
    assert row["status"] == tm.NOT_MET
    assert "9/9 metric" in row["observed"]        # naap poori thi, phir bhi FAIL
    assert "95" in row["observed"]
    assert tm.chased_win_rate("Target: 95% win rate.")
    assert not tm.chased_win_rate("Win rate 54% nikli.")


def test_MAE_bina_stop_ka_faisla_sirf_andaaza_hai():
    for gone in ("mae_p95_r", "mae_median_r"):
        row = _points(_report(numbers=_nums(**{gone: None})))["stop_loss_research"]
        assert row["status"] == tm.NOT_MET, gone
        assert "MAE nahi bana" in row["observed"]


def test_ek_hi_R_setting_se_ye_target_behtar_hai_nahi_kaha_ja_sakta():
    row = _points(_report(numbers=_nums(r_settings_measured=1)))
    assert row["take_profit_research"]["status"] == tm.NOT_MET
    assert "1 R-setting" in row["take_profit_research"]["observed"]
    ok = _points(_report(numbers=_nums(r_settings_measured=2)))
    assert ok["take_profit_research"]["status"] == tm.MET
    # Do setting tul bhi jaayein par expectancy naapi hi na gayi ho, to "ye
    # target behtar hai" phir bhi nahi kaha ja sakta — tulna hoti hai NET
    # expectancy PAR, aur wo number is sample me bana hi nahi.
    blind = _points(_report(numbers=_nums(expectancy_r=None)))
    assert blind["take_profit_research"]["status"] == tm.NOT_MET


def test_trade_chale_par_haar_class_me_na_jaaye_to_wajah_nahi_bani():
    row = _points(_report(numbers=_nums(loss_classes={})))["failure_classification"]
    assert row["status"] == tm.NOT_MET
    assert "0 haar classify hui" in row["observed"]


def test_cost_LAGI_HI_NAHI_par_realistic_costs_MET_nahi_ho_sakti():
    """`avg_cost_r == 0` = cost lagi hi nahi — likhi hui cost naap nahi hoti."""
    row = _points(_report(numbers=_nums(avg_cost_r=0.0)))["realistic_costs"]
    assert row["status"] == tm.NOT_MET
    assert "0R cost" in row["observed"]
    assert "LAGI HI NAHI" in row["reason"]


def test_cost_lagi_par_spec_me_zikr_patla_ho_to_bhi_MET_nahi():
    """Lump round-turn number me latency aur news-slippage naapi hi nahi gayi."""
    row = _points(_report(), "US100 model.")["realistic_costs"]
    assert row["status"] == tm.NOT_MET
    assert "aausat 0.0373R cost lagayi" in row["observed"]
    assert "latency" in row["reason"] and "news-slippage" in row["reason"]


def test_LAB_ka_test_na_chale_to_paanchon_point_BILKUL_purane_nateeje_dete_hain():
    """`jo phle bna h unko htana mt` — teen alag raaste, ek hi purana nateeja."""
    baseline = _points(None)
    same = (_points(_report(status="DATA_MISSING")),
            _points(_report(status="NOT_RUN")),
            _points(_report(recipe="walk_forward")),
            _points(_report(numbers={})))
    for rows in same:
        for pid in _FIVE:
            assert rows[pid]["status"] == baseline[pid]["status"], pid
            assert rows[pid]["observed"] == baseline[pid]["observed"], pid
            assert rows[pid]["reason"] == baseline[pid]["reason"], pid
    assert baseline["performance_metrics"]["observed"] == "9/9 metric"
    assert baseline["realistic_costs"]["status"] == tm.MET
    for pid in _FIVE:
        assert tm._LAB_MEASURED not in baseline[pid]["observed"], pid


# ══ 9. NON-NEGOTIABLE — determinism, aur `observed` se faisla kabhi nahi ════
def _code(func):
    """Function ka code bina docstring aur bina comment — sirf ASLI rasta."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    node = tree.body[0]
    body = node.body[1:] if ast.get_docstring(node) else node.body
    return "\n".join(ast.unparse(part) for part in body)


def test_wahi_series_do_baar_wahi_nateeja_deti_hai():
    """Randomness ghus jaaye to har run ka jawab badal jaayega — aur pata na chalega."""
    values = _walk()
    assert md.simulate_trades(values, 140) == md.simulate_trades(values, 140)
    first = md.trade_expectancy(_series(values))
    second = md.trade_expectancy(_series(values))
    assert first.rows == second.rows and first.reason_code == second.reason_code
    assert first.to_dict() == second.to_dict()
    assert _trade_test(_run(values))["numbers"] == _trade_test(_run(values))["numbers"]


def test_trade_ka_koi_hissa_random_use_nahi_karta():
    """`randomness_used: False` likhna aasan hai — ye us daawe ka naap hai."""
    for func in (md.simulate_trades, md.trade_stats, md._past_move_unit,
                 md._drift_direction, md._percentile):
        assert "random" not in _code(func), func.__name__
    assert md.trade_expectancy(_series(_walk())).to_dict()["randomness_used"] is False


def test_faisla_kabhi_insaan_ke_padhne_wali_line_se_nahi_hota():
    """`observed` ko wapas parse karna "derive, never declare" ka ulta rasta hai."""
    source = _src("research_engine/trademodel.py")
    for banned in ('numbers.get("observed")', 'numbers["observed"]',
                   'test.get("observed")', 'test["observed"]',
                   "numbers.get('observed')", "numbers['observed']"):
        assert banned not in source, banned
    assert "observed" not in _code(tm.lab_numbers)
    assert "observed" not in _code(tm.lab_trade_numbers)
    for func in (tm._perf_from_numbers, tm._stop_from_numbers,
                 tm._target_from_numbers):
        code = _code(func)
        assert "numbers.get('observed')" not in code, func.__name__
        assert "numbers['observed']" not in code, func.__name__


def test_naapa_hua_number_sirf_chale_hue_test_ke_saath_bahar_jaata_hai():
    """LAB me `numbers=` sirf PASS aur FAIL par — DATA_MISSING par kabhi nahi."""
    source = _src("research_engine/lab.py")
    assert source.count("numbers=measured") == 2
    assert "trade_expectancy" in lab.RECIPES
    # Dono taraf ka naam ek hi hona chahiye — `trademodel` ka recipe naam LAB ke
    # recipe se alag ho jaaye to naap chup-chaap padhi hi nahi jaayegi.
    assert tm.LAB_RECIPE_TRADE in lab.RECIPES


def test_naau_metric_ki_ginti_do_recipe_se_banti_hai_ek_se_nahi():
    assert len(tm.METRIC_KEYS) == 9
    assert "risk_of_ruin" in tm.METRIC_KEYS
    ran, _passed = tm.lab_recipe_status(_report(), tm.LAB_RECIPE_MONTE_CARLO)
    assert ran == 1
    ran_none, _p = tm.lab_recipe_status(_report(mc=False), tm.LAB_RECIPE_MONTE_CARLO)
    assert ran_none == 0
