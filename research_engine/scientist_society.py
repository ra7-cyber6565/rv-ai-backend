"""Independent scientist-society, blind analysis, debate, and replication primitives.

The old AgentManager owns one DeepResearchEngine per project. That is useful
runtime management but not evidence of a multi-agent scientific society. This
module adds an explicit orchestration boundary where independent runners receive
isolated task packets, selected runners can be blinded to expected results, a
judge can run an auditable pairwise debate tournament, and replication runners
must independently implement the same frozen protocol.

Runners are dependency-injected callables. They can be different free/local
models, deterministic statistical tools, human reviewers, or other engines.
The society does not label a run independent merely because multiple role names
exist: distinct runner identities and successful outputs are required.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple


def _hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ResearchTask:
    question: str
    evidence: Tuple[Mapping[str, Any], ...] = ()
    hypothesis: Optional[str] = None
    expected_result: Optional[str] = None
    constraints: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    role: str
    runner_id: str
    model_family: str
    perspective: str
    blind_to_expected_result: bool = False


@dataclass(frozen=True)
class AgentOutput:
    agent_id: str
    role: str
    answer: str
    evidence_ids: Tuple[str, ...]
    confidence: Optional[float]
    runner_id: str
    model_family: str
    perspective: str
    blind: bool
    output_hash: str
    error: str = ""


@dataclass(frozen=True)
class SocietyRun:
    outputs: Tuple[AgentOutput, ...]
    requested_agents: int
    successful_agents: int
    distinct_runner_ids: int
    distinct_model_families: int
    distinct_perspectives: int
    independent: bool
    blind_outputs: int


Runner = Callable[[ResearchTask], Mapping[str, Any]]


class ScientistSociety:
    def __init__(
        self,
        agents: Sequence[Tuple[AgentSpec, Runner]],
        *,
        minimum_independent_runners: int = 2,
        max_workers: int = 8,
    ):
        if len(agents) < 2:
            raise ValueError("scientist society requires at least two agents")
        ids = [spec.agent_id for spec, _ in agents]
        if len(ids) != len(set(ids)):
            raise ValueError("agent_id values must be unique")
        runner_ids = [spec.runner_id for spec, _ in agents]
        if any(not value.strip() for value in ids + runner_ids):
            raise ValueError("agent_id and runner_id are required")
        if minimum_independent_runners < 2:
            raise ValueError("minimum_independent_runners must be >= 2")
        self._agents = tuple(agents)
        self.minimum_independent_runners = minimum_independent_runners
        self.max_workers = max(1, min(int(max_workers), 32))

    @staticmethod
    def _isolated_task(task: ResearchTask, *, blind: bool) -> ResearchTask:
        return ResearchTask(
            question=str(task.question),
            evidence=tuple(copy.deepcopy(tuple(task.evidence))),
            hypothesis=copy.deepcopy(task.hypothesis),
            expected_result=None if blind else copy.deepcopy(task.expected_result),
            constraints=copy.deepcopy(dict(task.constraints)),
        )

    @staticmethod
    def _normalize_output(spec: AgentSpec, raw: Mapping[str, Any]) -> AgentOutput:
        if not isinstance(raw, Mapping):
            raise ValueError("agent runner must return a mapping")
        answer = str(raw.get("answer") or "").strip()
        if not answer:
            raise ValueError("agent output answer is empty")
        evidence_ids = tuple(sorted({str(item).strip() for item in raw.get("evidence_ids", ()) if str(item).strip()}))
        confidence = raw.get("confidence")
        if confidence is not None:
            confidence = float(confidence)
            if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
                raise ValueError("agent confidence must be in [0, 1]")
        payload = {
            "agent_id": spec.agent_id,
            "role": spec.role,
            "answer": answer,
            "evidence_ids": evidence_ids,
            "confidence": confidence,
            "runner_id": spec.runner_id,
            "model_family": spec.model_family,
            "perspective": spec.perspective,
            "blind": spec.blind_to_expected_result,
        }
        return AgentOutput(**payload, output_hash=_hash(payload))

    def run(self, task: ResearchTask) -> SocietyRun:
        if not str(task.question).strip():
            raise ValueError("question is required")
        jobs = [
            (spec, runner, self._isolated_task(task, blind=spec.blind_to_expected_result))
            for spec, runner in self._agents
        ]
        outputs: Dict[str, AgentOutput] = {}

        def execute(spec: AgentSpec, runner: Runner, packet: ResearchTask) -> AgentOutput:
            try:
                return self._normalize_output(spec, runner(packet))
            except Exception as exc:
                payload = {
                    "agent_id": spec.agent_id,
                    "role": spec.role,
                    "answer": "",
                    "evidence_ids": (),
                    "confidence": None,
                    "runner_id": spec.runner_id,
                    "model_family": spec.model_family,
                    "perspective": spec.perspective,
                    "blind": spec.blind_to_expected_result,
                    "error": f"{type(exc).__name__}: {exc}"[:1000],
                }
                return AgentOutput(**payload, output_hash=_hash(payload))

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(jobs))) as pool:
            futures = {
                pool.submit(execute, spec, runner, packet): spec.agent_id
                for spec, runner, packet in jobs
            }
            for future in as_completed(futures):
                output = future.result()
                outputs[output.agent_id] = output

        ordered = tuple(outputs[spec.agent_id] for spec, _ in self._agents)
        successful = tuple(item for item in ordered if item.answer and not item.error)
        runner_ids = {item.runner_id for item in successful}
        model_families = {item.model_family for item in successful if item.model_family.strip()}
        perspectives = {item.perspective for item in successful if item.perspective.strip()}
        independent = (
            len(successful) >= self.minimum_independent_runners
            and len(runner_ids) >= self.minimum_independent_runners
        )
        return SocietyRun(
            outputs=ordered,
            requested_agents=len(ordered),
            successful_agents=len(successful),
            distinct_runner_ids=len(runner_ids),
            distinct_model_families=len(model_families),
            distinct_perspectives=len(perspectives),
            independent=independent,
            blind_outputs=sum(1 for item in successful if item.blind),
        )


@dataclass(frozen=True)
class TournamentCandidate:
    hypothesis_id: str
    statement: str
    evidence_ids: Tuple[str, ...]
    author_agent_id: str = ""


@dataclass(frozen=True)
class DebateMatch:
    round_number: int
    left_id: str
    right_id: str
    winner_id: Optional[str]
    confidence: Optional[float]
    reasons: Tuple[str, ...]
    evidence_ids: Tuple[str, ...]
    judge_hash: str


@dataclass(frozen=True)
class TournamentResult:
    winner_id: Optional[str]
    status: str
    matches: Tuple[DebateMatch, ...]


Judge = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class DebateTournament:
    """Auditable single-elimination bracket with anonymized candidate packets."""

    def __init__(self, judge: Judge):
        self.judge = judge

    def _match(self, left: TournamentCandidate, right: TournamentCandidate, *, round_number: int) -> DebateMatch:
        packet = {
            "round": round_number,
            "candidate_A": {
                "hypothesis_id": left.hypothesis_id,
                "statement": left.statement,
                "evidence_ids": tuple(left.evidence_ids),
            },
            "candidate_B": {
                "hypothesis_id": right.hypothesis_id,
                "statement": right.statement,
                "evidence_ids": tuple(right.evidence_ids),
            },
        }
        raw = self.judge(copy.deepcopy(packet))
        if not isinstance(raw, Mapping):
            raise ValueError("judge must return a mapping")
        winner_slot = str(raw.get("winner") or "").upper()
        if winner_slot == "A":
            winner_id = left.hypothesis_id
        elif winner_slot == "B":
            winner_id = right.hypothesis_id
        elif winner_slot in {"", "TIE", "INCONCLUSIVE"}:
            winner_id = None
        else:
            raise ValueError("judge winner must be A, B, TIE or INCONCLUSIVE")
        confidence = raw.get("confidence")
        if confidence is not None:
            confidence = float(confidence)
            if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
                raise ValueError("judge confidence must be in [0,1]")
        reasons = tuple(str(item).strip() for item in raw.get("reasons", ()) if str(item).strip())
        evidence_ids = tuple(sorted({str(item).strip() for item in raw.get("evidence_ids", ()) if str(item).strip()}))
        return DebateMatch(
            round_number=round_number,
            left_id=left.hypothesis_id,
            right_id=right.hypothesis_id,
            winner_id=winner_id,
            confidence=confidence,
            reasons=reasons,
            evidence_ids=evidence_ids,
            judge_hash=_hash({"packet": packet, "result": dict(raw)}),
        )

    def run(self, candidates: Sequence[TournamentCandidate]) -> TournamentResult:
        if len(candidates) < 2:
            raise ValueError("tournament requires at least two candidates")
        ids = [item.hypothesis_id for item in candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("hypothesis_id values must be unique")
        current = list(candidates)
        matches = []
        round_number = 1
        by_id = {item.hypothesis_id: item for item in candidates}
        while len(current) > 1:
            next_round = []
            index = 0
            while index < len(current):
                left = current[index]
                if index + 1 >= len(current):
                    next_round.append(left)
                    index += 1
                    continue
                right = current[index + 1]
                match = self._match(left, right, round_number=round_number)
                matches.append(match)
                if match.winner_id is None:
                    return TournamentResult(None, "INCONCLUSIVE", tuple(matches))
                next_round.append(by_id[match.winner_id])
                index += 2
            current = next_round
            round_number += 1
        return TournamentResult(current[0].hypothesis_id, "WINNER_SELECTED", tuple(matches))


@dataclass(frozen=True)
class ReplicaSpec:
    replica_id: str
    runner_id: str
    runner: Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class ReplicaResult:
    replica_id: str
    runner_id: str
    implementation_hash: str
    result_hash: str
    metrics: Mapping[str, float]
    error: str = ""


@dataclass(frozen=True)
class ReplicationReport:
    results: Tuple[ReplicaResult, ...]
    independently_replicated: bool
    reasons: Tuple[str, ...]


class IndependentReplicationEngine:
    """Run a frozen protocol from scratch through distinct implementation runners."""

    def __init__(self, replicas: Sequence[ReplicaSpec]):
        if len(replicas) < 2:
            raise ValueError("at least two replicas are required")
        if len({item.replica_id for item in replicas}) != len(replicas):
            raise ValueError("replica_id values must be unique")
        self.replicas = tuple(replicas)

    def run(self, frozen_protocol: Mapping[str, Any], *, metric_tolerances: Mapping[str, float]) -> ReplicationReport:
        protocol = copy.deepcopy(dict(frozen_protocol))
        protocol_hash = _hash(protocol)
        results = []
        for spec in self.replicas:
            try:
                raw = spec.runner(copy.deepcopy(protocol))
                if not isinstance(raw, Mapping):
                    raise ValueError("replica runner must return a mapping")
                implementation_hash = str(raw.get("implementation_hash") or "").strip()
                if not implementation_hash:
                    raise ValueError("replica implementation_hash is required")
                metrics_raw = raw.get("metrics")
                if not isinstance(metrics_raw, Mapping) or not metrics_raw:
                    raise ValueError("replica metrics are required")
                metrics: Dict[str, float] = {}
                for name, value in metrics_raw.items():
                    number = float(value)
                    if not math.isfinite(number):
                        raise ValueError(f"metric {name} is not finite")
                    metrics[str(name)] = number
                result_payload = {
                    "protocol_hash": protocol_hash,
                    "implementation_hash": implementation_hash,
                    "metrics": metrics,
                }
                results.append(ReplicaResult(spec.replica_id, spec.runner_id, implementation_hash, _hash(result_payload), metrics))
            except Exception as exc:
                results.append(ReplicaResult(spec.replica_id, spec.runner_id, "", "", {}, f"{type(exc).__name__}: {exc}"[:1000]))

        reasons = []
        successful = [item for item in results if not item.error]
        if len(successful) < 2:
            reasons.append("fewer than two successful replicas")
        if len({item.runner_id for item in successful}) < 2:
            reasons.append("replicas do not use distinct runner identities")
        if len({item.implementation_hash for item in successful}) < 2:
            reasons.append("replicas do not have distinct implementation hashes")

        if successful:
            reference = successful[0]
            for metric, tolerance in metric_tolerances.items():
                tolerance = float(tolerance)
                if not math.isfinite(tolerance) or tolerance < 0:
                    raise ValueError(f"invalid tolerance for metric {metric}")
                if metric not in reference.metrics:
                    reasons.append(f"reference missing metric {metric}")
                    continue
                for other in successful[1:]:
                    if metric not in other.metrics:
                        reasons.append(f"{other.replica_id} missing metric {metric}")
                        continue
                    if abs(float(other.metrics[metric]) - float(reference.metrics[metric])) > tolerance:
                        reasons.append(
                            f"metric {metric} differs beyond tolerance between "
                            f"{reference.replica_id} and {other.replica_id}"
                        )
        return ReplicationReport(tuple(results), not reasons, tuple(dict.fromkeys(reasons)))
