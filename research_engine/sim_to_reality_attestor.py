"""Trusted external hardware attestation for capability #127.

The software evaluator in :mod:`research_engine.sim_to_reality` intentionally
cannot close the physical gap.  This verifier accepts a short-lived HMAC-signed
receipt from a protected hardware-observer environment, binds it to the exact
clean Git revision and exact deterministic gap report, checks repeated physical
sessions plus safety/calibration references, then mints only the policy-approved
EXECUTION, REPRODUCIBILITY, HARDWARE and SAFETY proof classes.

Tests can prove verifier behavior with synthetic keys; they are not real hardware
proof. Production keys and receipts must originate outside the repository/PR.
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
from typing import Any, Mapping, Sequence, Tuple

from utils.release_identity import repository_identity

from .capability_registry import ProofKind
from .maturity_auditor import (
    TrustedMaturityAudit,
    _parse_policy,
    _read_policy_bytes,
    _tracked_index,
    audit_repository_maturity,
)
from .maturity_proof import ProofLedger
from .sim_to_reality import verify_report_hash


_CAPABILITY_ID = 127
_SCHEMA_VERSION = 1
_MAX_BYTES = 2 * 1024 * 1024
_MAX_AGE_SECONDS = 2 * 60 * 60
_MAX_FUTURE_SKEW_SECONDS = 5 * 60
_GIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_SUBJECT = "sim-to-reality-hardware-validation"
_VERIFIER = "trusted-hardware-observer"
_PREFIX = "sim-to-reality:"
_REQUIRED: Tuple[ProofKind, ...] = (
    ProofKind.EXECUTION,
    ProofKind.REPRODUCIBILITY,
    ProofKind.HARDWARE,
    ProofKind.SAFETY,
)


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
        raise ValueError("attestation payload must be finite JSON") from exc


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


def _read_json(path: Path, label: str) -> tuple[Mapping[str, Any], bytes]:
    try:
        stat = path.stat()
    except OSError as exc:
        raise ValueError(f"{label} cannot be read") from exc
    if not path.is_file() or not 1 <= stat.st_size <= _MAX_BYTES:
        raise ValueError(f"{label} size is invalid")
    data = path.read_bytes()
    if len(data) != stat.st_size:
        raise ValueError(f"{label} changed during read")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value, data


def _outside_repo(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return False
    except ValueError:
        return True


def _safe_string_list(value: object, field: str, *, minimum: int = 1) -> Tuple[str, ...]:
    if not isinstance(value, list) or not minimum <= len(value) <= 1000:
        raise ValueError(f"{field} must be a bounded list")
    rows = tuple(_safe_id(item, field) for item in value)
    if len(set(rows)) != len(rows):
        raise ValueError(f"{field} values must be distinct")
    return tuple(sorted(rows))


@dataclass(frozen=True)
class ValidatedHardwareReceipt:
    revision: str
    created_at_epoch: int
    report_hash: str
    observer_id: str
    hardware_system_id: str
    session_ids: Tuple[str, ...]
    receipt_sha256: str


@dataclass(frozen=True)
class SimToRealityProofAttestation:
    revision: str
    hardware_receipt_sha256: str
    report_hash: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit


def validate_hardware_attestation(
    *,
    report_path: str | os.PathLike[str],
    hardware_receipt_path: str | os.PathLike[str],
    hardware_attestation_key: bytes,
    expected_revision: str,
    now: float,
) -> ValidatedHardwareReceipt:
    if not isinstance(hardware_attestation_key, (bytes, bytearray)) or len(hardware_attestation_key) < 32:
        raise ValueError("hardware_attestation_key must contain at least 32 bytes")
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    revision = str(expected_revision or "").strip().lower()
    if not _GIT_RE.fullmatch(revision):
        raise ValueError("expected_revision must be a full lowercase Git SHA")

    report, _report_bytes = _read_json(Path(report_path).expanduser().resolve(), "gap report")
    if not verify_report_hash(report):
        raise ValueError("gap report hash verification failed")
    if report.get("software_fit_passed") is not True:
        raise ValueError("gap report software fit did not pass")
    if report.get("structure_sufficient") is not True:
        raise ValueError("gap report physical holdout structure is insufficient")
    if report.get("threshold_sensitive") is not False:
        raise ValueError("gap report conclusion is threshold-sensitive")
    if report.get("gap_closed") is not False or report.get("hardware_validated") is not False:
        raise ValueError("software report must not pre-claim physical closure")
    if report.get("external_hardware_attestation_required") is not True:
        raise ValueError("gap report lost external-hardware boundary")
    report_hash = _safe_sha(report.get("report_hash"), "report_hash")
    report_sessions = _safe_string_list(report.get("sessions"), "report sessions", minimum=2)

    receipt, receipt_bytes = _read_json(
        Path(hardware_receipt_path).expanduser().resolve(),
        "hardware attestation receipt",
    )
    expected_keys = {
        "schema_version",
        "created_at_epoch",
        "implementation_revision",
        "report_hash",
        "observer_id",
        "hardware_system_id",
        "session_ids",
        "calibration_references",
        "safety_review_hash",
        "emergency_stop_test_hash",
        "execution_observed",
        "reproduction_passed",
        "hardware_observation_complete",
        "safety_gate_passed",
        "truth_proven",
        "signature",
    }
    if set(receipt) != expected_keys:
        raise ValueError("hardware attestation receipt schema is invalid")
    if receipt.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported hardware attestation schema_version")
    created = receipt.get("created_at_epoch")
    if type(created) is not int or created <= 0:
        raise ValueError("hardware receipt created_at_epoch is invalid")
    if created > current_time + _MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("hardware attestation receipt is from the future")
    if current_time - created > _MAX_AGE_SECONDS:
        raise ValueError("hardware attestation receipt is stale")
    receipt_revision = str(receipt.get("implementation_revision") or "").strip().lower()
    if receipt_revision != revision:
        raise ValueError("hardware attestation revision does not match current Git HEAD")
    if _safe_sha(receipt.get("report_hash"), "receipt report_hash") != report_hash:
        raise ValueError("hardware attestation does not bind the exact gap report")

    observer_id = _safe_id(receipt.get("observer_id"), "observer_id")
    hardware_system_id = _safe_id(receipt.get("hardware_system_id"), "hardware_system_id")
    sessions = _safe_string_list(receipt.get("session_ids"), "session_ids", minimum=2)
    if sessions != report_sessions:
        raise ValueError("hardware session_ids do not match gap report")
    _safe_string_list(receipt.get("calibration_references"), "calibration_references")
    _safe_sha(receipt.get("safety_review_hash"), "safety_review_hash")
    _safe_sha(receipt.get("emergency_stop_test_hash"), "emergency_stop_test_hash")

    required_true = (
        "execution_observed",
        "reproduction_passed",
        "hardware_observation_complete",
        "safety_gate_passed",
    )
    if any(receipt.get(field) is not True for field in required_true):
        raise ValueError("hardware attestation did not pass all required physical gates")
    if receipt.get("truth_proven") is not False:
        raise ValueError("hardware attestation must not claim truth_proven")

    signature = str(receipt.get("signature") or "").strip().lower()
    if not _SHA_RE.fullmatch(signature):
        raise ValueError("hardware attestation signature is invalid")
    unsigned = dict(receipt)
    unsigned.pop("signature", None)
    expected_signature = hmac.new(
        bytes(hardware_attestation_key),
        _canonical(unsigned),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("hardware attestation signature verification failed")

    return ValidatedHardwareReceipt(
        revision=revision,
        created_at_epoch=created,
        report_hash=report_hash,
        observer_id=observer_id,
        hardware_system_id=hardware_system_id,
        session_ids=sessions,
        receipt_sha256=_sha(receipt_bytes),
    )


def _required_policy_rules(policy) -> None:
    for kind in _REQUIRED:
        allowed = any(
            rule.capability_id == _CAPABILITY_ID
            and rule.proof_kind == kind
            and _SUBJECT in rule.subjects
            and _VERIFIER in rule.verifiers
            and _PREFIX in rule.reference_prefixes
            for rule in policy.rules
        )
        if not allowed:
            raise ValueError(
                f"committed proof policy does not authorize capability 127 {kind.value} attestation"
            )


def _existing_adds(ledger: ProofLedger) -> Mapping[str, Mapping[str, Any]]:
    return {
        str(row.get("receipt_id") or ""): row
        for row in ledger._events()  # noqa: SLF001 - same-package trusted attestor
        if row.get("event_type") == "ADD"
    }


def _same(
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


def attest_sim_to_reality_proofs(
    *,
    repo_root: str | os.PathLike[str],
    report_path: str | os.PathLike[str],
    hardware_receipt_path: str | os.PathLike[str],
    hardware_attestation_key: bytes,
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> SimToRealityProofAttestation:
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, target):
        raise ValueError("maturity ledger must live outside the audited repository")
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")

    identity = repository_identity(root)
    revision = str(identity.get("revision") or "")
    if not identity.get("available") or not identity.get("clean") or not revision:
        raise ValueError("sim-to-reality attestation requires a clean Git checkout")

    receipt = validate_hardware_attestation(
        report_path=report_path,
        hardware_receipt_path=hardware_receipt_path,
        hardware_attestation_key=hardware_attestation_key,
        expected_revision=revision,
        now=current_time,
    )
    tracked = _tracked_index(root)
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    _required_policy_rules(policy)

    exists = target.exists() and target.stat().st_size > 0
    if exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or not _GIT_RE.fullmatch(prior):
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(target), integrity_key=integrity_key)
        if not continuity.verify_chain(
            anchor_token=prior_anchor_token,
            current_revision=prior,
        ):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    ledger = ProofLedger(str(target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    reference = _PREFIX + receipt.report_hash
    added = 0
    reused = 0
    for kind in _REQUIRED:
        receipt_id = f"sim2real:c127:{kind.value}:{receipt.receipt_sha256[:16]}"
        previous = existing.get(receipt_id)
        if previous is not None:
            if not _same(
                previous,
                kind=kind,
                digest=receipt.receipt_sha256,
                reference=reference,
                revision=revision,
            ):
                raise ValueError("deterministic sim-to-reality receipt_id collision")
            reused += 1
            continue
        ledger.add(
            receipt_id=receipt_id,
            capability_id=_CAPABILITY_ID,
            proof_kind=kind,
            subject=_SUBJECT,
            subject_sha256=receipt.receipt_sha256,
            verifier=_VERIFIER,
            observed_at=current_time,
            reference=reference,
            implementation_revision=revision,
        )
        added += 1

    anchor = ledger.create_anchor(current_revision=revision, issued_at=current_time)
    audit = audit_repository_maturity(
        repo_root=root,
        ledger_path=target,
        integrity_key=integrity_key,
        anchor_token=anchor,
        now=current_time,
        policy_path=policy_path,
    )
    return SimToRealityProofAttestation(
        revision=revision,
        hardware_receipt_sha256=receipt.receipt_sha256,
        report_hash=receipt.report_hash,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
