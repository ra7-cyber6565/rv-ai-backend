"""Trusted software execution attestor for capability #97 Holdout Vault.

The benchmark exercises the application-level holdout state machine on a clean,
revision-bound checkout.  It proves only deterministic software properties:
dataset commitment checking, candidate/protocol freeze, evaluator capability
token enforcement, one-shot evaluation, token burn and result commitment.

It deliberately does NOT claim OS/process isolation, KMS-backed secret custody,
protection from a filesystem administrator, or physical/live secrecy.  Those
remain external security/deployment properties and must never be inferred from
this attestor.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from utils.release_identity import repository_identity

from .capability_registry import ProofKind
from .holdout_vault import HoldoutVault
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


_CAPABILITY_ID = 97
_REQUIRED = (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY)
_SUBJECT = "holdout-vault-benchmark"
_VERIFIER = "trusted-operator"
_ENGINE_SUBJECT = "research_engine/holdout_vault.py"
_BENCHMARK_VERSION = "holdout-vault-benchmark-v1"
_DATASET = b'{"rows":[[1,2],[3,4],[5,6]],"label":"sealed-fixture-v1"}'


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


def _error_name(callable_obj) -> str:
    try:
        callable_obj()
    except Exception as exc:  # exact class is part of the benchmark payload
        return type(exc).__name__
    return "ACCEPTED"


def _evaluate_fixture(dataset: bytes, packet: Mapping[str, Any]) -> Mapping[str, Any]:
    # The evaluator sees bytes only at the one-shot evaluation boundary.  The
    # result intentionally contains commitments/aggregate facts, never raw data.
    return {
        "dataset_sha256": hashlib.sha256(dataset).hexdigest(),
        "dataset_bytes": len(dataset),
        "candidate_id": str((packet.get("candidate") or {}).get("candidate_id") or ""),
        "protocol_hash": str((packet.get("candidate") or {}).get("protocol_hash") or ""),
        "fixture_score": 21,
    }


def _single_run(directory: str, *, vault_id: str) -> Mapping[str, Any]:
    vault = HoldoutVault(directory)
    creation = vault.create(
        vault_id,
        _DATASET,
        dataset_label="locked benchmark fixture",
        metadata={"benchmark": _BENCHMARK_VERSION},
    )
    builder_before = vault.builder_view(vault_id)
    frozen = vault.freeze_candidate(
        vault_id,
        candidate_id="candidate-v1",
        implementation_hash="a" * 64,
        protocol_hash="b" * 64,
        evaluator_instructions={"metric": "fixture_score", "higher_is_better": True},
        theory_blind=True,
    )

    wrong_token_error = _error_name(lambda: vault.evaluate(
        vault_id,
        evaluator_token="definitely-wrong-token",
        evaluator=_evaluate_fixture,
    ))
    refreeze_error = _error_name(lambda: vault.freeze_candidate(
        vault_id,
        candidate_id="candidate-v2",
        implementation_hash="c" * 64,
        protocol_hash="d" * 64,
        evaluator_instructions={"metric": "fixture_score"},
    ))

    receipt = vault.evaluate(
        vault_id,
        evaluator_token=creation.evaluator_token,
        evaluator=_evaluate_fixture,
    )
    token_reuse_error = _error_name(lambda: vault.evaluate(
        vault_id,
        evaluator_token=creation.evaluator_token,
        evaluator=_evaluate_fixture,
    ))
    second_eval_error = _error_name(lambda: vault.evaluate(
        vault_id,
        evaluator_token="another-token",
        evaluator=_evaluate_fixture,
    ))
    builder_after = vault.builder_view(vault_id)
    stored = vault.evaluation_receipt(vault_id) or {}

    # A separate vault proves that the committed holdout bytes are checked at
    # evaluation time.  We intentionally mutate the private fixture file only
    # inside this adversarial benchmark.
    tamper = HoldoutVault(directory)
    tamper_creation = tamper.create(
        f"{vault_id}-tamper",
        _DATASET,
        dataset_label="tamper fixture",
    )
    tamper.freeze_candidate(
        f"{vault_id}-tamper",
        candidate_id="candidate-v1",
        implementation_hash="a" * 64,
        protocol_hash="b" * 64,
        evaluator_instructions={"metric": "fixture_score"},
    )
    data_path = tamper._data_path(f"{vault_id}-tamper")  # noqa: SLF001
    with open(data_path, "ab") as handle:
        handle.write(b"tamper")
    dataset_tamper_error = _error_name(lambda: tamper.evaluate(
        f"{vault_id}-tamper",
        evaluator_token=tamper_creation.evaluator_token,
        evaluator=_evaluate_fixture,
    ))

    expected_dataset = hashlib.sha256(_DATASET).hexdigest()
    expected_result = {
        "dataset_sha256": expected_dataset,
        "dataset_bytes": len(_DATASET),
        "candidate_id": "candidate-v1",
        "protocol_hash": "b" * 64,
        "fixture_score": 21,
    }
    expected_result_hash = _sha(expected_result)

    checks = {
        "builder_view_never_contains_secret_token_or_dataset": (
            "evaluator_token" not in builder_before
            and "token_hash" not in builder_before
            and "dataset" not in builder_before
            and "evaluator_token" not in builder_after
            and "token_hash" not in builder_after
            and "dataset" not in builder_after
        ),
        "dataset_commitment_matches_fixture": creation.dataset_sha256 == expected_dataset,
        "candidate_and_protocol_are_frozen": (
            frozen.get("candidate_id") == "candidate-v1"
            and frozen.get("protocol_hash") == "b" * 64
            and len(str(frozen.get("freeze_hash") or "")) == 64
            and refreeze_error == "ValueError"
        ),
        "wrong_token_is_rejected": wrong_token_error == "PermissionError",
        "one_shot_evaluation_and_token_burn_are_enforced": (
            token_reuse_error == "ValueError" and second_eval_error == "ValueError"
        ),
        "dataset_tamper_is_rejected": dataset_tamper_error == "ValueError",
        "result_commitment_matches": (
            receipt.dataset_sha256 == expected_dataset
            and receipt.protocol_hash == "b" * 64
            and dict(receipt.result) == expected_result
            and receipt.result_hash == expected_result_hash
            and stored.get("result_hash") == expected_result_hash
        ),
        "final_state_is_evaluated": (
            builder_after.get("state") == "EVALUATED"
            and builder_after.get("evaluated") is True
            and builder_after.get("candidate_frozen") is True
        ),
        "vault_dataset_integrity_remains_valid": vault.verify_integrity(vault_id) is True,
    }
    payload = {
        "benchmark_version": _BENCHMARK_VERSION,
        "checks": checks,
        "dataset_sha256": expected_dataset,
        "candidate_freeze_hash": str(frozen.get("freeze_hash") or ""),
        "result_hash": expected_result_hash,
        "wrong_token_error": wrong_token_error,
        "refreeze_error": refreeze_error,
        "token_reuse_error": token_reuse_error,
        "second_eval_error": second_eval_error,
        "dataset_tamper_error": dataset_tamper_error,
        "application_level_boundary": True,
        "os_process_isolation_observed": False,
        "kms_backed_secret_observed": False,
        "filesystem_admin_resistance_observed": False,
        "truth_proven": False,
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


def run_holdout_vault_benchmark() -> Mapping[str, Any]:
    """Run a deterministic locked lifecycle/adversarial benchmark."""
    with tempfile.TemporaryDirectory(prefix="rv_holdout_benchmark_") as directory:
        return _single_run(directory, vault_id="locked-holdout-v1")


@dataclass(frozen=True)
class HoldoutVaultExecutionAttestation:
    revision: str
    engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    os_process_isolation_observed: bool = False
    kms_backed_secret_observed: bool = False
    filesystem_admin_resistance_observed: bool = False
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


def attest_holdout_vault_execution(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> HoldoutVaultExecutionAttestation:
    """Mint only revision-bound EXECUTION/REPRODUCIBILITY receipts for #97."""
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
        raise ValueError("holdout attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _ENGINE_SUBJECT)
    import research_engine.holdout_vault as loaded_holdout
    if Path(str(loaded_holdout.__file__)).resolve(strict=True) != (root / _ENGINE_SUBJECT).resolve(strict=True):
        raise ValueError("holdout runtime is not loaded from the audited repository")

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
            raise ValueError(f"committed proof policy has no trusted holdout {kind.value} rule")
        if not any(
            not rule.reference_prefixes
            or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
            for rule in matching
        ):
            raise ValueError("run_reference is not allowed by holdout proof policy")

    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or not prior:
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not continuity.verify_chain(anchor_token=prior_anchor_token, current_revision=prior):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    first = run_holdout_vault_benchmark()
    second = run_holdout_vault_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("holdout-vault benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("holdout-vault benchmark is not deterministic")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    digest_payload = {
        key: value for key, value in first.items()
        if key not in {"benchmark_passed", "benchmark_sha256"}
    }
    if len(benchmark_digest) != 64 or benchmark_digest != _sha(digest_payload):
        raise ValueError("holdout-vault benchmark digest verification failed")

    receipt_digest = _sha({
        "revision": revision,
        "engine_sha256": engine_digest,
        "benchmark_sha256": benchmark_digest,
        "subject": _SUBJECT,
        "capability": _CAPABILITY_ID,
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0
    for kind in _REQUIRED:
        receipt_id = f"holdout-vault:{revision[:12]}:{kind.value}"
        previous = existing.get(receipt_id)
        if previous is not None:
            if not _same_receipt(
                previous,
                kind=kind,
                digest=receipt_digest,
                reference=reference,
                revision=revision,
            ):
                raise ValueError("deterministic holdout-vault receipt_id collision")
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
        raise ValueError("trusted maturity audit rejected holdout-vault attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during holdout-vault attestation")

    return HoldoutVaultExecutionAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        benchmark_sha256=benchmark_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
