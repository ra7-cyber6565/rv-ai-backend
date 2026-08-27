"""#118 — market/economic TIME SERIES lane: data asli ho, aur test asli ho.

Kyun ye lane bani: LAB (#116) ke paanchve recipe `walk_forward` ke paas data
hi nahi tha, isliye "trading model banao aur backtest karo" par app hamesha
DATA_MISSING likhta tha. Ab discovery provider ki naapi hui series laati hai
(`SourceRecord.series_meta`), aur lab usi par bina network walk-forward chalata
hai.

Is file ke kaam (har ek ek JHOOTH rokta hai):
  1. series banane ke niyam — junk numbers se series NA bane (period ke bina
     number series nahi hai), aur conflict/unit-mismatch/mixed granularity par
     verdict na aaye,
  2. walk-forward me look-ahead na ho, aur naive random-walk baseline se
     muqabla compulsory rahe — "MAE chhota tha" apne aap pass nahi hai,
  3. provider ka HTTP 200 + "Note" = "0 data mila" NA bane (rate_limited),
  4. API key ka VALUE kabhi log/note/error me na aaye (naam aa sakta hai),
  5. key na hone par lane "khaali" na dikhe — "ruka (no_key)" dikhe,
  6. lab ka `network_used: False` aur ₹0 waada backtest chalne par bhi sach rahe,
  7. TESTED_PASS kabhi "proven"/"financial advice" na bane,
  8. routing: market ka ishara na ho to ye lane chale hi nahi (quota bachao).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import lab, market_data as md  # noqa: E402
from research_engine import depth  # noqa: E402
from research_engine.connectors import base as cbase  # noqa: E402
from research_engine.connectors import market_connector as mc  # noqa: E402
from research_engine.models import SourceRecord, SourceType  # noqa: E402
from research_engine.planner import ResearchPlanner  # noqa: E402
from research_engine.source_discovery import SourceDiscovery  # noqa: E402


# ── chhote helpers (koi network, koi randomness) ─────────────────────────────
class _Src:
    """EvidencePack ka sirf wahi hissa jo lab/market_data padhte hain."""

    def __init__(self, source_id, series_meta=None, title="", snippet="",
                 full_text=""):
        self.source_id = source_id
        self.series_meta = series_meta or {}
        self.title = title
        self.snippet = snippet
        self.full_text = full_text


class _Pack:
    def __init__(self, *sources):
        self.sources = list(sources)


class _Resp:
    """requests ka wo hissa jo connector chhoota hai — sirf .json()."""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _meta(values, start=2000, provider="world_bank_series", series_id="X",
          unit="%", frequency="yearly"):
    return {"provider": provider, "series_id": series_id, "label": "test series",
            "frequency": frequency, "unit": unit,
            "points": [[f"{start + i}", float(v)] for i, v in enumerate(values)]}


def _hyp(hid="RV-HYP-1",
         statement="Backtest: next year value badhega, forecast 12 %."):
    return {"hypothesis_id": hid, "statement": statement}


def _walk_test(report, index=0):
    tests = report["hypotheses"][index]["tests"]
    rows = [t for t in tests if t["recipe"] == "walk_forward"]
    assert rows, "walk_forward spec hi nahi bani"
    return rows[0]


def _rising(n=14, step=3.0, base=100.0):
    return [base + step * i for i in range(n)]


class _EnvGuard:
    """Env ko test ke baad WAISA hi chhodo — warna baaki suites jhooth bolte."""

    def __init__(self, **values):
        self.values = values
        self.saved = {}

    def __enter__(self):
        for name, value in self.values.items():
            self.saved[name] = os.environ.get(name)
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        return self

    def __exit__(self, *exc):
        for name, old in self.saved.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
        return False


class _StubHttp:
    """`market_connector.http_get` ko badal kar payload lautao. Koi network nahi."""

    def __init__(self, router):
        self.router = router
        self.calls = []
        self.original = None

    def __enter__(self):
        self.original = mc.http_get

        def fake(url, params=None, timeout=None, headers=None, retries=None):
            self.calls.append((url, dict(params or {})))
            return _Resp(self.router(url, dict(params or {})))

        mc.http_get = fake
        return self

    def __exit__(self, *exc):
        mc.http_get = self.original
        return False


# ── 1. series banane ke niyam — bina period koi series nahi ──────────────────

def test_numbers_without_periods_are_not_a_series():
    """"Table 2019 2020 2021 growth" me saal hain par VALUE nahi.

    Ye is lane ka sabse aasan jhooth hai: teen saal dikhe to "series mil gayi"
    maan lena. Saal khud value nahi hota, aur us par backtest chalana matlab
    saal ko hi data samajhna.
    """
    series, reason = md.series_from_text("[S1] Table 2019 2020 2021 shows growth")
    assert series is None
    assert reason == md.NO_PERIODS


def test_a_bare_year_is_never_read_as_a_value():
    """Ye us jhooth ki jad hai: "2020" ko value maan lena.

    Unit ke saath aaya wahi number value hai; akela saal sirf ek label hai.
    """
    assert md._read_value(" 2020 2021") is None
    assert md._read_value(": 2020 crore") == (2020.0, "crore")


def test_real_periodic_series_is_read_with_source_tag():
    text = "\n".join(f"[S7] {2000 + i}: {100 + 2 * i} %" for i in range(12))
    series, reason = md.series_from_text(text)
    assert reason == ""
    assert series is not None and len(series.points) == 12
    assert series.frequency == "yearly"
    assert series.periods()[0] == "2000" and series.last_period() == "2011"
    # Source id saath chalti hai — warna report bata hi nahi paati kahan se aaya.
    assert series.source_ids == ["S7"]


def test_conflicting_values_for_one_period_give_no_verdict():
    """Ek hi saal par do alag number = kaunsa sach hai ye evidence se tay nahi.

    Aisi haalat me "pehla utha lo" ek chupka faisla hota, aur uspar chala
    backtest pura jhooth hota.
    """
    text = "[S1] 2001: 10 %\n[S1] 2002: 11 %\n[S1] 2002: 19 %\n[S1] 2003: 12 %"
    series, reason = md.series_from_text(text)
    assert series is None
    assert reason == md.CONFLICT


def test_mixed_units_never_become_one_series():
    """Ek line "%" ki, ek "crore" ki — inko ek series maan lena unit ka jhooth.

    Points itne hain ki TOO_SHORT ki wajah se pass na ho jaaye: naap SIRF unit
    par honi chahiye.
    """
    lines = [f"[S1] {2001 + i}: {10 + i} %" for i in range(11)]
    lines[5] = "[S1] 2006: 500 crore"
    series, reason = md.series_from_text("\n".join(lines))
    assert series is None
    assert reason == md.UNIT_MISMATCH


def test_series_dict_always_carries_the_two_honesty_lines():
    """`not_financial_advice` aur `past_data_only` hataayi na ja sakein."""
    series, _ = md.series_from_text(
        "\n".join(f"[S1] {2000 + i}: {10 + i} %" for i in range(10)))
    payload = series.to_dict()
    assert md.NOT_ADVICE_NOTE in payload["not_financial_advice"]
    assert md.BACKTEST_NOTE in payload["past_data_only"]
    assert payload["n_points"] == 10
    assert payload["first_period"] == "2000"


# ── 2. walk-forward — baseline se muqabla, aur koi look-ahead nahi ────────────

def test_walk_forward_without_series_says_it_did_not_run():
    outcome = md.walk_forward(None)
    assert outcome.ok is False
    assert outcome.reason_code == md.NO_SERIES
    assert outcome.beats_naive is None


def test_walk_forward_refuses_a_short_series():
    series, _ = md.series_from_text(
        "\n".join(f"[S1] {2000 + i}: {10 + i} %" for i in range(9)))
    outcome = md.walk_forward(series, min_points=20)
    assert outcome.ok is False
    assert outcome.reason_code == md.TOO_SHORT


def test_walk_forward_has_no_look_ahead():
    """Har step par forecast SIRF us se pehle ke data se banta hai.

    Naap: held-out ka aakhri point badal do. Uske pehle ke saare forecast
    waise hi rehne chahiye — agar model ne aage jhaanka hota, to pehle ke
    nateeje bhi hil jaate.
    """
    values = _rising(14)
    first = md.walk_forward(md.series_from_pairs(
        [(f"{2000 + i}", v) for i, v in enumerate(values)], "t")[0])
    bumped = list(values)
    bumped[-1] = bumped[-1] + 1000.0
    second = md.walk_forward(md.series_from_pairs(
        [(f"{2000 + i}", v) for i, v in enumerate(bumped)], "t")[0])
    assert first.n_train == second.n_train and first.n_test == second.n_test
    # Aakhri step ki galti badli (wahi point badla hai), par uske pehle ke
    # steps ka hisaab bilkul wahi hai: model_mae ka farak SIRF aakhri step se
    # aata hai, isliye n_test * MAE ka farak = 1000 (na kam, na zyada).
    delta = second.model_mae * second.n_test - first.model_mae * first.n_test
    assert abs(delta - 1000.0) < 1e-6


def test_walk_forward_pass_needs_beating_the_naive_baseline():
    """Drift model naive random-walk se KAM galti kare, tabhi pass."""
    good = md.walk_forward(md.series_from_pairs(
        [(f"{2000 + i}", v) for i, v in enumerate(_rising(14))], "t")[0])
    assert good.ok is True and good.beats_naive is True
    assert good.model_mae < good.naive_mae

    # Chadhta train, girta held-out — drift ulta pad jaata hai.
    values = [100, 110, 120, 130, 140, 150, 160, 170, 180, 190,
              180, 170, 160, 150]
    bad = md.walk_forward(md.series_from_pairs(
        [(f"{2000 + i}", float(v)) for i, v in enumerate(values)], "t")[0])
    assert bad.ok is True and bad.beats_naive is False
    assert bad.model_mae >= bad.naive_mae


def test_two_sources_are_never_stitched_into_one_series():
    """S2 ka 2019 + S7 ka 2020 mila kar series banana sabse khatarnak jodh-tod.

    Alag-alag source ki naap alag basis par hoti hai; unhe jod kar backtest
    chalana ek aisi cheez ko test karna hota jo kisi ne naapi hi nahi.
    """
    half_a = [f"[S2] {2001 + i}: {10 + i} %" for i in range(6)]
    half_b = [f"[S7] {2007 + i}: {16 + i} %" for i in range(6)]
    series, reason = md.series_from_text("\n".join(half_a + half_b))
    assert series is None
    assert reason == md.TOO_SHORT          # dono dher chhote hain, jode nahi gaye


def test_flat_holdout_gives_no_winner():
    """Held-out hila hi nahi — aise data par har model 'sahi' lagta hai."""
    flat = md.walk_forward(md.series_from_pairs(
        [(f"{2000 + i}", 100.0) for i in range(14)], "t")[0])
    assert flat.naive_mae == 0.0
    assert flat.beats_naive is None
    assert flat.direction == ""
    # Flat step par "disha sahi bata di" muft ka credit hota — wo bhi 0 ho.
    assert flat.scored == 0 and flat.hits == 0


def test_walk_forward_dict_is_never_a_proof():
    outcome = md.walk_forward(md.series_from_pairs(
        [(f"{2000 + i}", v) for i, v in enumerate(_rising(14))], "t")[0])
    payload = outcome.to_dict()
    assert payload["is_established_fact"] is False
    assert md.BACKTEST_NOTE in payload["past_data_only"]
    assert md.NOT_ADVICE_NOTE in payload["not_financial_advice"]
    assert payload["beats_naive_baseline"] is True
    # Aur haar/flat par wahi field sach bole — warna dict me hamesha jeet likhi
    # ja sakti hai chahe hisaab kuch bhi kehta ho.
    losing = [100, 110, 120, 130, 140, 150, 160, 170, 180, 190,
              180, 170, 160, 150]
    lost = md.walk_forward(md.series_from_pairs(
        [(f"{2000 + i}", float(v)) for i, v in enumerate(losing)], "t")[0])
    assert lost.to_dict()["beats_naive_baseline"] is False
    flat = md.walk_forward(md.series_from_pairs(
        [(f"{2000 + i}", 100.0) for i in range(14)], "t")[0])
    assert flat.to_dict()["beats_naive_baseline"] is None


def test_walk_forward_is_deterministic():
    pairs = [(f"{2000 + i}", v) for i, v in enumerate(_rising(16))]
    one = md.walk_forward(md.series_from_pairs(pairs, "t")[0]).to_dict()
    two = md.walk_forward(md.series_from_pairs(pairs, "t")[0]).to_dict()
    assert one == two


# ── 3. provider payload → series (200-with-error-body ka trap) ───────────────

def test_alpha_vantage_note_is_a_rate_limit_not_zero_data():
    """HTTP 200 + "Note" = throttle. Use "0 data" kehna wahi purana jhooth hai."""
    series, reason = md.parse_alpha_vantage(
        {"Note": "Thank you for using Alpha Vantage! standard API rate limit"})
    assert series is None
    assert reason == md.PROVIDER_THROTTLED
    assert reason != md.NO_PERIODS


def test_world_bank_and_fred_payloads_become_series():
    wb = [{"page": 1}, [{"indicator": {"id": "FP.CPI.TOTL.ZG",
                                       "value": "Inflation"},
                         "country": {"value": "India"},
                         "date": str(2000 + i), "value": 4.0 + 0.3 * i}
                        for i in range(12)]]
    series, reason = md.parse_world_bank(wb)
    assert reason == "" and series is not None
    assert series.provider == "world_bank_series" and len(series.points) == 12

    fred = {"observations": [{"date": f"{2000 + i}-01-01", "value": str(100 + i)}
                             for i in range(12)]}
    series2, reason2 = md.parse_fred(fred)
    assert reason2 == "" and series2 is not None and len(series2.points) == 12


def test_missing_observations_are_dropped_but_counted():
    """Provider "." bhejta hai — usko 0 maan lena data banana hota."""
    fred = {"observations": ([{"date": "2000-01-01", "value": "."}]
                             + [{"date": f"{2001 + i}-01-01",
                                 "value": str(100 + i)} for i in range(12)])}
    series, reason = md.parse_fred(fred)
    assert reason == "" and series is not None
    assert len(series.points) == 12
    assert "1 observation" in series.note
    assert all(point.value != 0.0 for point in series.points)


# ── 4 + 5. connector: key ka value kabhi bahar nahi, aur no_key ≠ khaali ─────

def _router(payload_by_kind):
    def route(url, params):
        if "worldbank" in url:
            return payload_by_kind.get("wb")
        if "ecb" in url:
            return payload_by_kind.get("ecb")
        if "series/search" in url:
            return payload_by_kind.get("fred_search")
        if "observations" in url:
            return payload_by_kind.get("fred")
        if params.get("function") == "SYMBOL_SEARCH":
            return payload_by_kind.get("av_search")
        return payload_by_kind.get("av")
    return route


_WB_PAYLOAD = [{"page": 1},
               [{"indicator": {"id": "FP.CPI.TOTL.ZG", "value": "Inflation"},
                 "country": {"value": "India"}, "date": str(2000 + i),
                 "value": 4.0 + 0.3 * i} for i in range(14)]]
_FRED_PAYLOAD = {"observations": [{"date": f"{2000 + i}-01-01",
                                   "value": str(100 + 2 * i)}
                                  for i in range(14)]}


def test_missing_key_reports_stopped_not_empty():
    """Key nahi hai to "search hui hi nahi" — "kuch nahi mila" NAHI."""
    with _EnvGuard(FRED_API_KEY=None, ALPHA_VANTAGE_API_KEY=None):
        with _StubHttp(_router({})):
            result = mc.FredSeriesConnector().safe_search("us cpi", 1)
    assert result["count"] == 0
    assert result["reason"] == "no_key"
    # Naam batana theek hai (user ko batana hi hai kya set karna hai)...
    assert "FRED_API_KEY" in result["error"]
    # ...par lane band nahi hoti: keyless raasta bhi likha ho.
    assert "world_bank_series" in result["error"]


def test_api_key_value_never_appears_in_output():
    """Key query param me jaati hai, isliye error/note dono scrub hote hain."""
    secret = "TOPSECRET-FRED-VALUE-9999"

    def blow_up(url, params):
        raise RuntimeError(f"connection failed for {url}?api_key={secret}")

    with _EnvGuard(FRED_API_KEY=secret):
        with _StubHttp(blow_up):
            result = mc.FredSeriesConnector().safe_search("us cpi", 1)
    blob = json.dumps({k: str(v) for k, v in result.items() if k != "records"})
    assert secret not in blob
    assert result["count"] == 0
    # `_scrub` ka apna naap bhi pin ho — module-level rule hai, sirf ittefaq nahi.
    assert mc._scrub(f"url?api_key={secret}", secret) == "url?api_key=<hidden-key>"


def test_provider_throttle_becomes_rate_limited_in_the_log():
    throttle = {"Note": "standard API rate limit is 25 requests per day"}
    with _EnvGuard(ALPHA_VANTAGE_API_KEY="AVKEY-1234"):
        with _StubHttp(_router({"av_search": throttle, "av": throttle})):
            result = mc.AlphaVantageConnector().safe_search("reliance share", 1)
    assert result["count"] == 0
    assert result["reason"] == "rate_limited"
    assert "AVKEY-1234" not in json.dumps({k: str(v) for k, v in result.items()
                                           if k != "records"})


def test_keyless_provider_record_carries_the_series():
    with _EnvGuard(FRED_API_KEY=None, ALPHA_VANTAGE_API_KEY=None):
        with _StubHttp(_router({"wb": _WB_PAYLOAD})) as stub:
            result = mc.WorldBankSeriesConnector().safe_search(
                "india cpi inflation last 20 years", 1)
    assert result["count"] == 1
    record = result["records"][0]
    assert isinstance(record, SourceRecord)
    assert record.source_type == SourceType.DATASET
    assert record.read_level == "full" and record.is_primary is True
    # Peer review data par lagta hi nahi — jhoothi mohar na lage.
    assert record.peer_reviewed is None
    meta = record.series_meta
    assert meta["provider"] == "world_bank_series" and meta["n_points"] == 14
    assert md.NOT_ADVICE_NOTE in meta["not_financial_advice"]
    # Sirf official host, aur bounded window.
    url, params = stub.calls[0]
    assert url.startswith("https://api.worldbank.org/v2/country/")
    assert params["per_page"] == md.MAX_SERIES_POINTS


def test_key_gated_providers_are_hidden_until_the_key_exists():
    facade = mc.MarketConnector()
    with _EnvGuard(FRED_API_KEY=None, ALPHA_VANTAGE_API_KEY=None):
        without = facade.available_names()
    with _EnvGuard(FRED_API_KEY="k-value-1", ALPHA_VANTAGE_API_KEY="k-value-2"):
        with_keys = facade.available_names()
    assert without == ["world_bank_series", "ecb_series"]
    assert with_keys == ["world_bank_series", "ecb_series", "fred",
                        "alpha_vantage"]
    # Keyless pehle — quota wala provider tab hi jab wo sach me maujood ho.
    assert with_keys[:2] == without


def test_every_market_host_is_on_the_allowlist():
    """SSRF boundary: naya provider add karna = allowlist me naam daalna."""
    for host in ("api.worldbank.org", "data-api.ecb.europa.eu",
                 "api.stlouisfed.org", "www.alphavantage.co"):
        assert host in cbase.DISCOVERY_ALLOWED_HOSTS


# ── 6. discovery + planner routing ───────────────────────────────────────────

def test_market_tier_runs_only_when_the_plan_asks_for_it():
    discovery = SourceDiscovery()
    empty = discovery._tasks(["india cpi"], {"web": False}, 3, 5)
    assert [label for label, _ in empty if "series" in label
            or label in ("fred", "alpha_vantage")] == []
    asked = discovery._tasks(["india cpi"],
                             {"web": False, "markets": ["world_bank_series"]},
                             3, 5)
    assert [label for label, _ in asked] == ["world_bank_series"]


def test_market_tier_is_bounded_to_two_results():
    """Provider rate-limited hai — ek round me 2 se zyada nahi maangte."""
    discovery = SourceDiscovery()
    seen = {}

    class _Spy:
        name = "world_bank_series"

        def safe_search(self, query, limit):
            seen["limit"] = limit
            seen["query"] = query
            return {"records": [], "count": 0}

    discovery.markets.by_name = lambda name: _Spy()
    tasks = discovery._tasks(["primary q", "second q"],
                             {"web": False, "markets": ["world_bank_series"]},
                             9, 5)
    assert len(tasks) == 1          # sirf PRIMARY query par
    tasks[0][1]()
    assert seen["limit"] == 2 and seen["query"] == "primary q"


def test_planner_opens_the_lane_only_for_market_questions():
    planner = ResearchPlanner()
    config = depth.get_depth_config("DEEP")
    market_q = "nifty ke liye trading model banao aur backtest karo"
    plan = planner.connector_plan({"question": market_q}, config,
                                  question=market_q)
    assert plan["markets"], "market sawaal par lane band nahi honi chahiye"
    assert plan["market_intent"]["wanted"] is True
    assert md.NOT_ADVICE_NOTE in plan["market_intent"]["not_financial_advice"]

    physics_q = "room temperature superconductivity kaise hoti hai"
    plan2 = planner.connector_plan({"question": physics_q}, config,
                                   question=physics_q)
    assert plan2["markets"] == []
    assert plan2["market_intent"]["wanted"] is False
    # Chup-chaap band nahi — wajah likhi ho.
    assert plan2["market_intent"]["reason"]


def test_market_intent_needs_both_a_signal_and_a_time_ask():
    """Sirf "gdp" likha hona quota kharch karne ki wajah nahi."""
    both = md.market_intent("india gdp growth trend last 20 years")
    assert both["wanted"] is True
    assert both["market_signal"] is True and both["series_ask"] is True
    only_word = md.market_intent("gdp ka matlab kya hota hai")
    assert only_word["wanted"] is False


def test_source_record_has_an_empty_series_slot_by_default():
    """Khaali dict = koi series nahi. None rakhna callers ko todta hai."""
    record = SourceRecord(title="t", url="u", snippet="s")
    assert record.series_meta == {}


# ── 7. lab half — jo chala uska naam, jo nahi chala uski wajah ───────────────

def test_no_series_keeps_the_old_honest_wording():
    """#116 ka contract: series na ho to aaj bhi "test hua hi nahi"."""
    report = lab.run_lab("q", [_hyp("RV-HYP-A")])
    test = _walk_test(report)
    assert test["status"] == lab.DATA_MISSING
    assert test["reason_code"] == "series_data_missing"
    assert "test ho chuka" in test["detail"]
    assert any("walk-forward test chalaya hi nahi gaya" in line
               for line in lab.lab_limits(report))
    # "series thi hi nahi" ko "series test-layak nahi thi" ke bucket me daalna
    # ulta matlab de deta — wo line yahan NAHI aani chahiye.
    assert not any("backtest-layak nahi nikli" in line
                   for line in lab.lab_limits(report))


