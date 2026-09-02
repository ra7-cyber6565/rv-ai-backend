"""#150e — backtest ke BAAD ke teen test: risk, region, aur muqabla.

Kyun ye batch bani: #118 ke baad "backtest chal gaya" ka matlab log ye samajh
lete hain ki model tradeable hai. Nahi hai. "Backtest pass" se teen ALAG sawaal
ka jawab nahi milta:

  1. kitna risk per trade zinda rehta hai (drawdown / losing streak / ruin),
  2. edge ek REGION me hai ya ek magic number par,
  3. model kisi SIMPLE baseline se behtar bhi hai ya nahi.

Is file ka har test ek NAAPA hua jhooth rokta hai:
  - "thousands of random simulations" — yahan resample DETERMINISTIC hai, path
    ki asli ginti report hoti hai, aur `randomness_used: False` sach rehta hai;
  - "risk per trade 1% rakho" — koi level chhaton ke andar na bache to koi
    number nahi diya jaata (aur jo numbers dikhte hain wo KISKE hain, ye alag
    likha jaata hai);
  - "edge mila" jab sirf ek setting jeeti ho;
  - "model jeet gaya" jab muqabla hi na hua ho, ya jab ek seedha baseline behtar
    nikla ho;
  - flat held-out par vacuous "haar" — jahan model jeet bhi nahi sakta, wahan
    FAIL likhna jhootha signal hai;
  - kisi bhi baseline me future value ka istemal (leakage).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import lab, market_data as md  # noqa: E402


# ── chhote helpers (koi network, koi randomness, koi provider) ────────────────
class _Src:
    """EvidencePack ka sirf wahi hissa jo lab/market_data padhte hain."""

    def __init__(self, source_id, series_meta=None, snippet=""):
        self.source_id = source_id
        self.series_meta = series_meta or {}
        self.title = ""
        self.snippet = snippet
        self.full_text = ""


class _Pack:
    def __init__(self, *sources):
        self.sources = list(sources)


def _meta(values, start=1980, provider="world_bank_series"):
    return {"provider": provider, "series_id": "X", "label": "test series",
            "frequency": "yearly", "unit": "%",
            "points": [[str(start + i), float(v)] for i, v in enumerate(values)]}


def _series(values, start=1980):
    points = [md.SeriesPoint(period=str(start + i), order=(start + i) * 12,
                             value=float(v), unit="%")
              for i, v in enumerate(values)]
    return md.MarketSeries(points=points, frequency="yearly", unit="%",
                           provider="test_provider", series_id="X",
                           label="test series", source_ids=["S1"], note="")


def _hyp(hid="RV-HYP-1",
         statement="Backtest: next year value badhega, forecast 12 %."):
    return {"hypothesis_id": hid, "statement": statement}


def _run(values, hid="RV-HYP-1", policy=None):
    """Poora LAB chalao (bina network) aur report lauta do."""
    return lab.run_lab("cpi forecast", [_hyp(hid)],
                       pack=_Pack(_Src("S1", _meta(values))), policy=policy)


def _test(report, recipe, index=0):
    rows = [t for t in report["hypotheses"][index]["tests"]
            if t["recipe"] == recipe]
    assert rows, f"{recipe} spec hi nahi bani"
    return rows[0]


# ── test data. Har series ek ALAG asli nateeja deti hai (stub nahi) ───────────
def _linear(n=46, step=3.0, base=100.0):
    """Bilkul seedhi line — steps ek jaise, isliye resample me path hi kam."""
    return [base + step * i for i in range(n)]


def _sawtooth(n=46):
    """Har 7 par gir jaati hai — koi risk level chhat ke andar nahi bachta."""
    return [100 + (i % 7) * 5 for i in range(n)]


def _short(n=14):
    """Held-out 4 — Monte Carlo ke liye kaafi NAHI, sweep ke liye kaafi hai."""
    return [100 + 3 * i + (2 if i % 2 else 0) for i in range(n)]


# Ek asli series jispar drift model SAARE paanch baseline ko haraata hai.
# Ye haath se nahi chuni gayi: increments ek likhe hue LCG se bane, aur pehli
# series jo tournament jeeti wahi yahan pin ki gayi hai (level line se hat kar
# ghoomti hai, isliye linear_trend haar jaata hai).
_MODEL_WINS = [
    100.0, 107.32, 112.93, 115.95, 118.9, 122.7, 130.59, 137.49, 143.68,
    149.4, 155.09, 162.47, 167.7, 168.74, 175.63, 180.37, 187.44, 193.72,
    200.37, 201.91, 204.7, 211.06, 215.75, 223.41, 224.44, 226.8, 230.09,
    236.87, 242.26, 243.54, 249.95, 254.05, 260.0, 266.64, 268.41, 272.47,
    273.9, 276.78, 277.87, 282.85, 284.2, 289.08, 294.41, 301.11, 303.94,
    307.26,
]

_STEPS14 = [1.0, -2.0, 3.0, 0.5, -1.5, 4.0, 2.5, -3.0, 1.25, 0.75,
            -0.5, 5.0, -4.0, 2.0]


def _sawtooth_steps():
    """Sawtooth series ke asli step (diff) — bade uphaar aur bade girawat."""
    values = _sawtooth()
    return [values[i + 1] - values[i] for i in range(len(values) - 1)]


# ══ GROUP 1 ── resample DETERMINISTIC hai, aur path ki ginti ASLI hai ═════════
def test_resampled_paths_are_the_same_every_single_call():
    """Do baar bulao to bit-identical. Yehi `randomness_used: False` ka aadhaar."""
    first = md.mc_paths(_STEPS14)
    second = md.mc_paths(_STEPS14)
    assert first == second
    assert first, "14 step par path banne hi chahiye"


def test_every_resampled_path_keeps_the_original_length():
    for path in md.mc_paths(_STEPS14):
        assert len(path) == len(_STEPS14)


def test_resampling_never_invents_a_number_that_was_not_in_the_history():
    """Block-resample sirf PURANE steps ko dubara jodta hai, naye nahi banata."""
    seen = set()
    for path in md.mc_paths(_STEPS14):
        seen.update(path)
    assert seen <= set(_STEPS14)


def test_the_paths_are_all_different_from_each_other():
    paths = md.mc_paths(_STEPS14)
    assert len(set(paths)) == len(paths), "duplicate path ginti ko phula dega"


def test_every_path_has_its_mirror_image_in_the_set():
    """Reversal ek asli variation hai: har path ka ulta kram bhi maujood ho.

    Ye naap ke liye zaroori hai — agar reversal chup-chaap hat jaaye to path ki
    ginti aadhi ho jaayegi aur "kitne raaste dekhe" ka number jhootha ho jaayega.
    """
    paths = set(md.mc_paths(_STEPS14))
    assert paths
    missing = [p for p in paths if tuple(reversed(p)) not in paths]
    assert not missing, f"{len(missing)} path ka ulta kram gayab hai"
    assert any(tuple(reversed(p)) != p for p in paths), "sab palindrome nahi ho sakte"


def test_the_path_ceiling_is_actually_obeyed():
    assert len(md.mc_paths(_STEPS14, max_paths=5)) == 5


def test_a_block_longer_than_the_history_still_produces_paths():
    """block=50 par bhi rotation+reversal se path bante hain (crash nahi)."""
    paths = md.mc_paths(_STEPS14, block_lengths=(50,))
    assert paths
    assert all(len(p) == len(_STEPS14) for p in paths)


def test_no_steps_means_no_paths():
    assert md.mc_paths([]) == []


def test_a_single_step_gives_exactly_one_path():
    assert md.mc_paths([2.0]) == [(2.0,)]


def test_a_flat_history_can_only_produce_one_path():
    """Isliye FEW_PATHS wali shikayat imaandaar hai — variation hi nahi hai."""
    assert len(md.mc_paths([3.0] * 14)) == 1


# ══ GROUP 2 ── ek path ka nateeja: drawdown, streak, ruin ════════════════════
def test_a_path_that_never_moves_leaves_the_account_untouched():
    m = md.path_metrics([0.0] * 5, 1.0, 0.01)
    assert (m.ending_equity, m.max_drawdown, m.worst_streak, m.ruined) == \
        (1.0, 0.0, 0, False)


def test_drawdown_is_measured_from_the_peak_not_from_the_start():
    """[-1,-1,+2,-1] par 10% risk: peak ke baad ki girawat hi drawdown hai."""
    m = md.path_metrics([-1.0, -1.0, 2.0, -1.0], 1.0, 0.1)
    assert round(m.ending_equity, 4) == 0.8748
    assert round(m.max_drawdown, 4) == 0.19
    assert m.worst_streak == 2, "lagataar do haar hi sabse lambi lakeer hai"
    assert m.ruined is False


def test_drawdown_after_a_new_peak_is_measured_from_that_peak():
    """Pehle upar jao, phir giro — girawat NAYE peak se naapi jaati hai.

    Ye test upar wale se ALAG hai: wahan equity kabhi 1.0 se upar nahi gayi,
    isliye "peak se" aur "shuruaat se" dono ka jawab wahi aata tha. Yahan equity
    1.3 tak jaati hai, to shuruaat se naapne par drawdown 0 dikhta — yaani ek
    asli girawat chhup jaati.
    """
    m = md.path_metrics([3.0, -1.0, -1.0], 1.0, 0.1)
    assert round(m.ending_equity, 4) == 1.053
    assert round(m.max_drawdown, 4) == 0.19
    assert m.ruined is False


def test_a_long_losing_run_is_reported_as_ruin():
    m = md.path_metrics([-1.0] * 20, 1.0, 0.5)
    assert m.ruined is True
    assert m.worst_streak == 20
    assert m.max_drawdown > 0.99
    assert m.ending_equity < 0.001


def test_bigger_risk_hurts_more_on_the_very_same_path():
    """Ladder ka matlab yehi hai: risk badhao to drawdown badhta hai."""
    path = [-1.0, -1.0, 1.0, -1.0, 1.0]
    small = md.path_metrics(path, 1.0, 0.005)
    big = md.path_metrics(path, 1.0, 0.05)
    assert big.max_drawdown > small.max_drawdown
    assert big.ending_equity < small.ending_equity


def test_the_losing_streak_does_not_depend_on_risk_size():
    path = [-1.0, -1.0, 1.0, -1.0]
    assert md.path_metrics(path, 1.0, 0.005).worst_streak == \
        md.path_metrics(path, 1.0, 0.05).worst_streak == 2


# ══ GROUP 3 ── monte_carlo: kabhi "thousands of random simulations" nahi ═════
def _mc(steps=None):
    return md.monte_carlo(steps if steps is not None else _STEPS14,
                          md.MC_RISK_LADDER, md.MC_MIN_STEPS, md.MC_MIN_PATHS,
                          md.MC_MAX_P95_DRAWDOWN, md.MC_MAX_RUIN_PROB)


def test_monte_carlo_never_claims_randomness():
    """Sabse bada jhooth jo yahan structurally band hai."""
    out = _mc().to_dict()
    assert out["randomness_used"] is False
    assert "random draw nahi" in out["method"]


def test_the_reported_path_count_is_the_real_one():
    """168 = jitne path SACH ME bane. Round figure "10,000" kabhi nahi."""
    out = _mc().to_dict()
    assert out["n_paths"] == len(md.mc_paths(_STEPS14))
    assert out["n_steps"] == len(_STEPS14)


def test_monte_carlo_output_is_bit_identical_across_calls():
    assert _mc().to_dict() == _mc().to_dict()


def test_a_history_that_never_moved_is_refused_by_name():
    out = _mc([0.0] * 14)
    assert out.ok is False
    assert out.reason_code == md.NO_STEP_MOVED


def test_too_short_a_history_is_refused_by_name():
    out = _mc([1.0] * 5)
    assert out.ok is False
    assert out.reason_code == md.FEW_STEPS


def test_too_little_variation_is_refused_by_name():
    """Steps sab barabar: ek hi path banta hai, isliye simulation bemaani hai."""
    out = _mc([3.0] * 14)
    assert out.ok is False
    assert out.reason_code == md.FEW_PATHS
    assert out.n_paths == 1


def test_a_refused_monte_carlo_hands_out_no_risk_number():
    out = _mc([0.0] * 14).to_dict()
    assert out["risk_per_trade"] is None
    assert out["p95_drawdown"] is None
    assert out["ruin_probability"] is None


def test_the_whole_risk_ladder_is_reported_not_just_the_winner():
    """User ko dikhna chahiye ki 6 level dekhe gaye, ek nahi."""
    rows = _mc().to_dict()["ladder"]
    assert [row["risk"] for row in rows] == list(md.MC_RISK_LADDER)
    for row in rows:
        assert set(row) >= {"risk", "p95_drawdown", "ruin_prob", "median_end",
                            "median_drawdown", "worst_streak", "acceptable"}


def test_drawdown_grows_as_you_move_up_the_ladder():
    rows = _mc().to_dict()["ladder"]
    dds = [row["p95_drawdown"] for row in rows]
    assert dds == sorted(dds), "risk badhe aur drawdown na badhe to ladder jhoothi hai"


def test_the_chosen_risk_is_a_level_that_actually_passed_the_ceilings():
    out = _mc()
    assert out.survived is True
    chosen = [row for row in out.rows if row["risk"] == out.risk_fraction]
    assert chosen and chosen[0]["acceptable"] is True
    assert chosen[0]["p95_drawdown"] <= md.MC_MAX_P95_DRAWDOWN
    assert chosen[0]["ruin_prob"] <= md.MC_MAX_RUIN_PROB


def test_the_printed_numbers_say_which_risk_level_they_belong_to():
    """`numbers_belong_to_risk` alag field hai — top-level numbers kiske hain."""
    out = _mc()
    assert out.reported_risk == out.risk_fraction
    assert out.p95_drawdown == \
        [r for r in out.rows if r["risk"] == out.reported_risk][0]["p95_drawdown"]


def test_when_no_level_survives_the_numbers_still_name_their_owner():
    """Yahi wo jagah hai jahan chup rehna jhooth ban jaata: risk None, par
    p95/ruin phir bhi KISI ke hote hain — sabse chhote risk ke."""
    out = md.monte_carlo(_sawtooth_steps(), md.MC_RISK_LADDER, md.MC_MIN_STEPS,
                         md.MC_MIN_PATHS, 0.0001, md.MC_MAX_RUIN_PROB)
    assert out.ok is True and out.survived is False
    assert out.risk_fraction is None
    assert out.reported_risk == md.MC_RISK_LADDER[0]
    assert out.reason_code == md.NO_SAFE_RISK
    assert out.p95_drawdown is not None


# ══ GROUP 4 ── parameter sweep: edge REGION me hai ya ek magic number par ════
def _sweep(values):
    return md.parameter_sweep(_series(values), md.SWEEP_LOOKBACKS,
                              md.MIN_SERIES_POINTS, md.MIN_HOLDOUT_POINTS,
                              md.TRAIN_FRACTION, md.SWEEP_MIN_SETTINGS,
                              md.SWEEP_MIN_BEAT_SHARE)


def test_no_series_means_no_sweep_verdict_at_all():
    out = md.parameter_sweep(None)
    assert out.ok is False
    assert out.reason_code == md.NO_SERIES
    assert out.region_ok is None, "faisla hi nahi ho sakta to True/False jhooth hai"
    assert out.share is None


def test_the_base_setting_is_measured_alongside_the_variants():
    """Pehli row `lookback: None` = aaj ka default. Uske bina tulna adhoori hai."""
    rows = _sweep(_short()).to_dict()["settings"]
    assert rows[0]["lookback"] is None
    assert rows[0]["ran"] is True
    assert rows[0]["model_mae"] == \
        round(md.walk_forward(_series(_short())).model_mae, 6)


def test_a_setting_that_cannot_run_is_written_down_not_dropped_silently():
    """14 point par train 10 hai, isliye lookback 12 chal hi nahi sakti."""
    rows = _sweep(_short()).to_dict()["settings"]
    outside = [r for r in rows if r["lookback"] == 12]
    assert outside and outside[0]["ran"] is False
    assert outside[0]["reason"] == "lookback_outside_train"
    assert outside[0]["beats_naive"] is None


def test_a_setting_that_could_not_run_is_not_counted_as_a_win_or_a_loss():
    out = _sweep(_short())
    assert out.usable == 6, "7 settings likhi gayi, 6 chali"
    assert len(out.rows) == 7
    assert out.share == 1.0 and out.region_ok is True
    assert out.best_lookback == 3


def test_an_edge_at_one_isolated_setting_is_not_a_region():
    """Sawtooth: 7 setting chali, sirf 1 ne naive ko haraya → region NAHI."""
    out = _sweep(_sawtooth())
    assert out.usable == 7 and out.beat == 1
    assert round(out.share, 6) == 0.142857
    assert out.region_ok is False


def test_a_flat_series_gives_no_usable_setting_and_no_verdict():
    out = _sweep([100.0] * 46)
    assert out.usable == 0
    assert out.reason_code == md.FEW_SETTINGS
    assert out.share is None and out.region_ok is None


def test_the_sweep_never_calls_itself_established_fact():
    out = _sweep(_short()).to_dict()
    assert out["is_established_fact"] is False
    assert out["past_data_only"] and out["not_financial_advice"]


# ══ GROUP 5 ── baseline tournament: model ko HAR seedhe model ko haraana hai ═
def test_all_five_baselines_are_actually_compared():
    out = md.baseline_tournament(_series(_MODEL_WINS))
    assert [row["baseline"] for row in out.rows] == list(md.BASELINE_NAMES)
    assert out.total == 5 and all(row["compared"] for row in out.rows)


def test_the_model_only_wins_when_it_beats_every_single_baseline():
    out = md.baseline_tournament(_series(_MODEL_WINS))
    assert out.beaten == 5 and out.total == 5
    assert out.beats_all is True and out.winner == "model"
    for row in out.rows:
        assert row["mae"] > round(out.model_mae, 6)


def test_a_simple_straight_line_beats_the_drift_model_and_that_is_reported():
    """Yahi wo imaandaari hai: seedhi line par `linear_trend` behtar hai."""
    out = md.baseline_tournament(_series(_linear()))
    assert out.beats_all is False
    assert out.winner == "linear_trend"
    assert out.beaten < out.total


def test_the_tournament_uses_the_same_split_for_model_and_baselines():
    wf = md.walk_forward(_series(_MODEL_WINS))
    out = md.baseline_tournament(_series(_MODEL_WINS))
    assert (out.n_train, out.n_test) == (wf.n_train, wf.n_test)
    assert round(out.model_mae, 6) == round(wf.model_mae, 6)


def test_no_series_means_no_tournament_verdict():
    out = md.baseline_tournament(None)
    assert out.ok is False and out.reason_code == md.NO_SERIES
    assert out.beats_all is None, "muqabla hua hi nahi to True/False dono jhooth"


def test_when_no_baseline_can_forecast_nothing_is_declared_won():
    """Har baseline ke liye None aaye to `beats_all` None rehna chahiye."""
    original = md._baseline_forecasts
    try:
        md._baseline_forecasts = lambda history: {
            name: None for name in md.BASELINE_NAMES}
        out = md.baseline_tournament(_series(_MODEL_WINS))
    finally:
        md._baseline_forecasts = original
    assert out.reason_code == md.NO_BASELINE
    assert out.total == 0 and out.beats_all is None
    assert all(row["compared"] is False for row in out.rows)


def test_the_tournament_says_out_loud_what_it_did_not_test():
    """ORB/VWAP/order-flow strategy yahan test NAHI hui — ye likha jaata hai."""
    out = md.baseline_tournament(_series(_MODEL_WINS)).to_dict()
    assert out["scope"] == md.BASELINE_SCOPE_NOTE
    assert "order-flow" in out["scope"] and "NAHI" in out["scope"]
    assert out["is_established_fact"] is False


# ══ GROUP 6 ── leakage: t ke baad ki koi value kisi forecast me nahi jaati ════
def test_a_baseline_forecast_only_ever_sees_the_past():
    """Do series jinka shuruaati hissa same hai, unka forecast same hoga —
    chahe aage kuch bhi ho. Agar future value andar aati to ye tootta."""
    head = _MODEL_WINS[:20]
    assert md._baseline_forecasts(head) == \
        md._baseline_forecasts(list(head))
    ahead = md._baseline_forecasts(head + [9999.0])
    assert ahead["naive_last"] == 9999.0, "sanity: naya point forecast badalta hai"


def test_changing_the_last_holdout_value_only_moves_the_last_step_error():
    """Leakage ka seedha naap: aakhri value badlo to sirf aakhri step ka error
    badalna chahiye. Koi bhi baseline future dekh raha hota to poori MAE hilti."""
    bumped = list(_MODEL_WINS)
    bumped[-1] = bumped[-1] + 100.0
    before = md.baseline_tournament(_series(_MODEL_WINS))
    after = md.baseline_tournament(_series(bumped))
    forecasts = md._baseline_forecasts(_MODEL_WINS[:-1])
    assert before.n_test == after.n_test == 14
    for old, new in zip(before.rows, after.rows):
        guess = forecasts[old["baseline"]]
        expected = (abs(guess - bumped[-1]) - abs(guess - _MODEL_WINS[-1])) \
            / before.n_test
        assert round(new["mae"] - old["mae"], 5) == round(expected, 5)


def test_the_first_baseline_forecast_comes_from_the_training_slice_only():
    out = md.baseline_tournament(_series(_MODEL_WINS))
    train_only = md._baseline_forecasts(_MODEL_WINS[:out.n_train])
    assert train_only["naive_last"] == _MODEL_WINS[out.n_train - 1]
    assert set(train_only) == set(md.BASELINE_NAMES)


def test_a_one_point_history_cannot_fake_the_baselines_that_need_more():
    """1 point par momentum / MA3 / trend banane ka dikhawa nahi hota."""
    out = md._baseline_forecasts([5.0])
    assert out["naive_last"] == 5.0
    assert out["mean_reversion_history"] == 5.0
    assert out["momentum_last_change"] is None
    assert out["moving_average_3"] is None
    assert out["linear_trend"] is None


def test_the_walk_forward_report_shape_did_not_grow_new_keys():
    """#118 ke report keys jaise the waise hain — purane test na tootein."""
    keys = set(md.walk_forward(_series(_MODEL_WINS)).to_dict())
    assert "steps" not in keys and "drift_lookback" not in keys
    assert "model_mae" in keys and "naive_mae" in keys


