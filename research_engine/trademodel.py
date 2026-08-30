"""#150b — TRADE MODEL: farmaish padho, 30-point contract lagao, aur NAAPO.

intel ki maang saaf hai: "model mangu to gaane waali cheeje work krti dikhe to
answer khraab ho jaaye — aesa nhi hona chahiye". Isliye trading ka kaam apne
alag darwaze se aata hai, aur us darwaze ka taala `is_request()` hai — do
signal chahiye, ek nahi (trading ki cheez ka naam + kuch BANANE ki maang).

Ye module teen kaam karta hai, teeno deterministic aur ₹0 (koi model call nahi,
koi network nahi):

    1. ASK PADHO  — kaunsa instrument, kaunse timeframe, kaunsa execution chain
       (context -> confirmation -> entry), aur user ne kaun-kaunsi sakhti maangi
       (walk-forward, monte carlo, robustness, baseline, leakage, cost, red-team).
    2. CONTRACT   — intel ke 30 section ka ek naam-wala contract. Har point ka
       apna id, apna group, aur apna naap. Default MET nahi hai — default
       NOT_MEASURED hai, WAJAH ke saath.
    3. NAAP       — jo model spec bani, usme se naapo: entry model poora hai ya
       nahi, discretionary shabd bache hain ya nahi, kaunse metric likhe gaye,
       leakage/cost/OOS ka elaan hua ya nahi, kitni competing hypothesis thi.

JO YE MODULE JAAN-BOOJH KAR NAHI KARTA (aur report me naam se likhta hai):

  * Koi live ya demo trade nahi chalta (`LIVE_TESTED = False`), koi broker se
    connection nahi (`BROKER_CONNECTED = False`). "Ye model chalega" ka daawa
    yahan se nikal hi nahi sakta.
  * Tick data, Level-2 order book, footprint aur futures order flow — inka koi
    free/keyless official source is app me nahi hai (`ORDER_BOOK_READ = False`).
    Isliye "order flow ka edge" wala point contract me MET ho hi nahi sakta; wo
    NOT_MEASURED rehta hai, apni wajah ke saath. Ye chhupaana nahi hai.
  * Ye financial advice NAHI hai (`NOT_ADVICE_NOTE`, wahi ek line jo
    `market_data.py` bolta hai — do jagah do bhasha nahi).
  * Backtest future ka waada nahi hai (`BACKTEST_IS_NOT_FUTURE`), aur 90%+ win
    rate ka daawa mile to wo PASS nahi — wo khud ek FAIL check hai
    (`win_rate_not_chased`).
  * Instrument/timeframe ki table sirf ADDRESSING hai
    (`INSTRUMENT_LIST_IS_NOT_EXHAUSTIVE`) — "user ne kis cheez ka naam liya".
    Us instrument ka asli behaviour is table me likha HI NAHI hai; wo padhi hui
    source aur naapi hui series se aata hai.
  * Kisi concept ko naam ki wajah se sach nahi maanta. ICT, SMC, Wyckoff, Market
    Profile — sab `CONCEPTS_EARN_THEIR_PLACE` ke andar aate hain: bina exact
    algorithmic definition + baseline + sample size + out-of-sample number, unka
    point NOT_MET rehta hai.

Ek hi spec par wahi number, har baar — koi randomness nahi.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .market_data import BACKTEST_NOTE, NOT_ADVICE_NOTE

SCHEMA_VERSION = "trademodel-1"

# ── naap ki zubaan ────────────────────────────────────────────────────────────
# Ye teen literal `craft.py` se import NAHI kiye jaate: craft gaane ki lane ka
# module hai aur use trading me kheenchna wahi mixing hai jisse intel ne roka.
# Test `trademodel.MET == craft.MET` ko pin karta hai, taaki bhasha ek rahe.
MET = "MET"
NOT_MET = "NOT_MET"
NOT_MEASURED = "NOT_MEASURED"
CHECK_STATUSES: Tuple[str, ...] = (MET, NOT_MET, NOT_MEASURED)

# ── sach jo har report me jaata hai ──────────────────────────────────────────
LIVE_TESTED = False              # koi live/demo trade nahi chala
BROKER_CONNECTED = False         # kisi broker/terminal se connection nahi
ORDER_BOOK_READ = False          # L2/footprint/tape ka keyless source nahi hai
TICK_DATA_READ = False           # tick-level data nahi padha
PROFIT_NOT_PROMISED = True       # munafe ka koi waada nahi
BACKTEST_IS_NOT_FUTURE = True    # purane data par sahi hona future ka waada nahi
CONCEPTS_EARN_THEIR_PLACE = True # naam se koi concept sach nahi hota
FINANCIAL_ADVICE = False
NETWORK_USED = False             # query BANATA hai, chalata nahi
GEMINI_CALLS = 0                 # is stage me ek bhi model call nahi
DETERMINISTIC = True
PROVIDER_COST = "₹0"

CANNOT_MEASURE: Tuple[str, ...] = (
    "ye model asli market me paisa banayega ya nahi (koi live/demo trade nahi chala)",
    "aaj ke live spread, slippage aur latency (broker se connection nahi hai)",
    "order book ki asli depth, footprint aur absorption (keyless source nahi hai)",
    "kisi ek trade ka nateeja (backtest ka average kisi ek trade ka waada nahi)",
    "future ka regime — jo aage badla, wo purane data me hai hi nahi",
    "broker/CFD aur futures ke beech ka asli farak, jab tak dono ka data na ho",
)


def _norm(text: Any) -> str:
    return " " + re.sub(r"\s+", " ", str(text or "")).strip().lower() + " "


def _has(norm_text: str, cue: str) -> bool:
    cue = cue.strip().lower()
    if not cue:
        return False
    if re.match(r"^[\w&$.\-/ ]+$", cue):
        return re.search(r"(?<![\w$])" + re.escape(cue) + r"(?![\w])",
                         norm_text) is not None
    return cue in norm_text


def _matched(norm_text: str, cues: Iterable[str]) -> List[str]:
    return [cue for cue in cues if _has(norm_text, cue)]


# ── INSTRUMENT TABLE — ye ADDRESSING hai, KNOWLEDGE nahi ─────────────────────
# Yahan sirf itna likha hai ki "user ne kis cheez ka naam liya" aur us cheez ko
# duniya kis naam se search karti hai. Us instrument ka BEHAVIOUR (kab chalta
# hai, kitna volatile hai, kaunsa session best hai) is table me JAAN-BOOJH KAR
# nahi hai — wo padhi hui source aur naapi hui series se aata hai.
INSTRUMENT_LIST_IS_NOT_EXHAUSTIVE = True


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    label: str
    cues: Tuple[str, ...]
    family: str                      # index / metal / fx / energy / crypto
    venue_terms: Tuple[str, ...] = ()   # official jagah ka naam (search ke liye)


INSTRUMENTS: Tuple[Instrument, ...] = (
    Instrument("us100", "US100 / NAS100 (Nasdaq-100 index)",
               ("us100", "us 100", "usa100", "nas100", "nas 100", "nasdaq100",
                "nasdaq 100", "nasdaq-100", "ndx", "nq", "ustec", "us tech 100",
                "tech100"),
               "index",
               ("Nasdaq-100 index methodology", "CME Micro E-mini Nasdaq-100",
                "Nasdaq market structure")),
    Instrument("xauusd", "XAUUSD (gold vs US dollar)",
               ("xauusd", "xau usd", "xau/usd", "xau", "gold", "sona",
                "gold spot", "spot gold", "gc", "gld"),
               "metal",
               ("COMEX gold futures contract specifications",
                "LBMA gold price benchmark", "CFTC gold futures positioning")),
    Instrument("us500", "US500 / SPX (S&P 500 index)",
               ("us500", "us 500", "spx", "spx500", "s&p500", "s&p 500",
                "es", "sp500", "spy"),
               "index",
               ("S&P 500 index methodology", "CME E-mini S&P 500")),
    Instrument("us30", "US30 / DJI (Dow Jones)",
               ("us30", "us 30", "dji", "dow30", "ym", "dow jones"),
               "index",
               ("CME E-mini Dow futures",)),
    Instrument("eurusd", "EURUSD",
               ("eurusd", "eur usd", "eur/usd", "euro dollar", "fiber"),
               "fx",
               ("BIS triennial FX survey", "CME euro FX futures")),
    Instrument("gbpusd", "GBPUSD",
               ("gbpusd", "gbp usd", "gbp/usd", "cable"), "fx",
               ("BIS triennial FX survey",)),
    Instrument("usdjpy", "USDJPY",
               ("usdjpy", "usd jpy", "usd/jpy"), "fx",
               ("BIS triennial FX survey",)),
    Instrument("wti", "WTI / crude oil",
               ("wti", "usoil", "us oil", "crude", "crude oil", "cl",
                "brent"), "energy",
               ("CME WTI crude oil futures", "EIA petroleum data")),
    Instrument("btcusd", "BTCUSD",
               ("btcusd", "btc usd", "btc/usd", "bitcoin", "btc"), "crypto",
               ("CME bitcoin futures",)),
    Instrument("nifty", "NIFTY 50",
               ("nifty", "nifty50", "nifty 50", "banknifty", "bank nifty"),
               "index",
               ("NSE index methodology", "SEBI market structure")),
)

# ── TIMEFRAME — sirf naam padhna, koi "best timeframe" ka daawa nahi ──────────
TIMEFRAME_LIST_IS_NOT_EXHAUSTIVE = True

# minute me tola gaya, taaki context > confirmation > entry ka kram NAAPA ja sake
TIMEFRAMES: Tuple[Tuple[str, int, Tuple[str, ...]], ...] = (
    ("1M", 1, ("1m", "1 min", "1min", "1-minute", "one minute", "m1")),
    ("2M", 2, ("2m", "2 min", "2min", "m2")),
    ("3M", 3, ("3m", "3 min", "3min", "m3")),
    ("5M", 5, ("5m", "5 min", "5min", "5-minute", "five minute", "m5")),
    ("15M", 15, ("15m", "15 min", "15min", "15-minute", "m15")),
    ("30M", 30, ("30m", "30 min", "30min", "m30")),
    ("1H", 60, ("1h", "1 hour", "1hr", "hourly", "h1", "60m", "60 min")),
    ("4H", 240, ("4h", "4 hour", "4hr", "h4", "240m")),
    ("1D", 1440, ("1d", "daily", "day chart", "d1")),
    ("1W", 10080, ("1w", "weekly", "w1")),
)
_TF_BY_NAME = {name: minutes for name, minutes, _cues in TIMEFRAMES}

# execution chain ke teen role — user ke shabd se pehchane jaate hain
ROLE_CONTEXT = "context"
ROLE_CONFIRMATION = "confirmation"
ROLE_ENTRY = "entry"
CHAIN_ROLES: Tuple[str, ...] = (ROLE_CONTEXT, ROLE_CONFIRMATION, ROLE_ENTRY)
_ROLE_CUES: Dict[str, Tuple[str, ...]] = {
    ROLE_CONTEXT: ("context", "bias", "structure", "higher timeframe", "htf",
                   "direction se", "trend context"),
    ROLE_CONFIRMATION: ("confirmation", "confirm", "confirming", "pushti",
                        "tasdeek"),
    ROLE_ENTRY: ("entry", "execution", "trigger", "enter", "entri"),
}

# ── TRADING STYLE — kis raftaar ka kaam maanga gaya ──────────────────────────
STYLE_LIST_IS_NOT_EXHAUSTIVE = True
STYLES: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("scalping", "scalping (bahut chhote trade)",
     ("scalp", "scalping", "scalper", "scalpping", "intrabar")),
    ("intraday", "intraday / day trading",
     ("intraday", "day trading", "daytrading", "day trade", "session trade")),
    ("swing", "swing trading",
     ("swing trading", "swing trade", "swing model", "multi-day")),
    ("position", "position / long-term",
     ("position trading", "long term trade", "investing model", "carry")),
)

# ── SAKHTI KI MAANG — user ne kaunsi jaanch maangi ───────────────────────────
# Har entry: (key, label, cues). Ye SIRF "maanga gaya" padhta hai. "Hua ya nahi"
# ka faisla contract ke naap se aata hai, is list se NAHI.
DEMANDS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("walk_forward", "walk-forward / rolling validation",
     ("walk forward", "walk-forward", "walkforward", "rolling validation",
      "rolling window test")),
    ("monte_carlo", "monte carlo simulation",
     ("monte carlo", "montecarlo", "monte-carlo", "simulation thousands",
      "risk of ruin")),
    ("robustness", "parameter robustness",
     ("robustness", "robust", "parameter sensitivity", "parameter sweep",
      "magic number", "parameter region")),
    ("baseline", "baseline comparison",
     ("baseline", "benchmark model", "beat random", "simple breakout",
      "compare against simple", "opening range baseline")),
    ("leakage", "data leakage check",
     ("leakage", "look ahead", "lookahead", "look-ahead", "repaint",
      "repainting", "future candle", "hindsight")),
    ("costs", "spread / commission / slippage",
     ("spread", "commission", "slippage", "latency", "transaction cost",
      "trading cost", "cost model")),
    ("out_of_sample", "out-of-sample / held-out test",
     ("out of sample", "out-of-sample", "oos", "held out", "held-out",
      "untouched test", "test set")),
    ("red_team", "red-team / khud ko galat sabit karo",
     ("red team", "red-team", "redteam", "falsify", "falsification",
      "try to break", "disprove", "galat sabit", "authority par sach na",
      "authority par sach nahi", "curve fit", "curve-fit", "data mining",
      "cherry pick", "cherry-pick")),
    ("regime", "regime detection",
     ("regime", "regime switch", "market state", "trending vs ranging",
      "high vol", "low vol", "volatility regime")),
    ("session", "session / time-of-day expectancy",
     ("session", "time of day", "time-of-day", "london", "new york",
      "asian", "asia session", "opening range", "kill zone", "killzone")),
    ("macro_events", "macro event windows",
     ("macro", "news", "nfp", "cpi release", "fomc", "fed meeting",
      "event window", "economic calendar")),
    ("intermarket", "intermarket relationships",
     ("intermarket", "inter-market", "correlation", "dxy", "yields",
      "vix", "correlated instrument")),
    ("information_theory", "information theory",
     ("information theory", "mutual information", "entropy",
      "conditional information", "redundancy")),
    ("game_theory", "game theory",
     ("game theory", "game-theory", "market maker incentive",
      "hft incentive", "counterparty incentive")),
    ("microstructure", "market microstructure / order flow",
     ("microstructure", "micro-structure", "order flow", "orderflow",
      "order book", "limit order book", "footprint", "tape reading",
      "auction market theory", "price discovery", "liquidity")),
    ("risk_sizing", "position sizing / risk per trade",
     ("position sizing", "position size", "risk per trade", "lot size",
      "risk management", "kelly", "drawdown limit")),
)
DEMAND_KEYS: Tuple[str, ...] = tuple(key for key, _l, _c in DEMANDS)

# Naam se sach na maanne wale concept — inka naam lena JURM nahi, par inhe
# saboot ke bina rakhna jurm hai. Ye list `CONCEPTS_EARN_THEIR_PLACE` ke saath
# hi kaam karti hai.
NAMED_CONCEPTS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("ict", ("ict", "inner circle trader", "fair value gap", "fvg",
             "order block", "breaker block", "judas swing", "silver bullet",
             "power of three", "optimal trade entry", "ote")),
    ("smc", ("smc", "smart money concept", "smart money concepts",
             "liquidity sweep", "liquidity grab", "stop hunt", "bos",
             "break of structure", "choch", "change of character",
             "mitigation block", "imbalance")),
    ("wyckoff", ("wyckoff", "accumulation phase", "distribution phase",
                 "spring", "upthrust", "composite operator")),
    ("market_profile", ("market profile", "tpo", "value area", "poc",
                        "point of control", "initial balance",
                        "auction market theory", "amt")),
    ("volume_profile", ("volume profile", "vpvr", "volume node",
                        "high volume node", "low volume node")),
    ("vwap", ("vwap", "anchored vwap", "vwap band", "vwap reversion")),
    ("stat_arb", ("stat arb", "statistical arbitrage", "pairs trade",
                  "cointegration")),
)
CONCEPT_KEYS: Tuple[str, ...] = tuple(key for key, _c in NAMED_CONCEPTS)


# ── #150d: naam se bhi pehchano, par sirf UN naamon se jo aur kahin nahi milte ─
# `_TRADE_RE` me instrument ka ticker (us100/xauusd/nas100) aur ICT/SMC concept
# ka naam (order block, fair value gap) nahi tha. Nateeja: "order block ka rule
# banao" trading hi nahi maana jaata tha, aur `planner` ki purani creative-leak
# se Design/Materials Science le aata tha. Ye do list JAAN-BOOJH KAR chhoti
# hain — sirf wo shabd jo aam bhasha me kisi doosre matlab me nahi aate.
#
# Yahan JO NAHI HAI wo bhi naapa hua faisla hai: "gold", "sona", "es", "nq",
# "gc", "ndx", "spring", "upthrust", "imbalance", "walk forward" — inme se ek
# bhi nahi, kyunki "gold jewellery ka design banao" ya "spring ka model banao"
# trading nahi hai. Ye table bhi ADDRESSING hai, KNOWLEDGE nahi.
_TICKER_CUES: Tuple[str, ...] = (
    "us100", "us 100", "usa100", "nas100", "nas 100", "nasdaq100",
    "nasdaq 100", "nasdaq-100", "ustec", "us tech 100", "tech100",
    "xauusd", "xau usd", "xau/usd", "us500", "spx500", "s&p500", "sp500",
    "us30", "dow30", "eurusd", "eur usd", "eur/usd", "gbpusd", "gbp/usd",
    "usdjpy", "usd/jpy", "btcusd", "btc/usd", "usoil", "banknifty",
    "bank nifty", "nifty50", "nifty 50",
)
_CONCEPT_CUES: Tuple[str, ...] = (
    "order block", "breaker block", "fair value gap", "fvg", "judas swing",
    "silver bullet", "optimal trade entry", "inner circle trader",
    "smart money concept", "smart money concepts", "liquidity grab",
    "stop hunt", "break of structure", "change of character", "choch",
    "mitigation block", "wyckoff", "accumulation phase",
    "distribution phase", "composite operator", "market profile",
    "value area", "point of control", "initial balance",
    "auction market theory", "volume profile", "vpvr", "high volume node",
    "low volume node", "vwap", "anchored vwap", "vwap reversion",
    "statistical arbitrage", "stat arb", "cointegration",
    "footprint chart", "tape reading", "opening range breakout",
)


def instrument_cues(question: str) -> List[str]:
    """Sawaal me kaun-kaunsa saaf ticker naam aaya (ADDRESSING, knowledge nahi)."""
    return _matched(_norm(question), _TICKER_CUES)


def concept_cues(question: str) -> List[str]:
    """Kaun-kaunsa trading concept ka naam aaya. Naam aana sach hona NAHI hai."""
    return _matched(_norm(question), _CONCEPT_CUES)


# ── LANE KA TAALA: do signal chahiye, ek nahi ────────────────────────────────
# `market_data.market_intent()` ka wahi niyam. Sirf "gold" likha hona kaafi
# nahi — warna har aam sawaal trading lane khol dega. Aur sirf "model banao"
# kaafi nahi — warna gaana/nibandh bhi trading me ghus jaayega.
_TRADE_RE = re.compile(
    r"\bscalp\w*\b|\btrad(?:e|es|ing|er)\b|\bintraday\b|\bswing\s+trad\w*\b|"
    r"\bbacktest\w*\b|\bentry\s+model\b|\bstop[-\s]?loss\b|\btake[-\s]?profit\b"
    r"|\brisk[-\s]?reward\b|\bexpectancy\b|\bprofit\s+factor\b|\bdrawdown\b|"
    r"\bwin\s+rate\b|\bposition\s+sizing\b|\border\s+flow\b|\bmicrostructure\b|"
    r"\bliquidity\s+sweep\b|\bsmart\s+money\b|\bprice\s+action\b|\bchart\s+"
    r"pattern\b|\bcandle\w*\b|\blot\s+size\b|\bpip[s]?\b|\bbroker\b|"
    r"\bstrategy\s+backtest\b|\btrading\s+system\b|\btrading\s+model\b",
    re.IGNORECASE)
# "kuch BANAO" ki maang — bina iske trading shabd sirf topic hai (padhne ka
# sawaal), model banane ki farmaish nahi.
_BUILD_RE = re.compile(
    r"\bmodel\b|\bsystem\b|\bstrategy\b|\bstrategi\w*\b|\bsetup\b|\brule[s]?\b|"
    r"\bplan\b|\bbanao\b|\bbana\s+do\b|\bbana\s+kar\b|\bbnao\b|\bbna\s+do\b|"
    r"\bbanaa?o\b|\btayyar\s+kar\b|\bdesign\b|\bdevelop\b|\bbuild\b|"
    r"\bcreate\b|\bframework\b|\bplaybook\b|\bspec\b",
    re.IGNORECASE)

NOT_ASKED_REASON = ("farmaish trading model jaisi nahi lagi, isliye trade-study "
                    "lane nahi kholi")


def _trade_signal(text: str) -> bool:
    """Trading ki cheez ka naam mila ya nahi — regex se YA saaf naam se.

    Teen raste hain aur teeno ek hi baat naapte hain, isliye `is_request` aur
    `request_reason` dono yahin se poochhte hain (do jagah do faisla = agli
    baar wahi bug).
    """
    return (bool(_TRADE_RE.search(text)) or bool(instrument_cues(text))
            or bool(concept_cues(text)))


def is_request(question: str) -> bool:
    """Trading model ki farmaish hai ya nahi — DO signal par, ek par nahi."""
    text = str(question or "")
    return _trade_signal(text) and bool(_BUILD_RE.search(text))


def request_reason(question: str) -> str:
    """Taala khula ya band — aur KYUN. Dono hamesha likhe jaate hain."""
    text = str(question or "")
    trade = _trade_signal(text)
    build = bool(_BUILD_RE.search(text))
    if trade and build:
        return ("trade-study lane chali — sawaal me trading ki cheez ka naam "
                "bhi hai aur kuch BANANE ki maang bhi")
    if trade and not build:
        return ("trading ki baat hai par kuch banane ki maang nahi — ye padhne "
                "ka sawaal maana gaya, model lane nahi kholi")
    if build and not trade:
        return ("kuch banane ki maang hai par trading ki koi cheez ka naam "
                "nahi — model lane nahi kholi")
    return NOT_ASKED_REASON


# ── ASK PARSE ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class TradeAsk:
    asked: bool = False
    reason: str = NOT_ASKED_REASON
    instruments: Tuple[str, ...] = ()          # instrument_id
    instrument_labels: Tuple[str, ...] = ()
    families: Tuple[str, ...] = ()
    timeframes: Tuple[str, ...] = ()           # naam, chhote se bade kram me
    chain: Tuple[Tuple[str, str], ...] = ()    # (role, timeframe) jo saaf mila
    style_id: str = ""
    style_label: str = ""
    demands: Tuple[str, ...] = ()
    concepts: Tuple[str, ...] = ()
    hypothesis_count: int = 0
    separate_per_instrument: bool = False
    matched_cues: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asked": self.asked,
            "reason": self.reason,
            "instruments": list(self.instruments),
            "instrument_labels": list(self.instrument_labels),
            "families": list(self.families),
            "timeframes": list(self.timeframes),
            "chain": [{"role": role, "timeframe": tf} for role, tf in self.chain],
            "style_id": self.style_id,
            "style_label": self.style_label,
            "demands": list(self.demands),
            "concepts": list(self.concepts),
            "hypothesis_count": self.hypothesis_count,
            "separate_per_instrument": self.separate_per_instrument,
            "matched_cues": list(self.matched_cues),
            "instrument_list_is_not_exhaustive": INSTRUMENT_LIST_IS_NOT_EXHAUSTIVE,
            "timeframe_list_is_not_exhaustive": TIMEFRAME_LIST_IS_NOT_EXHAUSTIVE,
            "style_list_is_not_exhaustive": STYLE_LIST_IS_NOT_EXHAUSTIVE,
            "concepts_earn_their_place": CONCEPTS_EARN_THEIR_PLACE,
        }


_HYP_COUNT_RE = re.compile(
    r"\b(?:kam\s+se\s+kam|at\s+least|minimum|min)?\s*(\d{1,2})\s*"
    r"(?:[a-zऀ-ॿ\-]+\s+){0,3}?"
    r"(?:hypothes[ie]s|hypothesis|theor(?:y|ies)|competing\s+model[s]?)",
    re.IGNORECASE)
_SEPARATE_RE = re.compile(
    r"\bseparat\w*\b|\balag[-\s]?alag\b|\bper\s+instrument\b|"
    r"\beach\s+instrument\b|\bindividually\b|\bdono\s+ke\s+liye\s+alag\b",
    re.IGNORECASE)


def _timeframes_in(norm_text: str) -> List[str]:
    found: List[Tuple[int, str]] = []
    for name, minutes, cues in TIMEFRAMES:
        if _matched(norm_text, cues):
            found.append((minutes, name))
    return [name for _m, name in sorted(found)]


def _timeframe_positions(text: str) -> List[Tuple[int, str]]:
    """Har timeframe ka naam KAHAN aaya — jodi banane ke liye jagah chahiye."""
    lowered = str(text or "").lower()
    out: List[Tuple[int, str]] = []
    for name, _minutes, cues in TIMEFRAMES:
        for cue in cues:
            pattern = r"(?<![\w$])" + re.escape(cue) + r"(?![\w])"
            for hit in re.finditer(pattern, lowered):
                out.append((hit.start(), name))
    return sorted(dict.fromkeys(out))


# Role ke shabd aur timeframe itne door tak hi ek doosre ke maane jaate hain.
CHAIN_WINDOW_CHARS = 28


def _chain_in(text: str) -> List[Tuple[str, str]]:
    """Role ke shabd ke sabse PAAS wala timeframe — aur ek jodi sirf ek baar.

    Seedha "sabse chhota timeframe uthao" galat tha: "15M context, 5M
    confirmation, 1M entry" me teeno role ko 1M mil jaata. Aur akela "sabse paas
    wala" bhi galat tha: "final execution 15M" me `execution` 15M ke bilkul
    paas hai, isliye entry=15M ban jaata. Isliye dono taraf se sabse paas wali
    jodi pehle banti hai (greedy), aur uske baad na wo role dobara milta hai na
    wo timeframe. Role ka naam liya hi na gaya ho to koi jodi nahi banti — hum
    apni marzi se "15M zaroor context hoga" nahi maan lete.
    """
    lowered = str(text or "").lower()
    spots = _timeframe_positions(text)
    if not spots:
        return []
    candidates: List[Tuple[int, int, str, str]] = []
    for role in CHAIN_ROLES:
        for cue in _ROLE_CUES[role]:
            for hit in re.finditer(re.escape(cue), lowered):
                for pos, name in spots:
                    distance = abs(pos - hit.start())
                    if distance > CHAIN_WINDOW_CHARS:
                        continue
                    candidates.append((distance, pos, role, name))
    taken_roles: Dict[str, str] = {}
    taken_tfs: List[str] = []
    for _distance, _pos, role, name in sorted(candidates):
        if role in taken_roles or name in taken_tfs:
            continue
        taken_roles[role] = name
        taken_tfs.append(name)
    return [(role, taken_roles[role]) for role in CHAIN_ROLES
            if role in taken_roles]



def ask_of(question: str) -> TradeAsk:
    """Farmaish padho. Taala band ho to khaali TradeAsk — wajah ke saath."""
    text = str(question or "")
    if not is_request(text):
        return TradeAsk(asked=False, reason=request_reason(text))
    norm = _norm(text)
    cues: List[str] = []

    instruments: List[str] = []
    labels: List[str] = []
    families: List[str] = []
    for item in INSTRUMENTS:
        hits = _matched(norm, item.cues)
        if not hits:
            continue
        instruments.append(item.instrument_id)
        labels.append(item.label)
        if item.family not in families:
            families.append(item.family)
        cues.extend(hits)

    style_id, style_label = "", ""
    for sid, slabel, scues in STYLES:
        hits = _matched(norm, scues)
        if hits and not style_id:
            style_id, style_label = sid, slabel
            cues.extend(hits)

    demands: List[str] = []
    for key, _label, dcues in DEMANDS:
        hits = _matched(norm, dcues)
        if hits:
            demands.append(key)
            cues.extend(hits)

    concepts: List[str] = []
    for key, ccues in NAMED_CONCEPTS:
        hits = _matched(norm, ccues)
        if hits:
            concepts.append(key)
            cues.extend(hits)

    count = 0
    for hit in _HYP_COUNT_RE.finditer(text):
        try:
            value = int(hit.group(1))
        except (TypeError, ValueError):
            continue
        count = max(count, value)

    return TradeAsk(
        asked=True,
        reason=request_reason(text),
        instruments=tuple(instruments),
        instrument_labels=tuple(labels),
        families=tuple(families),
        timeframes=tuple(_timeframes_in(norm)),
        chain=tuple(_chain_in(text)),
        style_id=style_id,
        style_label=style_label,
        demands=tuple(demands),
        concepts=tuple(concepts),
        hypothesis_count=count,
        separate_per_instrument=bool(_SEPARATE_RE.search(text))
        or len(instruments) > 1,
        matched_cues=tuple(dict.fromkeys(cues)),
    )


# ── CONTRACT — intel ke 30 section se nikle naam-wale point ───────────────────
# Ginti 30 nahi, 34 hai — aur ye jaan-boojh kar hai: teen section me do-do alag
# cheezein naapi jaati hain (source ki tarteeb me institutional aur academic
# alag; exit me stop aur target alag; jaanch me har trade ka nateeja aur
# red-team alag). Number ko 30 dikhane ke liye do naap ek dabbe me daal dena
# theek lagta, par phir ek MET doosre ka jhooth chhupa leta.
GROUP_SCOPE = "scope"
GROUP_SOURCES = "sources"
GROUP_CONCEPTS = "concepts"
GROUP_HYPOTHESES = "hypotheses"
GROUP_TESTING = "testing"
GROUP_EXECUTION = "execution"
GROUP_RISK = "risk"
GROUP_HONESTY = "honesty"
GROUPS: Tuple[str, ...] = (GROUP_SCOPE, GROUP_SOURCES, GROUP_CONCEPTS,
                           GROUP_HYPOTHESES, GROUP_TESTING, GROUP_EXECUTION,
                           GROUP_RISK, GROUP_HONESTY)


@dataclass(frozen=True)
class ContractPoint:
    point_id: str
    label: str
    group: str
    needs: str          # MET kehne ke liye kya HONA chahiye (saaf shabdon me)
    blocked_by: str = ""  # aisi rukaawat jo is app me structurally hai


CONTRACT: Tuple[ContractPoint, ...] = (
    # ── scope ────────────────────────────────────────────────────────────────
    ContractPoint("instrument_scope",
                  "US100 aur XAUUSD alag-alag padhe gaye (ek hi model dono par thopa nahi)",
                  GROUP_SCOPE,
                  "har instrument ka apna section, apna number, apna nateeja"),
    ContractPoint("execution_chain",
                  "final execution 15M context -> 5M confirmation -> 1M entry",
                  GROUP_SCOPE,
                  "teeno role ka timeframe naam se likha ho, aur kram bada->chhota ho"),
    ContractPoint("research_timeframes",
                  "research me bade timeframe aur tick/order-book data ki ijazat",
                  GROUP_SCOPE,
                  "kaunsa data padha gaya wo naam se likha ho"),
    # ── sources ──────────────────────────────────────────────────────────────
    ContractPoint("institutional_sources",
                  "institutional-first source (CME, Nasdaq, Fed, BIS, CFTC, exchange docs)",
                  GROUP_SOURCES,
                  "kam se kam ek official exchange/regulator/central-bank document padha gaya ho"),
    ContractPoint("academic_sources",
                  "peer-reviewed microstructure / quant finance research",
                  GROUP_SOURCES,
                  "kam se kam ek academic paper source id ke saath"),
    ContractPoint("read_arguments_not_summaries",
                  "asli dalil padhi gayi, sirf summary nahi",
                  GROUP_SOURCES,
                  "read level full/section ho, sirf abstract/snippet nahi"),
    ContractPoint("theory_base",
                  "microstructure, auction theory, price discovery, liquidity, behavioural finance, execution",
                  GROUP_SOURCES,
                  "in vishayon me se jo bhi use hua, uske peeche source id ho"),
    # ── concepts ─────────────────────────────────────────────────────────────
    ContractPoint("concept_definitions",
                  "ICT/SMC/Wyckoff jaise concept ki exact algorithmic definition",
                  GROUP_CONCEPTS,
                  "jis concept ka naam liya, uski if-then definition likhi ho"),
    ContractPoint("no_authority_truth",
                  "koi concept naam ki wajah se sach nahi maana gaya",
                  GROUP_CONCEPTS,
                  "har concept ke saath baseline se muqabla aur sample size ho"),
    ContractPoint("subjective_terms_banned",
                  "'strong FVG', 'good OB', 'clear liquidity' jaise shabd bina number ke nahi",
                  GROUP_CONCEPTS,
                  "aisa har shabd ya hataya gaya ho ya uski ginti likhi ho"),
    ContractPoint("order_flow_edge",
                  "futures order flow se asli extra edge ka test",
                  GROUP_CONCEPTS,
                  "order flow ke saath aur uske bina, do number ka farak",
                  "footprint/L2 data ka koi keyless source nahi — ye MET ho hi nahi sakta"),
    # ── hypotheses ───────────────────────────────────────────────────────────
    ContractPoint("competing_hypotheses",
                  "kam se kam 7 sach me alag competing hypothesis",
                  GROUP_HYPOTHESES,
                  "7 ya zyada hypothesis, aur unka mechanism alag-alag ho"),
    ContractPoint("original_hypotheses",
                  "kam se kam 3 apni nayi hypothesis, naam se labelled",
                  GROUP_HYPOTHESES,
                  "'New hypothesis generated in this research' ka label lagi 3 entry"),
    ContractPoint("regime_detection",
                  "har scalp se pehle regime pehchana gaya",
                  GROUP_HYPOTHESES,
                  "regime ka naap likha ho aur uska rule entry se pehle lage"),
    ContractPoint("session_expectancy",
                  "session / time-of-day ki expectancy alag-alag naapi gayi",
                  GROUP_HYPOTHESES,
                  "har session/ghante ka apna number aur sample size"),
    ContractPoint("macro_event_windows",
                  "macro event window (pre-news, release, 1-5M, 5-15M, 15-60M) ka verdict",
                  GROUP_HYPOTHESES,
                  "har window ke liye trade / wait / avoid me se ek saaf faisla"),
    ContractPoint("intermarket_tests",
                  "intermarket rishte regime aur waqt par test kiye gaye",
                  GROUP_HYPOTHESES,
                  "correlation ka number, aur wo kab tootta hai"),
    ContractPoint("information_theory",
                  "information theory (mutual information, entropy, redundancy)",
                  GROUP_HYPOTHESES,
                  "kis signal me kitni asli jaankari hai — number ke saath"),
    ContractPoint("game_theory",
                  "game theory: HFT, market maker, dealer, CTA, fund, retail ke incentive",
                  GROUP_HYPOTHESES,
                  "incentive ka tark, aur 'institutions ne mera stop hunt kiya' jaisi bina-saboot kahani nahi"),
    # ── testing ──────────────────────────────────────────────────────────────
    ContractPoint("no_leakage",
                  "zero-tolerance data leakage (sirf t ya usse pehle ki jaankari)",
                  GROUP_TESTING,
                  "leakage ke naam-wale check chalaye gaye hon aur pass hon"),
    ContractPoint("realistic_costs",
                  "spread, commission, slippage, latency, news slippage",
                  GROUP_TESTING,
                  "har cost ka number, aur uske baad ka net nateeja"),
    ContractPoint("walk_forward_validation",
                  "chronological train / validation / untouched test + rolling walk-forward",
                  GROUP_TESTING,
                  "held-out ka apna number, aur kai window ka nateeja"),
    ContractPoint("monte_carlo_risk",
                  "Monte Carlo: drawdown, losing streak, ending equity, risk of ruin",
                  GROUP_TESTING,
                  "hazaaron simulation ka nateeja, aur usse nikla risk-per-trade"),
    ContractPoint("parameter_robustness",
                  "edge ek region me zinda ho, ek magic number par nahi",
                  GROUP_TESTING,
                  "parameter sweep ka nateeja aur padosi values ka number"),
    ContractPoint("baseline_tournament",
                  "random, breakout, ORB, momentum, mean reversion, VWAP, MA baseline ko OOS me haraya",
                  GROUP_TESTING,
                  "har baseline ka number aur model ka usse behtar hona (held-out par)"),
    ContractPoint("failure_classification",
                  "har haar ki wajah alag-alag class me daali gayi",
                  GROUP_TESTING,
                  "loss ke class aur unki ginti"),
    ContractPoint("red_team",
                  "khud ko todne ki koshish (curve fit? leakage? chhota sample? ek saal? ek session?)",
                  GROUP_TESTING,
                  "har red-team sawaal ka apna jawab, aur jo mila wo likha ho"),
    # ── execution ────────────────────────────────────────────────────────────
    ContractPoint("entry_model_exact",
                  "entry model: WHERE / WHEN / WHY / DIRECTION / TRIGGER / INVALIDATION / SL / TP / NO-TRADE",
                  GROUP_EXECUTION,
                  "nau me se nau khaane bhare hon, aur koi discretionary shabd na ho"),
    ContractPoint("stop_loss_research",
                  "stop-loss ki research, MAE (maximum adverse excursion) ke saath",
                  GROUP_EXECUTION,
                  "stop ki jagah ka number aur MAE ka distribution"),
    ContractPoint("take_profit_research",
                  "take-profit: 1R-3R+, liquidity target, VWAP, partials, trailing, time exit",
                  GROUP_EXECUTION,
                  "expectancy ke hisaab se chuna gaya target, win-rate ke hisaab se nahi"),
    ContractPoint("final_spec_tradeable",
                  "aakhri spec asli me trade karne laayak (hours, condition, trigger, size, news rule)",
                  GROUP_EXECUTION,
                  "har instrument ke liye poora spec, uncertainty interval ke saath"),
    # ── risk + honesty ───────────────────────────────────────────────────────
    ContractPoint("performance_metrics",
                  "win rate, avg win/loss, expectancy, profit factor, Sharpe, Sortino, max drawdown, tail loss, risk of ruin",
                  GROUP_RISK,
                  "ye sab number likhe hon — sirf win rate nahi"),
    ContractPoint("evidence_labels_ae",
                  "evidence label A-E, aur negative nateeje bhi dikhaye gaye",
                  GROUP_HONESTY,
                  "har daawe par A/B/C/D/E, aur E wale bhi report me"),
    ContractPoint("honest_final_decision",
                  "evidence kaafi na ho to model gadha nahi jaata — kya missing hai wo likha jaata hai",
                  GROUP_HONESTY,
                  "ya poora model saboot ke saath, ya saaf inkaar with missing list"),
)
CONTRACT_POINTS: int = len(CONTRACT)
CONTRACT_IDS: Tuple[str, ...] = tuple(point.point_id for point in CONTRACT)
CONTRACT_BY_ID: Dict[str, ContractPoint] = {p.point_id: p for p in CONTRACT}
# Jo point is app me structurally MET ho hi nahi sakte — inhe chhupaya nahi
# jaata, naam se ginne jaate hain.
STRUCTURALLY_BLOCKED: Tuple[str, ...] = tuple(
    point.point_id for point in CONTRACT if point.blocked_by)


# ── NAAP ke auzaar ───────────────────────────────────────────────────────────
# 1. Entry model ke nau khaane. Har khaana naam se dhoonda jaata hai; "lagta hai
#    yahan entry hogi" jaisa andaaza kabhi MET nahi banta.
ENTRY_SLOTS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("where", "WHERE — kis level/jagah par",
     ("where", "level", "price zone", "kis jagah", "kahan", "zone")),
    ("when", "WHEN — kis waqt/session me",
     ("when", "session", "time window", "kab", "ghanta", "hours")),
    ("why", "WHY — kaunsa mechanism",
     ("why", "mechanism", "reason", "kyun", "kyu", "logic", "rationale")),
    ("direction", "DIRECTION — long ya short",
     ("direction", "long", "short", "buy", "sell", "bullish", "bearish")),
    ("trigger", "TRIGGER — exact entry shart",
     ("trigger", "entry condition", "entry rule", "if close", "if price",
      "signal bar")),
    ("invalidation", "INVALIDATION — kab setup mar gaya",
     ("invalidation", "invalidated", "setup fails", "cancel", "rad",
      "no longer valid")),
    ("stop", "SL — stop kahan",
     ("stop loss", "stop-loss", "sl", "stop at", "stop placement")),
    ("target", "TP — target kahan",
     ("take profit", "take-profit", "tp", "target", "1r", "2r", "3r")),
    ("no_trade", "NO-TRADE — kab bilkul nahi",
     ("no trade", "no-trade", "avoid", "stand aside", "skip", "wait",
      "trade nahi")),
)
ENTRY_SLOT_KEYS: Tuple[str, ...] = tuple(key for key, _l, _c in ENTRY_SLOTS)

# 2. Discretionary shabd — inka hona jurm nahi, bina number ke hona jurm hai.
SUBJECTIVE_TERMS: Tuple[str, ...] = (
    "strong fvg", "good ob", "clear liquidity", "clean break", "strong ob",
    "obvious level", "nice setup", "good setup", "strong setup",
    "clear structure", "significant level", "key level", "proper fvg",
    "high probability", "strong momentum", "clear trend", "healthy pullback",
    "strong rejection", "aggressive buyers", "aggressive sellers",
    "smart money stepped in", "institutions defended", "looks bullish",
    "looks bearish", "feels like", "should reverse", "market wants",
)
SUBJECTIVE_LIST_IS_NOT_EXHAUSTIVE = True
# Isi line me number/shart mile to shabd ko "naapa hua" maana jaata hai.
_QUANTIFIED_RE = re.compile(
    r"\d|\bATR\b|\bpercentile\b|\bstd\b|\bstandard\s+deviation\b|"
    r"\bthreshold\b|\bdefined\s+as\b|\bexactly\b|>=|<=|>|<|=",
    re.IGNORECASE)

# 3. Jo number report me hone hi chahiye.
METRIC_FIELDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("win_rate", ("win rate", "win-rate", "winrate", "hit rate")),
    ("avg_win_loss", ("average win", "avg win", "average loss", "avg loss",
                      "average r", "avg r")),
    ("expectancy", ("expectancy", "expected value per trade", "ev per trade")),
    ("profit_factor", ("profit factor", "profit-factor")),
    ("sharpe", ("sharpe",)),
    ("sortino", ("sortino",)),
    ("max_drawdown", ("max drawdown", "maximum drawdown", "peak to trough",
                      "peak-to-trough")),
    ("tail_loss", ("tail loss", "worst loss", "worst trade", "cvar",
                   "expected shortfall", "95th percentile loss")),
    ("risk_of_ruin", ("risk of ruin", "ruin probability", "probability of ruin")),
)
METRIC_KEYS: Tuple[str, ...] = tuple(key for key, _c in METRIC_FIELDS)

# 4. Evidence label A-E — naam aur matlab ek hi jagah.
EVIDENCE_LABELS: Tuple[Tuple[str, str], ...] = (
    ("A", "strong empirical support (kai window, held-out, baseline se behtar)"),
    ("B", "moderate support (naapa gaya par sample chhota ya window kam)"),
    ("C", "plausible par uncertain (tark hai, number kamzor)"),
    ("D", "research hypothesis (abhi test hi nahi hui)"),
    ("E", "unsupported ya fail (test hui aur nateeja khilaaf aaya)"),
)
EVIDENCE_LABEL_KEYS: Tuple[str, ...] = tuple(key for key, _d in EVIDENCE_LABELS)
_LABEL_IN_TEXT_RE = re.compile(r"\[EVIDENCE-([A-E])\]")
ORIGINAL_HYPOTHESIS_LABEL = "New hypothesis generated in this research"

# 5. 90%+ win rate ka daawa — ye PASS nahi, ye FAIL hai.
MAX_CREDIBLE_WIN_RATE = 90.0
_WIN_RATE_CLAIM_RE = re.compile(
    r"(\d{1,3}(?:\.\d+)?)\s*%\s*(?:\+\s*)?(?:ka\s+)?"
    r"(?:win[-\s]?rate|winrate|accuracy|hit[-\s]?rate|jeet)",
    re.IGNORECASE)
_WIN_RATE_CLAIM_ALT_RE = re.compile(
    r"(?:win[-\s]?rate|winrate|accuracy|hit[-\s]?rate)\s*(?:of|:|=|is|hai)?\s*"
    r"(\d{1,3}(?:\.\d+)?)\s*%", re.IGNORECASE)

# 6. Bina saboot ki kahani — "institutions ne mera stop hunt kiya".
_STORY_RE = re.compile(
    r"institutions?\s+(?:hunted|hunt|took|grabbed|targeted)\s+(?:my\s+|the\s+)?"
    r"stop|smart\s+money\s+(?:hunted|took|grabbed)|market\s+makers?\s+"
    r"(?:hunted|targeted)|banks?\s+(?:hunted|pushed)\s+price|"
    r"broker\s+(?:hunted|hit)\s+my\s+stop|stop\s+hunt\s+hua",
    re.IGNORECASE)

MIN_COMPETING_HYPOTHESES = 7
MIN_ORIGINAL_HYPOTHESES = 3


def _text_of(value: Any) -> str:
    return str(value or "")


def _lines(text: str) -> List[str]:
    return [line for line in _text_of(text).splitlines() if line.strip()]


def subjective_hits(text: str) -> List[Dict[str, Any]]:
    """Discretionary shabd, aur us line par number tha ya nahi.

    Shabd ka milna apne aap me FAIL nahi. FAIL tab hai jab wahi line koi ginti,
    ATR, percentile ya shart na de. Isliye har hit ke saath `quantified` jaata
    hai — aur report me dono ginti alag likhi jaati hain.
    """
    out: List[Dict[str, Any]] = []
    for index, line in enumerate(_lines(text), start=1):
        norm = _norm(line)
        quantified = bool(_QUANTIFIED_RE.search(line))
        for term in SUBJECTIVE_TERMS:
            if _has(norm, term):
                out.append({"term": term, "line_no": index,
                            "quantified": quantified,
                            "line": line.strip()[:160]})
    return out


def entry_slots(text: str) -> Dict[str, bool]:
    """Nau khaane me se kaun-kaun bhara hai."""
    norm = _norm(text)
    return {key: bool(_matched(norm, cues)) for key, _label, cues in ENTRY_SLOTS}


def metrics_in(text: str) -> Dict[str, bool]:
    """Kaun-kaunsa performance number naam se likha gaya."""
    norm = _norm(text)
    return {key: bool(_matched(norm, cues)) for key, cues in METRIC_FIELDS}


def win_rate_claims(text: str) -> List[float]:
    """Report me likhe hue win-rate ke number (dono tarah ke vaakya se)."""
    found: List[float] = []
    for pattern in (_WIN_RATE_CLAIM_RE, _WIN_RATE_CLAIM_ALT_RE):
        for hit in pattern.finditer(_text_of(text)):
            try:
                found.append(float(hit.group(1)))
            except (TypeError, ValueError):
                continue
    return sorted(dict.fromkeys(found))


def chased_win_rate(text: str) -> List[float]:
    """90% se upar ka win-rate daawa — ye khud ek FAIL hai."""
    return [value for value in win_rate_claims(text)
            if value >= MAX_CREDIBLE_WIN_RATE]


def story_claims(text: str) -> List[str]:
    """Bina saboot ki 'institutions ne stop hunt kiya' jaisi kahani."""
    return [hit.group(0).strip()
            for hit in _STORY_RE.finditer(_text_of(text))]


def evidence_labels_in(text: str) -> List[str]:
    return sorted(set(_LABEL_IN_TEXT_RE.findall(_text_of(text))))


def original_hypothesis_count(hypotheses: Sequence[Any] = (),
                             text: str = "") -> int:
    """Sirf wahi ginti jispar SAAF label laga ho — andaaza nahi."""
    label = ORIGINAL_HYPOTHESIS_LABEL.lower()
    count = 0
    for item in hypotheses or ():
        blob = ""
        if isinstance(item, dict):
            blob = " ".join(str(value) for value in item.values())
        else:
            blob = str(item or "")
        if label in blob.lower():
            count += 1
    if count:
        return count
    return _text_of(text).lower().count(label)


# ── source ki pehchaan (institutional pehle, phir academic) ──────────────────
# Ye host-list ROUTING/PEHCHAAN ke liye hai, "sach kaun bolta hai" ke liye nahi.
# Kisi source ka official hona uske daawe ko sach nahi banata — bas ye batata
# hai ki wo exchange/regulator/central bank ka apna document hai.
INSTITUTIONAL_HOSTS: Tuple[str, ...] = (
    "cmegroup.com", "nasdaq.com", "nasdaqtrader.com", "nyse.com", "cboe.com",
    "theice.com", "lseg.com", "eurex.com", "nseindia.com", "bseindia.com",
    "federalreserve.gov", "newyorkfed.org", "stlouisfed.org", "bis.org",
    "cftc.gov", "sec.gov", "esma.europa.eu", "fca.org.uk", "sebi.gov.in",
    "ecb.europa.eu", "bankofengland.co.uk", "imf.org", "oecd.org",
    "treasury.gov", "bls.gov", "eia.gov", "lbma.org.uk", "comex.com",
)
INSTITUTIONAL_HOST_LIST_IS_NOT_EXHAUSTIVE = True
ACADEMIC_SOURCE_TYPES: Tuple[str, ...] = ("paper",)
DEEP_READ_LEVELS: Tuple[str, ...] = ("claims", "full_text")


def _source_field(source: Any, name: str) -> str:
    value = getattr(source, name, None)
    if value is None and isinstance(source, dict):
        value = source.get(name)
    if hasattr(value, "value"):          # Enum
        value = value.value
    return str(value or "")


def institutional_sources(sources: Iterable[Any] = ()) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for source in sources or ():
        url = _source_field(source, "url").lower()
        host = next((h for h in INSTITUTIONAL_HOSTS if h in url), "")
        if host:
            out.append({"source_id": _source_field(source, "source_id"),
                        "host": host,
                        "read_level": _source_field(source, "read_level")})
    return out


def academic_sources(sources: Iterable[Any] = ()) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for source in sources or ():
        stype = _source_field(source, "source_type").lower()
        if stype in ACADEMIC_SOURCE_TYPES:
            out.append({"source_id": _source_field(source, "source_id"),
                        "read_level": _source_field(source, "read_level")})
    return out


def deeply_read(sources: Iterable[Any] = ()) -> List[str]:
    """Sirf wahi source jinka asli text/claims padha gaya — mila hua nahi."""
    return [_source_field(source, "source_id") for source in sources or ()
            if _source_field(source, "read_level") in DEEP_READ_LEVELS]


# ── LAB report se kaam ka nateeja nikaalna ───────────────────────────────────
# Ye naam `lab.py` ke recipe naam hain. `monte_carlo`, `robustness` aur
# `baseline_tournament` abhi lab me NAHI hain — #150e me aayenge. Tab tak in
# teeno point ka status NOT_MEASURED rehta hai, apni wajah ke saath. Isliye
# yahan `lab.py` import nahi kiya jaata: is module ko usse aage jaana hai, aur
# import karne se dono ek doosre ko bandhak bana lete.
LAB_RECIPE_WALK_FORWARD = "walk_forward"
LAB_RECIPE_MONTE_CARLO = "monte_carlo"
LAB_RECIPE_ROBUSTNESS = "parameter_robustness"
LAB_RECIPE_BASELINE = "baseline_tournament"
LAB_PASS_STATUSES: Tuple[str, ...] = ("TESTED_PASS",)
LAB_RAN_STATUSES: Tuple[str, ...] = ("TESTED_PASS", "TESTED_FAIL")


def lab_tests(lab_report: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for block in (lab_report or {}).get("hypotheses") or ():
        if not isinstance(block, dict):
            continue
        for test in block.get("tests") or ():
            if isinstance(test, dict):
                rows.append(test)
    return rows


def lab_recipe_status(lab_report: Optional[Dict[str, Any]],
                      recipe: str) -> Tuple[int, int]:
    """(kitne chale, kitne pass) — ek hi jagah se, do jagah do ginti nahi."""
    ran = passed = 0
    for test in lab_tests(lab_report):
        if str(test.get("recipe") or "") != recipe:
            continue
        status = str(test.get("status") or "")
        if status in LAB_RAN_STATUSES:
            ran += 1
        if status in LAB_PASS_STATUSES:
            passed += 1
    return ran, passed


# ── ek hi teen-tarfa niyam, har point par ───────────────────────────────────
# NOT_MEASURED  = spec me is cheez ka zikr hi nahi mila (naapne ko kuch nahi)
# NOT_MET       = zikr hai par naap nahi (koi number/shart nahi)
# MET           = zikr bhi hai aur naap bhi
# Default MET kabhi nahi hai. Khaali spec par saare point NOT_MEASURED aate
# hain, "sab theek" nahi.
_NUMBER_RE = re.compile(r"\d")


def topic_lines(text: str, cues: Sequence[str]) -> List[str]:
    """Wo lines jinme in cues me se koi shabd aaya."""
    return [line.strip() for line in _lines(text)
            if _matched(_norm(line), cues)]


def _three_way(text: str, cues: Sequence[str], label: str, need: str,
               also: Sequence[str] = (), also_label: str = "") -> Dict[str, Any]:
    """Ek hi teen-tarfa niyam. `also` = ek doosri cheez jo saath honi chahiye."""
    rows = topic_lines(text, cues)
    if not rows:
        return {"status": NOT_MEASURED, "observed": "zikr nahi mila",
                "expected": need,
                "reason": f"{label} ka spec me koi zikr hi nahi — isliye "
                          f"naapa nahi ja saka (ise 'theek hai' na padha jaaye)"}
    numeric = [row for row in rows if _NUMBER_RE.search(row)]
    if not numeric:
        return {"status": NOT_MET, "observed": f"{len(rows)} line me zikr, 0 me number",
                "expected": need,
                "reason": f"{label} ka naam liya gaya par koi ginti/shart nahi "
                          f"di gayi — naam lena naap nahi hai"}
    if also and not _matched(_norm(text), also):
        return {"status": NOT_MET,
                "observed": f"{len(numeric)} line me number, par "
                            f"{also_label or 'doosri shart'} nahi",
                "expected": need,
                "reason": f"{label} ka number hai par {also_label or 'doosri shart'} "
                          f"kahin nahi — aadha naap poora naap nahi hota"}
    return {"status": MET,
            "observed": f"{len(numeric)} line me number ke saath",
            "expected": need, "reason": f"{label} number ke saath likha gaya"}


def _coverage(text: str, groups: Sequence[Tuple[str, Tuple[str, ...]]],
              minimum: int, label: str, need: str,
              need_number: bool = True) -> Dict[str, Any]:
    """Kitne alag-alag naam se cheezein aayin (ek shabd sab kuch nahi dhak sakta)."""
    hit: List[str] = []
    missing: List[str] = []
    for name, cues in groups:
        rows = topic_lines(text, cues)
        if rows and (not need_number
                     or any(_NUMBER_RE.search(row) for row in rows)):
            hit.append(name)
        else:
            missing.append(name)
    total = len(groups)
    if not hit:
        return {"status": NOT_MEASURED, "observed": f"0/{total}",
                "expected": need,
                "reason": f"{label} me se ek bhi cheez spec me nahi mili — "
                          f"naapne ko kuch nahi tha"}
    if len(hit) < minimum:
        return {"status": NOT_MET, "observed": f"{len(hit)}/{total}: "
                                              + ", ".join(hit),
                "expected": need,
                "reason": f"{label} adhoora hai — ye nahi mile: "
                          + ", ".join(missing[:8])}
    return {"status": MET, "observed": f"{len(hit)}/{total}: " + ", ".join(hit),
            "expected": need,
            "reason": f"{label} me kam se kam {minimum} cheezein number ke saath mili"}


_POINT_CUES: Dict[str, Tuple[str, ...]] = {
    "research_timeframes": ("daily", "4h", "1h", "30m", "tick", "order book",
                            "futures data", "options", "volatility index",
                            "macro data", "intermarket"),
    "theory_base": ("microstructure", "auction", "price discovery", "liquidity",
                    "behavioural", "behavioral", "execution algorithm",
                    "market impact", "adverse selection"),
    "regime_detection": ("regime", "trending", "ranging", "volatility state",
                         "market state"),
    "session_expectancy": ("session", "time of day", "london", "new york",
                           "asian", "opening range", "hour of day"),
    "macro_event_windows": ("pre-news", "pre news", "release", "event window",
                            "nfp", "cpi", "fomc", "fed", "macro window"),
    "intermarket_tests": ("intermarket", "correlation", "dxy", "yield", "vix",
                          "related instrument"),
    "information_theory": ("mutual information", "entropy", "information gain",
                           "conditional information", "redundancy"),
    "game_theory": ("game theory", "incentive", "market maker", "hft",
                    "dealer", "cta", "counterparty", "payoff"),
    "no_leakage": ("leakage", "look ahead", "lookahead", "look-ahead",
                   "repaint", "future candle", "point in time",
                   "information available at t"),
    "realistic_costs": ("spread", "commission", "slippage", "latency",
                        "transaction cost", "cost per trade"),
    "failure_classification": ("failure class", "loss class", "why it lost",
                               "loss reason", "failure mode", "haar ki wajah"),
    "red_team": ("red team", "red-team", "curve fit", "curve-fit",
                 "data mining", "overfit", "cherry pick", "survivorship",
                 "structural change", "falsif"),
    "stop_loss_research": ("stop loss", "stop-loss", "mae",
                           "maximum adverse excursion", "stop placement"),
    "take_profit_research": ("take profit", "take-profit", "target", "1r",
                             "2r", "3r", "partial", "trailing", "time exit"),
    "final_spec_tradeable": ("trading hours", "position size", "lot size",
                             "news rule", "no-trade rule", "final spec",
                             "uncertainty interval", "confidence interval"),
    "instrument_scope": (),      # apna evaluator hai
}


def _instrument_scope(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ask: TradeAsk = ctx["ask"]
    need = CONTRACT_BY_ID["instrument_scope"].needs
    if len(ask.instruments) < 2:
        return {"status": NOT_MEASURED,
                "observed": f"{len(ask.instruments)} instrument maange gaye",
                "expected": need,
                "reason": "do se kam instrument maange gaye — alag-alag padhne "
                          "ka sawaal hi nahi utha"}
    norm = _norm(ctx["spec"])
    named = [item for item in INSTRUMENTS if item.instrument_id in ask.instruments
             and _matched(norm, item.cues)]
    if len(named) < len(ask.instruments):
        missing = [i for i in ask.instruments
                   if i not in [n.instrument_id for n in named]]
        return {"status": NOT_MET,
                "observed": f"{len(named)}/{len(ask.instruments)} instrument spec me",
                "expected": need,
                "reason": "in instrument par apna alag hissa nahi mila: "
                          + ", ".join(missing)}
    per_instrument_numbers = 0
    for item in named:
        rows = topic_lines(ctx["spec"], item.cues)
        if any(_NUMBER_RE.search(row) for row in rows):
            per_instrument_numbers += 1
    if per_instrument_numbers < len(named):
        return {"status": NOT_MET,
                "observed": f"{per_instrument_numbers}/{len(named)} ke apne number",
                "expected": need,
                "reason": "dono instrument ka naam hai par har ek ka apna "
                          "number nahi — ek hi model dono par thopa gaya lagta hai"}
    return {"status": MET, "observed": f"{len(named)} instrument alag-alag",
            "expected": need,
            "reason": "har instrument ka apna hissa aur apne number mile"}


def _execution_chain(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ask: TradeAsk = ctx["ask"]
    need = CONTRACT_BY_ID["execution_chain"].needs
    chain = dict(ask.chain)
    if len(chain) < len(CHAIN_ROLES):
        missing = [role for role in CHAIN_ROLES if role not in chain]
        return {"status": NOT_MEASURED,
                "observed": f"{len(chain)}/3 role ka timeframe mila",
                "expected": need,
                "reason": "farmaish me in role ka timeframe saaf nahi tha: "
                          + ", ".join(missing)}
    minutes = [_TF_BY_NAME.get(chain[role], 0) for role in CHAIN_ROLES]
    if not (minutes[0] > minutes[1] > minutes[2]):
        return {"status": NOT_MET,
                "observed": " -> ".join(f"{role}:{chain[role]}"
                                        for role in CHAIN_ROLES),
                "expected": need,
                "reason": "kram bada->chhota nahi hai (context sabse bada aur "
                          "entry sabse chhota hona chahiye)"}
    norm = _norm(ctx["spec"])
    in_spec = [chain[role] for role in CHAIN_ROLES
               if _matched(norm, _TF_CUES_BY_NAME.get(chain[role], ()))]
    if len(in_spec) < len(CHAIN_ROLES):
        return {"status": NOT_MET,
                "observed": f"{len(in_spec)}/3 timeframe spec me mile",
                "expected": need,
                "reason": "farmaish me chain saaf thi par spec me teeno "
                          "timeframe naam se nahi aaye"}
    return {"status": MET,
            "observed": " -> ".join(f"{role}:{chain[role]}"
                                    for role in CHAIN_ROLES),
            "expected": need,
            "reason": "teeno role ka timeframe saaf hai aur kram sahi hai"}


_TF_CUES_BY_NAME: Dict[str, Tuple[str, ...]] = {
    name: cues for name, _minutes, cues in TIMEFRAMES}


# ── source-wale point: ginti sources se aati hai, spec ke daawe se nahi ──────
def _from_sources(ctx: Dict[str, Any], key: str, point_id: str,
                  label: str) -> Dict[str, Any]:
    need = CONTRACT_BY_ID[point_id].needs
    rows = ctx[key]
    total = len(ctx["sources"])
    if not total:
        return {"status": NOT_MEASURED, "observed": "0 source aaye",
                "expected": need,
                "reason": f"is run me koi source hi nahi aaya, isliye {label} "
                          f"ki ginti ho hi nahi sakti"}
    if not rows:
        return {"status": NOT_MET, "observed": f"0/{total} source",
                "expected": need,
                "reason": f"{total} source aaye par unme ek bhi {label} nahi — "
                          f"ginti badhne se yeh point nahi bharta"}
    return {"status": MET, "observed": f"{len(rows)}/{total} source",
            "expected": need,
            "reason": f"{label}: " + ", ".join(
                str(row.get("source_id") if isinstance(row, dict) else row)
                for row in rows[:5])}


def _theory_base(ctx: Dict[str, Any]) -> Dict[str, Any]:
    need = CONTRACT_BY_ID["theory_base"].needs
    rows = topic_lines(ctx["spec"], _POINT_CUES["theory_base"])
    if not rows:
        return {"status": NOT_MEASURED, "observed": "theory ka zikr nahi",
                "expected": need,
                "reason": "microstructure/auction/liquidity jaisa koi vishay spec "
                          "me nahi aaya — naapne ko kuch nahi"}
    if not ctx["deep"]:
        return {"status": NOT_MET, "observed": f"{len(rows)} line theory ki, "
                                              f"0 source poora padha",
                "expected": need,
                "reason": "theory ke naam liye gaye par kisi source ka asli text/"
                          "claims padha hi nahi gaya — naam yaad hona padhna nahi hai"}
    return {"status": MET,
            "observed": f"{len(rows)} theory line, {len(ctx['deep'])} source gehra padha",
            "expected": need,
            "reason": "theory ke vishay spec me hain aur unke peeche poore padhe "
                      "gaye source hain"}


def _lab_point(ctx: Dict[str, Any], point_id: str, recipe: str, label: str,
               absent_reason: str) -> Dict[str, Any]:
    """LAB ke asli nateeje se — spec ke likhe daawe se nahi."""
    need = CONTRACT_BY_ID[point_id].needs
    ran, passed = lab_recipe_status(ctx["lab_report"], recipe)
    claimed = bool(topic_lines(ctx["spec"], _LAB_CLAIM_CUES[point_id]))
    if not ran:
        if claimed:
            return {"status": NOT_MET, "observed": "spec me daawa, lab me 0 test",
                    "expected": need,
                    "reason": f"{label} ka daawa spec me hai par LAB me ek bhi "
                              f"{recipe} test chala hi nahi — likha hua naap nahi hai"}
        return {"status": NOT_MEASURED, "observed": "0 test chale",
                "expected": need, "reason": absent_reason}
    if not passed:
        return {"status": NOT_MET, "observed": f"{ran} test chale, 0 pass",
                "expected": need,
                "reason": f"{label} chala par pass nahi hua — ye nateeja "
                          f"chhupaya nahi jaata"}
    return {"status": MET, "observed": f"{ran} test chale, {passed} pass",
            "expected": need,
            "reason": f"{label} ka nateeja LAB se aaya hai (PASS = 'ab tak toota "
                      f"nahi', asli duniya ka saboot nahi)"}


_LAB_CLAIM_CUES: Dict[str, Tuple[str, ...]] = {
    "walk_forward_validation": ("walk forward", "walk-forward", "out of sample",
                                "out-of-sample", "held out", "held-out",
                                "untouched test", "rolling validation"),
    "monte_carlo_risk": ("monte carlo", "monte-carlo", "simulation",
                         "risk of ruin", "losing streak"),
    "parameter_robustness": ("parameter sweep", "robustness", "robust region",
                             "neighbouring value", "neighboring value",
                             "magic number"),
    "baseline_tournament": ("baseline", "orb", "opening range",
                            "random entry", "buy and hold", "benchmark model"),
}


# ── concept-wale point ───────────────────────────────────────────────────────
# Yahan asli sawaal ye NAHI hai ki "ICT sahi hai ya galat". Sawaal ye hai:
# jis concept ka naam liya gaya, uski EXACT definition likhi gayi ya nahi, aur
# uska baseline se muqabla hua ya nahi. Naam ki izzat se koi point nahi bharta.
_DEFINITION_CUES: Tuple[str, ...] = (
    "if ", "when ", "agar ", "define", "definition", "rule:", "condition:",
    ">=", "<=", ">", "<", "=", "candle", "bar", "atr", "percentile", "pips",
    "ticks", "points",
)
_BASELINE_CUES: Tuple[str, ...] = (
    "baseline", "random", "benchmark", "control", "muqabla", "compared with",
    "compared to", "versus", " vs ",
)
_SAMPLE_CUES: Tuple[str, ...] = (
    "sample size", "n =", "n=", "trades", "observations", "occurrences",
    "instances", "count =", "kitne trade",
)


def _named_concepts_in(ctx: Dict[str, Any]) -> List[str]:
    """Ask me ya spec me jo concept naam se aaye."""
    norm = _norm(ctx["spec"])
    found = list(ctx["ask"].concepts)
    for key, cues in NAMED_CONCEPTS:
        if key not in found and _matched(norm, cues):
            found.append(key)
    return found


def _concept_definitions(ctx: Dict[str, Any]) -> Dict[str, Any]:
    need = CONTRACT_BY_ID["concept_definitions"].needs
    names = _named_concepts_in(ctx)
    if not names:
        return {"status": NOT_MEASURED, "observed": "koi named concept nahi",
                "expected": need,
                "reason": "ICT/SMC/Wyckoff jaisa koi concept na farmaish me na "
                          "spec me aaya — isliye definition ka sawaal nahi utha"}
    cue_map = dict(NAMED_CONCEPTS)
    defined: List[str] = []
    undefined: List[str] = []
    for key in names:
        rows = topic_lines(ctx["spec"], cue_map.get(key, (key,)))
        ok = any(_matched(_norm(row), _DEFINITION_CUES)
                 and _NUMBER_RE.search(row) for row in rows)
        (defined if ok else undefined).append(key)
    if not defined:
        return {"status": NOT_MET,
                "observed": f"0/{len(names)} concept ki exact definition",
                "expected": need,
                "reason": "in concept ka naam liya gaya par ek ki bhi if-then "
                          "definition number ke saath nahi: " + ", ".join(names)}
    if undefined:
        return {"status": NOT_MET,
                "observed": f"{len(defined)}/{len(names)} defined",
                "expected": need,
                "reason": "in concept ki definition abhi bhi shabdon me hai, "
                          "code me nahi: " + ", ".join(undefined)}
    return {"status": MET, "observed": f"{len(defined)}/{len(names)} defined",
            "expected": need,
            "reason": "har named concept ki exact shart number ke saath likhi hai"}


def _no_authority_truth(ctx: Dict[str, Any]) -> Dict[str, Any]:
    need = CONTRACT_BY_ID["no_authority_truth"].needs
    names = _named_concepts_in(ctx)
    if not names:
        return {"status": NOT_MEASURED, "observed": "koi named concept nahi",
                "expected": need,
                "reason": "koi concept naam se nahi aaya — authority ka sawaal "
                          "hi nahi utha"}
    has_baseline = bool(_matched(_norm(ctx["spec"]), _BASELINE_CUES))
    has_sample = bool(_matched(_norm(ctx["spec"]), _SAMPLE_CUES))
    if not has_baseline or not has_sample:
        missing = []
        if not has_baseline:
            missing.append("baseline se muqabla")
        if not has_sample:
            missing.append("sample size")
        return {"status": NOT_MET,
                "observed": f"{len(names)} concept, baseline={has_baseline}, "
                            f"sample={has_sample}",
                "expected": need,
                "reason": "concept ko jagah kamaani padti hai; ye nahi mila: "
                          + ", ".join(missing)}
    return {"status": MET,
            "observed": f"{len(names)} concept, baseline+sample dono",
            "expected": need,
            "reason": "har concept ke saath muqabla aur sample size ka zikr hai"}


def _subjective_terms_banned(ctx: Dict[str, Any]) -> Dict[str, Any]:
    need = CONTRACT_BY_ID["subjective_terms_banned"].needs
    if not _lines(ctx["spec"]):
        return {"status": NOT_MEASURED, "observed": "spec khaali",
                "expected": need,
                "reason": "koi spec text hi nahi aaya — shabd naapne ko kuch nahi"}
    hits = ctx["subjective"]
    loose = [hit for hit in hits if not hit.get("quantified")]
    if loose:
        return {"status": NOT_MET,
                "observed": f"{len(loose)} bina-number, {len(hits) - len(loose)} number ke saath",
                "expected": need,
                "reason": "ye shabd bina kisi ginti ke bache hain (line no ke saath): "
                          + "; ".join(f"{hit['term']}@L{hit['line_no']}"
                                      for hit in loose[:6])}
    return {"status": MET,
            "observed": f"{len(hits)} hit, sab number/shart ke saath",
            "expected": need,
            "reason": "koi discretionary shabd bina naap ke nahi bacha "
                      "(list poori nahi hai — SUBJECTIVE_LIST_IS_NOT_EXHAUSTIVE)"}


_ORDER_FLOW_CLAIM_CUES: Tuple[str, ...] = (
    "order flow", "orderflow", "footprint", "level 2", "level-2", "l2",
    "delta divergence", "cumulative delta", "tape reading", "dom",
    "market depth", "bid ask imbalance",
)
# Ek line jo KEH RAHI HAI ki order-flow data nahi padha gaya, wo daawa NAHI hai —
# wo imaandaari hai. Usko FAIL ginna khud ek galat naap hoti.
_ORDER_FLOW_DENIAL_CUES: Tuple[str, ...] = (
    "nahi", "not read", "no order flow", "without order flow", "unavailable",
    "no access", "0 padha", "missing", "absent", "no source", "cannot",
    "nahin", "na padha",
)


def _order_flow_edge(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Ye point structurally MET nahi ho sakta — par jhootha daawa FAIL hai."""
    point = CONTRACT_BY_ID["order_flow_edge"]
    rows = [row for row in topic_lines(ctx["spec"], _ORDER_FLOW_CLAIM_CUES)
            if not _matched(_norm(row), _ORDER_FLOW_DENIAL_CUES)]
    if rows:
        return {"status": NOT_MET,
                "observed": f"{len(rows)} line me order-flow ka daawa",
                "expected": point.needs,
                "reason": "order flow ka edge likha gaya hai par is app me "
                          "footprint/L2 data padha hi nahi gaya "
                          f"(ORDER_BOOK_READ={ORDER_BOOK_READ}) — "
                          "bina data ka daawa MET nahi ho sakta",
                "blocked_by": point.blocked_by}
    return {"status": NOT_MEASURED, "observed": "koi order-flow daawa nahi",
            "expected": point.needs,
            "reason": point.blocked_by, "blocked_by": point.blocked_by}