def test_provider_series_makes_the_backtest_actually_run():
    pack = _Pack(_Src("S3", _meta(_rising(14))))
    report = lab.run_lab("cpi forecast", [_hyp("RV-HYP-B")], pack=pack)
    test = _walk_test(report)
    assert test["status"] == lab.TESTED_PASS
    assert test["reason_code"] == "model_beats_naive_baseline"
    assert "train 10" in test["observed"] and "naive" in test["observed"]
    assert test["evidence_ids"] == ["S3"]
    # Pass hona proof nahi, aur advice bilkul nahi.
    assert test["is_established_fact"] is False
    assert test["real_world_experiment_pending"] is True
    assert md.BACKTEST_NOTE in test["detail"]
    assert md.NOT_ADVICE_NOTE in test["detail"]


def test_a_model_losing_to_the_baseline_is_a_real_fail():
    """Haar ko DATA_MISSING likhna hypothesis ko bacha lena hota."""
    values = [100, 110, 120, 130, 140, 150, 160, 170, 180, 190,
              180, 170, 160, 150]
    pack = _Pack(_Src("S4", _meta(values)))
    report = lab.run_lab("q", [_hyp("RV-HYP-C")], pack=pack)
    test = _walk_test(report)
    assert test["status"] == lab.TESTED_FAIL
    assert test["reason_code"] == "model_loses_to_naive_baseline"
    assert report["hypotheses"][0]["verdict"] == lab.TESTED_FAIL