# ══ GROUP 7 ── LAB me teeno recipe asli me chalti hain ═══════════════════════
def test_a_forecast_claim_now_gets_all_four_market_tests():
    tests = _run(_MODEL_WINS)["hypotheses"][0]["tests"]
    recipes = [t["recipe"] for t in tests]
    for wanted in ("walk_forward", "monte_carlo", "parameter_robustness",
                   "baseline_tournament"):
        assert wanted in recipes, f"{wanted} spec hi nahi bani"


def test_all_four_pass_only_on_a_series_where_the_model_really_wins():
    report = _run(_MODEL_WINS)
    for recipe in ("walk_forward", "monte_carlo", "parameter_robustness",
                   "baseline_tournament"):
        assert _test(report, recipe)["status"] == lab.TESTED_PASS
    assert report["hypotheses"][0]["verdict"] == lab.TESTED_PASS


def test_passing_the_backtest_does_not_make_the_risk_test_pass():
    """Sawtooth: walk-forward PASS, par koi risk level chhat ke andar nahi bacha."""
    report = _run(_sawtooth())
    assert _test(report, "walk_forward")["status"] == lab.TESTED_PASS
    row = _test(report, "monte_carlo")
    assert row["status"] == lab.TESTED_FAIL
    assert row["reason_code"] == "no_risk_level_survived"