# ── hypothesis-wale point ────────────────────────────────────────────────────
_HYP_ID_RE = re.compile(r"\bH(\d{1,2})\b")
_MECHANISM_KEYS: Tuple[str, ...] = ("mechanism", "why", "statement", "claim",
                                    "hypothesis", "text", "title")


def _hypothesis_blob(item: Any) -> str:
    if isinstance(item, dict):
        for key in _MECHANISM_KEYS:
            if item.get(key):
                return str(item[key])
        return " ".join(str(value) for value in item.values())
    return str(item or "")


def _competing_hypotheses(ctx: Dict[str, Any]) -> Dict[str, Any]:
    need = CONTRACT_BY_ID["competing_hypotheses"].needs
    rows = list(ctx["hypotheses"])
    in_text = {int(num) for num in _HYP_ID_RE.findall(ctx["spec"])}
    count = max(len(rows), len(in_text))
    if not count:
        return {"status": NOT_MEASURED, "observed": "0 hypothesis",
                "expected": need,
                "reason": "is run me ek bhi hypothesis nahi bani — ginti karne "
                          "ko kuch nahi (ise 'kaafi hain' na padha jaaye)"}
    if count < MIN_COMPETING_HYPOTHESES:
        return {"status": NOT_MET, "observed": f"{count} hypothesis",
                "expected": need,
                "reason": f"kam se kam {MIN_COMPETING_HYPOTHESES} maange gaye the, "
                          f"mile {count} — kami chhupayi nahi jaati"}
    if rows:
        seen = {_norm(_hypothesis_blob(item))[:80] for item in rows}
        if len(seen) < count:
            return {"status": NOT_MET,
                    "observed": f"{count} entry par {len(seen)} alag mechanism",
                    "expected": need,
                    "reason": "ginti poori hai par mechanism dohra raha hai — "
                              "ek hi baat ko saat naam dena saat hypothesis nahi hai"}
    return {"status": MET, "observed": f"{count} alag hypothesis",
            "expected": need,
            "reason": f"{count} hypothesis, mechanism alag-alag"}


