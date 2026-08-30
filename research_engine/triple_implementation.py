"""Strict triple-implementation agreement gate for capability #40.

This module is intentionally stricter than ordinary two-run replication. A
"triple implementation" result requires exactly three pre-committed execution
paths with distinct runner identities, implementation families and SHA-256 code
digests. All three receive the same frozen protocol independently, each path is
executed twice to reject internally non-reproducible implementations, and every
required metric is compared across all three pairs.

Agreement is evidence of cross-implementation reproducibility, not proof that
the underlying scientific claim is true. The pre-committed code digests are
identifiers supplied by a trusted caller/auditor; this module does not itself
prove that a digest belongs to a particular repository file.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Callable, Dict, Mapping, Sequence, Tuple


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
Runner = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _required_text(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    if len(text) > 200:
        raise ValueError(f"{field} is too long")
    return text


@dataclass(frozen=True)
class TripleImplementationSpec:
    implementation_id: str
    runner_id: str
    implementation_family: str
    code_digest: str
    runner: Runner


@dataclass(frozen=True)
class TripleImplementationResult:
    implementation_id: str
    runner_id: str
    implementation_family: str
    code_digest: str
    protocol_hash: str
    metrics: Mapping[str, float]
    result_hash: str
    error: str = ""


@dataclass(frozen=True)
class PairwiseMetricCheck:
    left_id: str
    right_id: str
    metric: str
    left_value: float
    right_value: float
    tolerance: float
    absolute_delta: float
    passed: bool


@dataclass(frozen=True)
class TripleImplementationReport:
    protocol_hash: str
    manifest_hash: str
    results: Tuple[TripleImplementationResult, ...]
    comparisons: Tuple[PairwiseMetricCheck, ...]
    triple_confirmed: bool
    execution_complete: bool
    independence_structure_satisfied: bool
    truth_proven: bool
    agreement_is_not_truth: bool
    reasons: Tuple[str, ...]
    report_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol_hash": self.protocol_hash,
            "manifest_hash": self.manifest_hash,
            "results": [
                {
                    "implementation_id": item.implementation_id,
                    "runner_id": item.runner_id,
                    "implementation_family": item.implementation_family,
                    "code_digest": item.code_digest,
                    "protocol_hash": item.protocol_hash,
                    "metrics": dict(item.metrics),
                    "result_hash": item.result_hash,
                    "error": item.error,
                }
                for item in self.results
            ],
            "comparisons": [
                {
                    "left_id": item.left_id,
                    "right_id": item.right_id,
                    "metric": item.metric,
                    "left_value": item.left_value,
                    "right_value": item.right_value,
                    "tolerance": item.tolerance,
                    "absolute_delta": item.absolute_delta,
                    "passed": item.passed,
                }
                for item in self.comparisons
            ],
            "triple_confirmed": self.triple_confirmed,
            "execution_complete": self.execution_complete,
            "independence_structure_satisfied": self.independence_structure_satisfied,
            "truth_proven": self.truth_proven,
            "agreement_is_not_truth": self.agreement_is_not_truth,
            "reasons": list(self.reasons),
            "report_hash": self.report_hash,
        }


class TripleImplementationEngine:
    """Require all three pre-committed implementations to execute and agree."""

    def __init__(self, implementations: Sequence[TripleImplementationSpec]):
        if len(implementations) != 3:
            raise ValueError("triple implementation requires exactly three implementations")

        normalized = []
        for raw in implementations:
            implementation_id = _required_text(raw.implementation_id, "implementation_id")
            runner_id = _required_text(raw.runner_id, "runner_id")
            family = _required_text(raw.implementation_family, "implementation_family")
            digest = str(raw.code_digest or "").strip().lower()
            if not _SHA256_RE.fullmatch(digest):
                raise ValueError("code_digest must be a 64-character SHA-256 hex digest")
            if not callable(raw.runner):
                raise ValueError("runner must be callable")
            normalized.append(
                TripleImplementationSpec(
                    implementation_id=implementation_id,
                    runner_id=runner_id,
                    implementation_family=family,
                    code_digest=digest,
                    runner=raw.runner,
                )
            )

        checks = (
            ("implementation_id", [item.implementation_id for item in normalized]),
            ("runner_id", [item.runner_id for item in normalized]),
            ("implementation_family", [item.implementation_family for item in normalized]),
            ("code_digest", [item.code_digest for item in normalized]),
        )
        for field, values in checks:
            if len(set(values)) != 3:
                raise ValueError(
                    f"{field} values must be distinct across all three implementations"
                )

        self.implementations = tuple(
            sorted(normalized, key=lambda item: item.implementation_id)
        )
        self.manifest_hash = _hash([
            {
                "implementation_id": item.implementation_id,
                "runner_id": item.runner_id,
                "implementation_family": item.implementation_family,
                "code_digest": item.code_digest,
            }
            for item in self.implementations
        ])

    @staticmethod
    def _tolerances(metric_tolerances: Mapping[str, float]) -> Dict[str, float]:
        if not isinstance(metric_tolerances, Mapping) or not metric_tolerances:
            raise ValueError("metric_tolerances must be a non-empty mapping")
        normalized: Dict[str, float] = {}
        for raw_name, raw_value in metric_tolerances.items():
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise ValueError("metric names must be non-empty strings")
            name = raw_name.strip()
            if name in normalized:
                raise ValueError("metric names must be unique after normalization")
            value = float(raw_value)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"invalid tolerance for metric {name}")
            normalized[name] = value
        return dict(sorted(normalized.items()))

    @staticmethod
    def _metrics(raw: object, required: Mapping[str, float]) -> Dict[str, float]:
        if not isinstance(raw, Mapping) or not raw:
            raise ValueError("runner metrics must be a non-empty mapping")
        metrics: Dict[str, float] = {}
        for raw_name, raw_value in raw.items():
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise ValueError("metric names must be non-empty strings")
            name = raw_name.strip()
            if name in metrics:
                raise ValueError("metric names must be unique after normalization")
            value = float(raw_value)
            if not math.isfinite(value):
                raise ValueError(f"metric {name} is not finite")
            metrics[name] = value
        missing = [name for name in required if name not in metrics]
        if missing:
            raise ValueError("missing required metrics: " + ", ".join(missing))
        return dict(sorted(metrics.items()))

    @staticmethod
    def _identity_mismatch(
        spec: TripleImplementationSpec,
        raw: Mapping[str, Any],
    ) -> str:
        expected = {
            "implementation_id": spec.implementation_id,
            "runner_id": spec.runner_id,
            "implementation_family": spec.implementation_family,
            "code_digest": spec.code_digest,
        }
        for field, expected_value in expected.items():
            if field not in raw:
                continue
            actual = str(raw.get(field) or "").strip()
            if field == "code_digest":
                actual = actual.lower()
            if actual != expected_value:
                return field
        return ""

    def _execute_once(
        self,
        spec: TripleImplementationSpec,
        protocol: Mapping[str, Any],
        tolerances: Mapping[str, float],
        protocol_hash: str,
    ) -> tuple[Dict[str, float], str]:
        raw = spec.runner(copy.deepcopy(dict(protocol)))
        if not isinstance(raw, Mapping):
            raise ValueError("runner must return a mapping")
        mismatch = self._identity_mismatch(spec, raw)
        if mismatch:
            raise ValueError(
                f"runner attempted to override pre-committed {mismatch}"
            )
        metrics = self._metrics(raw.get("metrics"), tolerances)
        payload = {
            "implementation_id": spec.implementation_id,
            "runner_id": spec.runner_id,
            "implementation_family": spec.implementation_family,
            "code_digest": spec.code_digest,
            "protocol_hash": protocol_hash,
            "metrics": metrics,
        }
        return metrics, _hash(payload)

    def run(
        self,
        frozen_protocol: Mapping[str, Any],
        *,
        metric_tolerances: Mapping[str, float],
    ) -> TripleImplementationReport:
        if not isinstance(frozen_protocol, Mapping) or not frozen_protocol:
            raise ValueError("frozen_protocol must be a non-empty mapping")
        tolerances = self._tolerances(metric_tolerances)
        protocol = copy.deepcopy(dict(frozen_protocol))
        protocol_hash = _hash(protocol)

        results = []
        reasons = []
        for spec in self.implementations:
            try:
                first_metrics, first_hash = self._execute_once(
                    spec, protocol, tolerances, protocol_hash
                )
                second_metrics, second_hash = self._execute_once(
                    spec, protocol, tolerances, protocol_hash
                )
                if first_metrics != second_metrics or first_hash != second_hash:
                    raise ValueError(
                        "implementation is not reproducible across repeated execution"
                    )
                results.append(
                    TripleImplementationResult(
                        implementation_id=spec.implementation_id,
                        runner_id=spec.runner_id,
                        implementation_family=spec.implementation_family,
                        code_digest=spec.code_digest,
                        protocol_hash=protocol_hash,
                        metrics=first_metrics,
                        result_hash=first_hash,
                    )
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:1000]
                results.append(
                    TripleImplementationResult(
                        implementation_id=spec.implementation_id,
                        runner_id=spec.runner_id,
                        implementation_family=spec.implementation_family,
                        code_digest=spec.code_digest,
                        protocol_hash=protocol_hash,
                        metrics={},
                        result_hash="",
                        error=error,
                    )
                )
                reasons.append(f"{spec.implementation_id} failed: {error}")

        successful = [item for item in results if not item.error]
        comparisons = []
        for left, right in combinations(successful, 2):
            for metric, tolerance in tolerances.items():
                delta = abs(float(left.metrics[metric]) - float(right.metrics[metric]))
                passed = delta <= tolerance or math.isclose(
                    delta, tolerance, rel_tol=1e-12, abs_tol=1e-15
                )
                comparisons.append(
                    PairwiseMetricCheck(
                        left_id=left.implementation_id,
                        right_id=right.implementation_id,
                        metric=metric,
                        left_value=float(left.metrics[metric]),
                        right_value=float(right.metrics[metric]),
                        tolerance=tolerance,
                        absolute_delta=delta,
                        passed=passed,
                    )
                )
                if not passed:
                    reasons.append(
                        f"metric {metric} differs beyond tolerance between "
                        f"{left.implementation_id} and {right.implementation_id}"
                    )

        execution_complete = len(successful) == 3
        expected_comparisons = 3 * len(tolerances)
        if execution_complete and len(comparisons) != expected_comparisons:
            reasons.append("all three pairwise metric comparisons were not completed")

        reasons = list(dict.fromkeys(reasons))
        triple_confirmed = (
            execution_complete
            and len(comparisons) == expected_comparisons
            and all(item.passed for item in comparisons)
            and not reasons
        )
        report_payload = {
            "protocol_hash": protocol_hash,
            "manifest_hash": self.manifest_hash,
            "results": [
                {
                    "implementation_id": item.implementation_id,
                    "runner_id": item.runner_id,
                    "implementation_family": item.implementation_family,
                    "code_digest": item.code_digest,
                    "protocol_hash": item.protocol_hash,
                    "metrics": dict(item.metrics),
                    "result_hash": item.result_hash,
                    "error": item.error,
                }
                for item in results
            ],
            "comparisons": [
                {
                    "left_id": item.left_id,
                    "right_id": item.right_id,
                    "metric": item.metric,
                    "left_value": item.left_value,
                    "right_value": item.right_value,
                    "tolerance": item.tolerance,
                    "absolute_delta": item.absolute_delta,
                    "passed": item.passed,
                }
                for item in comparisons
            ],
            "triple_confirmed": triple_confirmed,
            "execution_complete": execution_complete,
            "independence_structure_satisfied": True,
            "truth_proven": False,
            "agreement_is_not_truth": True,
            "reasons": reasons,
        }
        return TripleImplementationReport(
            protocol_hash=protocol_hash,
            manifest_hash=self.manifest_hash,
            results=tuple(results),
            comparisons=tuple(comparisons),
            triple_confirmed=triple_confirmed,
            execution_complete=execution_complete,
            independence_structure_satisfied=True,
            truth_proven=False,
            agreement_is_not_truth=True,
            reasons=tuple(reasons),
            report_hash=_hash(report_payload),
        )
