"""Trusted deterministic EXECUTION/REPRODUCIBILITY attestor for #69.

The frozen benchmark exercises RANGE, CONSERVATION and RATE_LIMIT constraints
with explicit measured observations, then runs a negative control proving that
a SIMULATION row cannot satisfy a real-measurement requirement merely because
its number falls inside the requested range.  Receipts prove software execution
and deterministic replay only; they do not prove sensor authenticity, hardware
truth, or physical truth.
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

from . import physical_reality as physical
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


_CAPABILITY_ID = 69
_ENGINE_SUBJECT = "research_engine/physical_reality.py"
_BENCHMARK_VERSION = "physical-reality-execution-v1"
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


def run_physical_reality_benchmark() -> Mapping[str, Any]:
    observations = (
        physical.PhysicalObservation(
            "mass_in", "mass", 5.0, "kg", "MEASURED", "benchmark:mass-in", independent=True
        ),
        physical.PhysicalObservation(
            "mass_out", "mass", 5.0, "kg", "CALIBRATED_MEASUREMENT", "benchmark:mass-out", independent=True
        ),
        physical.PhysicalObservation(
            "temp_t0", "temperature", 20.0, "C", "MEASURED", "benchmark:temp0", 0.0, True
        ),
        physical.PhysicalObservation(
            "temp_t1", "temperature", 25.0, "C", "MEASURED", "benchmark:temp1", 10.0, True
        ),
    )
    constraints = (
        physical.PhysicalConstraint(
            "mass_conservation",
            "CONSERVATION",
            ("mass_in", "mass_out"),
            "kg",
            coefficients={"mass_in": 1.0, "mass_out": -1.0},
            target=0.0,
            tolerance=0.0,
            require_real_measurement=True,
        ),
        physical.PhysicalConstraint(
            "temperature_range",
            "RANGE",
            ("temp_t0",),
            "C",
            lower=0.0,
            upper=100.0,
            require_real_measurement=True,
        ),
        physical.PhysicalConstraint(
            "temperature_rate",
            "RATE_LIMIT",
            ("temp_t0", "temp_t1"),
            "C",
            max_abs_rate=1.0,
            require_real_measurement=True,
        ),
    )
    positive = physical.audit_physical_reality(
        observations=observations,
        constraints=constraints,
    )

    negative = physical.audit_physical_reality(
        observations=(
            physical.PhysicalObservation(
                "sim_pressure",
                "pressure",
                50.0,
                "kPa",
                "SIMULATION",
                "benchmark:simulation-pressure",
            ),
        ),
        constraints=(
            physical.PhysicalConstraint(
                "pressure_real_only",
                "RANGE",
                ("sim_pressure",),
                "kPa",
                lower=0.0,
                upper=100.0,
                require_real_measurement=True,
            ),
        ),
    )
    negative_audit = negative.audits[0]
    checks = {
        "positive_calculations_pass": positive.all_calculations_passed is True,
        "positive_evidence_sufficient": positive.all_evidence_sufficient is True,
        "positive_constraints_verified": positive.all_constraints_verified is True,
        "conservation_exact": math.isclose(
            float(positive.audits[0].calculated_value), 0.0, rel_tol=0.0, abs_tol=1e-12
        ),
        "rate_exact": math.isclose(
            float(positive.audits[2].calculated_value), 0.5, rel_tol=0.0, abs_tol=1e-12
        ),
        "simulation_numeric_passes": negative_audit.calculation_passed is True,
        "simulation_evidence_blocked": (
            negative_audit.evidence_sufficient is False
            and negative_audit.verified_constraint is False
            and "real_measurement_missing" in negative_audit.blockers
        ),
        "truth_boundary": (
            positive.simulation_promoted_to_measurement is False
            and positive.hardware_authenticity_proven is False
            and positive.physical_truth_proven is False
            and negative.simulation_promoted_to_measurement is False
            and negative.physical_truth_proven is False
        ),
    }
    payload = {
        "benchmark_version": _BENCHMARK_VERSION,
        "checks": checks,
        "positive": asdict(positive),
        "negative_control": asdict(negative),
        "hardware_authenticity_proven": False,
        "physical_truth_proven": False,
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


@dataclass(frozen=True)
class PhysicalRealityExecutionAttestation:
    revision: str
    engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    hardware_authenticity_proven: bool = False
    physical_truth_proven: bool = False


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


def attest_physical_reality_execution(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    observation_id: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> PhysicalRealityExecutionAttestation:
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
        raise ValueError("physical reality attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _ENGINE_SUBJECT)
    imported_engine = Path(str(physical.__file__)).resolve(strict=True)
    audited_engine = (root / _ENGINE_SUBJECT).resolve(strict=True)
    if imported_engine != audited_engine:
        raise ValueError("Physical Reality runtime is not loaded from the audited repository")

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

    first = run_physical_reality_benchmark()
    second = run_physical_reality_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("physical reality benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("physical reality benchmark is not deterministic")
    if first.get("hardware_authenticity_proven") is not False:
        raise ValueError("software benchmark must not claim hardware authenticity")
    if first.get("physical_truth_proven") is not False:
        raise ValueError("software benchmark must not claim physical truth")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    payload_for_digest = {
        key: value for key, value in first.items()
        if key not in {"benchmark_passed", "benchmark_sha256"}
    }
    if len(benchmark_digest) != 64 or benchmark_digest != _sha(payload_for_digest):
        raise ValueError("physical reality benchmark digest verification failed")

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
        receipt_id = f"physical-reality:{revision[:12]}:{kind.value}"
        previous = existing.get(receipt_id)
        if previous is not None:
            if not _same_receipt(
                previous,
                kind=kind,
                digest=receipt_digest,
                reference=reference,
                revision=revision,
            ):
                raise ValueError("deterministic physical-reality receipt_id collision")
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
        raise ValueError("physical reality attestation did not account for every proof route")

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
        raise ValueError("trusted maturity audit rejected physical reality attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "").strip().lower() != revision
    ):
        raise ValueError("repository changed during physical reality attestation")

    return PhysicalRealityExecutionAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        benchmark_sha256=benchmark_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
