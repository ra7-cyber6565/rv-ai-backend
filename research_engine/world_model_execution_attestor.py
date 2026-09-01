"""Trusted deterministic EXECUTION/REPRODUCIBILITY attestor for #68 World Model.

The benchmark exercises explicit state/action dynamics, observation mapping,
counterfactual rollout and calibration against an analytically generated trace.
It proves only that the audited software executes the frozen model contract and
repeats deterministically. It never claims that the model is reality, that a
causal effect is proven in the world, or that the sim-to-reality gap is closed.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from utils.release_identity import repository_identity

from . import world_model as world
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


_CAPABILITY_ID = 68
_ENGINE_SUBJECT = "research_engine/world_model.py"
_BENCHMARK_VERSION = "world-model-execution-v1"
_REQUIRED = (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY)
_VERIFIERS = {
    ProofKind.EXECUTION: "trusted-execution-attestor",
    ProofKind.REPRODUCIBILITY: "trusted-reproducibility-attestor",
}
_NAMESPACES = {
    ProofKind.EXECUTION: "execution",
    ProofKind.REPRODUCIBILITY: "reproducibility",
}
_SUFFIXES = {
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


def _safe_observation_id(value: object) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 120:
        raise ValueError("observation_id is invalid")
    if any(not (ch.isalnum() or ch in "_.@/+~-") for ch in text):
        raise ValueError("observation_id is invalid")
    return text


def _subject(kind: ProofKind) -> str:
    return f"capability-{_CAPABILITY_ID}-{_SUFFIXES[kind]}"


def _reference(kind: ProofKind, observation_id: str) -> str:
    return f"{_NAMESPACES[kind]}:c{_CAPABILITY_ID}:{observation_id}"


def _model() -> world.WorldModel:
    spec = world.WorldModelSpec(
        state_names=("x",),
        action_names=("u",),
        observation_names=("y",),
        transition_matrix=((1.0,),),
        action_matrix=((2.0,),),
        transition_bias=(1.0,),
        observation_matrix=((3.0,),),
        observation_bias=(4.0,),
        lower_bounds=(-100.0,),
        upper_bounds=(100.0,),
        calibration_tolerance=1e-9,
    )
    return world.WorldModel(spec)


def run_world_model_benchmark() -> Mapping[str, Any]:
    model = _model()
    initial = {"x": 1.0}
    actions = ({"u": 1.0}, {"u": 2.0})
    rollout = model.rollout(initial, actions)
    counterfactual = model.counterfactual(
        initial,
        ({"u": 0.0}, {"u": 0.0}),
        ({"u": 1.0}, {"u": 1.0}),
    )
    observed_states = ({"x": 1.0}, {"x": 4.0}, {"x": 9.0})
    observed_observations = ({"y": 7.0}, {"y": 16.0}, {"y": 31.0})
    calibration = model.calibrate(
        observed_states,
        observed_observations,
        actions,
    )

    checks = {
        "rollout_state_0": math.isclose(rollout.steps[0].state["x"], 1.0),
        "rollout_state_1": math.isclose(rollout.steps[1].state["x"], 4.0),
        "rollout_state_2": math.isclose(rollout.steps[2].state["x"], 9.0),
        "observation_0": math.isclose(rollout.steps[0].observation["y"], 7.0),
        "observation_2": math.isclose(rollout.steps[2].observation["y"], 31.0),
        "counterfactual_delta": math.isclose(
            counterfactual.final_state_delta["x"], 4.0, rel_tol=0.0, abs_tol=1e-12
        ),
        "counterfactual_divergence": math.isclose(
            counterfactual.max_normalized_state_divergence,
            0.02,
            rel_tol=0.0,
            abs_tol=1e-12,
        ),
        "calibration_exact": (
            calibration.calibrated is True
            and math.isclose(calibration.state_normalized_rmse, 0.0, abs_tol=1e-15)
            and math.isclose(calibration.observation_normalized_rmse, 0.0, abs_tol=1e-15)
            and calibration.one_step_predictions == 2
            and calibration.ood_observed_states == 0
        ),
        "truth_boundary": (
            rollout.software_only is True
            and rollout.world_model_is_reality is False
            and rollout.sim_to_reality_gap_open is True
            and counterfactual.causal_effect_proven is False
            and counterfactual.world_model_is_reality is False
            and calibration.sim_to_reality_gap_open is True
            and calibration.truth_proven is False
        ),
    }
    payload = {
        "benchmark_version": _BENCHMARK_VERSION,
        "checks": checks,
        "rollout": asdict(rollout),
        "counterfactual": asdict(counterfactual),
        "calibration": asdict(calibration),
        "world_model_is_reality": False,
        "sim_to_reality_gap_open": True,
        "truth_proven": False,
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


@dataclass(frozen=True)
class WorldModelExecutionAttestation:
    revision: str
    engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    world_model_is_reality: bool = False
    sim_to_reality_gap_open: bool = True
    truth_proven: bool = False


def _same_receipt(
    row: Mapping[str, Any],
    *,
    kind: ProofKind,
    digest: str,
    reference: str,
    revision: str,
) -> bool:
    expected = {
        "capability_id": _CAPABILITY_ID,
        "proof_kind": kind.value,
        "subject": _subject(kind),
        "subject_sha256": digest,
        "verifier": _VERIFIERS[kind],
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_world_model_execution(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    observation_id: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> WorldModelExecutionAttestation:
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
        raise ValueError("world model attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _ENGINE_SUBJECT)
    imported_engine = Path(str(world.__file__)).resolve(strict=True)
    audited_engine = (root / _ENGINE_SUBJECT).resolve(strict=True)
    if imported_engine != audited_engine:
        raise ValueError("World Model runtime is not loaded from the audited repository")

    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    references = {}
    for kind in _REQUIRED:
        subject = _subject(kind)
        verifier = _VERIFIERS[kind]
        reference = _reference(kind, observation)
        matching = tuple(
            rule for rule in policy.rules
            if rule.capability_id == _CAPABILITY_ID
            and rule.proof_kind is kind
            and subject in rule.subjects
            and verifier in rule.verifiers
        )
        if not matching:
            raise ValueError(f"committed proof policy has no trusted {kind.value} rule")
        if not any(
            not rule.reference_prefixes
            or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
            for rule in matching
        ):
            raise ValueError("generated reference is not allowed by proof policy")
        references[kind] = reference

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

    first = run_world_model_benchmark()
    second = run_world_model_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("world model benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("world model benchmark is not deterministic")
    if first.get("world_model_is_reality") is not False:
        raise ValueError("world model benchmark must not claim model=reality")
    if first.get("sim_to_reality_gap_open") is not True:
        raise ValueError("world model benchmark must keep sim-to-reality gap open")
    if first.get("truth_proven") is not False:
        raise ValueError("world model benchmark must not claim scientific truth")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    payload_for_digest = {
        key: value for key, value in first.items()
        if key not in {"benchmark_passed", "benchmark_sha256"}
    }
    if len(benchmark_digest) != 64 or benchmark_digest != _sha(payload_for_digest):
        raise ValueError("world model benchmark digest verification failed")

    receipt_digest = _sha({
        "revision": revision,
        "engine_sha256": engine_digest,
        "benchmark_sha256": benchmark_digest,
        "capability_id": _CAPABILITY_ID,
        "proof_kinds": [kind.value for kind in _REQUIRED],
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0
    for kind in _REQUIRED:
        reference = references[kind]
        receipt_id = f"world-model:{revision[:12]}:{kind.value}"
        previous = existing.get(receipt_id)
        if previous is not None:
            if not _same_receipt(
                previous,
                kind=kind,
                digest=receipt_digest,
                reference=reference,
                revision=revision,
            ):
                raise ValueError("deterministic world-model receipt_id collision")
            reused += 1
            continue
        ledger.add(
            receipt_id=receipt_id,
            capability_id=_CAPABILITY_ID,
            proof_kind=kind,
            subject=_subject(kind),
            subject_sha256=receipt_digest,
            verifier=_VERIFIERS[kind],
            observed_at=current_time,
            reference=reference,
            implementation_revision=revision,
        )
        added += 1

    if added + reused != len(_REQUIRED):
        raise ValueError("world model attestation did not account for every proof route")

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
        raise ValueError("trusted maturity audit rejected world model attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "").strip().lower() != revision
    ):
        raise ValueError("repository changed during world model attestation")

    return WorldModelExecutionAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        benchmark_sha256=benchmark_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
