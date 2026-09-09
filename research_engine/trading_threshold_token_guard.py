"""Exclude instrument-symbol digits from actionable threshold accounting.

``US100 entry`` and ``US500 entry`` contain numbers, but those digits identify an
instrument; they are not a model threshold.  This narrow compatibility guard
post-processes the threshold audit so ticker digits cannot create a false
unsupported-threshold failure.  It changes no genuine comparator/unit value.
"""
from __future__ import annotations

import re
from functools import wraps


def _embedded_symbol_number(expression: str, line: str) -> bool:
    expr = str(expression or "").strip().lower()
    # Only a bare positive number can be an instrument-symbol fragment. Values
    # with >/<, %, R, ATR, x etc. remain real threshold candidates.
    if not re.fullmatch(r"\d+(?:\.\d+)?", expr):
        return False
    token = re.escape(expr)
    return bool(re.search(rf"(?:[A-Za-z]+{token}\b|\b{token}[A-Za-z]+)", str(line or "")))


def install() -> None:
    from . import trading_acceptance_guard as _guard

    prior = _guard.audit_thresholds
    if getattr(prior, "__ticker_digit_guard__", False):
        return

    @wraps(prior)
    def guarded_audit_thresholds(question, spec, *, lab_report=None):
        out = prior(question, spec, lab_report=lab_report)
        rows = list(out.get("rows") or [])
        removed = [row for row in rows if row.get("provenance") == "unsupported"
                   and _embedded_symbol_number(row.get("expression", ""), row.get("line", ""))]
        if not removed:
            return out

        out = dict(out)
        out["rows"] = [row for row in rows if row not in removed]
        count = len(removed)
        out["actionable_numeric_thresholds"] = max(
            0, int(out.get("actionable_numeric_thresholds") or 0) - count)
        out["unsupported_count"] = max(0, int(out.get("unsupported_count") or 0) - count)
        out["acceptance_blocked"] = bool(out["unsupported_count"])
        total = int(out.get("actionable_numeric_thresholds") or 0)
        unsupported = int(out.get("unsupported_count") or 0)
        out["ticker_digits_excluded"] = count
        out["note"] = (
            f"{unsupported}/{total} actionable numeric threshold ka traceable "
            "source/user/LAB/provisional label nahi mila."
            if unsupported else
            f"{total} actionable numeric threshold mile; koi unlabelled/untraceable "
            "threshold nahi mila. Instrument-symbol digits threshold nahi gine gaye."
        )
        return out

    guarded_audit_thresholds.__ticker_digit_guard__ = True
    _guard.audit_thresholds = guarded_audit_thresholds


install()