def test_flat_holdout_is_neither_pass_nor_fail():
    pack = _Pack(_Src("S5", _meta([100.0] * 14)))
    report = lab.run_lab("q", [_hyp("RV-HYP-D")], pack=pack)
    test = _walk_test(report)
    assert test["status"] == lab.DATA_MISSING
    assert test["reason_code"] == md.FLAT_HOLDOUT
    assert test["status"] != lab.TESTED_PASS


def test_unusable_series_is_not_reported_as_missing_data():
    """"series thi par test-layak nahi" aur "series hi nahi thi" alag lines hain."""
    pack = _Pack(_Src("S6", None, snippet="Table 2019 2020 2021 shows growth"))
    report = lab.run_lab("q", [_hyp("RV-HYP-E")], pack=pack)
    test = _walk_test(report)
    assert test["reason_code"] == md.NO_PERIODS
    limits = lab.lab_limits(report)
    assert any("backtest-layak nahi nikli" in line for line in limits)
    assert not any("time-ordered data nahi tha" in line for line in limits)


def test_evidence_text_series_is_used_when_no_provider_series_exists():
    text = "\n".join(f"{2000 + i}: {100 + 2 * i} %" for i in range(12))
    pack = _Pack(_Src("S8", None, snippet=text))
    report = lab.run_lab("q", [_hyp("RV-HYP-F")], pack=pack)
    test = _walk_test(report)
    assert test["status"] in (lab.TESTED_PASS, lab.TESTED_FAIL)
    assert "evidence_text" in test["observed"]


