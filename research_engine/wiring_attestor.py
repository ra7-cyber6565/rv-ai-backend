"""Trusted GitHub-Foundation attestation for ``production_wiring`` proofs.

A passing unit test is not automatically production wiring.  This attestor is a
separate, opt-in trusted step that accepts only committed policy rules whose
subject is an exact focused integration-test file executed by the Foundation
receipt for the same clean Git revision.  The normal CODE/TEST attestor remains
unchanged and cannot mint WIRING/EXECUTION/SAFETY/LIVE/HARDWARE evidence.

The resulting receipt is revision-bound and HMAC-ledger anchored.  It proves the
specified integration test was part of a green Foundation run for that revision;
it does *not* prove scientific truth, live operation or real-world effectiveness.
"""
from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Tuple

from utils.release_identity import repository_identity

from .capability_registry import ProofKind
from .maturity_attestor import (
    _existing_adds,
    _outside_repo,
    _read_bounded_json,
    _safe_reference,
    _validate_stage,
    validate_foundation_receipt,
)
from .maturity_auditor import (
    TrustedMaturityAudit,
    _hash_tracked_regular,
    _parse_policy,
    _read_policy_bytes,
    _tracked_index,
    audit_repository_maturity,
)
from .maturity_proof import ProofLedger


@dataclass(frozen=True)
class WiringAttestation:
    revision: str
    foundation_receipt_sha256: str
    receipts_added: int
    receipts_reused: int
    focused_tests: Tuple[str, ...]
    anchor_token: str
    audit: TrustedMaturityAudit


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _focused_tests_from_receipt(path: str | os.PathLike[str]) -> Tuple[str, ...]:
    value, _raw = _read_bounded_json(Path(path).expanduser().resolve())
    stages = value.get("stages")
    if not isinstance(stages, list):
        raise ValueError("Foundation receipt stages are invalid")
    commands = {}
    for stage in stages:
        name, command = _validate_stage(stage)
        commands[name] = command
    focused = commands.get("focused_pytest")
    if not focused or len(focused) < 5 or tuple(focused[1:4]) != ("-m", "pytest", "-q"):
        raise ValueError("Foundation focused_pytest command is unavailable")
    tests = tuple(str(item) for item in focused[4:])
    if not tests or any(
        not item.startswith("tests/test_") or not item.endswith(".py")
        for item in tests
    ):
        raise ValueError("Foundation focused_pytest file set is invalid")
    if len(set(tests)) != len(tests):
        raise ValueError("Foundation focused_pytest contains duplicate files")
    return tests


def _same_wiring_receipt(
    row: Mapping[str, Any],
    *,
    capability_id: int,
    subject: str,
    subject_sha256: str,
    reference: str,
    revision: str,
) -> bool:
    expected = {
        "capability_id": capability_id,
        "proof_kind": ProofKind.WIRING.value,
        "subject": subject,
        "subject_sha256": subject_sha256,
        "verifier": "github-actions",
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_foundation_wiring_proofs(
    *,
    repo_root: str | os.PathLike[str],
    foundation_receipt_path: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> WiringAttestation:
    """Mint only policy-approved revision-bound WIRING receipts."""
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
        raise ValueError("wiring attestation requires a clean Git checkout")

    receipt = validate_foundation_receipt(
        foundation_receipt_path,
        expected_revision=revision,
        now=current_time,
    )
    focused_tests = _focused_tests_from_receipt(foundation_receipt_path)
    focused_set = set(focused_tests)
    tracked = _tracked_index(root)
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    eligible_rules = tuple(
        rule for rule in policy.rules
        if rule.proof_kind is ProofKind.WIRING and "github-actions" in rule.verifiers
    )
    if not eligible_rules:
        raise ValueError("committed proof policy has no github-actions WIRING rules")

    for rule in eligible_rules:
        if rule.reference_prefixes and not any(
            reference.startswith(prefix) for prefix in rule.reference_prefixes
        ):
            raise ValueError("run_reference is not allowed by WIRING proof policy")
        for subject in rule.subjects:
            if subject not in focused_set:
                raise ValueError(
                    f"WIRING proof subject was not executed by focused_pytest: {subject}"
                )
            if not subject.startswith("tests/test_") or not subject.endswith(".py"):
                raise ValueError("WIRING proof subject must be a focused integration test file")

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

    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = 0
    reused = 0
    for rule in eligible_rules:
        for subject in rule.subjects:
            digest = _hash_tracked_regular(root, tracked, subject)
            receipt_id = (
                f"ghawire:{receipt.sha256[:12]}:c{rule.capability_id}:"
                f"{_sha(subject.encode('utf-8'))[:12]}"
            )
            previous = existing.get(receipt_id)
            if previous is not None:
                if not _same_wiring_receipt(
                    previous,
                    capability_id=rule.capability_id,
                    subject=subject,
                    subject_sha256=digest,
                    reference=reference,
                    revision=revision,
                ):
                    raise ValueError("deterministic WIRING receipt_id collision")
                reused += 1
                continue
            ledger.add(
                receipt_id=receipt_id,
                capability_id=rule.capability_id,
                proof_kind=ProofKind.WIRING,
                subject=subject,
                subject_sha256=digest,
                verifier="github-actions",
                observed_at=current_time,
                reference=reference,
                implementation_revision=revision,
            )
            added += 1

    if added + reused <= 0:
        raise ValueError("Foundation wiring attestation produced no receipts")

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
        raise ValueError("trusted maturity audit rejected WIRING attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during WIRING attestation")

    return WiringAttestation(
        revision=revision,
        foundation_receipt_sha256=receipt.sha256,
        receipts_added=added,
        receipts_reused=reused,
        focused_tests=focused_tests,
        anchor_token=anchor,
        audit=audit,
    )
