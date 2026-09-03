"""Trusted execution/reproducibility attestation for capability #71.

This attestor executes a fixed deterministic manufacturing-analysis benchmark
against the tracked ``manufacturing_reality`` engine.  It proves only that the
software correctly evaluates bounded process-capability, yield, tolerance and
qualitative-gate fixtures for the audited revision.  It does NOT mint hardware
or safety evidence and does not claim factory execution, hardware authenticity,
certification, production readiness, or real-world manufacturability.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

from utils.release_identity import repository_identity

from . import manufacturing_reality as manufacturing
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


_CAPABILITY_ID = 71
_ENGINE_SUBJECT = "research_engine/manufacturing_reality.py"
_ROUTE = {
    ProofKind.EXECUTION: {
        "subject": "capability-71-execution-run",
        "verifier": "trusted-execution-attestor",
        "prefix": "execution:",
    },
    ProofKind.REPRODUCIBILITY: {
        "subject": "capability-71-reproducibility-run",
        "verifier": "trusted-reproducibility-attestor",
        "prefix": "reproducibility:",
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


def run_manufacturing_reality_benchmark() -> Mapping[str, Any]:
    """Run a closed deterministic benchmark with independently known answers."""
    requirements = (
        manufacturing.ManufacturingRequirement(
            requirement_id="process-capability",
            requirement_kind="PROCESS_CAPABILITY",
            lower_spec=8.0,
            upper_spec=12.0,
            minimum_cpk=1.2,
            minimum_sample_size=30,
            require_measured=False,
            require_hardware_observed=False,
        ),
        manufacturing.ManufacturingRequirement(
            requirement_id="yield",
            requirement_kind="YIELD",
            minimum_yield=0.95,
            minimum_sample_size=100,
            require_measured=False,
            require_hardware_observed=False,
        ),
        manufacturing.ManufacturingRequirement(
            requirement_id="tolerance",
            requirement_kind="TOLERANCE_VERIFICATION",
            lower_spec=9.5,
            upper_spec=10.5,
            minimum_sample_size=4,
            require_measured=False,
            require_hardware_observed=False,
        ),
        manufacturing.ManufacturingRequirement(
            requirement_id="quality-gate",
            requirement_kind="QUALITATIVE_GATE",
            minimum_sample_size=1,
            require_measured=False,
            require_hardware_observed=False,
        ),
    )
    evidence = (
        manufacturing.ManufacturingEvidence(
            evidence_id="pc-study",
            requirement_id="process-capability",
            environment="ANALYTICAL",
            provenance_ref="benchmark:analytic-process-capability",
            sample_size=30,
            mean=10.0,
            stddev=0.5,
        ),
        manufacturing.ManufacturingEvidence(
            evidence_id="yield-study",
            requirement_id="yield",
            environment="ANALYTICAL",
            provenance_ref="benchmark:analytic-yield",
            sample_size=100,
            accepted_count=96,
            total_count=100,
        ),
        manufacturing.ManufacturingEvidence(
            evidence_id="tol-study",
            requirement_id="tolerance",
            environment="ANALYTICAL",
            provenance_ref="benchmark:analytic-tolerance",
            sample_size=4,
            measured_values=(9.5, 9.9, 10.1, 10.5),
        ),
        manufacturing.ManufacturingEvidence(
            evidence_id="qual-study",
            requirement_id="quality-gate",
            environment="ANALYTICAL",
            provenance_ref="benchmark:analytic-quality-gate",
            sample_size=1,
            explicit_pass=True,
        ),
    )
    report = manufacturing.audit_manufacturing_reality(
        requirements=requirements,
        evidence=evidence,
    )
    by_id = {audit.requirement_id: audit for audit in report.audits}
    expected_cp = 4.0 / (6.0 * 0.5)
    expected_cpk = min((12.0 - 10.0) / (3.0 * 0.5), (10.0 - 8.0) / (3.0 * 0.5))
    checks = {
        "all_requirements_passed": report.all_requirements_passed is True,
        "process_cp_closed_form": math.isclose(
            float(by_id["process-capability"].cp), expected_cp, rel_tol=0.0, abs_tol=1e-12
        ),
        "process_cpk_closed_form": math.isclose(
            float(by_id["process-capability"].cpk), expected_cpk, rel_tol=0.0, abs_tol=1e-12
        ),
        "yield_closed_form": math.isclose(
            float(by_id["yield"].observed_yield), 0.96, rel_tol=0.0, abs_tol=1e-12
        ),
        "tolerance_closed_form": by_id["tolerance"].out_of_tolerance_count == 0,
        "qualitative_gate_passes": by_id["quality-gate"].passed is True,
        "truth_boundary": (
            report.simulation_promoted_to_measurement is False
            and report.factory_execution_proven is False
            and report.hardware_authenticity_proven is False
            and report.external_certification_claimed is False
            and report.manufacturability_truth_proven is False
        ),
    }
    payload = {
        "benchmark_version": "manufacturing-reality-benchmark-v1",
        "checks": checks,
        "report": asdict(report),
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


@dataclass(frozen=True)
class ManufacturingRealityAttestation:
    revision: str
    engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    factory_execution_proven: bool = False
    hardware_authenticity_proven: bool = False
    safety_proven: bool = False
    manufacturability_truth_proven: bool = False


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


def attest_manufacturing_reality_execution(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    execution_reference: str,
    reproducibility_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> ManufacturingRealityAttestation:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    references: Dict[ProofKind, str] = {
        ProofKind.EXECUTION: _safe_reference(execution_reference),
        ProofKind.REPRODUCIBILITY: _safe_reference(reproducibility_reference),
    }
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "")
    if not identity_before.get("available") or not identity_before.get("clean") or not revision:
        raise ValueError("manufacturing attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _ENGINE_SUBJECT)
    imported_engine = Path(str(manufacturing.__file__)).resolve(strict=True)
    audited_engine = (root / _ENGINE_SUBJECT).resolve(strict=True)
    if imported_engine != audited_engine:
        raise ValueError("Manufacturing Reality runtime is not loaded from audited repository")

    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    for kind, route in _ROUTE.items():
        reference = references[kind]
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
            not rule.reference_prefixes
            or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
            for rule in matching
        ):
            raise ValueError(f"{kind.value} reference is not allowed by manufacturing proof policy")

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

    first = run_manufacturing_reality_benchmark()
    second = run_manufacturing_reality_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("manufacturing reality benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("manufacturing reality benchmark is not deterministic")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    expected_digest = _sha({
        "benchmark_version": first["benchmark_version"],
        "checks": first["checks"],
        "report": first["report"],
    })
    if len(benchmark_digest) != 64 or benchmark_digest != expected_digest:
        raise ValueError("manufacturing reality benchmark digest verification failed")

    receipt_digest = _sha({
        "revision": revision,
        "engine_sha256": engine_digest,
        "benchmark_sha256": benchmark_digest,
        "capability_id": _CAPABILITY_ID,
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0
    for kind, route in _ROUTE.items():
        reference = references[kind]
        receipt_id = f"manufacturing:{revision[:12]}:{kind.value}"
        previous = existing.get(receipt_id)
        if previous is not None:
            if not _same_receipt(
                previous,
                kind=kind,
                digest=receipt_digest,
                reference=reference,
                revision=revision,
            ):
                raise ValueError("deterministic manufacturing receipt_id collision")
            reused += 1
            continue
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
        raise ValueError("trusted maturity audit rejected manufacturing attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during manufacturing attestation")

    return ManufacturingRealityAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        benchmark_sha256=benchmark_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