def test_provider_series_wins_over_text_numbers():
    """Provider ka naapa hua data text se nikaale number se pehle aata hai."""
    junk_text = "\n".join(f"{1900 + i}: {i} %" for i in range(30))
    pack = _Pack(_Src("S9", _meta(_rising(14), provider="fred",
                                  series_id="CPIAUCSL"), snippet=junk_text))
    report = lab.run_lab("q", [_hyp("RV-HYP-G")], pack=pack)
    test = _walk_test(report)
    assert "fred/CPIAUCSL" in test["observed"]


def test_backtest_run_stays_free_and_offline():
    """Backtest chalne par bhi ₹0, zero Gemini call, zero network."""
    pack = _Pack(_Src("S10", _meta(_rising(14))))
    report = lab.run_lab("q", [_hyp("RV-HYP-H")], pack=pack)
    assert report["gemini_calls"] == 0 and report["provider_cost"] == 0
    assert report["policy"]["network_used"] is False
    assert report["policy"]["randomness_used"] is False
    assert report["policy"]["model_written_code_executed"] is False
    assert report["hypotheses"][0]["is_established_fact"] is False


def test_lab_limits_names_the_backtest_that_ran():
    pack = _Pack(_Src("S11", _meta(_rising(14))))
    report = lab.run_lab("q", [_hyp("RV-HYP-I")], pack=pack)
    limits = lab.lab_limits(report)
    assert any("PURANE (out-of-sample) data par" in line for line in limits)
    assert any("financial advice nahi" in line for line in limits)
    # Aur jo line "data nahi tha" kehti hai, wo yahan NAHI honi chahiye.
    assert not any("time-ordered data nahi tha" in line for line in limits)
    # Chala hua backtest "test-layak nahi thi" ke bucket me bhi nahi jaana chahiye.
    assert not any("backtest-layak nahi nikli" in line for line in limits)


