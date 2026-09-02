"""Deterministic benchmark laboratory and controlled-improvement gate.

The lab provides software foundations for capability #91 (Automated Benchmark
Lab) and #92 (Controlled Self-Improvement).  It evaluates opaque candidate
implementations only through an injected evaluator and never edits code,
promotes a model, deploys a model, or changes production state by itself.

A benchmark suite is content-addressed and immutable by construction.  Safety
cases are first-class and any safety regression blocks promotion eligibility.
Every decision explicitly requires external/human approval and never claims
that a higher benchmark score proves truth or real-world superiority.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Sequence, Tuple


_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_MAX_CASES = 10_000
_MAX_PAYLOAD_BYTES = 1_000_000
_ALLOWED_DIRECTIONS = {"max", "min"}


def _safe_id(value: object, field: str) -> str:
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


def _canonical(value: Any) -> bytes:
    try:
        data = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("benchmark payload must be finite JSON-compatible data") from exc
    if len(data) > _MAX_PAYLOAD_BYTES:
        raise ValueError("benchmark payload exceeds size limit")
    return data


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    input_payload: Any
    expected_payload: Any
    weight: float = 1.0
    safety_critical: bool = False
    tags: Tuple[str, ...] = ()

    def normalized(self) -> "BenchmarkCase":
        case_id = _safe_id(self.case_id, "case_id")
        weight = _finite(self.weight, "weight")
        if weight <= 0:
            raise ValueError("weight must be > 0")
        _canonical(self.input_payload)
        _canonical(self.expected_payload)
        tags = tuple(sorted({_safe_id(item, "tag") for item in self.tags}))
        return BenchmarkCase(
            case_id=case_id,
            input_payload=self.input_payload,
            expected_payload=self.expected_payload,
            weight=weight,
            safety_critical=bool(self.safety_critical),
            tags=tags,
        )


@dataclass(frozen=True)
class BenchmarkSuite:
    suite_id: str
    cases: Tuple[BenchmarkCase, ...]
    suite_hash: str
    locked: bool = True


@dataclass(frozen=True)
class CaseEvaluation:
    case_id: str
    score: float
    passed: bool
    safety_critical: bool
    evaluator_hash: str
    details_hash: str


@dataclass(frozen=True)
class BenchmarkReport:
    suite_id: str
    suite_hash: str
    candidate_id: str
    implementation_hash: str
    evaluator_id: str
    total_score: float
    weighted_pass_rate: float
    safety_failures: Tuple[str, ...]
    case_results: Tuple[CaseEvaluation, ...]
    report_hash: str
    benchmark_only: bool = True
    real_world_superiority_proven: bool = False
    truth_proven: bool = False


@dataclass(frozen=True)
class ImprovementPolicy:
    primary_metric: str = "total_score"
    direction: str = "max"
    minimum_improvement: float = 0.0
    minimum_pass_rate: float = 0.0
    require_zero_safety_failures: bool = True
    require_distinct_implementation: bool = True
    require_independent_validation: bool = True

    def validated(self) -> "ImprovementPolicy":
        if self.primary_metric not in {"total_score", "weighted_pass_rate"}:
            raise ValueError("unsupported primary_metric")
        if self.direction not in _ALLOWED_DIRECTIONS:
            raise ValueError("direction must be max or min")
        improvement = _finite(self.minimum_improvement, "minimum_improvement")
        if improvement < 0:
            raise ValueError("minimum_improvement must be >= 0")
        pass_rate = _finite(self.minimum_pass_rate, "minimum_pass_rate")
        if not 0.0 <= pass_rate <= 1.0:
            raise ValueError("minimum_pass_rate must be in [0,1]")
        return self


@dataclass(frozen=True)
class ImprovementDecision:
    champion_id: str
    challenger_id: str
    eligible_for_external_approval: bool
    reasons: Tuple[str, ...]
    comparison_hash: str
    human_approval_required: bool = True
    automatic_code_change_allowed: bool = False
    automatic_deployment_allowed: bool = False
    truth_proven: bool = False


def build_locked_suite(suite_id: str, cases: Sequence[BenchmarkCase]) -> BenchmarkSuite:
    suite_id = _safe_id(suite_id, "suite_id")
    if isinstance(cases, (str, bytes, bytearray)) or not isinstance(cases, Sequence):
        raise ValueError("cases must be a finite sequence")
    if not 1 <= len(cases) <= _MAX_CASES:
        raise ValueError(f"cases must contain 1..{_MAX_CASES} items")
    normalized = tuple(case.normalized() for case in cases)
    ids = [case.case_id for case in normalized]
    if len(set(ids)) != len(ids):
        raise ValueError("case_id values must be unique")
    ordered = tuple(sorted(normalized, key=lambda item: item.case_id))
    payload = {
        "suite_id": suite_id,
        "cases": [
            {
                "case_id": case.case_id,
                "input_hash": _hash(case.input_payload),
                "expected_hash": _hash(case.expected_payload),
                "weight": case.weight,
                "safety_critical": case.safety_critical,
                "tags": case.tags,
            }
            for case in ordered
        ],
    }
    return BenchmarkSuite(
        suite_id=suite_id,
        cases=ordered,
        suite_hash=_hash(payload),
        locked=True,
    )


def verify_suite(suite: BenchmarkSuite) -> bool:
    rebuilt = build_locked_suite(suite.suite_id, suite.cases)
    return suite.locked is True and rebuilt.suite_hash == suite.suite_hash


def evaluate_candidate(
    suite: BenchmarkSuite,
    *,
    candidate_id: str,
    implementation_hash: str,
    evaluator_id: str,
    evaluator: Callable[[Any, Any], Mapping[str, Any]],
) -> BenchmarkReport:
    """Evaluate all locked cases with one explicit evaluator contract.

    Evaluator output must be a mapping containing exactly ``score``, ``passed``
    and optional ``details``.  Score is finite; ``passed`` must be a real bool.
    """
    if not verify_suite(suite):
        raise ValueError("benchmark suite integrity check failed")
    candidate_id = _safe_id(candidate_id, "candidate_id")
    evaluator_id = _safe_id(evaluator_id, "evaluator_id")
    implementation_hash = str(implementation_hash or "").strip()
    if not implementation_hash:
        raise ValueError("implementation_hash is required")
    if not callable(evaluator):
        raise ValueError("evaluator must be callable")

    results = []
    weighted_score = 0.0
    weighted_pass = 0.0
    total_weight = 0.0
    safety_failures = []
    evaluator_hash = _hash({"evaluator_id": evaluator_id})

    for case in suite.cases:
        try:
            raw = evaluator(case.input_payload, case.expected_payload)
        except Exception as exc:
            raise RuntimeError(f"benchmark evaluator failed for case {case.case_id}") from exc
        if not isinstance(raw, Mapping):
            raise ValueError(f"evaluator result for {case.case_id} must be a mapping")
        unknown = set(raw) - {"score", "passed", "details"}
        if unknown or "score" not in raw or "passed" not in raw:
            raise ValueError(f"evaluator result schema invalid for {case.case_id}")
        score = _finite(raw["score"], f"{case.case_id}.score")
        if type(raw["passed"]) is not bool:
            raise ValueError(f"{case.case_id}.passed must be boolean")
        details = raw.get("details", {})
        details_hash = _hash(details)
        passed = bool(raw["passed"])
        results.append(CaseEvaluation(
            case_id=case.case_id,
            score=score,
            passed=passed,
            safety_critical=case.safety_critical,
            evaluator_hash=evaluator_hash,
            details_hash=details_hash,
        ))
        weighted_score += score * case.weight
        weighted_pass += (1.0 if passed else 0.0) * case.weight
        total_weight += case.weight
        if case.safety_critical and not passed:
            safety_failures.append(case.case_id)

    total_score = weighted_score / total_weight
    pass_rate = weighted_pass / total_weight
    report_payload = {
        "suite_id": suite.suite_id,
        "suite_hash": suite.suite_hash,
        "candidate_id": candidate_id,
        "implementation_hash": implementation_hash,
        "evaluator_id": evaluator_id,
        "total_score": total_score,
        "weighted_pass_rate": pass_rate,
        "safety_failures": sorted(safety_failures),
        "case_results": [
            {
                "case_id": result.case_id,
                "score": result.score,
                "passed": result.passed,
                "safety_critical": result.safety_critical,
                "evaluator_hash": result.evaluator_hash,
                "details_hash": result.details_hash,
            }
            for result in results
        ],
    }
    return BenchmarkReport(
        suite_id=suite.suite_id,
        suite_hash=suite.suite_hash,
        candidate_id=candidate_id,
        implementation_hash=implementation_hash,
        evaluator_id=evaluator_id,
        total_score=total_score,
        weighted_pass_rate=pass_rate,
        safety_failures=tuple(sorted(safety_failures)),
        case_results=tuple(results),
        report_hash=_hash(report_payload),
    )


def compare_for_controlled_improvement(
    champion: BenchmarkReport,
    challenger: BenchmarkReport,
    *,
    policy: ImprovementPolicy = ImprovementPolicy(),
    independent_validation_ids: Sequence[str] = (),
) -> ImprovementDecision:
    """Decide whether a challenger may be submitted for external approval."""
    policy.validated()
    reasons = []
    if champion.suite_hash != challenger.suite_hash:
        reasons.append("benchmark_suite_mismatch")
    if champion.evaluator_id != challenger.evaluator_id:
        reasons.append("evaluator_mismatch")
    if policy.require_distinct_implementation and (
        champion.implementation_hash == challenger.implementation_hash
    ):
        reasons.append("implementation_not_distinct")
    independent = tuple(sorted({_safe_id(item, "independent_validation_id") for item in independent_validation_ids}))
    if policy.require_independent_validation and not independent:
        reasons.append("independent_validation_missing")
    if policy.require_zero_safety_failures and challenger.safety_failures:
        reasons.append("challenger_safety_failure")
    if challenger.weighted_pass_rate < policy.minimum_pass_rate:
        reasons.append("minimum_pass_rate_not_met")

    old = float(getattr(champion, policy.primary_metric))
    new = float(getattr(challenger, policy.primary_metric))
    improvement = (new - old) if policy.direction == "max" else (old - new)
    if improvement < policy.minimum_improvement:
        reasons.append("minimum_improvement_not_met")

    payload = {
        "champion_report_hash": champion.report_hash,
        "challenger_report_hash": challenger.report_hash,
        "policy": {
            "primary_metric": policy.primary_metric,
            "direction": policy.direction,
            "minimum_improvement": policy.minimum_improvement,
            "minimum_pass_rate": policy.minimum_pass_rate,
            "require_zero_safety_failures": policy.require_zero_safety_failures,
            "require_distinct_implementation": policy.require_distinct_implementation,
            "require_independent_validation": policy.require_independent_validation,
        },
        "independent_validation_ids": independent,
        "reasons": sorted(reasons),
    }
    return ImprovementDecision(
        champion_id=champion.candidate_id,
        challenger_id=challenger.candidate_id,
        eligible_for_external_approval=not reasons,
        reasons=tuple(sorted(reasons)),
        comparison_hash=_hash(payload),
    )
