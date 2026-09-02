"""Production result wiring for capability #69 Physical Reality Constraints.

Only explicit structured observations/constraints are evaluated.  The wrapper
never extracts physical laws from answer prose and never upgrades result status
or treats simulation/model values as real measurements.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Mapping, Sequence

from .physical_reality import PhysicalConstraint, PhysicalObservation, audit_physical_reality

_INSTALLED = False


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping")
    return value


def _sequence(value: object, field: str) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > 20_000:
            raise ValueError(f"{field} exceeds runtime budget")
        return value
    raise ValueError(f"{field} must be a bounded sequence")


def _inputs(result: Mapping[str, Any]):
    if "physical_reality_inputs" in result:
        return result.get("physical_reality_inputs")
    coverage = result.get("coverage") if isinstance(result.get("coverage"), Mapping) else {}
    return coverage.get("physical_reality_inputs")


def build_physical_reality_packet(result: Mapping[str, Any]) -> Dict[str, Any]:
    raw = _inputs(result)
    if raw is None:
        return {
            "ran": True,
            "status": "NO_STRUCTURED_PHYSICAL_REALITY_INPUTS",
            "free_form_constraint_inference_performed": False,
            "result_status_upgraded": False,
            "simulation_promoted_to_measurement": False,
            "hardware_authenticity_proven": False,
            "physical_truth_proven": False,
        }
    contract = _mapping(raw, "physical_reality_inputs")
    allowed = {"observations", "constraints"}
    if set(contract) - allowed:
        raise ValueError("unknown physical_reality_inputs keys")
    observations = []
    for raw_row in _sequence(contract.get("observations", ()), "observations"):
        row = _mapping(raw_row, "observation")
        observations.append(PhysicalObservation(
            observation_id=str(row.get("observation_id") or ""),
            variable=str(row.get("variable") or ""),
            value=row.get("value"),
            unit=str(row.get("unit") or ""),
            evidence_kind=str(row.get("evidence_kind") or ""),
            provenance_ref=str(row.get("provenance_ref") or ""),
            timestamp_seconds=row.get("timestamp_seconds"),
            independent=bool(row.get("independent")),
        ))
    constraints = []
    for raw_row in _sequence(contract.get("constraints", ()), "constraints"):
        row = _mapping(raw_row, "constraint")
        ids = tuple(str(item) for item in _sequence(row.get("observation_ids", ()), "observation_ids"))
        coefficients = row.get("coefficients")
        if coefficients is not None:
            coefficients = dict(_mapping(coefficients, "coefficients"))
        constraints.append(PhysicalConstraint(
            constraint_id=str(row.get("constraint_id") or ""),
            constraint_type=str(row.get("constraint_type") or ""),
            observation_ids=ids,
            unit=str(row.get("unit") or ""),
            coefficients=coefficients,
            lower=row.get("lower"),
            upper=row.get("upper"),
            target=row.get("target"),
            tolerance=row.get("tolerance"),
            max_abs_rate=row.get("max_abs_rate"),
            require_real_measurement=bool(row.get("require_real_measurement")),
        ))
    report = asdict(audit_physical_reality(observations=observations, constraints=constraints))
    report.update({
        "ran": True,
        "status": "AUDITED",
        "free_form_constraint_inference_performed": False,
        "result_status_upgraded": False,
    })
    return report


def apply_physical_reality_wiring(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    coverage = dict(data.get("coverage") or {})
    try:
        packet = build_physical_reality_packet(data)
    except Exception as exc:
        packet = {
            "ran": False,
            "status": "ASSESSMENT_ERROR",
            "free_form_constraint_inference_performed": False,
            "result_status_upgraded": False,
            "simulation_promoted_to_measurement": False,
            "hardware_authenticity_proven": False,
            "physical_truth_proven": False,
            "error": type(exc).__name__,
        }
    coverage["physical_reality"] = packet
    data["coverage"] = coverage
    return data


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from . import result_coverage_gate as result_mod
    original_enforce = result_mod.enforce

    def enforce_with_physical_reality(result: Dict[str, Any]) -> Dict[str, Any]:
        return apply_physical_reality_wiring(original_enforce(result))

    result_mod.enforce = enforce_with_physical_reality
