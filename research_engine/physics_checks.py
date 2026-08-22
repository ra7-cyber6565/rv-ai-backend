"""
physics_checks — point 12: "jahan sawal maange, wahan maths/physics sanity check".

Kyun banana pada
----------------
`verification.py` mein pehle se arithmetic (`check_math`), algebra
(`check_algebra`) aur statistics-presence (`check_statistical_claims`) ke check
hain. Par superconductivity jaisi quantitative research mein galti waise nahi
aati — wahan galti aati hai:

    * unit ke saath: "250 K (-23 °C)" — asli conversion -23.15 °C hai, theek;
      par "250 K (23 °C)" bilkul galat hai aur purana system ise pakad nahi paata
      tha kyunki koi `=` waala arithmetic hi nahi tha.
    * physical limit ke saath: "-15 K par superconducting" — 0 K se neeche koi
      temperature hoti hi nahi. Ya "efficiency 140%".
    * comparison ke saath: "250 K, jo 30 °C se zyada hai" — 250 K = -23 °C, yaani
      claim ulta hai.

Ye module wahi teen cheezein deterministically dekhta hai. Sab kuch local hai:
koi network, koi API, koi paid service, koi random — isliye ₹0 rule safe hai aur
do baar chalane par jawab wahi aata hai.

IMAANDAARI ki seema (jaan-boojh kar):
    * Ye physics ko "solve" nahi karta. Sirf wahi pakadta hai jo bina domain
      knowledge ke bhi galat sabit ho jaata hai (limit todna, unit conversion,
      ulti comparison).
    * Number na milne par check `None` (yaani "check nahi ho saka") deta hai —
      `False` (fail) NAHI. Missing data ko galti batana bhi jhooth hai.
    * Non-quantitative sawal par ye poora module chup rehta hai (`applicable`
      False), warna har jawab par bekaar warnings chipakne lagte.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

# ── SI (light) unit table ────────────────────────────────────────────────────
# unit token -> (dimension, SI factor). Temperature affine hai isliye alag.
_SPEED: Dict[str, float] = {"m/s": 1.0, "km/s": 1000.0, "cm/s": 0.01,
                            "km/h": 1 / 3.6, "mph": 0.44704}
_PRESSURE: Dict[str, float] = {
    "pa": 1.0, "kpa": 1e3, "mpa": 1e6, "gpa": 1e9, "tpa": 1e12,
    "bar": 1e5, "kbar": 1e8, "mbar": 1e2, "atm": 101325.0,
    "torr": 133.322, "psi": 6894.757,
}
_LENGTH: Dict[str, float] = {
    "m": 1.0, "km": 1e3, "cm": 1e-2, "mm": 1e-3, "um": 1e-6, "µm": 1e-6,
    "nm": 1e-9, "pm": 1e-12, "å": 1e-10, "angstrom": 1e-10, "angstroms": 1e-10,
}
_TIME: Dict[str, float] = {
    "s": 1.0, "sec": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9,
    "ps": 1e-12, "fs": 1e-15, "min": 60.0, "hr": 3600.0, "hour": 3600.0,
    "hours": 3600.0, "day": 86400.0, "days": 86400.0, "year": 3.15576e7,
    "years": 3.15576e7,
}
_MASS: Dict[str, float] = {"kg": 1.0, "g": 1e-3, "mg": 1e-6, "ug": 1e-9,
                           "µg": 1e-9, "tonne": 1e3}
_ENERGY: Dict[str, float] = {
    "j": 1.0, "kj": 1e3, "mj": 1e6, "ev": 1.602176634e-19,
    "mev_milli": 1.602176634e-22,           # meV — alag key, MeV se takraav na ho
    "kev": 1.602176634e-16, "gev": 1.602176634e-10,
}
_FIELD: Dict[str, float] = {"tesla": 1.0, "mt": 1e-3, "ut": 1e-6, "µt": 1e-6,
                            "gauss": 1e-4}
_TEMP_FACTOR: Dict[str, Tuple[float, float]] = {   # unit -> (factor, offset) → K
    "k": (1.0, 0.0), "kelvin": (1.0, 0.0), "mk": (1e-3, 0.0),
    "°c": (1.0, 273.15), "c": (1.0, 273.15), "celsius": (1.0, 273.15),
    "°f": (5 / 9, 255.372222222), "f": (5 / 9, 255.372222222),
    "fahrenheit": (5 / 9, 255.372222222),
}

C_LIGHT = 299792458.0            # m/s — isse zyada speed ka claim galat hai
ABS_ZERO_C = -273.15

# Regex ke liye tokens — lambe pehle, warna "mm" ko "m" kha jaayega.
_UNIT_TOKENS = [
    "km/h", "km/s", "cm/s", "m/s", "mph",
    "kelvin", "celsius", "fahrenheit", "angstroms", "angstrom",
    "tonne", "tesla", "gauss", "hours", "hour", "years", "year", "days", "day",
    "torr", "psi", "atm", "kbar", "mbar", "bar",
    "tpa", "gpa", "mpa", "kpa", "pa",
    "gev", "kev", "mev", "mev", "ev", "kj", "mj", "j",
    "°c", "°f", "mk", "k",
    "µm", "um", "nm", "pm", "mm", "cm", "km", "å",
    "µs", "us", "ms", "ns", "ps", "fs", "sec", "min", "s",
    "kg", "mg", "µg", "ug", "g",
    "mt", "µt", "ut",
    "m", "%",
]
_UNIT_RE = re.compile(
    r"(-?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*("
    + "|".join(re.escape(t) for t in _UNIT_TOKENS)
    + r")(?![a-zA-Z0-9µ°/])", re.IGNORECASE)

_SUPERCON_RE = re.compile(
    r"\bsupercond\w*|\bcritical temperature\b|\bt\s*_?c\b|\bmeissner\b|"
    r"\bzero resistance\b|\bcooper pair", re.IGNORECASE)
_EFFICIENCY_RE = re.compile(
    r"efficien\w*|yield|purity|accuracy|probabilit\w*|conversion rate|"
    r"success rate|karyakshamta", re.IGNORECASE)
_QUANT_WORDS = re.compile(
    r"\bkitn[aiey]\b|\bkitna\b|how (?:much|many|hot|cold|fast|big)\b|"
    r"\btemperature\b|\bpressure\b|\befficien\w*|\bpercent\w*|\bratio\b|"
    r"\bcalculate\b|\bcompute\b|\bcompare\b|\bspeed\b|\benergy\b|\bcost\b|"
    r"\bt\s*_?c\b|\bkelvin\b|\bgpa\b|\bthreshold\b|\blimit\b|\bhisaab\b|"
    r"\bnumber of\b|\bhow long\b", re.IGNORECASE)


@dataclass
class SanityCheck:
    name: str
    passed: Optional[bool]          # None = check nahi ho saka
    detail: str = ""

    def to_dict(self) -> Dict:
        return {"check": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class Quantity:
    value: float
    unit: str                        # jaise text mein tha
    dimension: str
    si: Optional[float]              # SI base unit mein
    raw: str
    start: int
    end: int

    def label(self) -> str:
        return f"{self.value:g} {self.unit}"


def _clean_number(text: str) -> Optional[float]:
    try:
        return float(text.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _resolve(unit_raw: str, original: str) -> Tuple[str, Optional[float], float]:
    """
    unit token -> (dimension, factor, offset).

    `original` case-sensitive token hai — sirf yahi `meV` (milli-electronvolt)
    aur `MeV` (mega-electronvolt) ka farq bata sakta hai. Ye farak 10^9 ka hai,
    isliye ise andaaze par chhodna theek nahi.
    """
    u = unit_raw.lower()
    if u in _TEMP_FACTOR:
        factor, offset = _TEMP_FACTOR[u]
        return "temperature", factor, offset
    if u == "mev":
        # 'meV' = milli-eV, 'MeV' = mega-eV. Kuch aur spelling (mev/MEV) aaye to
        # hum guess nahi karte — energy maan lete hain par mega ke saath, kyunki
        # research text mein 'MeV' zyada aam hai; farq detail mein likha jaata hai.
        if original == "meV":
            return "energy", _ENERGY["mev_milli"], 0.0
        return "energy", 1.602176634e-13, 0.0
    for table, dim in ((_PRESSURE, "pressure"), (_LENGTH, "length"),
                       (_TIME, "time"), (_MASS, "mass"), (_ENERGY, "energy"),
                       (_FIELD, "magnetic_field")):
        if u in table:
            return dim, table[u], 0.0
    if unit_raw in _SPEED or u in {k.lower() for k in _SPEED}:
        for k, v in _SPEED.items():
            if k.lower() == u:
                return "speed", v, 0.0
    if u == "%":
        return "percent", 1.0, 0.0
    return "", None, 0.0


def parse_quantities(text: str) -> List[Quantity]:
    """Text mein se (number + unit) nikaalo. Jo samajh na aaye, chhod do."""
    out: List[Quantity] = []
    source = text or ""
    for m in _UNIT_RE.finditer(source):
        raw_number = m.group(1)
        # "250-288 K" ek RANGE hai, "-288 K" nahi. Pehle ye hyphen minus sign
        # ban jaata tha aur check "-288 K absolute zero se neeche hai" bolkar
        # ek bilkul sahi jawab par physics warning laga deta tha. Isliye: minus
        # se pehle agar digit hai to wo range ka dash hai, sign nahi.
        if raw_number.startswith("-") and m.start() > 0 \
                and source[m.start() - 1].isdigit():
            raw_number = raw_number[1:]
        value = _clean_number(raw_number)
        if value is None:
            continue
        unit_raw = m.group(2)
        dim, factor, offset = _resolve(unit_raw, unit_raw)
        if not dim or factor is None:
            continue
        si = value * factor + offset if dim == "temperature" else value * factor
        out.append(Quantity(value=value, unit=unit_raw, dimension=dim, si=si,
                            raw=m.group(0), start=m.start(), end=m.end()))
    return out


def is_quantitative(question: str, answer: str = "") -> bool:
    """
    Sirf tab check chalao jab sawal/jawab mein sach mein numbers ka kaam ho.

    Warna har normal jawab ke neeche "physics check" ka bekaar section lagta
    hai — spec ka point 12 "jahan sawal demand kare" kehta hai, har jagah nahi.
    """
    q = question or ""
    if _QUANT_WORDS.search(q):
        return True
    if parse_quantities(q):
        return True
    return len(parse_quantities(answer or "")) >= 3


# ── 1. physical limits ───────────────────────────────────────────────────────
# Ye wo deewarein hain jinke paar koi bhi measurement ja hi nahi sakta. Inhe
# todne wala number ya typo hai ya hallucination — dono haalat mein user ko
# batana zaroori hai.
_NON_NEGATIVE = {"length": "lambai", "time": "samay", "mass": "vazan",
                 "pressure": "pressure (absolute)"}


def check_physical_limits(text: str) -> List[SanityCheck]:
    checks: List[SanityCheck] = []
    quantities = parse_quantities(text)
    if not quantities:
        return [SanityCheck("physical limits", None,
                            "jawab mein unit ke saath koi number nahi mila, "
                            "isliye limit check nahi ho saka")]
    low = (text or "").lower()
    bad: List[str] = []

    for q in quantities:
        if q.dimension == "temperature" and q.si is not None and q.si < 0:
            bad.append(f"{q.label()} = {q.si:.2f} K, jo absolute zero (0 K) se "
                       f"neeche hai — aisi temperature exist nahi karti")
        elif q.dimension in _NON_NEGATIVE and q.value < 0:
            bad.append(f"{q.label()} negative hai, par {_NON_NEGATIVE[q.dimension]} "
                       f"negative nahi ho sakti")
        elif q.dimension == "speed" and q.si is not None and q.si > C_LIGHT:
            bad.append(f"{q.label()} light ki speed (299,792,458 m/s) se zyada hai")
        elif q.dimension == "percent":
            window = (text or "")[max(0, q.start - 60):q.end + 40]
            if _EFFICIENCY_RE.search(window) and q.value > 100:
                bad.append(f"{q.label()} — efficiency/yield/probability 100% se "
                           f"zyada nahi ho sakti")
            elif q.value < 0:
                bad.append(f"{q.label()} — percentage negative likha gaya hai")

    if bad:
        checks.append(SanityCheck("physical limits", False,
                                  "; ".join(bad[:4])))
    else:
        checks.append(SanityCheck(
            "physical limits", True,
            f"{len(quantities)} number unit ke saath mile aur koi bhi physical "
            f"limit (absolute zero, light speed, 100% ki chhat) nahi todta"))
    # Domain-specific limit baad mein, taaki report mein pehle aam physics ki
    # baat aaye aur phir domain ki.
    if _SUPERCON_RE.search(low):
        checks.append(_superconductor_limit(quantities))
    return checks


def _superconductor_limit(quantities: List[Quantity]) -> SanityCheck:
    """
    Superconductivity wale sawal ke apne domain limits.

    Ye "physics solve" nahi hai — sirf wo range hai jiske bahar aaj tak koi
    measurement nahi hui, isliye us number ko bina flag chhodna galat hoga.
    """
    temps = [q for q in quantities if q.dimension == "temperature"
             and q.si is not None]
    press = [q for q in quantities if q.dimension == "pressure"]
    problems: List[str] = []
    for q in temps:
        if q.si is not None and q.si > 1000:
            problems.append(f"{q.label()} (= {q.si:.0f} K) — kisi bhi reported "
                            f"superconducting Tc se bahut aage (aaj tak ~250-290 K "
                            f"tak hi high-pressure claims aaye hain)")
    for q in press:
        if q.si is not None and q.si > 1e12:
            problems.append(f"{q.label()} lab mein achievable static pressure "
                            f"(~1 TPa ki theoretical chhat) se bahar hai")
        elif q.value < 0:
            problems.append(f"{q.label()} negative pressure hai — absolute "
                            f"pressure negative nahi hoti")
    if problems:
        return SanityCheck("superconductivity range", False, "; ".join(problems[:3]))
    if not temps and not press:
        return SanityCheck("superconductivity range", None,
                           "Tc ya pressure ka koi number nahi mila")
    return SanityCheck(
        "superconductivity range", True,
        f"{len(temps)} temperature aur {len(press)} pressure value known "
        f"physical range ke andar hain")


# ── 2. unit conversion ───────────────────────────────────────────────────────
# "250 K (-23 °C)" jaisi restatement. Yahi jagah hai jahan LLM sabse zyada
# chupchaap galti karta hai, kyunki dono numbers alag-alag theek lagte hain.
_SAME_MEANING_RE = re.compile(
    r"^\s*[\(\[\{]?\s*(?:=|==|≈|~|about|approx\.?|roughly|yaani|matlab|i\.e\.,?|"
    r"that is|which is|jo(?:\s+ki)?\s+hai|,)?\s*$", re.IGNORECASE)
_MORE_RE = re.compile(
    r"se\s+(?:zyada|adhik|ooncha|upar|bada)|higher than|greater than|more than|"
    r"above|over|exceeds?|beyond", re.IGNORECASE)
_LESS_RE = re.compile(
    r"se\s+(?:kam|neeche|chhota)|lower than|less than|smaller than|below|under|"
    r"fewer than", re.IGNORECASE)
# Hindi/Hinglish mein tulna ka shabd DOOSRE number ke BAAD aata hai:
# "250 K par kaam karta hai, jo 30 °C se zyada hai". Sirf gap dekhne se aisi
# ulti comparison chhoot jaati thi.
_TAIL_MORE_RE = re.compile(r"^\s*se\s+(?:zyada|adhik|ooncha|upar|bada)\b",
                           re.IGNORECASE)
_TAIL_LESS_RE = re.compile(r"^\s*se\s+(?:kam|neeche|chhota)\b", re.IGNORECASE)


def _tolerance(dimension: str, si_value: float) -> float:
    """2% relative, aur temperature mein kam se kam 0.5 K ki chhoot."""
    rel = abs(si_value) * 0.02
    if dimension == "temperature":
        return max(rel, 0.5)
    return max(rel, abs(si_value) * 0.0 + 1e-12)


def check_unit_conversions(text: str) -> List[SanityCheck]:
    quantities = parse_quantities(text)
    pairs = 0
    wrong: List[str] = []
    for a, b in zip(quantities, quantities[1:]):
        gap = (text or "")[a.end:b.start]
        if len(gap) > 24 or not _SAME_MEANING_RE.match(gap):
            continue
        if a.dimension != b.dimension or a.si is None or b.si is None:
            continue
        if a.unit.lower() == b.unit.lower() and a.value == b.value:
            continue
        pairs += 1
        if abs(a.si - b.si) > _tolerance(a.dimension, a.si):
            wrong.append(f"'{a.label()}' aur '{b.label()}' ek hi cheez ki tarah "
                         f"likhe hain, par conversion se ye {_pretty(a)} vs "
                         f"{_pretty(b)} nikalte hain")
    if not pairs:
        return [SanityCheck("unit conversion", None,
                            "ek hi value do units mein dobara nahi likhi gayi, "
                            "isliye conversion check karne ka mauka nahi mila")]
    if wrong:
        return [SanityCheck("unit conversion", False, "; ".join(wrong[:3]))]
    return [SanityCheck("unit conversion", True,
                        f"{pairs} unit conversion check hui aur sab sahi hain")]


def _pretty(q: Quantity) -> str:
    if q.si is None:
        return q.label()
    if q.dimension == "temperature":
        return f"{q.si:.2f} K"
    if q.dimension == "pressure":
        return f"{q.si / 1e9:.4g} GPa"
    return f"{q.si:.4g} (SI)"


# ── 3. comparison direction ──────────────────────────────────────────────────
def _restated_from(text: str, quantities: List[Quantity]) -> Dict[int, int]:
    """
    Kaunsa number kis number ka DOBARA-likha roop hai — aur wo restatement
    galat hai ya nahi.

    "730 days (20 years)" mein '20 years' asli quantity ('730 days') ka
    restatement hai, aur galat hai (730 din ≈ 2 saal). Aage jo tulna is '20
    years' par khadi hai, wo bhi tabhi tak sahi lagti hai jab tak galat number
    par bharosa karein. Isliye index-map banate hain: {restatement_index:
    original_index} — sirf un jodon ka jinka conversion GALAT nikla.
    """
    out: Dict[int, int] = {}
    for i in range(len(quantities) - 1):
        a, b = quantities[i], quantities[i + 1]
        gap = (text or "")[a.end:b.start]
        if len(gap) > 24 or not _SAME_MEANING_RE.match(gap):
            continue
        if a.dimension != b.dimension or a.si is None or b.si is None:
            continue
        if a.unit.lower() == b.unit.lower() and a.value == b.value:
            continue
        if abs(a.si - b.si) > _tolerance(a.dimension, a.si):
            out[i + 1] = i
    return out


def check_comparisons(text: str) -> List[SanityCheck]:
    """
    "250 K, jo 30 °C se zyada hai" — dono number theek, comparison ulta.

    Sirf same-dimension jodon par chalta hai aur sirf tab jab dono ke beech
    40 characters se kam ka comparative phrase ho — warna do alag baaton ko
    jodne ka khatra hai.

    2026-08-21 (cross-domain benchmark): ek keeda pakda gaya. "730 days (20
    years) hai, jo 5 years se zyada hai" — yahan tulna '20 years' se ho rahi
    thi, jo khud ek GALAT conversion hai (730 din ≈ 2 saal). Restated number
    par tulna sahi baithti thi, isliye check PASS bol deta tha — jabki asli
    number (730 days) 5 saal se kam hai, yaani baat ulti hai. Ab restatement
    ke peeche wale ASLI number se bhi jaancha jaata hai.
    """
    quantities = parse_quantities(text)
    restated = _restated_from(text, quantities)
    tested = 0
    wrong: List[str] = []
    for i in range(len(quantities) - 1):
        a, b = quantities[i], quantities[i + 1]
        gap = (text or "")[a.end:b.start]
        if len(gap) > 40 or a.dimension != b.dimension:
            continue
        if a.si is None or b.si is None or a.si == b.si:
            continue
        more, less = _MORE_RE.search(gap), _LESS_RE.search(gap)
        if not more and not less:
            tail = (text or "")[b.end:b.end + 30]
            more, less = _TAIL_MORE_RE.match(tail), _TAIL_LESS_RE.match(tail)
        if bool(more) == bool(less):          # dono ya koi nahi → chhod do
            continue
        tested += 1
        if more and a.si < b.si:
            wrong.append(f"likha hai '{a.label()}' > '{b.label()}', lekin "
                         f"{_pretty(a)} < {_pretty(b)} hai")
            continue
        if less and a.si > b.si:
            wrong.append(f"likha hai '{a.label()}' < '{b.label()}', lekin "
                         f"{_pretty(a)} > {_pretty(b)} hai")
            continue
        # Tulna dekhne mein sahi hai — par kya wo kisi galat restatement par
        # khadi hai? Aisa ho to asli number se dobara jaancho.
        for idx, side in ((i, "left"), (i + 1, "right")):
            src = restated.get(idx)
            if src is None:
                continue
            orig = quantities[src]
            if orig.si is None:
                continue
            left = orig.si if side == "left" else a.si
            right = orig.si if side == "right" else b.si
            if (more and left < right) or (less and left > right):
                sign = ">" if more else "<"
                wrong.append(
                    f"tulna '{a.label()}' {sign} '{b.label()}' galat "
                    f"conversion par khadi hai: asli value '{orig.label()}' "
                    f"({_pretty(orig)}) lene par baat ulti ho jaati hai")
                break
    if not tested:
        return [SanityCheck("comparison direction", None,
                            "unit ke saath koi aisi tulna nahi mili jise "
                            "conversion se jaancha ja sake")]
    if wrong:
        return [SanityCheck("comparison direction", False, "; ".join(wrong[:3]))]
    return [SanityCheck("comparison direction", True,
                        f"{tested} tulna unit conversion ke baad bhi sahi nikli")]


# ── §17: calculation records ─────────────────────────────────────────────────
# Kyun zaroori: dark-matter run mein user ne Milky Way ka mass calculation
# maanga tha. Jawab mein na formula aaya, na inputs, na units — phir bhi upar
# "numeric sanity check passed" likha tha. Yaani check chala hi nahi tha aur
# report jhooth bol rahi thi.
#
# Ye hissa jawab ke andar se calculation ka POORA record nikaalta hai (formula,
# inputs, units, assumptions, result, uncertainty) aur teen cheezein ALAG-ALAG
# batata hai: unit theek likhe hain ya nahi, dobara jodne par wahi jawab aata
# hai ya nahi, aur koi input humne khud gadha hai ya sources/question se aaya.
# Jo cheez jaanchi na ja sake wo `None` rehti hai — `False` nahi.

# Astro/extra units sirf calculation ke liye. Inhe `_UNIT_TOKENS` mein daalne se
# baaki checks ka behaviour badal jaata, isliye alag table.
_CALC_EXTRA_UNITS: Dict[str, Tuple[str, float]] = {
    "pc": ("length", 3.0856775814913673e16),
    "kpc": ("length", 3.0856775814913673e19),
    "mpc": ("length", 3.0856775814913673e22),
    "ly": ("length", 9.4607304725808e15),
    "au": ("length", 1.495978707e11),
    "r_sun": ("length", 6.957e8),
    "m_sun": ("mass", 1.98892e30),
    "msun": ("mass", 1.98892e30),
    "solar mass": ("mass", 1.98892e30),
    "solar masses": ("mass", 1.98892e30),
    "m☉": ("mass", 1.98892e30),
    "kg/m^3": ("density", 1.0),
    "gev/cm^3": ("density", 1.0),
    "g/cm^3": ("density", 1000.0),
    # Volume/area/energy/force — inke bina "V = 3.0 m^3" par recalculation
    # ruk jaata tha aur record jhoothi "unit unknown" warning deta tha.
    "m^3": ("volume", 1.0), "cm^3": ("volume", 1e-6), "mm^3": ("volume", 1e-9),
    "km^3": ("volume", 1e9), "l": ("volume", 1e-3), "litre": ("volume", 1e-3),
    "liter": ("volume", 1e-3), "ml": ("volume", 1e-6),
    "m^2": ("area", 1.0), "cm^2": ("area", 1e-4), "km^2": ("area", 1e6),
    "n": ("force", 1.0), "kn": ("force", 1e3),
    "j": ("energy", 1.0), "kj": ("energy", 1e3), "mj": ("energy", 1e6),
    "ev": ("energy", 1.602176634e-19), "kev": ("energy", 1.602176634e-16),
    "mev": ("energy", 1.602176634e-13), "gev": ("energy", 1.602176634e-10),
    "tev": ("energy", 1.602176634e-7), "erg": ("energy", 1e-7),
    "w": ("power", 1.0), "kw": ("power", 1e3), "mw": ("power", 1e6),
    "pa": ("pressure", 1.0), "kpa": ("pressure", 1e3),
    "gpa": ("pressure", 1e9), "bar": ("pressure", 1e5),
    "m^3/kg/s^2": ("gravitational", 1.0),
    "km/s/mpc": ("hubble", 1.0),
}

# Jaane-maane physical constants — inka value "invent" nahi maana jaata, kyunki
# ye kisi source se aane wali cheez hi nahi hai.
KNOWN_CONSTANTS: Dict[str, float] = {
    "g": 6.6743e-11,          # gravitational constant
    "c": 299792458.0,
    "h": 6.62607015e-34,
    "hbar": 1.054571817e-34,
    "k_b": 1.380649e-23,
    "kb": 1.380649e-23,
    "e": 1.602176634e-19,
    "m_e": 9.1093837015e-31,
    "m_p": 1.67262192369e-27,
    "n_a": 6.02214076e23,
    "sigma": 5.670374419e-8,
    "m_sun": 1.98892e30,
    "msun": 1.98892e30,
    "pi": 3.141592653589793,
}

_ASSUMPTION_RE = re.compile(
    r"\b(assum\w*|approximation|approximat\w*|maan\s?kar|maankar|maan lete|"
    r"idealis\w*|idealiz\w*|neglect\w*|ignoring)\b", re.IGNORECASE)
_UNCERTAINTY_RE = re.compile(
    r"(±\s*[\d.]+[^\n,;]*|\+/-\s*[\d.]+[^\n,;]*|uncertaint\w*[^\n]*|"
    r"error bar[^\n]*|margin of error[^\n]*|lagbhag[^\n]*|\bapprox\b[^\n]*)",
    re.IGNORECASE)
# "M = v^2 r / G" — baayein ek symbol, dayein sirf symbol/operator (numbers
# alag line mein aate hain). Yahi §17 ka "formula" hai.
_SYMBOLIC_RE = re.compile(
    r"(?<![\w])([A-Za-z][A-Za-z0-9_]{0,14}(?:\s*\([^)]{0,20}\))?)\s*=\s*"
    r"([A-Za-z0-9_^*/×·÷() .+\-]{3,80})")
# Unit ko pehle "solar masses" try karna zaroori hai, warna sirf "solar" milta
# hai aur mass conversion silently galat ho jaata hai.
_UNIT_PART = r"(?:solar[ \t]+mass(?:es)?|[A-Za-zµ°☉/^0-9_]{1,14})?"
_ASSIGN_RE = re.compile(
    r"(?<![\w])([A-Za-z][A-Za-z0-9_]{0,14})[ \t]*=[ \t]*"
    r"(-?\d[\d,]*(?:\.\d+)?(?:[ \t]*[eE×x][ \t]*10\^?-?\d+|[eE][+-]?\d+)?)"
    r"[ \t]*(" + _UNIT_PART + r")")
_RESULT_RE = re.compile(
    r"(?:result|answer|nateeja|jawab|≈|~=|=)[ \t]*"
    r"(-?\d[\d,]*(?:\.\d+)?(?:[ \t]*[eE×x][ \t]*10\^?-?\d+|[eE][+-]?\d+)?)"
    r"[ \t]*(" + _UNIT_PART + r")", re.IGNORECASE)
# "Result = 8.99e10" ko input nahi maanenge — wo nateeja hai.
_RESULT_NAMES = {"result", "results", "answer", "nateeja", "natija", "jawab",
                 "total", "final", "ans", "output", "uncertainty", "error"}
# Nateeja chunne ke liye: naam se likha hua result plain "=" se behtar hai.
_RESULT_HINTS = ("result", "answer", "nateeja", "natija", "jawab", "final",
                 "total", "output")
# Uncertainty/error waali line se nateeja NAHI uthana. Sirf match se PEHLE ka
# text dekhte hain, taaki "M = 8.99e10 ± 0.5e10" jaisa nateeja bacha rahe.
_UNCERT_PREFIX_RE = re.compile(
    r"(uncertaint|error|margin|tolerance|±|\+/-)", re.IGNORECASE)

CALC_TOLERANCE = 0.05        # 5% — rounding ("9.2e10") allowed, galti nahi


@dataclass
class CalculationRecord:
    """§17 ka structured record. Har field ka matlab report mein bhi dikhta hai."""
    formula: str = ""
    inputs: Dict[str, float] = None            # type: ignore[assignment]
    units: Dict[str, str] = None               # type: ignore[assignment]
    assumptions: List[str] = None              # type: ignore[assignment]
    result: str = ""
    uncertainty: str = ""
    unit_check_passed: Optional[bool] = None
    recalculation_passed: Optional[bool] = None
    sanity_check_passed: Optional[bool] = None
    invented_input: Optional[bool] = None
    recomputed: str = ""
    notes: List[str] = None                    # type: ignore[assignment]
    source_text: str = ""

    def __post_init__(self) -> None:
        self.inputs = dict(self.inputs or {})
        self.units = dict(self.units or {})
        self.assumptions = list(self.assumptions or [])
        self.notes = list(self.notes or [])

    @property
    def is_complete(self) -> bool:
        """Poora record = formula + inputs + units + result. Baaki honesty hai."""
        return bool(self.formula and self.inputs and self.units and self.result)

    @property
    def core_missing(self) -> List[str]:
        """Sirf wo cheezein jinke bina hisaab hi hisaab nahi kehla sakta."""
        gaps: List[str] = []
        if not self.formula:
            gaps.append("formula")
        if not self.inputs:
            gaps.append("inputs (kaunsa number kahan se)")
        if not self.units:
            gaps.append("units")
        if not self.result:
            gaps.append("result")
        return gaps

    @property
    def missing(self) -> List[str]:
        gaps = list(self.core_missing)
        if not self.assumptions:
            gaps.append("assumptions")
        if not self.uncertainty:
            gaps.append("uncertainty")
        return gaps

    def to_dict(self) -> Dict:
        return {
            "formula": self.formula,
            "inputs": dict(self.inputs),
            "units": dict(self.units),
            "assumptions": list(self.assumptions),
            "result": self.result,
            "uncertainty": self.uncertainty,
            "unit_check_passed": self.unit_check_passed,
            "recalculation_passed": self.recalculation_passed,
            "sanity_check_passed": self.sanity_check_passed,
            "invented_input": self.invented_input,
            "recomputed": self.recomputed,
            "complete": self.is_complete,
            "missing": self.missing,
            "core_missing": self.core_missing,
            "notes": list(self.notes),
        }


def _calc_si(value: float, unit: str) -> Tuple[Optional[float], bool]:
    """(SI value, unit pehchani gayi?) — pehchani na jaaye to `None`, False."""
    token = (unit or "").strip().lower().replace("−", "-")
    if not token:
        return value, False
    if token in _CALC_EXTRA_UNITS:
        return value * _CALC_EXTRA_UNITS[token][1], True
    dimension, factor, offset = _resolve(token, unit or "")
    if dimension == "unknown" or factor is None:
        return None, False
    return value * factor + offset, True


_SAFE_EXPR = re.compile(r"^[0-9eE.+\-*/() ]+$")


def _safe_eval(expr: str) -> Optional[float]:
    """
    Sirf arithmetic. Koi naam, koi function, koi builtin nahi — isliye `eval`
    yahan safe hai (pattern pehle validate hota hai, phir empty globals).
    """
    text = (expr or "").strip()
    if not text or not _SAFE_EXPR.match(text):
        return None
    try:
        value = eval(text, {"__builtins__": {}}, {})    # noqa: S307 - validated
    except (SyntaxError, ZeroDivisionError, TypeError, ValueError,
            OverflowError, MemoryError):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _to_number(raw: str) -> Optional[float]:
    """'6.6743e-11', '2.2 × 10^5', '9,200' — sabko float banao."""
    text = (raw or "").strip().replace(",", "").replace("−", "-")
    text = re.sub(r"\s*(?:[×x]\s*10\s*\^?|[eE])\s*([+-]?\d+)$", r"e\1", text)
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


_CALC_BLOCK_RE = re.compile(
    r"(?:^|\n)\s*(?:#{1,6}\s*)?[^\n]{0,80}?"
    r"(calculation|calculate|hisaab|formula|estimate|derivation)[^\n]{0,80}\n",
    re.IGNORECASE)
_FORMULA_HINT = re.compile(r"[=∝]")

# "M = v^2 * r / G se nikalta hai" — 'se nikalta hai' formula ka hissa nahi hai.
# Ye shabd aage aaye to formula wahin khatam maan lete hain, warna recalculation
# unknown symbol par ruk jaata tha aur hum galti se "check nahi ho saka" kehte.
_PROSE_WORD_RE = re.compile(
    r"^(?:use[ds]?|using|karenge|karke|karta|karti|karna|kar|hai|hain|hoga|"
    r"hogi|hota|hoti|se|ka|ki|ke|ko|jo|mein|aur|ya|from|where|with|and|then|"
    r"this|that|we|which|gives?|given|standard|relation|formula|equation|"
    r"according|apply|substitute|values?|nikalta|nikalte|nikaalte|lagakar|"
    r"hence|thus|because|yaani|matlab)$", re.IGNORECASE)


def _trim_prose(rhs: str) -> str:
    """Formula ke baad likhi hui baat kaat do (pehla prose shabd = poora stop)."""
    kept: List[str] = []
    for token in rhs.split():
        if _PROSE_WORD_RE.match(token.strip(",.;:")):
            break
        kept.append(token)
    return " ".join(kept).strip(" .,;:")


def _blocks_with_math(text: str) -> List[str]:
    """
    Jawab ko chhote blocks mein todo aur sirf wahi rakho jinme asli hisaab ho.

    Poore jawab par ek saath regex chalane se do alag calculations mil kar ek
    ban jaate the (aur inputs galat hypothesis se ja mil jaate the).
    """
    raw = (text or "").replace("\r", "")
    if not raw.strip():
        return []
    chunks: List[str] = []
    current: List[str] = []
    for line in raw.split("\n"):
        if line.strip().startswith("#") and current:
            chunks.append("\n".join(current))
            current = [line]
            continue
        current.append(line)
        # do khaali line = naya block
        if len(current) >= 3 and not current[-1].strip() and not current[-2].strip():
            chunks.append("\n".join(current))
            current = []
    if current:
        chunks.append("\n".join(current))
    return [c for c in chunks if _FORMULA_HINT.search(c) and re.search(r"\d", c)]


def _pick_formula(block: str) -> str:
    """Sabse pehla symbolic formula ('M = v^2 r / G') — number wala nahi."""
    best = ""
    for m in _SYMBOLIC_RE.finditer(block):
        lhs, rhs = m.group(1).strip(), m.group(2).strip(" .")
        if lhs.lower() in _RESULT_NAMES:
            continue                        # "Result = 8.99e10" nateeja hai
        if "\n" in rhs:
            continue                        # formula ek line mein hota hai
        rhs = _trim_prose(rhs)
        if not rhs:
            continue
        # Numeric line ko formula samajhna hi pichhli galti thi: formula mein
        # sirf chhote exponent ('v^2') aate hain, 8.99e10 jaisi value nahi.
        if re.search(r"\d[\d.,]|[eE][+-]?\d|\d\s*(?:[×x]\s*10|\^\s*\d{2})", rhs):
            continue
        letters = len(re.findall(r"[A-Za-z]", rhs))
        if letters < 1:
            continue
        if not re.search(r"[*/^×·÷+\-]|\s", rhs):
            continue                        # "x = y" ko formula nahi maanenge
        candidate = f"{lhs} = {rhs}"
        if len(candidate) > len(best):
            best = candidate
    return best[:200]


def _expr_from_formula(formula: str, inputs: Dict[str, float],
                       units: Dict[str, str]) -> Tuple[Optional[str], List[str]]:
    """
    Formula ke symbols ki jagah SI numbers rakho.

    Kaunsa symbol nahi mila — wo bhi wapas bhejte hain, taaki record mein
    "recalculation nahi ho saka: kaunsa input missing tha" likha ja sake.
    """
    rhs = formula.split("=", 1)[1] if "=" in formula else formula
    rhs = (rhs.replace("×", "*").replace("·", "*").replace("÷", "/")
              .replace("^", "**"))
    missing: List[str] = []
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]*", rhs)
    for name in sorted(set(tokens), key=len, reverse=True):
        key = name.lower()
        value: Optional[float] = None
        if name in inputs:
            value, unit = inputs[name], units.get(name, "")
            si, known = _calc_si(value, unit)
            if si is None:
                if key in KNOWN_CONSTANTS:
                    # G, c, h wagairah SI mein hi likhe jaate hain — unka
                    # compound unit table mein na hone se hisaab nahi rukega.
                    si = value
                else:
                    missing.append(f"{name} ka unit '{unit}' humari table mein nahi")
                    continue
            value = si
        elif key in KNOWN_CONSTANTS:
            value = KNOWN_CONSTANTS[key]
        else:
            missing.append(f"{name} ki value jawab mein nahi di gayi")
            continue
        rhs = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])",
                     f"({value!r})", rhs)
    # bina operator wala gap ("v**2 r" = guna) explicit karo
    rhs = re.sub(r"\)\s+\(", ")*(", rhs)
    rhs = re.sub(r"\)\s*\(", ")*(", rhs)
    if missing:
        return None, missing
    return rhs.strip(), []


def extract_calculations(answer: str, question: str = "",
                         evidence_text: str = "") -> List[CalculationRecord]:
    """
    §17 — jawab ke andar se calculation ka poora record nikaalo.

    Kuch bhi "banaya" nahi jaata: jo formula/input/unit likha hi nahi gaya, wo
    record mein missing rehta hai aur `missing` list uska naam leti hai. Isi
    tarah jo check chal na sake wo `None` rehta hai.
    """
    records: List[CalculationRecord] = []
    haystack = f"{question}\n{evidence_text}".lower()
    for block in _blocks_with_math(answer or ""):
        formula = _pick_formula(block)
        inputs: Dict[str, float] = {}
        units: Dict[str, str] = {}
        for m in _ASSIGN_RE.finditer(block):
            name = m.group(1).strip()
            value = _to_number(m.group(2))
            if value is None or name in inputs or name.lower() in _RESULT_NAMES:
                continue
            inputs[name] = value
            units[name] = (m.group(3) or "").strip()
        result = ""
        result_unit = ""
        # "Result = 8.99e10 solar masses" ke NEECHE "Uncertainty = 20 percent"
        # likha ho to pehle aakhri match uthate the aur uncertainty hi nateeja
        # ban jaata tha — phir recalculation ka milaan bekaar ho jaata. Isliye:
        # uncertainty/error waali line chhod do, aur naam se likha hua nateeja
        # (result/answer/nateeja/jawab) plain "=" se zyada bharosemand maano.
        named = None
        plain = None
        for rm in _RESULT_RE.finditer(block):
            line_start = block.rfind("\n", 0, rm.start()) + 1
            prefix = block[line_start:rm.start()]
            if _UNCERT_PREFIX_RE.search(prefix):
                continue
            context = (prefix + rm.group(0)).lower()
            if any(word in context for word in _RESULT_HINTS):
                named = rm
            else:
                plain = rm
        rm = named or plain
        if rm is not None:
            result = f"{rm.group(1).strip()} {(rm.group(2) or '').strip()}".strip()
            result_unit = (rm.group(2) or "").strip()
        assumptions = [line.strip(" -*\t")
                       for line in re.split(r"[\n;]+", block)
                       if _ASSUMPTION_RE.search(line)][:5]
        um = _UNCERTAINTY_RE.search(block)
        # Label ("Uncertainty = ") hata do, sirf value rakho — report mein
        # "Uncertainty: Uncertainty = 20 percent" padhna bekaar lagta hai.
        uncertainty = re.sub(r"^(?:uncertaint\w*|error bar|margin of error)"
                             r"[ \t]*[:=]?[ \t]*", "",
                             um.group(1).strip(), flags=re.IGNORECASE)[:200] \
            if um else ""
        if not (formula or inputs):
            continue
        rec = CalculationRecord(formula=formula, inputs=inputs, units=units,
                                assumptions=assumptions, result=result,
                                uncertainty=uncertainty, source_text=block.strip())
        if result_unit:
            rec.units["result"] = result_unit

        # ── A. unit check ────────────────────────────────────────────────────
        # Jaane-maane constants (G, c, h) SI mein hi likhe jaate hain aur unka
        # compound unit humari simple table mein nahi hota — unhe "unresolved"
        # kehna galat warning deta, isliye alag rakha hai.
        unresolved = [f"{k}='{v}'" for k, v in units.items()
                      if v and k != "result" and k.lower() not in KNOWN_CONSTANTS
                      and _calc_si(1.0, v)[0] is None]
        no_unit = [k for k, v in units.items() if not v and k != "result"
                   and k.lower() not in KNOWN_CONSTANTS]
        if not inputs:
            rec.unit_check_passed = None
            rec.notes.append("inputs hi nahi mile, isliye unit check nahi ho saka")
        elif no_unit or not result_unit:
            rec.unit_check_passed = False
            if no_unit:
                rec.notes.append("in inputs ka unit likha hi nahi: "
                                 + ", ".join(no_unit[:4]))
            if not result_unit:
                rec.notes.append("nateeje ka unit nahi likha")
        elif unresolved:
            rec.unit_check_passed = None
            rec.notes.append("ye unit humari table mein nahi, isliye conversion "
                             "jaanch nahi ho saki: " + ", ".join(unresolved[:4]))
        else:
            rec.unit_check_passed = True

        # ── B. recalculation ─────────────────────────────────────────────────
        stated = _to_number(re.split(r"[^\d.eE+×x^\-,]", result, 1)[0]
                            if result else "")
        if not formula:
            rec.recalculation_passed = None
            rec.notes.append("formula nahi likha gaya, isliye dobara jodna "
                             "possible nahi tha")
        elif stated is None:
            rec.recalculation_passed = None
            rec.notes.append("nateeja number ki tarah nahi likha, isliye "
                             "recalculation ka milaan nahi ho saka")
        else:
            expr, gaps = _expr_from_formula(formula, inputs, units)
            value = _safe_eval(expr) if expr else None
            if value is None:
                rec.recalculation_passed = None
                rec.notes.extend(gaps[:3] or ["formula ko arithmetic mein badla "
                                              "nahi ja saka"])
            else:
                # nateeja SI mein laao, tabhi tulna imaandaar hai
                target, known_unit = _calc_si(stated, result_unit)
                rec.recomputed = f"{value:.4g} (SI)"
                if target is None or not known_unit:
                    rec.recalculation_passed = None
                    rec.notes.append(f"nateeje ka unit '{result_unit}' table mein "
                                     "nahi, isliye number ka milaan nahi ho saka")
                else:
                    scale = max(abs(target), abs(value), 1e-30)
                    rec.recalculation_passed = (
                        abs(target - value) / scale <= CALC_TOLERANCE)
                    if not rec.recalculation_passed:
                        rec.notes.append(
                            f"dobara jodne par {value:.4g} aata hai, jawab mein "
                            f"{target:.4g} likha hai (SI) — farak "
                            f"{abs(target - value) / scale * 100:.1f}%")

        # ── C. sanity checks (limits + conversion) ───────────────────────────
        checks = check_physical_limits(block) + check_unit_conversions(block)
        ran = [c for c in checks if c.passed is not None]
        failed = [c for c in checks if c.passed is False]
        if failed:
            rec.sanity_check_passed = False
            rec.notes.append("sanity check fail: "
                             + "; ".join(c.detail for c in failed[:2]))
        elif ran:
            rec.sanity_check_passed = True
        else:
            rec.sanity_check_passed = None
            rec.notes.append("is block mein sanity check ke liye kaafi "
                             "number+unit nahi mile")

        # ── D. invented input? ───────────────────────────────────────────────
        if not inputs:
            rec.invented_input = None
        elif not haystack.strip():
            rec.invented_input = None
            rec.notes.append("sources ka text nahi mila, isliye ye nahi kaha ja "
                             "sakta ki inputs kahan se aaye")
        else:
            invented: List[str] = []
            hay_digits = re.sub(r"[^0-9]", "", haystack)
            for name, value in inputs.items():
                if name.lower() in KNOWN_CONSTANTS:
                    continue
                literal = f"{value:g}"
                digits = re.sub(r"[^0-9]", "", literal)
                # 3+ digit ka number sources mein dhoondhna reliable hai; ek-do
                # digit ke liye exact token match zaroori hai, warna "2" ko
                # "220" ke andar dekh kar hum galat se "source se aaya" keh dete.
                if len(digits) >= 3 and digits in hay_digits:
                    continue
                if re.search(rf"(?<![\d.]){re.escape(literal)}(?![\d])",
                             haystack):
                    continue
                invented.append(name)
            rec.invented_input = bool(invented)
            if invented:
                rec.notes.append(
                    "in inputs ki value question/sources mein nahi mili, yaani "
                    "ye model ka apna number hai: " + ", ".join(invented[:4]))
        records.append(rec)
    return records


def calculation_records(answer: str, question: str = "",
                        evidence_text: str = "") -> List[Dict]:
    """§17 — `quality_context["calculations"]` ke liye ready dict list."""
    return [r.to_dict() for r in extract_calculations(answer, question,
                                                      evidence_text)]


def _calc_ok(rec) -> bool:
    """
    Ek record "kaam ka hisaab" hai ya nahi — record ya dict, dono chalte hain.

    Sakht niyam: formula, inputs, units aur result chaaron likhe hon, aur jo
    check chala wo fail na hua ho. "Calculation section mein kuch likha tha"
    ko hisaab hona nahi maanenge — wahi pichhli galti thi.
    """
    if isinstance(rec, dict):
        complete = bool(rec.get("complete"))
        unit = rec.get("unit_check_passed")
        recalc = rec.get("recalculation_passed")
        sanity = rec.get("sanity_check_passed")
    else:
        complete = bool(getattr(rec, "is_complete", False))
        unit = getattr(rec, "unit_check_passed", None)
        recalc = getattr(rec, "recalculation_passed", None)
        sanity = getattr(rec, "sanity_check_passed", None)
    if not complete:
        return False
    return not (unit is False or recalc is False or sanity is False)


def usable_calculation_count(records: Optional[Sequence]) -> Optional[int]:
    """
    Ledger ke liye ginti: kitne hisaab POORE hue. `None` matlab extraction hi
    nahi chali — "0 hue" se bilkul alag baat.
    """
    if records is None:
        return None
    return sum(1 for rec in records if _calc_ok(rec))


def calculations_done(records: Sequence[CalculationRecord]) -> bool:
    """§18 ke `NO_CALCULATION` reason code ke liye: koi ek hisaab poora hua?"""
    return any(_calc_ok(rec) for rec in records or [])


def _calc_field(rec, name: str, default=None):
    """Record ya dict — dono se ek hi tarah field padho (§17 ke saare helpers)."""
    if isinstance(rec, dict):
        if name == "core_missing":
            return rec.get("core_missing") or []
        return rec.get(name, default)
    if name == "core_missing":
        return list(getattr(rec, "core_missing", []) or [])
    return getattr(rec, name, default)


def calculation_warnings(records: Optional[Sequence]) -> List[str]:
    """User ko dikhane wali imaandaar shikayatein (raw error nahi, Hinglish)."""
    out: List[str] = []
    for i, rec in enumerate(records or [], start=1):
        label = f"Calculation {i}"
        core_missing = _calc_field(rec, "core_missing") or []
        if core_missing:
            out.append(f"{label} adhoora hai — ye cheezein likhi hi nahi gayi: "
                       f"{', '.join(core_missing[:4])}.")
        elif not (_calc_field(rec, "assumptions") or []):
            out.append(f"{label} ke assumptions likhe nahi gaye, isliye ise "
                       "dobara-check kiya hua hisaab nahi kaha ja sakta.")
        if _calc_field(rec, "unit_check_passed") is False:
            out.append(f"{label} ka unit check fail hua (unit likha hi nahi gaya), "
                       "isliye ise verified numeric result nahi kaha ja sakta.")
        if _calc_field(rec, "recalculation_passed") is False:
            out.append(f"{label} dobara jodne par wahi jawab nahi aaya "
                       f"({_calc_field(rec, 'recomputed') or 'recompute'} vs "
                       f"{_calc_field(rec, 'result')}).")
        if _calc_field(rec, "sanity_check_passed") is False:
            out.append(f"{label} physical limit ya unit conversion check mein "
                       "fail hua.")
        if _calc_field(rec, "invented_input") is True:
            out.append(f"{label} mein kam se kam ek number aisa hai jo "
                       "question ya sources mein nahi mila — wo model ka apna "
                       "anumaan hai, verified input nahi.")
    return out


# ── entry point ──────────────────────────────────────────────────────────────

# Sawal quantitative na ho to hum "check pass ho gaya" NAHI likhte — saaf
# likhte hain ki check chala hi nahi.
_SKIP_NOTE = ("Ye sawal numbers/units ka nahi tha, isliye maths-physics sanity "
              "check nahi chalaya gaya (bekaar warnings se bachne ke liye).")


def run(answer: str, question: str = "") -> Dict:
    """
    Point 12 ka poora sanity pass.

    Returns:
        {
          "applicable": bool,      # sawal quantitative tha ya nahi
          "note": str,             # insaani bhasha mein wajah
          "checks": [ {check, passed, detail}, ... ],
          "warnings": [str],       # sirf fail hui checks ke liye
          "quantities": int,       # kitne number+unit mile
          "failed": int,
        }
    """
    text = answer or ""
    if not is_quantitative(question, text):
        return {"applicable": False, "note": _SKIP_NOTE, "checks": [],
                "warnings": [], "quantities": 0, "failed": 0}

    checks: List[SanityCheck] = []
    checks.extend(check_physical_limits(text))
    checks.extend(check_unit_conversions(text))
    checks.extend(check_comparisons(text))

    failed = [c for c in checks if c.passed is False]
    warnings: List[str] = []
    for c in failed:
        warnings.append(f"Maths/physics sanity check fail hui — {c.name}: "
                        f"{c.detail}. Ye jawab ka number galat hone ka signal hai, "
                        f"isliye ise verified mat maanein.")
    done = [c for c in checks if c.passed is not None]
    if not failed and done:
        note = (f"{len(done)} numeric sanity check chali aur sab pass hui "
                f"(physical limits, unit conversion, comparison direction).")
    elif not done:
        note = ("Sawal quantitative tha, par jawab mein unit ke saath itne "
                "numbers nahi the ki sanity check chalaya ja sake.")
    else:
        note = (f"{len(failed)} numeric sanity check fail hui — neeche warning "
                f"mein exact number likha hai.")
    return {
        "applicable": True,
        "note": note,
        "checks": [c.to_dict() for c in checks],
        "warnings": warnings,
        "quantities": len(parse_quantities(text)),
        "failed": len(failed),
    }
