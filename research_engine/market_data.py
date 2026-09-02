"""#118 — market/economic time-series lane: asli series, asli walk-forward.

Aaj tak `lab._run_walk_forward` sirf itna keh sakta tha: "time-ordered data
nahi hai, isliye backtest chala hi nahi". Wo imaandaar tha par adhoora. Ye
module wo khaali jagah bharta hai — bina jhooth jode:

  * `series_from_text()` — evidence ke andar PEHLE SE likhi hui series
    (saal → number) nikaalta hai. Yahan koi network, koi paisa, koi model call
    nahi. Series ek hi source block se banti hai (jodh-tod se nahi), aur
    period ke step barabar na hon to series maani hi nahi jaati.
  * `series_from_pack()` — discovery ne jo asli provider series laayi (record ke
    `series_meta` mein) usko pehle chunta hai; text wali series backup hai.
  * `walk_forward()` — train → held-out split, expanding window, drift model vs
    naive (random-walk) baseline. Sab deterministic: koi randomness nahi.
  * provider payload parsers (`parse_world_bank`, `parse_fred`,
    `parse_alpha_vantage`, `parse_ecb_sdmx`) — pure functions, isliye offline
    test ho sakte hain aur connector ka network hissa alag rehta hai.

Teen jhooth jinse ye module jaan-boojh kar bachta hai:
  1. "Backtest pass ho gaya" = "future mein paisa banega" — NAHI. Har nateeje
     ke saath `BACKTEST_NOTE` jaata hai.
  2. Ye financial advice nahi hai (`NOT_ADVICE_NOTE`) — kya kharidna/bechna hai
     ye faisla is data se nahi nikalta.
  3. Provider ne rate limit lagayi ho par HTTP 200 bheja ho (Alpha Vantage aisa
     hi karta hai — body mein "Note"/"Information") to usko "0 data mila" kehna
     jhooth hai. Parser usko alag reason code deta hai.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ── imaandaari ki lines (ek jagah, taaki har caller wahi bhasha bole) ─────────
NOT_ADVICE_NOTE = (
    "Ye market/economic DATA hai, financial advice NAHI. Kya khareedna, bechna "
    "ya hold karna hai — wo faisla is jawab se nahi nikalta."
)
BACKTEST_NOTE = (
    "Held-out (out-of-sample) test PURANE data par hota hai. Purane data par "
    "sahi nikalna future ka waada NAHI hai — asli duniya ka test abhi baaki hai."
)
SERIES_LABEL = "market/economic time series"

# ── seemayein (jaan-boojh kar, chupke se nahi) ───────────────────────────────
MIN_SERIES_POINTS = 8       # isse chhoti series par koi backtest nahi
MIN_HOLDOUT_POINTS = 3      # held-out itna chhota ho to koi verdict nahi
TRAIN_FRACTION = 0.7
MAX_SERIES_POINTS = 400
MAX_TEXT_CHARS = 200_000

# Reason codes — inse bahar koi shabd nahi (report inhi par tiki hai).
NO_SERIES = "series_data_missing"          # #116 se wahi naam, jaan-boojh kar
NO_PERIODS = "no_periods_found"
TOO_SHORT = "series_too_short"
IRREGULAR = "irregular_periods"
CONFLICT = "conflicting_values"
UNIT_MISMATCH = "unit_mismatch"
HOLDOUT_SMALL = "holdout_too_small"
FLAT_HOLDOUT = "no_net_move_in_holdout"
PROVIDER_THROTTLED = "provider_rate_limit_note"


@dataclass
class SeriesPoint:
    """Ek naapa hua point. `order` sortable hai (yearly/monthly = mahine)."""
    period: str
    order: int
    value: float
    unit: str = ""


@dataclass
class MarketSeries:
    """Ek time-ordered series + wo kahan se aayi (provenance kabhi khaali nahi)."""
    points: List[SeriesPoint] = field(default_factory=list)
    frequency: str = ""                 # yearly / quarterly / monthly / daily
    unit: str = ""                      # sirf tab bhara jab HAR point par wahi ho
    provider: str = ""                  # "evidence_text" | "world_bank" | ...
    series_id: str = ""
    label: str = ""
    source_ids: List[str] = field(default_factory=list)
    note: str = ""

    def values(self) -> List[float]:
        return [p.value for p in self.points]

    def periods(self) -> List[str]:
        return [p.period for p in self.points]

    def first_period(self) -> str:
        """Sabse purana period. Khaali series par "" — kabhi guess nahi."""
        return self.points[0].period if self.points else ""

    def last_period(self) -> str:
        """Sabse naya period. Khaali series par "" — kabhi guess nahi."""
        return self.points[-1].period if self.points else ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "series_id": self.series_id,
            "label": self.label,
            "frequency": self.frequency,
            "unit": self.unit,
            "source_ids": list(self.source_ids),
            "n_points": len(self.points),
            "first_period": self.first_period(),
            "last_period": self.last_period(),
            "points": [[p.period, p.value] for p in self.points],
            "note": self.note,
            # Ye do line kabhi nahi badalti.
            "not_financial_advice": NOT_ADVICE_NOTE,
            "past_data_only": BACKTEST_NOTE,
        }


# ── period padhna (sab deterministic, koi guess nahi) ────────────────────────
_MONTHS = {m: i + 1 for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"))}

# Kram maayne rakhta hai: pehle sabse KHAAS shakal (din), phir mahina, quarter,
# aur sabse aakhir me akela saal. Ulta kram rakhne par "2019-04" ka "2019"
# hissa pehle match ho jaata aur mahina gum ho jaata.
#    #150i — `stamp` (intraday) sabse PEHLE hai: "2024-03-20 14:30" ka din wala
#    hissa pehle match ho jaata to ghanta gum ho jaata, aur ghanta gum hone ka
#    matlab hai "session/time-of-day naapa hi nahi ja sakta".
#    #150i — mahine ka NAAM poora likha hua chahiye. Pehle `dec[a-z]*` tha, isse
#    "rate decision 2024" ka "decision 2024" hissa "December 2024" ban jaata tha
#    (aur us match ne saal kha liya, jisse aage ka asli waqt bhi gum ho gaya).
_PERIOD_RE = re.compile(
    r"(?P<stamp>(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
    r"[ T](?:[01]\d|2[0-3]):[0-5]\d)"
    r"|(?P<day>(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))"
    r"|(?P<month>(?:19|20)\d{2}[-/](?:0[1-9]|1[0-2])(?![-/]?\d))"
    r"|(?P<mname>\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\.?\s+(?:19|20)\d{2})"
    r"|(?P<quarter>(?:q[1-4]\s*(?:19|20)\d{2})|(?:(?:19|20)\d{2}\s*[-]?\s*q[1-4]))"
    r"|(?P<year>(?:19|20)\d{2})",
    re.IGNORECASE)

_YEAR_ONLY_RE = re.compile(r"^(?:19|20)\d{2}$")


def _read_period(match: "re.Match[str]") -> Optional[Tuple[str, str, int]]:
    """(frequency, label, order) — order yearly/monthly ke liye mahine me."""
    text = match.group(0)
    if match.group("stamp"):
        # #150i — intraday: order MINUTE me. Do frequency ka order ek paimane par
        # laana zaroori nahi hai (mixed granularity `_build` me pehle hi ruk
        # jaati hai), par ek hi series ke andar step barabar naapne ke liye
        # minute chahiye — din ke paimane par 09:30 aur 14:30 ka farak 0 hota.
        head, tail = re.split(r"[ T]", text, maxsplit=1)
        year, month, day = (int(x) for x in head.split("-"))
        hour, minute = (int(x) for x in tail.split(":"))
        label = f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"
        order = (((year * 12 + month - 1) * 31 + day) * 1440) + hour * 60 + minute
        return "intraday", label, order
    if match.group("day"):
        year, month, day = (int(x) for x in text.split("-"))
        return "daily", text, (year * 12 + month - 1) * 31 + day
    if match.group("month"):
        year, month = (int(x) for x in re.split(r"[-/]", text))
        return "monthly", f"{year:04d}-{month:02d}", year * 12 + month - 1
    if match.group("mname"):
        name, year_text = text.split()
        month = _MONTHS[name[:3].lower()]
        year = int(year_text)
        return "monthly", f"{year:04d}-{month:02d}", year * 12 + month - 1
    if match.group("quarter"):
        quarter = int(re.search(r"[qQ]([1-4])", text).group(1))
        year = int(re.search(r"(?:19|20)\d{2}", text).group(0))
        return "quarterly", f"{year:04d}-Q{quarter}", year * 12 + (quarter - 1) * 3
    year = int(text)
    return "yearly", f"{year:04d}", year * 12


MIXED = "mixed_period_granularity"

# Number + uske saath ka unit. Unit ki list SIRF label ke liye hai (kis unit me
# naapa gaya) — isse koi knowledge decide nahi hoti.
_VALUE_RE = re.compile(
    r"(?P<cur>[₹$€£])?\s*(?P<num>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>%|percent(?:age)?(?:\s+points?)?|pp|bps|crore|lakh|arab|"
    r"billion|million|trillion|bn|mn|usd|inr|eur|gbp|jpy|points?|index)?",
    re.IGNORECASE)
_TAG_LINE_RE = re.compile(r"^\s*\[([^\]]{1,40})\]\s*")


def _norm_unit(currency: str, unit: str) -> str:
    token = (unit or "").strip().lower()
    if token.startswith("percent") or token == "%":
        return "%"
    if token in ("pp",):
        return "pp"
    if token:
        return token
    return (currency or "").strip()


def _read_value(segment: str) -> Optional[Tuple[float, str]]:
    """Period ke turant baad ka number. Bina unit wala saal number NAHI hai.

    "2018 2019 2020 ..." jaisi line ko series maan lena sabse aasan jhooth tha:
    har saal ka "value" agla saal ban jaata aur backtest kachre par chal padta.
    """
    match = _VALUE_RE.search(segment or "")
    if not match:
        return None
    raw = match.group("num")
    unit = _norm_unit(match.group("cur") or "", match.group("unit") or "")
    if not unit and _YEAR_ONLY_RE.match(raw):
        return None
    try:
        return float(raw.replace(",", "")), unit
    except ValueError:
        return None


def _collect(text: str) -> Dict[str, List[Tuple[str, SeriesPoint]]]:
    """Har source tag (`[S3]`) ka apna dher. Do source ke number JODE nahi jaate.

    Ye jodh-tod hi sabse khatarnak jhooth hoti: S2 ka 2019 aur S7 ka 2020 mila
    kar ek "series" bana dena, aur phir uspar backtest chala dena.
    """
    groups: Dict[str, List[Tuple[str, SeriesPoint]]] = {}
    for raw_line in str(text or "")[:MAX_TEXT_CHARS].splitlines():
        tag_match = _TAG_LINE_RE.match(raw_line)
        tag = tag_match.group(1).strip() if tag_match else ""
        line = raw_line[tag_match.end():] if tag_match else raw_line
        matches = list(_PERIOD_RE.finditer(line))
        for index, match in enumerate(matches):
            read = _read_period(match)
            if read is None:
                continue
            frequency, label, order = read
            end = (matches[index + 1].start() if index + 1 < len(matches)
                   else len(line))
            found = _read_value(line[match.end():end])
            if found is None:
                continue
            value, unit = found
            groups.setdefault(tag, []).append(
                (frequency, SeriesPoint(period=label, order=order,
                                        value=value, unit=unit)))
    return groups


def _build(rows: Sequence[Tuple[str, SeriesPoint]], provider: str, tag: str,
           require_uniform: bool = True) -> Tuple[Optional[MarketSeries], str]:
    """Ek tag ke dher ko series banao — ya saaf wajah ke saath mana kar do."""
    frequencies = {frequency for frequency, _ in rows}
    if len(frequencies) > 1:
        return None, MIXED
    frequency = next(iter(frequencies))
    by_period: Dict[str, SeriesPoint] = {}
    for _frequency, point in rows:
        seen = by_period.get(point.period)
        if seen is not None and seen.value != point.value:
            # Ek hi period ke do alag number — chup-chaap ek chun lena jhooth hai.
            return None, CONFLICT
        by_period.setdefault(point.period, point)
    points = sorted(by_period.values(), key=lambda p: p.order)
    if len(points) > MAX_SERIES_POINTS:
        points = points[-MAX_SERIES_POINTS:]
    if len(points) < MIN_SERIES_POINTS:
        return None, TOO_SHORT
    gaps = {b.order - a.order for a, b in zip(points, points[1:])}
    if min(gaps) <= 0:
        return None, IRREGULAR
    # Yearly/quarterly/monthly series ka step barabar hona chahiye — bekaar
    # numbers se bani "series" ka step kabhi barabar nahi nikalta. Daily par ye
    # shart nahi lagti: weekend aur chhutti ka gap asli market data me normal hai.
    # #150i — intraday par bhi nahi: raat ka gap (session band) daily ke weekend
    # jaisa hi asli hai, aur us gap ki wajah se intraday series ko "jhoothi"
    # kehna sirf isliye ki bazaar 24 ghante nahi chalta — wo galat naap hoti.
    # `require_uniform=False` SIRF provider series ke liye hai: wahan series ki
    # pehchaan provider ne di hai, aur beech ka ek missing observation series ko
    # jhoothi nahi banata. Text se padhi series par ye dheel kabhi nahi milti.
    if require_uniform and frequency not in ("daily", "intraday") and len(gaps) > 1:
        return None, IRREGULAR
    units = {point.unit for point in points}
    named = {unit for unit in units if unit}
    if len(named) > 1:
        return None, UNIT_MISMATCH
    unit = next(iter(named)) if len(named) == 1 and len(units) == 1 else ""
    return MarketSeries(
        points=points, frequency=frequency, unit=unit, provider=provider,
        series_id=(f"{provider}:{tag}" if tag else provider),
        label=f"{SERIES_LABEL} ({frequency})",
        source_ids=[tag] if tag else [],
        note=("Ye series evidence ke andar likhe numbers se padhi gayi hai "
              "(ek hi source block se) — kisi provider API se nahi."
              if provider == "evidence_text" else ""),
    ), ""


# Wajah batane ka kram: jo sabse KHAAS baat hai wo pehle. "chhoti thi" sabse
# aakhir me, kyunki wo sabse aam aur sabse kam kaam ki wajah hai.
_REASON_ORDER: Tuple[str, ...] = (CONFLICT, UNIT_MISMATCH, MIXED, IRREGULAR,
                                  TOO_SHORT, NO_PERIODS)


def series_from_text(text: str, provider: str = "evidence_text"
                     ) -> Tuple[Optional[MarketSeries], str]:
    """Evidence text me se sabse lambi VALID series. Warna (None, wajah)."""
    groups = _collect(text)
    if not groups:
        return None, NO_PERIODS
    best: Optional[MarketSeries] = None
    reasons: List[str] = []
    for tag in sorted(groups):
        series, reason = _build(groups[tag], provider, tag)
        if series is None:
            reasons.append(reason)
            continue
        if best is None or len(series.points) > len(best.points):
            best = series
    if best is not None:
        return best, ""
    for code in _REASON_ORDER:
        if code in reasons:
            return None, code
    return None, NO_PERIODS


def series_from_pack(pack: Any) -> Tuple[Optional[MarketSeries], str]:
    """Discovery ki laayi asli provider series (record ke `series_meta` se).

    Provider ki naapi hui series text se nikaali series se behtar hai, isliye
    pehle yahi dekhi jaati hai. Kuch na mile to (None, "") — "wajah nahi",
    kyunki text wala raasta abhi baaki hai.
    """
    best: Optional[MarketSeries] = None
    for source in list(getattr(pack, "sources", None) or []):
        meta = getattr(source, "series_meta", None)
        if not isinstance(meta, dict):
            continue
        rows = meta.get("points") or []
        points: List[SeriesPoint] = []
        for row in rows:
            try:
                label, value = str(row[0]), float(row[1])
            except Exception:
                continue
            match = _PERIOD_RE.match(label)
            read = _read_period(match) if match else None
            if read is None:
                continue
            points.append(SeriesPoint(period=read[1], order=read[2],
                                      value=value, unit=str(meta.get("unit") or "")))
        if len(points) < MIN_SERIES_POINTS:
            continue
        points.sort(key=lambda p: p.order)
        series = MarketSeries(
            points=points[-MAX_SERIES_POINTS:],
            frequency=str(meta.get("frequency") or ""),
            unit=str(meta.get("unit") or ""),
            provider=str(meta.get("provider") or ""),
            series_id=str(meta.get("series_id") or ""),
            label=str(meta.get("label") or SERIES_LABEL),
            source_ids=[str(getattr(source, "source_id", "") or "")],
            note=str(meta.get("note") or ""))
        if best is None or len(series.points) > len(best.points):
            best = series
    return best, ""


# ── walk-forward: train → held-out, expanding window, naive baseline ─────────
@dataclass
class WalkForward:
    """Naapa hua nateeja. `ok=False` ka matlab test chala hi nahi."""
    ok: bool = False
    reason_code: str = ""
    n_total: int = 0
    n_train: int = 0
    n_test: int = 0
    hits: int = 0
    scored: int = 0
    model_mae: float = 0.0
    naive_mae: float = 0.0
    net_change: float = 0.0
    net_pct: Optional[float] = None
    train_last: float = 0.0
    holdout_low: float = 0.0
    holdout_high: float = 0.0
    holdout_last: float = 0.0
    first_period: str = ""
    last_period: str = ""
    holdout_first: str = ""
    # #150e — held-out ke HAR step ka signed nateeja (price units me): model ne
    # jis taraf kaha, us taraf chaal hui to +, ulti hui to −, aur koi signal na
    # ho (drift 0) to 0.0. Ye `to_dict` me JAAN-BOOJH KAR nahi jaata (report
    # bhaari ho jaati); ye Monte Carlo aur baseline muqable ka input hai. Isse
    # MC us MODEL par chalta hai jo sach me test hua, buy-and-hold par nahi.
    steps: Tuple[float, ...] = ()
    # Kis drift lookback par ye nateeja aaya (None = poora itihaas, purana
    # bartaav). Robustness sweep ise badal kar dekhta hai ki edge ek REGION me
    # zinda hai ya ek magic number par.
    drift_lookback: Optional[int] = None

    @property
    def direction(self) -> str:
        """Held-out me net chaal. Bilkul flat par khaali (koi faisla nahi)."""
        if self.net_change > 0:
            return "up"
        if self.net_change < 0:
            return "down"
        return ""

    @property
    def beats_naive(self) -> Optional[bool]:
        """Drift model naive (random-walk) se behtar hai ya nahi."""
        if not self.ok or self.naive_mae <= 0:
            return None
        return self.model_mae < self.naive_mae

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "reason_code": self.reason_code,
            "n_total": self.n_total,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "direction_hits": self.hits,
            "direction_scored": self.scored,
            "model_mae": round(self.model_mae, 6),
            "naive_mae": round(self.naive_mae, 6),
            "beats_naive_baseline": self.beats_naive,
            "net_change": round(self.net_change, 6),
            "net_pct": (None if self.net_pct is None
                        else round(self.net_pct, 4)),
            "holdout_first": self.holdout_first,
            "holdout_last_period": self.last_period,
            "holdout_low": round(self.holdout_low, 6),
            "holdout_high": round(self.holdout_high, 6),
            "past_data_only": BACKTEST_NOTE,
            "not_financial_advice": NOT_ADVICE_NOTE,
            "is_established_fact": False,
        }


def walk_forward(series: Optional[MarketSeries],
                 min_points: int = MIN_SERIES_POINTS,
                 min_holdout: int = MIN_HOLDOUT_POINTS,
                 train_fraction: float = TRAIN_FRACTION,
                 drift_lookback: Optional[int] = None) -> WalkForward:
    """Expanding-window walk-forward. Deterministic: koi random seed nahi.

    Har held-out step par model ke paas SIRF us se pehle ka data hota hai
    (peeche se jhaank kar "sahi" jawab nahi utha sakta). Model = drift
    (train ka average change), baseline = naive random-walk (aakhri value).

    `drift_lookback=None` (default) = poora itihaas, yaani #118 ka bilkul wahi
    bartaav. Koi number dene par drift sirf aakhri utne point se banta hai —
    ye #150e ke parameter-robustness sweep ke liye hai, aur ye bhi sirf PICHLA
    data dekhta hai (koi leakage nahi).
    """
    if series is None or not series.points:
        return WalkForward(reason_code=NO_SERIES)
    values = series.values()
    total = len(values)
    if total < max(min_points, 4):
        return WalkForward(reason_code=TOO_SHORT, n_total=total)
    n_test = max(min_holdout, int(round(total * (1.0 - train_fraction))))
    n_train = total - n_test
    if n_test < min_holdout or n_train < max(3, min_points // 2):
        return WalkForward(reason_code=HOLDOUT_SMALL, n_total=total,
                           n_train=max(0, n_train), n_test=max(0, n_test))
    model_error = naive_error = 0.0
    hits = scored = 0
    steps: List[float] = []
    for index in range(n_train, total):
        history = values[:index]
        window = history
        if drift_lookback is not None and drift_lookback >= 2:
            window = history[-int(drift_lookback):]
        drift = ((window[-1] - window[0]) / (len(window) - 1)
                 if len(window) > 1 else 0.0)
        forecast = history[-1] + drift
        actual = values[index]
        model_error += abs(actual - forecast)
        naive_error += abs(actual - history[-1])
        # Ek step ka asli P&L: signal ki taraf chaal hui to fayda, ulti hui to
        # nuksaan, aur bina signal (drift 0) par kuch nahi. Yahan bhi sirf
        # `forecast` istemal hota hai, `actual` ki disha se signal nahi banta.
        move = actual - history[-1]
        if forecast > history[-1]:
            steps.append(move)
        elif forecast < history[-1]:
            steps.append(-move)
        else:
            steps.append(0.0)
        # Direction sirf tab ginti hai jab cheez sach me hili ho — flat step par
        # "sahi disha bata di" kehna muft ka credit hota.
        if actual != history[-1]:
            scored += 1
            if (actual - history[-1] > 0) == (forecast - history[-1] > 0):
                hits += 1
    train_last = values[n_train - 1]
    holdout = values[n_train:]
    net = holdout[-1] - train_last
    return WalkForward(
        ok=True, n_total=total, n_train=n_train, n_test=n_test,
        hits=hits, scored=scored,
        model_mae=model_error / n_test, naive_mae=naive_error / n_test,
        net_change=net,
        net_pct=(None if train_last == 0 else 100.0 * net / abs(train_last)),
        train_last=train_last, holdout_low=min(holdout), holdout_high=max(holdout),
        holdout_last=holdout[-1],
        first_period=series.points[0].period,
        last_period=series.points[-1].period,
        holdout_first=series.points[n_train].period,
        steps=tuple(steps), drift_lookback=drift_lookback)


# ── #150e: backtest ke AAGE ke teen naap (sab deterministic, ₹0) ─────────────
# "Backtest chal gaya" se teen alag sawaalon ka jawab NAHI milta, isliye teen
# alag naap:
#   monte_carlo         — usi nateeje ka kram badal kar drawdown, losing streak,
#                         risk of ruin, aur unse nikla risk-per-trade
#   parameter_sweep     — edge ek REGION me zinda hai ya ek magic number par
#   baseline_tournament — model ko HAR simple baseline se held-out par jeetna hai
#
# Randomness yahan bhi NAHI hai. Aam "Monte Carlo" random draw karta hai; yahan
# uski jagah ek LIKHA HUA niyam hai — har path steps ka ek block-resample hai
# (block stride se chune jaate hain, aur ulta kram bhi), yaani replacement ke
# saath resampling, par bina kisi random number ke. Isliye wahi input par hamesha
# wahi nateeja aata hai aur `randomness_used: False` jhooth nahi banta. Path ki
# ginti bhi ASLI likhi jaati hai — "hazaaron simulation" ka jhootha daawa nahi.
MC_MIN_STEPS = 12            # itne held-out step se kam par koi distribution nahi
MC_MIN_PATHS = 60            # itne se kam path par percentile bemaani hai
MC_MAX_PATHS = 600           # chhat (kram wahi, isliye truncate bhi deterministic)
MC_BLOCK_LENGTHS: Tuple[int, ...] = (1, 2, 3, 4, 6, 8)
MC_RISK_LADDER: Tuple[float, ...] = (0.0025, 0.005, 0.01, 0.02, 0.03, 0.05)
MC_RUIN_LEVEL = 0.5          # equity aadhi reh gayi = ruin
MC_MAX_P95_DRAWDOWN = 0.20   # p95 drawdown ki chhat
MC_MAX_RUIN_PROB = 0.01      # ruin ki chhat (1%)
FEW_STEPS = "too_few_steps_for_simulation"
NO_STEP_MOVED = "no_step_moved_at_all"
FEW_PATHS = "too_few_deterministic_paths"
NO_SAFE_RISK = "no_risk_level_survived"

SWEEP_LOOKBACKS: Tuple[int, ...] = (3, 4, 5, 6, 8, 12)
SWEEP_MIN_SETTINGS = 3       # itne se kam setting par "region" ka daawa nahi
SWEEP_MIN_BEAT_SHARE = 0.6   # region me kam se kam itne setting jeetein
FEW_SETTINGS = "too_few_usable_parameter_settings"

# ── #150f: asli TRADE-level naap (sirf forecast error nahi) ───────────────────
# `walk_forward` sirf ye batata hai ki agla point kitna galat guess hua. Trading
# ka sawaal alag hai: entry, stop, target, cost — inke baad kya bachta hai. Ye
# hissa wahi naapta hai, aur do baat par bilkul saaf hai:
#
#   1. Series me sirf CLOSE hai (SeriesPoint me high/low nahi). Isliye "ek hi bar
#      me pehle SL laga ya TP" ye HISAAB NAHI HO SAKTA. Har exit close par tay
#      hota hai, aur ye baat `CLOSE_ONLY_NOTE` me likh kar bahar jaati hai.
#      Intrabar sequencing ka andaaza lagana yahan jaan-boojh kar mana hai.
#   2. Signal, stop ki naap, aur cost — teeno sirf PICHLE data se bante hain.
#      Kisi bhi step par `values[index]` se signal nahi banta.
TRADE_MIN_TRADES = 8         # itne se kam trade par expectancy naapna dhokha hai
TRADE_R_MULTIPLES: Tuple[float, ...] = (1.0, 1.5, 2.0, 3.0)
TRADE_STOP_UNITS = 1.5       # SL = itne guna pichhli aausat harkat
TRADE_MAX_BARS = 5           # itne bar me exit na hua to time-exit
TRADE_COST_FRACTION = 0.0004  # round-turn cost (spread+commission+slippage), price ka hissa
TRADE_MIN_EXPECTANCY_R = 0.0  # isse neeche expectancy = koi edge nahi
TRADE_MIN_PROFIT_FACTOR = 1.0
TRADE_MIN_ROBUST_SHARE = 0.5  # itne R-setting me expectancy positive ho
FEW_TRADES = "too_few_trades_to_measure_expectancy"
NO_VOLATILITY = "no_past_movement_to_size_a_stop"
NO_EDGE_AFTER_COST = "no_positive_expectancy_after_cost"
# Ek bhi haar na ho to loss-side naapa hi nahi gaya. Aisa sample "edge mil gaya"
# ka saboot NAHI hai — aur "expectancy positive nahi thi" bolna bhi JHOOTH hoga.
# Isliye ye alag, teesri haalat hai: faisla mumkin nahi.
NO_LOSS_TO_MEASURE = "no_losing_trade_in_sample_loss_side_unmeasured"
# Edge sirf ek hi R par zinda ho to wo region nahi, ek magic number hai.
FRAGILE_EDGE = "edge_only_at_one_r_setting"
# Kitni series chahiye — naapa hua, andaaza nahi: 8 trade ke liye ~40 held-out bar
# chahiye (har trade ~TRADE_MAX_BARS bar leti hai), aur held-out series ka
# (1 - TRAIN_FRACTION) hissa hota hai.
TRADE_MIN_SERIES_POINTS = int(round(TRADE_MIN_TRADES * TRADE_MAX_BARS
                                    / (1.0 - TRAIN_FRACTION)))
CLOSE_ONLY_NOTE = ("Series me sirf close hai (high/low nahi), isliye har exit "
                   "close par naapa gaya hai — 'ek hi bar me pehle SL laga ya "
                   "TP' ye hisaab nahi kiya ja sakta, aur andaaza nahi lagaya "
                   "gaya.")
TRADE_COST_NOTE = ("Har trade par round-turn cost lagayi gayi hai (spread + "
                   "commission + slippage ka ek hissa), yaani ye gross nahi "
                   "NET nateeja hai.")
# Har haar ki wajah — teen alag class, aur teeno naapi hui hain (kahani nahi).
LOSS_STOPPED = "stopped_out"          # SL tak gaya
LOSS_TIME_EXIT = "time_exit_negative"  # bar khatam, ulta band hua
LOSS_COST_ONLY = "cost_ate_the_win"    # gross >= 0 tha, cost ke baad negative

# ── #150i-a: SLOT = din/hafte ka wo hissa jisme trade hui ─────────────────────
# intel ke contract me ek point hai: "session / time-of-day ki expectancy
# alag-alag naapi gayi". Aaj tak wo point sirf LIKHE HUE shabd se paas hota tha.
# Ye hissa usko NAAP par le aata hai — par teen hadd ke saath, aur teeno likhi
# hui hain (chupi hui nahi):
#
#   1. Slot ka naam data ki granularity se banta hai, marzi se nahi:
#      intraday → ghanta (h00…h23), daily → weekday, monthly → mahina,
#      quarterly → quarter, yearly → koi slot NAHI (SLOT_TOO_COARSE).
#   2. "London session" / "New York session" jaise naam KABHI nahi bante —
#      period stamp ke saath koi timezone nahi aata, aur bina timezone ghante ko
#      session ka naam dena andaaza hai. Ye baat `SESSION_NAME_NOTE` me bahar
#      jaati hai.
#   3. Slot uska hai jis bar par SIGNAL bana (entry se ek bar pehle), entry wale
#      bar ka nahi — warna slot ka faisla us data se hota jo signal ke waqt
#      maujood hi nahi tha (leakage).
SLOT_MIN_TRADES = 3          # itne se kam trade wale slot ka number bahar nahi
SLOT_MIN_SLOTS = 2           # ek hi slot par "slot-wise farak" bemaani hai
SLOT_HOUR = "hour_of_day"
SLOT_WEEKDAY = "weekday"
SLOT_MONTH = "month_of_year"
SLOT_QUARTER = "quarter_of_year"
SLOT_DIFF_R = 0.25           # best-worst ka itna farak = slot maayne rakhta hai
# Slot ki tulna EK hi R par hoti hai. Har slot ke liye apna "best R" dhoondhna
# cherry-picking hai — tab farak slot ka nahi, R ke chunav ka hota hai.
SLOT_R_MULTIPLE = 2.0
NO_SLOT_LABELS = "period_labels_carry_no_time_slot"
SLOT_TOO_COARSE = "yearly_data_has_no_time_slot"
FEW_SLOTS = "too_few_slots_with_enough_trades"
SLOT_NO_DIFFERENCE = "slot_expectancy_difference_too_small"
NO_INTRADAY_DATA = "no_intraday_stamps_so_hour_of_day_unmeasured"
SESSION_NAME_NOTE = (
    "Slot ka naam ghante ke number se bana hai (h00…h23), 'London'/'New York' "
    "jaise session ke naam se NAHI — period stamp ke saath koi timezone nahi "
    "aata, isliye ghante ko session ka naam dena andaaza hota."
)
SLOT_SIGNAL_BAR_NOTE = (
    "Har trade ka slot us bar se liya gaya jis par SIGNAL bana (entry se ek bar "
    "pehle), entry wale bar se nahi — warna slot ka faisla us data se hota jo "
    "signal ke waqt maujood hi nahi tha."
)
_WEEKDAY_NAMES: Tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri",
                                   "sat", "sun")
_MONTH_NAMES: Tuple[str, ...] = ("jan", "feb", "mar", "apr", "may", "jun",
                                 "jul", "aug", "sep", "oct", "nov", "dec")
_STAMP_LABEL_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})$")
_DAY_LABEL_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTH_LABEL_RE = re.compile(r"^(\d{4})-(\d{2})$")
_QUARTER_LABEL_RE = re.compile(r"^(\d{4})-Q([1-4])$")

# ── #150i-b: REGIME — har entry se PEHLE, sirf pichhle bar se ─────────────────
# Contract ka point: "har scalp se pehle regime pehchana gaya". Iska saboot ek
# hi cheez ho sakti hai — har trade par label maujood ho, aur wo label SIRF us
# data se bana ho jo signal ke waqt maujood tha. Isliye `regime_at()` sirf
# `history` leta hai; usko poori series kabhi nahi di jaati. Do axis:
#   trend  → per-bar drift, pichhli aausat harkat ke paimane par (trend/range)
#   vol    → haal ki harkat vs lambe window ki harkat (high/mid/low)
# Dono axis relative hain (kisi fixed rupee/point number par nahi), isliye
# instrument badalne par bhi paimana toota nahi.
REGIME_TREND_LOOKBACK = 6    # trend naapne ka window (bar)
REGIME_VOL_LOOKBACK = 4      # "haal ki harkat" ka window (bar)
REGIME_TREND_UNITS = 0.5     # per-bar drift itne x aausat harkat = trend
REGIME_VOL_HIGH = 1.25       # haal/lamba ratio isse ooper = high vol
REGIME_VOL_LOW = 0.8         # isse neeche = low vol
REGIME_MIN_TRADES = 3        # itne se kam trade wale regime ka number bahar nahi
REGIME_MIN_REGIMES = 2       # ek hi regime par "regime maayne rakhta hai" jhooth
REGIME_DIFF_R = 0.25
REGIME_R_MULTIPLE = 2.0      # tulna ek hi R par (warna farak R ke chunav ka hai)
REGIME_TREND_UP = "trend_up"
REGIME_TREND_DOWN = "trend_down"
REGIME_RANGE = "range"
REGIME_VOL_HIGH_NAME = "high_vol"
REGIME_VOL_MID_NAME = "mid_vol"
REGIME_VOL_LOW_NAME = "low_vol"
NO_REGIME_HISTORY = "not_enough_past_bars_to_label_a_regime"
FEW_REGIMES = "too_few_regimes_with_enough_trades"
REGIME_NO_DIFFERENCE = "regime_expectancy_difference_too_small"
REGIME_UNLABELLED = "some_trades_had_no_regime_label_before_entry"
REGIME_PAST_ONLY_NOTE = (
    "Regime ka label sirf SIGNAL ke waqt maujood bar se bana hai (entry wale "
    "bar ya aage ke bar se nahi) — isliye isme future ka koi hissa nahi hai."
)
REGIME_RELATIVE_NOTE = (
    "Trend aur volatility dono RELATIVE naapi gayi hain (pichhli aausat harkat "
    "ke paimane par), kisi fixed point/rupee number par nahi — isliye ye paimana "
    "instrument badalne par bhi wahi rehta hai."
)

# ── #150i-c: MACRO EVENT WINDOW (pre-news, release, 1-5M, 5-15M, 15-60M) ──────
# Contract maangta hai: har window ke liye trade / wait / avoid me se EK saaf
# faisla. Do mode hain, aur dono ki hadd likhi hui hai:
#
#   calendar mode  — asli event date/time evidence me likhi mili (FOMC, CPI, NFP
#                    jaisi). Sirf IS mode me "pre-news" window naapi ja sakti
#                    hai, kyunki event ka waqt pehle se pata tha.
#   shock proxy    — koi calendar nahi mili to bade move ko event ka nishaan
#                    maana gaya (threshold sirf PICHHLE bar se). Is mode me
#                    "pre-news" ka faisla NAHI hota (`pre_event = None`), kyunki
#                    shock ka pata tab chalta hai jab wo bar chhap chuka hota —
#                    usse pehle ki window banana leakage hoti.
#
# Minute wali window sirf intraday stamp par ban sakti hai. Daily/monthly data
# par "1-5M" jaisi window banana banaawat hai, isliye wahan naap ruk jaati hai.
EVENT_MODE_CALENDAR = "calendar"
EVENT_MODE_SHOCK = "shock_proxy"
EVENT_SHOCK_UNITS = 2.5      # bar ka move itne x pichhli aausat harkat = shock
EVENT_WARMUP_BARS = 8        # itne bar ke baad hi threshold banta hai
EVENT_MIN_TRADES = 3         # itne se kam trade wali window ka number bahar nahi
EVENT_MIN_WINDOWS = 2
EVENT_PRE_MINUTES = 60       # release se itne minute pehle = pre-event window
EVENT_PRE = "pre_event"
EVENT_RELEASE = "release_bar"
EVENT_EARLY = "post_1_5m"
EVENT_MID = "post_5_15m"
EVENT_LATE = "post_15_60m"
EVENT_QUIET = "no_event_nearby"
EVENT_WINDOW_ORDER: Tuple[str, ...] = (EVENT_PRE, EVENT_RELEASE, EVENT_EARLY,
                                       EVENT_MID, EVENT_LATE, EVENT_QUIET)
EVENT_TRADE = "trade"
EVENT_WAIT = "wait"
EVENT_AVOID = "avoid"
EVENT_TRADE_MIN_R = 0.10     # isse ooper expectancy = trade
EVENT_AVOID_MAX_R = -0.10    # isse neeche = avoid; beech me = wait
EVENT_NEEDS_INTRADAY = "minute_windows_need_intraday_stamps"
NO_EVENTS = "no_event_marker_found_in_data_or_evidence"
FEW_EVENT_WINDOWS = "too_few_event_windows_with_enough_trades"
PRE_EVENT_NEEDS_CALENDAR = "pre_event_window_needs_a_real_event_calendar"
EVENT_STEP_UNKNOWN = "bar_step_in_minutes_could_not_be_read"
# Sab window ka faisla ek hi nikla — yaani khabar ki khidki se bartaav me koi
# NAAPA HUA farak nahi aaya. Ye "naap nahi hui" NAHI hai; ye ek asli negative
# nateeja hai, aur isko chhupana hi "news window par edge hai" wala jhooth hai.
EVENT_NO_DIFFERENCE = "event_window_verdicts_were_all_the_same"
EVENT_SHOCK_NOTE = (
    "Koi asli event calendar nahi mili, isliye event ki jagah SHOCK ko nishaan "
    "maana gaya (bar ka move pichhli aausat harkat se kai guna bada). Ye event "
    "ka proxy hai, event ka saboot NAHI — aur 'pre-news' ka faisla is mode me "
    "nahi hota."
)
EVENT_CALENDAR_NOTE = (
    "Event ka waqt evidence me LIKHA hua mila (naam + date/time), isliye "
    "'pre-news' window bhi naapi ja sakti hai — event ka waqt pehle se pata tha."
)
EVENT_VERDICT_NOTE = (
    "Har window ka faisla (trade / wait / avoid) uski NAAPI HUI expectancy se "
    "bana hai. Jis window me itne trade nahi bane, uska faisla None rehta hai — "
    "'wait' likh dena us naap ke na hone ko chhupa dena hota."
)
# Naam ki list ADDRESSING hai (kis line me event ka zikr hai), knowledge nahi —
# isse koi nateeja nahi nikalta, sirf date padhne ki jagah tay hoti hai.
EVENT_DATE_WITHOUT_TIME = "event_date_had_no_time_so_minute_windows_unmeasurable"
EVENT_OUTSIDE_SERIES = "event_time_outside_the_series_range"
_EVENT_NAME_RE = re.compile(
    r"\b(fomc|cpi|nfp|non[- ]?farm|ppi|pce|gdp\s+release|rate\s+decision|"
    r"fed\s+funds|payrolls?|unemployment\s+rate|ecb\s+decision|boj\s+decision|"
    r"press\s+conference|inflation\s+report|jobs\s+report)\b", re.IGNORECASE)


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile. Koi interpolation nahi — kram hi kaafi hai."""
    if not sorted_values:
        return 0.0
    index = int(round(q * (len(sorted_values) - 1)))
    return float(sorted_values[max(0, min(len(sorted_values) - 1, index))])