def test_passing_the_backtest_does_not_make_the_region_test_pass():
    report = _run(_sawtooth())
    row = _test(report, "parameter_robustness")
    assert row["status"] == lab.TESTED_FAIL
    assert row["reason_code"] == "edge_only_at_isolated_setting"
    assert "1 ne naive baseline ko haraya" in row["observed"]


def test_one_failing_market_test_sinks_the_whole_hypothesis():
    """Rollup me FAIL sabse aage hai — teen PASS ek FAIL ko dhak nahi sakte."""
    report = _run(_sawtooth())
    assert report["hypotheses"][0]["verdict"] == lab.TESTED_FAIL


def test_a_straight_line_is_beaten_by_a_simple_trend_and_says_so():
    report = _run(_linear())
    row = _test(report, "baseline_tournament")
    assert row["status"] == lab.TESTED_FAIL
    assert row["reason_code"] == "simpler_baseline_did_better"
    assert "jeeta: linear_trend" in row["observed"]


def test_the_risk_numbers_name_the_risk_level_they_belong_to():
    row = _test(_run(_sawtooth()), "monte_carlo")
    assert "risk 0.25% par" in row["observed"], "numbers kiske hain, ye likha ho"
    assert "ruin" in row["observed"] and "losing streak" in row["observed"]


