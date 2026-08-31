"""Trusted deterministic execution attestor for the bounded simulation family.

Covers software execution/reproducibility routes for:
- #25 Digital Twin Engine
- #26 Multi-Physics Simulation
- #27 Synthetic Environment
- #28 Agent-Based Simulation
- #73 Failure Mode and Effects Analysis
- #74 Fault Injection
- #86 Black Swan Testing

This benchmark deliberately proves only that the tracked software executes
reproducibly on fixed falsifiable fixtures.  It never mints hardware, safety,
live, physical-truth, or sim-to-reality evidence.  Capabilities whose registry
also requires HARDWARE/SAFETY therefore remain incomplete until those external
proofs actually exist.
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

from . import multiphysics_simulation as mp
from . import simulation_lab as sim
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


_CAPABILITY_IDS = (25, 26, 27, 28, 73, 74, 86)
_REQUIRED = (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY)
_SUBJECT = "simulation-lab-benchmark"
_VERIFIER = "trusted-operator"
_SIM_ENGINE = "research_engine/simulation_lab.py"
_MULTIPHYSICS_ENGINE = "research_engine/multiphysics_simulation.py"
_BENCHMARK_VERSION = "simulation-lab-benchmark-v1"


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


def _twin_fixture() -> tuple[sim.DigitalTwin, Mapping[str, Any]]:
    twin = sim.DigitalTwin(sim.DigitalTwinSpec(
        state_names=("signal",),
        transition_matrix=((0.9,),),
        bias=(0.0,),
        lower_bounds=(-10.0,),
        upper_bounds=(10.0,),
        calibration_tolerance=0.02,
    ))
    run = twin.simulate({"signal": 1.0}, steps=8)
    calibration = twin.validate_calibration([
        {"signal": 1.0},
        {"signal": 0.9},
        {"signal": 0.81},
        {"signal": 0.729},
        {"signal": 0.6561},
    ])
    return twin, {
        "simulation": asdict(run),
        "calibration": asdict(calibration),
    }


def _multiphysics_fixture() -> Mapping[str, Any]:
    model = mp.CoupledPhysicsModel()
    initial = mp.PhysicsState(
        temperature=20.0,
        position=0.0,
        velocity=0.0,
        current=0.0,
    )
    inputs = mp.PhysicsInputs(
        ambient_temperature=20.0,
        heat_input=1.0,
        force_input=0.2,
        voltage_input=1.0,
    )
    result = mp.simulate_coupled(
        model,
        initial,
        inputs,
        duration=1.0,
        dt=0.02,
        retain_every=10,
    )
    convergence = mp.convergence_check(
        model,
        initial,
        inputs,
        duration=1.0,
        coarse_dt=0.02,
        tolerance=1e-5,
    )
    return {
        "result": asdict(result),
        "convergence": asdict(convergence),
    }


def _agent_fixture() -> Mapping[str, Any]:
    agents = (
        sim.AgentSpec("alpha", response=0.25, inertia=0.6, coupling=0.10),
        sim.AgentSpec("beta", response=0.35, inertia=0.5, coupling=0.15),
        sim.AgentSpec("gamma", response=0.20, inertia=0.7, coupling=0.05),
    )
    result = sim.run_agent_environment(
        agents,
        {"alpha": 0.0, "beta": 0.1, "gamma": -0.1},
        external_signal=(0.0, 0.2, 0.4, 0.1, -0.2, 0.0, 0.3, 0.1),
        shocks={4: -0.25},
        seed=20260831,
    )
    return asdict(result)


def _fault_fixture(twin: sim.DigitalTwin) -> Mapping[str, Any]:
    campaign = sim.run_fault_campaign(
        twin,
        {"signal": 1.0},
        (
            sim.FaultMode(
                name="large_positive_impulse",
                variable="signal",
                delta=4.0,
                severity=8,
                occurrence=3,
                detectability=5,
                duration_steps=2,
            ),
            sim.FaultMode(
                name="small_negative_impulse",
                variable="signal",
                delta=-0.5,
                severity=3,
                occurrence=2,
                detectability=2,
                duration_steps=1,
            ),
        ),
        steps=16,
        injection_step=3,
        recovery_tolerance=0.05,
    )
    return asdict(campaign)


def _black_swan_fixture() -> Mapping[str, Any]:
    report = sim.black_swan_suite(
        (
            100.0, 101.0, 102.0, 101.5, 103.0, 104.0, 103.5, 105.0,
            106.0, 105.5, 107.0, 108.0, 107.5, 109.0, 110.0, 111.0,
        ),
        seed=20260831,
    )
    return asdict(report)


def run_simulation_benchmark() -> Mapping[str, Any]:
    """Execute the frozen software-only simulation benchmark."""
    twin, twin_payload = _twin_fixture()
    multiphysics = _multiphysics_fixture()
    agents = _agent_fixture()
    faults = _fault_fixture(twin)
    black_swan = _black_swan_fixture()

    twin_sim = twin_payload["simulation"]
    calibration = twin_payload["calibration"]
    mp_result = multiphysics["result"]
    convergence = multiphysics["convergence"]

    scenario_names = tuple(
        row["name"] for row in black_swan["scenarios"]
    )
    ranked_rpns = tuple(row["rpn"] for row in faults["ranked_fmea"])
    checks = {
        "digital_twin_executes_bounded_software_model": (
            len(twin_sim["states"]) == 9
            and twin_sim["software_only"] is True
            and twin_sim["hardware_validated"] is False
            and not twin_sim["bound_violations"]
        ),
        "digital_twin_calibration_is_explicit_not_physical_proof": (
            calibration["calibrated"] is True
            and calibration["normalized_rmse"] <= 0.02
            and calibration["sim_to_reality_gap_open"] is True
        ),
        "multiphysics_coupling_executes_with_rk4": (
            mp_result["integration_method"] == "RK4_FIXED_STEP"
            and mp_result["coupling_active"] is True
            and mp_result["software_only"] is True
            and mp_result["hardware_validated"] is False
            and mp_result["truth_proven"] is False
        ),
        "multiphysics_has_numerical_convergence_diagnostic": (
            convergence["converged"] is True
            and convergence["normalized_terminal_error"] <= convergence["tolerance"]
            and convergence["software_only"] is True
            and convergence["hardware_validated"] is False
            and convergence["truth_proven"] is False
        ),
        "synthetic_agent_environment_is_seeded_and_bounded": (
            agents["seed"] == 20260831
            and agents["synthetic_only"] is True
            and len(agents["aggregate"]) == 9
            and len(agents["per_agent"]) == 3
        ),
        "fmea_and_fault_injection_preserve_safety_boundary": (
            faults["software_only"] is True
            and faults["safety_review_required"] is True
            and len(ranked_rpns) == 2
            and ranked_rpns == tuple(sorted(ranked_rpns, reverse=True))
        ),
        "black_swan_suite_covers_locked_stress_families": (
            black_swan["synthetic_only"] is True
            and black_swan["future_guarantee"] is False
            and scenario_names == (
                "tail_crash",
                "volatility_cluster",
                "regime_reversal",
                "liquidity_freeze_gap",
            )
        ),
    }
    payload = {
        "benchmark_version": _BENCHMARK_VERSION,
        "checks": checks,
        "digital_twin": twin_payload,
        "multiphysics": multiphysics,
        "agent_environment": agents,
        "fault_campaign": faults,
        "black_swan": black_swan,
        "software_only": True,
        "hardware_observed": False,
        "safety_certified": False,
        "live_world_observed": False,
        "sim_to_reality_closed": False,
        "future_guaranteed": False,
        "truth_proven": False,
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


@dataclass(frozen=True)
class SimulationExecutionAttestation:
    revision: str
    simulation_engine_sha256: str
    multiphysics_engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    hardware_observed: bool = False
    safety_certified: bool = False
    live_world_observed: bool = False
    sim_to_reality_closed: bool = False
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
        "subject": _SUBJECT,
        "subject_sha256": digest,
        "verifier": _VERIFIER,
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_simulation_execution(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> SimulationExecutionAttestation:
    """Run benchmark and mint only policy-approved EXECUTION/REPRO receipts."""
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
        raise ValueError("simulation attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    sim_digest = _hash_tracked_regular(root, tracked, _SIM_ENGINE)
    multiphysics_digest = _hash_tracked_regular(root, tracked, _MULTIPHYSICS_ENGINE)
    if Path(str(sim.__file__)).resolve(strict=True) != (root / _SIM_ENGINE).resolve(strict=True):
        raise ValueError("simulation runtime is not loaded from the audited repository")
    if Path(str(mp.__file__)).resolve(strict=True) != (root / _MULTIPHYSICS_ENGINE).resolve(strict=True):
        raise ValueError("multi-physics runtime is not loaded from the audited repository")

    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    for capability_id in _CAPABILITY_IDS:
        for kind in _REQUIRED:
            matching = tuple(
                rule for rule in policy.rules
                if rule.capability_id == capability_id
                and rule.proof_kind is kind
                and _SUBJECT in rule.subjects
                and _VERIFIER in rule.verifiers
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
                raise ValueError("run_reference is not allowed by simulation proof policy")

    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or not prior:
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not continuity.verify_chain(
            anchor_token=prior_anchor_token,
            current_revision=prior,
        ):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    first = run_simulation_benchmark()
    second = run_simulation_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("simulation benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("simulation benchmark is not deterministic")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    payload_for_digest = {
        key: value for key, value in first.items()
        if key not in {"benchmark_passed", "benchmark_sha256"}
    }
    if len(benchmark_digest) != 64 or benchmark_digest != _sha(payload_for_digest):
        raise ValueError("simulation benchmark digest verification failed")

    receipt_digest = _sha({
        "revision": revision,
        "simulation_engine_sha256": sim_digest,
        "multiphysics_engine_sha256": multiphysics_digest,
        "benchmark_sha256": benchmark_digest,
        "subject": _SUBJECT,
        "capabilities": _CAPABILITY_IDS,
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0
    for capability_id in _CAPABILITY_IDS:
        for kind in _REQUIRED:
            receipt_id = f"simulation-lab:{revision[:12]}:c{capability_id}:{kind.value}"
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
                    raise ValueError("deterministic simulation receipt_id collision")
                reused += 1
                continue
            ledger.add(
                receipt_id=receipt_id,
                capability_id=capability_id,
                proof_kind=kind,
                subject=_SUBJECT,
                subject_sha256=receipt_digest,
                verifier=_VERIFIER,
                observed_at=current_time,
                reference=reference,
                implementation_revision=revision,
            )
            added += 1

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
        raise ValueError("trusted maturity audit rejected simulation attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during simulation attestation")

    return SimulationExecutionAttestation(
        revision=revision,
        simulation_engine_sha256=sim_digest,
        multiphysics_engine_sha256=multiphysics_digest,
        benchmark_sha256=benchmark_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
