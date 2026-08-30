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
_PERIOD_RE = re.compile(
    r"(?P<day>(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))"
    r"|(?P<month>(?:19|20)\d{2}[-/](?:0[1-9]|1[0-2])(?![-/]?\d))"
    r"|(?P<mname>(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
    r"\s+(?:19|20)\d{2})"
    r"|(?P<quarter>(?:q[1-4]\s*(?:19|20)\d{2})|(?:(?:19|20)\d{2}\s*[-]?\s*q[1-4]))"
    r"|(?P<year>(?:19|20)\d{2})",
    re.IGNORECASE)

_YEAR_ONLY_RE = re.compile(r"^(?:19|20)\d{2}$")


def _read_period(match: "re.Match[str]") -> Optional[Tuple[str, str, int]]:
    """(frequency, label, order) — order yearly/monthly ke liye mahine me."""
    text = match.group(0)
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
    # `require_uniform=False` SIRF provider series ke liye hai: wahan series ki
    # pehchaan provider ne di hai, aur beech ka ek missing observation series ko
    # jhoothi nahi banata. Text se padhi series par ye dheel kabhi nahi milti.
    if require_uniform and frequency != "daily" and len(gaps) > 1:
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
                 train_fraction: float = TRAIN_FRACTION) -> WalkForward:
    """Expanding-window walk-forward. Deterministic: koi random seed nahi.

    Har held-out step par model ke paas SIRF us se pehle ka data hota hai
    (peeche se jhaank kar "sahi" jawab nahi utha sakta). Model = drift
    (train ka average change), baseline = naive random-walk (aakhri value).
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
    for index in range(n_train, total):
        history = values[:index]
        drift = (history[-1] - history[0]) / (len(history) - 1)
        forecast = history[-1] + drift
        actual = values[index]
        model_error += abs(actual - forecast)
        naive_error += abs(actual - history[-1])
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
        holdout_first=series.points[n_train].period)


# ── provider payload → series (pure functions, isliye offline test hote hain) ─
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