def test_the_real_path_count_reaches_the_user_not_a_round_number():
    row = _test(_run(_MODEL_WINS), "monte_carlo")
    real = len(md.mc_paths(md.walk_forward(_series(_MODEL_WINS)).steps))
    assert f"{real} deterministic path" in row["observed"]
    assert "14 held-out step" in row["observed"]


def test_a_short_series_refuses_the_simulation_instead_of_faking_it():
    """14 point = held-out 4. Simulation ke liye 12 step chahiye — DATA_MISSING."""
    row = _test(_run(_short()), "monte_carlo")
    assert row["status"] == lab.DATA_MISSING
    assert row["reason_code"] == md.FEW_STEPS
    assert "%" not in row["observed"], "chala nahi to koi risk number nahi"


def test_a_short_series_can_still_run_the_parameter_region_test():
    """Ek recipe ka DATA_MISSING dusri ko band nahi karta."""
    row = _test(_run(_short()), "parameter_robustness")
    assert row["status"] == lab.TESTED_PASS
    assert "6 setting chali" in row["observed"]


def test_a_perfect_line_has_no_variation_to_simulate():
    row = _test(_run(_linear()), "monte_carlo")
    assert row["status"] == lab.DATA_MISSING
    assert row["reason_code"] == md.FEW_PATHS


