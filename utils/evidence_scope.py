"""Conservative pressure-scope metadata, not an experimental truth classifier.

One standard atmosphere is exactly 101325 Pa. No tolerance for a particular
experiment is guessed: mixed, different and unspecified conditions stay context.
Matching pressure alone establishes neither superconductivity nor replication.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

_AMBIENT = re.compile(
    r"\b(?:ambient|atmospheric|normal(?:\s+atmospheric)?|standard\s+atmospheric)\s*[- ]\s*pressure\b"
    r"|सामान्य\s*(?:वायुदाब|दबाव)|वायुमंडलीय\s*(?:दबाव|दाब)", re.I)
_NEAR = re.compile(r"\bnear\s*[- ]\s*ambient", re.I)
_PRESSURE = re.compile(
    r"(?<![\w.,+-])(?P<value>(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?)\s*"
    r"(?P<unit>GPa|MPa|kPa|Pa|kbar|mbar|bar|atm)\b")
_FACTORS = {"GPa": Decimal(10**9), "MPa": Decimal(10**6),
            "kPa": Decimal(1000), "Pa": Decimal(1), "kbar": Decimal(10**8),
            "bar": Decimal(100000), "mbar": Decimal(100), "atm": Decimal(101325)}


def ambient_pressure_requested(question: str) -> bool:
    return bool(_AMBIENT.search(_NEAR.sub("near-condition", str(question or ""))))


def pressure_scope(question: str, passage: str) -> dict:
    """Describe only explicitly written conditions; never infer absent pressure."""
    if not ambient_pressure_requested(question):
        return {"required": False, "state": "NOT_APPLICABLE", "reported_pressures": []}
    text = str(passage or "")
    ambient = ambient_pressure_requested(text)
    pressures = []
    for match in _PRESSURE.finditer(text[:10000]):
        try:
            if len(match["value"]) > 64:
                continue
            value = Decimal(match["value"])
            # Unbounded exponents are untrusted source text, not usable data.
            if not value.is_finite() or abs(value.adjusted()) > 30:
                continue
            pa = value * _FACTORS[match["unit"]]
        except InvalidOperation:
            continue
        pressures.append({"value": match["value"], "unit": match["unit"],
                          "pascals": str(pa), "standard_atmosphere": pa == Decimal(101325)})
    different = any(not p["standard_atmosphere"] for p in pressures)
    matching = ambient or any(p["standard_atmosphere"] for p in pressures)
    if different:
        state = "MIXED_CONDITIONS" if matching else "DIFFERENT_PRESSURE"
    elif matching:
        state = "MATCHING_PRESSURE_ONLY"
    else:
        state = "PRESSURE_UNSPECIFIED"
    return {"required": True, "state": state, "reported_pressures": pressures,
            "scientific_confirmation": "NOT_ASSESSED"}


SCOPE_LABELS = {
    "DIFFERENT_PRESSURE": "Reported pressure 1 standard atmosphere se alag hai; experimental conditions verify karni hain",
    "MIXED_CONDITIONS": "Kai pressure conditions; har result ki condition alag verify karni hai",
    "PRESSURE_UNSPECIFIED": "Is passage mein normal atmospheric pressure verify nahi hua",
    "MATCHING_PRESSURE_ONLY": "Pressure ka milaan hua; claim ki independent confirmation alag check hai",
}
