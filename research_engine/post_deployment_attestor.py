"""Trusted external attestation for capabilities #87 and #88.

This verifier turns *real deployment evidence* into narrowly-scoped maturity
proofs.  It never treats an offline unit test or a stable feature distribution as
live validation.  A protected deployment observer must HMAC-sign a short-lived
receipt that binds:

* the exact clean Git revision,
* a deeply verified persisted post-deployment state snapshot,
* one exact model baseline and its complete 3+ batch history,
* live data-source and runtime identities,
* actual outcome-bearing validation windows,
* persistent-state reload, and
* two distinct deterministic replay runs reproducing the stored analyses.

Synthetic receipts in tests prove verifier behavior only; they are not runtime or
live maturity evidence.
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
from .post_deployment_integrity import verify_post_deployment_state


_SCHEMA_VERSION = 1
_MAX_BYTES = 4 * 1024 * 1024
_MAX_AGE_SECONDS = 2 * 60 * 60
_MAX_FUTURE_SKEW_SECONDS = 5 * 60
_GIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_SUBJECT = "post-deployment-live-validation"
_VERIFIER = "trusted-deployment-observer"
_PREFIX = "post-deployment:"
_ROUTE_MAP = {
    87: (
        ProofKind.PERSISTENCE,
        ProofKind.RUNTIME,
        ProofKind.LIVE,
    ),
    88: (
        ProofKind.EXECUTION,
        ProofKind.REPRODUCIBILITY,
        ProofKind.PERSISTENCE,
        ProofKind.RUNTIME,
        ProofKind.LIVE,
    ),
}
_OUTCOME_OBSERVED = {"VALIDATED_FOR_OBSERVED_METRICS", "DEGRADED"}
_EXPIRING_PROOFS = {ProofKind.RUNTIME, ProofKind.LIVE}


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
        raise ValueError("deployment attestation payload must be finite JSON") from exc


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


def _finite(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


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


def _outside_repo(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return False
    except ValueError:
        return True


def _ids(value: object, field: str, *, minimum: int = 1) -> Tuple[str, ...]:
    if not isinstance(value, list) or not minimum <= len(value) <= 10_000:
        raise ValueError(f"{field} must be a bounded list")
    rows = tuple(_safe_id(item, field) for item in value)
    if len(set(rows)) != len(rows):
        raise ValueError(f"{field} values must be distinct")
    return rows


def _shas(value: object, field: str, *, minimum: int = 1) -> Tuple[str, ...]:
    if not isinstance(value, list) or not minimum <= len(value) <= 10_000:
        raise ValueError(f"{field} must be a bounded list")
    return tuple(_safe_sha(item, field) for item in value)


@dataclass(frozen=True)
class ValidatedDeploymentReceipt:
    revision: str
    created_at_epoch: int
    project_id: str
    model_id: str
    deployment_id: str
    runtime_instance_id: str
    observer_id: str
    state_sha256: str
    event_head_hash: str
    baseline_hash: str
    batch_ids: Tuple[str, ...]
    batch_analysis_hashes: Tuple[str, ...]
    receipt_sha256: str


@dataclass(frozen=True)
class PostDeploymentProofAttestation:
    revision: str
    deployment_receipt_sha256: str
    state_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit


def _proof_valid_until(
    kind: ProofKind,
    receipt: ValidatedDeploymentReceipt,
) -> float | None:
    """Return the immutable freshness ceiling for runtime/live evidence.

    The clock is anchored to the protected deployment observer's receipt time,
    not to when an operator happens to run this attestor.  Re-attesting a nearly
    stale receipt therefore cannot manufacture a fresh runtime/live window.
    """
    if kind not in _EXPIRING_PROOFS:
        return None
    return float(receipt.created_at_epoch + _MAX_AGE_SECONDS)


def validate_deployment_attestation(
    *,
    state_path: str | os.PathLike[str],
    deployment_receipt_path: str | os.PathLike[str],
    deployment_attestation_key: bytes,
    expected_revision: str,
    now: float,
) -> ValidatedDeploymentReceipt:
    if not isinstance(deployment_attestation_key, (bytes, bytearray)) or len(deployment_attestation_key) < 32:
        raise ValueError("deployment_attestation_key must contain at least 32 bytes")
    current_time = _finite(now, "now")
    revision = str(expected_revision or "").strip().lower()
    if not _GIT_RE.fullmatch(revision):
        raise ValueError("expected_revision must be a full lowercase Git SHA")

    receipt, receipt_bytes = _read_json(
        Path(deployment_receipt_path).expanduser().resolve(),
        "deployment attestation receipt",
    )
    expected_keys = {
        "schema_version",
        "created_at_epoch",
        "implementation_revision",
        "project_id",
        "model_id",
        "deployment_id",
        "runtime_instance_id",
        "observer_id",
        "state_sha256",
        "event_head_hash",
        "baseline_hash",
        "batch_ids",
        "batch_analysis_hashes",
        "live_data_source_ids",
        "observation_window_start_epoch",
        "observation_window_end_epoch",
        "monitor_execution_observed",
        "persistent_state_reloaded",
        "runtime_observation_complete",
        "live_observation_complete",
        "replay_reproducibility_passed",
        "replay_run_ids",
        "replay_analysis_hashes",
        "truth_proven",
        "signature",
    }
    if set(receipt) != expected_keys:
        raise ValueError("deployment attestation receipt schema is invalid")
    if receipt.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported deployment attestation schema_version")
    created = receipt.get("created_at_epoch")
    if type(created) is not int or created <= 0:
        raise ValueError("deployment receipt created_at_epoch is invalid")
    if created > current_time + _MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("deployment attestation receipt is from the future")
    if current_time - created >= _MAX_AGE_SECONDS:
        raise ValueError("deployment attestation receipt is stale")
    receipt_revision = str(receipt.get("implementation_revision") or "").strip().lower()
    if receipt_revision != revision:
        raise ValueError("deployment attestation revision does not match current Git HEAD")

    project_id = _safe_id(receipt.get("project_id"), "project_id")
    model_id = _safe_id(receipt.get("model_id"), "model_id")
    deployment_id = _safe_id(receipt.get("deployment_id"), "deployment_id")
    runtime_instance_id = _safe_id(receipt.get("runtime_instance_id"), "runtime_instance_id")
    observer_id = _safe_id(receipt.get("observer_id"), "observer_id")
    batch_ids = _ids(receipt.get("batch_ids"), "batch_ids", minimum=3)
    analysis_hashes = _shas(receipt.get("batch_analysis_hashes"), "batch_analysis_hashes", minimum=3)
    if len(batch_ids) != len(analysis_hashes):
        raise ValueError("batch_ids and batch_analysis_hashes length mismatch")
    _ids(receipt.get("live_data_source_ids"), "live_data_source_ids", minimum=1)
    replay_run_ids = _ids(receipt.get("replay_run_ids"), "replay_run_ids", minimum=2)
    replay_hashes = _shas(receipt.get("replay_analysis_hashes"), "replay_analysis_hashes", minimum=3)
    if len(replay_run_ids) < 2 or replay_hashes != analysis_hashes:
        raise ValueError("replay reproducibility does not reproduce exact stored analyses")

    window_start = _finite(receipt.get("observation_window_start_epoch"), "observation_window_start_epoch")
    window_end = _finite(receipt.get("observation_window_end_epoch"), "observation_window_end_epoch")
    if window_start <= 0 or window_end <= window_start or window_end > created:
        raise ValueError("deployment observation window is invalid")

    required_true = (
        "monitor_execution_observed",
        "persistent_state_reloaded",
        "runtime_observation_complete",
        "live_observation_complete",
        "replay_reproducibility_passed",
    )
    if any(receipt.get(field) is not True for field in required_true):
        raise ValueError("deployment attestation did not pass all required runtime gates")
    if receipt.get("truth_proven") is not False:
        raise ValueError("deployment attestation must not claim truth_proven")

    verified_state = verify_post_deployment_state(
        state_path,
        expected_project_id=project_id,
    )
    if _safe_sha(receipt.get("state_sha256"), "state_sha256") != verified_state.state_sha256:
        raise ValueError("deployment attestation does not bind the exact persisted state")
    if _safe_sha(receipt.get("event_head_hash"), "event_head_hash") != verified_state.event_head_hash:
        raise ValueError("deployment attestation event head does not match persisted state")

    state, _raw_state = _read_json(Path(state_path).expanduser().resolve(), "post-deployment state")
    baselines = state.get("baselines") or {}
    batches = state.get("batches") or {}
    baseline = baselines.get(model_id)
    if not isinstance(baseline, Mapping):
        raise ValueError("deployment receipt model_id has no persisted baseline")
    baseline_hash = _safe_sha(baseline.get("baseline_hash"), "baseline_hash")
    if _safe_sha(receipt.get("baseline_hash"), "receipt baseline_hash") != baseline_hash:
        raise ValueError("deployment attestation baseline hash mismatch")

    rows = [
        row for row in batches.values()
        if isinstance(row, Mapping) and row.get("model_id") == model_id
    ]
    rows.sort(key=lambda row: (float(row["observed_at_epoch"]), str(row["batch_id"])))
    if len(rows) < 3:
        raise ValueError("continuous validation requires at least three persisted batches")
    persisted_ids = tuple(str(row["batch_id"]) for row in rows)
    persisted_hashes = tuple(_safe_sha(row.get("analysis_hash"), "persisted analysis_hash") for row in rows)
    if batch_ids != persisted_ids or analysis_hashes != persisted_hashes:
        raise ValueError("deployment receipt must bind the complete persisted model batch history")
    timestamps = tuple(_finite(row.get("observed_at_epoch"), "batch observed_at_epoch") for row in rows)
    if min(timestamps) < window_start or max(timestamps) > window_end:
        raise ValueError("persisted batch history falls outside attested live observation window")
    if any(row.get("automatic_model_change_allowed") is not False for row in rows):
        raise ValueError("post-deployment state unexpectedly permits automatic model changes")
    outcome_count = sum(
        1 for row in rows if str(row.get("outcome_status") or "") in _OUTCOME_OBSERVED
    )
    if outcome_count < 2:
        raise ValueError("continuous validation lacks enough outcome-bearing live batches")

    signature = str(receipt.get("signature") or "").strip().lower()
    if not _SHA_RE.fullmatch(signature):
        raise ValueError("deployment attestation signature is invalid")
    unsigned = dict(receipt)
    unsigned.pop("signature", None)
    expected_signature = hmac.new(
        bytes(deployment_attestation_key),
        _canonical(unsigned),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("deployment attestation signature verification failed")

    return ValidatedDeploymentReceipt(
        revision=revision,
        created_at_epoch=created,
        project_id=project_id,
        model_id=model_id,
        deployment_id=deployment_id,
        runtime_instance_id=runtime_instance_id,
        observer_id=observer_id,
        state_sha256=verified_state.state_sha256,
        event_head_hash=verified_state.event_head_hash,
        baseline_hash=baseline_hash,
        batch_ids=batch_ids,
        batch_analysis_hashes=analysis_hashes,
        receipt_sha256=_sha(receipt_bytes),
    )


def _required_policy_rules(policy) -> None:
    for capability_id, kinds in _ROUTE_MAP.items():
        for kind in kinds:
            allowed = any(
                rule.capability_id == capability_id
                and rule.proof_kind == kind
                and _SUBJECT in rule.subjects
                and _VERIFIER in rule.verifiers
                and _PREFIX in rule.reference_prefixes
                for rule in policy.rules
            )
            if not allowed:
                raise ValueError(
                    f"committed proof policy does not authorize capability {capability_id} {kind.value} attestation"
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
    capability_id: int,
    kind: ProofKind,
    digest: str,
    reference: str,
    revision: str,
    valid_until: float | None,
) -> bool:
    expected = {
        "capability_id": capability_id,
        "proof_kind": kind.value,
        "subject": _SUBJECT,
        "subject_sha256": digest,
        "verifier": _VERIFIER,
        "reference": reference,
        "implementation_revision": revision,
        "valid_until": valid_until,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_post_deployment_proofs(
    *,
    repo_root: str | os.PathLike[str],
    state_path: str | os.PathLike[str],
    deployment_receipt_path: str | os.PathLike[str],
    deployment_attestation_key: bytes,
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> PostDeploymentProofAttestation:
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    state_target = Path(state_path).expanduser().resolve()
    receipt_target = Path(deployment_receipt_path).expanduser().resolve()
    ledger_target = Path(ledger_path).expanduser().resolve()
    for target, label in (
        (state_target, "post-deployment state"),
        (receipt_target, "deployment attestation receipt"),
        (ledger_target, "maturity ledger"),
    ):
        if not _outside_repo(root, target):
            raise ValueError(f"{label} must live outside the audited repository")

    current_time = _finite(now, "now")
    identity = repository_identity(root)
    revision = str(identity.get("revision") or "")
    if not identity.get("available") or not identity.get("clean") or not revision:
        raise ValueError("post-deployment attestation requires a clean Git checkout")

    receipt = validate_deployment_attestation(
        state_path=state_target,
        deployment_receipt_path=receipt_target,
        deployment_attestation_key=deployment_attestation_key,
        expected_revision=revision,
        now=current_time,
    )
    tracked = _tracked_index(root)
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    _required_policy_rules(policy)

    exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or not _GIT_RE.fullmatch(prior):
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
    reference = _PREFIX + receipt.state_sha256
    added = 0
    reused = 0

    # Preflight every deterministic route before mutating the append-only ledger.
    # A collision or freshness mismatch on a later route must not leave a partial
    # prefix of receipts behind.
    pending = []
    for capability_id, kinds in _ROUTE_MAP.items():
        for kind in kinds:
            receipt_id = (
                f"postdeploy:c{capability_id}:{kind.value}:"
                f"{receipt.receipt_sha256[:16]}"
            )
            valid_until = _proof_valid_until(kind, receipt)
            previous = existing.get(receipt_id)
            if previous is not None:
                if not _same(
                    previous,
                    capability_id=capability_id,
                    kind=kind,
                    digest=receipt.receipt_sha256,
                    reference=reference,
                    revision=revision,
                    valid_until=valid_until,
                ):
                    raise ValueError("deterministic post-deployment receipt_id collision")
                reused += 1
                continue
            if valid_until is not None and valid_until <= current_time:
                raise ValueError("runtime/live proof freshness window is exhausted")
            pending.append((receipt_id, capability_id, kind, valid_until))

    for receipt_id, capability_id, kind, valid_until in pending:
        ledger.add(
            receipt_id=receipt_id,
            capability_id=capability_id,
            proof_kind=kind,
            subject=_SUBJECT,
            subject_sha256=receipt.receipt_sha256,
            verifier=_VERIFIER,
            observed_at=current_time,
            reference=reference,
            valid_until=valid_until,
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
    return PostDeploymentProofAttestation(
        revision=revision,
        deployment_receipt_sha256=receipt.receipt_sha256,
        state_sha256=receipt.state_sha256,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