def mc_paths(steps: Sequence[float],
             block_lengths: Sequence[int] = MC_BLOCK_LENGTHS,
             max_paths: int = MC_MAX_PATHS) -> List[Tuple[float, ...]]:
    """Deterministic block-resample: (block, start) ka har joda + ulta kram.

    Block stride `block + 1` hai, isliye path me kuch step do baar aa sakta hai
    aur kuch chhoot sakta hai — bootstrap wahi karta hai (replacement ke saath),
    bas yahan chunav random nahi, likha hua hai.
    """
    base = [float(step) for step in steps or ()]
    n = len(base)
    if n < 2:
        return [tuple(base)] if base else []
    out: List[Tuple[float, ...]] = []
    seen = set()
    for raw in block_lengths:
        block = max(1, min(int(raw), n))
        for start in range(n):
            order: List[float] = []
            index = start
            while len(order) < n:
                order.extend(base[(index + k) % n] for k in range(block))
                index = (index + block + 1) % n
            path = tuple(order[:n])
            for candidate in (path, tuple(reversed(path))):
                if candidate in seen:
                    continue
                seen.add(candidate)
                out.append(candidate)
                if len(out) >= max_paths:
                    return out
    return out


@dataclass
class PathMetrics:
    """Ek path ka nateeja. `ruined` = equity kabhi ruin level tak gir gayi."""
    ending_equity: float = 1.0
    max_drawdown: float = 0.0
    worst_streak: int = 0
    ruined: bool = False


