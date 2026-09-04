"""Experiment, mathematical-model and evidence-readiness logic for AI-2."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from .validation_contracts import (
    INCONCLUSIVE, NOT_TESTED, RESULT_OBSERVED, TEST_PERFORMED, TEST_POSSIBLE,
    TEST_PROPOSED, TO_BE_ESTIMATED, UNKNOWN, as_list, clean_status, first,
    meaningful, source_count, test_state, text,
)


def normalize_variables(h: Mapping[str, Any]) -> List[Dict[str, Any]]:
    prediction = h.get("prediction") if isinstance(h.get("prediction"), Mapping) else {}
    experiment = h.get("experiment") if isinstance(h.get("experiment"), Mapping) else {}
    raw = first(experiment, "measured_variables", "variables",
                fallback=first(prediction, "variables", fallback=h.get("variables")))
    rows: List[Dict[str, Any]] = []
    for i, item in enumerate(as_list(raw), 1):
        if isinstance(item, Mapping):
            name = text(first(item, "name", "variable", "label"), UNKNOWN)
            symbol = text(item.get("symbol"))
            definition = text(first(item, "definition", "description"), name)
            unit = text(item.get("unit"))
            interpretation = text(item.get("interpretation"))
            symbol_metadata_complete = symbol == UNKNOWN or all(
                value != UNKNOWN for value in (definition, unit, interpretation)
            )
            rows.append({
                "name": name,
                "symbol": symbol,
                "role": text(first(item, "role", "type")),
                "unit": unit,
                "definition": definition,
                "interpretation": interpretation,
                "measurement_method": text(first(item, "measurement_method", "measurement")),
                "applicability": text(first(item, "applicability", "applies"), "APPLICABLE"),
                "symbol_metadata_complete": symbol_metadata_complete,
                "status": "EXPLICIT" if name != UNKNOWN and symbol_metadata_complete else "PARTIAL",
            })
        elif meaningful(item):
            name = text(item)
            rows.append({
                "name": name, "symbol": UNKNOWN, "role": UNKNOWN, "unit": UNKNOWN,
                "definition": name, "interpretation": UNKNOWN,
                "measurement_method": text(prediction.get("measurement_method")),
                "applicability": "APPLICABLE", "symbol_metadata_complete": True,
                "status": "PARTIAL",
            })
    return rows or [{
        "name": UNKNOWN, "symbol": UNKNOWN, "role": UNKNOWN, "unit": UNKNOWN,
        "definition": "No measurable variable explicitly supplied.",
        "interpretation": UNKNOWN, "measurement_method": UNKNOWN,
        "applicability": UNKNOWN, "symbol_metadata_complete": True, "status": "MISSING",
    }]


def _experiment_field_missing(row: Mapping[str, Any], field: str) -> bool:
    value = row.get(field)
    if field == "Variables":
        return not isinstance(value, list) or not value or all(
            not isinstance(v, Mapping) or v.get("name") == UNKNOWN for v in value
        )
    if field == "Confounders":
        return not isinstance(value, list) or not value or all(v == UNKNOWN for v in value)
    return not meaningful(value) or value == UNKNOWN


def normalize_experiment(h: Mapping[str, Any], index: int) -> Dict[str, Any]:
    prediction = h.get("prediction") if isinstance(h.get("prediction"), Mapping) else {}
    experiment = h.get("experiment") if isinstance(h.get("experiment"), Mapping) else {}
    raw_experiment_text = h.get("experiment") if isinstance(h.get("experiment"), str) else None
    state = test_state(h)
    upstream_status = clean_status(h.get("validation_status") or h.get("hypothesis_status") or h.get("status"))

    row: Dict[str, Any] = {
        "hypothesis_id": text(first(h, "id", "hypothesis_id"), f"H{index}"),
        "test_state": state,
        "hypothesis_status": INCONCLUSIVE,
        "upstream_claimed_status": upstream_status,
        "Hypothesis": text(first(h, "statement", "hypothesis", "title"), UNKNOWN),
        "Variables": normalize_variables(h),
        "Dataset/sample": text(first(experiment, "dataset_or_sample", "dataset", "sample",
                                      fallback=first(h, "dataset", "sample"))),
        "Experimental setup": text(first(experiment, "experimental_setup", "setup",
                                          fallback=first(h, "how_to_test", fallback=raw_experiment_text))),
        "Prediction": text(first(prediction, "expected_outcome", "prediction",
                                  fallback=h.get("prediction") if isinstance(h.get("prediction"), str) else None)),
        "Null hypothesis": text(first(experiment, "null_hypothesis", "null", fallback=h.get("null_hypothesis"))),
        "Metric": text(first(experiment, "statistical_metric", "metric",
                              fallback=first(h, "metric", "primary_metric"))),
        "Baseline": text(first(experiment, "control_or_baseline", "baseline", "control",
                                fallback=first(h, "baseline", "control"))),
        "Confounders": as_list(first(experiment, "confounders", fallback=h.get("confounders"))) or [UNKNOWN],
        "Falsification condition": text(first(
            experiment, "falsification_condition", "failure_threshold",
            fallback=first(prediction, "falsification_condition",
                           fallback=first(h, "falsification_condition", "falsification_test")))),
        "Replication method": text(first(experiment, "replication_method", "replication",
                                          fallback=first(h, "replication_method", "replication"))),
        "parameter_range": text(first(experiment, "parameter_range", fallback=h.get("parameter_range"))),
        "success_threshold": text(first(experiment, "success_threshold", fallback=h.get("success_threshold")), TO_BE_ESTIMATED),
        "failure_threshold": text(first(experiment, "failure_threshold", fallback=h.get("failure_threshold")), TO_BE_ESTIMATED),
        "result": text(first(h, "observed_result", "result_observed"), NOT_TESTED) if state == RESULT_OBSERVED else NOT_TESTED,
        "result_provenance": deepcopy(first(h, "result_provenance", "provenance", "test_provenance", fallback={})) if state == RESULT_OBSERVED else {},
        "statistical_validation": {
            "effect_size": NOT_TESTED, "uncertainty_interval": NOT_TESTED,
            "confidence_interval": NOT_TESTED, "bayesian_evidence": NOT_TESTED,
            "bootstrap": TEST_PROPOSED, "permutation_test": TEST_PROPOSED,
            "monte_carlo": TEST_PROPOSED, "multiple_testing_correction": TEST_PROPOSED,
            "power_analysis": TEST_PROPOSED,
        },
        "predictive_validation": {
            "training_set": "Discovery only; split TO BE ESTIMATED.",
            "validation_set": "Model/parameter selection only; split TO BE ESTIMATED.",
            "untouched_test_set": "Lock before final evaluation; never optimize on it.",
            "rolling_validation": TEST_PROPOSED, "walk_forward": TEST_PROPOSED,
            "external_replication": TEST_PROPOSED, "cross_dataset_testing": TEST_PROPOSED,
            "temporal_replication": TEST_PROPOSED, "regime_testing": TEST_PROPOSED,
        },
    }
    required = (
        "Hypothesis", "Variables", "Dataset/sample", "Experimental setup", "Prediction",
        "Null hypothesis", "Metric", "Baseline", "Confounders",
        "Falsification condition", "Replication method",
    )
    row["missing_required_fields"] = [field for field in required if _experiment_field_missing(row, field)]
    row["variable_symbol_contract_complete"] = all(
        not isinstance(v, Mapping) or v.get("symbol_metadata_complete") is not False
        for v in row["Variables"]
    )
    row["contract_complete"] = not row["missing_required_fields"] and row["variable_symbol_contract_complete"]
    if row["test_state"] == TEST_PROPOSED and row["contract_complete"]:
        row["test_state"] = TEST_POSSIBLE
    return row


def extract_math_models(hypotheses: Sequence[Mapping[str, Any]], result: Mapping[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Any] = []
    for key in ("mathematical_model", "mathematical_models", "quantitative_model", "equations", "objective_function"):
        if meaningful(result.get(key)):
            candidates += as_list(result.get(key))
    for h in hypotheses:
        for key in ("mathematical_model", "equation", "model", "objective_function", "constraints"):
            if meaningful(h.get(key)):
                candidates.append({"hypothesis_id": first(h, "id", "hypothesis_id"), key: h.get(key)})

    models: List[Dict[str, Any]] = []
    for i, item in enumerate(candidates, 1):
        if not isinstance(item, Mapping):
            models.append({
                "model_id": f"M{i}", "model_type": UNKNOWN, "expression": text(item),
                "objective": UNKNOWN, "constraints": UNKNOWN, "assumptions": [UNKNOWN],
                "parameters": {}, "symbol_metadata": [], "estimation_method": UNKNOWN,
                "identifiability": UNKNOWN, "data_linked_prediction": UNKNOWN,
                "symbol_contract_complete": False, "model_contract_complete": False,
                "requirements_status": {},
                "symbol_rule": "Every symbol requires definition, unit and interpretation; none are inferred from equation text.",
                "unknown_parameter_policy": "Unmeasured numeric parameters are TO BE ESTIMATED.",
                "status": INCONCLUSIVE,
            })
            continue

        raw = first(item, "parameters", "symbols", fallback={})
        symbols: List[Dict[str, Any]] = []
        if isinstance(raw, Mapping):
            for symbol, meta in raw.items():
                if isinstance(meta, Mapping):
                    symbols.append({
                        "symbol": str(symbol),
                        "definition": text(first(meta, "definition", "description")),
                        "unit": text(meta.get("unit")),
                        "interpretation": text(meta.get("interpretation")),
                        "value": deepcopy(meta.get("value", TO_BE_ESTIMATED)),
                    })
                else:
                    symbols.append({
                        "symbol": str(symbol), "definition": UNKNOWN, "unit": UNKNOWN,
                        "interpretation": UNKNOWN,
                        "value": deepcopy(meta) if meaningful(meta) else TO_BE_ESTIMATED,
                    })
        elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            for meta in raw:
                if isinstance(meta, Mapping):
                    symbols.append({
                        "symbol": text(first(meta, "symbol", "name")),
                        "definition": text(first(meta, "definition", "description")),
                        "unit": text(meta.get("unit")),
                        "interpretation": text(meta.get("interpretation")),
                        "value": deepcopy(meta.get("value", TO_BE_ESTIMATED)),
                    })

        symbol_complete = bool(symbols) and all(
            all(s[k] != UNKNOWN for k in ("symbol", "definition", "unit", "interpretation"))
            for s in symbols
        )
        expression = text(first(item, "equation", "expression", "model", "objective_function", "mathematical_model"))
        objective = text(first(item, "objective", "purpose", "target"))
        model_type = text(first(item, "model_type", "type", "family"))
        assumptions = as_list(first(item, "assumptions", "model_assumptions")) or [UNKNOWN]
        estimation_method = text(first(item, "estimation_method", "estimator", "parameter_estimation"))
        identifiability = text(first(item, "identifiability", "identification_strategy", "identification"))
        data_linked_prediction = text(first(item, "data_linked_prediction", "observable_prediction", "testable_prediction", "prediction"))
        constraint_keys = ("constraints", "constraint")
        constraints_declared = any(key in item for key in constraint_keys)
        if "constraints" in item:
            constraints: Any = deepcopy(item.get("constraints"))
        elif "constraint" in item:
            constraints = deepcopy(item.get("constraint"))
        else:
            constraints = UNKNOWN

        requirements_status = {
            "model_type_explicit": model_type != UNKNOWN,
            "expression_explicit": expression != UNKNOWN,
            "objective_explicit": objective != UNKNOWN,
            "constraints_explicit_or_declared_none": constraints_declared,
            "assumptions_explicit": any(value != UNKNOWN for value in assumptions),
            "symbols_defined_with_units_and_interpretation": symbol_complete,
            "estimation_method_explicit_or_not_applicable": estimation_method != UNKNOWN,
            "identifiability_explicit_or_not_applicable": identifiability != UNKNOWN,
            "data_linked_prediction_explicit": data_linked_prediction != UNKNOWN,
        }
        model_complete = all(requirements_status.values())
        models.append({
            "model_id": f"M{i}", "model_type": model_type, "expression": expression,
            "objective": objective, "constraints": constraints, "assumptions": assumptions,
            "parameters": deepcopy(raw), "symbol_metadata": symbols,
            "estimation_method": estimation_method, "identifiability": identifiability,
            "data_linked_prediction": data_linked_prediction,
            "symbol_contract_complete": symbol_complete,
            "model_contract_complete": model_complete,
            "requirements_status": requirements_status,
            "symbol_rule": "Every symbol requires definition, unit and interpretation; none are inferred from equation text.",
            "unknown_parameter_policy": "Unmeasured numeric parameters are TO BE ESTIMATED; no threshold is invented.",
            "status": TEST_POSSIBLE if model_complete else INCONCLUSIVE,
        })
    return models


def confidence_score(experiments: Sequence[Mapping[str, Any]], result: Mapping[str, Any]) -> Dict[str, Any]:
    verification = result.get("verification"); verified = False
    if isinstance(verification, Mapping):
        verified = str(verification.get("status") or "").upper() in {"VERIFIED", "PASS", "PASSED", "COMPLETE"}
        checks = verification.get("claim_checks")
        verified = verified or (isinstance(checks, Mapping) and checks.get("gate_passed") is True)
    checks: List[Tuple[str, bool]] = [
        ("structured_hypothesis_present", bool(experiments)),
        ("dataset_or_sample_explicit", any(e["Dataset/sample"] != UNKNOWN for e in experiments)),
        ("variables_explicit", any(e["Variables"] and e["Variables"][0]["name"] != UNKNOWN for e in experiments)),
        ("metric_explicit", any(e["Metric"] != UNKNOWN for e in experiments)),
        ("baseline_explicit", any(e["Baseline"] != UNKNOWN for e in experiments)),
        ("falsification_explicit", any(e["Falsification condition"] != UNKNOWN for e in experiments)),
        ("replication_explicit", any(e["Replication method"] != UNKNOWN for e in experiments)),
        ("complete_experiment_contract", any(e["contract_complete"] for e in experiments)),
        ("sources_present", source_count(result) > 0),
        ("test_performed", any(e["test_state"] in {TEST_PERFORMED, RESULT_OBSERVED} for e in experiments)),
        ("result_observed_with_provenance", any(e["test_state"] == RESULT_OBSERVED and meaningful(e.get("result_provenance")) for e in experiments)),
        ("upstream_verification_gate", verified),
    ]
    passed = sum(ok for _, ok in checks)
    return {
        "score": round(100.0 * passed / len(checks), 1),
        "meaning": "Evidence-readiness confidence only; NOT probability a hypothesis is true.",
        "formula": f"100 * passed_evidence_checks / {len(checks)}; equal-weight transparent checklist.",
        "passed_checks": passed, "total_checks": len(checks),
        "checks": [{"check": name, "passed": ok} for name, ok in checks],
    }
