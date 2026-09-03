"""Fail-closed production wiring for capability #71 Manufacturing Reality.

The manufacturing engine accepts only an explicit structured contract. This
wrapper never translates prose into tolerances, yields, Cpk requirements,
factory observations, or evidence receipts.

A manufacturing-relevant result with no valid structured contract is surfaced
as a blocker and can only downgrade COMPLETE -> PARTIAL. A passing software
audit supports only the narrow statement that declared requirements passed
against supplied receipts; it never proves factory execution, hardware
authenticity, external certification, safety, or real-world manufacturability.
"""
from __future__ import annotations

import re
from dataclasses import asdict, fields
from typing import Any, Dict, Mapping, Sequence

from .manufacturing_reality import (
    ManufacturingEvidence,
    ManufacturingRequirement,
    audit_manufacturing_reality,
)

_INSTALLED = False
_MAX_ROWS = 10_000

_MANUFACTURING_RE = re.compile(
    r"(?:manufactur|fabricat|factory|production\s+(?:line|ready|readiness)|"
    r"mass[-\s]?produc|process\s+capabilit|\bcpk\b|tolerance\s+(?:stack|verification)|"
    r"tooling|assembly\s+line|pilot\s+production)",
    re.IGNORECASE,
)
_PHYSICAL_BUILD_RE = re.compile(
    r"(?:how\s+to\s+(?:build|make)|can\s+(?:it|this|we)\s+be\s+(?:built|made)|"
    r"kaise\s+ban(?:aye|aaye)|ban\s+sakt[ai]|bana\s+sakt[ei])",
    re.IGNORECASE,
)
_PHYSICAL_NOUN_RE = re.compile(
    r"(?:device|machine|robot|vehicle|engine|motor|sensor|hardware|prototype|"
    r"product|suit|battery|drone|aircraft|material|component|part|assembly)",
    re.IGNORECASE,
)

_REQ_FIELDS = {item.name for item in fields(ManufacturingRequirement)}
_EVID_FIELDS = {item.name for item in fields(ManufacturingEvidence)}
_REQ_REQUIRED = {"requirement_id", "requirement_kind"}
_EVID_REQUIRED = {"evidence_id", "requirement_id", "environment", "provenance_ref"}
_REQ_BOOL = {
    "require_measured", "require_hardware_observed", "require_independent",
    "require_production_environment",
}
_EVID_BOOL = {"measured", "hardware_observed", "independent", "reproducible"}


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping")
    return value


def _sequence(value: object, field: str, *, allow_empty: bool = True) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > _MAX_ROWS:
            raise ValueError(f"{field} exceeds runtime budget")
        if not allow_empty and not value:
            raise ValueError(f"{field} must not be empty")
        return value
    raise ValueError(f"{field} must be a bounded sequence")


def _strict_row(value: object, *, field: str, allowed: set[str], required: set[str]) -> Dict[str, Any]:
    row = dict(_mapping(value, field))
    unknown = sorted(set(row) - allowed)
    if unknown:
        raise ValueError(f"unknown {field} keys: " + ", ".join(unknown))
    missing = sorted(key for key in required if key not in row)
    if missing:
        raise ValueError(f"missing {field} keys: " + ", ".join(missing))
    return row


def _require_bool(row: Mapping[str, Any], key: str) -> None:
    if key in row and type(row[key]) is not bool:
        raise ValueError(f"{key} must be boolean")


def _require_int(row: Mapping[str, Any], key: str) -> None:
    if key in row and row[key] is not None and type(row[key]) is not int:
        raise ValueError(f"{key} must be an integer")


def _inputs(result: Mapping[str, Any]):
    if "manufacturing_reality_inputs" in result:
        return result.get("manufacturing_reality_inputs")
    coverage = result.get("coverage") if isinstance(result.get("coverage"), Mapping) else {}
    return coverage.get("manufacturing_reality_inputs")


def manufacturing_reality_relevant(question: object) -> bool:
    """Conservatively detect questions that actually ask physical build/production feasibility."""
    text = str(question or "").strip()
    if not text:
        return False
    if _MANUFACTURING_RE.search(text):
        return True
    return bool(_PHYSICAL_BUILD_RE.search(text) and _PHYSICAL_NOUN_RE.search(text))


def _requirements(raw: object) -> list[ManufacturingRequirement]:
    parsed: list[ManufacturingRequirement] = []
    for raw_row in _sequence(raw, "manufacturing requirements", allow_empty=False):
        row = _strict_row(
            raw_row, field="manufacturing requirement",
            allowed=_REQ_FIELDS, required=_REQ_REQUIRED,
        )
        for key in _REQ_BOOL:
            _require_bool(row, key)
        _require_int(row, "minimum_sample_size")
        parsed.append(ManufacturingRequirement(**row).normalized())
    return parsed