def path_metrics(path: Sequence[float], unit: float, risk: float,
                 ruin_level: float = MC_RUIN_LEVEL) -> PathMetrics:
    """Ek path par equity chala kar drawdown/streak/ruin naapo.

    `unit` = ek "R" kitna bada hai (steps ki average absolute chaal). Risk ka
    matlab: har step par equity ka `risk` hissa ek R par laga hai.
    """
    equity = peak = 1.0
    max_dd = 0.0
    streak = worst = 0
    ruined = False
    for step in path:
        equity = max(0.0, equity * (1.0 + risk * (float(step) / unit)))
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
        if float(step) < 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
        if equity <= ruin_level:
            ruined = True
    return PathMetrics(ending_equity=equity, max_drawdown=max_dd,
                       worst_streak=worst, ruined=ruined)


@dataclass
class MonteCarlo:
    """Deterministic resampling ka nateeja. `ok=False` = chala hi nahi."""
    ok: bool = False
    reason_code: str = ""
    n_steps: int = 0
    n_paths: int = 0
    unit: float = 0.0
    rows: Tuple[Dict[str, Any], ...] = ()
    risk_fraction: Optional[float] = None
    # Top-level p95/ruin/median kis risk level ke hain. Ye field JAAN-BOOJH KAR
    # alag hai: koi bhi level chhat ke andar na bache to `risk_fraction` None
    # rehta hai par numbers phir bhi kisi ke hote hain (sabse chhote risk ke) —
    # unhe "chune hue risk ke numbers" samajh lena hi jhooth ban jaata.
    reported_risk: Optional[float] = None
    p95_drawdown: Optional[float] = None
    ruin_prob: Optional[float] = None
    median_end: Optional[float] = None
    worst_streak: int = 0

    @property
    def survived(self) -> bool:
        """Koi risk level in chhaton ke andar bacha ya nahi."""
        return self.ok and self.risk_fraction is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "reason_code": self.reason_code,
            "n_steps": self.n_steps,
            "n_paths": self.n_paths,
            "ladder": [dict(row) for row in self.rows],
            "risk_per_trade": self.risk_fraction,
            "numbers_belong_to_risk": self.reported_risk,
            "p95_drawdown": self.p95_drawdown,
            "ruin_probability": self.ruin_prob,
            "median_ending_equity": self.median_end,
            "worst_losing_streak": self.worst_streak,
            "randomness_used": False,
            "method": ("deterministic block-resample (rotation + ulta kram), "
                       "koi random draw nahi"),
            "past_data_only": BACKTEST_NOTE,
            "not_financial_advice": NOT_ADVICE_NOTE,
            "is_established_fact": False,
        }


