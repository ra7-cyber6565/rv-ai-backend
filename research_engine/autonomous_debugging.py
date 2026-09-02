"""Bounded autonomous-debugging and graceful-degradation foundation.

This module supports blueprint #75 (Graceful Degradation), #76 (Self-Healing
Research Runs) and #128 (Autonomous Debugging Scientist) without granting an AI
unbounded repository mutation.  It can classify dependency-root failures,
minimize reproducible factors, rank externally proposed patch candidates, and
validate candidates through injected test callbacks.  It never edits files,
merges code, weakens critical gates or deploys a candidate itself.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple


_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_ALLOWED_STAGE_STATUS = {"PASS", "FAIL", "SKIP", "BLOCKED"}
_ALLOWED_RISK = {"LOW", "MEDIUM", "HIGH"}
_MAX_STAGES = 10_000
_MAX_FACTORS = 1_000
_MAX_PATCHES = 1_000
_MAX_REPRODUCER_CALLS = 10_000


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is empty or invalid")
    return text


def _text(value: object, field: str, *, maximum: int = 20_000) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum:
        raise ValueError(f"{field} is empty or too long")
    return text


def _finite(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("debugging payload must be finite JSON-compatible data") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class StageObservation:
    stage_id: str
    status: str
    dependency_ids: Tuple[str, ...] = ()
    error_class: Optional[str] = None
    error_fingerprint: Optional[str] = None
    critical: bool = True

    def normalized(self) -> "StageObservation":
        stage_id = _safe_id(self.stage_id, "stage_id")
        status = str(self.status or "").strip().upper()
        if status not in _ALLOWED_STAGE_STATUS:
            raise ValueError("unsupported stage status")
        dependencies = tuple(sorted({_safe_id(item, "dependency_id") for item in self.dependency_ids}))
        if stage_id in dependencies:
            raise ValueError("stage cannot depend on itself")
        error_class = None if self.error_class is None else _safe_id(self.error_class, "error_class")
        error_fingerprint = (
            None if self.error_fingerprint is None else _safe_id(self.error_fingerprint, "error_fingerprint")
        )
        if status == "FAIL" and not error_class:
            raise ValueError("failed stage requires error_class")
        if status != "FAIL" and (error_class or error_fingerprint):
            raise ValueError("non-failed stage cannot carry failure fields")
        return StageObservation(
            stage_id=stage_id,
            status=status,
            dependency_ids=dependencies,
            error_class=error_class,
            error_fingerprint=error_fingerprint,
            critical=bool(self.critical),
        )


@dataclass(frozen=True)
class FailureDiagnosis:
    root_failure_ids: Tuple[str, ...]
    downstream_failure_ids: Tuple[str, ...]
    blocked_by_ids: Mapping[str, Tuple[str, ...]]
    diagnosis_hash: str
    root_cause_proven: bool = False


@dataclass(frozen=True)
class FailureFactor:
    factor_id: str
    payload_hash: str

    @classmethod
    def from_payload(cls, factor_id: str, payload: Any) -> "FailureFactor":
        return cls(_safe_id(factor_id, "factor_id"), _hash(payload))


@dataclass(frozen=True)
class MinimizationReport:
    minimal_factor_ids: Tuple[str, ...]
    calls_used: int
    reproduced: bool
    one_minimal: bool
    report_hash: str
    causal_root_proven: bool = False


@dataclass(frozen=True)
class PatchCandidate:
    candidate_id: str
    description: str
    patch_hash: str
    affected_components: Tuple[str, ...]
    risk: str = "MEDIUM"

    def normalized(self) -> "PatchCandidate":
        risk = str(self.risk or "").strip().upper()
        if risk not in _ALLOWED_RISK:
            raise ValueError("unsupported patch risk")
        components = tuple(sorted({_safe_id(item, "affected_component") for item in self.affected_components}))
        if not components:
            raise ValueError("patch candidate requires affected_components")
        patch_hash = str(self.patch_hash or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", patch_hash):
            raise ValueError("patch_hash must be a SHA-256 hex digest")
        return PatchCandidate(
            candidate_id=_safe_id(self.candidate_id, "candidate_id"),
            description=_text(self.description, "patch description"),
            patch_hash=patch_hash,
            affected_components=components,
            risk=risk,
        )


@dataclass(frozen=True)
class PatchValidation:
    candidate_id: str
    original_failure_fixed: bool
    regression_suite_passed: bool
    safety_suite_passed: bool
    reproducibility_check_passed: bool
    metrics: Mapping[str, float]
    result_hash: str
    eligible_for_external_approval: bool
    rejection_reasons: Tuple[str, ...]
    automatic_apply_allowed: bool = False
    automatic_merge_allowed: bool = False
    automatic_deploy_allowed: bool = False


@dataclass(frozen=True)
class DegradationPlan:
    executable_stage_ids: Tuple[str, ...]
    skipped_optional_stage_ids: Tuple[str, ...]
    blocked_critical_stage_ids: Tuple[str, ...]
    plan_hash: str
    hard_gates_weakened: bool = False


def diagnose_stage_failures(stages: Sequence[StageObservation]) -> FailureDiagnosis:
    if isinstance(stages, (str, bytes, bytearray)) or not isinstance(stages, Sequence):
        raise ValueError("stages must be a finite sequence")
    if not 1 <= len(stages) <= _MAX_STAGES:
        raise ValueError(f"stages must contain 1..{_MAX_STAGES} items")
    normalized = tuple(item.normalized() for item in stages)
    by_id = {item.stage_id: item for item in normalized}
    if len(by_id) != len(normalized):
        raise ValueError("stage_id values must be unique")
    for item in normalized:
        unknown = set(item.dependency_ids) - set(by_id)
        if unknown:
            raise ValueError(f"stage {item.stage_id} has unknown dependencies")

    failed = {item.stage_id for item in normalized if item.status == "FAIL"}
    root = []
    downstream = []
    blocked_by: Dict[str, Tuple[str, ...]] = {}
    for item in normalized:
        failed_deps = tuple(sorted(set(item.dependency_ids) & failed))
        if item.status == "FAIL":
            if failed_deps:
                downstream.append(item.stage_id)
                blocked_by[item.stage_id] = failed_deps
            else:
                root.append(item.stage_id)
        elif item.status == "BLOCKED":
            blockers = tuple(sorted(dep for dep in item.dependency_ids if by_id[dep].status in {"FAIL", "BLOCKED"}))
            if blockers:
                blocked_by[item.stage_id] = blockers

    payload = {
        "root_failure_ids": sorted(root),
        "downstream_failure_ids": sorted(downstream),
        "blocked_by_ids": {key: blocked_by[key] for key in sorted(blocked_by)},
        "observations": [
            {
                "stage_id": item.stage_id,
                "status": item.status,
                "dependencies": item.dependency_ids,
                "error_class": item.error_class,
                "error_fingerprint": item.error_fingerprint,
                "critical": item.critical,
            }
            for item in sorted(normalized, key=lambda row: row.stage_id)
        ],
    }
    return FailureDiagnosis(
        root_failure_ids=tuple(sorted(root)),
        downstream_failure_ids=tuple(sorted(downstream)),
        blocked_by_ids={key: blocked_by[key] for key in sorted(blocked_by)},
        diagnosis_hash=_hash(payload),
        root_cause_proven=False,
    )


def minimize_reproducing_factors(
    factors: Sequence[FailureFactor],
    reproducer: Callable[[Tuple[FailureFactor, ...]], bool],
    *,
    max_calls: int = 1_000,
) -> MinimizationReport:
    """Deterministic 1-minimal reduction of factors that reproduce a failure."""
    if isinstance(factors, (str, bytes, bytearray)) or not isinstance(factors, Sequence):
        raise ValueError("factors must be a finite sequence")
    if not 1 <= len(factors) <= _MAX_FACTORS:
        raise ValueError(f"factors must contain 1..{_MAX_FACTORS} items")
    if not callable(reproducer):
        raise ValueError("reproducer must be callable")
    if type(max_calls) is not int or not 1 <= max_calls <= _MAX_REPRODUCER_CALLS:
        raise ValueError("max_calls is outside allowed range")
    ordered = tuple(sorted(factors, key=lambda item: item.factor_id))
    if len({item.factor_id for item in ordered}) != len(ordered):
        raise ValueError("factor_id values must be unique")

    calls = 1
    if not bool(reproducer(ordered)):
        payload = {"factors": [item.factor_id for item in ordered], "calls": calls, "reproduced": False}
        return MinimizationReport((), calls, False, False, _hash(payload), False)

    current = list(ordered)
    changed = True
    while changed:
        changed = False
        for factor in tuple(current):
            if calls >= max_calls:
                payload = {
                    "minimal_factor_ids": sorted(item.factor_id for item in current),
                    "calls_used": calls,
                    "reproduced": True,
                    "one_minimal": False,
                    "budget_exhausted": True,
                }
                return MinimizationReport(
                    tuple(sorted(item.factor_id for item in current)), calls, True, False, _hash(payload), False
                )
            trial = tuple(item for item in current if item.factor_id != factor.factor_id)
            calls += 1
            if trial and bool(reproducer(trial)):
                current = list(trial)
                changed = True
                break

    ids = tuple(sorted(item.factor_id for item in current))
    payload = {"minimal_factor_ids": ids, "calls_used": calls, "reproduced": True, "one_minimal": True}
    return MinimizationReport(ids, calls, True, True, _hash(payload), False)


def validate_patch_candidates(
    candidates: Sequence[PatchCandidate],
    validator: Callable[[PatchCandidate], Mapping[str, Any]],
) -> Tuple[PatchValidation, ...]:
    """Validate externally generated candidates; never applies them."""
    if isinstance(candidates, (str, bytes, bytearray)) or not isinstance(candidates, Sequence):
        raise ValueError("candidates must be a finite sequence")
    if not 1 <= len(candidates) <= _MAX_PATCHES:
        raise ValueError(f"candidates must contain 1..{_MAX_PATCHES} items")
    if not callable(validator):
        raise ValueError("validator must be callable")
    normalized = tuple(item.normalized() for item in candidates)
    if len({item.candidate_id for item in normalized}) != len(normalized):
        raise ValueError("candidate_id values must be unique")

    results = []
    for candidate in sorted(normalized, key=lambda item: item.candidate_id):
        try:
            raw = validator(candidate)
        except Exception as exc:
            raise RuntimeError(f"patch validator failed for candidate {candidate.candidate_id}") from exc
        required = {
            "original_failure_fixed",
            "regression_suite_passed",
            "safety_suite_passed",
            "reproducibility_check_passed",
            "metrics",
        }
        if not isinstance(raw, Mapping) or set(raw) != required:
            raise ValueError(f"patch validation schema invalid for {candidate.candidate_id}")
        bools = {}
        for field in required - {"metrics"}:
            if type(raw[field]) is not bool:
                raise ValueError(f"{candidate.candidate_id}.{field} must be boolean")
            bools[field] = bool(raw[field])
        if not isinstance(raw["metrics"], Mapping):
            raise ValueError(f"{candidate.candidate_id}.metrics must be a mapping")
        metrics = {
            _safe_id(name, "metric"): _finite(value, f"metrics[{name}]")
            for name, value in raw["metrics"].items()
        }
        reasons = []
        if not bools["original_failure_fixed"]:
            reasons.append("original_failure_not_fixed")
        if not bools["regression_suite_passed"]:
            reasons.append("regression_suite_failed")
        if not bools["safety_suite_passed"]:
            reasons.append("safety_suite_failed")
        if not bools["reproducibility_check_passed"]:
            reasons.append("reproducibility_check_failed")
        if candidate.risk == "HIGH":
            reasons.append("high_risk_patch_requires_manual_redesign")

        payload = {
            "candidate_id": candidate.candidate_id,
            "patch_hash": candidate.patch_hash,
            "risk": candidate.risk,
            **bools,
            "metrics": dict(sorted(metrics.items())),
            "rejection_reasons": sorted(reasons),
        }
        results.append(PatchValidation(
            candidate_id=candidate.candidate_id,
            original_failure_fixed=bools["original_failure_fixed"],
            regression_suite_passed=bools["regression_suite_passed"],
            safety_suite_passed=bools["safety_suite_passed"],
            reproducibility_check_passed=bools["reproducibility_check_passed"],
            metrics=dict(sorted(metrics.items())),
            result_hash=_hash(payload),
            eligible_for_external_approval=not reasons,
            rejection_reasons=tuple(sorted(reasons)),
            automatic_apply_allowed=False,
            automatic_merge_allowed=False,
            automatic_deploy_allowed=False,
        ))
    return tuple(results)


def plan_graceful_degradation(stages: Sequence[StageObservation]) -> DegradationPlan:
    """Skip only optional stages whose failed dependencies make them unsafe.

    Critical failures are surfaced as blockers and never silently bypassed.
    """
    diagnosis = diagnose_stage_failures(stages)
    normalized = tuple(item.normalized() for item in stages)
    by_id = {item.stage_id: item for item in normalized}
    executable = []
    skipped_optional = []
    blocked_critical = []
    unavailable = {
        item.stage_id for item in normalized if item.status in {"FAIL", "BLOCKED"}
    }
    for item in sorted(normalized, key=lambda row: row.stage_id):
        dependency_unavailable = any(dep in unavailable for dep in item.dependency_ids)
        if item.status == "PASS" and not dependency_unavailable:
            executable.append(item.stage_id)
            continue
        if item.critical:
            blocked_critical.append(item.stage_id)
        else:
            skipped_optional.append(item.stage_id)

    payload = {
        "diagnosis_hash": diagnosis.diagnosis_hash,
        "executable_stage_ids": executable,
        "skipped_optional_stage_ids": skipped_optional,
        "blocked_critical_stage_ids": blocked_critical,
        "hard_gates_weakened": False,
    }
    return DegradationPlan(
        executable_stage_ids=tuple(executable),
        skipped_optional_stage_ids=tuple(skipped_optional),
        blocked_critical_stage_ids=tuple(blocked_critical),
        plan_hash=_hash(payload),
        hard_gates_weakened=False,
    )
