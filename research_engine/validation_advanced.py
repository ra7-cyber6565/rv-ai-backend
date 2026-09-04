"""Advanced executable validation receipts for AI-2.

This module closes the gap between a validation *plan* and a validation engine.
It remains fail-closed: no provenance -> no observed result, no supplied rule ->
no PASS/FAIL, and no final-test declaration -> no generalization claim.
"""
from __future__ import annotations

import math
import random
from copy import deepcopy
from statistics import mean
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .validation_contracts import (
    CONDITIONAL_PASS, FAIL, INCONCLUSIVE, NOT_TESTED, PASS, RESULT_OBSERVED,
    TEST_PERFORMED, TEST_POSSIBLE, UNKNOWN, meaningful,
)

_PROVENANCE_KEYS = (
    "test_id", "run_id", "dataset_id", "source", "source_id", "timestamp",
    "artifact", "report", "observed_metrics",
)
_OPERATORS = {
    ">": lambda x, y: x > y,
    ">=": lambda x, y: x >= y,
    "<": lambda x, y: x < y,
    "<=": lambda x, y: x <= y,
    "==": lambda x, y: x == y,
    "!=": lambda x, y: x != y,
}
_REQUIRED_VARIABLE_ROLES = (
    "independent", "dependent", "control", "mediator", "confounder", "state", "uncertainty",
)