def test_data_missing_tests_are_not_counted_as_tests_that_ran():
    """`_ran_count` sirf PASS/FAIL ginta hai. DATA_MISSING ko "test ho gaya"
    kehna wahi purana jhooth hai jise ye ginti rokti hai."""
    report = _run(_linear())
    statuses = {t["recipe"]: t["status"]
                for t in report["hypotheses"][0]["tests"]}
    assert statuses["monte_carlo"] == lab.DATA_MISSING
    assert lab._ran_count(report, "monte_carlo") == 0
    assert lab._ran_count(report, "parameter_robustness") == 1
    assert lab._ran_count(report, "baseline_tournament") == 1


def test_the_lab_spends_no_gemini_call_and_no_money_on_these_tests():
    report = _run(_MODEL_WINS)
    assert report["gemini_calls"] == 0
    assert report["provider_cost"] == 0.0


def test_the_whole_lab_report_is_identical_on_a_second_run():
    assert _run(_MODEL_WINS) == _run(_MODEL_WINS)


# ══ GROUP 8 ── flat held-out par chaaron chup: vacuous "haar" nahi ═══════════
def test_a_flat_holdout_blocks_all_four_tests_not_just_the_backtest():
    """Purana bug: yahan `baseline_tournament` TESTED_FAIL likh deta tha.

    Flat held-out par sab MAE 0 par barabar hote hain — model JEET hi nahi
    sakta. Wahan "simpler baseline did better" likhna naapa hua jhootha signal
    hai, isliye #118 ka flat-holdout gate ab chaaron recipe par lagta hai.
    """
    report = _run([100.0] * 46)
    for recipe in ("walk_forward", "monte_carlo", "parameter_robustness",
                   "baseline_tournament"):
        row = _test(report, recipe)
        assert row["status"] == lab.DATA_MISSING, recipe
        assert row["reason_code"] == md.FLAT_HOLDOUT, recipe