def test_lab_policy_pins_the_series_ceilings():
    """Chhat market_data se aati hai — do jagah likhne se dono bikhar jaati."""
    policy = lab.LabPolicy().to_dict()
    assert policy["min_series_points"] == md.MIN_SERIES_POINTS
    assert policy["min_holdout_points"] == md.MIN_HOLDOUT_POINTS
    assert policy["train_fraction"] == md.TRAIN_FRACTION


def test_policy_ceiling_is_actually_obeyed():
    """Chhat badhao to wahi series ab test-layak na rahe — warna knob jhootha hai."""
    pack = _Pack(_Src("S12", _meta(_rising(14))))
    strict = lab.LabPolicy(min_series_points=40)
    report = lab.run_lab("q", [_hyp("RV-HYP-J")], pack=pack, policy=strict)
    test = _walk_test(report)
    assert test["status"] == lab.DATA_MISSING
    assert test["reason_code"] == md.TOO_SHORT


def test_spec_dict_shows_where_the_series_came_from():
    pack = _Pack(_Src("S13", _meta(_rising(14), provider="ecb_series")))
    specs = lab.plan_specs(_hyp("RV-HYP-K"), pack)
    rows = [s for s in specs if s.recipe == "walk_forward"]
    assert rows and rows[0].series is not None
    payload = rows[0].to_dict()
    assert payload["series_provider"] == "ecb_series"
    assert payload["series_points"] == 14
    assert payload["series_reason"] == ""
    assert payload["model_written_code"] is False


def test_non_forecast_claim_makes_no_walk_forward_spec():
    """Har hypothesis par backtest ka plan banana report me bekaar shor hai."""
    specs = lab.plan_specs(_hyp("RV-HYP-L", "Ye material 250 K par kaam karega."),
                           _Pack(_Src("S14", _meta(_rising(14)))))
    assert [s for s in specs if s.recipe == "walk_forward"] == []