def _numbers(value: Any) -> List[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    out: List[float] = []
    for item in value:
        if isinstance(item, bool):
            return []
        try:
            number = float(item)
        except (TypeError, ValueError):
            return []
        if not math.isfinite(number):
            return []
        out.append(number)
    return out


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _provenance(receipt: Any) -> Dict[str, Any]:
    if not isinstance(receipt, Mapping):
        return {}
    raw = receipt.get("provenance") or receipt.get("result_provenance") or receipt.get("test_provenance")
    if not isinstance(raw, Mapping):
        return {}
    if not any(meaningful(raw.get(key)) for key in _PROVENANCE_KEYS):
        return {}
    return deepcopy(dict(raw))


def _percentile(values: Sequence[float], q: float) -> Any:
    if not values:
        return NOT_TESTED
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    lo = int(math.floor(pos)); hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def evaluate_decision_rule(metrics: Mapping[str, Any], rule: Any) -> Dict[str, Any]:
    """Evaluate only an explicit numeric rule; supports explicit CONDITIONAL PASS."""
    if not isinstance(rule, Mapping):
        return {"status": INCONCLUSIVE, "reason": "No explicit machine-readable decision rule supplied."}
    metric = str(rule.get("metric") or "").strip()
    operator = str(rule.get("operator") or "").strip()
    threshold = _number(rule.get("threshold"))
    observed = _number(metrics.get(metric)) if metric in metrics else None
    if not metric or operator not in _OPERATORS or threshold is None or observed is None:
        return {"status": INCONCLUSIVE, "reason": "Decision rule is incomplete or references a non-numeric/unavailable metric."}
    passed = bool(_OPERATORS[operator](observed, threshold))
    status_if_pass = str(rule.get("status_if_pass") or PASS).strip().upper().replace("_", " ")
    if status_if_pass not in {PASS, CONDITIONAL_PASS}:
        return {"status": INCONCLUSIVE, "reason": "status_if_pass must be PASS or CONDITIONAL PASS when supplied."}
    return {
        "status": status_if_pass if passed else FAIL,
        "metric": metric,
        "observed": observed,
        "operator": operator,
        "threshold": threshold,
        "rule_source": "SUPPLIED_IN_RESULT_RECEIPT",
    }


def collect_second_pass_outputs(result: Mapping[str, Any], explicit: Any = None) -> Dict[str, Any]:
    """Collect already-present agent handoffs without inventing missing agents."""
    merged: Dict[str, Any] = deepcopy(dict(explicit)) if isinstance(explicit, Mapping) else {}
    aliases = {
        "AI-1": ("ai1_research_packet", "ai1_output"),
        "AI-3": ("ai3_theory_packet", "ai3_hypotheses", "ai3_output"),
        "AI-4": ("ai4_red_team_packet", "ai4_output", "red_team_packet"),
    }
    for agent, keys in aliases.items():
        if agent in merged:
            continue
        for key in keys:
            value = result.get(key)
            if isinstance(value, Mapping) and value:
                merged[agent] = deepcopy(dict(value))
                break
    return merged


def variable_role_audit(experiments: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for experiment in experiments:
        roles = set()
        variables = experiment.get("Variables")
        if isinstance(variables, Sequence) and not isinstance(variables, (str, bytes, bytearray)):
            for variable in variables:
                if isinstance(variable, Mapping):
                    role = str(variable.get("role") or "").strip().lower()
                    if role and role != UNKNOWN.lower():
                        roles.add(role)
        rows.append({
            "hypothesis_id": experiment.get("hypothesis_id"),
            "provided_roles": sorted(roles),
            "role_categories_not_explicitly_supplied": [role for role in _REQUIRED_VARIABLE_ROLES if role not in roles],
            "interpretation": "Missing roles are not automatically errors; AI-2 must mark them NOT APPLICABLE or define them when causally/statistically relevant.",
        })
    return rows


def _find_mapping(result: Mapping[str, Any], keys: Sequence[str]) -> Optional[Dict[str, Any]]:
    for key in keys:
        value = result.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    coverage = result.get("coverage")
    if isinstance(coverage, Mapping):
        for key in keys:
            value = coverage.get(key)
            if isinstance(value, Mapping):
                return dict(value)
    return None


def find_predictive_receipt(result: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    return _find_mapping(result, ("predictive_validation_receipt", "predictive_result_receipt", "model_validation_receipt"))


def analyze_predictive_receipt(receipt: Any) -> Dict[str, Any]:
    provenance = _provenance(receipt)
    if not isinstance(receipt, Mapping) or not provenance:
        return {"observed": False, "status": INCONCLUSIVE, "reason": "Predictive validation requires explicit result provenance."}
    primary_metric = str(receipt.get("primary_metric") or "").strip()
    splits = receipt.get("splits") if isinstance(receipt.get("splits"), Mapping) else {}
    if not primary_metric or not splits:
        return {"observed": False, "status": INCONCLUSIVE, "reason": "primary_metric and split metrics are required."}

    def split_metric(*names: str) -> Optional[float]:
        for name in names:
            row = splits.get(name)
            if isinstance(row, Mapping):
                value = _number(row.get(primary_metric))
                if value is not None:
                    return value
        return None

    train = split_metric("train", "training")
    validation = split_metric("validation", "valid", "dev")
    untouched = split_metric("untouched_test", "test", "oos", "out_of_sample", "external_test")
    test_tuning_flag = receipt.get("test_was_used_for_tuning")
    final_test_valid = untouched is not None and test_tuning_flag is False
    metrics: Dict[str, Any] = {
        "training_metric": train if train is not None else NOT_TESTED,
        "validation_metric": validation if validation is not None else NOT_TESTED,
        "untouched_test_metric": untouched if untouched is not None else NOT_TESTED,
    }
    if train is not None and untouched is not None:
        metrics["train_to_test_change"] = untouched - train
    if validation is not None and untouched is not None:
        metrics["validation_to_test_change"] = untouched - validation

    if not final_test_valid:
        decision = {"status": INCONCLUSIVE,
                    "reason": "A numeric untouched test metric plus test_was_used_for_tuning=false is required before final predictive PASS/FAIL."}
    else:
        decision = evaluate_decision_rule(metrics, receipt.get("decision_rule"))
    return {
        "observed": True,
        "test_state": RESULT_OBSERVED,
        "status": decision["status"],
        "provenance": provenance,
        "primary_metric": primary_metric,
        "metrics": metrics,
        "final_test_valid": final_test_valid,
        "test_was_used_for_tuning": test_tuning_flag if isinstance(test_tuning_flag, bool) else UNKNOWN,
        "rolling_validation": deepcopy(receipt.get("rolling_validation", NOT_TESTED)),
        "walk_forward": deepcopy(receipt.get("walk_forward", NOT_TESTED)),
        "external_replication": deepcopy(receipt.get("external_replication", NOT_TESTED)),
        "cross_dataset_testing": deepcopy(receipt.get("cross_dataset_testing", NOT_TESTED)),
        "temporal_replication": deepcopy(receipt.get("temporal_replication", NOT_TESTED)),
        "regime_testing": deepcopy(receipt.get("regime_testing", NOT_TESTED)),
        "decision": decision,
    }


def find_robustness_receipt(result: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    return _find_mapping(result, ("robustness_result_receipt", "robustness_receipt"))


def analyze_robustness_receipt(receipt: Any) -> Dict[str, Any]:
    provenance = _provenance(receipt)
    if not isinstance(receipt, Mapping) or not provenance:
        return {"observed": False, "status": INCONCLUSIVE, "reason": "Robustness analysis requires explicit provenance."}
    raw = receipt.get("scenarios")
    scenarios: Dict[str, float] = {}
    if isinstance(raw, Mapping):
        for name, value in raw.items():
            number = _number(value)
            if number is not None:
                scenarios[str(name)] = number
    if not scenarios:
        return {"observed": False, "status": INCONCLUSIVE, "reason": "Numeric robustness scenarios are required."}
    values = list(scenarios.values())
    nominal_name = str(receipt.get("nominal_scenario") or "").strip()
    nominal = scenarios.get(nominal_name) if nominal_name else None
    metrics: Dict[str, Any] = {
        "scenario_count": len(values),
        "minimum": min(values),
        "maximum": max(values),
        "range": max(values) - min(values),
        "mean": mean(values),
        "all_positive": 1.0 if all(v > 0 for v in values) else 0.0,
        "all_nonnegative": 1.0 if all(v >= 0 for v in values) else 0.0,
    }
    if nominal is not None:
        metrics["nominal"] = nominal
        metrics["max_absolute_deviation_from_nominal"] = max(abs(v - nominal) for v in values)
    decision = evaluate_decision_rule(metrics, receipt.get("decision_rule"))
    return {"observed": True, "test_state": RESULT_OBSERVED, "status": decision["status"],
            "provenance": provenance, "scenarios": scenarios, "metrics": metrics,
            "decision": decision,
            "warning": "Stable regions matter more than a single optimum; the decision threshold must be supplied, never inferred."}


def find_ablation_receipt(result: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    return _find_mapping(result, ("ablation_result_receipt", "ablation_receipt"))


def analyze_ablation_receipt(receipt: Any) -> Dict[str, Any]:
    provenance = _provenance(receipt)
    if not isinstance(receipt, Mapping) or not provenance:
        return {"observed": False, "status": INCONCLUSIVE, "reason": "Ablation analysis requires explicit provenance."}
    full_score = _number(receipt.get("full_model_score"))
    raw = receipt.get("without_component_scores")
    higher_is_better = receipt.get("higher_is_better")
    threshold = _number(receipt.get("materiality_threshold"))
    if full_score is None or not isinstance(raw, Mapping) or not raw or not isinstance(higher_is_better, bool):
        return {"observed": False, "status": INCONCLUSIVE,
                "reason": "full_model_score, without_component_scores and explicit higher_is_better boolean are required."}
    rows = []
    for component, value in raw.items():
        score = _number(value)
        if score is None:
            continue
        loss = full_score - score if higher_is_better else score - full_score
        recommendation = NOT_TESTED
        if threshold is not None and threshold >= 0:
            recommendation = "REMOVAL" if loss <= threshold else "KEEP"
        rows.append({"component": str(component), "score_without_component": score,
                     "incremental_value_of_component": loss, "recommendation": recommendation})
    if not rows:
        return {"observed": False, "status": INCONCLUSIVE, "reason": "No numeric ablation scores were supplied."}
    return {
        "observed": True, "test_state": RESULT_OBSERVED, "status": INCONCLUSIVE,
        "provenance": provenance, "full_model_score": full_score,
        "higher_is_better": higher_is_better, "materiality_threshold": threshold if threshold is not None else NOT_TESTED,
        "components": rows,
        "decision_rule": "REMOVAL is emitted only when an explicit non-negative materiality_threshold is supplied and removal does not materially weaken performance.",
    }


def find_failure_receipt(result: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    return _find_mapping(result, ("failure_result_receipt", "failure_distribution_receipt", "stress_result_receipt"))


def analyze_failure_receipt(receipt: Any) -> Dict[str, Any]:
    provenance = _provenance(receipt)
    if not isinstance(receipt, Mapping) or not provenance:
        return {"observed": False, "status": INCONCLUSIVE, "reason": "Failure-distribution analysis requires explicit provenance."}
    flags_raw = receipt.get("failure_flags")
    flags: List[bool] = []
    if isinstance(flags_raw, Sequence) and not isinstance(flags_raw, (str, bytes, bytearray)):
        if all(isinstance(v, bool) for v in flags_raw):
            flags = list(flags_raw)
    severities = _numbers(receipt.get("failure_severities"))
    if not flags and not severities:
        return {"observed": False, "status": INCONCLUSIVE, "reason": "failure_flags and/or numeric failure_severities are required."}
    metrics: Dict[str, Any] = {}
    if flags:
        metrics["sample_size"] = len(flags)
        metrics["failure_frequency"] = sum(flags) / len(flags)
        current = 0; longest = 0
        for flag in flags:
            current = current + 1 if flag else 0
            longest = max(longest, current)
        metrics["longest_failure_cluster"] = longest
    if severities:
        metrics["severity_n"] = len(severities)
        metrics["mean_failure_severity"] = mean(severities)
        metrics["p95_failure_severity"] = _percentile(severities, .95)
        metrics["worst_failure_severity"] = max(severities)

    threshold = _number(receipt.get("catastrophe_threshold"))
    higher_is_worse = receipt.get("severity_higher_is_worse")
    if threshold is not None and isinstance(higher_is_worse, bool) and severities:
        catastrophic = [v >= threshold if higher_is_worse else v <= threshold for v in severities]
        metrics["catastrophic_failure_frequency"] = sum(catastrophic) / len(catastrophic)
    else:
        metrics["catastrophic_failure_frequency"] = NOT_TESTED

    mc: Any = NOT_TESTED
    iterations = receipt.get("monte_carlo_iterations"); seed = receipt.get("random_seed")
    if severities and isinstance(iterations, int) and iterations > 0 and isinstance(seed, int):
        rng = random.Random(seed); maxima = []
        for _ in range(iterations):
            sample = [severities[rng.randrange(len(severities))] for _ in severities]
            maxima.append(max(sample))
        mc = {"method": "iid_bootstrap_of_observed_failure_severity", "iterations": iterations,
              "random_seed": seed, "median_path_max": _percentile(maxima, .5),
              "p95_path_max": _percentile(maxima, .95), "worst_path_max": max(maxima),
              "assumption_warning": "IID bootstrap does not preserve temporal dependence; use a supplied dependence model/block design when clustering matters."}
    decision = evaluate_decision_rule(metrics, receipt.get("decision_rule"))
    return {"observed": True, "test_state": RESULT_OBSERVED, "status": decision["status"],
            "provenance": provenance, "metrics": metrics, "monte_carlo": mc,
            "stress_scenarios": deepcopy(receipt.get("stress_scenarios", NOT_TESTED)),
            "decision": decision}


def apply_bias_guard(audit_rows: Sequence[Mapping[str, Any]], experiments: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    detected_tokens = {"FOUND", "DETECTED", "PRESENT", "FAIL", "FAILED", "INVALID", "BIAS FOUND", "LEAKAGE FOUND"}
    verified_findings = []
    unverified_findings = []
    for row in audit_rows:
        status = str(row.get("status") or "").strip().upper().replace("_", " ")
        if status not in detected_tokens:
            continue
        evidence = row.get("evidence")
        finding = {"risk": row.get("risk"), "status": status, "evidence": evidence}
        if meaningful(evidence) and evidence != UNKNOWN:
            verified_findings.append(finding)
        else:
            unverified_findings.append(finding)
    if verified_findings:
        for experiment in experiments:
            if experiment.get("hypothesis_status") in {PASS, CONDITIONAL_PASS}:
                experiment["pre_bias_guard_status"] = experiment.get("hypothesis_status")
                experiment["hypothesis_status"] = INCONCLUSIVE
                experiment["bias_guard"] = "DOWNGRADED — verified leakage/bias finding invalidates an unqualified positive verdict until clean re-test."
    return {
        "verified_findings": verified_findings,
        "unverified_findings": unverified_findings,
        "positive_verdicts_downgraded": bool(verified_findings),
        "rule": "Verified look-ahead/leakage/bias invalidates or downgrades affected positive conclusions; unverified allegations trigger investigation but do not fabricate invalidation.",
    }
