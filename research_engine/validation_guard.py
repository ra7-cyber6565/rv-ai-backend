"""AI-2 holdout, leakage, robustness, ablation and failure guards."""
from __future__ import annotations

import hashlib
import json
import statistics
from typing import Any, Dict, Mapping, Sequence

from .validation_stats import quantile
from .validation_types import HypothesisStatus, UNKNOWN, listify, number, numbers, text


def seal_holdout(values: Any) -> str:
    """Return a deterministic content hash for a predeclared final holdout.

    The hash by itself is not proof that sealing happened before evaluation.
    Callers must also record ``untouched_test_sealed_before_evaluation=True``
    when that fact is supported by their execution workflow/receipt.
    """
    encoded = json.dumps(values, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def audit_holdout(execution: Mapping[str, Any]) -> Dict[str, Any]:
    """Audit whether a final test can truthfully be called *untouched*.

    A final evaluation is promotion-grade only when all of the following are
    explicit: the holdout exists, a predeclared hash matches it, sealing is
    recorded as having happened before evaluation, it was used exactly once,
    and it was not used for tuning/selection. Missing evidence is not silently
    interpreted as success.
    """
    holdout = execution.get("untouched_test")
    if holdout is None:
        return {
            "status": UNKNOWN,
            "reason": "No completely untouched test set supplied.",
            "evaluation_valid_for_final_claim": False,
        }

    current = seal_holdout(holdout)
    declared = text(execution.get("untouched_test_hash"))
    sealed_before = execution.get("untouched_test_sealed_before_evaluation") is True
    uses_number = number(execution.get("untouched_test_uses"))
    uses = int(uses_number) if uses_number is not None and float(uses_number).is_integer() else None
    tuned = bool(execution.get("tuned_on_untouched_test"))
    changed = bool(declared) and declared != current

    issues = []
    if not declared:
        issues.append("PREDECLARED_HASH_MISSING")
    elif changed:
        issues.append("HOLDOUT_CHANGED_AFTER_DECLARATION")
    if not sealed_before:
        issues.append("PRE_EVALUATION_SEALING_NOT_PROVEN")
    if uses is None:
        issues.append("HOLDOUT_USE_COUNT_UNKNOWN")
    elif uses != 1:
        issues.append("HOLDOUT_NOT_USED_EXACTLY_ONCE")
    if tuned:
        issues.append("TUNED_ON_FINAL_HOLDOUT")

    valid = not issues
    return {
        "status": "TEST PERFORMED",
        "hash": current,
        "declared_hash_present": bool(declared),
        "declared_hash_matches": bool(declared) and not changed,
        "sealed_before_evaluation": sealed_before,
        "reported_uses": uses if uses is not None else UNKNOWN,
        "tuned_on_untouched_test": tuned,
        "integrity_pass": valid,
        "evaluation_valid_for_final_claim": valid,
        "issues": issues,
        "fatal_reason": (
            "Final holdout cannot support a promotion-grade claim: " + ", ".join(issues)
            if issues else ""
        ),
        "note": (
            "Hash equality proves content equality only; pre-evaluation sealing is a separate required receipt."
        ),
    }


_FATAL_LEAKAGE = {
    "look_ahead": "Future-known information entered features/decision path.",
    "target_leakage": "Target or target-derived information entered predictors.",
    "tuned_on_untouched_test": "The final test set was used for tuning/selection.",
    "survivorship_bias": "Sampling excluded failures/dead entities in a way that can inflate results.",
    "revised_data_as_realtime": "Revised data were treated as if known in real time.",
}
_OTHER_BIAS = {
    "hindsight_bias": "Rules may depend on information obvious only after outcomes.",
    "selection_bias": "Sample inclusion may depend on outcome/exposure.",
    "confirmation_bias": "Only supportive tests/evidence may have been pursued.",
    "data_snooping": "Repeated search over models/parameters can inflate apparent edge.",
    "cherry_picking": "Periods/metrics/examples may have been selected post hoc.",
    "p_hacking": "Analysis choices may have been iterated until significance appeared.",
    "publication_bias": "Observed literature may overrepresent positive findings.",
    "repeated_holdout_tuning": "Final data appear to have been consulted repeatedly.",
}


def leakage_bias_audit(meta: Mapping[str, Any]) -> Dict[str, Any]:
    src = meta if isinstance(meta, Mapping) else {}
    findings, fatal = [], []
    for key, detail in _FATAL_LEAKAGE.items():
        if bool(src.get(key)):
            findings.append({"risk": key, "severity": "FATAL", "detail": detail})
            fatal.append(key)
    for key, detail in _OTHER_BIAS.items():
        if bool(src.get(key)):
            findings.append({"risk": key, "severity": "HIGH", "detail": detail})
    missing = [key for key in list(_FATAL_LEAKAGE) + list(_OTHER_BIAS) if key not in src]
    return {
        "status": "FAIL" if fatal else ("AUDIT PARTIAL" if missing else "PASS"),
        "fatal": fatal,
        "findings": findings,
        "not_assessed": missing,
        "rule": "Confirmed fatal leakage invalidates the contaminated evaluation; it does not by itself prove the hypothesis false.",
    }


def walk_forward_summary(runs: Any, metric: str) -> Dict[str, Any]:
    rows = [r for r in listify(runs) if isinstance(r, Mapping)]
    values = [number(r.get(metric)) for r in rows]
    values = [v for v in values if v is not None]
    if not values:
        return {"status": UNKNOWN, "reason": f"No walk-forward values for metric '{metric}'."}
    return {"status": "TEST PERFORMED", "metric": metric, "folds": len(values),
            "mean": statistics.fmean(values), "median": statistics.median(values),
            "min": min(values), "max": max(values), "values": values}


def regime_summary(runs: Any, metric: str) -> Dict[str, Any]:
    rows = [r for r in listify(runs) if isinstance(r, Mapping)]
    out = []
    for row in rows:
        value = number(row.get(metric))
        if value is not None:
            out.append({"regime": text(row.get("regime"), "unknown"), metric: value,
                        "explicit_failure": bool(row.get("failed"))})
    if not out:
        return {"status": UNKNOWN, "reason": f"No regime values for metric '{metric}'."}
    return {"status": "TEST PERFORMED", "metric": metric, "rows": out,
            "worst": min(x[metric] for x in out), "best": max(x[metric] for x in out),
            "explicit_failures": [x["regime"] for x in out if x["explicit_failure"]]}


def parameter_stability(grid: Any, *, metric: str, tolerance: Any = None,
                        maximize: bool = True) -> Dict[str, Any]:
    rows = [dict(r) for r in listify(grid) if isinstance(r, Mapping) and number(r.get(metric)) is not None]
    if not rows:
        return {"status": UNKNOWN, "reason": f"No parameter grid rows with metric '{metric}'."}
    rows.sort(key=lambda r: float(r[metric]), reverse=maximize)
    best, tol = rows[0], number(tolerance)
    out: Dict[str, Any] = {"status": "TEST PERFORMED", "metric": metric, "best": best, "rows": len(rows)}
    if tol is None or tol < 0:
        out["stable_region"] = UNKNOWN
        out["reason"] = "No caller-supplied plateau tolerance; a sharp optimum cannot be declared stable or unstable."
        return out
    best_val = float(best[metric])
    threshold = best_val - abs(best_val) * tol if maximize else best_val + abs(best_val) * tol
    plateau = [r for r in rows if (float(r[metric]) >= threshold if maximize else float(r[metric]) <= threshold)]
    out.update({"tolerance_fraction": tol, "plateau_threshold": threshold,
                "plateau_rows": len(plateau), "stable_region": plateau})
    return out


def ablation_analysis(rows: Any, *, metric: str, full_name: str = "full",
                      minimum_increment: Any = None, maximize: bool = True) -> Dict[str, Any]:
    items = [dict(r) for r in listify(rows) if isinstance(r, Mapping)]
    by_name = {text(r.get("name")): r for r in items if text(r.get("name"))}
    full = by_name.get(full_name)
    full_metric = number(full.get(metric)) if full else None
    if full_metric is None:
        return {"status": UNKNOWN, "reason": f"Full model '{full_name}' metric missing."}
    min_inc, comparisons = number(minimum_increment), []
    for name, row in by_name.items():
        if name == full_name:
            continue
        value = number(row.get(metric))
        if value is None:
            continue
        increment = full_metric - value if maximize else value - full_metric
        verdict = UNKNOWN if min_inc is None else ("MEASURABLE VALUE" if increment >= min_inc else "REMOVAL CANDIDATE")
        comparisons.append({"removed_variant": name, "metric": value,
                            "full_minus_variant_increment": increment, "verdict": verdict})
    return {"status": "TEST PERFORMED", "metric": metric, "full_metric": full_metric,
            "caller_minimum_increment": min_inc if min_inc is not None else UNKNOWN,
            "comparisons": comparisons,
            "note": "No component is recommended for removal unless caller supplied an incremental-value/equivalence criterion."}


def failure_distribution(values: Sequence[Any], *, catastrophic_threshold: Any = None,
                         worse_is_lower: bool = True) -> Dict[str, Any]:
    xs, threshold = numbers(values), number(catastrophic_threshold)
    if not xs:
        return {"status": UNKNOWN, "reason": "No observed failure/performance distribution supplied."}
    out: Dict[str, Any] = {"status": "RESULT OBSERVED", "n": len(xs), "min": min(xs),
                           "max": max(xs), "median": statistics.median(xs),
                           "p05": quantile(xs, .05), "p95": quantile(xs, .95),
                           "mean": statistics.fmean(xs),
                           "sample_sd": statistics.stdev(xs) if len(xs) >= 2 else UNKNOWN,
                           "catastrophic_rate": UNKNOWN}
    if threshold is not None:
        out["catastrophic_rate"] = sum((x <= threshold if worse_is_lower else x >= threshold) for x in xs) / len(xs)
        out["catastrophic_threshold"] = threshold
    return out


def failure_cluster_analysis(outcomes: Sequence[Any], *, failure_threshold: Any,
                             worse_is_lower: bool = True) -> Dict[str, Any]:
    xs, threshold = numbers(outcomes), number(failure_threshold)
    if not xs or threshold is None:
        return {"status": UNKNOWN, "reason": "Observed outcomes and an explicit failure threshold are required."}
    flags = [(x <= threshold if worse_is_lower else x >= threshold) for x in xs]
    clusters, cur = [], 0
    for flag in flags + [False]:
        if flag:
            cur += 1
        elif cur:
            clusters.append(cur)
            cur = 0
    return {"status": "RESULT OBSERVED", "n": len(xs), "failure_threshold": threshold,
            "failure_rate": sum(flags) / len(flags), "clusters": clusters,
            "cluster_count": len(clusters), "longest_failure_cluster": max(clusters) if clusters else 0}


def evaluate_decision_rule(metrics: Mapping[str, Any], rule: Mapping[str, Any]) -> Dict[str, Any]:
    if not rule:
        return {"status": HypothesisStatus.INCONCLUSIVE.value,
                "reason": "Observed metrics may exist, but no explicit decision/falsification rule was supplied."}
    metric, op, threshold = text(rule.get("metric")), text(rule.get("operator")), number(rule.get("threshold"))
    value = number(metrics.get(metric)) if metric else None
    if not metric or op not in (">", ">=", "<", "<=", "==") or threshold is None or value is None:
        return {"status": HypothesisStatus.INCONCLUSIVE.value,
                "reason": "Decision rule is not fully evaluable against observed metrics."}
    passed = {">": value > threshold, ">=": value >= threshold, "<": value < threshold,
              "<=": value <= threshold, "==": value == threshold}[op]
    return {"status": HypothesisStatus.PASS.value if passed else HypothesisStatus.FAIL.value,
            "reason": f"Observed {metric}={value} {'satisfies' if passed else 'does not satisfy'} caller-supplied rule {metric} {op} {threshold}.",
            "metric": metric, "value": value, "operator": op, "threshold": threshold}


__all__ = [
    "seal_holdout", "audit_holdout", "leakage_bias_audit", "walk_forward_summary",
    "regime_summary", "parameter_stability", "ablation_analysis", "failure_distribution",
    "failure_cluster_analysis", "evaluate_decision_rule",
]
