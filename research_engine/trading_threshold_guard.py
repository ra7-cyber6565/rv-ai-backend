"""Fail-closed provenance guard for numeric trading rules.

A generated trading specification may contain useful numeric entry/exit/risk
parameters, but a bare number is not evidence.  This module does *not* decide
whether a strategy is profitable and it does not invent a replacement value.
It only checks that numeric rule lines are visibly scoped as one of:

* source/evidence reported (with a citation/provenance cue),
* explicitly user-specified, or
* provisional / hypothesis / parameter-to-test.

The guard is deterministic, network-free and stores only counts, line numbers
and hashes for unsupported lines.  It never copies the answer text into its
machine-readable receipt.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Mapping

from . import trademodel


_NUMERIC = re.compile(
    r"(?<![A-Za-z0-9_])(?:\d+(?:\.\d+)?|\.\d+)\s*"
    r"(?:%|r\b|atr\b|points?\b|pts?\b|ticks?\b|pips?\b|"
    r"minutes?\b|mins?\b|hours?\b|hrs?\b|sigma\b|bps?\b|ms\b|x\b)?",
    re.IGNORECASE,
)

# Only lines that look like an actual executable/trading rule are checked.
# Source counts, dates and ordinary explanatory numbers are intentionally out of
# scope so this does not become a generic number detector.
_RULE_CUE = re.compile(
    r"(?:\bentry\b|\btrigger\b|\blong\s+if\b|\bshort\s+if\b|"
    r"\bstop(?:[- ]?loss)?\b|\btake[- ]?profit\b|\btarget\b|"
    r"\bno[- ]?trade\b|\bposition\s+size\b|\brisk\s+per\s+trade\b|"
    r"\bthreshold\b|\bfilter\b|\breclaim\b|\bbreak(?:out)?\b|"
    r"\bsweep\b|\bimbalance\b|\bspread\b|\bslippage\b|\blatency\b|"
    r"\batr\b|\bvwap\b|\bema\b|\brsi\b|\badx\b)",
    re.IGNORECASE,
)

_SOURCE_PROVENANCE = re.compile(
    r"(?:\[(?:source[- ]?reported|evidence[- ]?[a-e]|s\d{1,3})\]|"
    r"\((?:s\d{1,3})\)|\bsource[- ]?reported\b|\baccording\s+to\b|"
    r"\bcited\b|\bcitation\b|\bfrom\s+source\b)",
    re.IGNORECASE,
)
_PROVISIONAL = re.compile(
    r"(?:\bprovisional\b|\btest\s+parameter\b|\bparameter\s+to\s+test\b|"
    r"\bstarting\s+parameter\b|\bstarting\s+value\b|\billustrative\b|"
    r"\bexample\b|\bhypothes(?:is|ized|ised)\b|\bto\s+be\s+tested\b|"
    r"\bnot\s+measured\b|\bunverified\b|\bassumption\b|\bplaceholder\b|"
    r"\bgrid[- ]?search\b|\bparameter\s+sweep\b|\btune\b|\boptimi[sz]e\b|"
    r"\brange\s+to\s+test\b)",
    re.IGNORECASE,
)
_USER_SPECIFIED = re.compile(
    r"(?:\buser[- ]?specified\b|\buser[- ]?requested\b|"
    r"\baap(?:ke|ka|ki)\s+(?:diye|requested|rule|constraint)\b|"
    r"\buser\s+constraint\b)",
    re.IGNORECASE,
)


def _hash_line(line: str) -> str:
    return hashlib.sha256(line.strip().encode("utf-8")).hexdigest()


def assess(question: str, result: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a sanitized threshold-provenance receipt.

    `passed=False` means at least one numeric trading-rule line has no visible
    provenance class.  It does not mean the number is scientifically false; it
    means the app cannot honestly present it as an accepted final threshold yet.
    """
    active = bool(trademodel.is_request(str(question or "")))
    report: Dict[str, Any] = {
        "schema": 1,
        "active": active,
        "passed": True,
        "checked_rule_lines": 0,
        "supported_rule_lines": 0,
        "unsupported_rule_lines": 0,
        "unsupported_line_numbers": [],
        "unsupported_line_sha256": [],
        "accepted_provenance": ["SOURCE_REPORTED", "USER_SPECIFIED", "PROVISIONAL_TEST_PARAMETER"],
        "network_used": False,
        "model_calls": 0,
        "profitability_proven": False,
        "policy": "numeric trading rules require visible source/user/provisional provenance; bare thresholds fail closed",
    }
    if not active:
        return report

    answer = str(result.get("answer") or "")
    lines = answer.splitlines()
    supported = 0
    unsupported_numbers = []
    unsupported_hashes = []
    checked = 0

    for index, line in enumerate(lines):
        if not line.strip() or not _RULE_CUE.search(line) or not _NUMERIC.search(line):
            continue
        checked += 1
        # A heading immediately above a table/list may establish scope for the
        # numeric row, so inspect only a tight local window rather than the full
        # answer.  This prevents one distant "provisional" word blessing every
        # later threshold.
        start = max(0, index - 2)
        context = "\n".join(lines[start:index + 1])
        if _SOURCE_PROVENANCE.search(context) or _PROVISIONAL.search(context) or _USER_SPECIFIED.search(context):
            supported += 1
            continue
        unsupported_numbers.append(index + 1)
        unsupported_hashes.append(_hash_line(line))

    report.update(
        passed=not unsupported_numbers,
        checked_rule_lines=checked,
        supported_rule_lines=supported,
        unsupported_rule_lines=len(unsupported_numbers),
        unsupported_line_numbers=unsupported_numbers[:64],
        unsupported_line_sha256=unsupported_hashes[:64],
    )
    return report