def _original_hypotheses(ctx: Dict[str, Any]) -> Dict[str, Any]:
    need = CONTRACT_BY_ID["original_hypotheses"].needs
    count = ctx["original_count"]
    if not count:
        return {"status": NOT_MEASURED, "observed": "0 labelled entry",
                "expected": need,
                "reason": f"'{ORIGINAL_HYPOTHESIS_LABEL}' label kisi entry par "
                          f"nahi mila — aur andaaza lagakar apni hypothesis "
                          f"ginna jhooth hota"}
    if count < MIN_ORIGINAL_HYPOTHESES:
        return {"status": NOT_MET, "observed": f"{count} labelled",
                "expected": need,
                "reason": f"kam se kam {MIN_ORIGINAL_HYPOTHESES} nayi hypothesis "
                          f"chahiye thi, label lagi mili {count}"}
    return {"status": MET, "observed": f"{count} labelled",
            "expected": need,
            "reason": f"{count} nayi hypothesis saaf label ke saath "
                      f"(nayi hona sach hona nahi hai — inka test alag se hota hai)"}


def _game_theory(ctx: Dict[str, Any]) -> Dict[str, Any]:
    need = CONTRACT_BY_ID["game_theory"].needs
    rows = topic_lines(ctx["spec"], _POINT_CUES["game_theory"])
    stories = ctx["stories"]
    if not rows:
        if stories:
            return {"status": NOT_MET, "observed": f"{len(stories)} kahani, 0 tark",
                    "expected": need,
                    "reason": "'institutions ne stop hunt kiya' jaisi baat likhi hai "
                              "par kiska kya faayda tha wo tark nahi: "
                              + "; ".join(stories[:3])}
        return {"status": NOT_MEASURED, "observed": "game theory ka zikr nahi",
                "expected": need,
                "reason": "kisi participant ke incentive ka zikr nahi aaya — "
                          "naapne ko kuch nahi"}
    if stories:
        return {"status": NOT_MET,
                "observed": f"{len(rows)} tark-line, {len(stories)} bina-saboot kahani",
                "expected": need,
                "reason": "incentive ka tark hai par saath me bina-saboot kahani "
                          "bhi bachi hai: " + "; ".join(stories[:3])}
    return {"status": MET, "observed": f"{len(rows)} line incentive ki, 0 kahani",
            "expected": need,
            "reason": "participant ke incentive ka tark hai aur koi bina-saboot "
                      "'mera stop hunt hua' wali kahani nahi"}