def monte_carlo(steps: Sequence[float],
                risk_ladder: Sequence[float] = MC_RISK_LADDER,
                min_steps: int = MC_MIN_STEPS,
                min_paths: int = MC_MIN_PATHS,
                max_p95_drawdown: float = MC_MAX_P95_DRAWDOWN,
                max_ruin_prob: float = MC_MAX_RUIN_PROB) -> MonteCarlo:
    """Held-out ke steps par deterministic resampling — aur usse risk-per-trade.

    Kya naapa jaata hai: p95 drawdown, ruin ki probability, median ending
    equity, aur sabse lamba losing streak. Risk-per-trade WAHI chuna jaata hai
    jo in chhaton ke andar sabse bada bacha ho. Koi risk level na bache to
    `risk_fraction` None rehta hai — "chalo 1% le lo" jaisa andaaza nahi.
    """
    rows_in = [float(step) for step in steps or ()]
    if len(rows_in) < max(4, int(min_steps)):
        return MonteCarlo(reason_code=FEW_STEPS, n_steps=len(rows_in))
    unit = sum(abs(step) for step in rows_in) / len(rows_in)
    if unit <= 0:
        return MonteCarlo(reason_code=NO_STEP_MOVED, n_steps=len(rows_in))
    paths = mc_paths(rows_in)
    if len(paths) < max(2, int(min_paths)):
        return MonteCarlo(reason_code=FEW_PATHS, n_steps=len(rows_in),
                          n_paths=len(paths), unit=unit)
    rows: List[Dict[str, Any]] = []
    for risk in risk_ladder:
        metrics = [path_metrics(path, unit, float(risk)) for path in paths]
        drawdowns = sorted(m.max_drawdown for m in metrics)
        endings = sorted(m.ending_equity for m in metrics)
        ruin_prob = sum(1 for m in metrics if m.ruined) / len(metrics)
        row = {
            "risk": float(risk),
            "median_drawdown": _percentile(drawdowns, 0.5),
            "p95_drawdown": _percentile(drawdowns, 0.95),
            "ruin_prob": ruin_prob,
            "median_end": _percentile(endings, 0.5),
            "p05_end": _percentile(endings, 0.05),
            "worst_streak": max((m.worst_streak for m in metrics), default=0),
        }
        row["acceptable"] = bool(row["p95_drawdown"] <= max_p95_drawdown
                                 and ruin_prob <= max_ruin_prob
                                 and row["median_end"] > 1.0)
        rows.append(row)
    safe = [row for row in rows if row["acceptable"]]
    best = max(safe, key=lambda row: row["risk"]) if safe else None
    return MonteCarlo(
        ok=True, reason_code=("" if best else NO_SAFE_RISK),
        n_steps=len(rows_in), n_paths=len(paths), unit=unit,
        rows=tuple(rows),
        risk_fraction=(best["risk"] if best else None),
        reported_risk=(best or rows[0])["risk"],
        p95_drawdown=(best or rows[0])["p95_drawdown"],
        ruin_prob=(best or rows[0])["ruin_prob"],
        median_end=(best or rows[0])["median_end"],
        worst_streak=max(int(row["worst_streak"]) for row in rows))


@dataclass
class Sweep:
    """Parameter sweep ka nateeja — edge region me hai ya ek magic number par."""
    ok: bool = False
    reason_code: str = ""
    rows: Tuple[Dict[str, Any], ...] = ()
    usable: int = 0
    beat: int = 0
    best_lookback: Optional[int] = None
    min_settings: int = SWEEP_MIN_SETTINGS
    min_share: float = SWEEP_MIN_BEAT_SHARE

    @property
    def share(self) -> Optional[float]:
        return None if not self.usable else self.beat / self.usable

    @property
    def region_ok(self) -> Optional[bool]:
        """None = faisla hi nahi ho sakta (itni settings chali hi nahi)."""
        if not self.ok or self.usable < max(2, int(self.min_settings)):
            return None
        return bool((self.share or 0.0) >= self.min_share)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "reason_code": self.reason_code,
            "settings": [dict(row) for row in self.rows],
            "usable_settings": self.usable,
            "settings_that_beat_naive": self.beat,
            "share": self.share,
            "region_ok": self.region_ok,
            "best_lookback": self.best_lookback,
            "past_data_only": BACKTEST_NOTE,
            "not_financial_advice": NOT_ADVICE_NOTE,
            "is_established_fact": False,
        }


def parameter_sweep(series: Optional[MarketSeries],
                    lookbacks: Sequence[int] = SWEEP_LOOKBACKS,
                    min_points: int = MIN_SERIES_POINTS,
                    min_holdout: int = MIN_HOLDOUT_POINTS,
                    train_fraction: float = TRAIN_FRACTION,
                    min_settings: int = SWEEP_MIN_SETTINGS,
                    min_share: float = SWEEP_MIN_BEAT_SHARE) -> Sweep:
    """Drift lookback badal kar dekho: edge ek region me zinda hai ya nahi.

    Split wahi rehta hai (warna do cheezein saath badal jaayengi aur pata nahi
    chalega kis wajah se nateeja badla). Jo setting chal hi nahi sakti (lookback
    train se bada) wo row me likhi jaati hai par ginti me nahi aati — chupke se
    girna hi purani galti hai.
    """
    base = walk_forward(series, min_points=min_points, min_holdout=min_holdout,
                        train_fraction=train_fraction)
    if not base.ok:
        return Sweep(reason_code=base.reason_code or NO_SERIES,
                     min_settings=min_settings, min_share=min_share)
    rows: List[Dict[str, Any]] = []
    wanted: List[Optional[int]] = [None]
    wanted.extend(int(k) for k in lookbacks)
    for lookback in wanted:
        if lookback is not None and not (2 <= lookback <= base.n_train):
            rows.append({"lookback": lookback, "ran": False,
                         "reason": "lookback_outside_train",
                         "beats_naive": None})
            continue
        outcome = (base if lookback is None else
                   walk_forward(series, min_points=min_points,
                                min_holdout=min_holdout,
                                train_fraction=train_fraction,
                                drift_lookback=lookback))
        rows.append({
            "lookback": lookback,
            "ran": bool(outcome.ok),
            "reason": ("" if outcome.ok else outcome.reason_code),
            "model_mae": round(outcome.model_mae, 6),
            "naive_mae": round(outcome.naive_mae, 6),
            "beats_naive": outcome.beats_naive,
        })
    usable = [row for row in rows if row.get("beats_naive") is not None]
    winners = [row for row in usable if row["beats_naive"]]
    best = min(winners, key=lambda row: row["model_mae"]) if winners else None
    return Sweep(ok=True,
                 reason_code=("" if len(usable) >= max(2, int(min_settings))
                              else FEW_SETTINGS),
                 rows=tuple(rows), usable=len(usable), beat=len(winners),
                 best_lookback=(None if best is None else best["lookback"]),
                 min_settings=min_settings, min_share=min_share)


# Baseline tournament — model ko HAR simple model ko haraana padega, warna
# "complex model" ka koi haq nahi. Naam wahi jo asli me chalte hain.
BASELINE_NAMES: Tuple[str, ...] = (
    "naive_last", "momentum_last_change", "mean_reversion_history",
    "moving_average_3", "linear_trend",
)
BASELINE_SCOPE_NOTE = (
    "Ye SERIES-level forecast baseline hain (naive, momentum, mean-reversion, "
    "moving average, linear trend). Intraday ORB / VWAP / order-flow strategy "
    "yahan test NAHI hui — uske liye bar-level (OHLC/tick) data chahiye, jo is "
    "run me nahi tha."
)
NO_BASELINE = "no_baseline_could_forecast"


def _baseline_forecasts(history: Sequence[float]) -> Dict[str, Optional[float]]:
    """t tak ke data se hi har baseline ka agla forecast (koi future value nahi)."""
    last = history[-1]
    out: Dict[str, Optional[float]] = {"naive_last": last}
    out["momentum_last_change"] = (last + (last - history[-2])
                                   if len(history) > 1 else None)
    out["mean_reversion_history"] = sum(history) / len(history)
    out["moving_average_3"] = (sum(history[-3:]) / 3.0
                               if len(history) >= 3 else None)
    if len(history) > 1:
        n = len(history)
        mean_x = (n - 1) / 2.0
        mean_y = sum(history) / n
        var = sum((i - mean_x) ** 2 for i in range(n))
        cov = sum((i - mean_x) * (history[i] - mean_y) for i in range(n))
        slope = (cov / var) if var else 0.0
        out["linear_trend"] = mean_y + slope * (n - mean_x)
    else:
        out["linear_trend"] = None
    return out


@dataclass
class Tournament:
    """Model vs simple baselines, sab par WAHI held-out split."""
    ok: bool = False
    reason_code: str = ""
    n_train: int = 0
    n_test: int = 0
    model_mae: float = 0.0
    rows: Tuple[Dict[str, Any], ...] = ()
    beaten: int = 0
    total: int = 0
    winner: str = ""

    @property
    def beats_all(self) -> Optional[bool]:
        if not self.ok or not self.total:
            return None
        return self.beaten == self.total

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "reason_code": self.reason_code,
            "train_points": self.n_train,
            "holdout_points": self.n_test,
            "model_mae": round(self.model_mae, 6),
            "baselines": [dict(row) for row in self.rows],
            "baselines_beaten": self.beaten,
            "baselines_compared": self.total,
            "beats_all_baselines": self.beats_all,
            "winner": self.winner,
            "scope": BASELINE_SCOPE_NOTE,
            "past_data_only": BACKTEST_NOTE,
            "not_financial_advice": NOT_ADVICE_NOTE,
            "is_established_fact": False,
        }


def baseline_tournament(series: Optional[MarketSeries],
                        min_points: int = MIN_SERIES_POINTS,
                        min_holdout: int = MIN_HOLDOUT_POINTS,
                        train_fraction: float = TRAIN_FRACTION,
                        drift_lookback: Optional[int] = None) -> Tournament:
    """Held-out MAE par model aur paanch simple baseline ka seedha muqabla.

    Model ka number `walk_forward()` se hi aata hai (do jagah do hisaab = jhooth
    ki jagah). Baseline usi expanding window par chalte hain, sirf `history` se —
    yaani sirf t ya usse pehle ka data.
    """
    outcome = walk_forward(series, min_points=min_points,
                           min_holdout=min_holdout,
                           train_fraction=train_fraction,
                           drift_lookback=drift_lookback)
    if not outcome.ok or series is None:
        return Tournament(reason_code=(outcome.reason_code or NO_SERIES))
    values = series.values()
    n_train = outcome.n_train
    errors: Dict[str, List[float]] = {name: [] for name in BASELINE_NAMES}
    usable: Dict[str, bool] = {name: True for name in BASELINE_NAMES}
    for index in range(n_train, len(values)):
        history = values[:index]
        actual = values[index]
        forecasts = _baseline_forecasts(history)
        for name in BASELINE_NAMES:
            guess = forecasts.get(name)
            if guess is None:
                usable[name] = False
                continue
            errors[name].append(abs(actual - guess))
    rows: List[Dict[str, Any]] = []
    beaten = 0
    total = 0
    for name in BASELINE_NAMES:
        points = errors[name]
        if not usable[name] or not points:
            rows.append({"baseline": name, "compared": False,
                         "reason": "baseline_could_not_forecast",
                         "mae": None, "model_better": None})
            continue
        mae = sum(points) / len(points)
        better = outcome.model_mae < mae
        total += 1
        beaten += 1 if better else 0
        rows.append({"baseline": name, "compared": True, "reason": "",
                     "mae": round(mae, 6), "model_better": better})
    if not total:
        return Tournament(reason_code=NO_BASELINE, n_train=n_train,
                          n_test=outcome.n_test, model_mae=outcome.model_mae,
                          rows=tuple(rows))
    scored = [(row["mae"], row["baseline"]) for row in rows if row["compared"]]
    best_mae, best_name = min(scored)
    winner = "model" if outcome.model_mae < best_mae else best_name
    return Tournament(ok=True, n_train=n_train, n_test=outcome.n_test,
                      model_mae=outcome.model_mae, rows=tuple(rows),
                      beaten=beaten, total=total, winner=winner)


# ── #150f: ek trade ka poora jeevan (entry → exit), sirf pichhle data se ──────
@dataclass(frozen=True)
class Trade:
    """Ek trade. `mae_r` = close par naapi gayi sabse ulti chaal (R me, >= 0)."""
    entry_index: int = 0
    direction: int = 0          # +1 long, -1 short (0 kabhi trade nahi banta)
    entry: float = 0.0
    stop_distance: float = 0.0
    exit_index: int = 0
    exit_price: float = 0.0
    exit_kind: str = ""         # "target" | "stop" | "time"
    gross_r: float = 0.0
    cost_r: float = 0.0
    net_r: float = 0.0
    mae_r: float = 0.0

    @property
    def loss_class(self) -> str:
        """Haar ki naapi hui wajah. Jeet par khaali string — kahani nahi."""
        if self.net_r >= 0:
            return ""
        if self.exit_kind == "stop":
            return LOSS_STOPPED
        if self.gross_r >= 0:
            return LOSS_COST_ONLY
        return LOSS_TIME_EXIT


def _past_move_unit(history: Sequence[float]) -> float:
    """Pichhli aausat harkat (absolute). Stop ki naap sirf ISSE banti hai."""
    if len(history) < 2:
        return 0.0
    moves = [abs(history[i] - history[i - 1]) for i in range(1, len(history))]
    return sum(moves) / float(len(moves))


def _drift_direction(history: Sequence[float],
                     lookback: Optional[int] = None) -> int:
    """+1 / -1 / 0. `walk_forward` wala hi drift — aur sirf `history` se."""
    window = list(history)
    if lookback is not None and lookback >= 2:
        window = window[-int(lookback):]
    if len(window) < 2:
        return 0
    drift = (window[-1] - window[0]) / (len(window) - 1)
    if drift > 0:
        return 1
    if drift < 0:
        return -1
    return 0

def simulate_trades(values: Sequence[float], n_train: int,
                    r_multiple: float = 2.0,
                    stop_units: float = TRADE_STOP_UNITS,
                    max_bars: int = TRADE_MAX_BARS,
                    cost_fraction: float = TRADE_COST_FRACTION,
                    lookback: Optional[int] = None) -> List[Trade]:
    """Held-out hisse par ek-ke-baad-ek (overlap bina) trade chalao.

    Har entry par model ke paas SIRF `values[:index]` hota hai — signal, stop ki
    naap aur cost teeno wahin se bante hain. Exit ke liye aage ke close padhe
    jaate hain (wo asli waqt me bhi aage hi aate hain), par entry ka faisla ho
    chukne ke BAAD. Isliye koi leakage nahi.

    Ek hi bar me SL aur TP dono paar ho jaayein — ye close-only data se tay nahi
    ho sakta. Yahan pehle STOP dekha jaata hai (bura-se-bura), kyunki apne haq
    me maan lena hi backtest ka sabse aam jhooth hai.
    """
    total = len(values)
    trades: List[Trade] = []
    index = max(1, int(n_train))
    while index < total:
        history = values[:index]
        unit = _past_move_unit(history)
        direction = _drift_direction(history, lookback)
        if unit <= 0 or direction == 0:
            index += 1
            continue
        entry = history[-1]
        stop_distance = float(stop_units) * unit
        target = float(r_multiple) * stop_distance
        worst = 0.0
        exit_index = min(index + max(1, int(max_bars)) - 1, total - 1)
        exit_kind = "time"
        exit_price = values[exit_index]
        for step in range(index, exit_index + 1):
            excursion = direction * (values[step] - entry)
            worst = min(worst, excursion)
            if excursion <= -stop_distance:
                exit_index, exit_kind, exit_price = step, "stop", values[step]
                break
            if excursion >= target:
                exit_index, exit_kind, exit_price = step, "target", values[step]
                break
        gross_r = direction * (exit_price - entry) / stop_distance
        cost_r = abs(float(cost_fraction) * entry) / stop_distance
        trades.append(Trade(entry_index=index, direction=direction, entry=entry,
                            stop_distance=stop_distance, exit_index=exit_index,
                            exit_price=exit_price, exit_kind=exit_kind,
                            gross_r=gross_r, cost_r=cost_r,
                            net_r=gross_r - cost_r,
                            mae_r=max(0.0, -worst / stop_distance)))
        index = exit_index + 1
    return trades


