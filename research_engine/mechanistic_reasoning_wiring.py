"""Production audit wiring for #101/#102 mechanistic reasoning.

Only explicit ``hypothesis.mechanistic_model`` contracts are evaluated.  Prose
is never converted into equations.  The packet is audit-only and cannot upgrade
answer status, confidence, evidence, causal truth or real-world validation.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Mapping, Sequence

from .mechanistic_reasoning import (
    audit_mechanism,
    coefficient_sensitivity,
    compare_intervention,
    mechanism_model_from_mapping,
    simulate_mechanism,
)


_INSTALLED = False
_MAX_HYPOTHESES = 100
_MAX_INTERVENTIONS = 20


def _sequence(value: object, field: str, maximum: int) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be a bounded sequence")
    if len(value) > maximum:
        raise ValueError(f"{field} exceeds bounded size")
    return value


def _hypothesis_id(row: Mapping[str, Any], index: int) -> str:
    return str(row.get("id") or row.get("hypothesis_id") or f"H{index}")[:240]


def build_mechanistic_reasoning_packet(result: Mapping[str, Any]) -> Dict[str, Any]:
    hypotheses = result.get("hypotheses") or []
    hypotheses = _sequence(hypotheses, "hypotheses", _MAX_HYPOTHESES)
    rows = []
    explicit = invalid = complete = simulated = 0

    for index, hypothesis in enumerate(hypotheses, 1):
        if not isinstance(hypothesis, Mapping):
            continue
        raw_model = hypothesis.get("mechanistic_model")
        if raw_model is None:
            continue
        explicit += 1
        hypothesis_id = _hypothesis_id(hypothesis, index)
        try:
            if not isinstance(raw_model, Mapping):
                raise ValueError("mechanistic_model must be a mapping")
            model = mechanism_model_from_mapping(raw_model)
            audit = audit_mechanism(model)
            row: Dict[str, Any] = {
                "hypothesis_id": hypothesis_id,
                "model_id": model.model_id,
                "mechanism_audit": asdict(audit),
                "simulation": None,
                "intervention_comparisons": [],
                "sensitivity": None,
                "causal_mechanism_proven": False,
                "empirical_validation_proven": False,
                "truth_proven": False,
            }
            if audit.complete:
                complete += 1
                baseline = simulate_mechanism(model)
                row["simulation"] = asdict(baseline)
                simulated += 1
                interventions = hypothesis.get("mechanistic_interventions") or []
                interventions = _sequence(
                    interventions, "mechanistic_interventions", _MAX_INTERVENTIONS
                )
                for intervention_index, intervention in enumerate(interventions, 1):
                    if not isinstance(intervention, Mapping):
                        raise ValueError(
                            f"mechanistic_intervention {intervention_index} must be a mapping"
                        )
                    comparison = compare_intervention(model, intervention)
                    row["intervention_comparisons"].append(asdict(comparison))
                if hypothesis.get("mechanistic_sensitivity") is True:
                    row["sensitivity"] = coefficient_sensitivity(model)
            rows.append(row)
        except Exception as exc:
            invalid += 1
            rows.append({
                "hypothesis_id": hypothesis_id,
                "status": "INVALID_MECHANISTIC_CONTRACT",
                "error": type(exc).__name__,
                "causal_mechanism_proven": False,
                "empirical_validation_proven": False,
                "truth_proven": False,
            })

    if explicit == 0:
        status = "NO_EXPLICIT_MECHANISTIC_MODELS"
    elif invalid:
        status = "PARTIAL_INVALID_MECHANISTIC_MODELS"
    elif complete != explicit:
        status = "INCOMPLETE_MECHANISM_REQUIREMENTS"
    else:
        status = "AUDITED_MODEL_CONSEQUENCES"

    return {
        "ran": True,
        "status": status,
        "hypotheses_seen": len(hypotheses),
        "explicit_models": explicit,
        "complete_mechanism_contracts": complete,
        "simulated_models": simulated,
        "invalid_models": invalid,
        "models": rows,
        "prose_formalization_performed": False,
        "model_execution_proves_causality": False,
        "causal_mechanism_proven": False,
        "empirical_validation_proven": False,
        "truth_proven": False,
    }


def apply_mechanistic_reasoning_wiring(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    coverage = dict(data.get("coverage") or {})
    try:
        packet = build_mechanistic_reasoning_packet(data)
    except Exception as exc:
        packet = {
            "ran": False,
            "status": "ASSESSMENT_ERROR",
            "models": [],
            "prose_formalization_performed": False,
            "model_execution_proves_causality": False,
            "causal_mechanism_proven": False,
            "empirical_validation_proven": False,
            "truth_proven": False,
            "error": type(exc).__name__,
        }
    coverage["mechanistic_reasoning"] = packet
    data["coverage"] = coverage
    return data


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from . import result_coverage_gate as result_mod

    original_enforce = result_mod.enforce

    def enforce_with_mechanistic_reasoning(result: Dict[str, Any]) -> Dict[str, Any]:
        return apply_mechanistic_reasoning_wiring(original_enforce(result))

    result_mod.enforce = enforce_with_mechanistic_reasoning
