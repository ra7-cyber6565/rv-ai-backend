"""Production result wiring for capability #72 Human Factors.

Only explicit task-study contracts are evaluated.  The wrapper never invents a
human study from prose/agent simulation, never generalizes a sample to a whole
population, and never upgrades result status or claims human safety truth.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Mapping, Sequence

from .human_factors import HumanFactorsRequirement, HumanStudyEvidence, audit_human_factors

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
    if "human_factors_inputs" in result:
        return result.get("human_factors_inputs")
    coverage = result.get("coverage") if isinstance(result.get("coverage"), Mapping) else {}
    return coverage.get("human_factors_inputs")


def build_human_factors_packet(result: Mapping[str, Any]) -> Dict[str, Any]:
    raw = _inputs(result)
    if raw is None:
        return {
            "ran": True,
            "status": "NO_STRUCTURED_HUMAN_FACTORS_INPUTS",
            "free_form_human_study_inference_performed": False,
            "result_status_upgraded": False,
            "agent_simulation_promoted_to_human_evidence": False,
            "population_generalization_proven": False,
            "human_safety_truth_proven": False,
            "external_certification_claimed": False,
        }
    contract = _mapping(raw, "human_factors_inputs")
    if set(contract) - {"requirements", "studies"}:
        raise ValueError("unknown human_factors_inputs keys")
    requirements = []
    for raw_row in _sequence(contract.get("requirements", ()), "requirements"):
        row = _mapping(raw_row, "human factors requirement")
        requirements.append(HumanFactorsRequirement(
            requirement_id=str(row.get("requirement_id") or ""),
            task_id=str(row.get("task_id") or ""),
            minimum_participants=row.get("minimum_participants"),
            minimum_task_success=row.get("minimum_task_success"),
            maximum_critical_error_rate=row.get("maximum_critical_error_rate"),
            maximum_adverse_event_rate=row.get("maximum_adverse_event_rate"),
            maximum_p95_completion_seconds=row.get("maximum_p95_completion_seconds"),
            maximum_p95_workload_score=row.get("maximum_p95_workload_score"),
            require_real_humans=bool(row.get("require_real_humans", True)),
            require_field_or_operational=bool(row.get("require_field_or_operational")),
            require_independent=bool(row.get("require_independent")),
            require_ethics_review=bool(row.get("require_ethics_review", True)),
            require_consent=bool(row.get("require_consent", True)),
            require_safety_review=bool(row.get("require_safety_review", True)),
        ))
    studies = []
    for raw_row in _sequence(contract.get("studies", ()), "studies"):
        row = _mapping(raw_row, "human study")
        studies.append(HumanStudyEvidence(
            study_id=str(row.get("study_id") or ""),
            requirement_id=str(row.get("requirement_id") or ""),
            task_id=str(row.get("task_id") or ""),
            environment=str(row.get("environment") or ""),
            provenance_ref=str(row.get("provenance_ref") or ""),
            participant_count=row.get("participant_count"),
            successful_tasks=row.get("successful_tasks"),
            attempted_tasks=row.get("attempted_tasks"),
            critical_errors=row.get("critical_errors"),
            adverse_events=row.get("adverse_events"),
            completion_seconds=tuple(row.get("completion_seconds") or ()),
            workload_scores=tuple(row.get("workload_scores") or ()),
            real_humans_observed=bool(row.get("real_humans_observed")),
            independent=bool(row.get("independent")),
            ethics_reviewed=bool(row.get("ethics_reviewed")),
            consent_documented=bool(row.get("consent_documented")),
            safety_reviewed=bool(row.get("safety_reviewed")),
            representative_sample_proven=bool(row.get("representative_sample_proven")),
        ))
    report = asdict(audit_human_factors(requirements=requirements, studies=studies))
    report.update({
        "ran": True,
        "status": "AUDITED",
        "free_form_human_study_inference_performed": False,
        "result_status_upgraded": False,
    })
    return report


def apply_human_factors_wiring(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    coverage = dict(data.get("coverage") or {})
    try:
        packet = build_human_factors_packet(data)
    except Exception as exc:
        packet = {
            "ran": False,
            "status": "ASSESSMENT_ERROR",
            "free_form_human_study_inference_performed": False,
            "result_status_upgraded": False,
            "agent_simulation_promoted_to_human_evidence": False,
            "population_generalization_proven": False,
            "human_safety_truth_proven": False,
            "external_certification_claimed": False,
            "error": type(exc).__name__,
        }
    coverage["human_factors"] = packet
    data["coverage"] = coverage
    return data


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from . import result_coverage_gate as result_mod
    original_enforce = result_mod.enforce

    def enforce_with_human_factors(result: Dict[str, Any]) -> Dict[str, Any]:
        return apply_human_factors_wiring(original_enforce(result))

    result_mod.enforce = enforce_with_human_factors
