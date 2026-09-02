"""Safe production adapter from existing verification checks to #40 tasks.

The current verification engine already detects a small class of arithmetic and
percentage claims and emits normalized machine-created check names such as
``12 + 8 = 20`` and ``30% of 200 = 60``.  #40 should be useful for those normal
runs without editing the concurrently-owned verification code.

This adapter therefore accepts ONLY the exact normalized check-name grammar
produced by that engine.  Free prose, unit-bearing expressions, algebra prose,
URLs, markdown, code, prompt-injection text, and unknown check shapes are ignored
rather than guessed into executable formulas.

The claimed right-hand-side value is kept as ``expected_value``.  The triple
engine must independently agree with each other *and* with that expected value;
three implementations agreeing on a different answer must not validate a wrong
claim.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Mapping, Sequence


_NUMBER = r"(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?"
_ARITH = re.compile(
    rf"^({_NUMBER})\s*([+\-*/x×])\s*({_NUMBER})\s*=\s*({_NUMBER})$"
)
_PERCENT = re.compile(
    rf"^({_NUMBER})%\s+of\s+({_NUMBER})\s*=\s*({_NUMBER})$",
    re.IGNORECASE,
)
_ALLOWED_CHECK_KEYS = frozenset({"check", "passed", "detail"})


def _number(raw: str) -> float:
    value = float(str(raw).replace(",", ""))
    if not math.isfinite(value) or abs(value) > 1e12:
        raise ValueError("numeric_out_of_bounds")
    return value


def _literal(value: float) -> str:
    return format(float(value), ".17g")


def _tolerances(expected: float, kind: str) -> tuple[float, float]:
    # Mirror the existing verification engine's claimed-value tolerance ceiling,
    # but never make #40 looser than the source check. Arithmetic: max(0.01,
    # 0.1%); percentages: max(0.01, 1%).
    if kind == "percentage":
        return 0.01, 0.01
    return 0.01, 0.001


def _task_from_check(row: Mapping[str, Any], index: int) -> Dict[str, Any] | None:
    # VerificationReport.to_dict emits exactly these public fields for Check.
    # Reject extra keys so arbitrary callers cannot smuggle an alternate formula
    # through a record merely labelled as a verification check.
    if not isinstance(row, Mapping) or not set(row).issubset(_ALLOWED_CHECK_KEYS):
        return None
    name = str(row.get("check") or "").strip()
    if not name or len(name) > 160:
        return None

    match = _ARITH.fullmatch(name)
    if match:
        left_raw, op, right_raw, claimed_raw = match.groups()
        try:
            left, right, claimed = _number(left_raw), _number(right_raw), _number(claimed_raw)
        except ValueError:
            return None
        normalized_op = "*" if op in {"x", "×"} else op
        if normalized_op == "/" and right == 0:
            # Existing verifier reports division by zero as a different check
            # shape without '= claimed'; keep this extra fail-closed guard.
            return None
        abs_tol, rel_tol = _tolerances(claimed, "arithmetic")
        return {
            "task_id": f"verification_check_{index + 1}",
            "expression": f"{_literal(left)} {normalized_op} {_literal(right)}",
            "variables": {},
            "expected_value": claimed,
            "abs_tolerance": abs_tol,
            "rel_tolerance": rel_tol,
            "provenance": {
                "kind": "verification_check",
                "check_name": name,
                "original_passed": row.get("passed"),
            },
        }

    match = _PERCENT.fullmatch(name)
    if match:
        pct_raw, base_raw, claimed_raw = match.groups()
        try:
            pct, base, claimed = _number(pct_raw), _number(base_raw), _number(claimed_raw)
        except ValueError:
            return None
        abs_tol, rel_tol = _tolerances(claimed, "percentage")
        return {
            "task_id": f"verification_check_{index + 1}",
            "expression": f"({_literal(pct)} / 100) * {_literal(base)}",
            "variables": {},
            "expected_value": claimed,
            "abs_tolerance": abs_tol,
            "rel_tolerance": rel_tol,
            "provenance": {
                "kind": "verification_check",
                "check_name": name,
                "original_passed": row.get("passed"),
            },
        }
    return None


def derive_triple_tasks(
    verification: Mapping[str, Any] | None,
    *,
    max_tasks: int = 12,
) -> Dict[str, Any]:
    """Derive bounded #40 tasks from trusted verification-output shapes only.

    Explicit ``triple_implementation_tasks`` win and are returned unchanged by
    this adapter; the triple engine still performs its own grammar validation.
    Automatic derivation is used only when no explicit structured task list is
    present.
    """
    if not isinstance(verification, Mapping):
        return {
            "status": "NO_VERIFICATION_MAPPING",
            "tasks": [],
            "derived": False,
            "source": "none",
            "skipped_checks": 0,
        }

    explicit = verification.get("triple_implementation_tasks")
    if explicit is None:
        nested = verification.get("data_for_verification")
        if isinstance(nested, Mapping):
            explicit = nested.get("triple_implementation_tasks")
    if explicit is not None:
        if not isinstance(explicit, Sequence) or isinstance(explicit, (str, bytes, bytearray)):
            return {
                "status": "INVALID_EXPLICIT_TASK_CONTAINER",
                "tasks": [],
                "derived": False,
                "source": "explicit",
                "skipped_checks": 0,
            }
        return {
            "status": "EXPLICIT_TASKS_PRESENT",
            "tasks": list(explicit),
            "derived": False,
            "source": "explicit",
            "skipped_checks": 0,
        }

    checks = verification.get("checks")
    if not isinstance(checks, Sequence) or isinstance(checks, (str, bytes, bytearray)):
        return {
            "status": "NO_DERIVABLE_CHECKS",
            "tasks": [],
            "derived": True,
            "source": "verification_checks",
            "skipped_checks": 0,
        }

    limit = max(1, min(24, int(max_tasks)))
    tasks: List[Dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    skipped = 0
    for index, raw in enumerate(list(checks)[:200]):
        task = _task_from_check(raw, index) if isinstance(raw, Mapping) else None
        if task is None:
            skipped += 1
            continue
        fingerprint = (str(task["expression"]), float(task["expected_value"]))
        if fingerprint in seen:
            skipped += 1
            continue
        seen.add(fingerprint)
        tasks.append(task)
        if len(tasks) >= limit:
            break
    return {
        "status": "DERIVED_TASKS" if tasks else "NO_DERIVABLE_CHECKS",
        "tasks": tasks,
        "derived": True,
        "source": "verification_checks",
        "skipped_checks": skipped,
        "checks_examined": min(len(checks), 200),
        "note": (
            "Sirf verification engine ke exact normalized arithmetic/percentage check names adapt kiye gaye; free prose execute nahi hoti."
        ),
    }


__all__ = ["derive_triple_tasks"]
