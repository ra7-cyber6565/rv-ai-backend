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
from typing import Dict, List, Optional, Tuple

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
def check_comparisons(text: str) -> List[SanityCheck]:
    """
    "250 K, jo 30 °C se zyada hai" — dono number theek, comparison ulta.

    Sirf same-dimension jodon par chalta hai aur sirf tab jab dono ke beech
    40 characters se kam ka comparative phrase ho — warna do alag baaton ko
    jodne ka khatra hai.
    """
    quantities = parse_quantities(text)
    tested = 0
    wrong: List[str] = []
    for a, b in zip(quantities, quantities[1:]):
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
        elif less and a.si > b.si:
            wrong.append(f"likha hai '{a.label()}' < '{b.label()}', lekin "
                         f"{_pretty(a)} > {_pretty(b)} hai")
    if not tested:
        return [SanityCheck("comparison direction", None,
                            "unit ke saath koi aisi tulna nahi mili jise "
                            "conversion se jaancha ja sake")]
    if wrong:
        return [SanityCheck("comparison direction", False, "; ".join(wrong[:3]))]
    return [SanityCheck("comparison direction", True,
                        f"{tested} tulna unit conversion ke baad bhi sahi nikli")]


# ── entry point ──────────────────────────────────────────────────────────────
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