_LEAKAGE_CLEAR_CUES: Tuple[str, ...] = (
    "no leakage", "koi leakage nahi", "leakage nahi", "leak-free", "clean",
    "pass", "verified", "point in time", "point-in-time", "only past",
    "t se pehle", "available at t",
)


def _no_leakage(ctx: Dict[str, Any]) -> Dict[str, Any]:
    need = CONTRACT_BY_ID["no_leakage"].needs
    rows = topic_lines(ctx["spec"], _POINT_CUES["no_leakage"])
    if not rows:
        return {"status": NOT_MEASURED, "observed": "leakage check ka zikr nahi",
                "expected": need,
                "reason": "leakage ka koi naam-wala check spec me nahi — aur "
                          "'zikr nahi hua' ka matlab 'leakage nahi tha' NAHI hai"}
    cleared = [row for row in rows if _matched(_norm(row), _LEAKAGE_CLEAR_CUES)]
    if not cleared:
        return {"status": NOT_MET, "observed": f"{len(rows)} line, 0 saaf nateeja",
                "expected": need,
                "reason": "leakage ka zikr hai par kisi check ka nateeja nahi likha — "
                          "sawaal uthana jawab nahi hai"}
    return {"status": MET, "observed": f"{len(cleared)}/{len(rows)} line me nateeja",
            "expected": need,
            "reason": "leakage ke check naam se chale aur unka nateeja likha gaya"}


