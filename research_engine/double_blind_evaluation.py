"""Cryptographic multi-evaluator double-blind strategy evaluation (#98).

Application-level fail-closed double-blind evaluation core.

Security / epistemic boundaries:
* candidate/theory identities are absent from evaluator packets;
* blind arm IDs are HMAC pseudonyms bound to study+protocol+artifact;
* protocol, metric tolerances and evaluator instructions freeze at seal;
* at least two structurally distinct evaluators are required;
* every evaluator must score every arm before reveal;
* result cells are immutable;
* reproducibility is measured across all evaluator pairs;
* completion/blinding/agreement do NOT prove scientific truth or profitability.

This remains an application boundary: a privileged host administrator or an
artifact that reveals its own identity can defeat operational blinding.
Production use therefore still needs isolated evaluator processes/artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import re
from typing import Any, Dict, Mapping, Tuple


_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_ARMS = 32
_MAX_EVALUATORS = 16
_MAX_METRICS = 256
_MAX_RESULT_BYTES = 256 * 1024
_MAX_INSTRUCTIONS_BYTES = 128 * 1024


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _digest(value: object, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA_RE.fullmatch(text):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return text


def _number(value: object, field: str, *, non_negative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    if non_negative and result < 0.0:
        raise ValueError(f"{field} must be non-negative")
    return result


def _assignment_key(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) < 32:
        raise ValueError("assignment_key must contain at least 32 bytes")
    return value


@dataclass(frozen=True)
class BlindArmPacket:
    arm_id: str
    artifact_digest: str
    protocol_hash: str
    instructions: Mapping[str, Any]


@dataclass(frozen=True)
class EvaluatorPacket:
    study_id: str
    evaluator_id: str
    protocol_hash: str
    arms: Tuple[BlindArmPacket, ...]


@dataclass(frozen=True)
class DoubleBlindReport:
    study_id: str
    protocol_hash: str
    assignment_commitment: str
    candidates: Tuple[Mapping[str, str], ...]
    evaluators: Tuple[Mapping[str, str], ...]
    results: Tuple[Mapping[str, Any], ...]
    comparisons: Tuple[Mapping[str, Any], ...]
    execution_complete: bool
    blinding_structure_satisfied: bool
    independence_structure_satisfied: bool
    reproducibility_satisfied: bool
    truth_proven: bool
    profitability_proven: bool
    report_hash: str

    def to_dict(self) -> dict:
        return {
            "study_id": self.study_id,
            "protocol_hash": self.protocol_hash,
            "assignment_commitment": self.assignment_commitment,
            "candidates": [dict(row) for row in self.candidates],
            "evaluators": [dict(row) for row in self.evaluators],
            "results": [dict(row) for row in self.results],
            "comparisons": [dict(row) for row in self.comparisons],
            "execution_complete": self.execution_complete,
            "blinding_structure_satisfied": self.blinding_structure_satisfied,
            "independence_structure_satisfied": self.independence_structure_satisfied,
            "reproducibility_satisfied": self.reproducibility_satisfied,
            "truth_proven": self.truth_proven,
            "profitability_proven": self.profitability_proven,
            "report_hash": self.report_hash,
        }


class DoubleBlindStudy:
    """State machine for one frozen multi-arm/multi-evaluator blind study."""

    def __init__(
        self,
        *,
        study_id: str,
        protocol_hash: str,
        assignment_key: bytes,
        metric_tolerances: Mapping[str, object],
        evaluator_instructions: Mapping[str, Any],
    ) -> None:
        self.study_id = _id(study_id, "study_id")
        self.protocol_hash = _digest(protocol_hash, "protocol_hash")
        self._assignment_key = _assignment_key(assignment_key)

        if not isinstance(metric_tolerances, Mapping) or not metric_tolerances:
            raise ValueError("metric_tolerances must be a non-empty mapping")
        if len(metric_tolerances) > _MAX_METRICS:
            raise ValueError("metric_tolerances exceeds metric budget")
        tolerances: Dict[str, float] = {}
        for raw_name, raw_value in metric_tolerances.items():
            name = _id(raw_name, "metric name")
            if name in tolerances:
                raise ValueError("duplicate normalized metric name")
            tolerances[name] = _number(
                raw_value, f"metric tolerance {name}", non_negative=True
            )

        if not isinstance(evaluator_instructions, Mapping):
            raise ValueError("evaluator_instructions must be a mapping")
        instructions_bytes = _canonical(dict(evaluator_instructions))
        if len(instructions_bytes) > _MAX_INSTRUCTIONS_BYTES:
            raise ValueError("evaluator_instructions are too large")

        self._tolerances = dict(sorted(tolerances.items()))
        self._instructions = json.loads(instructions_bytes.decode("utf-8"))
        self._candidates: Dict[str, Dict[str, str]] = {}
        self._evaluators: Dict[str, Dict[str, str]] = {}
        self._results: Dict[Tuple[str, str], Dict[str, float]] = {}
        self._sealed = False
        self._revealed = False
        self._seal_hash = ""

    @property
    def assignment_commitment(self) -> str:
        return _sha(b"double-blind-assignment-key-v1\x00" + self._assignment_key)

    def _arm_id(self, candidate_id: str, artifact_digest: str) -> str:
        body = (
            b"double-blind-arm-v1\x00"
            + self.study_id.encode("utf-8")
            + b"\x00"
            + self.protocol_hash.encode("ascii")
            + b"\x00"
            + candidate_id.encode("utf-8")
            + b"\x00"
            + artifact_digest.encode("ascii")
        )
        token = hmac.new(self._assignment_key, body, hashlib.sha256).hexdigest()
        return f"arm_{token[:32]}"

    def register_candidate(
        self,
        *,
        candidate_id: str,
        artifact_digest: str,
        builder_theory: str,
    ) -> str:
        if self._sealed:
            raise ValueError("study is sealed")
        cid = _id(candidate_id, "candidate_id")
        digest = _digest(artifact_digest, "artifact_digest")
        theory = str(builder_theory or "").strip()
        if not theory or len(theory) > 20_000:
            raise ValueError("builder_theory is required and bounded")
        if cid in self._candidates:
            raise ValueError("candidate_id already exists")
        if any(row["artifact_digest"] == digest for row in self._candidates.values()):
            raise ValueError("candidate artifact digests must be distinct")
        arm_id = self._arm_id(cid, digest)
        if any(row["arm_id"] == arm_id for row in self._candidates.values()):
            raise RuntimeError("blind arm collision")
        self._candidates[cid] = {
            "candidate_id": cid,
            "artifact_digest": digest,
            "builder_theory": theory,
            "arm_id": arm_id,
        }
        return arm_id

    def register_evaluator(
        self,
        *,
        evaluator_id: str,
        evaluator_family: str,
        evaluator_implementation_hash: str,
    ) -> None:
        if self._sealed:
            raise ValueError("study is sealed")
        eid = _id(evaluator_id, "evaluator_id")
        family = _id(evaluator_family, "evaluator_family")
        implementation = _digest(
            evaluator_implementation_hash, "evaluator_implementation_hash"
        )
        if eid in self._evaluators:
            raise ValueError("evaluator_id already exists")
        self._evaluators[eid] = {
            "evaluator_id": eid,
            "evaluator_family": family,
            "evaluator_implementation_hash": implementation,
        }

    def seal(self) -> str:
        if self._sealed:
            raise ValueError("study is already sealed")
        if not (2 <= len(self._candidates) <= _MAX_ARMS):
            raise ValueError("double-blind study requires 2..32 candidates")
        if not (2 <= len(self._evaluators) <= _MAX_EVALUATORS):
            raise ValueError("double-blind study requires 2..16 evaluators")

        evaluator_rows = list(self._evaluators.values())
        for field in (
            "evaluator_id",
            "evaluator_family",
            "evaluator_implementation_hash",
        ):
            if len({row[field] for row in evaluator_rows}) != len(evaluator_rows):
                raise ValueError(
                    f"{field} must be distinct across independent evaluators"
                )

        arm_rows = [
            {
                "arm_id": row["arm_id"],
                "artifact_digest": row["artifact_digest"],
            }
            for row in self._candidates.values()
        ]
        payload = {
            "study_id": self.study_id,
            "protocol_hash": self.protocol_hash,
            "assignment_commitment": self.assignment_commitment,
            "arms": sorted(arm_rows, key=lambda row: row["arm_id"]),
            "evaluators": sorted(
                (dict(row) for row in evaluator_rows),
                key=lambda row: row["evaluator_id"],
            ),
            "metric_tolerances": self._tolerances,
            "instructions_hash": _sha(_canonical(self._instructions)),
        }
        self._seal_hash = _sha(_canonical(payload))
        self._sealed = True
        return self._seal_hash

    def evaluator_packet(self, evaluator_id: str) -> EvaluatorPacket:
        if not self._sealed:
            raise ValueError("study must be sealed before evaluation")
        if self._revealed:
            raise ValueError("study identities have already been revealed")
        eid = _id(evaluator_id, "evaluator_id")
        if eid not in self._evaluators:
            raise KeyError(eid)
        arms = tuple(
            BlindArmPacket(
                arm_id=row["arm_id"],
                artifact_digest=row["artifact_digest"],
                protocol_hash=self.protocol_hash,
                instructions=json.loads(_canonical(self._instructions).decode("utf-8")),
            )
            for row in sorted(
                self._candidates.values(), key=lambda item: item["arm_id"]
            )
        )
        return EvaluatorPacket(
            study_id=self.study_id,
            evaluator_id=eid,
            protocol_hash=self.protocol_hash,
            arms=arms,
        )

    def record_result(
        self,
        *,
        evaluator_id: str,
        arm_id: str,
        metrics: Mapping[str, object],
    ) -> None:
        if not self._sealed or self._revealed:
            raise ValueError("results require a sealed unrevealed study")
        eid = _id(evaluator_id, "evaluator_id")
        arm = _id(arm_id, "arm_id")
        if eid not in self._evaluators:
            raise KeyError(eid)
        known_arms = {row["arm_id"] for row in self._candidates.values()}
        if arm not in known_arms:
            raise KeyError(arm)
        key = (eid, arm)
        if key in self._results:
            raise ValueError("blind evaluation result is immutable")
        if not isinstance(metrics, Mapping) or set(metrics) != set(self._tolerances):
            raise ValueError("result metrics must exactly match frozen metric names")
        clean = {
            name: _number(metrics[name], f"metric {name}")
            for name in sorted(self._tolerances)
        }
        if len(_canonical(clean)) > _MAX_RESULT_BYTES:
            raise ValueError("evaluation result is too large")
        self._results[key] = clean

    def completion(self) -> Mapping[str, int | bool]:
        expected = len(self._candidates) * len(self._evaluators)
        completed = len(self._results)
        return {
            "expected_results": expected,
            "completed_results": completed,
            "complete": bool(self._sealed and expected > 0 and completed == expected),
        }

    def builder_view(self) -> Mapping[str, Any]:
        state = self.completion()
        return {
            "study_id": self.study_id,
            "protocol_hash": self.protocol_hash,
            "sealed": self._sealed,
            "revealed": self._revealed,
            "candidate_count": len(self._candidates),
            "evaluator_count": len(self._evaluators),
            "completed_results": state["completed_results"],
            "expected_results": state["expected_results"],
            "results_visible": self._revealed,
        }

    def reveal(self) -> DoubleBlindReport:
        state = self.completion()
        if state["complete"] is not True:
            raise ValueError("all blind evaluator-arm results are required before reveal")
        if self._revealed:
            raise ValueError("study can only be revealed once")

        evaluator_ids = sorted(self._evaluators)
        arm_ids = sorted(row["arm_id"] for row in self._candidates.values())
        comparisons = []
        reproducible = True
        for arm_id in arm_ids:
            for metric, tolerance in sorted(self._tolerances.items()):
                for left_index, left_id in enumerate(evaluator_ids):
                    for right_id in evaluator_ids[left_index + 1 :]:
                        left = self._results[(left_id, arm_id)][metric]
                        right = self._results[(right_id, arm_id)][metric]
                        delta = abs(left - right)
                        passed = delta <= tolerance or math.isclose(
                            delta,
                            tolerance,
                            rel_tol=1e-12,
                            abs_tol=1e-15,
                        )
                        reproducible = reproducible and passed
                        comparisons.append(
                            {
                                "arm_id": arm_id,
                                "metric": metric,
                                "left_evaluator_id": left_id,
                                "right_evaluator_id": right_id,
                                "left_value": left,
                                "right_value": right,
                                "tolerance": tolerance,
                                "absolute_delta": delta,
                                "passed": passed,
                            }
                        )

        candidate_rows = tuple(
            {
                "candidate_id": row["candidate_id"],
                "arm_id": row["arm_id"],
                "artifact_digest": row["artifact_digest"],
                "theory_hash": _sha(row["builder_theory"].encode("utf-8")),
            }
            for row in sorted(
                self._candidates.values(), key=lambda item: item["candidate_id"]
            )
        )
        evaluator_rows = tuple(
            dict(row)
            for row in sorted(
                self._evaluators.values(), key=lambda item: item["evaluator_id"]
            )
        )
        result_rows = tuple(
            {
                "evaluator_id": evaluator_id,
                "arm_id": arm_id,
                "metrics": dict(self._results[(evaluator_id, arm_id)]),
                "result_hash": _sha(
                    _canonical(
                        {
                            "evaluator_id": evaluator_id,
                            "arm_id": arm_id,
                            "metrics": self._results[(evaluator_id, arm_id)],
                            "protocol_hash": self.protocol_hash,
                            "seal_hash": self._seal_hash,
                        }
                    )
                ),
            }
            for evaluator_id in evaluator_ids
            for arm_id in arm_ids
        )
        report_payload = {
            "study_id": self.study_id,
            "protocol_hash": self.protocol_hash,
            "assignment_commitment": self.assignment_commitment,
            "candidates": candidate_rows,
            "evaluators": evaluator_rows,
            "results": result_rows,
            "comparisons": tuple(comparisons),
            "execution_complete": True,
            "blinding_structure_satisfied": True,
            "independence_structure_satisfied": True,
            "reproducibility_satisfied": bool(reproducible),
            "truth_proven": False,
            "profitability_proven": False,
        }
        report_hash = _sha(_canonical(report_payload))
        self._revealed = True
        return DoubleBlindReport(**report_payload, report_hash=report_hash)
