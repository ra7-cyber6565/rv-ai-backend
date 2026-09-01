"""Role-separated maturity attestation for capability #72 Human Factors.

Four proof classes are deliberately kept separate:

* EXECUTION: a fixed analytic software benchmark executes on the audited engine.
* REPRODUCIBILITY: the same benchmark is byte-deterministic on repeat execution.
* HARDWARE: a trusted hardware-lab context supplies an externally retained,
  hash-bound real-human study bundle that explicitly records hardware observation.
* SAFETY: a distinct trusted safety-officer context reviews the same kind of
  hash-bound human study against a precommitted adverse-event threshold.

The software benchmark can never mint HARDWARE or SAFETY.  Conversely, external
study observations do not silently mint EXECUTION/REPRODUCIBILITY.  The attestor
never claims population generalization, universal human safety, certification,
or real-world effectiveness merely because a bounded requirement passes.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple

from utils.release_identity import repository_identity

from . import human_factors as hf
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


_CAPABILITY_ID = 72
_ENGINE_SUBJECT = "research_engine/human_factors.py"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ROUTE = {
    ProofKind.EXECUTION: {
        "subject": "capability-72-execution-run",
        "verifier": "trusted-execution-attestor",
        "prefix": "execution:c72:",
    },
    ProofKind.REPRODUCIBILITY: {
        "subject": "capability-72-reproducibility-run",
        "verifier": "trusted-reproducibility-attestor",
        "prefix": "reproducibility:c72:",
    },
    ProofKind.HARDWARE: {
        "subject": "capability-72-hardware-observation",
        "verifier": "trusted-hardware-lab",
        "prefix": "hardware:c72:",
    },
    ProofKind.SAFETY: {
        "subject": "capability-72-safety-gate",
        "verifier": "trusted-safety-officer",
        "prefix": "safety:c72:",
    },
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


def _finite_time(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("now must be finite") from exc
    if not math.isfinite(number):
        raise ValueError("now must be finite")
    return number


def run_human_factors_benchmark() -> Mapping[str, Any]:
    """Exercise the math/contract engine without pretending simulated rows are humans."""
    requirement = hf.HumanFactorsRequirement(
        requirement_id="analytic-task",
        task_id="bounded-ui-task",
        minimum_participants=4,
        minimum_task_success=0.75,
        maximum_critical_error_rate=0.25,
        maximum_adverse_event_rate=0.25,
        maximum_p95_completion_seconds=12.0,
        maximum_p95_workload_score=55.0,
        require_real_humans=False,
        require_field_or_operational=False,
        require_independent=False,
        require_ethics_review=False,
        require_consent=False,
        require_safety_review=False,
    )
    study = hf.HumanStudyEvidence(
        study_id="analytic-row",
        requirement_id="analytic-task",
        task_id="bounded-ui-task",
        environment="SIMULATION",
        provenance_ref="benchmark:synthetic-not-human-evidence",
        participant_count=4,
        successful_tasks=3,
        attempted_tasks=4,
        critical_errors=1,
        adverse_events=0,
        completion_seconds=(8.0, 9.0, 10.0, 11.0),
        workload_scores=(20.0, 30.0, 40.0, 50.0),
        real_humans_observed=False,
        independent=False,
        ethics_reviewed=False,
        consent_documented=False,
        safety_reviewed=False,
        representative_sample_proven=False,
    )
    report = hf.audit_human_factors(requirements=(requirement,), studies=(study,))
    audit = report.audits[0]
    checks = {
        "requirement_passes": report.all_requirements_passed is True,
        "participant_count": audit.participant_count == 4,
        "task_success_closed_form": math.isclose(
            float(audit.task_success_rate), 0.75, rel_tol=0.0, abs_tol=1e-12
        ),
        "critical_error_closed_form": math.isclose(
            float(audit.critical_error_rate), 0.25, rel_tol=0.0, abs_tol=1e-12
        ),
        "adverse_event_closed_form": math.isclose(
            float(audit.adverse_event_rate), 0.0, rel_tol=0.0, abs_tol=1e-12
        ),
        "p95_completion_closed_form": math.isclose(
            float(audit.p95_completion_seconds), 11.0, rel_tol=0.0, abs_tol=1e-12
        ),
        "p95_workload_closed_form": math.isclose(
            float(audit.p95_workload_score), 50.0, rel_tol=0.0, abs_tol=1e-12
        ),
        "truth_boundary": (
            report.agent_simulation_promoted_to_human_evidence is False
            and report.population_generalization_proven is False
            and report.human_safety_truth_proven is False
            and report.external_certification_claimed is False
        ),
    }
    payload = {
        "benchmark_version": "human-factors-software-benchmark-v1",
        "checks": checks,
        "report": asdict(report),
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


@dataclass(frozen=True)
class HumanFactorsExternalObservation:
    """Hash-bound data supplied only in an authorized external attestor context."""

    requirement: hf.HumanFactorsRequirement
    studies: Tuple[hf.HumanStudyEvidence, ...]
    hardware_observed: bool
    hardware_provenance_ref: str
    safety_officer_reviewed: bool
    safety_review_ref: str

    def normalized_payload(self) -> Mapping[str, Any]:
        requirement = self.requirement.normalized()
        studies = tuple(item.normalized() for item in self.studies)
        if not studies:
            raise ValueError("external human-factors observation requires study rows")
        hardware_ref = str(self.hardware_provenance_ref or "").strip()
        safety_ref = str(self.safety_review_ref or "").strip()
        if self.hardware_observed and not 3 <= len(hardware_ref) <= 20_000:
            raise ValueError("hardware_provenance_ref is required for hardware observation")
        if self.safety_officer_reviewed and not 3 <= len(safety_ref) <= 20_000:
            raise ValueError("safety_review_ref is required for safety review")
        return {
            "requirement": asdict(requirement),
            "studies": [asdict(item) for item in studies],
            "hardware_observed": bool(self.hardware_observed),
            "hardware_provenance_ref": hardware_ref,
            "safety_officer_reviewed": bool(self.safety_officer_reviewed),
            "safety_review_ref": safety_ref,
        }

    def sha256(self) -> str:
        return _sha(self.normalized_payload())


@dataclass(frozen=True)
class HumanFactorsAttestation:
    revision: str
    engine_sha256: str
    proof_kind: str
    evidence_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    population_generalization_proven: bool = False
    universal_human_safety_proven: bool = False
    external_certification_claimed: bool = False


def _prepare_repo(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
):
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")
    identity = repository_identity(root)
    revision = str(identity.get("revision") or "")
    if not identity.get("available") or not identity.get("clean") or not revision:
        raise ValueError("human-factors attestation requires a clean Git checkout")
    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _ENGINE_SUBJECT)
    imported_engine = Path(str(hf.__file__)).resolve(strict=True)
    audited_engine = (root / _ENGINE_SUBJECT).resolve(strict=True)
    if imported_engine != audited_engine:
        raise ValueError("Human Factors runtime is not loaded from audited repository")
    return root, ledger_target, identity, revision, tracked, engine_digest


def _check_policy(policy, *, kind: ProofKind, reference: str) -> None:
    route = _ROUTE[kind]
    matching = tuple(
        rule for rule in policy.rules
        if rule.capability_id == _CAPABILITY_ID
        and rule.proof_kind is kind
        and route["subject"] in rule.subjects
        and route["verifier"] in rule.verifiers
    )
    if not matching:
        raise ValueError(f"committed proof policy has no trusted {kind.value} rule")
    if not any(
        (not rule.reference_prefixes)
        or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
        for rule in matching
    ):
        raise ValueError(f"{kind.value} reference is not allowed by human-factors proof policy")
    if not reference.startswith(route["prefix"]):
        raise ValueError(f"{kind.value} reference is not capability-bound")


def _check_continuity(
    *,
    ledger_target: Path,
    integrity_key: bytes,
    prior_anchor_token: str,
    prior_revision: str,
) -> None:
    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or not prior:
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not ledger.verify_chain(
            anchor_token=prior_anchor_token,
            current_revision=prior,
        ):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")


def _same_receipt(
    row: Mapping[str, Any],
    *,
    kind: ProofKind,
    digest: str,
    reference: str,
    revision: str,
) -> bool:
    route = _ROUTE[kind]
    expected = {
        "capability_id": _CAPABILITY_ID,
        "proof_kind": kind.value,
        "subject": route["subject"],
        "subject_sha256": digest,
        "verifier": route["verifier"],
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def _mint_one(
    *,
    root: Path,
    ledger_target: Path,
    integrity_key: bytes,
    revision: str,
    engine_digest: str,
    kind: ProofKind,
    evidence_digest: str,
    reference: str,
    current_time: float,
    policy_path: str,
) -> HumanFactorsAttestation:
    route = _ROUTE[kind]
    receipt_digest = _sha({
        "revision": revision,
        "engine_sha256": engine_digest,
        "evidence_sha256": evidence_digest,
        "proof_kind": kind.value,
        "capability_id": _CAPABILITY_ID,
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    receipt_id = f"human-factors:{revision[:12]}:{kind.value}:{evidence_digest[:12]}"
    previous = existing.get(receipt_id)
    added = reused = 0
    if previous is not None:
        if not _same_receipt(
            previous,
            kind=kind,
            digest=receipt_digest,
            reference=reference,
            revision=revision,
        ):
            raise ValueError("deterministic human-factors receipt_id collision")
        reused = 1
    else:
        ledger.add(
            receipt_id=receipt_id,
            capability_id=_CAPABILITY_ID,
            proof_kind=kind,
            subject=route["subject"],
            subject_sha256=receipt_digest,
            verifier=route["verifier"],
            observed_at=current_time,
            reference=reference,
            implementation_revision=revision,
        )
        added = 1
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
        raise ValueError("trusted maturity audit rejected human-factors attestation")
    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during human-factors attestation")
    return HumanFactorsAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        proof_kind=kind.value,
        evidence_sha256=evidence_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )


def attest_human_factors_software(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    proof_kind: ProofKind,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> HumanFactorsAttestation:
    """Mint exactly one EXECUTION or REPRODUCIBILITY proof from the fixed benchmark."""
    if proof_kind not in {ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY}:
        raise ValueError("software attestor only accepts execution/reproducibility")
    current_time = _finite_time(now)
    reference = _safe_reference(run_reference)
    root, ledger_target, _identity, revision, tracked, engine_digest = _prepare_repo(
        repo_root=repo_root, ledger_path=ledger_path
    )
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    _check_policy(policy, kind=proof_kind, reference=reference)
    _check_continuity(
        ledger_target=ledger_target,
        integrity_key=integrity_key,
        prior_anchor_token=prior_anchor_token,
        prior_revision=prior_revision,
    )
    first = run_human_factors_benchmark()
    second = run_human_factors_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("human-factors software benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("human-factors software benchmark is not deterministic")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    expected = _sha({
        "benchmark_version": first["benchmark_version"],
        "checks": first["checks"],
        "report": first["report"],
    })
    if not _HEX64.fullmatch(benchmark_digest) or benchmark_digest != expected:
        raise ValueError("human-factors benchmark digest verification failed")
    return _mint_one(
        root=root,
        ledger_target=ledger_target,
        integrity_key=integrity_key,
        revision=revision,
        engine_digest=engine_digest,
        kind=proof_kind,
        evidence_digest=benchmark_digest,
        reference=reference,
        current_time=current_time,
        policy_path=policy_path,
    )


def attest_human_factors_external(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    proof_kind: ProofKind,
    observation: HumanFactorsExternalObservation,
    expected_bundle_sha256: str,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> HumanFactorsAttestation:
    """Mint one HARDWARE or SAFETY proof from a trusted external observation context."""
    if proof_kind not in {ProofKind.HARDWARE, ProofKind.SAFETY}:
        raise ValueError("external attestor only accepts hardware/safety")
    current_time = _finite_time(now)
    reference = _safe_reference(run_reference)
    root, ledger_target, _identity, revision, tracked, engine_digest = _prepare_repo(
        repo_root=repo_root, ledger_path=ledger_path
    )
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    _check_policy(policy, kind=proof_kind, reference=reference)
    _check_continuity(
        ledger_target=ledger_target,
        integrity_key=integrity_key,
        prior_anchor_token=prior_anchor_token,
        prior_revision=prior_revision,
    )

    payload = observation.normalized_payload()
    digest = _sha(payload)
    expected = str(expected_bundle_sha256 or "").strip().lower()
    if not _HEX64.fullmatch(expected) or expected != digest:
        raise ValueError("external human-factors bundle digest mismatch")

    requirement = observation.requirement.normalized()
    studies = tuple(item.normalized() for item in observation.studies)
    report = hf.audit_human_factors(requirements=(requirement,), studies=studies)
    if report.all_requirements_passed is not True:
        raise ValueError("external human-factors study does not satisfy precommitted requirement")
    if not all(item.real_humans_observed for item in studies):
        raise ValueError("real-human observation is required for external human-factors proof")
    if not all(item.ethics_reviewed and item.consent_documented for item in studies):
        raise ValueError("ethics review and consent are required for external human-factors proof")
    if not any(item.environment in {"FIELD", "OPERATIONAL"} for item in studies):
        raise ValueError("field or operational observation is required for external human-factors proof")

    if proof_kind is ProofKind.HARDWARE:
        if not observation.hardware_observed:
            raise ValueError("trusted hardware observation is required")
        if not str(observation.hardware_provenance_ref or "").strip():
            raise ValueError("hardware provenance is required")
    else:
        if requirement.maximum_adverse_event_rate is None:
            raise ValueError("safety proof requires a precommitted adverse-event threshold")
        if requirement.require_safety_review is not True:
            raise ValueError("safety proof requires safety review in the contract")
        if not all(item.safety_reviewed for item in studies):
            raise ValueError("all human-study rows require safety review")
        if not observation.safety_officer_reviewed:
            raise ValueError("trusted safety-officer review is required")
        if not str(observation.safety_review_ref or "").strip():
            raise ValueError("safety review provenance is required")

    return _mint_one(
        root=root,
        ledger_target=ledger_target,
        integrity_key=integrity_key,
        revision=revision,
        engine_digest=engine_digest,
        kind=proof_kind,
        evidence_digest=digest,
        reference=reference,
        current_time=current_time,
        policy_path=policy_path,
    )