def test_a_flat_holdout_never_marks_the_hypothesis_failed():
    report = _run([100.0] * 46)
    assert report["hypotheses"][0]["verdict"] == lab.DATA_MISSING
    assert report["counts"][lab.TESTED_FAIL] == 0


def test_the_flat_holdout_block_is_the_walk_forward_verdict_being_reused():
    """Semantic aadhaar: `beats_naive is None` ⟺ naive ki galti 0 thi.

    `market_data` khud ise "chala hi nahi" nahi kehta (ok True hai) — muqabla
    hua hi nahi, ye faisla LAB me hota hai. Isliye teeno naye recipe ko sirf
    `ok` dekhna kaafi nahi tha; `beats_naive is None` bhi dekhna zaroori tha.
    """
    outcome = md.walk_forward(_series([100.0] * 46))
    assert outcome.ok is True
    assert outcome.beats_naive is None
    assert outcome.naive_mae == 0.0 and outcome.model_mae == 0.0


def test_a_flat_holdout_leaves_exactly_one_honest_audit_line():
    limits = lab.lab_limits(_run([100.0] * 46))
    assert len(limits) == 1
    assert "backtest-layak nahi nikli" in limits[0]
    assert md.FLAT_HOLDOUT in limits[0]


def test_the_helper_refuses_when_walk_forward_did_not_run_at_all():
    """Do alag wajah, dono par chup: (a) chala nahi, (b) held-out flat tha."""
    spec = lab.plan_specs(_hyp(), pack=_Pack(_Src("S1", _meta(_MODEL_WINS))))[0]
    dead = md.WalkForward(ok=False, reason_code=md.NO_SERIES)
    blocked = lab._outcome_blocked(spec, dead, "label", ["S1"])
    assert blocked is not None
    assert blocked.status == lab.DATA_MISSING
    assert blocked.reason_code == md.NO_SERIES


