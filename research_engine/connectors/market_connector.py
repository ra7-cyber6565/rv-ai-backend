"""MarketConnector — market/economic TIME SERIES ka lane (#118).

Kyun alag connector: baaki dataset connectors CATALOGUE dhoondhte hain ("ye
dataset maujood hai, yahan milega"). Backtest ke liye catalogue kaam ka nahi —
uske liye ASLI period→value series chahiye, waqt ke kram mein. Ye lane wahi
laata hai, aur use `SourceRecord.series_meta` mein baith kar aage bhejta hai,
jahan se LAB (`research_engine/lab.py`) bina koi network call kiye
walk-forward test chala sakta hai.

Kaise: sirf providers ke APNE OFFICIAL public API. Koi HTML scraping nahi,
koi third-party mirror nahi, koi "unofficial endpoint" nahi (§2 ka rule).
Keyless provider PEHLE — key wala provider key na hone par `ConnectorSkipped`
deta hai, jo report mein "ruka (API key nahi hai)" bucket mein jaata hai,
"khaali (kuch nahi mila)" mein NAHI.

TEEN JHOOTH jo ye file jaan-boojh kar nahi bolti:
  1. **Key ka value kabhi log/nota/error mein nahi.** FRED aur Alpha Vantage
     key ko QUERY PARAM mein maangte hain, isliye har error message aur note
     `_scrub()` se guzarta hai. `public_error()` bhi raw exception text nahi
     deta, par do deewar ek se behtar hai — kyunki yahan key URL ke andar hai.
  2. **Provider ka HTTP 200 + "Note" = data nahi hai.** Alpha Vantage throttle
     hone par 200 bhejta hai aur body mein "Note"/"Information" likhta hai.
     Use "0 result" maan lena wahi jhooth hai jo `base.py` ke `ConnectorSkipped`
     ne theek kiya tha. Isliye wo `RateLimited` ban kar uthta hai.
  3. **Ye financial advice nahi hai.** Har series ka `series_meta` apne saath
     `not_financial_advice` aur `past_data_only` line le kar chalta hai
     (`market_data.MarketSeries.to_dict()`), isliye report mein wo line
     hataayi nahi ja sakti chup-chaap.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from .. import market_data as md
from ..models import SourceRecord, SourceType
from .base import (SLOW_TIMEOUT, BaseConnector, ConnectorSkipped, RateLimited,
                   http_get)

# Providers ke default series — jab sawaal se koi khaas series id na bane.
# Ye "knowledge list" NAHI hai (kya sach hai wo isse tay nahi hota); ye sirf
# ek START point hai taaki lane khaali na baithe. Series ka faisla query se
# hota hai (`_pick`), aur na bane to ye default.
WORLD_BANK_DEFAULT = "FP.CPI.TOTL.ZG"        # CPI inflation, annual %
WORLD_BANK_COUNTRY = "IND"
FRED_DEFAULT = "CPIAUCSL"                    # US CPI, monthly index
ECB_DEFAULT = "EXR/M.USD.EUR.SP00.A"         # EUR/USD monthly average

# Kitne saal peeche tak (bounded — poora itihaas maangna provider par bojh hai)
DEFAULT_YEARS = 25
MAX_POINTS = md.MAX_SERIES_POINTS


def _scrub(text: str, *secrets: str) -> str:
    """Key ka value kabhi bahar na jaaye — naam bhale jaaye.

    `str(exc)` mein poora URL aa sakta hai (`...&api_key=abcd`). Yahan value
    ko uske NAAM se badla jaata hai, taaki message padhne layak rahe:
    "api_key=<FRED_API_KEY>". Chhoti value (<8 char) bhi badli jaati hai, kyunki
    galat/adhoori key bhi secret hi hai.
    """
    out = str(text or "")
    for secret in secrets:
        value = (secret or "").strip()
        if len(value) >= 4:
            out = out.replace(value, "<hidden-key>")
    return out


class _SeriesConnector(BaseConnector):
    """Common base — record banane ka ek hi tareeka, taaki labels na bhatken."""

    source_type = SourceType.DATASET
    timeout: Tuple[int, int] = SLOW_TIMEOUT
    provider_label = "provider"
    home_url = ""

    def record(self, series: md.MarketSeries, url: str) -> SourceRecord:
        """Ek series = ek SourceRecord, aur uska data `series_meta` mein.

        `snippet` mein series ka SAAF summary jaata hai (kitne point, kab se kab
        tak, unit) — number bhi list hote hain taaki text-only path bhi
        (`market_data.series_from_text`) inhe padh sake agar `series_meta`
        kahin gum ho jaaye. Ye guess nahi hai: yehi wo values hain jo provider
        ne di.
        """
        pairs = ", ".join(f"{p.period} {p.value:g}" for p in series.points[:60])
        unit = f" ({series.unit})" if series.unit else ""
        return SourceRecord(
            title=f"{series.label or series.series_id} — {self.provider_label}",
            url=url or self.home_url,
            snippet=self._clean(
                f"{md.SERIES_LABEL}{unit}: {len(series.points)} point, "
                f"{series.first_period()} se {series.last_period()} tak. "
                f"{pairs}", 1500),
            connector=self.name,
            source_type=SourceType.DATASET,
            publisher=self.provider_label,
            is_primary=True,          # provider ka apna data
            peer_reviewed=None,       # data peer-review nahi hota
            full_text_available=True,
            # #186c: pehle yahan "full" likha tha — aur wo `models.py` ki
            # READ_LEVEL_ORDER me maujood hi nahi hai. Natija naapa gaya:
            # `Source.reading_level()` value jaisi-ki-taisi lautata hai, isliye
            # `access_depth()` ka fallback lag kar ye series "METADATA ONLY"
            # (content dekha hi nahi gaya) dikhti thi, aur `read_level_counts()`
            # sirf READ_LEVEL_ORDER ke naam ginta hai — matlab poori padhi hui
            # series ginti se hi gayab thi. Sahi naam "full_text" hai.
            read_level="full_text",   # series poori padhi gayi hai
            series_meta=series.to_dict(),
        )

    def note_for(self, reason: str, series_id: str) -> str:
        """Series na banne par imaandaar wajah — reason code chhupta nahi."""
        return (f"{self.provider_label} se {series_id} ka jawab aaya par usse "
                f"test-layak series nahi bani (wajah: {reason or 'unknown'}) — "
                f"isliye is par koi backtest nahi chalega")


# ── query → provider address ─────────────────────────────────────────────────
# NOTE (open-knowledge rule): niche ki do tables KNOWLEDGE nahi hain. Ye
# ADDRESSING hain — "World Bank ke server par is cheez ka code kya hai". Kaun
# concept sahi hai, kaunsa lens lagega, kya sach hai — wo faisla aaj bhi
# `domain.py` / `lenses.py` / evidence ke paas hai, aur is file se uska koi
# lena-dena nahi. Table mein match na ho to lane band nahi hota: default
# indicator chalta hai aur record mein saaf likha hota hai kaunsi series aayi.
_WB_INDICATORS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("FP.CPI.TOTL.ZG", ("inflation", "cpi", "mehngai", "mahangai", "price index")),
    ("NY.GDP.MKTP.KD.ZG", ("gdp growth", "growth rate", "vikas dar")),
    ("NY.GDP.MKTP.CD", ("gdp", "economy size", "arthvyavastha")),
    ("SL.UEM.TOTL.ZS", ("unemployment", "berozgari", "jobless")),
    ("FR.INR.RINR", ("real interest", "interest rate", "byaj")),
    ("PA.NUS.FCRF", ("exchange rate", "rupee", "currency rate")),
    ("SP.POP.TOTL", ("population", "aabadi", "jansankhya")),
    ("NE.EXP.GNFS.ZS", ("exports", "niryat")),
    ("NE.IMP.GNFS.ZS", ("imports", "aayat")),
)
_WB_COUNTRIES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("IND", ("india", "indian", "bharat", "nifty", "sensex", "rupee", "rbi")),
    ("USA", ("usa", "us ", "united states", "america", "fed", "dollar",
             "s&p", "nasdaq", "dow")),
    ("CHN", ("china", "chinese", "yuan")),
    ("GBR", ("uk", "britain", "british", "pound")),
    ("JPN", ("japan", "japanese", "yen")),
    ("DEU", ("germany", "german")),
    ("WLD", ("world", "global", "duniya")),
)


def _pick(query: str, table) -> str:
    """Sabse pehla match — table ka kram hi priority hai. Match na ho to ""."""
    low = f" {(query or '').lower()} "
    for code, hints in table:
        for hint in hints:
            if hint in low:
                return code
    return ""


class WorldBankSeriesConnector(_SeriesConnector):
    """World Bank Indicators API — keyless, official, poora itihaas deta hai.

    `datasets` lane ka `world_bank` connector CATALOGUE search karta hai
    (kaunsa dataset hai). Ye uska bhai nahi, alag kaam hai: yahan se seedhe
    period→value aate hain (`/v2/country/<iso>/indicator/<code>`), isliye
    iska naam bhi alag hai (`world_bank_series`) — log mein dono gum na ho jaayein.
    """

    name = "world_bank_series"
    provider_label = "World Bank (Indicators API)"
    home_url = "https://data.worldbank.org"
    # Live run par World Bank ne pehle 429 diya tha (dataset lane ka note),
    # isliye yahan bhi sach likha hai: free hai, par throttle ho sakta hai.
    rate_limited = True

    def address(self, query: str) -> Tuple[str, str]:
        """(indicator, country) — match na ho to imaandaar default."""
        return (_pick(query, _WB_INDICATORS) or WORLD_BANK_DEFAULT,
                _pick(query, _WB_COUNTRIES) or WORLD_BANK_COUNTRY)

    def build_url(self, indicator: str, country: str) -> str:
        return (f"https://api.worldbank.org/v2/country/{country}"
                f"/indicator/{indicator}")

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        indicator, country = self.address(query)
        resp = http_get(self.build_url(indicator, country),
                        params={"format": "json", "per_page": MAX_POINTS,
                                "date": f"{_start_year()}:2100"},
                        timeout=self.timeout)
        series, reason = md.parse_world_bank(
            resp.json() if hasattr(resp, "json") else None)
        if series is None:
            self.last_note = self.note_for(reason, f"{country}/{indicator}")
            return []
        url = (f"https://data.worldbank.org/indicator/{indicator}"
               f"?locations={country}")
        return [self.record(series, url)]


def _start_year() -> int:
    """Bounded window — poora itihaas maangna provider par bekaar bojh hai."""
    try:
        import datetime
        return max(1960, datetime.date.today().year - DEFAULT_YEARS)
    except Exception:
        return 2000


class EcbSeriesConnector(_SeriesConnector):
    """ECB Data Portal (SDMX-JSON) — keyless, official.

    Exchange rate ke sawaal par ye sabse saaf keyless source hai. Currency ka
    faisla sawaal me likhe ISO code se hota hai (kisi list se nahi): "USD",
    "JPY", "GBP" jaise teen-akshar code khud sawaal me hote hain.
    """

    name = "ecb_series"
    provider_label = "European Central Bank (Data Portal)"
    home_url = "https://data.ecb.europa.eu"

    _CURRENCY = ("USD", "GBP", "JPY", "INR", "CHF", "CNY", "AUD", "CAD")

    def address(self, query: str) -> str:
        """`EXR/M.<CUR>.EUR.SP00.A` — sawaal me code na ho to default."""
        upper = f" {(query or '').upper()} "
        for code in self._CURRENCY:
            if code in upper:
                return f"EXR/M.{code}.EUR.SP00.A"
        return ECB_DEFAULT

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        address = self.address(query)
        resp = http_get(f"https://data-api.ecb.europa.eu/service/data/{address}",
                        params={"format": "jsondata",
                                "lastNObservations": MAX_POINTS},
                        timeout=self.timeout)
        series, reason = md.parse_ecb_sdmx(
            resp.json() if hasattr(resp, "json") else None)
        if series is None:
            self.last_note = self.note_for(reason, address)
            return []
        series.series_id = series.series_id or address
        series.label = series.label or f"ECB {address}"
        return [self.record(series, f"https://data.ecb.europa.eu/data/datasets/"
                                    f"EXR")]


class FredSeriesConnector(_SeriesConnector):
    """FRED (St. Louis Fed) — free key chahiye, isliye key na hone par SKIP.

    FRED ka apna `series/search` endpoint hai, isliye yahan koi hath se likhi
    indicator list nahi hai: sawaal seedha provider ke search par jaata hai aur
    provider hi bataata hai kaunsi series uske paas hai. Ye is lane ka sabse
    khula raasta hai.
    """

    name = "fred"
    provider_label = "FRED (Federal Reserve Bank of St. Louis)"
    home_url = "https://fred.stlouisfed.org"
    free = False              # key chahiye — quota disclosure me imaandaari
    rate_limited = True

    @staticmethod
    def api_key() -> str:
        return (os.getenv("FRED_API_KEY") or "").strip()

    def _find_series(self, key: str, query: str) -> Tuple[str, str]:
        """(series_id, title) — provider ke apne search se. Na mile to ("","")."""
        try:
            resp = http_get("https://api.stlouisfed.org/fred/series/search",
                            params={"search_text": query, "api_key": key,
                                    "file_type": "json", "limit": 1,
                                    "order_by": "popularity",
                                    "sort_order": "desc"},
                            timeout=self.timeout)
            payload = resp.json() if hasattr(resp, "json") else {}
        except RateLimited:
            raise
        except Exception as exc:
            self.last_note = _scrub(f"FRED series search nahi chali: {exc}", key)
            return "", ""
        rows = (payload or {}).get("seriess") or []
        first = rows[0] if rows and isinstance(rows[0], dict) else {}
        return str(first.get("id") or ""), str(first.get("title") or "")

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        key = self.api_key()
        if not key:
            raise ConnectorSkipped(
                "FRED_API_KEY .env mein nahi hai — FRED se koi series maangi hi "
                "nahi gayi (ye 'data nahi mila' se alag baat hai). Free key "
                "https://fredaccount.stlouisfed.org/apikeys par bina card milti "
                "hai; uske bina bhi keyless market sources (world_bank_series, "
                "ecb_series) chalte hain."
            )
        series_id, title = self._find_series(key, query)
        if not series_id:
            series_id, title = FRED_DEFAULT, ""
        try:
            resp = http_get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={"series_id": series_id, "api_key": key,
                        "file_type": "json",
                        "observation_start": f"{_start_year()}-01-01",
                        "sort_order": "asc", "limit": MAX_POINTS},
                timeout=self.timeout)
            payload = resp.json() if hasattr(resp, "json") else None
        except Exception as exc:
            # Key URL ke andar hai — message dobara scrub hokar hi bahar jaaye.
            raise type(exc)(_scrub(str(exc), key)) from None
        series, reason = md.parse_fred(payload)
        if series is None:
            self.last_note = _scrub(self.note_for(reason, series_id), key)
            return []
        series.series_id = series_id
        series.label = title or series_id
        return [self.record(series,
                            f"https://fred.stlouisfed.org/series/{series_id}")]


class AlphaVantageConnector(_SeriesConnector):
    """Alpha Vantage — free key (bina card), stock/index/FX ki monthly series.

    Symbol ka faisla provider ke `SYMBOL_SEARCH` se hota hai, isliye yahan bhi
    koi ticker list nahi hai. Throttle par ye HTTP 200 + `"Note"` bhejta hai;
    us haalat me hum `RateLimited` uthate hain — "0 data" kehna jhooth hoga.
    """

    name = "alpha_vantage"
    provider_label = "Alpha Vantage"
    home_url = "https://www.alphavantage.co"
    free = False
    rate_limited = True

    @staticmethod
    def api_key() -> str:
        return (os.getenv("ALPHA_VANTAGE_API_KEY") or "").strip()

    @staticmethod
    def _throttled(payload) -> bool:
        if not isinstance(payload, dict):
            return False
        return any(str(payload.get(k) or "").strip()
                   for k in ("Note", "Information", "Error Message"))

    def _find_symbol(self, key: str, query: str) -> Tuple[str, str]:
        resp = http_get(f"{self.home_url}/query",
                        params={"function": "SYMBOL_SEARCH", "keywords": query,
                                "apikey": key},
                        timeout=self.timeout)
        payload = resp.json() if hasattr(resp, "json") else {}
        if self._throttled(payload):
            raise RateLimited(
                "Alpha Vantage ne HTTP 200 ke saath throttle note bheja "
                "(free plan ki minute/day limit) — symbol search chali hi nahi. "
                "Ise '0 data mila' mat samjho.")
        rows = (payload or {}).get("bestMatches") or []
        first = rows[0] if rows and isinstance(rows[0], dict) else {}
        return (str(first.get("1. symbol") or ""),
                str(first.get("2. name") or ""))

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        key = self.api_key()
        if not key:
            raise ConnectorSkipped(
                "ALPHA_VANTAGE_API_KEY .env mein nahi hai — Alpha Vantage se koi "
                "series maangi hi nahi gayi (ye 'data nahi mila' se alag baat "
                "hai). Free key https://www.alphavantage.co/support/#api-key par "
                "bina card milti hai; uske bina bhi keyless market sources "
                "(world_bank_series, ecb_series) chalte hain."
            )
        try:
            symbol, title = self._find_symbol(key, query)
            if not symbol:
                self.last_note = ("Alpha Vantage par is sawaal se koi symbol "
                                  "match nahi hua — koi price series nahi laayi "
                                  "gayi (banayi bhi nahi gayi)")
                return []
            resp = http_get(f"{self.home_url}/query",
                            params={"function": "TIME_SERIES_MONTHLY_ADJUSTED",
                                    "symbol": symbol, "apikey": key},
                            timeout=self.timeout)
            payload = resp.json() if hasattr(resp, "json") else None
        except RateLimited:
            raise
        except Exception as exc:
            raise type(exc)(_scrub(str(exc), key)) from None
        series, reason = md.parse_alpha_vantage(payload)
        if series is None:
            if reason == md.PROVIDER_THROTTLED:
                raise RateLimited(
                    "Alpha Vantage ne HTTP 200 ke saath throttle note bheja "
                    "(free plan ki limit) — price series aayi hi nahi. "
                    "Ise '0 data mila' mat samjho.")
            self.last_note = _scrub(self.note_for(reason, symbol), key)
            return []
        series.series_id = symbol
        series.label = title or symbol
        return [self.record(series, f"{self.home_url}/query?function="
                                    f"TIME_SERIES_MONTHLY_ADJUSTED&symbol={symbol}")]


class MarketConnector:
    """Facade — baaki facades (Web/Paper/Book/Dataset/Patent) jaisa hi interface.

    Kram maayne rakhta hai: KEYLESS official provider pehle. Key wala provider
    key na hone par `ConnectorSkipped` deta hai (log me "no_key"), isliye
    `available_names()` unhe plan me daalta hi nahi jab key nahi hai — har round
    "no_key" likhna sirf shor hai, aur planner ko bhi jhoothi ummeed deta hai.
    """

    def __init__(self):
        self.connectors: List[BaseConnector] = [
            WorldBankSeriesConnector(),
            EcbSeriesConnector(),
            FredSeriesConnector(),
            AlphaVantageConnector(),
        ]

    def by_name(self, name: str) -> Optional[BaseConnector]:
        return next((c for c in self.connectors if c.name == name), None)

    def available_names(self) -> List[str]:
        names: List[str] = []
        for connector in self.connectors:
            getter = getattr(connector, "api_key", None)
            if callable(getter) and not getter():
                continue
            names.append(connector.name)
        return names

    def search(self, query: str, max_per_source: int = 1,
               only: Optional[List[str]] = None) -> Dict:
        records: List[SourceRecord] = []
        log: List[Dict] = []
        for connector in self.connectors:
            if only and connector.name not in only:
                continue
            result = connector.safe_search(query, max_per_source)
            records.extend(result["records"])
            log.append({k: v for k, v in result.items() if k != "records"})
        return {"records": records, "log": log}


