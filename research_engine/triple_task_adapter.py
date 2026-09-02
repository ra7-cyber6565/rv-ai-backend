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
from copy import deepcopy
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


def _expected_number(raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("invalid_expected_value")
    value = float(raw)
    if not math.isfinite(value) or abs(value) > 1e18:
        raise ValueError("invalid_expected_value")
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


def run_adapted_triple(engine: Any, adaptation: Mapping[str, Any]) -> Dict[str, Any]:
    """Run #40 and independently compare any claimed expected values.

    The base triple engine remains the authority for grammar/backend/pairwise
    implementation agreement.  This wrapper adds a second fail-closed condition:
    where a task carries ``expected_value``, every successful backend result must
    also match that claimed value inside the same bounded tolerance.
    """
    if not isinstance(adaptation, Mapping):
        return {
            "schema_version": "1.0",
            "capability_id": 40,
            "capability": "Triple Independent Implementation",
            "status": "INVALID_TASK_SET",
            "all_requested_tasks_agree": False,
            "all_expected_values_match": False,
            "results": [],
            "task_adapter": {"status": "INVALID_ADAPTER_INPUT"},
        }
    adapter_status = str(adaptation.get("status") or "")
    tasks_raw = adaptation.get("tasks")
    if adapter_status == "INVALID_EXPLICIT_TASK_CONTAINER" or not isinstance(tasks_raw, Sequence) or isinstance(tasks_raw, (str, bytes, bytearray)):
        return {
            "schema_version": "1.0",
            "capability_id": 40,
            "capability": "Triple Independent Implementation",
            "status": "INVALID_TASK_SET",
            "all_requested_tasks_agree": False,
            "all_expected_values_match": False,
            "results": [],
            "task_adapter": {
                "status": adapter_status or "INVALID_TASK_CONTAINER",
                "derived": bool(adaptation.get("derived")),
                "source": str(adaptation.get("source") or "unknown"),
            },
        }

    tasks = list(tasks_raw)
    try:
        base = engine.run(tasks)
    except Exception:
        return {
            "schema_version": "1.0",
            "capability_id": 40,
            "capability": "Triple Independent Implementation",
            "status": "ASSESSMENT_ERROR",
            "all_requested_tasks_agree": False,
            "all_expected_values_match": False,
            "results": [],
            "task_adapter": {
                "status": adapter_status or "UNKNOWN",
                "derived": bool(adaptation.get("derived")),
                "source": str(adaptation.get("source") or "unknown"),
            },
        }
    report = deepcopy(dict(base))
    rows = list(report.get("results") or [])
    expected_checked = 0
    expected_matched = 0
    invalid_expected = 0
    claim_mismatch = False

    for raw, row in zip(tasks, rows):
        if not isinstance(raw, Mapping) or not isinstance(row, dict) or "expected_value" not in raw:
            continue
        expected_checked += 1
        try:
            expected = _expected_number(raw.get("expected_value"))
            abs_tol = float(raw.get("abs_tolerance", row.get("abs_tolerance", 1e-9)))
            rel_tol = float(raw.get("rel_tolerance", row.get("rel_tolerance", 1e-9)))
            if not math.isfinite(abs_tol) or not math.isfinite(rel_tol) or abs_tol < 0 or rel_tol < 0 or rel_tol > 1.0:
                raise ValueError("invalid_tolerance")
        except (TypeError, ValueError):
            invalid_expected += 1
            row["expected_value_checked"] = False
            row["claim_value_matches_expected"] = False
            row["verified"] = False
            if row.get("status") == "TRIPLE_AGREEMENT":
                row["status"] = "INVALID_EXPECTED_VALUE"
            continue

        backend_checks: Dict[str, bool] = {}
        for implementation in row.get("implementations", []):
            if not isinstance(implementation, Mapping) or not implementation.get("ok"):
                continue
            try:
                value = float(implementation.get("value"))
            except (TypeError, ValueError):
                continue
            backend_checks[str(implementation.get("backend") or "unknown")] = math.isclose(
                value,
                expected,
                rel_tol=rel_tol,
                abs_tol=abs_tol,
            )
        expected_ok = len(backend_checks) == 3 and all(backend_checks.values())
        row["expected_value_checked"] = True
        row["expected_value"] = expected
        row["expected_value_agreement"] = backend_checks
        row["claim_value_matches_expected"] = expected_ok
        if expected_ok:
            expected_matched += 1
        elif row.get("status") == "TRIPLE_AGREEMENT":
            # All implementations can agree with each other and still prove the
            # model/user's written RHS is wrong. Do not let that become a pass.
            claim_mismatch = True
            row["status"] = "CLAIM_MISMATCH"
            row["verified"] = False
            row["note"] = (
                "Teen implementations aapas mein agree karte hain, lekin claimed expected value se match nahi karte; claim validate nahi hua."
            )

    report["results"] = rows
    report["task_adapter"] = {
        "status": adapter_status or "UNKNOWN",
        "derived": bool(adaptation.get("derived")),
        "source": str(adaptation.get("source") or "unknown"),
        "skipped_checks": int(adaptation.get("skipped_checks") or 0),
    }
    report["expected_values_checked"] = expected_checked
    report["expected_values_matched"] = expected_matched
    report["all_expected_values_match"] = bool(expected_checked) and expected_matched == expected_checked and invalid_expected == 0
    report["invalid_expected_values"] = invalid_expected
    report["implementations_all_agree"] = bool(report.get("all_requested_tasks_agree"))

    if invalid_expected:
        report["status"] = "INVALID_EXPECTED_VALUE"
        report["all_requested_tasks_agree"] = False
    elif claim_mismatch:
        report["status"] = "CLAIM_MISMATCH"
        report["all_requested_tasks_agree"] = False
    if expected_checked and not report["all_expected_values_match"]:
        report["maturity_proof"] = dict(report.get("maturity_proof") or {})
        report["maturity_proof"]["max_or_verified_real_world_claim"] = False
    return report


__all__ = ["derive_triple_tasks", "run_adapted_triple"]