def _evidence(raw: object) -> list[ManufacturingEvidence]:
    parsed: list[ManufacturingEvidence] = []
    for raw_row in _sequence(raw, "manufacturing evidence"):
        row = _strict_row(
            raw_row, field="manufacturing evidence",
            allowed=_EVID_FIELDS, required=_EVID_REQUIRED,
        )
        for key in _EVID_BOOL:
            _require_bool(row, key)
        for key in ("sample_size", "accepted_count", "total_count"):
            _require_int(row, key)
        if "explicit_pass" in row and row["explicit_pass"] is not None and type(row["explicit_pass"]) is not bool:
            raise ValueError("explicit_pass must be boolean or null")
        if "measured_values" in row:
            row["measured_values"] = tuple(_sequence(row["measured_values"], "measured_values"))
        parsed.append(ManufacturingEvidence(**row).normalized())
    return parsed


def build_manufacturing_reality_packet(result: Mapping[str, Any]) -> Dict[str, Any]:
    relevant = manufacturing_reality_relevant(result.get("question"))
    raw = _inputs(result)
    common = {
        "ran": True,
        "relevance_detected": relevant,
        "free_form_manufacturability_inference_performed": False,
        "result_status_upgraded": False,
        "simulation_promoted_to_measurement": False,
        "factory_execution_proven": False,
        "hardware_authenticity_proven": False,
        "external_certification_claimed": False,
        "manufacturability_truth_proven": False,
        "supports_scoped_requirement_statement": False,
        "blocks_unqualified_manufacturability_claim": True,
    }
    if raw is None:
        return {
            **common,
            "status": "STRUCTURED_MANUFACTURING_INPUTS_REQUIRED" if relevant else "NO_STRUCTURED_MANUFACTURING_INPUTS",
            "structured_contract_present": False,
            "all_requirements_passed": None,
            "blocks_completion": relevant,
        }

    contract = _mapping(raw, "manufacturing_reality_inputs")
    unknown = sorted(set(contract) - {"requirements", "evidence"})
    if unknown:
        raise ValueError("unknown manufacturing_reality_inputs keys: " + ", ".join(unknown))
    if "requirements" not in contract or "evidence" not in contract:
        raise ValueError("manufacturing_reality_inputs requires requirements and evidence")

    requirements = _requirements(contract.get("requirements"))
    evidence = _evidence(contract.get("evidence"))
    report = audit_manufacturing_reality(requirements=requirements, evidence=evidence)
    payload = asdict(report)
    passed = bool(report.all_requirements_passed)
    payload.update({
        **common,
        "status": "AUDITED_PASS" if passed else "AUDITED_BLOCKED",
        "structured_contract_present": True,
        "requirements_audited": len(requirements),
        "evidence_rows_audited": len(evidence),
        "supports_scoped_requirement_statement": passed,
        "blocks_completion": bool(relevant and not passed),
        "blocks_unqualified_manufacturability_claim": True,
    })
    return payload


def apply_manufacturing_reality_wiring(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    coverage = dict(data.get("coverage") or {})
    relevant = manufacturing_reality_relevant(data.get("question"))
    try:
        packet = build_manufacturing_reality_packet(data)
    except Exception as exc:
        packet = {
            "ran": False,
            "status": "ASSESSMENT_ERROR",
            "relevance_detected": relevant,
            "structured_contract_present": _inputs(data) is not None,
            "free_form_manufacturability_inference_performed": False,
            "result_status_upgraded": False,
            "simulation_promoted_to_measurement": False,
            "factory_execution_proven": False,
            "hardware_authenticity_proven": False,
            "external_certification_claimed": False,
            "manufacturability_truth_proven": False,
            "supports_scoped_requirement_statement": False,
            "blocks_unqualified_manufacturability_claim": True,
            "blocks_completion": relevant,
            "error": type(exc).__name__,
        }
    coverage["manufacturing_reality"] = packet
    data["coverage"] = coverage

    # Downgrade-only: never turn a weaker result into COMPLETE.
    if packet.get("blocks_completion") and str(data.get("status") or "").upper() == "COMPLETE":
        data["status"] = "PARTIAL"
        coverage["manufacturing_reality_gate_note"] = (
            "Manufacturing Reality gate blocked COMPLETE: explicit structured "
            "requirements/evidence did not establish the declared manufacturing constraints."
        )
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