def test_the_helper_lets_a_usable_walk_forward_through():
    spec = lab.plan_specs(_hyp(), pack=_Pack(_Src("S1", _meta(_MODEL_WINS))))[0]
    good = md.walk_forward(_series(_MODEL_WINS))
    assert good.beats_naive is not None
    assert lab._outcome_blocked(spec, good, "label", ["S1"]) is None


# ══ GROUP 9 ── kaun-kaun test bane, aur audit me kya likha jaata hai ═════════
def test_a_claim_that_is_not_a_forecast_gets_none_of_these_tests():
    """Market recipe sirf forecast/backtest wale daawe par lagti hain."""
    specs = lab.plan_specs(
        {"hypothesis_id": "H", "statement": "Log khush rehte hain jab dhoop hoti hai."})
    assert [s.recipe for s in specs
            if s.recipe in ("monte_carlo", "parameter_robustness",
                            "baseline_tournament")] == []


def test_without_a_series_only_the_backtest_spec_is_planned():
    """Teeno naye test series ke bina banate hi nahi — dikhawa nahi hota."""
    specs = lab.plan_specs(_hyp())
    assert [s.recipe for s in specs] == ["walk_forward"]


def test_with_a_series_all_four_specs_are_planned():
    specs = lab.plan_specs(_hyp(), pack=_Pack(_Src("S1", _meta(_MODEL_WINS))))
    # #150g me paanchvi series-spec judi (`trade_expectancy`). Ye list poori
    # likhi jaati hai — sirf `in` se dekhne par ek spec chup-chaap gir sakti hai
    # aur test phir bhi green rehta.
    # #150i me teen aur judi: slot / regime / event window.
    assert [s.recipe for s in specs] == [
        "walk_forward", "monte_carlo", "parameter_robustness",
        "baseline_tournament", "trade_expectancy", "slot_expectancy",
        "regime_split", "event_window"]


def test_the_per_hypothesis_spec_cap_really_stops_the_planner():
    specs = lab.plan_specs(_hyp(), pack=_Pack(_Src("S1", _meta(_MODEL_WINS))),
                           policy=lab.LabPolicy(max_specs_per_hypothesis=2))
    assert len(specs) == 2
    assert [s.recipe for s in specs] == ["walk_forward", "monte_carlo"]


def test_each_test_that_ran_writes_its_own_audit_limit_line():
    limits = lab.lab_limits(_run(_MODEL_WINS))
    assert len(limits) == 5
    joined = "\n".join(limits)
    assert "Monte-Carlo" in joined and "block-resample" in joined
    assert "parameter-robustness sweep" in joined
    assert "baseline tournament" in joined


def test_the_monte_carlo_audit_line_denies_random_simulations_out_loud():
    limits = [line for line in lab.lab_limits(_run(_MODEL_WINS))
              if "Monte-Carlo" in line]
    assert len(limits) == 1
    assert "thousands of random simulations" in limits[0]


def test_a_test_that_did_not_run_writes_no_audit_line_for_itself():
    """Perfect line par MC chala nahi — uski line bhi nahi aani chahiye."""
    limits = lab.lab_limits(_run(_linear()))
    assert not any("Monte-Carlo" in line for line in limits)
    assert any("parameter-robustness sweep" in line for line in limits)
    assert len(limits) == 4


def test_the_audit_line_budget_still_has_room():
    """`MAX_AUDIT_LIMIT_LINES` ki chhat 5 lines ke baad bhi zinda hai."""
    assert len(lab.lab_limits(_run(_MODEL_WINS))) <= lab.MAX_AUDIT_LIMIT_LINES


