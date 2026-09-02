"""Trusted EXECUTION/REPRODUCIBILITY attestation for #102.

The attestor executes a fixed analytic structural-equation benchmark twice from
the exact tracked implementation.  It independently checks expected Euler-step
values and do-intervention consequences before minting revision-bound receipts.
This proves deterministic software execution, not real-world causal validity.
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

from . import mechanistic_reasoning as mech
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


_CAPABILITY_ID = 102
_SUBJECT = "mechanistic-simulation-benchmark"
_VERIFIER = "trusted-operator"
_REQUIRED = (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY)
_MODEL_SUBJECT = "research_engine/mechanistic_reasoning.py"


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


def _benchmark_model() -> mech.MechanismModel:
    return mech.MechanismModel(
        model_id="analytic_two_state",
        variables=(
            mech.MechanismVariable(
                variable_id="x",
                initial_value=2.0,
                lower_bound=-10.0,
                upper_bound=10.0,
                unit="1",
                role="STATE",
                observable_ref="benchmark:x",
            ),
            mech.MechanismVariable(
                variable_id="y",
                initial_value=0.0,
                lower_bound=-20.0,
                upper_bound=20.0,
                unit="1",
                role="STATE",
                observable_ref="benchmark:y",
            ),
        ),
        equations=(
            mech.MechanismEquation(
                target="x",
                terms=(mech.MechanismTerm("x", -1.0),),
                mechanism="x decays proportionally to its current state",
                observable="measure x after each half-step",
                falsifier="x does not halve per step under the benchmark equation",
                evidence_refs=("benchmark:analytic-definition",),
            ),
            mech.MechanismEquation(
                target="y",
                terms=(mech.MechanismTerm("x", 1.0),),
                mechanism="x drives the rate of y",
                observable="measure y after each half-step",
                falsifier="y increments do not equal dt*x under the benchmark equation",
                evidence_refs=("benchmark:analytic-definition",),
            ),
        ),
        dt=0.5,
        steps=2,
    )


def run_mechanistic_simulation_benchmark() -> Mapping[str, Any]:
    model = _benchmark_model()
    audit = mech.audit_mechanism(model)
    baseline = mech.simulate_mechanism(model)
    intervention = mech.simulate_mechanism(model, intervention={"x": 4.0})
    comparison = mech.compare_intervention(model, {"x": 4.0})
    baseline_final = dict(baseline.final_state)
    intervention_final = dict(intervention.final_state)
    delta = dict(comparison.final_delta)
    checks = {
        "mechanism_contract_complete": audit.complete is True,
        "baseline_x_closed_form": math.isclose(baseline_final["x"], 0.5, abs_tol=1e-12),
        "baseline_y_closed_form": math.isclose(baseline_final["y"], 1.5, abs_tol=1e-12),
        "do_x_fixed": math.isclose(intervention_final["x"], 4.0, abs_tol=1e-12),
        "do_y_closed_form": math.isclose(intervention_final["y"], 4.0, abs_tol=1e-12),
        "counterfactual_delta_x": math.isclose(delta["x"], 3.5, abs_tol=1e-12),
        "counterfactual_delta_y": math.isclose(delta["y"], 2.5, abs_tol=1e-12),
        "truth_boundary": (
            baseline.causal_mechanism_proven is False
            and baseline.real_world_effect_proven is False
            and comparison.causal_effect_proven is False
            and audit.empirical_validation_proven is False
            and baseline.truth_proven is False
        ),
    }
    payload = {
        "benchmark_version": "mechanistic-simulation-benchmark-v1",
        "checks": checks,
        "audit": asdict(audit),
        "baseline": asdict(baseline),
        "intervention": asdict(intervention),
        "comparison": asdict(comparison),
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


@dataclass(frozen=True)
class MechanisticExecutionAttestation:
    revision: str
    engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    causal_mechanism_proven: bool = False
    real_world_effect_proven: bool = False
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
        "subject": _SUBJECT,
        "subject_sha256": digest,
        "verifier": _VERIFIER,
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_mechanistic_simulation_execution(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> MechanisticExecutionAttestation:
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
        raise ValueError("mechanistic execution attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _MODEL_SUBJECT)
    imported_engine = Path(str(mech.__file__)).resolve(strict=True)
    audited_engine = (root / _MODEL_SUBJECT).resolve(strict=True)
    if imported_engine != audited_engine:
        raise ValueError("Mechanistic runtime is not loaded from the audited repository")

    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    for kind in _REQUIRED:
        matching = tuple(
            rule for rule in policy.rules
            if rule.capability_id == _CAPABILITY_ID
            and rule.proof_kind is kind
            and _SUBJECT in rule.subjects
            and _VERIFIER in rule.verifiers
        )
        if not matching:
            raise ValueError(f"committed proof policy has no trusted {kind.value} rule")
        if not any(
            not rule.reference_prefixes
            or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
            for rule in matching
        ):
            raise ValueError("run_reference is not allowed by mechanistic proof policy")

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

    first = run_mechanistic_simulation_benchmark()
    second = run_mechanistic_simulation_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("mechanistic analytic benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("mechanistic benchmark is not deterministic")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    expected_digest = _sha({
        "benchmark_version": first["benchmark_version"],
        "checks": first["checks"],
        "audit": first["audit"],
        "baseline": first["baseline"],
        "intervention": first["intervention"],
        "comparison": first["comparison"],
    })
    if len(benchmark_digest) != 64 or benchmark_digest != expected_digest:
        raise ValueError("mechanistic benchmark digest verification failed")

    receipt_digest = _sha({
        "revision": revision,
        "engine_sha256": engine_digest,
        "benchmark_sha256": benchmark_digest,
        "subject": _SUBJECT,
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0
    for kind in _REQUIRED:
        receipt_id = f"mechanistic:{revision[:12]}:{kind.value}"
        previous = existing.get(receipt_id)
        if previous is not None:
            if not _same_receipt(
                previous,
                kind=kind,
                digest=receipt_digest,
                reference=reference,
                revision=revision,
            ):
                raise ValueError("deterministic mechanistic receipt_id collision")
            reused += 1
            continue
        ledger.add(
            receipt_id=receipt_id,
            capability_id=_CAPABILITY_ID,
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
        raise ValueError("trusted maturity audit rejected mechanistic execution attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during mechanistic execution attestation")

    return MechanisticExecutionAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        benchmark_sha256=benchmark_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
