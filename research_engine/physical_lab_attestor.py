"""Trusted external live-hardware attestation for capabilities #125 and #126.

The in-process :mod:`physical_lab_boundary` is deliberately unable to prove that
its callback touched real hardware. This module closes only the *attestation
route*: a protected external hardware-observer may submit a short-lived HMAC
receipt that binds the exact clean Git revision, exact physical boundary source
hash, repeated runtime sessions, per-session sensor/action commitments,
calibration records and safety/emergency-stop review.

Synthetic unit-test receipts prove verifier behaviour only. They are never real
hardware evidence. Production keys and receipts must be kept outside the repo
and outside pull-request code.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

from utils.release_identity import repository_identity

from .capability_registry import ProofKind
from .maturity_auditor import (
    TrustedMaturityAudit,
    _hash_tracked_regular,
    _parse_policy,
    _read_policy_bytes,
    _tracked_index,
    audit_repository_maturity,
)
from .maturity_proof import ProofLedger


_CAPABILITIES = (125, 126)
_SCHEMA_VERSION = 1
_MAX_BYTES = 2 * 1024 * 1024
_MAX_AGE_SECONDS = 2 * 60 * 60
_MAX_FUTURE_SKEW_SECONDS = 5 * 60
_MAX_SESSIONS = 64
_GIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_BOUNDARY_PATH = "research_engine/physical_lab_boundary.py"
_REQUIRED: Tuple[ProofKind, ...] = (
    ProofKind.EXECUTION,
    ProofKind.REPRODUCIBILITY,
    ProofKind.RUNTIME,
    ProofKind.LIVE,
    ProofKind.HARDWARE,
    ProofKind.SAFETY,
)
_ROUTE_ROLE = {
    ProofKind.EXECUTION: ("execution-run", "trusted-execution-attestor", "execution"),
    ProofKind.REPRODUCIBILITY: (
        "reproducibility-run",
        "trusted-reproducibility-attestor",
        "reproducibility",
    ),
    ProofKind.RUNTIME: ("runtime-observation", "trusted-runtime-attestor", "runtime"),
    ProofKind.LIVE: ("live-observation", "trusted-live-observer", "live"),
    ProofKind.HARDWARE: ("hardware-observation", "trusted-hardware-lab", "hardware"),
    ProofKind.SAFETY: ("safety-gate", "trusted-safety-officer", "safety"),
}


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("physical-lab attestation payload must be finite JSON") from exc


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _safe_sha(value: object, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA_RE.fullmatch(text):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return text


def _route_meta(capability_id: int, kind: ProofKind) -> Tuple[str, str, str]:
    if capability_id not in _CAPABILITIES or kind not in _ROUTE_ROLE:
        raise ValueError("unsupported physical-lab proof route")
    suffix, verifier, namespace = _ROUTE_ROLE[kind]
    return (
        f"capability-{capability_id}-{suffix}",
        verifier,
        f"{namespace}:c{capability_id}:",
    )


def _outside_repo(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return False
    except ValueError:
        return True


def _read_json(path: Path, label: str) -> tuple[Mapping[str, Any], bytes]:
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError(f"{label} cannot be read") from exc
    if not path.is_file() or not 1 <= info.st_size <= _MAX_BYTES:
        raise ValueError(f"{label} size is invalid")
    data = path.read_bytes()
    if len(data) != info.st_size:
        raise ValueError(f"{label} changed during read")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value, data


def _safe_ids(value: object, field: str, *, minimum: int = 1) -> Tuple[str, ...]:
    if not isinstance(value, list) or not minimum <= len(value) <= _MAX_SESSIONS:
        raise ValueError(f"{field} must be a bounded list")
    rows = tuple(_safe_id(item, field) for item in value)
    if len(set(rows)) != len(rows):
        raise ValueError(f"{field} must contain distinct values")
    return rows


def _session_hash_map(value: object, sessions: Tuple[str, ...], field: str) -> Mapping[str, str]:
    if not isinstance(value, dict) or set(value) != set(sessions):
        raise ValueError(f"{field} must contain exactly the attested sessions")
    result: Dict[str, str] = {}
    for session in sessions:
        result[session] = _safe_sha(value.get(session), f"{field}[{session}]")
    if len(set(result.values())) != len(result):
        raise ValueError(f"{field} must prove distinct per-session commitments")
    return dict(sorted(result.items()))


def _session_action_map(value: object, sessions: Tuple[str, ...]) -> Mapping[str, Tuple[str, ...]]:
    if not isinstance(value, dict) or set(value) != set(sessions):
        raise ValueError("session_action_hashes must contain exactly the attested sessions")
    result: Dict[str, Tuple[str, ...]] = {}
    for session in sessions:
        raw = value.get(session)
        if not isinstance(raw, list) or not 1 <= len(raw) <= 1000:
            raise ValueError("each physical session must contain observed action hashes")
        hashes = tuple(_safe_sha(item, f"session_action_hashes[{session}]") for item in raw)
        if len(set(hashes)) != len(hashes):
            raise ValueError("session action hashes must be distinct within a session")
        result[session] = hashes
    return dict(sorted(result.items()))


@dataclass(frozen=True)
class ValidatedPhysicalLabReceipt:
    revision: str
    created_at_epoch: int
    live_observed_at_epoch: int
    boundary_sha256: str
    observer_id: str
    hardware_system_id: str
    session_ids: Tuple[str, ...]
    receipt_sha256: str


@dataclass(frozen=True)
class PhysicalLabProofAttestation:
    revision: str
    hardware_receipt_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit


def validate_physical_lab_attestation(
    *,
    repo_root: str | os.PathLike[str],
    hardware_receipt_path: str | os.PathLike[str],
    hardware_attestation_key: bytes,
    expected_revision: str,
    now: float,
) -> ValidatedPhysicalLabReceipt:
    if not isinstance(hardware_attestation_key, (bytes, bytearray)) or len(hardware_attestation_key) < 32:
        raise ValueError("hardware_attestation_key must contain at least 32 bytes")
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    revision = str(expected_revision or "").strip().lower()
    if not _GIT_RE.fullmatch(revision):
        raise ValueError("expected_revision must be a full lowercase Git SHA")

    root = Path(repo_root).resolve(strict=True)
    receipt_path = Path(hardware_receipt_path).expanduser().resolve()
    if not _outside_repo(root, receipt_path):
        raise ValueError("real hardware attestation receipt must live outside the audited repository")
    tracked = _tracked_index(root)
    boundary_sha = _hash_tracked_regular(root, tracked, _BOUNDARY_PATH)

    receipt, receipt_bytes = _read_json(receipt_path, "physical-lab hardware receipt")
    expected_keys = {
        "schema_version",
        "created_at_epoch",
        "live_observed_at_epoch",
        "implementation_revision",
        "boundary_sha256",
        "observer_id",
        "hardware_system_id",
        "session_ids",
        "session_sensor_chain_heads",
        "session_action_hashes",
        "calibration_references",
        "safety_review_hash",
        "emergency_stop_test_hash",
        "lab_interface_exercised",
        "sensor_loop_exercised",
        "execution_observed",
        "reproduction_passed",
        "runtime_observation_complete",
        "live_observation_complete",
        "hardware_observation_complete",
        "safety_gate_passed",
        "software_boundary_preserved",
        "truth_proven",
        "signature",
    }
    if set(receipt) != expected_keys:
        raise ValueError("physical-lab hardware receipt schema is invalid")
    if receipt.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported physical-lab hardware receipt schema_version")

    created = receipt.get("created_at_epoch")
    live_observed = receipt.get("live_observed_at_epoch")
    if type(created) is not int or created <= 0 or type(live_observed) is not int or live_observed <= 0:
        raise ValueError("hardware receipt timestamps are invalid")
    if created > current_time + _MAX_FUTURE_SKEW_SECONDS or live_observed > current_time + _MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("hardware attestation timestamp is from the future")
    if current_time - created > _MAX_AGE_SECONDS or current_time - live_observed > _MAX_AGE_SECONDS:
        raise ValueError("hardware attestation receipt or live observation is stale")
    if live_observed > created:
        raise ValueError("live observation cannot occur after receipt creation")

    receipt_revision = str(receipt.get("implementation_revision") or "").strip().lower()
    if receipt_revision != revision:
        raise ValueError("hardware attestation revision does not match current Git HEAD")
    supplied_boundary = _safe_sha(receipt.get("boundary_sha256"), "boundary_sha256")
    if supplied_boundary != boundary_sha:
        raise ValueError("hardware attestation does not bind exact physical lab boundary code")

    observer_id = _safe_id(receipt.get("observer_id"), "observer_id")
    hardware_system_id = _safe_id(receipt.get("hardware_system_id"), "hardware_system_id")
    sessions = _safe_ids(receipt.get("session_ids"), "session_ids", minimum=2)
    _session_hash_map(receipt.get("session_sensor_chain_heads"), sessions, "session_sensor_chain_heads")
    _session_action_map(receipt.get("session_action_hashes"), sessions)
    _safe_ids(receipt.get("calibration_references"), "calibration_references")
    _safe_sha(receipt.get("safety_review_hash"), "safety_review_hash")
    _safe_sha(receipt.get("emergency_stop_test_hash"), "emergency_stop_test_hash")

    required_true = (
        "lab_interface_exercised",
        "sensor_loop_exercised",
        "execution_observed",
        "reproduction_passed",
        "runtime_observation_complete",
        "live_observation_complete",
        "hardware_observation_complete",
        "safety_gate_passed",
        "software_boundary_preserved",
    )
    if any(receipt.get(field) is not True for field in required_true):
        raise ValueError("physical-lab attestation did not pass every required external gate")
    if receipt.get("truth_proven") is not False:
        raise ValueError("physical-lab attestation must not claim truth_proven")

    signature = str(receipt.get("signature") or "").strip().lower()
    if not _SHA_RE.fullmatch(signature):
        raise ValueError("physical-lab attestation signature is invalid")
    unsigned = dict(receipt)
    unsigned.pop("signature", None)
    expected_signature = hmac.new(
        bytes(hardware_attestation_key),
        _canonical(unsigned),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("physical-lab attestation signature verification failed")

    return ValidatedPhysicalLabReceipt(
        revision=revision,
        created_at_epoch=created,
        live_observed_at_epoch=live_observed,
        boundary_sha256=boundary_sha,
        observer_id=observer_id,
        hardware_system_id=hardware_system_id,
        session_ids=sessions,
        receipt_sha256=_sha(receipt_bytes),
    )


def _required_policy_rules(policy) -> None:
    for capability_id in _CAPABILITIES:
        for kind in _REQUIRED:
            subject, verifier, prefix = _route_meta(capability_id, kind)
            allowed = any(
                rule.capability_id == capability_id
                and rule.proof_kind == kind
                and subject in rule.subjects
                and verifier in rule.verifiers
                and prefix in rule.reference_prefixes
                for rule in policy.rules
            )
            if not allowed:
                raise ValueError(
                    f"committed proof policy does not authorize capability {capability_id} {kind.value} physical-lab attestation"
                )


def _existing_adds(ledger: ProofLedger) -> Mapping[str, Mapping[str, Any]]:
    return {
        str(row.get("receipt_id") or ""): row
        for row in ledger._events()  # noqa: SLF001 - trusted same-package attestor
        if row.get("event_type") == "ADD"
    }


def _same(
    row: Mapping[str, Any],
    *,
    capability_id: int,
    kind: ProofKind,
    subject: str,
    verifier: str,
    digest: str,
    reference: str,
    revision: str,
) -> bool:
    expected = {
        "capability_id": capability_id,
        "proof_kind": kind.value,
        "subject": subject,
        "subject_sha256": digest,
        "verifier": verifier,
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_physical_lab_proofs(
    *,
    repo_root: str | os.PathLike[str],
    hardware_receipt_path: str | os.PathLike[str],
    hardware_attestation_key: bytes,
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> PhysicalLabProofAttestation:
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")

    identity = repository_identity(root)
    revision = str(identity.get("revision") or "").strip().lower()
    if not identity.get("available") or not identity.get("clean") or not _GIT_RE.fullmatch(revision):
        raise ValueError("physical-lab attestation requires a clean Git checkout")

    receipt = validate_physical_lab_attestation(
        repo_root=root,
        hardware_receipt_path=hardware_receipt_path,
        hardware_attestation_key=hardware_attestation_key,
        expected_revision=revision,
        now=current_time,
    )
    tracked = _tracked_index(root)
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    _required_policy_rules(policy)

    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or not _GIT_RE.fullmatch(prior):
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not continuity.verify_chain(anchor_token=prior_anchor_token, current_revision=prior):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = 0
    reused = 0
    for capability_id in _CAPABILITIES:
        for kind in _REQUIRED:
            subject, verifier, prefix = _route_meta(capability_id, kind)
            reference = prefix + receipt.receipt_sha256
            receipt_id = f"physical-lab:c{capability_id}:{kind.value}:{receipt.receipt_sha256[:16]}"
            previous = existing.get(receipt_id)
            if previous is not None:
                if not _same(
                    previous,
                    capability_id=capability_id,
                    kind=kind,
                    subject=subject,
                    verifier=verifier,
                    digest=receipt.receipt_sha256,
                    reference=reference,
                    revision=revision,
                ):
                    raise ValueError("deterministic physical-lab receipt_id collision")
                reused += 1
                continue
            ledger.add(
                receipt_id=receipt_id,
                capability_id=capability_id,
                proof_kind=kind,
                subject=subject,
                subject_sha256=receipt.receipt_sha256,
                verifier=verifier,
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
        raise ValueError("trusted maturity audit rejected physical-lab attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "").strip().lower() != revision
    ):
        raise ValueError("repository changed during physical-lab attestation")

    return PhysicalLabProofAttestation(
        revision=revision,
        hardware_receipt_sha256=receipt.receipt_sha256,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
