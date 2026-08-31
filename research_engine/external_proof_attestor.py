"""Strict facade for generic external maturity-proof attestation.

The heavy proof-kind validators live in :mod:`external_proof_attestor_core`.
This facade adds two representation-boundary guarantees before those validators
or the proof ledger are reached:

1. ``reference`` must already use one canonical safe-token spelling. Whitespace,
   control characters and normalization-by-stripping are rejected rather than
   silently accepted.
2. Receipt identity is the SHA-256 of canonical signed JSON, not the raw file
   bytes. Pretty-printing or JSON key reordering therefore cannot create a
   second proof identity for the same signed semantic receipt.

The facade does not weaken any core evidence schema, revision, policy, HMAC,
anchor, external-observation or truth-boundary checks.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from .external_proof_attestor_core import (
    ExternalEvidenceReceipt,
    ExternalProofAttestation,
    _canonical,
    _outside_repo,
    _read_bounded_json,
    _safe_id,
    attest_external_proof as _core_attest_external_proof,
    sign_external_receipt,
    validate_external_evidence_receipt as _core_validate_external_evidence_receipt,
)


__all__ = [
    "ExternalEvidenceReceipt",
    "ExternalProofAttestation",
    "sign_external_receipt",
    "validate_external_evidence_receipt",
    "attest_external_proof",
]


def _strict_reference(value: Mapping[str, Any]) -> str:
    raw = value.get("reference")
    if not isinstance(raw, str):
        raise ValueError("reference must be a string")
    if raw != raw.strip():
        raise ValueError("reference must use canonical safe-token spelling")
    reference = _safe_id(raw, "reference")
    if reference != raw:
        raise ValueError("reference must use canonical safe-token spelling")
    return reference


def _canonical_receipt(path: str | os.PathLike[str]) -> tuple[Mapping[str, Any], bytes, str]:
    value, _raw = _read_bounded_json(Path(path).expanduser().resolve())
    _strict_reference(value)
    encoded = _canonical(value)
    return value, encoded, hashlib.sha256(encoded).hexdigest()


def validate_external_evidence_receipt(
    path: str | os.PathLike[str],
    *,
    repo_root: str | os.PathLike[str],
    expected_revision: str,
    verifier_key: bytes,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
) -> ExternalEvidenceReceipt:
    """Validate a receipt and return its canonical semantic identity."""
    _value, _encoded, canonical_sha256 = _canonical_receipt(path)
    parsed = _core_validate_external_evidence_receipt(
        path,
        repo_root=repo_root,
        expected_revision=expected_revision,
        verifier_key=verifier_key,
        now=now,
        policy_path=policy_path,
    )
    return replace(parsed, receipt_sha256=canonical_sha256)


def attest_external_proof(
    *,
    repo_root: str | os.PathLike[str],
    evidence_receipt_path: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    ledger_integrity_key: bytes,
    verifier_key: bytes,
    now: float,
    prior_anchor_token: str = "",
    prior_revision: str = "",
    policy_path: str = "config/maturity_proof_policy.json",
) -> ExternalProofAttestation:
    """Attest one canonicalized signed receipt without changing its semantics."""
    root = Path(repo_root).resolve(strict=True)
    source = Path(evidence_receipt_path).expanduser().resolve()
    if not _outside_repo(root, source):
        raise ValueError("external evidence receipt must live outside the audited repository")

    parsed = validate_external_evidence_receipt(
        source,
        repo_root=root,
        expected_revision=str(
            __import__("utils.release_identity", fromlist=["repository_identity"])
            .repository_identity(root)
            .get("revision")
            or ""
        ),
        verifier_key=verifier_key,
        now=now,
        policy_path=policy_path,
    )
    _value, canonical_bytes, canonical_sha256 = _canonical_receipt(source)
    if parsed.receipt_sha256 != canonical_sha256:
        raise ValueError("canonical external receipt identity changed during validation")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".rv-ai-external-proof-",
        suffix=".json",
    )
    try:
        try:
            os.fchmod(descriptor, 0o600)
        except (AttributeError, OSError):
            pass
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        result = _core_attest_external_proof(
            repo_root=root,
            evidence_receipt_path=temporary_name,
            ledger_path=ledger_path,
            ledger_integrity_key=ledger_integrity_key,
            verifier_key=verifier_key,
            now=now,
            prior_anchor_token=prior_anchor_token,
            prior_revision=prior_revision,
            policy_path=policy_path,
        )
        if result.receipt_sha256 != canonical_sha256:
            raise ValueError("core attestation did not bind canonical receipt identity")
        return result
    finally:
        try:
            os.remove(temporary_name)
        except OSError:
            pass