def test_the_new_ceilings_are_declared_in_the_policy_not_hidden_in_code():
    policy = lab.LabPolicy().to_dict()
    assert policy["mc_min_steps"] == md.MC_MIN_STEPS
    assert policy["mc_min_paths"] == md.MC_MIN_PATHS
    assert policy["mc_max_p95_drawdown"] == md.MC_MAX_P95_DRAWDOWN
    assert policy["mc_max_ruin_prob"] == md.MC_MAX_RUIN_PROB
    assert policy["sweep_min_settings"] == md.SWEEP_MIN_SETTINGS
    assert policy["sweep_min_beat_share"] == md.SWEEP_MIN_BEAT_SHARE


def test_the_policy_still_swears_it_used_no_randomness():
    assert lab.LabPolicy().to_dict()["randomness_used"] is False


# ══ GROUP 10 ── 34-point contract: ye chaar point ab MET tak pahunch sakte hain
def _contract(lab_report=None):
    from research_engine import trademodel
    checks = trademodel.measure(spec="", lab_report=lab_report)["checks"]
    return {row["point_id"]: row for row in checks}


_LAB_POINTS = ("walk_forward_validation", "monte_carlo_risk",
               "parameter_robustness", "baseline_tournament")


def test_without_a_lab_report_these_four_points_stay_unmeasured():
    """Default MET kabhi nahi. "Test nahi chala" = NOT_MEASURED, "sab theek" nahi."""
    rows = _contract(None)
    for point in _LAB_POINTS:
        assert rows[point]["status"] == "NOT_MEASURED", point
        assert rows[point]["observed"] == "0 test chale"


def test_a_real_lab_pass_is_what_turns_these_four_points_met():
    rows = _contract(_run(_MODEL_WINS))
    for point in _LAB_POINTS:
        assert rows[point]["status"] == "MET", point
        assert rows[point]["observed"] == "1 test chale, 1 pass"


def test_a_lab_failure_is_never_dressed_up_as_met():
    """Sawtooth: risk aur region FAIL hue — contract me wahi dikhta hai."""
    rows = _contract(_run(_sawtooth()))
    assert rows["monte_carlo_risk"]["status"] == "NOT_MET"
    assert rows["parameter_robustness"]["status"] == "NOT_MET"
    assert rows["walk_forward_validation"]["status"] == "MET"
    assert "0 pass" in rows["monte_carlo_risk"]["observed"]


def test_a_flat_series_leaves_all_four_points_unmeasured_not_failed():
    """DATA_MISSING ko "naap ho gaya, fail" padhna sabse aasaan galti hai."""
    rows = _contract(_run([100.0] * 46))
    for point in _LAB_POINTS:
        assert rows[point]["status"] == "NOT_MEASURED", point


def test_the_order_flow_point_can_never_be_met_from_a_lab_run():
    """Keyless L2/footprint source nahi hai — ye point imaandaari se khaali hai."""
    rows = _contract(_run(_MODEL_WINS))
    assert rows["order_flow_edge"]["status"] in ("NOT_MEASURED", "NOT_MET")


# ══ GROUP 11 ── "test nahi chala" ki WAJAH bhi sach bole ═════════════════════
# #150e se pehle in teen point ki wajah likhi thi "ye recipe LAB me abhi nahi
# hai (#150e me aayegi)". Recipe ban jaane ke baad wahi line JHOOTH ho jaati:
# feature maujood hai, kami DATA ki hai. Ye group us purani line ko wapas aane
# se rokta hai.
_RECIPE_BUILT_POINTS = ("monte_carlo_risk", "parameter_robustness",
                        "baseline_tournament")


def test_a_test_that_did_not_run_never_blames_a_missing_feature():
    """Wajah "feature nahi bana" nahi bol sakti — teeno recipe ban chuke hain."""
    rows = _contract(None)
    for point in _RECIPE_BUILT_POINTS:
        reason = rows[point]["reason"].lower()
        assert "abhi nahi hai" not in reason, point
        assert "#150e me aayegi" not in reason, point
        assert "lab me" in reason and "hai par" in reason, point


def test_each_unrun_recipe_gives_its_own_data_reason_not_one_shared_line():
    """Teen point, teen alag wajah — ek copy-paste line teeno par nahi chipakti."""
    rows = _contract(None)
    reasons = {rows[point]["reason"] for point in _RECIPE_BUILT_POINTS}
    assert len(reasons) == 3


def test_the_monte_carlo_reason_names_the_step_count_it_needs():
    """Sirf "data kam tha" kaafi nahi — KITNA kam, ye user ko pata chale."""
    reason = _contract(None)["monte_carlo_risk"]["reason"]
    assert "12" in reason
    assert "held-out" in reason.lower()


def test_a_flat_series_reason_still_points_at_the_data_not_at_the_code():
    """Flat held-out par bhi wajah data ki rehti hai, "feature missing" ki nahi."""
    rows = _contract(_run([100.0] * 46))
    for point in _RECIPE_BUILT_POINTS:
        assert rows[point]["status"] == "NOT_MEASURED", point
        assert "abhi nahi hai" not in rows[point]["reason"].lower(), point