# ── execution-wale point ─────────────────────────────────────────────────────
def _entry_model_exact(ctx: Dict[str, Any]) -> Dict[str, Any]:
    need = CONTRACT_BY_ID["entry_model_exact"].needs
    slots = ctx["slots"]
    filled = [key for key, ok in slots.items() if ok]
    empty = [key for key, ok in slots.items() if not ok]
    if not filled:
        return {"status": NOT_MEASURED, "observed": f"0/{len(ENTRY_SLOT_KEYS)} khaane",
                "expected": need,
                "reason": "entry model ka ek bhi khaana spec me nahi mila — "
                          "naapne ko koi entry rule hi nahi tha"}
    if empty:
        return {"status": NOT_MET,
                "observed": f"{len(filled)}/{len(ENTRY_SLOT_KEYS)} khaane bhare",
                "expected": need,
                "reason": "ye khaane khaali hain: " + ", ".join(empty)
                          + " — adhoora entry rule live market me chalta nahi"}
    loose = [hit for hit in ctx["subjective"] if not hit.get("quantified")]
    if loose:
        return {"status": NOT_MET,
                "observed": f"{len(ENTRY_SLOT_KEYS)}/{len(ENTRY_SLOT_KEYS)} khaane, "
                            f"{len(loose)} discretionary shabd",
                "expected": need,
                "reason": "nau khaane bhare hain par faisla abhi bhi aankh par "
                          "chhoda gaya hai: "
                          + "; ".join(f"{hit['term']}@L{hit['line_no']}"
                                      for hit in loose[:5])}
    return {"status": MET, "observed": f"{len(ENTRY_SLOT_KEYS)}/{len(ENTRY_SLOT_KEYS)} khaane",
            "expected": need,
            "reason": "nau me se nau khaane bhare hain aur koi discretionary "
                      "shabd bina naap ke nahi bacha"}


