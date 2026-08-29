"""Production result wiring for capability #71 Manufacturing Reality.

Only explicit manufacturing requirements/evidence are evaluated.  Passing the
software audit never claims factory execution, hardware authenticity, external
certification, or real-world manufacturability by itself.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Mapping, Sequence

from .manufacturing_reality import (
    ManufacturingEvidence,
    ManufacturingRequirement,
    audit_manufacturing_reality,
)

_INSTALLED = False


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping")
    return value


def _sequence(value: object, field: str) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > 10_000:
            raise ValueError(f"{field} exceeds runtime budget")
        return value
    raise ValueError(f"{field} must be a bounded sequence")


def _inputs(result: Mapping[str, Any]):
    if "manufacturing_reality_inputs" in result:
        return result.get("manufacturing_reality_inputs")
    coverage = result.get("coverage") if isinstance(result.get("coverage"), Mapping) else {}
    return coverage.get("manufacturing_reality_inputs")


def build_manufacturing_reality_packet(result: Mapping[str, Any]) -> Dict[str, Any]:
    raw = _inputs(result)
    if raw is None:
        return {
            "ran": True,
            "status": "NO_STRUCTURED_MANUFACTURING_INPUTS",
            "free_form_manufacturability_inference_performed": False,
            "result_status_upgraded": False,
            "simulation_promoted_to_measurement": False,
            "factory_execution_proven": False,
            "hardware_authenticity_proven": False,
            "external_certification_claimed": False,
            "manufacturability_truth_proven": False,
        }
    contract = _mapping(raw, "manufacturing_reality_inputs")
    if set(contract) - {"requirements", "evidence"}:
        raise ValueError("unknown manufacturing_reality_inputs keys")
    requirements = []
    for raw_row in _sequence(contract.get("requirements", ()), "requirements"):
        row = _mapping(raw_row, "manufacturing requirement")
        requirements.append(ManufacturingRequirement(
            requirement_id=str(row.get("requirement_id") or ""),
            requirement_kind=str(row.get("requirement_kind") or ""),
            unit=str(row.get("unit") or "unitless"),
            lower_spec=row.get("lower_spec"),
            upper_spec=row.get("upper_spec"),
            minimum_cpk=row.get("minimum_cpk"),
            minimum_yield=row.get("minimum_yield"),
            minimum_sample_size=row.get("minimum_sample_size", 1),
            require_measured=bool(row.get("require_measured", True)),
            require_hardware_observed=bool(row.get("require_hardware_observed", True)),
            require_independent=bool(row.get("require_independent")),
            require_production_environment=bool(row.get("require_production_environment")),
        ))
    evidence = []
    for raw_row in _sequence(contract.get("evidence", ()), "evidence"):
        row = _mapping(raw_row, "manufacturing evidence")
        evidence.append(ManufacturingEvidence(
            evidence_id=str(row.get("evidence_id") or ""),
            requirement_id=str(row.get("requirement_id") or ""),
            environment=str(row.get("environment") or ""),
            provenance_ref=str(row.get("provenance_ref") or ""),
            sample_size=row.get("sample_size", 1),
            measured=bool(row.get("measured")),
            hardware_observed=bool(row.get("hardware_observed")),
            independent=bool(row.get("independent")),
            reproducible=bool(row.get("reproducible")),
            mean=row.get("mean"),
            stddev=row.get("stddev"),
            accepted_count=row.get("accepted_count"),
            total_count=row.get("total_count"),
            measured_values=tuple(row.get("measured_values") or ()),
            explicit_pass=row.get("explicit_pass"),
        ))
    report = asdict(audit_manufacturing_reality(requirements=requirements, evidence=evidence))
    report.update({
        "ran": True,
        "status": "AUDITED",
        "free_form_manufacturability_inference_performed": False,
        "result_status_upgraded": False,
    })
    return report


def apply_manufacturing_reality_wiring(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    coverage = dict(data.get("coverage") or {})
    try:
        packet = build_manufacturing_reality_packet(data)
    except Exception as exc:
        packet = {
            "ran": False,
            "status": "ASSESSMENT_ERROR",
            "free_form_manufacturability_inference_performed": False,
            "result_status_upgraded": False,
            "simulation_promoted_to_measurement": False,
            "factory_execution_proven": False,
            "hardware_authenticity_proven": False,
            "external_certification_claimed": False,
            "manufacturability_truth_proven": False,
            "error": type(exc).__name__,
        }
    coverage["manufacturing_reality"] = packet
    data["coverage"] = coverage
    return data


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from . import result_coverage_gate as result_mod
    original_enforce = result_mod.enforce

    def enforce_with_manufacturing_reality(result: Dict[str, Any]) -> Dict[str, Any]:
        return apply_manufacturing_reality_wiring(original_enforce(result))

    result_mod.enforce = enforce_with_manufacturing_reality
