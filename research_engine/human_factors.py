"""Evidence-driven human-factors audit engine for capability #72.

The engine evaluates explicit task-study evidence against explicit thresholds.
It never fabricates a user study from an agent simulation, never generalizes a
sample to a population, and never treats self-reported "safe/usability passed"
as measured human evidence.

Supported metrics include task success, critical-error rate, adverse-event
rate, p95 completion time, and p95 workload score.  Study provenance, real-human
observation, sample size, ethics/consent/safety review, environment, and
independence can all be required by the contract.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Sequence, Tuple

_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_ENVIRONMENTS = {"SIMULATION", "LAB", "FIELD", "OPERATIONAL"}
_MAX_STUDIES = 10_000
_MAX_SAMPLES = 1_000_000


def _id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is empty or invalid")
    return text


def _finite(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _p95(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


@dataclass(frozen=True)
class HumanFactorsRequirement:
    requirement_id: str
    task_id: str
    minimum_participants: int
    minimum_task_success: float | None = None
    maximum_critical_error_rate: float | None = None
    maximum_adverse_event_rate: float | None = None
    maximum_p95_completion_seconds: float | None = None
    maximum_p95_workload_score: float | None = None
    require_real_humans: bool = True
    require_field_or_operational: bool = False
    require_independent: bool = False
    require_ethics_review: bool = True
    require_consent: bool = True
    require_safety_review: bool = True

    def normalized(self) -> "HumanFactorsRequirement":
        if type(self.minimum_participants) is not int or not 1 <= self.minimum_participants <= _MAX_SAMPLES:
            raise ValueError("minimum_participants is invalid")

        def probability(value: float | None, field: str) -> float | None:
            if value is None:
                return None
            number = _finite(value, field)
            if not 0 <= number <= 1:
                raise ValueError(f"{field} must be in [0,1]")
            return number

        task_success = probability(self.minimum_task_success, "minimum_task_success")
        critical = probability(self.maximum_critical_error_rate, "maximum_critical_error_rate")
        adverse = probability(self.maximum_adverse_event_rate, "maximum_adverse_event_rate")
        completion = None if self.maximum_p95_completion_seconds is None else _finite(
            self.maximum_p95_completion_seconds, "maximum_p95_completion_seconds"
        )
        workload = None if self.maximum_p95_workload_score is None else _finite(
            self.maximum_p95_workload_score, "maximum_p95_workload_score"
        )
        if completion is not None and completion <= 0:
            raise ValueError("maximum_p95_completion_seconds must be > 0")
        if workload is not None and not 0 <= workload <= 100:
            raise ValueError("maximum_p95_workload_score must be in [0,100]")
        if all(value is None for value in (task_success, critical, adverse, completion, workload)):
            raise ValueError("at least one human-factors metric threshold is required")
        return HumanFactorsRequirement(
            requirement_id=_id(self.requirement_id, "requirement_id"),
            task_id=_id(self.task_id, "task_id"),
            minimum_participants=self.minimum_participants,
            minimum_task_success=task_success,
            maximum_critical_error_rate=critical,
            maximum_adverse_event_rate=adverse,
            maximum_p95_completion_seconds=completion,
            maximum_p95_workload_score=workload,
            require_real_humans=bool(self.require_real_humans),
            require_field_or_operational=bool(self.require_field_or_operational),
            require_independent=bool(self.require_independent),
            require_ethics_review=bool(self.require_ethics_review),
            require_consent=bool(self.require_consent),
            require_safety_review=bool(self.require_safety_review),
        )


@dataclass(frozen=True)
class HumanStudyEvidence:
    study_id: str
    requirement_id: str
    task_id: str
    environment: str
    provenance_ref: str
    participant_count: int
    successful_tasks: int
    attempted_tasks: int
    critical_errors: int
    adverse_events: int
    completion_seconds: Tuple[float, ...] = ()
    workload_scores: Tuple[float, ...] = ()
    real_humans_observed: bool = False
    independent: bool = False
    ethics_reviewed: bool = False
    consent_documented: bool = False
    safety_reviewed: bool = False
    representative_sample_proven: bool = False

    def normalized(self) -> "HumanStudyEvidence":
        environment = str(self.environment or "").strip().upper()
        if environment not in _ENVIRONMENTS:
            raise ValueError("environment is invalid")
        provenance = str(self.provenance_ref or "").strip()
        if not 3 <= len(provenance) <= 20_000:
            raise ValueError("provenance_ref is missing or too long")
        integer_fields = {
            "participant_count": self.participant_count,
            "successful_tasks": self.successful_tasks,
            "attempted_tasks": self.attempted_tasks,
            "critical_errors": self.critical_errors,
            "adverse_events": self.adverse_events,
        }
        if any(type(value) is not int or value < 0 for value in integer_fields.values()):
            raise ValueError("human study counts must be non-negative integers")
        if not 1 <= self.participant_count <= _MAX_SAMPLES:
            raise ValueError("participant_count is invalid")
        if self.attempted_tasks <= 0 or self.successful_tasks > self.attempted_tasks:
            raise ValueError("task success counts are invalid")
        if self.critical_errors > self.attempted_tasks or self.adverse_events > self.attempted_tasks:
            raise ValueError("error/adverse-event counts exceed attempted_tasks")
        completion = tuple(_finite(value, "completion_seconds") for value in self.completion_seconds)
        workload = tuple(_finite(value, "workload_scores") for value in self.workload_scores)
        if len(completion) > _MAX_SAMPLES or len(workload) > _MAX_SAMPLES:
            raise ValueError("human metric samples exceed bounded size")
        if any(value <= 0 for value in completion):
            raise ValueError("completion_seconds values must be > 0")
        if any(not 0 <= value <= 100 for value in workload):
            raise ValueError("workload_scores values must be in [0,100]")
        return HumanStudyEvidence(
            study_id=_id(self.study_id, "study_id"),
            requirement_id=_id(self.requirement_id, "requirement_id"),
            task_id=_id(self.task_id, "task_id"),
            environment=environment,
            provenance_ref=provenance,
            participant_count=self.participant_count,
            successful_tasks=self.successful_tasks,
            attempted_tasks=self.attempted_tasks,
            critical_errors=self.critical_errors,
            adverse_events=self.adverse_events,
            completion_seconds=completion,
            workload_scores=workload,
            real_humans_observed=bool(self.real_humans_observed),
            independent=bool(self.independent),
            ethics_reviewed=bool(self.ethics_reviewed),
            consent_documented=bool(self.consent_documented),
            safety_reviewed=bool(self.safety_reviewed),
            representative_sample_proven=bool(self.representative_sample_proven),
        )


@dataclass(frozen=True)
class HumanFactorsAudit:
    requirement_id: str
    task_id: str
    passed: bool
    blockers: Tuple[str, ...]
    study_ids: Tuple[str, ...]
    participant_count: int
    task_success_rate: float | None
    critical_error_rate: float | None
    adverse_event_rate: float | None
    p95_completion_seconds: float | None
    p95_workload_score: float | None


@dataclass(frozen=True)
class HumanFactorsReport:
    audits: Tuple[HumanFactorsAudit, ...]
    all_requirements_passed: bool
    report_sha256: str
    agent_simulation_promoted_to_human_evidence: bool = False
    population_generalization_proven: bool = False
    human_safety_truth_proven: bool = False
    external_certification_claimed: bool = False


def audit_human_factors(
    *,
    requirements: Sequence[HumanFactorsRequirement],
    studies: Sequence[HumanStudyEvidence],
) -> HumanFactorsReport:
    if isinstance(requirements, (str, bytes, bytearray)) or not isinstance(requirements, Sequence):
        raise ValueError("requirements must be a finite sequence")
    if isinstance(studies, (str, bytes, bytearray)) or not isinstance(studies, Sequence):
        raise ValueError("studies must be a finite sequence")
    if not requirements or len(requirements) > _MAX_STUDIES:
        raise ValueError("requirements must contain 1..10000 rows")
    if len(studies) > _MAX_STUDIES:
        raise ValueError("studies exceed bounded size")
    specs = tuple(item.normalized() for item in requirements)
    rows = tuple(item.normalized() for item in studies)
    if len({item.requirement_id for item in specs}) != len(specs):
        raise ValueError("requirement_id values must be unique")
    if len({item.study_id for item in rows}) != len(rows):
        raise ValueError("study_id values must be unique")
    known = {item.requirement_id for item in specs}
    if any(item.requirement_id not in known for item in rows):
        raise ValueError("study references unknown requirement_id")

    audits = []
    for spec in specs:
        matching = tuple(
            row for row in rows
            if row.requirement_id == spec.requirement_id and row.task_id == spec.task_id
        )
        blockers: list[str] = []
        if not matching:
            blockers.append("human_study_evidence_missing")
        participant_count = sum(row.participant_count for row in matching)
        if participant_count < spec.minimum_participants:
            blockers.append("participant_count_below_requirement")
        if spec.require_real_humans and (not matching or not all(row.real_humans_observed for row in matching)):
            blockers.append("real_human_observation_missing")
        if spec.require_field_or_operational and not any(row.environment in {"FIELD", "OPERATIONAL"} for row in matching):
            blockers.append("field_or_operational_study_missing")
        if spec.require_independent and not any(row.independent for row in matching):
            blockers.append("independent_study_missing")
        if spec.require_ethics_review and (not matching or not all(row.ethics_reviewed for row in matching)):
            blockers.append("ethics_review_missing")
        if spec.require_consent and (not matching or not all(row.consent_documented for row in matching)):
            blockers.append("consent_documentation_missing")
        if spec.require_safety_review and (not matching or not all(row.safety_reviewed for row in matching)):
            blockers.append("safety_review_missing")

        attempts = sum(row.attempted_tasks for row in matching)
        successes = sum(row.successful_tasks for row in matching)
        critical_errors = sum(row.critical_errors for row in matching)
        adverse_events = sum(row.adverse_events for row in matching)
        success_rate = successes / attempts if attempts else None
        critical_rate = critical_errors / attempts if attempts else None
        adverse_rate = adverse_events / attempts if attempts else None
        completion = [value for row in matching for value in row.completion_seconds]
        workload = [value for row in matching for value in row.workload_scores]
        p95_completion = _p95(completion)
        p95_workload = _p95(workload)

        if spec.minimum_task_success is not None:
            if success_rate is None or success_rate < spec.minimum_task_success:
                blockers.append("task_success_below_requirement")
        if spec.maximum_critical_error_rate is not None:
            if critical_rate is None or critical_rate > spec.maximum_critical_error_rate:
                blockers.append("critical_error_rate_above_requirement")
        if spec.maximum_adverse_event_rate is not None:
            if adverse_rate is None or adverse_rate > spec.maximum_adverse_event_rate:
                blockers.append("adverse_event_rate_above_requirement")
        if spec.maximum_p95_completion_seconds is not None:
            if p95_completion is None or p95_completion > spec.maximum_p95_completion_seconds:
                blockers.append("p95_completion_time_above_requirement")
        if spec.maximum_p95_workload_score is not None:
            if p95_workload is None or p95_workload > spec.maximum_p95_workload_score:
                blockers.append("p95_workload_above_requirement")

        audits.append(HumanFactorsAudit(
            requirement_id=spec.requirement_id,
            task_id=spec.task_id,
            passed=not blockers,
            blockers=tuple(sorted(set(blockers))),
            study_ids=tuple(sorted(row.study_id for row in matching)),
            participant_count=participant_count,
            task_success_rate=success_rate,
            critical_error_rate=critical_rate,
            adverse_event_rate=adverse_rate,
            p95_completion_seconds=p95_completion,
            p95_workload_score=p95_workload,
        ))

    payload = [asdict(item) for item in audits]
    return HumanFactorsReport(
        audits=tuple(audits),
        all_requirements_passed=all(item.passed for item in audits),
        report_sha256=_hash(payload),
    )
