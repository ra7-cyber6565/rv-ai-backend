"""Trusted deterministic execution attestor for hypothesis evolution.

Covers software execution/reproducibility for:
- #20 Hypothesis Evolution Engine
- #66 Evolutionary Idea Search

The benchmark executes a locked two-generation search with explicit roots,
mutations, crossovers and a deliberate near-duplicate. It verifies lineage,
budgets, graveyard preservation, deterministic hashes and the engine's explicit
truth/novelty boundaries. Proposal content is synthetic benchmark data; this
attestor does not claim scientific novelty or real-world truth.
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

from . import hypothesis_evolution as evo
from .capability_registry import ProofKind
from .maturity_attestor import _existing_adds, _outside_repo, _safe_reference
from .maturity_auditor import (
    TrustedMaturityAudit,
    _hash_tracked_regular,
    _parse_policy,
    _read_policy_bytes,
    _tracked_index,
    audit_repository_maturity,
)
from .maturity_proof import ProofLedger


_CAPABILITY_IDS = (20, 66)
_REQUIRED = (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY)
_SUBJECT = "hypothesis-evolution-benchmark"
_VERIFIER = "trusted-operator"
_ENGINE_SUBJECT = "research_engine/hypothesis_evolution.py"
_BENCHMARK_VERSION = "hypothesis-evolution-benchmark-v1"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _variant(
    hypothesis_id: str,
    statement: str,
    mechanism: str,
    *,
    generation: int,
    parents: Tuple[str, ...] = (),
    evidence: float = 0.7,
    falsifiability: float = 0.8,
    testability: float = 0.8,
    novelty: float = 0.7,
    contradiction: float = 0.1,
    complexity: float = 2.0,
    source: str = "benchmark",
) -> evo.HypothesisVariant:
    return evo.HypothesisVariant(
        hypothesis_id=hypothesis_id,
        statement=statement,
        mechanism=mechanism,
        evidence_fit=evidence,
        falsifiability=falsifiability,
        testability=testability,
        novelty_screening=novelty,
        contradiction_penalty=contradiction,
        complexity=complexity,
        generation=generation,
        parent_ids=parents,
        source=source,
    )


def _initial_population() -> Tuple[evo.HypothesisVariant, ...]:
    return (
        _variant("R1", "Signal timing predicts the locked synthetic response under regime alpha.", "A timing feature changes the benchmark response through the declared alpha channel.", generation=0, evidence=0.72),
        _variant("R2", "Context stability predicts the locked synthetic response under regime beta.", "A context feature changes the benchmark response through the declared beta channel.", generation=0, evidence=0.70),
        _variant("R3", "Interaction strength predicts the locked synthetic response under regime gamma.", "Two benchmark features interact through the declared gamma channel.", generation=0, evidence=0.68),
        _variant("R4", "Noise filtering predicts the locked synthetic response under regime delta.", "A filtering operation changes benchmark noise through the declared delta channel.", generation=0, evidence=0.66),
    )


def _proposal_factory(generation: int, population: Tuple[evo.HypothesisVariant, ...]):
    p0 = population[0].hypothesis_id
    p1 = population[1].hypothesis_id
    if generation == 1:
        prefix = "G1"
    else:
        prefix = "G2"
    strong_statement = f"{prefix} refined timing-context mechanism predicts the locked synthetic response robustly."
    strong_mechanism = f"{prefix} combines declared benchmark timing and context channels before the measured synthetic outcome."
    return (
        _variant(f"{prefix}A", strong_statement, strong_mechanism, generation=generation, parents=(p0,), evidence=0.88, falsifiability=0.92, testability=0.91, novelty=0.83, contradiction=0.04, complexity=2.2, source="mutation"),
        _variant(f"{prefix}B", f"{prefix} alternative context pathway predicts a distinct locked synthetic response pattern.", f"{prefix} routes the benchmark context feature through an alternative declared pathway.", generation=generation, parents=(p1,), evidence=0.81, falsifiability=0.90, testability=0.88, novelty=0.86, contradiction=0.06, complexity=2.0, source="mutation"),
        _variant(f"{prefix}C", f"{prefix} crossover timing and context jointly predict the locked synthetic response.", f"{prefix} combines two surviving parent mechanisms into one declared benchmark interaction.", generation=generation, parents=(p0, p1), evidence=0.84, falsifiability=0.91, testability=0.89, novelty=0.90, contradiction=0.05, complexity=2.8, source="crossover"),
        _variant(f"{prefix}DUP", strong_statement, strong_mechanism, generation=generation, parents=(p0,), evidence=0.60, falsifiability=0.70, testability=0.70, novelty=0.55, contradiction=0.15, complexity=3.5, source="duplicate-control"),
    )


def run_hypothesis_evolution_benchmark() -> Mapping[str, Any]:
    policy = evo.EvolutionPolicy(
        population_size=4,
        elite_count=2,
        duplicate_similarity=0.88,
        diversity_weight=0.18,
        complexity_weight=0.08,
        contradiction_weight=0.20,
        max_generations=3,
        max_proposals_per_generation=8,
    )
    history = evo.run_evolution(
        _initial_population(),
        _proposal_factory,
        generations=2,
        policy=policy,
    )

    over_budget_blocked = False
    try:
        evo.run_evolution(
            _initial_population(),
            lambda generation, population: tuple(
                _variant(
                    f"OVER{generation}-{index}",
                    f"Over budget synthetic proposal number {index} is intentionally rejected by policy.",
                    f"Over budget mechanism {index} exists only to exercise the hard proposal limit safely.",
                    generation=generation,
                    parents=(population[0].hypothesis_id,),
                )
                for index in range(9)
            ),
            generations=1,
            policy=policy,
        )
    except ValueError as exc:
        over_budget_blocked = "max_proposals_per_generation" in str(exc) or "proposal batch" in str(exc)

    generations = [asdict(item) for item in history]
    all_survivor_ids = [item.hypothesis_id for generation in history for item in generation.survivors]
    all_eliminated = [item for generation in history for item in generation.eliminated]
    all_scores = [score for generation in history for score in generation.scores]
    checks = {
        "two_generations_executed": len(history) == 2 and tuple(item.generation for item in history) == (1, 2),
        "population_budget_respected": all(2 <= len(item.survivors) <= policy.population_size for item in history),
        "survivor_ids_unique_per_generation": all(len({row.hypothesis_id for row in item.survivors}) == len(item.survivors) for item in history),
        "mutation_and_crossover_exercised": all(item.mutations_seen >= 2 and item.crossovers_seen >= 1 for item in history),
        "near_duplicate_preserved_in_graveyard": any("near_duplicate_of:" in item.reason for item in all_eliminated),
        "population_hashes_are_sha256": all(len(item.population_hash) == 64 for item in history),
        "truth_boundary_preserved": all(item.truth_proven is False for item in history) and all(score.truth_proven is False and score.global_novelty_proven is False for score in all_scores),
        "lineage_is_nontrivial": any(score.lineage_depth >= 1 for score in all_scores),
        "hard_proposal_budget_fails_closed": over_budget_blocked,
        "search_not_truth_claim": len(all_survivor_ids) >= 4,
    }
    payload = {
        "benchmark_version": _BENCHMARK_VERSION,
        "policy": asdict(policy),
        "checks": checks,
        "generations": generations,
        "global_novelty_proven": False,
        "scientific_truth_proven": False,
        "real_world_experiment_executed": False,
    }
    return {**payload, "benchmark_passed": all(checks.values()), "benchmark_sha256": _sha(payload)}


@dataclass(frozen=True)
class HypothesisEvolutionExecutionAttestation:
    revision: str
    engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    global_novelty_proven: bool = False
    scientific_truth_proven: bool = False
    real_world_experiment_executed: bool = False


def _same_receipt(row: Mapping[str, Any], *, capability_id: int, kind: ProofKind, digest: str, reference: str, revision: str) -> bool:
    expected = {"capability_id": capability_id, "proof_kind": kind.value, "subject": _SUBJECT, "subject_sha256": digest, "verifier": _VERIFIER, "reference": reference, "implementation_revision": revision}
    return all(row.get(key) == value for key, value in expected.items())


def attest_hypothesis_evolution_execution(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> HypothesisEvolutionExecutionAttestation:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    reference = _safe_reference(run_reference)
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "")
    if not identity_before.get("available") or not identity_before.get("clean") or not revision:
        raise ValueError("hypothesis evolution attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _ENGINE_SUBJECT)
    if Path(str(evo.__file__)).resolve(strict=True) != (root / _ENGINE_SUBJECT).resolve(strict=True):
        raise ValueError("hypothesis evolution runtime is not loaded from the audited repository")

    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    for capability_id in _CAPABILITY_IDS:
        for kind in _REQUIRED:
            matching = tuple(rule for rule in policy.rules if rule.capability_id == capability_id and rule.proof_kind is kind and _SUBJECT in rule.subjects and _VERIFIER in rule.verifiers)
            if not matching:
                raise ValueError(f"committed proof policy has no trusted c{capability_id} {kind.value} rule")
            if not any(not rule.reference_prefixes or any(reference.startswith(prefix) for prefix in rule.reference_prefixes) for rule in matching):
                raise ValueError("run_reference is not allowed by hypothesis evolution proof policy")

    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or not prior:
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not continuity.verify_chain(anchor_token=prior_anchor_token, current_revision=prior):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    first = run_hypothesis_evolution_benchmark()
    second = run_hypothesis_evolution_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("hypothesis evolution benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("hypothesis evolution benchmark is not deterministic")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    payload_for_digest = {key: value for key, value in first.items() if key not in {"benchmark_passed", "benchmark_sha256"}}
    if len(benchmark_digest) != 64 or benchmark_digest != _sha(payload_for_digest):
        raise ValueError("hypothesis evolution benchmark digest verification failed")

    receipt_digest = _sha({"revision": revision, "engine_sha256": engine_digest, "benchmark_sha256": benchmark_digest, "subject": _SUBJECT, "capabilities": _CAPABILITY_IDS})
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0
    for capability_id in _CAPABILITY_IDS:
        for kind in _REQUIRED:
            receipt_id = f"hypothesis-evolution:{revision[:12]}:c{capability_id}:{kind.value}"
            previous = existing.get(receipt_id)
            if previous is not None:
                if not _same_receipt(previous, capability_id=capability_id, kind=kind, digest=receipt_digest, reference=reference, revision=revision):
                    raise ValueError("deterministic hypothesis evolution receipt_id collision")
                reused += 1
                continue
            ledger.add(receipt_id=receipt_id, capability_id=capability_id, proof_kind=kind, subject=_SUBJECT, subject_sha256=receipt_digest, verifier=_VERIFIER, observed_at=current_time, reference=reference, implementation_revision=revision)
            added += 1

    anchor = ledger.create_anchor(current_revision=revision, issued_at=current_time)
    audit = audit_repository_maturity(repo_root=root, ledger_path=ledger_target, integrity_key=integrity_key, anchor_token=anchor, now=current_time, policy_path=policy_path)
    if not audit.audit_valid:
        raise ValueError("trusted maturity audit rejected hypothesis evolution attestation")

    identity_after = repository_identity(root)
    if not identity_after.get("available") or not identity_after.get("clean") or str(identity_after.get("revision") or "") != revision:
        raise ValueError("repository changed during hypothesis evolution attestation")

    return HypothesisEvolutionExecutionAttestation(revision=revision, engine_sha256=engine_digest, benchmark_sha256=benchmark_digest, receipts_added=added, receipts_reused=reused, anchor_token=anchor, audit=audit)