_FINAL_SPEC_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("trading hours", ("trading hours", "session window", "kab trade",
                       "utc", "ist", "market hours")),
    ("position size", ("position size", "lot size", "risk per trade",
                       "% of equity", "sizing")),
    ("news rule", ("news rule", "news window", "event rule", "avoid news",
                   "pre-news", "release")),
    ("no-trade rule", ("no-trade", "no trade", "skip", "avoid", "stand aside")),
    ("uncertainty", ("uncertainty", "confidence interval", "interval",
                     "+/-", "±", "range of")),
    ("sample size", _SAMPLE_CUES),
)
_RED_TEAM_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("data mining", ("data mining", "data-mining", "multiple testing",
                     "how many variants")),
    ("leakage", ("leakage", "look ahead", "lookahead", "repaint")),
    ("sample size", _SAMPLE_CUES),
    ("one year only", ("one year", "single year", "ek saal", "period length",
                       "multiple years")),
    ("one session only", ("one session", "single session", "ek session",
                          "all sessions")),
    ("costs", ("cost", "spread", "slippage", "commission")),
    ("one threshold", ("one threshold", "single threshold", "magic number",
                       "parameter sweep", "neighbouring", "neighboring")),
    ("survivorship", ("survivorship", "survivor bias", "delisted",
                      "contract roll")),
    ("fake causal story", ("causal", "story", "narrative", "mechanism proof")),
    ("structural change", ("structural change", "regime change", "market changed",
                           "edge decay", "decay")),
    ("cherry picking", ("cherry pick", "cherry-pick", "best window",
                        "selected period")),
)
_COST_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("spread", ("spread",)),
    ("commission", ("commission", "fee", "brokerage")),
    ("slippage", ("slippage", "fill quality")),
    ("latency", ("latency", "delay", "execution lag")),
    ("news slippage", ("news slippage", "event slippage", "gap")),
)
_RESEARCH_DATA_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("higher timeframes", ("daily", "1d", "4h", "1h", "30m", "weekly")),
    ("tick / order book", ("tick", "order book", "l2", "footprint", "depth")),
    ("futures", ("futures", "cme", "micro e-mini", "comex", "open interest")),
    ("macro", ("macro", "cpi", "nfp", "fomc", "yield", "rate decision")),
    ("volatility", ("volatility", "atr", "vix", "gvz", "realised vol",
                    "realized vol")),
    ("options", ("options", "implied volatility", "gamma", "put call")),
    ("intermarket", ("intermarket", "dxy", "correlation", "related market")),
)


# ── risk aur imaandaari wale point ───────────────────────────────────────────
def _performance_metrics(ctx: Dict[str, Any]) -> Dict[str, Any]:
    need = CONTRACT_BY_ID["performance_metrics"].needs
    metrics = ctx["metrics"]
    present = [key for key, ok in metrics.items() if ok]
    missing = [key for key, ok in metrics.items() if not ok]
    chased = ctx["chased"]
    if not present:
        return {"status": NOT_MEASURED, "observed": f"0/{len(METRIC_KEYS)} metric",
                "expected": need,
                "reason": "ek bhi performance number naam se nahi likha gaya — "
                          "naapne ko kuch nahi"}
    if chased:
        return {"status": NOT_MET,
                "observed": f"{len(present)}/{len(METRIC_KEYS)} metric, "
                            f"win-rate daawa {chased}",
                "expected": need,
                "reason": f"{MAX_CREDIBLE_WIN_RATE:.0f}% ya usse upar ka win-rate "
                          f"daawa hai — ye apne aap me FAIL hai, chahe baaki "
                          f"number likhe hon"}
    if missing:
        return {"status": NOT_MET,
                "observed": f"{len(present)}/{len(METRIC_KEYS)} metric",
                "expected": need,
                "reason": "ye number nahi likhe gaye: " + ", ".join(missing)
                          + " — sirf win rate se model ki sehat pata nahi chalti"}
    return {"status": MET, "observed": f"{len(present)}/{len(METRIC_KEYS)} metric",
            "expected": need,
            "reason": "saare number likhe hain aur koi 90%+ win-rate daawa nahi"}


_NEGATIVE_RESULT_CUES: Tuple[str, ...] = (
    "failed", "fail", "no edge", "koi edge nahi", "did not work",
    "nahi chala", "rejected", "negative result", "unsupported",
    "[evidence-e]",
)
# `[evidence-d]` JAAN-BOOJH KAR is list me nahi hai. D ka matlab hai "research
# hypothesis — abhi test hi nahi hui", aur "test nahi hui" kabhi "test hui aur
# khilaaf nikli" ke barabar nahi hoti. Agar D ko negative maan lein to koi bhi
# spec sirf apni nayi hypothesis gin kar "hum apni haar bhi dikhate hain" ka
# credit le jaayega — jabki ek bhi cheez fail hui hi nahi. Sirf E (ya saaf
# fail/rejected shabd) hi haar ka saboot hai.


def _evidence_labels_ae(ctx: Dict[str, Any]) -> Dict[str, Any]:
    need = CONTRACT_BY_ID["evidence_labels_ae"].needs
    labels = ctx["labels"]
    if not labels:
        return {"status": NOT_MEASURED, "observed": "0 label",
                "expected": need,
                "reason": "kisi daawe par [EVIDENCE-A..E] label nahi laga — "
                          "bina label ke sab daawe barabar dikhte hain, "
                          "aur ye khud ek khatra hai"}
    negatives = bool(_matched(_norm(ctx["spec"]), _NEGATIVE_RESULT_CUES))
    if len(labels) < 3:
        return {"status": NOT_MET, "observed": "label: " + ", ".join(labels),
                "expected": need,
                "reason": "sirf ek-do tarah ke label lage hain — asli research me "
                          "kuch daawe kamzor bhi nikalte hain"}
    if not negatives:
        return {"status": NOT_MET, "observed": "label: " + ", ".join(labels),
                "expected": need,
                "reason": "label lage hain par koi fail/negative nateeja report me "
                          "nahi — sirf jeetne wali baatein dikhana chhupana hai"}
    return {"status": MET, "observed": "label: " + ", ".join(labels),
            "expected": need,
            "reason": "A-E label lage hain aur jo fail hua wo bhi report me hai"}


_REFUSAL_CUES: Tuple[str, ...] = (
    "insufficient evidence", "kaafi saboot nahi", "saboot kaafi nahi",
    "model nahi bana", "cannot deliver", "not enough data", "missing:",
    "kya missing hai", "incomplete", "adhoora",
)
_DELIVERED_CUES: Tuple[str, ...] = (
    "final spec", "aakhri spec", "final model", "entry rule", "long if",
    "short if", "trade rule",
)
# "final model nahi bana" me `final model` cue hai — par wo delivery NAHI, wo
# inkaar hai. Cue ke turant baad aane wale inkaar ko na dekhein to har imaandaar
# inkaar galti se "model de diya gaya" gina jaayega, aur uske baad hard-fail ka
# hisaab bhi ulta chalega. Isliye cue ke agle thode akshar me nakaar dhoondte
# hain — ye seema jaan-boojh kar chhoti hai (window bada karne se asli delivery
# bhi nakaari lagne lagegi).
_DENIAL_AFTER_CUE_CHARS = 24
_DENIAL_WORDS: Tuple[str, ...] = (
    "nahi", "nhi", " not ", "cannot", "can not", "can't", "bina",
)


def _delivered_cue_hits(norm_text: str) -> List[str]:
    """Wo delivery-cue jinke peechhe turant inkaar nahi likha hai."""
    out: List[str] = []
    for cue in _DELIVERED_CUES:
        for match in re.finditer(
                r"(?<![\w$])" + re.escape(cue.lower()) + r"(?![\w])",
                norm_text):
            tail = norm_text[match.end():match.end() + _DENIAL_AFTER_CUE_CHARS]
            if any(word.strip() in tail for word in _DENIAL_WORDS):
                continue
            out.append(cue)
            break
    return out


def _honest_final_decision(ctx: Dict[str, Any]) -> Dict[str, Any]:
    need = CONTRACT_BY_ID["honest_final_decision"].needs
    norm = _norm(ctx["spec"])
    refused = bool(_matched(norm, _REFUSAL_CUES))
    delivered = bool(_delivered_cue_hits(norm))
    if not refused and not delivered:
        return {"status": NOT_MEASURED, "observed": "na spec, na inkaar",
                "expected": need,
                "reason": "aakhir me na poora model likha gaya na saaf inkaar — "
                          "isliye imaandaari naapi nahi ja saki"}
    if delivered and not refused:
        blocked_fail = ctx.get("_hard_fail_ids") or []
        if blocked_fail:
            return {"status": NOT_MET, "observed": "model diya gaya",
                    "expected": need,
                    "reason": "model to de diya gaya par ye point NOT_MET hain aur "
                              "unka zikr inkaar me nahi hua: "
                              + ", ".join(blocked_fail[:6])}
        return {"status": MET, "observed": "model diya gaya",
                "expected": need,
                "reason": "model saboot ke saath diya gaya aur koi naapa hua "
                          "point jhooth nahi bola"}
    # Sirf inkaar (model diya hi nahi gaya) = imaandaar jawab, chahe kitne hi
    # point fail hue hon — "saboot kaafi nahi" kehna hi to sahi kaam hai.
    # Par inkaar KE SAATH model bhi de dena alag baat hai: tab ek "missing: X"
    # ki line baaki har NOT_MET point ka parda ban jaati hai. Isliye us mile-jule
    # haal me hard fail ko chhupne nahi diya jaata.
    if delivered:
        blocked_fail = ctx.get("_hard_fail_ids") or []
        if blocked_fail:
            return {"status": NOT_MET,
                    "observed": "inkaar/missing list + spec",
                    "expected": need,
                    "reason": "ek 'missing' line likh kar model bhi de diya gaya, "
                              "par ye point NOT_MET hain: "
                              + ", ".join(blocked_fail[:6])}
    return {"status": MET,
            "observed": "inkaar/missing list" + (" + spec" if delivered else ""),
            "expected": need,
            "reason": "saboot kam tha to kya missing hai wo saaf likha gaya — "
                      "model gadha nahi gaya"}


# ── dispatch: har point ka apna naapne wala ──────────────────────────────────
# Ek bhi point bina evaluator ka nahi chhoda ja sakta — `measure()` ke shuru me
# hi ye check hota hai. Warna ek point chup-chaap "naapa nahi gaya" ki aad me
# hamesha ke liye gayab ho jaata.
def _simple(point_id: str, label: str, cues: Sequence[str] = (),
            also: Sequence[str] = (), also_label: str = ""):
    def run(ctx: Dict[str, Any]) -> Dict[str, Any]:
        return _three_way(ctx["spec"], cues or _POINT_CUES[point_id], label,
                          CONTRACT_BY_ID[point_id].needs, also, also_label)
    return run


def _cov(point_id: str, groups: Sequence[Tuple[str, Tuple[str, ...]]],
         minimum: int, label: str, need_number: bool = True):
    def run(ctx: Dict[str, Any]) -> Dict[str, Any]:
        return _coverage(ctx["spec"], groups, minimum, label,
                         CONTRACT_BY_ID[point_id].needs, need_number)
    return run


def _src(point_id: str, key: str, label: str):
    def run(ctx: Dict[str, Any]) -> Dict[str, Any]:
        return _from_sources(ctx, key, point_id, label)
    return run


def _lab(point_id: str, recipe: str, label: str, absent_reason: str):
    def run(ctx: Dict[str, Any]) -> Dict[str, Any]:
        return _lab_point(ctx, point_id, recipe, label, absent_reason)
    return run


_NOT_IN_LAB_YET = ("ye recipe LAB me abhi nahi hai (#150e me aayegi) — isliye "
                   "naapa nahi gaya, aur ise 'ho gaya' nahi likha ja raha")

_EVALUATORS: Dict[str, Any] = {
    "instrument_scope": _instrument_scope,
    "execution_chain": _execution_chain,
    "research_timeframes": _cov("research_timeframes", _RESEARCH_DATA_GROUPS, 3,
                                "research ka data", need_number=False),
    "institutional_sources": _src("institutional_sources", "inst",
                                  "official exchange/regulator document"),
    "academic_sources": _src("academic_sources", "acad", "academic paper"),
    "read_arguments_not_summaries": _src("read_arguments_not_summaries", "deep",
                                         "poora padha gaya source"),
    "theory_base": _theory_base,
    "concept_definitions": _concept_definitions,
    "no_authority_truth": _no_authority_truth,
    "subjective_terms_banned": _subjective_terms_banned,
    "order_flow_edge": _order_flow_edge,
    "competing_hypotheses": _competing_hypotheses,
    "original_hypotheses": _original_hypotheses,
    "regime_detection": _simple("regime_detection", "regime ki pehchaan"),
    "session_expectancy": _simple("session_expectancy", "session/ghante ki expectancy",
                                  also=_SAMPLE_CUES, also_label="sample size"),
    "macro_event_windows": _simple(
        "macro_event_windows", "macro event window",
        also=("trade", "wait", "avoid", "skip", "no-trade", "stand aside"),
        also_label="trade/wait/avoid ka faisla"),
    "intermarket_tests": _simple(
        "intermarket_tests", "intermarket rishta",
        also=("regime", "break", "unstable", "tootta", "time dependent",
              "time-dependent", "redundant"),
        also_label="rishta kab tootta hai"),
    "information_theory": _simple("information_theory", "information theory"),
    "game_theory": _game_theory,
    "no_leakage": _no_leakage,
    "realistic_costs": _cov("realistic_costs", _COST_GROUPS, 3, "asli cost"),
    "walk_forward_validation": _lab(
        "walk_forward_validation", LAB_RECIPE_WALK_FORWARD, "walk-forward",
        "LAB me ek bhi walk-forward test nahi chala (series aayi hi nahi ho "
        "sakti) — isliye held-out ka nateeja nahi hai"),
    "monte_carlo_risk": _lab("monte_carlo_risk", LAB_RECIPE_MONTE_CARLO,
                             "Monte Carlo", _NOT_IN_LAB_YET),
    "parameter_robustness": _lab("parameter_robustness", LAB_RECIPE_ROBUSTNESS,
                                 "parameter robustness", _NOT_IN_LAB_YET),
    "baseline_tournament": _lab("baseline_tournament", LAB_RECIPE_BASELINE,
                                "baseline tournament", _NOT_IN_LAB_YET),
    "failure_classification": _simple("failure_classification",
                                      "haar ki class-wise ginti"),
    "red_team": _cov("red_team", _RED_TEAM_GROUPS, 6, "red-team ke sawaal",
                     need_number=False),
    "entry_model_exact": _entry_model_exact,
    "stop_loss_research": _simple(
        "stop_loss_research", "stop-loss ki research",
        also=("mae", "maximum adverse excursion", "adverse excursion"),
        also_label="MAE ka distribution"),
    "take_profit_research": _simple(
        "take_profit_research", "take-profit ki research",
        also=("expectancy", "expected value", "net r", "average r"),
        also_label="expectancy ka hisaab (win-rate ka nahi)"),
    "final_spec_tradeable": _cov("final_spec_tradeable", _FINAL_SPEC_GROUPS, 4,
                                 "final spec ke hisse"),
    "performance_metrics": _performance_metrics,
    "evidence_labels_ae": _evidence_labels_ae,
    "honest_final_decision": _honest_final_decision,
}


