"""#150i-f — waqt / haalat / khabar ki naap ka pehra: kya sach me naapa gaya.

Kyun ye file bani: #150i se contract ke teen point (`session_expectancy`,
`regime_detection`, `macro_event_windows`) text me likhe shabd se nahi, LAB ki
ASLI naap se grade hote hain. Naya raasta = naye jhooth ke naye mauke, isliye
har test yahan ek NAAPA hua jhooth rokta hai:

  - **"session" ka matlab ghanta hai** — weekday-wise ya mahina-wise farak
    naapna kaam hai, par usse "session expectancy naap li" keh dena nahi. Stamp
    me timezone hota hi nahi, isliye "London"/"New York" jaisa naam bhi nahi
    diya jaata;
  - **leakage** — slot aur window SIGNAL bar (`entry_index - 1`) se aate hain,
    regime ka label sirf `values[:entry_index]` se banta hai. Entry wale bar ka
    label lena ya aage ka bar dekhna nateeja shaandaar bana deta hai aur galat;
  - **"wait" ka jhooth** — jahan naap hi nahi hui wahan verdict `None` rehta
    hai. "wait" ek FAISLA hai (naapa, edge nahi mila, ruko); usko "naapa hi
    nahi" ki jagah likh dena is point ka sabse aasan jhooth hai;
  - **pre-news bina calendar** — shock-proxy mode me event ka waqt pehle se pata
    hi nahi hota, isliye wahan pre-news ka faisla structurally `None` rehta hai;
  - **aadha label** — kuch trade bina slot/regime reh jaayein to per-bucket
    number adhoore sample par tikte hain, aur "HAR scalp se pehle" jhootha ho
    jaata hai (`labelled_share` chhupaya nahi jaata);
  - **DATA_MISSING par number** — naap na ho to `numbers` bahar hi nahi jaata,
    warna aage wo "naapa hua" jaisa padha jaata hai;
  - **positive-nateeja ka jhukav** — naap ke baad "koi farak nahi" nikalna bhi
    poora jawab hai, isliye MET ke liye farak MILNA zaroori nahi;
  - **purana raasta kamzor ho jaana** — LAB ki naap na ho to teeno point bilkul
    wahi purana text-cue nateeja dete hain (`jo phle bna h unko htana mt`).

Koi network, koi randomness, koi provider key, koi Gemini call — sab kuch is
file ke andar ki deterministic series par chalta hai.
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import lab, market_data as md, trademodel as tm  # noqa: E402


# ── helpers: sab deterministic, sab is file ke andar ─────────────────────────
class _Src:
    """EvidencePack ka sirf wahi hissa jo market_data/lab padhte hain."""

    def __init__(self, source_id, series_meta=None, snippet=""):
        self.source_id = source_id
        self.series_meta = series_meta or {}
        self.title = ""
        self.snippet = snippet
        self.full_text = ""


class _Pack:
    def __init__(self, *sources):
        self.sources = list(sources)


#: Paanch trading ghante — is chaudai par slot/regime/event teeno me asli naap
#: hoti hai AUR ek bucket jaan-boojh kar chhoti reh jaati hai (adhoora sample ka
#: test bemaani na ho). Ye ghante empirically chune gaye hain, guess se nahi.
_HOURS = (9, 10, 11, 12, 13)


def _stamps(n, hours=_HOURS, step=5, day0=4):
    """`YYYY-MM-DD HH:MM` stamp — 5 minute ke bar, roz teen ghante."""
    out, day, index, minute = [], day0, 0, 0
    for _ in range(n):
        out.append(f"2024-03-{day:02d} {hours[index]:02d}:{minute:02d}")
        minute += step
        if minute >= 60:
            minute, index = 0, index + 1
            if index >= len(hours):
                index, day = 0, day + 1
    return out


def _walk(n, drift=0.30, seed=11, amp=2.2):
    """Deterministic LCG walk — jeet AUR haar dono banti hain (yahi zaroori hai)."""
    out, level, state = [], 100.0, seed
    for _ in range(n):
        state = (state * 1103515245 + 12345) % 2147483648
        shock = ((state % 2001) / 1000.0) - 1.0
        level += drift + amp * shock
        out.append(round(level, 3))
    return out


def _shocky(n, every=40, jump=16.0, seed=11):
    """Wahi walk, par har `every` bar par ek bada jhatka — shock proxy ke liye."""
    out, bump = [], 0.0
    for index, value in enumerate(_walk(n, seed=seed)):
        if index and index % every == 0:
            bump += jump
        out.append(round(value + bump, 3))
    return out


def _meta(values, stamps, frequency="intraday"):
    return {"provider": "test_provider", "series_id": "X", "label": "test series",
            "frequency": frequency, "unit": "pt",
            "points": [[stamps[i], float(value)]
                       for i, value in enumerate(values)]}


def _series(values, stamps, frequency="intraday"):
    """Series MODULE ke apne parser se banti hai — order yahan haath se nahi."""
    got, _reason = md.series_from_pack(
        _Pack(_Src("S1", _meta(values, stamps, frequency))))
    assert got is not None, "series_from_pack ne series hi nahi banayi"
    return got


def _intraday(n=240, seed=11):
    return _series(_walk(n, seed=seed), _stamps(n))


def _event_series(n=240, every=40):
    return _series(_shocky(n, every=every), _stamps(n))


def _years(n=20, frequency="yearly"):
    """Sirf saal wale label — inme koi slot nahi hota."""
    stamps = [str(2001 + i) for i in range(n)]
    return _series(_walk(n, seed=5), stamps, frequency=frequency)


def _daily(n=40):
    stamps = [f"2024-03-{1 + (i % 28):02d}" if i < 28 else
              f"2024-04-{1 + (i - 28):02d}" for i in range(n)]
    return _series(_walk(n, seed=9), sorted(stamps), frequency="daily")


def _row(slot="h09", n_trades=5, expectancy=0.4, measured=True, key="slot"):
    """Ek naapi hui bucket-row — jaisi `SlotSplit.rows` me hoti hai."""
    return {key: slot, "measured": bool(measured), "n_trades": int(n_trades),
            "expectancy_r": expectancy, "reason": ""}


# ══ 1. slot_of — slot sirf LABEL se banta hai, guess se nahi ═════════════════
def test_stamp_se_ghanta_nikalta_hai_aur_wahi_session_ka_paimana_hai():
    assert md.slot_of("2024-03-04 09:35") == (md.SLOT_HOUR, "h09")
    assert md.slot_of("2024-03-04 14:05") == (md.SLOT_HOUR, "h14")
    assert md.slot_of("2024-03-04T00:00") == (md.SLOT_HOUR, "h00")


def test_sirf_din_mile_to_weekday_aur_wo_machine_ki_bhasha_se_nahi_badalta():
    granularity, slot = md.slot_of("2024-03-04")
    assert granularity == md.SLOT_WEEKDAY
    # 2024-03-04 somwaar hai. Naam `date.weekday()` se aata hai, locale se nahi —
    # warna machine ki bhasha badalte hi slot ka naam badal jaata aur do run ka
    # nateeja jud hi nahi paata.
    assert slot == md._WEEKDAY_NAMES[0]
    assert md.slot_of("2024-03-09")[1] == md._WEEKDAY_NAMES[5]


def test_mahina_aur_quarter_bhi_slot_ban_sakte_hain_par_apne_naam_se():
    assert md.slot_of("2024-03") == (md.SLOT_MONTH, md._MONTH_NAMES[2])
    assert md.slot_of("2024-Q2") == (md.SLOT_QUARTER, "q2")


def test_akele_saal_par_koi_slot_nahi_banta():
    # Saal-bhar ka ek point — "din ka kaunsa hissa" ka sawaal hi nahi banta.
    assert md.slot_of("2024") == ("", "")
    assert md.slot_of("") == ("", "")


def test_bemaani_ghanta_ya_mahina_slot_nahi_banta_chupke_se_bhi_nahi():
    assert md.slot_of("2024-03-04 27:00") == ("", "")
    assert md.slot_of("2024-13") == ("", "")
    assert md.slot_of("2024-02-30") == ("", "")


# ══ 2. slot_expectancy — naap hui ya nahi, aur kis paimane par ══════════════
def test_saal_bhar_ke_data_par_session_expectancy_naapi_hi_nahi_jaati():
    split = md.slot_expectancy(_years())
    assert split.ok is False
    assert split.reason_code == md.SLOT_TOO_COARSE
    assert split.granularity == ""


def test_label_me_koi_slot_na_ho_to_wajah_saaf_likhi_jaati_hai():
    got, _reason = md.series_from_pack(
        _Pack(_Src("S1", _meta(_walk(20, seed=5),
                               [str(2001 + i) for i in range(20)],
                               frequency="unknown"))))
    split = md.slot_expectancy(got)
    assert split.ok is False
    assert split.reason_code == md.NO_SLOT_LABELS


def test_intraday_series_par_ghanta_wise_naap_sach_me_hoti_hai():
    split = md.slot_expectancy(_intraday())
    assert split.ok is True
    assert split.granularity == md.SLOT_HOUR
    assert split.intraday is True
    assert split.measured >= 2
    assert split.labelled_share == 1.0
    assert split.to_dict()["hour_of_day_measured"] is True
    assert split.to_dict()["hour_of_day_reason"] == ""


def test_daily_series_par_naap_hoti_hai_par_use_session_nahi_kaha_jaata():
    split = md.slot_expectancy(_daily())
    if split.ok:
        assert split.granularity == md.SLOT_WEEKDAY
    assert split.intraday is False
    numbers = split.to_dict()
    assert numbers["hour_of_day_measured"] is False
    assert numbers["hour_of_day_reason"] == md.NO_INTRADAY_DATA


def test_session_ke_naam_kabhi_nahi_diye_jaate_kyunki_stamp_me_timezone_nahi():
    split = md.slot_expectancy(_intraday())
    slots = [row["slot"] for row in split.rows]
    assert slots and all(slot.startswith("h") for slot in slots)
    for name in ("london", "new york", "tokyo", "asia"):
        assert not any(name in slot.lower() for slot in slots)
    assert "timezone" in split.to_dict()["session_names_not_used"].lower()


def test_slot_signal_bar_se_aata_hai_entry_wale_bar_se_nahi():
    """Yahi leakage ka asli taala — aur ye test dono taraf naapta hai."""
    series = _intraday()
    values = list(series.values())
    periods = list(series.periods())
    base = md.walk_forward(series)
    trades = md.simulate_trades(values, base.n_train)
    assert trades, "trade hi nahi bane to test bemaani hai"

    def _count(offset):
        buckets = {}
        for trade in trades:
            index = trade.entry_index - offset
            found, slot = md.slot_of(periods[index] if 0 <= index < len(periods)
                                     else "")
            if found == md.SLOT_HOUR and slot:
                buckets[slot] = buckets.get(slot, 0) + 1
        return buckets

    split = md.slot_expectancy(series)
    got = {row["slot"]: row["n_trades"] for row in split.rows}
    assert got == _count(1)
    # Aur ye do ginti barabar NAHI honi chahiye — warna test kuch saabit nahi
    # karta (entry bar aur signal bar ka farak dikhna zaroori hai).
    assert _count(1) != _count(0)


def test_jis_slot_me_poora_sample_nahi_uske_number_None_rehte_hain():
    split = md.slot_expectancy(_intraday())
    unmeasured = [row for row in split.rows if not row["measured"]]
    assert unmeasured, "ek bhi chhoti bucket nahi bani to ye test bemaani hai"
    for row in unmeasured:
        # Chupke se girana nahi, aur 2 trade ka "expectancy" 20 trade wale jaisa
        # dikhna bhi nahi — number None rehte hain aur wajah saath jaati hai.
        for key in ("expectancy_r", "profit_factor", "sharpe_r", "sortino_r",
                    "win_rate"):
            assert row[key] is None, row
        assert row["reason"] == md.FEW_TRADES
        assert row["n_trades"] >= 1


def test_slot_naap_me_koi_randomness_nahi_do_run_ka_nateeja_ek_hi():
    first = md.slot_expectancy(_intraday()).to_dict()
    second = md.slot_expectancy(_intraday()).to_dict()
    assert first == second
    assert first["randomness_used"] is False
    assert first["is_established_fact"] is False


# ══ 3. SlotSplit ke teen-tarfa property — None ka matlab "tay nahi hua" ══════
def _slot_split(*expectancies, n_trades=0, unlabelled=0, measured=True):
    rows = tuple(_row(slot=f"h{index:02d}", expectancy=value,
                      measured=measured)
                 for index, value in enumerate(expectancies))
    return md.SlotSplit(ok=True, rows=rows, n_trades=n_trades,
                        unlabelled=unlabelled)


def test_ek_hi_naapi_hui_bucket_par_faasla_aur_faisla_dono_None_rehte_hain():
    # Ek slot se "is waqt trade karo" nikaalna hi is jagah ka aam jhooth hai.
    split = _slot_split(0.4)
    assert split.measured == 1
    assert split.spread_r is None
    assert split.slot_dependent is None
    assert split.verdict_reason == md.FEW_SLOTS


def test_farak_chhota_nikalna_bhi_poora_jawab_hai_naap_ka_na_hona_nahi():
    split = _slot_split(0.40, 0.30)
    assert split.spread_r is not None
    assert split.spread_r < md.SLOT_DIFF_R
    # False = naapa gaya aur farak nahi mila. None = naapa hi nahi gaya. Ye do
    # baat ek jagah mila dena hi "positive nateeje ka jhukav" hai.
    assert split.slot_dependent is False
    assert split.verdict_reason == md.SLOT_NO_DIFFERENCE


def test_bada_farak_mile_to_koi_wajah_bacha_kar_nahi_rakhi_jaati():
    split = _slot_split(0.90, 0.10)
    assert round(split.spread_r, 6) == round(md.SLOT_DIFF_R * 3.2, 6)
    assert split.slot_dependent is True
    assert split.verdict_reason == ""


def test_ek_bhi_trade_na_bane_to_labelled_share_None_hota_hai_zero_nahi():
    assert _slot_split(0.4, 0.2).labelled_share is None
    aadha = _slot_split(0.4, 0.2, n_trades=4, unlabelled=1)
    assert aadha.labelled_share == 0.75
    assert aadha.to_dict()["labelled_share"] == 0.75
    assert _slot_split(0.4, 0.2, n_trades=4).labelled_share == 1.0


def test_best_aur_worst_sirf_naapi_hui_row_se_chunte_hain():
    # Bina naap wali row ka "expectancy" chun lena hi sabse aasan dhokha hai:
    # 2 trade ka number 200 trade wale jaisa dikhne lagta hai.
    rows = (_row(slot="h09", expectancy=99.0, n_trades=1, measured=False),
            _row(slot="h10", expectancy=0.5, n_trades=9),
            _row(slot="h11", expectancy=0.1, n_trades=7))
    split = md.SlotSplit(ok=True, rows=rows, n_trades=17)
    assert split.measured == 2
    assert split.best["slot"] == "h10"
    assert split.worst["slot"] == "h11"
    assert round(split.spread_r, 4) == 0.4
    assert split.positive == 2


# ══ 4. REGIME — label sirf pichhle bar se, aur "har" ka matlab HAR ═══════════
def test_itna_pichhla_data_hi_na_ho_to_regime_ka_label_khaali_rehta_hai():
    # Khaali string ka matlab "koi regime nahi" NAHI hai — matlab "naapa hi nahi
    # ja saka". Isko "range" gin lena hi wo jhooth hai jo yahan roka jaata hai.
    need = max(md.REGIME_TREND_LOOKBACK, md.REGIME_VOL_LOOKBACK) + 1
    values = _walk(need + 5)
    assert md.regime_at([]) == ""
    assert md.regime_at(values[:need - 1]) == ""
    assert md.regime_at(values[:need]) != ""
    # Bilkul flat history par paimana hi nahi banta (unit 0) — wahan bhi khaali.
    assert md.regime_at([100.0] * (need + 4)) == ""


def test_regime_ka_naam_do_hisso_se_banta_hai_trend_aur_volatility():
    label = md.regime_at(_walk(40))
    trend, _, volatility = label.partition("|")
    assert trend in (md.REGIME_TREND_UP, md.REGIME_TREND_DOWN, md.REGIME_RANGE)
    assert volatility in (md.REGIME_VOL_HIGH_NAME, md.REGIME_VOL_MID_NAME,
                          md.REGIME_VOL_LOW_NAME)


def test_regime_label_entry_se_pehle_ke_bar_se_banta_hai_entry_wale_se_nahi():
    """Doosra leakage taala — aur ye bhi dono taraf naapta hai."""
    series = _intraday()
    values = list(series.values())
    base = md.walk_forward(series)
    trades = md.simulate_trades(values, base.n_train)
    assert trades, "trade hi nahi bane to test bemaani hai"

    def _count(extra):
        buckets = {}
        for trade in trades:
            label = md.regime_at(values[:trade.entry_index + extra])
            if label:
                buckets[label] = buckets.get(label, 0) + 1
        return buckets

    split = md.regime_expectancy(series)
    got = {row["regime"]: row["n_trades"] for row in split.rows}
    assert got == _count(0)
    # Ek bar aage dekhne se ginti badalti hai — yaani ye test khaali nahi hai.
    assert _count(0) != _count(1)


def test_aage_ke_bar_jodne_se_pichhla_label_badal_nahi_sakta():
    """`regime_at` ko poori series kabhi nahi di jaati — yahi structural garanti."""
    values = _walk(60)
    cut = 30
    before = md.regime_at(values[:cut])
    assert before
    for tail in ([], [999.0] * 10, [-999.0] * 10, _walk(10, seed=77)):
        assert md.regime_at((values[:cut] + tail)[:cut]) == before
    assert "history" in inspect.signature(md.regime_at).parameters


def test_kuch_trade_bina_label_reh_jaayein_to_pehli_wajah_wahi_hoti_hai():
    rows = (_row(slot="range|mid_vol", expectancy=0.9, n_trades=6, key="regime"),
            _row(slot="trend_up|mid_vol", expectancy=0.1, n_trades=5,
                 key="regime"))
    split = md.RegimeSplit(ok=True, rows=rows, n_trades=13, unlabelled=2)
    # Farak bada hai (0.8R), phir bhi pehli wajah "adhoora label" hai — kyunki
    # per-regime number us adhoore hisse par tike hote.
    assert split.spread_r is not None and split.spread_r >= md.REGIME_DIFF_R
    assert split.verdict_reason == md.REGIME_UNLABELLED
    assert split.labelled_before_entry is False
    assert split.to_dict()["labelled_before_entry"] is False
    poora = md.RegimeSplit(ok=True, rows=rows, n_trades=11, unlabelled=0)
    assert poora.labelled_before_entry is True
    assert poora.verdict_reason == ""


def test_ek_bhi_trade_na_ho_to_labelled_before_entry_None_rehta_hai():
    split = md.RegimeSplit(ok=True, rows=(), n_trades=0)
    assert split.labelled_share is None
    assert split.labelled_before_entry is None
    assert split.regime_dependent is None


# ══ 5. EVENT ka waqt — likha hua mile tabhi calendar, warna proxy ════════════
def _event_line(stamp, name="CPI release"):
    return f"{name} {stamp} par aayi."


def test_event_ke_liye_ek_hi_line_par_naam_aur_waqt_dono_chahiye():
    stamp = _stamps(1)[0]
    assert md.event_periods_from_text(_event_line(stamp))
    # Sirf waqt (naam nahi) — kis cheez ki khidki hai, ye pata hi nahi.
    assert md.event_periods_from_text(f"Kuch bhi {stamp} par hua.") == ()
    # Sirf naam (waqt nahi) — minute wali khidki ban hi nahi sakti.
    assert md.event_periods_from_text("CPI release ka din tha.") == ()
    assert md.event_periods_from_text("CPI release 2024 me aayi.") == ()


def test_sirf_date_mile_to_wo_daily_hai_aur_minute_khidki_nahi_banati():
    got = md.event_periods_from_text("CPI release 2024-03-04 par aayi.")
    assert len(got) == 1
    assert got[0]["granularity"] == "daily"
    emap = md.event_windows(_event_series(), got)
    # Ginti "0" nahi hoti — wo event chupke se gayab nahi, alag se ginaa jaata.
    assert emap.events_without_time == 1
    assert emap.reason_code == md.NO_EVENTS
    assert emap.ok is False


def test_series_se_bahar_ka_event_alag_se_ginaa_jaata_hai():
    got = md.event_periods_from_text("CPI release 2099-03-04 09:35 par aayi.")
    emap = md.event_windows(_event_series(), got)
    assert emap.events_outside_series == 1
    assert emap.reason_code == md.NO_EVENTS
    numbers = md.event_window_expectancy(_event_series(), events=got).to_dict()
    assert numbers["event_outside_series_reason"] == md.EVENT_OUTSIDE_SERIES


def test_ek_line_se_ek_hi_event_nikalta_hai_aur_dohraav_hat_jaata_hai():
    stamps = _stamps(2)
    one_line = md.event_periods_from_text(
        f"CPI {stamps[0]} aur NFP {stamps[1]} ek hi line me.")
    assert len(one_line) == 1
    twice = md.event_periods_from_text("\n".join(
        [_event_line(stamps[0]), _event_line(stamps[0]),
         _event_line(stamps[0], "NFP release")]))
    # Dedup `(naam, waqt)` par hai — wahi event do baar likha ho to ek, par do
    # ALAG event ek hi waqt par hon to dono rehte hain.
    assert len(twice) == 2


def test_minute_wali_khidki_sirf_intraday_stamp_par_ban_sakti_hai():
    assert md.event_windows(None).reason_code == md.NO_SERIES
    assert md.event_windows(_daily()).reason_code == md.EVENT_NEEDS_INTRADAY
    assert md.event_window_expectancy(_daily()).reason_code == \
        md.EVENT_NEEDS_INTRADAY


def test_bar_ka_step_pata_na_chale_to_naap_ruk_jaati_hai():
    points = tuple(md.SeriesPoint(period="2024-03-04 09:00", order=5,
                                  value=100.0 + index, unit="pt")
                   for index in range(20))
    stuck = md.MarketSeries(points=points, frequency="intraday", unit="pt",
                            provider="test_provider", series_id="X",
                            label="test series", source_ids=["S1"], note="")
    assert md.event_windows(stuck).reason_code == md.EVENT_STEP_UNKNOWN
    assert md.event_windows(_event_series()).step_minutes == 5


def _calendar(series, indexes, stamps=None):
    """Series ke andar ke stamp par asli calendar — text se PADHA hua."""
    labels = stamps or _stamps(len(list(series.periods())))
    lines = "\n".join(_event_line(labels[index]) for index in indexes)
    return md.event_periods_from_text(lines)


def test_shock_proxy_me_pre_news_ka_label_lagta_hi_nahi():
    """Shock ka pata usi bar par chalta hai jab wo chhap chuka — pehle nahi."""
    emap = md.event_windows(_event_series())
    assert emap.mode == md.EVENT_MODE_SHOCK
    assert emap.n_events >= 2
    assert md.EVENT_PRE not in emap.labels
    assert emap.pre_event_measurable is False


def test_asli_calendar_mile_to_pre_news_ka_label_banta_hai():
    series = _event_series()
    events = _calendar(series, range(40, 240, 40))
    emap = md.event_windows(series, events)
    assert emap.mode == md.EVENT_MODE_CALENDAR
    assert md.EVENT_PRE in emap.labels
    assert emap.pre_event_measurable is True
    # Yahi ek farak dono mode ka asli farak hai — baaki khidkiyan dono me banti.
    for window in (md.EVENT_RELEASE, md.EVENT_EARLY, md.EVENT_LATE):
        assert window in emap.labels, window


def test_warmup_se_pehle_ka_jhatka_event_nahi_maana_jaata():
    """Threshold sirf PICHHLE bar se banta hai — bina paimane koi nishaan nahi."""
    n = 60
    values = [value + (25.0 if index >= 5 else 0.0)
              for index, value in enumerate(_walk(n))]
    series = _series(values, _stamps(n))
    early = md.event_windows(series, warmup=2)
    assert early.ok is True
    assert [index for index, label in enumerate(early.labels)
            if label == md.EVENT_RELEASE] == [5]
    # Wahi jhatka, default warmup par — nishaan hi nahi banta.
    assert md.EVENT_WARMUP_BARS > 5
    assert md.event_windows(series).reason_code == md.NO_EVENTS


def test_release_wala_bar_kisi_doosre_event_ki_khidki_se_nahi_dhankta():
    n = 120
    series = _series(_walk(n), _stamps(n))
    events = _calendar(series, (40, 42))
    assert len(events) == 2
    emap = md.event_windows(series, events)
    assert emap.n_events == 2
    assert emap.labels[40] == md.EVENT_RELEASE
    assert emap.labels[42] == md.EVENT_RELEASE
    # Beech ka bar nazdeek wale event ka hai, aur doosre event ka pre-news label
    # release ya post ko chhupa nahi sakta.
    assert emap.labels[41] == md.EVENT_EARLY


def test_event_khidki_signal_bar_se_lagti_hai_entry_wale_bar_se_nahi():
    """Slot aur regime ki tarah event-window bhi SIGNAL bar se — aur ye test
    dono taraf naapta hai, warna kuch saabit nahi hota."""
    series = _event_series()
    values = list(series.values())
    base = md.walk_forward(series)
    trades = md.simulate_trades(values, base.n_train)
    assert trades, "trade hi nahi bane to test bemaani hai"
    emap = md.event_windows(series, ())
    assert emap.ok, "event map hi nahi bana to test bemaani hai"

    def _count(offset):
        buckets = {}
        for trade in trades:
            index = trade.entry_index - offset
            label = (emap.labels[index] if 0 <= index < len(emap.labels)
                     else "")
            if label:
                buckets[label] = buckets.get(label, 0) + 1
        return buckets

    split = md.event_window_expectancy(series)
    got = {row["window"]: row["n_trades"] for row in split.rows}
    assert got == _count(1)
    # Entry bar aur signal bar ki ginti alag dikhni chahiye — tab hi upar wala
    # assert leakage ka asli taala hai.
    assert _count(1) != _count(0)


# ══ 6. FAISLA — trade / wait / avoid, aur "naapa hi nahi" ka None ════════════
def test_faisla_naapi_hui_expectancy_ki_hadd_par_banta_hai():
    def _verdict(expectancy, window=md.EVENT_LATE,
                 mode=md.EVENT_MODE_SHOCK, enough=True):
        return md._event_verdict(window, mode, {"expectancy_r": expectancy},
                                 enough)

    assert _verdict(md.EVENT_TRADE_MIN_R) == md.EVENT_TRADE
    assert _verdict(md.EVENT_TRADE_MIN_R - 0.001) == md.EVENT_WAIT
    assert _verdict(md.EVENT_AVOID_MAX_R) == md.EVENT_AVOID
    assert _verdict(md.EVENT_AVOID_MAX_R + 0.001) == md.EVENT_WAIT
    assert _verdict(0.0) == md.EVENT_WAIT


def test_naap_na_ho_to_faisla_None_rehta_hai_wait_nahi():
    """"wait" ek FAISLA hai. Usko "naapa hi nahi" ki jagah likhna hi jhooth hai."""
    stats = {"expectancy_r": 0.9}
    # (a) itne trade hi nahi bane
    assert md._event_verdict(md.EVENT_LATE, md.EVENT_MODE_SHOCK, stats,
                            False) is None
    # (b) pre-news, par calendar nahi
    assert md._event_verdict(md.EVENT_PRE, md.EVENT_MODE_SHOCK, stats,
                            True) is None
    assert md._event_verdict(md.EVENT_PRE, md.EVENT_MODE_CALENDAR, stats,
                            True) == md.EVENT_TRADE
    # (c) expectancy hi None (row me number nahi bacha)
    assert md._event_verdict(md.EVENT_LATE, md.EVENT_MODE_SHOCK,
                            {"expectancy_r": None}, True) is None
    assert md._event_verdict(md.EVENT_LATE, md.EVENT_MODE_SHOCK, {},
                            True) is None


def _event_split(mode=md.EVENT_MODE_SHOCK, **verdicts):
    rows = tuple({"window": window, "measured": True, "verdict": verdict,
                  "reason": "", "n_trades": 5, "expectancy_r": 0.4}
                 for window, verdict in verdicts.items())
    return md.EventSplit(ok=True, mode=mode, rows=rows, n_trades=5 * len(rows))


def test_shock_mode_me_pre_news_ka_faisla_row_hone_par_bhi_None_rehta_hai():
    """Do taale ek hi baat par — label bhi nahi lagta, aur faisla bhi None."""
    split = _event_split(**{md.EVENT_PRE: md.EVENT_TRADE,
                            md.EVENT_LATE: md.EVENT_AVOID})
    # Row me verdict likha hai (jaan-boojh kar), phir bhi baahar None jaata hai.
    assert split.verdicts[md.EVENT_PRE] == md.EVENT_TRADE
    assert split.pre_event_verdict is None
    numbers = split.to_dict()
    assert numbers["pre_event_verdict"] is None
    assert numbers["pre_event_reason"] == md.PRE_EVENT_NEEDS_CALENDAR


def test_calendar_mode_me_pre_news_ka_faisla_bahar_jaata_hai():
    split = _event_split(mode=md.EVENT_MODE_CALENDAR,
                         **{md.EVENT_PRE: md.EVENT_WAIT,
                            md.EVENT_LATE: md.EVENT_AVOID})
    assert split.pre_event_verdict == md.EVENT_WAIT
    assert split.to_dict()["pre_event_reason"] == ""


def test_khidki_se_farak_pada_ya_nahi_teen_tarfa_jawab_hai():
    ek = _event_split(**{md.EVENT_LATE: md.EVENT_TRADE})
    assert ek.decided == 1
    assert ek.window_dependent is None          # tay hi nahi hua
    assert ek.verdict_reason == md.FEW_EVENT_WINDOWS
    same = _event_split(**{md.EVENT_LATE: md.EVENT_TRADE,
                           md.EVENT_QUIET: md.EVENT_TRADE})
    assert same.window_dependent is False       # naapa, farak nahi mila
    assert same.verdict_reason == md.EVENT_NO_DIFFERENCE
    differ = _event_split(**{md.EVENT_LATE: md.EVENT_AVOID,
                             md.EVENT_QUIET: md.EVENT_TRADE})
    assert differ.window_dependent is True
    assert differ.verdict_reason == ""


def test_khidki_naapi_par_faisla_ek_hi_bana_to_wajah_khaali_nahi_rehti():
    """Do khidki naapi gayi, par faisla ek hi bana — dependence tay NAHI hua.

    Aise waqt wajah khaali ("sab theek") likhna jhooth hai; slot aur regime
    lane bhi yahi baat FEW_SLOTS / FEW_REGIMES likh kar batate hain.
    """
    adhoora = _event_split(**{md.EVENT_LATE: md.EVENT_TRADE,
                              md.EVENT_EARLY: None})
    assert adhoora.measured == 2
    assert adhoora.decided == 1
    assert adhoora.window_dependent is None
    assert adhoora.verdict_reason == md.FEW_EVENT_WINDOWS


def test_shock_proxy_par_bhi_naap_asli_hoti_hai_par_pre_news_khaali_rehta_hai():
    split = md.event_window_expectancy(_event_series())
    assert split.ok is True
    assert split.mode == md.EVENT_MODE_SHOCK
    assert split.n_events >= 2
    assert split.measured >= 2
    assert split.decided >= 2
    assert split.labelled_share == 1.0
    # Ye poore point ka dil hai: naap chali, par pre-news ka jawab imaandaari se
    # khaali hai — kyunki shock ka waqt pehle se pata nahi hota.
    assert split.pre_event_verdict is None
    pre_row = [row for row in split.rows if row["window"] == md.EVENT_PRE]
    for row in pre_row:
        assert row["reason"] == md.PRE_EVENT_NEEDS_CALENDAR


def test_calendar_mile_to_pre_news_ka_faisla_asli_naap_se_banta_hai():
    series = _series(_shocky(300, every=40), _stamps(300))
    events = _calendar(series, range(40, 300, 40), _stamps(300))
    assert len(events) >= 6
    split = md.event_window_expectancy(series, events=events)
    assert split.ok is True
    assert split.mode == md.EVENT_MODE_CALENDAR
    assert split.pre_event_verdict in (md.EVENT_TRADE, md.EVENT_WAIT,
                                       md.EVENT_AVOID)
    assert split.to_dict()["pre_event_reason"] == ""


def test_event_naap_me_koi_randomness_nahi_do_run_ka_nateeja_ek_hi():
    first = md.event_window_expectancy(_event_series()).to_dict()
    second = md.event_window_expectancy(_event_series()).to_dict()
    assert first == second
    assert first["randomness_used"] is False
    assert first["is_established_fact"] is False


# ══ 7. LAB WIRING — teen nayi recipe asli me chalti hain ════════════════════
_HYP = {"hypothesis_id": "RV-HYP-1",
        "statement": "Backtest: next year value badhega, forecast 12 %."}
_NEW_RECIPES = ("slot_expectancy", "regime_split", "event_window")


def _lab(values, stamps=None, frequency="intraday"):
    stamps = stamps or _stamps(len(values))
    pack = _Pack(_Src("S1", _meta(values, stamps, frequency)))
    return lab.run_lab("cpi forecast", [_HYP], pack=pack)


def _rows(report):
    return {row["recipe"]: row for row in report["hypotheses"][0]["tests"]}


def test_teen_nayi_recipe_lab_me_hain_aur_naam_dono_taraf_ek_hi():
    """Naam ka farak = point chup-chaap kabhi grade hi na ho. Isliye pinned."""
    assert tm.LAB_RECIPE_SLOT == "slot_expectancy"
    assert tm.LAB_RECIPE_REGIME == "regime_split"
    assert tm.LAB_RECIPE_EVENT == "event_window"
    for recipe in (tm.LAB_RECIPE_SLOT, tm.LAB_RECIPE_REGIME,
                   tm.LAB_RECIPE_EVENT):
        assert recipe in lab.RECIPES, recipe
    # Pin abhi bhi EXACT hai, sirf do hisso me: 12 science/trading recipe +
    # #171e ki exam recipes. Ye "12" ko dhakka de kar 17 karna nahi hai —
    # science/trading ka hissa apni jagah pinned rehta hai, warna kal koi
    # trading recipe chup-chaap gayab ho jaaye aur exam ki ek nayi recipe
    # us kami ko dhak de.
    assert len(lab.EXAM_RECIPES) == 5
    assert len(lab.RECIPES) == 12 + len(lab.EXAM_RECIPES)
    for recipe in lab.EXAM_RECIPES:
        assert recipe not in (tm.LAB_RECIPE_SLOT, tm.LAB_RECIPE_REGIME,
                              tm.LAB_RECIPE_EVENT), recipe


def test_intraday_series_par_slot_aur_regime_ki_spec_banti_aur_chalti_hai():
    specs = lab.plan_specs(_HYP, _Pack(_Src("S1", _meta(_walk(240),
                                                        _stamps(240)))),
                           lab.LabPolicy(), "cpi forecast")
    for recipe in _NEW_RECIPES:
        assert recipe in [spec.recipe for spec in specs], recipe
    rows = _rows(_lab(_walk(240)))
    for recipe in ("slot_expectancy", "regime_split"):
        row = rows[recipe]
        assert row["status"] == "TESTED_PASS", recipe
        assert row["numbers"], recipe
        assert row["numbers"]["ran"] is True
        assert row["numbers"]["n_train"] == 168
        assert row["numbers"]["n_test"] == 72
        assert row["is_established_fact"] is False
        assert row["real_world_experiment_pending"] is True


def test_event_ki_naap_jhatke_wali_series_par_chalti_hai():
    row = _rows(_lab(_shocky(240, every=40)))["event_window"]
    assert row["status"] == "TESTED_PASS"
    assert row["numbers"]["mode"] == md.EVENT_MODE_SHOCK
    assert row["numbers"]["n_events"] >= 2
    assert row["numbers"]["windows_decided"] >= 2
    assert row["numbers"]["n_test"] == 72
    # Shock proxy me pre-news ka jawab lab se bahar bhi khaali hi jaata hai.
    assert row["numbers"]["pre_event_verdict"] is None
    assert row["numbers"]["pre_event_reason"] == md.PRE_EVENT_NEEDS_CALENDAR


def test_jhatka_hi_na_ho_to_event_naap_DATA_MISSING_rehti_hai_jhootha_PASS_nahi():
    row = _rows(_lab(_walk(240)))["event_window"]
    assert row["status"] == "DATA_MISSING"
    assert row["reason_code"] == md.NO_EVENTS
    assert row["numbers"] == {}


def test_DATA_MISSING_par_teeno_recipe_se_ek_bhi_number_bahar_nahi_jaata():
    """Naap na chali to `numbers` khaali — warna aage "naapa hua" padha jaata."""
    rows = _rows(_lab(_walk(20, seed=5), [str(2001 + i) for i in range(20)],
                      frequency="yearly"))
    expected = {"slot_expectancy": md.SLOT_TOO_COARSE,
                "regime_split": md.FEW_REGIMES,
                "event_window": md.EVENT_NEEDS_INTRADAY}
    for recipe, reason in expected.items():
        row = rows[recipe]
        assert row["status"] == "DATA_MISSING", recipe
        assert row["reason_code"] == reason, recipe
        assert row["numbers"] == {}, recipe
        assert row["computed"] is None, recipe


def test_naap_chali_par_HAR_nahi_hui_to_nateeja_FAIL_hai_DATA_MISSING_nahi():
    """Aadha label = naap ne kuch bataya. Usko "data nahi mila" kehna jhooth hai."""
    rows = tuple({"regime": name, "measured": True, "n_trades": 5,
                  "expectancy_r": value, "reason": ""}
                 for name, value in (("trend_up_high_vol", 0.9),
                                     ("range_low_vol", 0.1)))
    fake = md.RegimeSplit(ok=True, rows=rows, n_trades=13, unlabelled=2,
                          n_train=100, n_test=40)
    real = lab.market_data.regime_expectancy
    try:
        lab.market_data.regime_expectancy = lambda *a, **k: fake
        row = _rows(_lab(_walk(240)))["regime_split"]
    finally:
        lab.market_data.regime_expectancy = real
    assert row["status"] == "TESTED_FAIL"
    assert row["reason_code"] == md.REGIME_UNLABELLED
    assert row["numbers"]["labelled_share"] == round(11 / 13.0, 4)
    assert row["computed"] == round(11 / 13.0, 4)
    # Aur patch hatne ke baad asli raasta zinda hai (test ne module tod nahi diya).
    assert lab.market_data.regime_expectancy is real
    assert _rows(_lab(_walk(240)))["regime_split"]["status"] == "TESTED_PASS"


def test_naap_na_chalne_par_number_dene_ka_raasta_code_me_hi_nahi_hai():
    """Static pehra: `numbers=` sirf TESTED_PASS/TESTED_FAIL par likha ja sakta."""
    import ast
    import textwrap
    seen = 0
    for func in (lab._run_slot_expectancy, lab._run_regime_split,
                 lab._run_event_window):
        tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", "")
            if name != "_result":
                continue
            has_numbers = any(kw.arg == "numbers" for kw in node.keywords)
            if not has_numbers:
                continue
            status = node.args[1]
            assert isinstance(status, ast.Name), func.__name__
            assert status.id in ("TESTED_PASS", "TESTED_FAIL"), func.__name__
            seen += 1
    assert seen == 7, seen


# ══ 8. CONTRACT GATE — teen point naapi hui number par grade hote hain ══════
#: Jaan-boojh kar aisa spec jisme session/regime/event ka koi text-cue NAHI hai.
#: Isse do faayde: (a) naap na hone par nateeja NOT_MET rehta hai, (b) niche
#: section 9 ka "purana raasta bilkul wahi" test bemaani nahi hota.
_SPEC = """US100 scalping model.
Execution chain: 15M context, 5M confirmation, 1M entry.
"""


def _slot_numbers(**over):
    out = md.slot_expectancy(_intraday()).to_dict()
    out.update(over)
    return out


def _regime_numbers(**over):
    out = md.regime_expectancy(_intraday()).to_dict()
    out.update(over)
    return out


def _event_numbers(mode=md.EVENT_MODE_CALENDAR, verdicts=None, **over):
    """Paanchon contract khidki ka faisla — gate ko yahi padhna hota hai."""
    if verdicts is None:
        verdicts = {window: md.EVENT_TRADE
                    for window in tm.CONTRACT_EVENT_WINDOWS}
    out = _event_split(mode=mode, **verdicts).to_dict()
    out.update(over)
    return out


def _report(rows):
    """LAB report ka sirf wahi hissa jo trademodel padhta hai."""
    tests = [{"recipe": recipe, "status": status, "numbers": numbers}
             for recipe, status, numbers in rows]
    return {"hypotheses": [{"tests": tests}]}


def _points(report):
    return {row["point_id"]: row
            for row in tm.measure(spec=_SPEC, lab_report=report)["checks"]}


def _point(point_id, recipe, numbers, status="TESTED_PASS"):
    return _points(_report([(recipe, status, numbers)]))[point_id]


def _session(**over):
    return _point("session_expectancy", tm.LAB_RECIPE_SLOT,
                  _slot_numbers(**over))


def _regime(**over):
    return _point("regime_detection", tm.LAB_RECIPE_REGIME,
                  _regime_numbers(**over))


def _event(**over):
    return _point("macro_event_windows", tm.LAB_RECIPE_EVENT,
                  _event_numbers(**over))


def test_teeno_point_asli_naap_par_MET_ho_sakte_hain():
    for row in (_session(), _regime(), _event()):
        assert row["status"] == tm.MET, row["point_id"]
        # Ye tag hi batata hai ki nateeja text-cue se nahi, naap se aaya.
        assert tm._LAB_MEASURED in row["observed"], row["point_id"]


def test_ghante_ke_bina_session_expectancy_MET_nahi_hoti():
    """Weekday-wise farak naapna kaam hai, par wo "session expectancy" nahi."""
    row = _session(granularity=md.SLOT_WEEKDAY, hour_of_day_measured=False,
                   hour_of_day_reason=md.NO_INTRADAY_DATA)
    assert row["status"] == tm.NOT_MET
    assert md.SLOT_HOUR in row["reason"]
    assert md.NO_INTRADAY_DATA in row["reason"]
    assert tm._LAB_MEASURED not in row["observed"]
    # Granularity ghanta likha ho par naap na hui ho — tab bhi NOT_MET.
    assert _session(hour_of_day_measured=False)["status"] == tm.NOT_MET


def test_ek_hi_ghanta_ya_faasla_hi_na_nikle_to_session_NOT_MET_rehti_hai():
    assert _session(slots_measured=1)["status"] == tm.NOT_MET
    assert _session(spread_r=None)["status"] == tm.NOT_MET


def test_kuch_trade_bina_ghante_reh_jaayein_to_session_NOT_MET():
    row = _session(labelled_share=0.9, trades_without_slot=2)
    assert row["status"] == tm.NOT_MET
    assert "adhoore" in row["reason"]
    assert "0.9" in row["observed"]


def test_waqt_se_farak_na_mile_to_bhi_session_MET_rehti_hai():
    """Naap ke baad "koi farak nahi" bhi POORA jawab hai — positive-bias nahi."""
    row = _session(slot_dependent=False, spread_r=0.01)
    assert row["status"] == tm.MET
    assert "farak NAHI padta" in row["reason"]


def test_regime_ka_pehla_taala_label_hai_regime_ki_ginti_nahi():
    """Dono galat hon to pehli wajah "label hi nahi bana" honi chahiye."""
    row = _regime(labelled_before_entry=False, labelled_share=0.8,
                  regimes_measured=1)
    assert row["status"] == tm.NOT_MET
    assert "PEHLE nahi bana" in row["reason"]
    assert "do regime" not in row["reason"]


def test_do_regime_ke_bina_regime_point_NOT_MET_rehta_hai():
    row = _regime(regimes_measured=1)
    assert row["status"] == tm.NOT_MET
    assert "do regime" in row["reason"]


def test_haalat_se_farak_na_mile_to_bhi_regime_point_MET_rehta_hai():
    row = _regime(regime_dependent=False, spread_r=0.02)
    assert row["status"] == tm.MET
    assert "farak NAHI padta" in row["reason"]


def test_contract_ki_paanch_khidki_market_data_ke_kram_se_hi_aati_hain():
    """List haath se dobara likhna = do jagah sach alag ho jaana."""
    assert tm.CONTRACT_EVENT_WINDOWS == tuple(
        window for window in md.EVENT_WINDOW_ORDER if window != md.EVENT_QUIET)
    assert md.EVENT_QUIET not in tm.CONTRACT_EVENT_WINDOWS
    assert len(tm.CONTRACT_EVENT_WINDOWS) == 5


def test_ek_khidki_ka_faisla_na_bane_to_event_NOT_MET_aur_naam_bataya_jaata():
    verdicts = {window: md.EVENT_TRADE
                for window in tm.CONTRACT_EVENT_WINDOWS
                if window != md.EVENT_MID}
    row = _event(verdicts=verdicts)
    assert row["status"] == tm.NOT_MET
    assert md.EVENT_MID in row["reason"]
    assert "wait" in row["reason"]


def test_shock_mode_me_pre_news_ka_row_hone_par_bhi_event_NOT_MET():
    """Row me verdict likha ho tab bhi pre-news bina calendar naapa nahi jaata."""
    row = _event(mode=md.EVENT_MODE_SHOCK)
    assert row["status"] == tm.NOT_MET
    assert md.EVENT_PRE in row["reason"]
    assert md.PRE_EVENT_NEEDS_CALENDAR in row["reason"]


def test_khidki_se_farak_na_pade_to_bhi_event_point_MET_rehta_hai():
    row = _event()
    assert row["status"] == tm.MET
    assert set(_event_numbers()["verdicts"].values()) == {md.EVENT_TRADE}
    assert _event_numbers()["window_dependent"] is False
    assert "ek jaisa nikla" in row["reason"]


def test_sabse_bada_naap_coverage_se_chunti_hai_expectancy_se_nahi():
    """Do LAB row me se bada = zyada trade, phir zyada coverage — na ki behtar R."""
    wide = _slot_numbers(n_trades=10, slots_measured=5, spread_r=0.30)
    narrow = _slot_numbers(n_trades=10, slots_measured=2, spread_r=9.99)
    report = _report([(tm.LAB_RECIPE_SLOT, "TESTED_PASS", narrow),
                      (tm.LAB_RECIPE_SLOT, "TESTED_PASS", wide)])
    assert tm.lab_slot_numbers(report)["slots_measured"] == 5
    # Trade ki ginti coverage se bhi upar hai — sample size pehle aata hai.
    bigger = _slot_numbers(n_trades=11, slots_measured=2, spread_r=9.99)
    report = _report([(tm.LAB_RECIPE_SLOT, "TESTED_PASS", wide),
                      (tm.LAB_RECIPE_SLOT, "TESTED_PASS", bigger)])
    assert tm.lab_slot_numbers(report)["slots_measured"] == 2
    assert tm.lab_regime_numbers(_report([])) is None
    assert tm.lab_event_numbers(_report([])) is None


# ══ 9. PURANA RAASTA — naap na ho to ek akshar nahi badalta ═════════════════
_NEW_POINTS = ("session_expectancy", "regime_detection", "macro_event_windows")
#: Text-cue wala spec: ye cue KHUD module se aate hain, haath se likhe nahi —
#: warna cue badalne par ye test chup-chaap bemaani ho jaata.
_CUE_SPEC = ("US100 model. "
             + " ".join(tm._POINT_CUES[point][0] for point in _NEW_POINTS)
             + " sample size 240 trades, expectancy 0.31R. "
               "trade / wait / avoid ka faisla.")


def _text_points(spec, lab_report=None):
    res = tm.measure(spec=spec, lab_report=lab_report)
    return {row["point_id"]: row for row in res["checks"]
            if row["point_id"] in _NEW_POINTS}


def test_naap_na_chali_to_teeno_point_bilkul_purana_nateeja_dete_hain():
    """`jo phle bna h unko htana mt` — fallback ka nateeja HU-BE-HU wahi."""
    numbers = {tm.LAB_RECIPE_SLOT: _slot_numbers(),
               tm.LAB_RECIPE_REGIME: _regime_numbers(),
               tm.LAB_RECIPE_EVENT: _event_numbers()}
    useless = (
        # (a) test chala hi nahi — number ho bhi to padhe nahi jaate
        _report([(recipe, "DATA_MISSING", value)
                 for recipe, value in numbers.items()]),
        # (b) test chala par kisi doosri recipe ka
        _report([(tm.LAB_RECIPE_TRADE, "TESTED_PASS", _slot_numbers())]),
        # (c) test chala par usne koi structured naap hi nahi di
        _report([(recipe, "TESTED_PASS", {}) for recipe in numbers]),
        _report([]),
        {},
    )
    for spec, expect in ((_SPEC, tm.NOT_MEASURED), (_CUE_SPEC, tm.MET)):
        base = _text_points(spec)
        assert {row["status"] for row in base.values()} == {expect}, spec[:20]
        for row in base.values():
            assert tm._LAB_MEASURED not in row["observed"]
        for report in useless:
            assert _text_points(spec, report) == base, spec[:20]


def test_naap_chal_gayi_to_wo_text_ke_MET_ko_bhi_gira_sakti_hai():
    """Likha hua naap nahi hota — naap text par BHAARI hai, dono taraf."""
    base = _text_points(_CUE_SPEC)
    assert base["session_expectancy"]["status"] == tm.MET
    report = _report([(tm.LAB_RECIPE_SLOT, "TESTED_PASS",
                       _slot_numbers(hour_of_day_measured=False,
                                     granularity=md.SLOT_WEEKDAY))])
    row = _text_points(_CUE_SPEC, report)["session_expectancy"]
    assert row["status"] == tm.NOT_MET
    assert row != base


def test_teeno_naye_evaluator_wiring_me_lage_hue_hain():
    assert tm._EVALUATORS["session_expectancy"] is tm._session_point
    assert tm._EVALUATORS["regime_detection"] is tm._regime_point
    assert tm._EVALUATORS["macro_event_windows"] is tm._event_point


def _reads_observed(func):
    """Kya ye function insaan ke padhne wali line ko WAPAS padhta hai."""
    import ast
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and node.slice.value == "observed"
                and isinstance(node.ctx, ast.Load)):
            return True
        if (isinstance(node, ast.Call)
                and getattr(node.func, "attr", "") == "get"
                and node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "observed"):
            return True
    return False


def test_naye_evaluator_insaan_ki_line_ko_kabhi_wapas_nahi_padhte():
    """"Derive, never declare" — faisla `numbers` se, kabhi `observed` se nahi."""
    # Control: pehle ye saabit karo ki checker asli me kuch pakadta hai, warna
    # niche ka pehra khaali reh jaata (ye function jaan-boojh kar text ki line
    # aage badhata hai, aur wahi is checker ka nishaan hai).
    assert _reads_observed(tm._cost_point) is True
    for func in (tm._session_from_numbers, tm._regime_from_numbers,
                 tm._event_from_numbers, tm._session_point, tm._regime_point,
                 tm._event_point):
        assert _reads_observed(func) is False, func.__name__





