"""Trusted deterministic benchmark attestor for Scientist Society execution paths.

This module specializes software EXECUTION/REPRODUCIBILITY evidence for:
- #19 Debate Tournament
- #37 Devil's Advocate Swarm
- #39 Replication Engine

It deliberately does NOT mint INDEPENDENT evidence.  The deterministic benchmark
runs in the audited repository and proves that the software paths execute and
repeat under a frozen benchmark; it cannot prove that real external models,
humans, providers, or implementation teams were independent.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Tuple

from utils.release_identity import repository_identity

from . import scientist_society as society
from .capability_registry import ProofKind
from .maturity_attestor import _existing_adds, _outside_repo
from .maturity_auditor import (
    TrustedMaturityAudit,
    _hash_tracked_regular,
    _parse_policy,
    _read_policy_bytes,
    _tracked_index,
    audit_repository_maturity,
)
from .maturity_proof import ProofLedger


_CAPABILITY_IDS = (19, 37, 39)
_REQUIRED = (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY)
_ENGINE_SUBJECT = "research_engine/scientist_society.py"
_BENCHMARK_VERSION = "scientist-society-execution-v1"
_VERIFIERS = {
    ProofKind.EXECUTION: "trusted-execution-attestor",
    ProofKind.REPRODUCIBILITY: "trusted-reproducibility-attestor",
}
_NAMESPACES = {
    ProofKind.EXECUTION: "execution",
    ProofKind.REPRODUCIBILITY: "reproducibility",
}
_SUBJECT_SUFFIXES = {
    ProofKind.EXECUTION: "execution-run",
    ProofKind.REPRODUCIBILITY: "reproducibility-run",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _subject(capability_id: int, kind: ProofKind) -> str:
    return f"capability-{capability_id}-{_SUBJECT_SUFFIXES[kind]}"


def _reference(capability_id: int, kind: ProofKind, observation_id: str) -> str:
    return f"{_NAMESPACES[kind]}:c{capability_id}:{observation_id}"


def _safe_observation_id(value: object) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 120:
        raise ValueError("observation_id is invalid")
    if any(not (ch.isalnum() or ch in "_.@/+~-") for ch in text):
        raise ValueError("observation_id is invalid")
    return text


def _agent_runner(answer: str, evidence_id: str, confidence: float):
    def run(task: society.ResearchTask) -> Mapping[str, Any]:
        return {
            "answer": answer,
            "evidence_ids": [evidence_id],
            "confidence": confidence,
        }
    return run


def _judge(packet: Mapping[str, Any]) -> Mapping[str, Any]:
    left = packet["candidate_A"]
    right = packet["candidate_B"]
    left_score = len(tuple(left.get("evidence_ids") or ()))
    right_score = len(tuple(right.get("evidence_ids") or ()))
    if left_score > right_score:
        winner = "A"
    elif right_score > left_score:
        winner = "B"
    else:
        # Deterministic tie-break is part of this software benchmark only.
        winner = "A" if str(left["hypothesis_id"]) < str(right["hypothesis_id"]) else "B"
    return {
        "winner": winner,
        "confidence": 0.75,
        "reasons": ["frozen benchmark evidence-count rule"],
        "evidence_ids": sorted(
            set(tuple(left.get("evidence_ids") or ()) + tuple(right.get("evidence_ids") or ()))
        ),
    }


def _replica(implementation_hash: str, effect: float):
    def run(protocol: Mapping[str, Any]) -> Mapping[str, Any]:
        if protocol.get("protocol_version") != "society-replication-v1":
            raise ValueError("unexpected protocol")
        return {
            "implementation_hash": implementation_hash,
            "metrics": {"effect": effect, "n": 100.0},
        }
    return run


def run_scientist_society_benchmark() -> Mapping[str, Any]:
    """Exercise society, adversarial role, debate, and replication twice-stably."""
    task = society.ResearchTask(
        question="Which frozen candidate survives adversarial evaluation?",
        evidence=({"id": "E1"}, {"id": "E2"}, {"id": "E3"}),
        hypothesis="H1",
        expected_result="H1",
        constraints={"benchmark_version": _BENCHMARK_VERSION},
    )
    engine = society.ScientistSociety(
        [
            (
                society.AgentSpec(
                    "scientist",
                    "scientist",
                    "runner-scientist",
                    "family-a",
                    "mechanistic",
                    True,
                ),
                _agent_runner("mechanistic case for H1", "E1", 0.61),
            ),
            (
                society.AgentSpec(
                    "devil",
                    "devils_advocate",
                    "runner-devil",
                    "family-b",
                    "adversarial",
                    True,
                ),
                _agent_runner("counterexample pressure against H1", "E2", 0.58),
            ),
            (
                society.AgentSpec(
                    "skeptic",
                    "skeptic",
                    "runner-skeptic",
                    "family-c",
                    "falsification",
                    False,
                ),
                _agent_runner("independent skeptical audit", "E3", 0.64),
            ),
        ],
        minimum_independent_runners=3,
        max_workers=3,
    )
    society_run = engine.run(task)

    candidates = (
        society.TournamentCandidate("H1", "candidate one", ("E1", "E2"), "author-hidden-1"),
        society.TournamentCandidate("H2", "candidate two", ("E3",), "author-hidden-2"),
        society.TournamentCandidate("H3", "candidate three", ("E4",), "author-hidden-3"),
    )
    tournament = society.DebateTournament(_judge).run(candidates)

    replication = society.IndependentReplicationEngine(
        (
            society.ReplicaSpec(
                "replica-a", "replica-runner-a", _replica("implementation-a", 0.500)
            ),
            society.ReplicaSpec(
                "replica-b", "replica-runner-b", _replica("implementation-b", 0.505)
            ),
        )
    ).run(
        {"protocol_version": "society-replication-v1", "hypothesis_id": "H1"},
        metric_tolerances={"effect": 0.01, "n": 0.0},
    )

    successful = [row for row in society_run.outputs if row.answer and not row.error]
    roles = {row.role for row in successful}
    perspectives = {row.perspective for row in successful}
    checks = {
        "society_execution_complete": society_run.successful_agents == 3,
        "distinct_runner_structure": society_run.distinct_runner_ids == 3,
        "distinct_model_families": society_run.distinct_model_families == 3,
        "distinct_perspectives": society_run.distinct_perspectives == 3,
        "blind_packet_exercised": society_run.blind_outputs == 2,
        "devils_advocate_role_executed": (
            "devils_advocate" in roles and "adversarial" in perspectives
        ),
        "debate_completed": (
            tournament.status == "WINNER_SELECTED"
            and tournament.winner_id == "H1"
            and len(tournament.matches) == 2
            and all(len(match.judge_hash) == 64 for match in tournament.matches)
        ),
        "replication_completed": (
            replication.independently_replicated is True
            and not replication.reasons
            and len(replication.results) == 2
            and len({row.runner_id for row in replication.results}) == 2
            and len({row.implementation_hash for row in replication.results}) == 2
        ),
    }
    payload = {
        "benchmark_version": _BENCHMARK_VERSION,
        "checks": checks,
        "society": asdict(society_run),
        "tournament": asdict(tournament),
        "replication": asdict(replication),
        "software_execution_only": True,
        "external_independence_proven": False,
        "truth_proven": False,
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


@dataclass(frozen=True)
class ScientistSocietyExecutionAttestation:
    revision: str
    engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    external_independence_proven: bool = False
    truth_proven: bool = False


def _same_receipt(
    row: Mapping[str, Any],
    *,
    capability_id: int,
    kind: ProofKind,
    digest: str,
    reference: str,
    revision: str,
) -> bool:
    expected = {
        "capability_id": capability_id,
        "proof_kind": kind.value,
        "subject": _subject(capability_id, kind),
        "subject_sha256": digest,
        "verifier": _VERIFIERS[kind],
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_scientist_society_execution(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    observation_id: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> ScientistSocietyExecutionAttestation:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    observation = _safe_observation_id(observation_id)
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "").strip().lower()
    if not identity_before.get("available") or not identity_before.get("clean") or len(revision) != 40:
        raise ValueError("scientist society attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _ENGINE_SUBJECT)
    imported_engine = Path(str(society.__file__)).resolve(strict=True)
    audited_engine = (root / _ENGINE_SUBJECT).resolve(strict=True)
    if imported_engine != audited_engine:
        raise ValueError("Scientist Society runtime is not loaded from the audited repository")

    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    references = {}
    for capability_id in _CAPABILITY_IDS:
        for kind in _REQUIRED:
            subject = _subject(capability_id, kind)
            verifier = _VERIFIERS[kind]
            reference = _reference(capability_id, kind, observation)
            matching = tuple(
                rule for rule in policy.rules
                if rule.capability_id == capability_id
                and rule.proof_kind is kind
                and subject in rule.subjects
                and verifier in rule.verifiers
            )
            if not matching:
                raise ValueError(
                    f"committed proof policy has no trusted c{capability_id} {kind.value} rule"
                )
            if not any(
                not rule.reference_prefixes
                or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
                for rule in matching
            ):
                raise ValueError("generated reference is not allowed by proof policy")
            references[(capability_id, kind)] = reference

    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or len(prior) != 40:
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not continuity.verify_chain(
            anchor_token=prior_anchor_token,
            current_revision=prior,
        ):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    first = run_scientist_society_benchmark()
    second = run_scientist_society_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("scientist society benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("scientist society benchmark is not deterministic")
    if first.get("external_independence_proven") is not False:
        raise ValueError("software benchmark must not claim external independence")
    if first.get("truth_proven") is not False:
        raise ValueError("software benchmark must not claim scientific truth")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    payload_for_digest = {
        key: value for key, value in first.items()
        if key not in {"benchmark_passed", "benchmark_sha256"}
    }
    if len(benchmark_digest) != 64 or benchmark_digest != _sha(payload_for_digest):
        raise ValueError("scientist society benchmark digest verification failed")

    receipt_digest = _sha({
        "revision": revision,
        "engine_sha256": engine_digest,
        "benchmark_sha256": benchmark_digest,
        "capability_ids": _CAPABILITY_IDS,
        "proof_kinds": [kind.value for kind in _REQUIRED],
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = 0
    reused = 0
    for capability_id in _CAPABILITY_IDS:
        for kind in _REQUIRED:
            reference = references[(capability_id, kind)]
            receipt_id = (
                f"scientist-society:{revision[:12]}:c{capability_id}:{kind.value}"
            )
            previous = existing.get(receipt_id)
            if previous is not None:
                if not _same_receipt(
                    previous,
                    capability_id=capability_id,
                    kind=kind,
                    digest=receipt_digest,
                    reference=reference,
                    revision=revision,
                ):
                    raise ValueError("deterministic scientist-society receipt_id collision")
                reused += 1
                continue
            ledger.add(
                receipt_id=receipt_id,
                capability_id=capability_id,
                proof_kind=kind,
                subject=_subject(capability_id, kind),
                subject_sha256=receipt_digest,
                verifier=_VERIFIERS[kind],
                observed_at=current_time,
                reference=reference,
                implementation_revision=revision,
            )
            added += 1

    if added + reused != len(_CAPABILITY_IDS) * len(_REQUIRED):
        raise ValueError("scientist society attestation did not account for every proof route")

    anchor = ledger.create_anchor(current_revision=revision, issued_at=current_time)
    audit = audit_repository_maturity(
        repo_root=root,
        ledger_path=ledger_target,
        integrity_key=integrity_key,
        anchor_token=anchor,
        now=current_time,
        policy_path=policy_path,
    )
    if not audit.audit_valid:
        raise ValueError("trusted maturity audit rejected scientist-society attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during scientist society attestation")

    return ScientistSocietyExecutionAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        benchmark_sha256=benchmark_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
