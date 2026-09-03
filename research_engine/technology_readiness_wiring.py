"""Production audit wiring for capability #70.

Only explicit readiness evidence receipts are evaluated.  The wrapper does not
infer maturity from prose, feature names or model confidence, and never claims
external certification.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Mapping, Sequence

from .technology_readiness import ReadinessEvidence, assess_technology_readiness

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
    if "technology_readiness_inputs" in result:
        return result.get("technology_readiness_inputs")
    coverage = result.get("coverage") if isinstance(result.get("coverage"), Mapping) else {}
    return coverage.get("technology_readiness_inputs")


def build_technology_readiness_packet(result: Mapping[str, Any]) -> Dict[str, Any]:
    raw = _inputs(result)
    if raw is None:
        return {
            "ran": True,
            "status": "NO_STRUCTURED_READINESS_INPUTS",
            "free_form_maturity_inference_performed": False,
            "result_status_upgraded": False,
            "external_certification_claimed": False,
            "truth_proven": False,
        }
    contract = _mapping(raw, "technology_readiness_inputs")
    allowed = {"technology_id", "technology_type", "target_level", "evidence"}
    unknown = sorted(set(contract) - allowed)
    if unknown:
        raise ValueError("unknown readiness input keys: " + ", ".join(unknown))
    evidence = []
    for raw_row in _sequence(contract.get("evidence", ()), "readiness evidence"):
        row = _mapping(raw_row, "readiness evidence")
        evidence.append(ReadinessEvidence(
            evidence_id=str(row.get("evidence_id") or ""),
            supports_level=row.get("supports_level"),
            evidence_kind=str(row.get("evidence_kind") or ""),
            environment=str(row.get("environment") or ""),
            provenance_ref=str(row.get("provenance_ref") or ""),
            independent=bool(row.get("independent")),
            reproducible=bool(row.get("reproducible")),
            integrated_system=bool(row.get("integrated_system")),
            hardware_observed=bool(row.get("hardware_observed")),
            safety_reviewed=bool(row.get("safety_reviewed")),
            production_observed=bool(row.get("production_observed")),
        ))
    report = asdict(assess_technology_readiness(
        technology_id=str(contract.get("technology_id") or ""),
        technology_type=str(contract.get("technology_type") or ""),
        target_level=contract.get("target_level"),
        evidence=evidence,
    ))
    report.update({
        "ran": True,
        "status": "AUDITED",
        "free_form_maturity_inference_performed": False,
        "result_status_upgraded": False,
    })
    return report


def apply_technology_readiness_wiring(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    coverage = dict(data.get("coverage") or {})
    try:
        packet = build_technology_readiness_packet(data)
    except Exception as exc:
        packet = {
            "ran": False,
            "status": "ASSESSMENT_ERROR",
            "free_form_maturity_inference_performed": False,
            "result_status_upgraded": False,
            "external_certification_claimed": False,
            "truth_proven": False,
            "error": type(exc).__name__,
        }
    coverage["technology_readiness"] = packet
    data["coverage"] = coverage
    return data


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from . import result_coverage_gate as result_mod
    original_enforce = result_mod.enforce

    def enforce_with_readiness(result: Dict[str, Any]) -> Dict[str, Any]:
        return apply_technology_readiness_wiring(original_enforce(result))

    result_mod.enforce = enforce_with_readiness