def _stdev(values: Sequence[float]) -> float:
    """Population stdev. 2 se kam value par 0.0 — "0 risk" nahi, "naap nahi"."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / float(len(values))
    var = sum((v - mean) ** 2 for v in values) / float(len(values))
    return var ** 0.5


def trade_stats(trades: Sequence[Trade]) -> Dict[str, Any]:
    """Trade list se naap. Jo naapa nahi ja sakta wo `None` rehta hai, 0 nahi.

    Win rate JAAN-BOOJH KAR sabse pehla naap nahi hai — expectancy hai. 90% win
    rate wala model bhi ek hi haar me sab de sakta hai, aur intel ka contract
    saaf kehta hai: win rate ke peechhe nahi bhaagna.
    """
    n = len(trades)
    if not n:
        return {"n_trades": 0, "win_rate": None, "expectancy_r": None,
                "profit_factor": None, "sharpe_r": None, "sortino_r": None,
                "avg_win_r": None, "avg_loss_r": None, "max_drawdown_r": None,
                "tail_loss_r": None, "mae_median_r": None, "mae_p95_r": None,
                "avg_cost_r": None,
                "loss_classes": {}, "exit_kinds": {}}
    nets = [t.net_r for t in trades]
    wins = [r for r in nets if r > 0]
    losses = [r for r in nets if r <= 0]
    mean = sum(nets) / float(n)
    spread = _stdev(nets)
    downside = _stdev([r for r in nets if r < mean]) if len(nets) > 1 else 0.0
    equity = 0.0
    peak = 0.0
    worst_dd = 0.0
    for r in nets:
        equity += r
        peak = max(peak, equity)
        worst_dd = max(worst_dd, peak - equity)
    maes = sorted(t.mae_r for t in trades)
    classes: Dict[str, int] = {}
    for trade in trades:
        if trade.loss_class:
            classes[trade.loss_class] = classes.get(trade.loss_class, 0) + 1
    kinds: Dict[str, int] = {}
    for trade in trades:
        kinds[trade.exit_kind] = kinds.get(trade.exit_kind, 0) + 1
    loss_sum = abs(sum(losses))
    return {
        "n_trades": n,
        "win_rate": round(len(wins) / float(n), 4),
        "expectancy_r": round(mean, 4),
        # Koi haar hi na ho to profit factor ka bhaag hi nahi banta — tab None,
        # kyunki "infinite profit factor" chhaapna hi ek jhooth hai.
        "profit_factor": (None if loss_sum <= 0
                          else round(sum(wins) / loss_sum, 4)),
        "sharpe_r": None if spread <= 0 else round(mean / spread, 4),
        "sortino_r": None if downside <= 0 else round(mean / downside, 4),
        "avg_win_r": None if not wins else round(sum(wins) / len(wins), 4),
        "avg_loss_r": None if not losses else round(sum(losses) / len(losses), 4),
        "max_drawdown_r": round(worst_dd, 4),
        "tail_loss_r": round(_percentile(sorted(nets), 0.05), 4),
        "mae_median_r": round(_percentile(maes, 0.5), 4),
        "mae_p95_r": round(_percentile(maes, 0.95), 4),
        # Cost sach me lagi ya sirf "laga di gayi" kaha gaya — ye NAAP uska
        # saboot hai. 0 aaye to matlab cost lagi hi nahi.
        "avg_cost_r": round(sum(t.cost_r for t in trades) / float(n), 6),
        "loss_classes": classes,
        "exit_kinds": kinds,
    }


@dataclass(frozen=True)
class TradeSim:
    """R-ladder ka poora nateeja. `chosen` = wo R jiski expectancy sabse acchi."""
    ok: bool = False
    reason_code: str = ""
    n_train: int = 0
    n_test: int = 0
    rows: Tuple[Dict[str, Any], ...] = ()
    chosen: Optional[float] = None
    min_trades: int = TRADE_MIN_TRADES
    min_robust_share: float = TRADE_MIN_ROBUST_SHARE

    @property
    def usable(self) -> int:
        """Wo R-setting jinme itne trade bane ki naap ka matlab ho."""
        return len([row for row in self.rows if row["measured"]])

    @property
    def positive(self) -> int:
        return len([row for row in self.rows
                    if row["measured"] and (row["expectancy_r"] or 0.0) > 0])

    @property
    def robust_share(self) -> Optional[float]:
        """Kitne hisse R-setting me edge zinda hai. 0 naap par None, 0.0 nahi."""
        if not self.usable:
            return None
        return self.positive / self.usable

    @property
    def best(self) -> Optional[Dict[str, Any]]:
        rows = [row for row in self.rows if row["measured"]]
        if not rows:
            return None
        return max(rows, key=lambda row: row["expectancy_r"])

    @property
    def edge_after_cost(self) -> Optional[bool]:
        """None = faisla hi nahi ho saka. Ye teesri haalat kabhi mit nahi sakti.

        Do alag-alag "None" hain, aur dono ka matlab ek hi hai — naap nahi hui:
        (a) koi R-setting itne trade nahi bana paayi, (b) sample me EK BHI haar
        nahi thi, isliye loss-side naapa hi nahi gaya. (b) ko "edge mil gaya"
        maan lena hi backtest ka sabse meetha jhooth hai, aur usko "expectancy
        positive nahi thi" kehna bhi jhooth hoga.
        """
        if not self.ok or not self.usable:
            return None
        best = self.best or {}
        if best.get("profit_factor") is None:
            return None
        share = self.robust_share or 0.0
        return bool((best.get("expectancy_r") or 0.0) > TRADE_MIN_EXPECTANCY_R
                    and (best.get("profit_factor") or 0.0)
                    > TRADE_MIN_PROFIT_FACTOR
                    and share >= self.min_robust_share)

    @property
    def verdict_reason(self) -> str:
        """Faisla jo bana, uski ASLI wajah — ek hi copy-paste line nahi.

        `edge_after_cost` False hone ki teen alag wajah ho sakti hain, aur user
        ko wahi wajah dikhni chahiye jo asli me lagi.
        """
        if not self.ok or not self.usable:
            return FEW_TRADES
        best = self.best or {}
        if best.get("profit_factor") is None:
            return NO_LOSS_TO_MEASURE
        if (best.get("expectancy_r") or 0.0) <= TRADE_MIN_EXPECTANCY_R:
            return NO_EDGE_AFTER_COST
        if (best.get("profit_factor") or 0.0) <= TRADE_MIN_PROFIT_FACTOR:
            return NO_EDGE_AFTER_COST
        if (self.robust_share or 0.0) < self.min_robust_share:
            return FRAGILE_EDGE
        return ""

    def to_dict(self) -> Dict[str, Any]:
        best = self.best or {}
        return {
            "ran": self.ok,
            "reason_code": self.reason_code,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "r_settings_measured": self.usable,
            "r_settings_positive": self.positive,
            "robust_share": (None if self.robust_share is None
                             else round(self.robust_share, 4)),
            "chosen_r_multiple": self.chosen,
            "edge_after_cost": self.edge_after_cost,
            # Loss-side naapa gaya ya nahi — ye alag se bahar jaata hai, warna
            # "0 haar" wala sample sabse strong dikhne lagta hai.
            "loss_side_measured": (None if not self.usable
                                   else best.get("profit_factor") is not None),
            "min_series_points_for_this_test": TRADE_MIN_SERIES_POINTS,
            "rows": list(self.rows),
            "best": dict(best),
            "close_only_limit": CLOSE_ONLY_NOTE,
            "cost_applied": TRADE_COST_NOTE,
            "past_data_only": BACKTEST_NOTE,
            "not_financial_advice": NOT_ADVICE_NOTE,
            "randomness_used": False,
            "is_established_fact": False,
        }


def trade_expectancy(series: Optional[MarketSeries],
                     r_multiples: Sequence[float] = TRADE_R_MULTIPLES,
                     min_points: int = MIN_SERIES_POINTS,
                     min_holdout: int = MIN_HOLDOUT_POINTS,
                     train_fraction: float = TRAIN_FRACTION,
                     min_trades: int = TRADE_MIN_TRADES,
                     stop_units: float = TRADE_STOP_UNITS,
                     max_bars: int = TRADE_MAX_BARS,
                     cost_fraction: float = TRADE_COST_FRACTION,
                     min_robust_share: float = TRADE_MIN_ROBUST_SHARE
                     ) -> TradeSim:
    """Har take-profit (1R…3R) par asli trade chala kar NET naap.

    Split wahi hai jo `walk_forward` ka — do jagah do split rakhne se pata nahi
    chalta kis wajah se number badla. Jo R-setting itne trade nahi bana paati ki
    naap ka matlab ho, wo row me likhi jaati hai `measured False` ke saath aur
    ginti me nahi aati (chupke se girna hi purani galti hai).

    Edge ek hi "magic" R par zinda ho to wo edge nahi, ittefaq hai — isliye
    `robust_share` bhi shart me hai.
    """
    base = walk_forward(series, min_points=min_points, min_holdout=min_holdout,
                        train_fraction=train_fraction)
    if not base.ok:
        return TradeSim(reason_code=base.reason_code or NO_SERIES,
                        min_trades=int(min_trades),
                        min_robust_share=float(min_robust_share))
    values = list(series.values()) if series is not None else []
    if _past_move_unit(values[:base.n_train]) <= 0:
        return TradeSim(reason_code=NO_VOLATILITY, n_train=base.n_train,
                        n_test=base.n_test, min_trades=int(min_trades),
                        min_robust_share=float(min_robust_share))
    rows: List[Dict[str, Any]] = []
    for r_multiple in r_multiples or ():
        trades = simulate_trades(values, base.n_train, r_multiple=r_multiple,
                                 stop_units=stop_units, max_bars=max_bars,
                                 cost_fraction=cost_fraction)
        stats = trade_stats(trades)
        enough = stats["n_trades"] >= max(2, int(min_trades))
        row: Dict[str, Any] = {"r_multiple": float(r_multiple),
                               "measured": bool(enough),
                               "reason": ("" if enough else FEW_TRADES)}
        row.update(stats)
        if not enough:
            # Naapa nahi gaya to koi number bahar nahi jaata — warna 2 trade ki
            # "expectancy" 200 trade waali jaisi hi dikhne lagti hai.
            for key in ("expectancy_r", "profit_factor", "sharpe_r",
                        "sortino_r", "win_rate"):
                row[key] = None
        rows.append(row)
    sim = TradeSim(ok=True, n_train=base.n_train, n_test=base.n_test,
                   rows=tuple(rows), min_trades=int(min_trades),
                   min_robust_share=float(min_robust_share))
    if not sim.usable:
        return TradeSim(reason_code=FEW_TRADES, n_train=base.n_train,
                        n_test=base.n_test, rows=tuple(rows),
                        min_trades=int(min_trades),
                        min_robust_share=float(min_robust_share))
    best = sim.best or {}
    chosen = best.get("r_multiple")
    return TradeSim(ok=True, reason_code=sim.verdict_reason,
                    n_train=base.n_train,
                    n_test=base.n_test, rows=tuple(rows), chosen=chosen,
                    min_trades=int(min_trades),
                    min_robust_share=float(min_robust_share))


def slot_of(period: str) -> Tuple[str, str]:
    """(granularity, slot) — sirf period ke LABEL se. Pata na chale to ("", "").

    Koi guess nahi: label me ghanta hai to ghanta, warna din hai to weekday
    (locale-free, `datetime.date.weekday()` se — machine ki bhasha badalne par
    naam nahi badalta), warna mahina/quarter. Akela saal par koi slot nahi.
    """
    text = (period or "").strip()
    match = _STAMP_LABEL_RE.match(text)
    if match:
        hour = int(match.group(4))
        if not 0 <= hour <= 23:
            return "", ""
        return SLOT_HOUR, f"h{hour:02d}"
    match = _DAY_LABEL_RE.match(text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        try:
            index = date(year, month, day).weekday()
        except ValueError:
            return "", ""
        return SLOT_WEEKDAY, _WEEKDAY_NAMES[index]
    match = _MONTH_LABEL_RE.match(text)
    if match:
        month = int(match.group(2))
        if not 1 <= month <= 12:
            return "", ""
        return SLOT_MONTH, _MONTH_NAMES[month - 1]
    match = _QUARTER_LABEL_RE.match(text)
    if match:
        return SLOT_QUARTER, f"q{int(match.group(2))}"
    return "", ""


@dataclass(frozen=True)
class SlotSplit:
    """Slot-wise expectancy ka nateeja. Har number ke saath uska sample size."""
    ok: bool = False
    reason_code: str = ""
    granularity: str = ""
    n_train: int = 0
    n_test: int = 0
    r_multiple: float = SLOT_R_MULTIPLE
    rows: Tuple[Dict[str, Any], ...] = ()
    n_trades: int = 0
    unlabelled: int = 0
    min_slot_trades: int = SLOT_MIN_TRADES
    min_slots: int = SLOT_MIN_SLOTS

    @property
    def intraday(self) -> bool:
        """Ghanta-wise naap sirf tab mumkin hai jab stamp me ghanta ho."""
        return self.granularity == SLOT_HOUR

    @property
    def measured(self) -> int:
        return len([row for row in self.rows if row["measured"]])

    @property
    def positive(self) -> int:
        return len([row for row in self.rows
                    if row["measured"] and (row["expectancy_r"] or 0.0) > 0])

    @property
    def best(self) -> Optional[Dict[str, Any]]:
        rows = [row for row in self.rows if row["measured"]]
        if not rows:
            return None
        return max(rows, key=lambda row: row["expectancy_r"])

    @property
    def worst(self) -> Optional[Dict[str, Any]]:
        rows = [row for row in self.rows if row["measured"]]
        if not rows:
            return None
        return min(rows, key=lambda row: row["expectancy_r"])

    @property
    def spread_r(self) -> Optional[float]:
        """Best - worst slot ka farak. 2 se kam naapa hua slot par None."""
        if self.measured < 2:
            return None
        best = (self.best or {}).get("expectancy_r")
        worst = (self.worst or {}).get("expectancy_r")
        if best is None or worst is None:
            return None
        return float(best) - float(worst)


    @property
    def labelled_share(self) -> Optional[float]:
        """Kitne hisse trade ko slot mila. 0 trade par None — 0.0 nahi.

        Ye number hi is baat ka saboot hai ki attribution asli me hui. 1.0 se
        kam ho to kuch trade bina slot ke reh gayi, aur ye chhupaya nahi jaata.
        """
        if not self.n_trades:
            return None
        return (self.n_trades - self.unlabelled) / float(self.n_trades)

    @property
    def slot_dependent(self) -> Optional[bool]:
        """None = faisla hi nahi ho saka (kaafi slot naape hi nahi gaye)."""
        if not self.ok or self.measured < max(1, int(self.min_slots)):
            return None
        spread = self.spread_r
        if spread is None:
            return None
        return bool(spread >= SLOT_DIFF_R)

    @property
    def verdict_reason(self) -> str:
        """Jo faisla bana, uski ASLI wajah — ek hi copy-paste line nahi."""
        if not self.ok or self.measured < max(1, int(self.min_slots)):
            return FEW_SLOTS
        if self.spread_r is None:
            return FEW_SLOTS
        if self.spread_r < SLOT_DIFF_R:
            return SLOT_NO_DIFFERENCE
        return ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ran": self.ok,
            "reason_code": self.reason_code,
            "granularity": self.granularity,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "r_multiple": self.r_multiple,
            "n_trades": self.n_trades,
            "trades_without_slot": self.unlabelled,
            "labelled_share": (None if self.labelled_share is None
                               else round(self.labelled_share, 4)),
            "slots_measured": self.measured,
            "slots_positive": self.positive,
            "min_trades_per_slot": self.min_slot_trades,
            "min_slots": self.min_slots,
            "spread_r": (None if self.spread_r is None
                         else round(self.spread_r, 4)),
            "slot_dependent": self.slot_dependent,
            "best_slot": dict(self.best or {}),
            "worst_slot": dict(self.worst or {}),
            "rows": list(self.rows),
            # Ghanta-wise ("session") naap hui ya nahi — ye alag se bahar jaata
            # hai, warna weekday-wise naap ko "session expectancy" keh dena
            # aasan jhooth ban jaata.
            "hour_of_day_measured": self.intraday,
            "hour_of_day_reason": "" if self.intraday else NO_INTRADAY_DATA,
            "session_names_not_used": SESSION_NAME_NOTE,
            "slot_taken_from": SLOT_SIGNAL_BAR_NOTE,
            "close_only_limit": CLOSE_ONLY_NOTE,
            "cost_applied": TRADE_COST_NOTE,
            "past_data_only": BACKTEST_NOTE,
            "not_financial_advice": NOT_ADVICE_NOTE,
            "randomness_used": False,
            "is_established_fact": False,
        }


def slot_expectancy(series: Optional[MarketSeries],
                    r_multiple: float = SLOT_R_MULTIPLE,
                    min_points: int = MIN_SERIES_POINTS,
                    min_holdout: int = MIN_HOLDOUT_POINTS,
                    train_fraction: float = TRAIN_FRACTION,
                    stop_units: float = TRADE_STOP_UNITS,
                    max_bars: int = TRADE_MAX_BARS,
                    cost_fraction: float = TRADE_COST_FRACTION,
                    min_slot_trades: int = SLOT_MIN_TRADES,
                    min_slots: int = SLOT_MIN_SLOTS) -> SlotSplit:
    """Har slot (ghanta / weekday / mahina / quarter) ki apni NET expectancy.

    Split wahi hai jo `walk_forward` aur `trade_expectancy` ka — teen jagah teen
    split rakhne se pata hi nahi chalta ki number kis wajah se badla.

    Jo slot itne trade nahi bana paaya ki naap ka matlab ho, wo row me likha
    jaata hai `measured False` ke saath aur uske number None rehte hain (chupke
    se girana hi purani galti hai, aur 2 trade ka "expectancy" 200 trade waale
    jaisa dikhna hi sabse aam dhokha hai).
    """
    kwargs = {"min_slot_trades": int(min_slot_trades),
              "min_slots": int(min_slots),
              "r_multiple": float(r_multiple)}
    base = walk_forward(series, min_points=min_points, min_holdout=min_holdout,
                        train_fraction=train_fraction)
    if not base.ok:
        return SlotSplit(reason_code=base.reason_code or NO_SERIES, **kwargs)
    frequency = (series.frequency or "") if series is not None else ""
    if frequency == "yearly":
        # Saal-bhar ka ek point — isme "din ka kaunsa hissa" jaisa koi sawaal
        # hi nahi banta. Yahan kuch bhi chhaapna banaawat hoti.
        return SlotSplit(reason_code=SLOT_TOO_COARSE, n_train=base.n_train,
                         n_test=base.n_test, **kwargs)
    periods = list(series.periods()) if series is not None else []
    values = list(series.values()) if series is not None else []
    granularity = ""
    for period in periods:
        found, slot = slot_of(period)
        if found and slot:
            granularity = found
            break
    if not granularity:
        return SlotSplit(reason_code=NO_SLOT_LABELS, n_train=base.n_train,
                         n_test=base.n_test, **kwargs)
    if _past_move_unit(values[:base.n_train]) <= 0:
        return SlotSplit(reason_code=NO_VOLATILITY, granularity=granularity,
                         n_train=base.n_train, n_test=base.n_test, **kwargs)
    trades = simulate_trades(values, base.n_train, r_multiple=r_multiple,
                             stop_units=stop_units, max_bars=max_bars,
                             cost_fraction=cost_fraction)
    if not trades:
        return SlotSplit(reason_code=FEW_TRADES, granularity=granularity,
                         n_train=base.n_train, n_test=base.n_test, **kwargs)
    buckets: Dict[str, List[Trade]] = {}
    unlabelled = 0
    for trade in trades:
        # SIGNAL bar = entry se ek bar pehle. `simulate_trades` entry
        # `history[-1]` par leta hai, yaani `values[entry_index - 1]` par —
        # isliye slot bhi wahi bar deta hai. Entry wale bar ka label lena
        # leakage hota: signal ke waqt wo bar dikha hi nahi tha.
        signal_index = trade.entry_index - 1
        label = periods[signal_index] if 0 <= signal_index < len(periods) else ""
        found, slot = slot_of(label)
        if found != granularity or not slot:
            unlabelled += 1
            continue
        buckets.setdefault(slot, []).append(trade)
    rows: List[Dict[str, Any]] = []
    for slot in sorted(buckets):
        group = buckets[slot]
        stats = trade_stats(group)
        enough = stats["n_trades"] >= max(2, int(min_slot_trades))
        row: Dict[str, Any] = {"slot": slot, "granularity": granularity,
                               "measured": bool(enough),
                               "reason": ("" if enough else FEW_TRADES)}
        row.update(stats)
        if not enough:
            for key in ("expectancy_r", "profit_factor", "sharpe_r",
                        "sortino_r", "win_rate"):
                row[key] = None
        rows.append(row)
    split = SlotSplit(ok=True, granularity=granularity, n_train=base.n_train,
                      n_test=base.n_test, rows=tuple(rows),
                      n_trades=len(trades), unlabelled=unlabelled, **kwargs)
    if split.measured < max(1, int(min_slots)):
        return SlotSplit(reason_code=FEW_SLOTS, granularity=granularity,
                         n_train=base.n_train, n_test=base.n_test,
                         rows=tuple(rows), n_trades=len(trades),
                         unlabelled=unlabelled, **kwargs)
    return SlotSplit(ok=True, reason_code=split.verdict_reason,
                     granularity=granularity, n_train=base.n_train,
                     n_test=base.n_test, rows=tuple(rows),
                     n_trades=len(trades), unlabelled=unlabelled, **kwargs)


def regime_at(history: Sequence[float],
              trend_lookback: int = REGIME_TREND_LOOKBACK,
              vol_lookback: int = REGIME_VOL_LOOKBACK) -> str:
    """Regime ka label — SIRF `history` se. Pata na chale to "" (khaali).

    Ye function poori series kabhi nahi leta; yahi is baat ki structural garanti
    hai ki label me future ka hissa nahi aa sakta. Do axis:
      trend → window ka per-bar drift, pichhli aausat harkat ke paimane par
      vol   → haal ki aausat harkat / poore history ki aausat harkat

    Khaali string ka matlab "koi regime nahi" nahi hai — matlab "itna pichhla
    data hi nahi tha ki regime naapa ja sake". Ye do baat alag rakhna zaroori
    hai, warna bina naap wale trade "range" me gin liye jaate.
    """
    window = [float(value) for value in history or ()]
    need = max(int(trend_lookback), int(vol_lookback)) + 1
    if len(window) < max(2, need):
        return ""
    unit = _past_move_unit(window)
    if unit <= 0:
        return ""
    trend_window = window[-(max(1, int(trend_lookback)) + 1):]
    drift = (trend_window[-1] - trend_window[0]) / float(len(trend_window) - 1)
    if abs(drift) >= REGIME_TREND_UNITS * unit:
        trend = REGIME_TREND_UP if drift > 0 else REGIME_TREND_DOWN
    else:
        trend = REGIME_RANGE
    recent = _past_move_unit(window[-(max(1, int(vol_lookback)) + 1):])
    ratio = recent / unit
    if ratio >= REGIME_VOL_HIGH:
        volatility = REGIME_VOL_HIGH_NAME
    elif ratio <= REGIME_VOL_LOW:
        volatility = REGIME_VOL_LOW_NAME
    else:
        volatility = REGIME_VOL_MID_NAME
    return f"{trend}|{volatility}"


@dataclass(frozen=True)
class RegimeSplit:
    """Regime-wise expectancy + is baat ka naap ki label ENTRY SE PEHLE bana."""
    ok: bool = False
    reason_code: str = ""
    n_train: int = 0
    n_test: int = 0
    r_multiple: float = REGIME_R_MULTIPLE
    rows: Tuple[Dict[str, Any], ...] = ()
    n_trades: int = 0
    unlabelled: int = 0
    min_regime_trades: int = REGIME_MIN_TRADES
    min_regimes: int = REGIME_MIN_REGIMES

    @property
    def measured(self) -> int:
        return len([row for row in self.rows if row["measured"]])

    @property
    def positive(self) -> int:
        return len([row for row in self.rows
                    if row["measured"] and (row["expectancy_r"] or 0.0) > 0])

    @property
    def best(self) -> Optional[Dict[str, Any]]:
        rows = [row for row in self.rows if row["measured"]]
        if not rows:
            return None
        return max(rows, key=lambda row: row["expectancy_r"])

    @property
    def worst(self) -> Optional[Dict[str, Any]]:
        rows = [row for row in self.rows if row["measured"]]
        if not rows:
            return None
        return min(rows, key=lambda row: row["expectancy_r"])

    @property
    def spread_r(self) -> Optional[float]:
        if self.measured < 2:
            return None
        best = (self.best or {}).get("expectancy_r")
        worst = (self.worst or {}).get("expectancy_r")
        if best is None or worst is None:
            return None
        return float(best) - float(worst)


    @property
    def labelled_share(self) -> Optional[float]:
        """Kitne hisse trade ko entry se PEHLE regime label mila. 0 par None."""
        if not self.n_trades:
            return None
        return (self.n_trades - self.unlabelled) / float(self.n_trades)

    @property
    def labelled_before_entry(self) -> Optional[bool]:
        """Contract ka asli sawaal: HAR scalp se pehle regime pehchana gaya?

        None = naap hi nahi hui (koi trade nahi). 1.0 se kam share par False —
        "lagbhag sab" ko "har" kehna hi wo jhooth hai jise ye point rokta hai.
        """
        share = self.labelled_share
        if share is None:
            return None
        return bool(share >= 1.0)

    @property
    def regime_dependent(self) -> Optional[bool]:
        if not self.ok or self.measured < max(1, int(self.min_regimes)):
            return None
        spread = self.spread_r
        if spread is None:
            return None
        return bool(spread >= REGIME_DIFF_R)

    @property
    def verdict_reason(self) -> str:
        if self.n_trades and self.unlabelled:
            return REGIME_UNLABELLED
        if not self.ok or self.measured < max(1, int(self.min_regimes)):
            return FEW_REGIMES
        if self.spread_r is None:
            return FEW_REGIMES
        if self.spread_r < REGIME_DIFF_R:
            return REGIME_NO_DIFFERENCE
        return ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ran": self.ok,
            "reason_code": self.reason_code,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "r_multiple": self.r_multiple,
            "n_trades": self.n_trades,
            "trades_without_regime": self.unlabelled,
            "labelled_share": (None if self.labelled_share is None
                               else round(self.labelled_share, 4)),
            "labelled_before_entry": self.labelled_before_entry,
            "regimes_measured": self.measured,
            "regimes_positive": self.positive,
            "min_trades_per_regime": self.min_regime_trades,
            "min_regimes": self.min_regimes,
            "spread_r": (None if self.spread_r is None
                         else round(self.spread_r, 4)),
            "regime_dependent": self.regime_dependent,
            "best_regime": dict(self.best or {}),
            "worst_regime": dict(self.worst or {}),
            "rows": list(self.rows),
            "label_is_past_only": REGIME_PAST_ONLY_NOTE,
            "scale_is_relative": REGIME_RELATIVE_NOTE,
            "close_only_limit": CLOSE_ONLY_NOTE,
            "cost_applied": TRADE_COST_NOTE,
            "past_data_only": BACKTEST_NOTE,
            "not_financial_advice": NOT_ADVICE_NOTE,
            "randomness_used": False,
            "is_established_fact": False,
        }


def regime_expectancy(series: Optional[MarketSeries],
                      r_multiple: float = REGIME_R_MULTIPLE,
                      min_points: int = MIN_SERIES_POINTS,
                      min_holdout: int = MIN_HOLDOUT_POINTS,
                      train_fraction: float = TRAIN_FRACTION,
                      stop_units: float = TRADE_STOP_UNITS,
                      max_bars: int = TRADE_MAX_BARS,
                      cost_fraction: float = TRADE_COST_FRACTION,
                      trend_lookback: int = REGIME_TREND_LOOKBACK,
                      vol_lookback: int = REGIME_VOL_LOOKBACK,
                      min_regime_trades: int = REGIME_MIN_TRADES,
                      min_regimes: int = REGIME_MIN_REGIMES) -> RegimeSplit:
    """Har regime (trend/range × high/mid/low vol) ki apni NET expectancy.

    Do sawaal ek saath naape jaate hain:
      1. Har trade par entry se PEHLE regime pehchana gaya ya nahi
         (`labelled_share` / `labelled_before_entry`).
      2. Regime badalne par expectancy asli me badalti hai ya nahi (`spread_r`).

    Pehla sawaal doosre se zyada zaroori hai: agar sab trade label nahi hui to
    per-regime number chhaapna hi galat hoga, isliye `verdict_reason` sabse
    pehle wahi wajah deta hai.
    """
    kwargs = {"min_regime_trades": int(min_regime_trades),
              "min_regimes": int(min_regimes), "r_multiple": float(r_multiple)}
    base = walk_forward(series, min_points=min_points, min_holdout=min_holdout,
                        train_fraction=train_fraction)
    if not base.ok:
        return RegimeSplit(reason_code=base.reason_code or NO_SERIES, **kwargs)
    values = list(series.values()) if series is not None else []
    if _past_move_unit(values[:base.n_train]) <= 0:
        return RegimeSplit(reason_code=NO_VOLATILITY, n_train=base.n_train,
                           n_test=base.n_test, **kwargs)
    trades = simulate_trades(values, base.n_train, r_multiple=r_multiple,
                             stop_units=stop_units, max_bars=max_bars,
                             cost_fraction=cost_fraction)
    if not trades:
        return RegimeSplit(reason_code=FEW_TRADES, n_train=base.n_train,
                           n_test=base.n_test, **kwargs)
    buckets: Dict[str, List[Trade]] = {}
    unlabelled = 0
    for trade in trades:
        # `values[:entry_index]` = signal ke waqt tak ka SAARA data, aur bas
        # itna hi. Entry `history[-1]` par hui thi, isliye ye slice theek us bar
        # par khatam hoti hai jis par faisla hua.
        label = regime_at(values[:trade.entry_index],
                          trend_lookback=trend_lookback,
                          vol_lookback=vol_lookback)
        if not label:
            unlabelled += 1
            continue
        buckets.setdefault(label, []).append(trade)
    rows: List[Dict[str, Any]] = []
    for label in sorted(buckets):
        group = buckets[label]
        stats = trade_stats(group)
        enough = stats["n_trades"] >= max(2, int(min_regime_trades))
        row: Dict[str, Any] = {"regime": label, "measured": bool(enough),
                               "reason": ("" if enough else FEW_TRADES)}
        row.update(stats)
        if not enough:
            for key in ("expectancy_r", "profit_factor", "sharpe_r",
                        "sortino_r", "win_rate"):
                row[key] = None
        rows.append(row)
    split = RegimeSplit(ok=True, n_train=base.n_train, n_test=base.n_test,
                        rows=tuple(rows), n_trades=len(trades),
                        unlabelled=unlabelled, **kwargs)
    if split.measured < max(1, int(min_regimes)):
        return RegimeSplit(reason_code=FEW_REGIMES, n_train=base.n_train,
                           n_test=base.n_test, rows=tuple(rows),
                           n_trades=len(trades), unlabelled=unlabelled,
                           **kwargs)
    return RegimeSplit(ok=True, reason_code=split.verdict_reason,
                       n_train=base.n_train, n_test=base.n_test,
                       rows=tuple(rows), n_trades=len(trades),
                       unlabelled=unlabelled, **kwargs)


def event_periods_from_text(text: str,
                            max_events: int = 200) -> Tuple[Dict[str, Any], ...]:
    """Evidence me LIKHI hui event date/time nikaalo (koi network, koi guess).

    Ek line me event ka naam aur uska waqt dono hon — tabhi wo event maana jaata
    hai. Sirf naam mile (waqt nahi) to wo event yahan se nahi nikalta, kyunki
    bina waqt ke minute-wali window ban hi nahi sakti.
    """
    out: List[Dict[str, Any]] = []
    seen = set()
    for raw_line in (text or "")[:MAX_TEXT_CHARS].splitlines():
        line = raw_line.strip()
        if not line:
            continue
        name_match = _EVENT_NAME_RE.search(line)
        if not name_match:
            continue
        for period_match in _PERIOD_RE.finditer(line):
            read = _read_period(period_match)
            if read is None:
                continue
            frequency, label, order = read
            if frequency not in ("intraday", "daily"):
                continue
            key = (name_match.group(1).lower(), label)
            if key in seen:
                continue
            seen.add(key)
            out.append({"event": name_match.group(1).lower(), "period": label,
                        "granularity": frequency, "order": int(order)})
            break
        if len(out) >= max(1, int(max_events)):
            break
    return tuple(out)


def _modal_step_minutes(orders: Sequence[int]) -> int:
    """Bar ka aam step (minute me). Sabse zyada dohraya gaya gap; tie par chhota.

    Intraday series me raat ka gap bada hota hai — usko step maan lena poori
    window ki naap bigaad deta, isliye gap ki GINTI dekhi jaati hai, aausat nahi.
    """
    gaps: Dict[int, int] = {}
    for index in range(1, len(orders)):
        gap = int(orders[index]) - int(orders[index - 1])
        if gap > 0:
            gaps[gap] = gaps.get(gap, 0) + 1
    if not gaps:
        return 0
    return min(gaps, key=lambda gap: (-gaps[gap], gap))


@dataclass(frozen=True)
class EventMap:
    """Har bar ka window label + ye label kis mode se bana."""
    mode: str = ""
    reason_code: str = ""
    labels: Tuple[str, ...] = ()
    step_minutes: int = 0
    n_events: int = 0
    events_without_time: int = 0
    events_outside_series: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.mode and self.labels and not self.reason_code)

    @property
    def pre_event_measurable(self) -> bool:
        """Shock proxy me pre-news naapna leakage hai — isliye sirf calendar."""
        return self.mode == EVENT_MODE_CALENDAR


def event_windows(series: Optional[MarketSeries],
                  events: Sequence[Dict[str, Any]] = (),
                  shock_units: float = EVENT_SHOCK_UNITS,
                  warmup: int = EVENT_WARMUP_BARS,
                  pre_minutes: int = EVENT_PRE_MINUTES) -> EventMap:
    """Har bar ko event-window ka label do. Sirf intraday par mumkin hai."""
    points = list(series.points) if series is not None else []
    if not points:
        return EventMap(reason_code=NO_SERIES)
    if (series.frequency or "") != "intraday":
        # "1-5M" jaisi window daily/monthly data par banaawat hoti — yahan naap
        # ruk jaati hai, aur wajah saaf likhi jaati hai.
        return EventMap(reason_code=EVENT_NEEDS_INTRADAY)
    orders = [int(point.order) for point in points]
    values = [float(point.value) for point in points]
    step = _modal_step_minutes(orders)
    if step <= 0:
        return EventMap(reason_code=EVENT_STEP_UNKNOWN)
    marks: List[int] = []
    without_time = 0
    outside = 0
    mode = EVENT_MODE_SHOCK
    if events:
        mode = EVENT_MODE_CALENDAR
        for event in events:
            if (event or {}).get("granularity") != "intraday":
                # Sirf date mili, waqt nahi — minute wali window ban hi nahi
                # sakti, isliye ye event ginti me nahi aata (chupke se "0" nahi).
                without_time += 1
                continue
            order = int((event or {}).get("order") or 0)
            hit = next((index for index, value in enumerate(orders)
                        if value >= order), None)
            if hit is None:
                outside += 1
                continue
            marks.append(hit)
    else:
        for index in range(1, len(values)):
            unit = _past_move_unit(values[:index])
            if index < max(2, int(warmup)) or unit <= 0:
                continue
            if abs(values[index] - values[index - 1]) >= float(shock_units) * unit:
                marks.append(index)
    if not marks:
        return EventMap(reason_code=NO_EVENTS, step_minutes=step,
                        events_without_time=without_time,
                        events_outside_series=outside)
    labels = [EVENT_QUIET] * len(points)
    for mark in sorted(set(marks)):
        if mode == EVENT_MODE_CALENDAR:
            # Pre-news SIRF calendar mode me. Shock mode me event ka pata usi
            # bar par chalta hai jab wo chhap chuka hota — usse pehle ki window
            # banana future ka istemaal hota.
            index = mark - 1
            while index >= 0 and orders[mark] - orders[index] <= int(pre_minutes):
                if labels[index] == EVENT_QUIET:
                    labels[index] = EVENT_PRE
                index -= 1
        labels[mark] = EVENT_RELEASE
        for index in range(mark + 1, len(points)):
            delta = orders[index] - orders[mark]
            if delta <= 5:
                window = EVENT_EARLY
            elif delta <= 15:
                window = EVENT_MID
            elif delta <= 60:
                window = EVENT_LATE
            else:
                break
            # Nazdeek ka label door ke label se ooper hai; release kabhi nahi
            # badalta (do event paas-paas hon to bhi).
            if labels[index] in (EVENT_QUIET, EVENT_PRE):
                labels[index] = window
    return EventMap(mode=mode, labels=tuple(labels), step_minutes=step,
                    n_events=len(set(marks)),
                    events_without_time=without_time,
                    events_outside_series=outside)


def _event_verdict(window: str, mode: str, stats: Dict[str, Any],
                   enough: bool) -> Optional[str]:
    """trade / wait / avoid — sirf NAAP se. Naap na ho to None, "wait" nahi.

    "wait" ek faisla hai ("naapa, edge nahi mila, ruko"), aur usko "naapa hi
    nahi" ki jagah likh dena hi is point ka sabse aasan jhooth hai.
    """
    if not enough:
        return None
    if window == EVENT_PRE and mode != EVENT_MODE_CALENDAR:
        return None
    expectancy = stats.get("expectancy_r")
    if expectancy is None:
        return None
    if float(expectancy) >= EVENT_TRADE_MIN_R:
        return EVENT_TRADE
    if float(expectancy) <= EVENT_AVOID_MAX_R:
        return EVENT_AVOID
    return EVENT_WAIT


@dataclass(frozen=True)
class EventSplit:
    """Window-wise expectancy + har window ka trade/wait/avoid faisla."""
    ok: bool = False
    reason_code: str = ""
    mode: str = ""
    step_minutes: int = 0
    n_events: int = 0
    events_without_time: int = 0
    events_outside_series: int = 0
    n_train: int = 0
    n_test: int = 0
    r_multiple: float = REGIME_R_MULTIPLE
    rows: Tuple[Dict[str, Any], ...] = ()
    n_trades: int = 0
    unlabelled: int = 0
    min_window_trades: int = EVENT_MIN_TRADES
    min_windows: int = EVENT_MIN_WINDOWS

    @property
    def measured(self) -> int:
        return len([row for row in self.rows if row["measured"]])

    @property
    def decided(self) -> int:
        return len([row for row in self.rows if row.get("verdict")])

    @property
    def verdicts(self) -> Dict[str, Optional[str]]:
        return {row["window"]: row.get("verdict") for row in self.rows}

    @property
    def pre_event_verdict(self) -> Optional[str]:
        """Shock proxy me hamesha None — aur uski wajah alag se bahar jaati hai."""
        if self.mode != EVENT_MODE_CALENDAR:
            return None
        return self.verdicts.get(EVENT_PRE)


    @property
    def labelled_share(self) -> Optional[float]:
        if not self.n_trades:
            return None
        return (self.n_trades - self.unlabelled) / float(self.n_trades)

    @property
    def window_dependent(self) -> Optional[bool]:
        """Khidki badalne par faisla asli me badla ya nahi. None = tay hi nahi.

        `slot_dependent` / `regime_dependent` ke jaisa hi sawaal, par yahan
        faasla R me nahi naapa jaata — event window ka poora matlab hi FAISLA
        hai (trade / wait / avoid). Do khidki ka faisla alag = news window
        maayne rakhti hai. Sab ek jaisa = is series par khabar se bartaav nahi
        badla, aur ye baat saaf likhi jaati hai.
        """
        if not self.ok:
            return None
        decided = [row.get("verdict") for row in self.rows if row.get("verdict")]
        if len(decided) < max(2, int(self.min_windows)):
            return None
        return len(set(decided)) > 1

    @property
    def verdict_reason(self) -> str:
        if not self.ok or self.measured < max(1, int(self.min_windows)):
            return FEW_EVENT_WINDOWS
        # `slot_dependent` / `regime_dependent` ki tarah: "tay hi nahi hua" ko
        # chup-chaap "sab theek" (khaali wajah) nahi likha jaata.
        if self.window_dependent is None:
            return FEW_EVENT_WINDOWS
        if self.window_dependent is False:
            return EVENT_NO_DIFFERENCE
        return ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ran": self.ok,
            "reason_code": self.reason_code,
            "mode": self.mode,
            "bar_step_minutes": self.step_minutes,
            "n_events": self.n_events,
            "events_without_time": self.events_without_time,
            "events_outside_series": self.events_outside_series,
            "event_date_without_time_reason": (
                "" if not self.events_without_time else EVENT_DATE_WITHOUT_TIME),
            "event_outside_series_reason": (
                "" if not self.events_outside_series else EVENT_OUTSIDE_SERIES),
            "n_train": self.n_train,
            "n_test": self.n_test,
            "r_multiple": self.r_multiple,
            "n_trades": self.n_trades,
            "trades_without_window": self.unlabelled,
            "labelled_share": (None if self.labelled_share is None
                               else round(self.labelled_share, 4)),
            "windows_measured": self.measured,
            "windows_decided": self.decided,
            "min_trades_per_window": self.min_window_trades,
            "min_windows": self.min_windows,
            "verdicts": dict(self.verdicts),
            "window_dependent": self.window_dependent,
            "pre_event_verdict": self.pre_event_verdict,
            "pre_event_reason": ("" if self.mode == EVENT_MODE_CALENDAR
                                 else PRE_EVENT_NEEDS_CALENDAR),
            "rows": list(self.rows),
            "mode_limit": (EVENT_CALENDAR_NOTE if self.mode == EVENT_MODE_CALENDAR
                           else EVENT_SHOCK_NOTE),
            "verdict_rule": EVENT_VERDICT_NOTE,
            "close_only_limit": CLOSE_ONLY_NOTE,
            "cost_applied": TRADE_COST_NOTE,
            "past_data_only": BACKTEST_NOTE,
            "not_financial_advice": NOT_ADVICE_NOTE,
            "randomness_used": False,
            "is_established_fact": False,
        }


def event_window_expectancy(series: Optional[MarketSeries],
                            events: Sequence[Dict[str, Any]] = (),
                            text: str = "",
                            r_multiple: float = REGIME_R_MULTIPLE,
                            min_points: int = MIN_SERIES_POINTS,
                            min_holdout: int = MIN_HOLDOUT_POINTS,
                            train_fraction: float = TRAIN_FRACTION,
                            stop_units: float = TRADE_STOP_UNITS,
                            max_bars: int = TRADE_MAX_BARS,
                            cost_fraction: float = TRADE_COST_FRACTION,
                            shock_units: float = EVENT_SHOCK_UNITS,
                            min_window_trades: int = EVENT_MIN_TRADES,
                            min_windows: int = EVENT_MIN_WINDOWS) -> EventSplit:
    """Macro-event window ki expectancy + har window ka saaf faisla.

    `events` na diye jaayein to `text` me likhi hui event date/time dhoondhi
    jaati hai; wo bhi na mile to shock-proxy mode chalta hai (jiska matlab
    pre-news window ka faisla NAHI hota).
    """
    kwargs = {"min_window_trades": int(min_window_trades),
              "min_windows": int(min_windows), "r_multiple": float(r_multiple)}
    calendar = tuple(events or ()) or event_periods_from_text(text or "")
    emap = event_windows(series, calendar, shock_units=shock_units)
    if not emap.ok:
        return EventSplit(reason_code=emap.reason_code or NO_EVENTS,
                          mode=emap.mode, step_minutes=emap.step_minutes,
                          events_without_time=emap.events_without_time,
                          events_outside_series=emap.events_outside_series,
                          **kwargs)
    base = walk_forward(series, min_points=min_points, min_holdout=min_holdout,
                        train_fraction=train_fraction)
    common = {"mode": emap.mode, "step_minutes": emap.step_minutes,
              "n_events": emap.n_events,
              "events_without_time": emap.events_without_time,
              "events_outside_series": emap.events_outside_series}
    if not base.ok:
        return EventSplit(reason_code=base.reason_code or NO_SERIES,
                          **common, **kwargs)
    values = list(series.values()) if series is not None else []
    if _past_move_unit(values[:base.n_train]) <= 0:
        return EventSplit(reason_code=NO_VOLATILITY, n_train=base.n_train,
                          n_test=base.n_test, **common, **kwargs)
    trades = simulate_trades(values, base.n_train, r_multiple=r_multiple,
                             stop_units=stop_units, max_bars=max_bars,
                             cost_fraction=cost_fraction)
    if not trades:
        return EventSplit(reason_code=FEW_TRADES, n_train=base.n_train,
                          n_test=base.n_test, **common, **kwargs)
    buckets: Dict[str, List[Trade]] = {}
    unlabelled = 0
    for trade in trades:
        # Window bhi SIGNAL bar se (entry se ek bar pehle) — wahi bar hai jis par
        # "abhi trade karni hai ya rukna hai" ka faisla hota hai.
        signal_index = trade.entry_index - 1
        label = (emap.labels[signal_index]
                 if 0 <= signal_index < len(emap.labels) else "")
        if not label:
            unlabelled += 1
            continue
        buckets.setdefault(label, []).append(trade)
    rows: List[Dict[str, Any]] = []
    for window in EVENT_WINDOW_ORDER:
        group = buckets.get(window)
        if not group:
            continue
        stats = trade_stats(group)
        enough = stats["n_trades"] >= max(2, int(min_window_trades))
        verdict = _event_verdict(window, emap.mode, stats, enough)
        row: Dict[str, Any] = {
            "window": window, "measured": bool(enough), "verdict": verdict,
            "reason": ("" if enough else FEW_TRADES)}
        row.update(stats)
        if not enough:
            for key in ("expectancy_r", "profit_factor", "sharpe_r",
                        "sortino_r", "win_rate"):
                row[key] = None
        # Do taale ek hi baat par: shock mode me pre-news ki row ban hi nahi
        # sakti (label hi nahi lagta), aur agar kabhi ban jaaye to uska faisla
        # phir bhi None rehta hai aur wajah likhi jaati hai.
        if window == EVENT_PRE and emap.mode != EVENT_MODE_CALENDAR:
            row["reason"] = PRE_EVENT_NEEDS_CALENDAR
        rows.append(row)
    split = EventSplit(ok=True, n_train=base.n_train, n_test=base.n_test,
                       rows=tuple(rows), n_trades=len(trades),
                       unlabelled=unlabelled, **common, **kwargs)
    if split.measured < max(1, int(min_windows)):
        return EventSplit(reason_code=FEW_EVENT_WINDOWS, n_train=base.n_train,
                          n_test=base.n_test, rows=tuple(rows),
                          n_trades=len(trades), unlabelled=unlabelled,
                          **common, **kwargs)
    return EventSplit(ok=True, reason_code=split.verdict_reason,
                      n_train=base.n_train, n_test=base.n_test,
                      rows=tuple(rows), n_trades=len(trades),
                      unlabelled=unlabelled, **common, **kwargs)


def _condense(rows: List[Tuple[str, SeriesPoint]]
              ) -> List[Tuple[str, SeriesPoint]]:
    """ISO date jinme din hamesha 01 ho, wo daily nahi — monthly/yearly hai.

    FRED monthly series ki har date "YYYY-MM-01" hoti hai. Usko "daily" kehna
    label ka jhooth hota (aur frequency report me chhapti hai).
    """
    if not rows or any(frequency != "daily" for frequency, _ in rows):
        return rows
    parts = [point.period.split("-") for _frequency, point in rows]
    if any(part[2] != "01" for part in parts):
        return rows
    yearly = all(part[1] == "01" for part in parts)
    out: List[Tuple[str, SeriesPoint]] = []
    for (_frequency, point), part in zip(rows, parts):
        year, month = int(part[0]), int(part[1])
        if yearly:
            out.append(("yearly", SeriesPoint(f"{year:04d}", year * 12,
                                              point.value, point.unit)))
        else:
            out.append(("monthly", SeriesPoint(f"{year:04d}-{month:02d}",
                                               year * 12 + month - 1,
                                               point.value, point.unit)))
    return out


def series_from_pairs(pairs: Sequence[Tuple[Any, Any]], provider: str,
                      series_id: str = "", label: str = "", unit: str = "",
                      note: str = "") -> Tuple[Optional[MarketSeries], str]:
    """(period, value) jodon se provider series. Missing value chup-chaap chhodi
    jaati hai (provider "." ya null bhejta hai), par gin kar note me likhi jaati."""
    rows: List[Tuple[str, SeriesPoint]] = []
    skipped = 0
    for raw_period, raw_value in pairs or []:
        text = str(raw_period or "").strip()
        if raw_value is None or str(raw_value).strip() in ("", ".", "NA", "null",
                                                           "None", "-"):
            skipped += 1
            continue
        try:
            value = float(str(raw_value).replace(",", "").strip())
        except (TypeError, ValueError):
            skipped += 1
            continue
        match = _PERIOD_RE.match(text)
        read = _read_period(match) if match else None
        if read is None:
            skipped += 1
            continue
        rows.append((read[0], SeriesPoint(period=read[1], order=read[2],
                                          value=value, unit=unit)))
    if not rows:
        return None, NO_PERIODS
    series, reason = _build(_condense(rows), provider, "", require_uniform=False)
    if series is None:
        return None, reason
    series.series_id = series_id or series.series_id
    series.label = label or series.label
    series.unit = unit or series.unit
    parts = [note] if note else []
    if skipped:
        parts.append(f"{skipped} observation provider ne khaali bheji thi "
                     "(unhe hata diya gaya, banaya nahi gaya).")
    series.note = " ".join(parts)
    return series, ""


def parse_world_bank(payload: Any) -> Tuple[Optional[MarketSeries], str]:
    """World Bank indicator API — keyless, official. `[meta, [rows]]` shape."""
    rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else None
    if not isinstance(rows, list) or not rows:
        return None, NO_PERIODS
    first = rows[0] if isinstance(rows[0], dict) else {}
    indicator = (first.get("indicator") or {}).get("value") or ""
    country = (first.get("country") or {}).get("value") or ""
    code = (first.get("indicator") or {}).get("id") or ""
    pairs = [(row.get("date"), row.get("value")) for row in rows
             if isinstance(row, dict)]
    return series_from_pairs(
        pairs, provider="world_bank_series", series_id=str(code),
        label=" — ".join(part for part in (indicator, country) if part),
        note="World Bank indicator API (official, keyless).")


def parse_fred(payload: Any) -> Tuple[Optional[MarketSeries], str]:
    """FRED (St. Louis Fed) observations. Missing value provider "." bhejta hai."""
    if not isinstance(payload, dict):
        return None, NO_PERIODS
    rows = payload.get("observations")
    if not isinstance(rows, list) or not rows:
        return None, NO_PERIODS
    pairs = [(row.get("date"), row.get("value")) for row in rows
             if isinstance(row, dict)]
    return series_from_pairs(pairs, provider="fred",
                             note="FRED (St. Louis Fed) official API.")


def parse_alpha_vantage(payload: Any) -> Tuple[Optional[MarketSeries], str]:
    """Alpha Vantage. Rate limit par ye HTTP 200 + body me "Note" bhejta hai.

    Usko "0 data mila" kehna wahi purana jhooth hai jo `connectors/base.py` ke
    sabak #2 me pakda gaya tha — search hui hi nahi thi. Isliye alag reason code.
    """
    if not isinstance(payload, dict):
        return None, NO_PERIODS
    for key in ("Note", "Information", "Error Message"):
        if str(payload.get(key) or "").strip():
            return None, PROVIDER_THROTTLED
    block = None
    for key, value in payload.items():
        if str(key).lower().startswith("time series") and isinstance(value, dict):
            block = value
            break
    if not isinstance(block, dict) or not block:
        return None, NO_PERIODS
    pairs: List[Tuple[Any, Any]] = []
    for date, fields in block.items():
        if not isinstance(fields, dict):
            continue
        close = ""
        for field_name, field_value in fields.items():
            if "close" in str(field_name).lower():
                close = field_value
                break
        pairs.append((date, close))
    return series_from_pairs(sorted(pairs), provider="alpha_vantage",
                             note="Alpha Vantage official API (free key).")


def parse_ecb_sdmx(payload: Any) -> Tuple[Optional[MarketSeries], str]:
    """ECB Data Portal SDMX-JSON — keyless, official.

    Period ke labels `structure.dimensions.observation[0].values` me hain aur
    values `dataSets[0].series[...].observations` me index se judi hoti hain.
    """
    if not isinstance(payload, dict):
        return None, NO_PERIODS
    try:
        observation_dims = payload["structure"]["dimensions"]["observation"]
        labels = [str(value.get("id") or "")
                  for value in observation_dims[0]["values"]]
        series_map = payload["dataSets"][0]["series"]
    except (KeyError, IndexError, TypeError):
        return None, NO_PERIODS
    if not labels or not isinstance(series_map, dict) or not series_map:
        return None, NO_PERIODS
    key = sorted(series_map)[0]
    observations = (series_map.get(key) or {}).get("observations") or {}
    pairs: List[Tuple[Any, Any]] = []
    for index_text, cell in observations.items():
        try:
            index = int(index_text)
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= len(labels):
            continue
        value = cell[0] if isinstance(cell, (list, tuple)) and cell else None
        pairs.append((labels[index], value))
    return series_from_pairs(sorted(pairs), provider="ecb_series",
                             series_id=str(key),
                             note="ECB Data Portal (official, keyless).")


# ── routing: kab market data lane kholni hai ─────────────────────────────────
# Ye vocabulary SIRF ROUTING ke liye hai — "kaunsi API call karni hai". Ye
# faisla nahi karti ki jawab kya hoga, kaunsa lens lagega, ya kaunsa source
# relevant hai (wo `domain.py` / `lenses.py` ka kaam hai, aur wo list par nahi
# tikta). Isliye yahan chhoti, saaf list rakhna theek hai.
_MARKET_RE = re.compile(
    r"\bstock(?:s|\s+market)?\b|\bshare\s+price\b|\bnifty\b|\bsensex\b|"
    r"\bnasdaq\b|\bs&p\b|\bdow\b|\bindex\b|\bequit(?:y|ies)\b|\bbond\b|"
    r"\byield\b|\binterest\s+rate\b|\brepo\s+rate\b|\bexchange\s+rate\b|"
    r"\bforex\b|\bcurrency\b|\brupee\b|\bdollar\b|\beuro\b|\bcrypto\b|"
    r"\bbitcoin\b|\bcommodity\b|\bgold\b|\bcrude\b|\boil\s+price\b|"
    r"\binflation\b|\bcpi\b|\bwpi\b|\bgdp\b|\bunemployment\b|\bgrowth\s+rate\b|"
    r"\btrading\b|\btrader\b|\bportfolio\b|\breturns?\b|\bbacktest\b|"
    r"\bbazaar\b|\bshare\s+bazar\b|\bnivesh\b|\bmehngai\b|\bbyaaj\s+dar\b",
    re.IGNORECASE)
# Ticker/symbol ke naam (#150d) — "US100", "XAUUSD", "NAS100" me na "stock"
# aata hai na "index", isliye purani list inhe pehchanti hi nahi thi aur trading
# model ki farmaish par series lane band reh jaati thi. Ye list `trademodel` se
# import NAHI hoti (wo module isi file se import karta hai — ulta import cycle
# ban jaata). Yahan bhi wahi ehtiyaat: sirf saaf ticker, "gold"/"es"/"nq" jaise
# do-matlab wale shabd nahi (unme se kuch pehle se `_MARKET_RE` me hain).
_TICKER_RE = re.compile(
    r"\bus\s?100\b|\busa100\b|\bnas\s?100\b|\bnasdaq[\s-]?100\b|\bustec\b|"
    r"\btech100\b|\bxau\s?/?\s?usd\b|\bus\s?500\b|\bspx\s?500?\b|"
    r"\bs&p\s?500\b|\bsp500\b|\bus\s?30\b|\bdow\s?30\b|\beur\s?/?\s?usd\b|"
    r"\bgbp\s?/?\s?usd\b|\busd\s?/?\s?jpy\b|\bbtc\s?/?\s?usd\b|\busoil\b|"
    r"\bbank\s?nifty\b|\bnifty\s?50\b",
    re.IGNORECASE)
# Sawaal me "waqt ke saath number" ki maang — iske bina market shabd sirf
# topic hai, series ki zaroorat nahi.
_SERIES_ASK_RE = re.compile(
    r"\bforecast\b|\bpredict\w*\b|\bproject(?:ion|ed)\b|\bbacktest\w*\b|"
    r"\bwalk[-\s]?forward\b|\btime[-\s]?series\b|\btrend\b|\bhistorical\b|"
    r"\bhistory\b|\bmonthly\b|\bquarterly\b|\byearly\b|\bannual\b|"
    r"\bover\s+(?:the\s+)?(?:last|past|next)\b|\bnext\s+"
    r"(?:year|month|quarter|week|day)\b|\bdata\b|\bseries\b|\bchart\b|"
    r"\bagle\s+(?:saal|mahine|hafte|din)\b|\bpichhle\s+\w+\b|\baankde\b|"
    r"\bkitna\s+(?:tha|hoga|badha|ghata)\b|\btrend\s+kya\b",
    re.IGNORECASE)


def market_intent(question: str, domain_key: str = "",
                  trade_ask: bool = False) -> Dict[str, Any]:
    """Market/economic series lane khulegi ya nahi — aur KYUN (dono likhte hain).

    Do signal chahiye, ek nahi: (a) market/economic cheez ka naam, aur (b) waqt
    ke saath number ki maang. Sirf "price" likha hona kaafi nahi — warna har
    aam sawaal par ye API call jaati aur budget yahin kharch ho jaata.

    `trade_ask` (#150d) doosre signal ki JAGAH le sakta hai, aur ye chhoot ek
    naapi hui wajah se hai: trading model banane ki farmaish me user "historical
    data" shabd nahi likhta, par bina purane number ke us model ko naapa hi nahi
    ja sakta. Ye faisla yahan khud nahi hota — caller (planner) `trademodel.
    is_request()` se poochh kar bhejta hai, taaki do jagah do list na banein.
    """
    text = str(question or "")
    market = bool(_MARKET_RE.search(text)) or bool(_TICKER_RE.search(text))
    ask = bool(_SERIES_ASK_RE.search(text))
    model = bool(trade_ask)
    econ = str(domain_key or "").strip().lower() in ("economics", "finance")
    wanted = bool(((market or econ) and model) or (market and ask)
                  or (econ and ask))
    if wanted:
        if market and ask:
            which = ("sawaal me market/economic cheez ka naam bhi hai aur waqt ke "
                     "saath number ki maang bhi")
        elif econ and ask:
            which = ("field economics/finance nikla aur sawaal waqt ke saath "
                     "number maang raha hai")
        else:
            which = ("trading model banane ki farmaish hai — model purane number "
                     "par hi naapa jaata hai, isliye series maangi gayi (ye "
                     "financial advice nahi hai)")
        reason = f"market data lane chali — {which}"
    elif market and not ask:
        reason = ("market/economic shabd hai par waqt ke saath number ki maang "
                  "nahi — series lane nahi kholi (bina zaroorat API call nahi)")
    elif ask and not market and not econ:
        reason = ("waqt ke saath number ki baat hai par koi market/economic "
                  "cheez ka naam nahi — series lane nahi kholi")
    else:
        reason = "sawaal me market/economic series ka koi ishara nahi mila"
    return {"wanted": wanted, "reason": reason,
            "market_signal": market, "series_ask": ask,
            "domain_economics": econ,
            # #150d — ye key alag isliye hai ki "user ne khud series maangi" aur
            # "model banane ke liye series chahiye" do alag baatein hain. Dono ko
            # ek key me mila dena wahi jhooth hota jise #133/#134 me rokha tha.
            "model_ask": model,
            "not_financial_advice": NOT_ADVICE_NOTE}