# ── NAAP: ek hi jagah, ek hi kram, har point ka apna nateeja ─────────────────
def measure(ask: Optional[TradeAsk] = None, spec: Any = "",
            sources: Iterable[Any] = (),
            hypotheses: Sequence[Any] = (),
            lab_report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Contract ke har point ko naapo. Default MET nahi — default NOT_MEASURED.

    `honest_final_decision` jaan-boojh kar SABSE AAKHIR me naapa jaata hai,
    kyunki uska sawaal hi ye hai: "jo point fail hue, unka zikr inkaar me hua
    ya nahi". Isliye kram badalna is point ko andha kar dega.
    """
    missing_eval = [pid for pid in CONTRACT_IDS if pid not in _EVALUATORS]
    if missing_eval:
        raise AssertionError(
            "contract point bina naap ke reh gaya: " + ", ".join(missing_eval))

    ask = ask or TradeAsk(asked=False, reason=NOT_ASKED_REASON)
    spec_text = _text_of(spec)
    source_list = list(sources or ())
    hyp_list = list(hypotheses or ())
    ctx: Dict[str, Any] = {
        "ask": ask,
        "spec": spec_text,
        "sources": source_list,
        "hypotheses": hyp_list,
        "lab_report": lab_report or {},
        "inst": institutional_sources(source_list),
        "acad": academic_sources(source_list),
        "deep": deeply_read(source_list),
        "slots": entry_slots(spec_text),
        "metrics": metrics_in(spec_text),
        "subjective": subjective_hits(spec_text),
        "stories": story_claims(spec_text),
        "labels": evidence_labels_in(spec_text),
        "original_count": original_hypothesis_count(hyp_list, spec_text),
        "chased": chased_win_rate(spec_text),
        "_hard_fail_ids": [],
    }

    checks: List[Dict[str, Any]] = []
    for point in CONTRACT:
        result = dict(_EVALUATORS[point.point_id](ctx))
        status = result.get("status")
        if status not in CHECK_STATUSES:
            status = NOT_MEASURED
            result["reason"] = ("naap ka nateeja pehchana nahi gaya, isliye "
                                "NOT_MEASURED (jhoothe MET se behtar)")
        row = {"point_id": point.point_id, "label": point.label,
               "group": point.group, "status": status,
               "expected": result.get("expected") or point.needs,
               "observed": result.get("observed") or "",
               "reason": result.get("reason") or ""}
        if point.blocked_by:
            row["blocked_by"] = point.blocked_by
        checks.append(row)
        if status == NOT_MET:
            ctx["_hard_fail_ids"].append(point.point_id)

    by_status = {name: [row["point_id"] for row in checks
                        if row["status"] == name] for name in CHECK_STATUSES}
    return {
        "schema": SCHEMA_VERSION,
        "asked": bool(ask.asked),
        "contract_points": CONTRACT_POINTS,
        "checks": checks,
        "met": by_status[MET],
        "not_met": by_status[NOT_MET],
        "not_measured": by_status[NOT_MEASURED],
        "met_count": len(by_status[MET]),
        "not_met_count": len(by_status[NOT_MET]),
        "not_measured_count": len(by_status[NOT_MEASURED]),
        "structurally_blocked": list(STRUCTURALLY_BLOCKED),
        "win_rate_claims": win_rate_claims(spec_text),
        "chased_win_rate": ctx["chased"],
        "story_claims": ctx["stories"],
        "subjective_unquantified": [hit for hit in ctx["subjective"]
                                    if not hit.get("quantified")],
        "institutional_source_count": len(ctx["inst"]),
        "academic_source_count": len(ctx["acad"]),
        "deeply_read_count": len(ctx["deep"]),
        "original_hypotheses": ctx["original_count"],
        "evidence_labels": ctx["labels"],
        "live_tested": LIVE_TESTED,
        "broker_connected": BROKER_CONNECTED,
        "order_book_read": ORDER_BOOK_READ,
        "backtest_is_not_future": BACKTEST_IS_NOT_FUTURE,
        "financial_advice": FINANCIAL_ADVICE,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "deterministic": DETERMINISTIC,
        "provider_cost": PROVIDER_COST,
        "not_advice_note": NOT_ADVICE_NOTE,
        "backtest_note": BACKTEST_NOTE,
    }


# ── gate band hone par: "wanted" key hi asli farak hai ──────────────────────
# Sirf `not_asked()` me `wanted` key hoti hai. `study()` ke record me ye key
# hoti hi NAHI. Isse caller saaf-saaf farak kar sakta hai: "darwaza band tha"
# vs "lane chali par kuch nahi mila". Ye do baatein ek jaisi likh dena hi
# purani galti thi.
def not_asked(question: str = "") -> Dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "wanted": False,
        "asked": False,
        "ran": False,
        "reason": request_reason(question) if question else NOT_ASKED_REASON,
        "queries": [],
        "checks": [],
        "guidance_blocks": [],
        "contract_points": CONTRACT_POINTS,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "provider_cost": PROVIDER_COST,
    }


# ── institutional-first query: pehle asli document, phir theory, phir sakhti ─
# Ye function query BANATA hai — chalata nahi (`NETWORK_USED = False`). Kaun
# chalayega ye #150d ka kaam hai. Kram jaan-boojh kar ye hai: exchange/regulator
# ka apna document sabse pehle, kyunki wahi sabse kam mila-jula hota hai.
THEORY_QUERIES: Tuple[str, ...] = (
    "market microstructure limit order book price discovery",
    "auction market theory value area price acceptance",
    "intraday volatility seasonality futures market",
    "short horizon momentum and mean reversion intraday equity index",
    "transaction cost slippage market impact intraday execution",
    "behavioural finance intraday trader behaviour evidence",
    "walk forward validation overfitting trading strategy backtest",
    "information theory mutual information financial time series predictability",
    "game theory market making order anticipation incentives",
)
CONCEPT_QUERY_SUFFIX = "empirical test statistical evidence out of sample"
MAX_QUERIES = 24


def _concept_queries(ask: Optional[TradeAsk]) -> List[str]:
    """Jis concept ka naam liya gaya, uske ASLI test ki query.

    Query me wahi shabd jaata hai jo user ne KHUD likha ("order block"), na ki
    group ka chhota naam ("ict"). Aur ye ek hi jagah likha hai: `study_queries`
    aur `lane_queries` dono yahi bulate hain, warna do jagah do alag concept
    query banti aur ek din dono alag cheez dhoondhne lagti.
    """
    if ask is None or not ask.asked:
        return []
    concept_map = dict(NAMED_CONCEPTS)
    matched = [str(cue).lower() for cue in ask.matched_cues]
    out: List[str] = []
    for key in ask.concepts:
        cues = concept_map.get(key, (key,))
        pick = next((cue for cue in cues if cue.lower() in matched), cues[0])
        out.append(f"{pick} {CONCEPT_QUERY_SUFFIX}")
    return out


def study_queries(ask: Optional[TradeAsk] = None) -> List[str]:
    """Institutional pehle, phir academic theory, phir concept ka asli test."""
    if ask is None or not ask.asked:
        return []
    out: List[str] = []
    for item in INSTRUMENTS:
        if item.instrument_id in ask.instruments:
            out.extend(item.venue_terms)
    for item in INSTRUMENTS:
        if item.instrument_id in ask.instruments:
            out.append(f"{item.label} intraday liquidity and volatility study")
    out.extend(THEORY_QUERIES)
    out.extend(_concept_queries(ask))
    for key, label, _cues in DEMANDS:
        if key in ask.demands and key in _DEMAND_QUERY:
            out.append(_DEMAND_QUERY[key])
    seen: List[str] = []
    for query in out:
        text = " ".join(str(query or "").split())
        if text and text.lower() not in [s.lower() for s in seen]:
            seen.append(text)
    return seen[:MAX_QUERIES]


_DEMAND_QUERY: Dict[str, str] = {
    "monte_carlo": "monte carlo simulation risk of ruin drawdown trading system",
    "robustness": "parameter sensitivity robustness trading strategy overfitting",
    "baseline": "benchmark opening range breakout baseline strategy performance",
    "leakage": "look ahead bias data leakage backtest methodology",
    "costs": "spread commission slippage estimation intraday index futures",
    "regime": "volatility regime detection markov switching intraday",
    "session": "time of day effects intraday returns session expectancy",
    "macro_events": "macroeconomic announcement intraday price impact window",
    "intermarket": "intermarket correlation gold dollar yields regime dependence",
    "information_theory": "entropy mutual information predictability price series",
    "game_theory": "high frequency trading market maker adverse selection game",
    "microstructure": "order book imbalance short horizon price impact evidence",
    "risk_sizing": "position sizing risk of ruin kelly fraction drawdown",
    "red_team": "backtest overfitting deflated sharpe ratio multiple testing",
    "walk_forward": "walk forward analysis rolling out of sample trading",
    "out_of_sample": "out of sample testing trading strategy evaluation",
}


def study_plan(ask: Optional[TradeAsk] = None) -> Dict[str, Any]:
    """#150d ke liye ek saaf plan — kya dhoondhna hai aur kyu."""
    if ask is None or not ask.asked:
        return {"wanted": False, "reason": NOT_ASKED_REASON, "queries": [],
                "institutional_first": True}
    queries = study_queries(ask)
    venue = [term for item in INSTRUMENTS if item.instrument_id in ask.instruments
             for term in item.venue_terms]
    return {
        "asked": True,
        "institutional_first": True,
        "queries": queries,
        "institutional_queries": [q for q in queries if q in venue],
        "theory_queries": [q for q in queries if q in THEORY_QUERIES],
        "instruments": list(ask.instruments),
        "concepts": list(ask.concepts),
        "demands": list(ask.demands),
        "max_queries": MAX_QUERIES,
        "network_used": NETWORK_USED,
        "gemini_calls": GEMINI_CALLS,
        "note": ("query sirf BANI hai, chali nahi — kaun chalayega wo discovery "
                 "tier ka kaam hai"),
    }


# ── #150d: DISCOVERY TIER ke liye lane-wise query ───────────────────────────
# `study_queries()` (upar) poori list deta hai — 24 tak. Discovery tier ko wo
# poori list DENI NAHI hai: har query network par jaati hai aur asli sawaal ka
# budget kha leti hai. Isliye yahan ek chhoti chhat aur ek KRAM hai. Paanch
# group banate hain:
#
#   1. exchange/regulator ka apna document (web)   ← institutional-first
#   2. ICT/SMC/Wyckoff jaise concept (books — ye literature journal me nahi,
#      kitaab/course me milta hai; naam aana sach hona NAHI hai)
#   3. instrument ki liquidity/volatility study (papers)
#   4. academic theory (papers)
#   5. user ki maangi hui sakhti — monte carlo, robustness, baseline (papers)
#
# Group ke BEECH round-robin chalta hai, group ke ANDAR kram wahi rehta hai.
# Wajah naapi hui hai: flat kram me theory ki 9 query pehle nikal jaati thi aur
# user ki KHUD maangi hui sakhti (walk-forward, monte carlo) chhat se bahar gir
# jaati thi. Har pass institutional se shuru hota hai, isliye institutional-
# first ka niyam tootta nahi — pehli query aaj bhi exchange/regulator ki hai
# (jab instrument ka naam aaya ho).
#
# Instrument ka naam na aaye (jaise "order block ka rule banao") to group 1 aur
# 3 khaali rehte hain, par lane BAND nahi hoti — concept ka empirical test aur
# theory tab bhi padhi jaati hai. Us haalat me `institutional_first` jhanda
# planner me False hota hai, kyunki wahan sach me koi venue document nahi aaya.
# Ye function bhi query BANATA hai, chalata nahi (`NETWORK_USED = False`).
MAX_STUDY_QUERIES = 10
LANE_WEB = "web"
LANE_PAPERS = "papers"
LANE_BOOKS = "books"
STUDY_LANES: Tuple[str, ...] = (LANE_WEB, LANE_PAPERS, LANE_BOOKS)

_WHY_VENUE = ("exchange/regulator ka apna document — sabse kam mila-jula "
              "source, isliye pehle")
_WHY_LIQUIDITY = "is instrument ki apni liquidity/volatility ki naapi hui study"
_WHY_THEORY = "academic theory — microstructure, cost, validation ka asli paper"
_WHY_CONCEPT = ("concept ka naam sach hona nahi hai — uska empirical test "
                "dhoondha ja raha hai")
_WHY_DEMAND = "user ne khud ye sakhti maangi thi, iska tareeka padha ja raha hai"


def _ask_instruments(ask: Optional[TradeAsk]) -> List[Instrument]:
    if ask is None or not ask.asked:
        return []
    return [item for item in INSTRUMENTS if item.instrument_id in ask.instruments]


def _study_groups(ask: Optional[TradeAsk]) -> List[Tuple[str, str, List[str]]]:
    """(lane, why, queries) ke paanch group — kram institutional-first.

    Instrument ka naam na aaya ho (jaise "order block ka rule banao") to venue
    aur liquidity group KHAALI rehte hain — par lane band nahi hoti: concept ka
    empirical test aur theory tab bhi padhi jaati hai. Pehle yahan se khaali
    list lautti thi, yaani farmaish maani jaati thi par ek bhi query nahi banti.
    """
    if ask is None or not ask.asked:
        return []
    items = _ask_instruments(ask)
    # venue: round-robin, taaki DO instrument maange gaye ho to doosre ka ek bhi
    # slot na chhine (pehle poore us100 ke baad hi xauusd aata tha).
    venue: List[str] = []
    depth = max((len(item.venue_terms) for item in items), default=0)
    for index in range(depth):
        for item in items:
            if index < len(item.venue_terms):
                venue.append(item.venue_terms[index])
    liquidity = [f"{item.label} intraday liquidity and volatility study"
                 for item in items]
    # Concept query ek hi jagah banti hai (`_concept_queries`), taaki purana
    # `study_queries` aur ye lane version kabhi do alag cheez na dhoondhe.
    concepts = _concept_queries(ask)
    demands = [_DEMAND_QUERY[key] for key, _l, _c in DEMANDS
               if key in ask.demands and key in _DEMAND_QUERY]
    return [
        (LANE_WEB, _WHY_VENUE, venue),
        # Concept kitaab lane par jaata hai: ICT/SMC/Wyckoff ka likha hua
        # journal me nahi, kitaab/course me milta hai. Naam aana sach hona NAHI.
        (LANE_BOOKS, _WHY_CONCEPT, concepts),
        (LANE_PAPERS, _WHY_LIQUIDITY, liquidity),
        (LANE_PAPERS, _WHY_THEORY, list(THEORY_QUERIES)),
        (LANE_PAPERS, _WHY_DEMAND, demands),
    ]


def _dedup(rows: List[Dict[str, str]], limit: int) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen: List[str] = []
    for row in rows:
        text = " ".join(str(row.get("query") or "").split())
        if not text or text.lower() in seen:
            continue
        seen.append(text.lower())
        out.append({"query": text, "lane": row["lane"], "why": row["why"]})
    return out[:max(0, int(limit))]


def lane_queries(ask: Optional[TradeAsk] = None,
                 limit: int = MAX_STUDY_QUERIES) -> List[Dict[str, str]]:
    """{"query","lane","why"} ki chhoti list — institutional pehle.

    Group ke beech ROUND-ROBIN chalta hai (har pass me pehle venue, phir
    concept, phir liquidity, phir theory, phir demand). Wajah naapi hui hai:
    flat kram me theory ki 9 query pehle aa jaati thi aur user ki KHUD maangi
    hui sakhti (monte carlo, walk-forward) budget se bahar gir jaati thi. Har
    pass institutional se hi shuru hota hai, isliye institutional-first ka
    niyam tootta nahi.
    """
    groups = _study_groups(ask)
    if not groups:
        return []
    depth = max((len(queries) for _l, _w, queries in groups), default=0)
    rows: List[Dict[str, str]] = []
    for index in range(depth):
        for lane, why, queries in groups:
            if index < len(queries):
                rows.append({"query": queries[index], "lane": lane, "why": why})
    return _dedup(rows, limit)


def lead_queries(ask: Optional[TradeAsk] = None, limit: int = 3) -> List[str]:
    """Round-1 ki pehli chand query — curated macro-econ intent ki JAGAH.

    Trading model ki farmaish par domain profile `economics` nikalta hai, aur
    uski curated intents ("minimum wage employment effect labour market gdp")
    scalping ke liye bekaar hain. Ye function un slots ke liye institutional-
    first queries deta hai. Base query kabhi nahi girti — wo planner me pehle
    number par hi rehti hai.

    Yahan round-robin JAAN-BOOJH KAR nahi hai: round 1 ke 3 slot me exchange/
    regulator ka document pehle chahiye. Instrument ka naam na ho to yahi list
    concept ke empirical test se shuru hoti hai.
    """
    rows: List[Dict[str, str]] = []
    for lane, why, queries in _study_groups(ask):
        rows.extend({"query": q, "lane": lane, "why": why} for q in queries)
    return [row["query"] for row in _dedup(rows, limit)]


# ── prompt block: sochne wale ko contract dikhao, jhooth ki chhoot nahi ─────
PROMPT_HEADING = "TRADING MODEL CONTRACT (naapa jaayega, maana nahi jaayega)"
PROMPT_MAX_POINTS = 12


def prompt_block(ask: Optional[TradeAsk] = None) -> str:
    """Reasoning prompt me jaane wala block. Ye khud koi model call nahi karta."""
    if ask is None or not ask.asked:
        return ""
    lines: List[str] = [PROMPT_HEADING, ""]
    if ask.instrument_labels:
        lines.append("Instrument (har ek ka apna alag hissa, apne number): "
                     + ", ".join(ask.instrument_labels))
    if ask.chain:
        lines.append("Execution chain: " + " -> ".join(
            f"{role} {name}" for role, name in ask.chain))
    if ask.style_label:
        lines.append("Style: " + ask.style_label)
    if ask.hypothesis_count:
        lines.append(f"Kam se kam {ask.hypothesis_count} sach me alag competing "
                     f"hypothesis, aur kam se kam {MIN_ORIGINAL_HYPOTHESES} apni "
                     f"nayi (label: \"{ORIGINAL_HYPOTHESIS_LABEL}\")")
    lines.append("")
    lines.append("Ye shabd bina number ke likhe to wo point FAIL hoga: "
                 + ", ".join(SUBJECTIVE_TERMS[:8]) + " (aur aise hi baaki).")
    lines.append(f"{MAX_CREDIBLE_WIN_RATE:.0f}%+ win rate ka daawa apne aap me "
                 f"FAIL hai. Expectancy, profit factor, drawdown, risk of ruin "
                 f"likho.")
    lines.append("Har daawe par [EVIDENCE-A] se [EVIDENCE-E] tak ka label lagao. "
                 "Jo fail hua wo bhi likho.")
    lines.append("Saboot kaafi na ho to model banao hi nahi — kya missing hai wo "
                 "likho.")
    lines.append("")
    lines.append("Naape jaane wale point (poori list " f"{CONTRACT_POINTS}):")
    for point in CONTRACT[:PROMPT_MAX_POINTS]:
        lines.append(f"  - {point.point_id}: {point.needs}")
    if CONTRACT_POINTS > PROMPT_MAX_POINTS:
        lines.append(f"  - (aur {CONTRACT_POINTS - PROMPT_MAX_POINTS} point, "
                     f"sab report me alag se naape jaate hain)")
    for point in CONTRACT:
        if point.blocked_by:
            lines.append(f"  ! {point.point_id}: {point.blocked_by} — iska daawa "
                         f"mat karo.")
    lines.append("")
    lines.append(NOT_ADVICE_NOTE)
    return "\n".join(lines)


# ── answer me jaane wala block ──────────────────────────────────────────────
SECTION_HEADING = "### TRADING MODEL ka contract — kya naapa gaya"
NOT_EVIDENCE_LINE = ("Neeche ka har MET matlab: **jo maanga gaya wo likha aur "
                     "naapa gaya**. Iska matlab 'ye model paisa banayega' NAHI hai.")
MAX_SECTION_ROWS = 40
_STATUS_MARK = {MET: "MET", NOT_MET: "NOT MET", NOT_MEASURED: "NAAPA NAHI GAYA"}


def section_lines(report: Optional[Dict[str, Any]] = None) -> List[str]:
    """Report ka wo hissa jo user padhta hai. Fail chhupta nahi."""
    data = report or {}
    if not data.get("checks"):
        return []
    lines: List[str] = [SECTION_HEADING, "", NOT_EVIDENCE_LINE, ""]
    lines.append(f"Ginti: {data.get('met_count', 0)} MET / "
                 f"{data.get('not_met_count', 0)} NOT MET / "
                 f"{data.get('not_measured_count', 0)} naapa nahi gaya "
                 f"(kul {data.get('contract_points', CONTRACT_POINTS)} point)")
    lines.append("")
    # Pehle jo FAIL hua, phir jo naapa nahi ja saka, phir jo bana. Kram
    # jaan-boojh kar ulta hai — buri khabar neeche dabti nahi.
    order = (NOT_MET, NOT_MEASURED, MET)
    shown = 0
    for status in order:
        rows = [row for row in data["checks"] if row.get("status") == status]
        if not rows:
            continue
        lines.append(f"**{_STATUS_MARK[status]} ({len(rows)})**")
        for row in rows:
            if shown >= MAX_SECTION_ROWS:
                break
            shown += 1
            lines.append(f"- `{row.get('point_id')}` — {row.get('label')}")
            if row.get("observed"):
                lines.append(f"  - mila: {row['observed']}")
            if row.get("reason"):
                lines.append(f"  - wajah: {row['reason']}")
            if row.get("blocked_by"):
                lines.append(f"  - rukaawat: {row['blocked_by']}")
        lines.append("")
    if len(data["checks"]) > MAX_SECTION_ROWS:
        lines.append(f"(is section me {MAX_SECTION_ROWS} point dikhaye gaye, "
                     f"naape gaye {len(data['checks'])})")
        lines.append("")
    if data.get("chased_win_rate"):
        lines.append(f"**Chetavni:** {data['chased_win_rate']} — itna win rate "
                     f"ka daawa mila. Ye apne aap me ek FAIL hai, jeet nahi.")
        lines.append("")
    if data.get("story_claims"):
        lines.append("**Bina saboot ki kahani mili** (ye daawe hataye ya naape "
                     "jaane chahiye): " + "; ".join(data["story_claims"][:3]))
        lines.append("")
    lines.append(data.get("backtest_note") or BACKTEST_NOTE)
    lines.append(data.get("not_advice_note") or NOT_ADVICE_NOTE)
    return lines


# ── seema: kya is app me ho hi nahi sakta ───────────────────────────────────
def limits(report: Optional[Dict[str, Any]] = None) -> List[str]:
    """Audit me jaane wali seema-line. Ginti yahin se aati hai, hard-code nahi."""
    data = report or {}
    out: List[str] = [
        "Koi live ya demo trade nahi chala aur kisi broker se connection nahi "
        f"(LIVE_TESTED={LIVE_TESTED}, BROKER_CONNECTED={BROKER_CONNECTED}) — "
        "'ye chalega' ka koi saboot yahan se nahi nikalta.",
        "Tick data, Level-2 order book, footprint aur futures order flow nahi "
        f"padhe gaye (ORDER_BOOK_READ={ORDER_BOOK_READ}, "
        f"TICK_DATA_READ={TICK_DATA_READ}) — inka koi keyless official source "
        "is app me nahi hai.",
        "Held-out (out-of-sample) test purane data par hota hai. Purane data par "
        "sahi nikalna future ka waada nahi hai.",
        "Ye financial advice nahi hai. Kya khareedna, bechna ya hold karna hai — "
        "wo faisla is jawab se nahi nikalta.",
        "Instrument, timeframe, style aur concept ki table sirf ADDRESSING hai "
        "(user ne kis cheez ka naam liya) — us instrument ka asli behaviour us "
        "table me likha hi nahi hai.",
        "Discretionary shabdon ki list poori nahi hai "
        f"(SUBJECTIVE_LIST_IS_NOT_EXHAUSTIVE={SUBJECTIVE_LIST_IS_NOT_EXHAUSTIVE}) "
        "— jo shabd list me nahi, wo pakda nahi jaayega.",
    ]
    blocked = list(data.get("structurally_blocked") or STRUCTURALLY_BLOCKED)
    for point_id in blocked:
        point = CONTRACT_BY_ID.get(point_id)
        if point is not None:
            out.append(f"`{point_id}` MET ho hi nahi sakta: {point.blocked_by}")
    not_measured = list(data.get("not_measured") or [])
    if not_measured:
        out.append("Ye point is run me naape hi nahi ja sake (inhe 'theek hai' "
                   "na padha jaaye): " + ", ".join(not_measured[:10]))
    return out


# Chhat naapi hui ginti se aati hai — koi hard-code number nahi. Aur ye ginti
# SABSE BURE haal se leni padti hai, khaali call se nahi: `limits()` bina report
# 6 pakki line + blocked point deta hai, par asli run me ek line AUR aati hai
# ("ye point naape hi nahi ja sake"). Agar chhat khaali call se banti to koi
# truncate karne wala thik wahi line kaat deta jo buri khabar hai.
MAX_AUDIT_LIMIT_LINES: int = len(limits({"not_measured": list(CONTRACT_IDS)}))


def policy() -> Dict[str, Any]:
    """Ek jagah se saara sach — test aur audit dono isi ko padhte hain."""
    return {
        "schema": SCHEMA_VERSION,
        "contract_points": CONTRACT_POINTS,
        "contract_ids": list(CONTRACT_IDS),
        "groups": list(GROUPS),
        "check_statuses": list(CHECK_STATUSES),
        "default_status": NOT_MEASURED,
        "structurally_blocked": list(STRUCTURALLY_BLOCKED),
        "live_tested": LIVE_TESTED,
        "broker_connected": BROKER_CONNECTED,
        "order_book_read": ORDER_BOOK_READ,
        "tick_data_read": TICK_DATA_READ,
        "profit_not_promised": PROFIT_NOT_PROMISED,
        "backtest_is_not_future": BACKTEST_IS_NOT_FUTURE,
        "concepts_earn_their_place": CONCEPTS_EARN_THEIR_PLACE,
        "financial_advice": FINANCIAL_ADVICE,
        "instrument_list_is_not_exhaustive": INSTRUMENT_LIST_IS_NOT_EXHAUSTIVE,
        "timeframe_list_is_not_exhaustive": TIMEFRAME_LIST_IS_NOT_EXHAUSTIVE,
        "style_list_is_not_exhaustive": STYLE_LIST_IS_NOT_EXHAUSTIVE,
        "subjective_list_is_not_exhaustive": SUBJECTIVE_LIST_IS_NOT_EXHAUSTIVE,
        "institutional_host_list_is_not_exhaustive":
            INSTITUTIONAL_HOST_LIST_IS_NOT_EXHAUSTIVE,
        "min_competing_hypotheses": MIN_COMPETING_HYPOTHESES,
        "min_original_hypotheses": MIN_ORIGINAL_HYPOTHESES,
        "max_credible_win_rate": MAX_CREDIBLE_WIN_RATE,
        "max_audit_limit_lines": MAX_AUDIT_LIMIT_LINES,
        "max_queries": MAX_QUERIES,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "deterministic": DETERMINISTIC,
        "provider_cost": PROVIDER_COST,
        "cannot_measure": list(CANNOT_MEASURE),
        "not_advice_note": NOT_ADVICE_NOTE,
        "backtest_note": BACKTEST_NOTE,
    }


# ── ek hi darwaza: caller sirf `study()` bulata hai ─────────────────────────
def study(question: str = "", spec: Any = "", sources: Iterable[Any] = (),
          hypotheses: Sequence[Any] = (),
          lab_report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Farmaish padho, contract naapo, aur poora record lautao.

    Gate band hone par `not_asked()` lautta hai — usme `wanted: False` hota hai.
    Yahan se lautne wale record me `wanted` key JAAN-BOOJH KAR nahi hai, taaki
    "darwaza band tha" aur "lane chali par kuch nahi mila" kabhi ek jaise na
    dikhein.
    """
    ask = ask_of(question)
    if not ask.asked:
        return not_asked(question)
    report = measure(ask, spec, sources, hypotheses, lab_report)
    block = prompt_block(ask)
    report["ran"] = True
    report["ask"] = ask.to_dict()
    report["queries"] = study_queries(ask)
    report["plan"] = study_plan(ask)
    report["section_lines"] = section_lines(report)
    report["limits"] = limits(report)
    report["max_audit_limit_lines"] = MAX_AUDIT_LIMIT_LINES
    report["guidance_blocks"] = [block] if block else []
    return report


def public_record(report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """API/UI ke liye chhota record — par ek bhi buri khabar kaat kar nahi."""
    data = report or {}
    out = {
        "schema": SCHEMA_VERSION,
        "asked": bool(data.get("asked")),
        "ran": bool(data.get("ran")),
        "contract_points": data.get("contract_points", CONTRACT_POINTS),
        "met_count": data.get("met_count", 0),
        "not_met_count": data.get("not_met_count", 0),
        "not_measured_count": data.get("not_measured_count", 0),
        "not_met": list(data.get("not_met") or []),
        "not_measured": list(data.get("not_measured") or []),
        "structurally_blocked": list(data.get("structurally_blocked")
                                     or STRUCTURALLY_BLOCKED),
        "status_vocabulary": list(CHECK_STATUSES),
        "chased_win_rate": list(data.get("chased_win_rate") or []),
        "story_claims": list(data.get("story_claims") or []),
        "institutional_source_count": data.get("institutional_source_count", 0),
        "academic_source_count": data.get("academic_source_count", 0),
        "deeply_read_count": data.get("deeply_read_count", 0),
        "original_hypotheses": data.get("original_hypotheses", 0),
        "evidence_labels": list(data.get("evidence_labels") or []),
        "live_tested": LIVE_TESTED,
        "broker_connected": BROKER_CONNECTED,
        "order_book_read": ORDER_BOOK_READ,
        "financial_advice": FINANCIAL_ADVICE,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "provider_cost": PROVIDER_COST,
        "limit_lines": list(data.get("limits") or limits(data)),
    }
    if "wanted" in data:
        out["wanted"] = bool(data["wanted"])
        out["reason"] = str(data.get("reason") or "")
    return out




