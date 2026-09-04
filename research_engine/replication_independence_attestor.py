"""External independence attestor for capability #39 Replication Engine.

Replication code can run multiple runners, but software cannot prove that those
runners are organizationally and implementation-wise independent merely because
identifiers differ.  This module accepts a bounded external validation campaign
and mints *only* ``independent_validation`` when the campaign demonstrates a
strong structural independence boundary.

Honesty boundaries:
- at least three external replication groups are required;
- group, runner, model-family, operator-domain and declared implementation
  digests must all be distinct;
- every group receives the same frozen, author/expected-result-blinded protocol;
- every group repeats the protocol at least twice;
- disagreement is allowed and is never converted into truth/failure by this
  attestor;
- external implementation digests are declarations unless separately verified;
- hidden provider/operator dependencies are not claimed to be ruled out;
- this attestor never mints execution, reproducibility, safety, runtime, live or
  hardware evidence and never claims scientific truth.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Sequence, Tuple

from utils.release_identity import repository_identity

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


_CAPABILITY_ID = 39
_PROOF_KIND = ProofKind.INDEPENDENT
_IMPLEMENTATION_SUBJECT = "research_engine/scientist_society.py"
_SUBJECT = "capability-39-independent-validation"
_VERIFIER = "trusted-independent-validator"
_REFERENCE_PREFIX = "independent:"
_SCHEMA_VERSION = 1
_MAX_RECEIPT_BYTES = 4 * 1024 * 1024
_MAX_TEXT_BYTES = 128 * 1024
_MIN_GROUPS = 3
_MAX_GROUPS = 12
_MIN_REPETITIONS = 2
_MAX_REPETITIONS = 5
_MAX_METRICS = 1_000
_MAX_EVIDENCE_IDS = 256
_MAX_RECEIPT_AGE_SECONDS = 2 * 60 * 60
_MAX_FUTURE_SKEW_SECONDS = 5 * 60
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_FORBIDDEN_PROTOCOL_KEYS = {
    "author",
    "author_id",
    "author_agent_id",
    "expected",
    "expected_result",
    "expected_outcome",
    "champion",
    "champion_id",
    "ground_truth",
    "correct_answer",
}

ReplicaRunner = Callable[[Mapping[str, Any]], Mapping[str, Any]]


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
        raise ValueError("replication-independence data must be strict finite JSON") from exc


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_ID_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _safe_sha(value: object, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"{field} must be a SHA-256 hex digest")
    return text


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _walk_keys(value: Any):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key).strip().lower()
            yield from _walk_keys(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            yield from _walk_keys(item)


def _frozen_protocol(value: object) -> Tuple[Dict[str, Any], str]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError("frozen_protocol must be a non-empty mapping")
    payload = copy.deepcopy(dict(value))
    encoded = _canonical(payload)
    if len(encoded) > _MAX_TEXT_BYTES:
        raise ValueError("frozen_protocol exceeds bounded size")
    leaked = sorted(set(_walk_keys(payload)) & _FORBIDDEN_PROTOCOL_KEYS)
    if leaked:
        raise ValueError("frozen_protocol leaked blinded metadata: " + ",".join(leaked))
    return payload, _sha(payload)


def _evidence_ids(value: object, field: str) -> Tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be a sequence")
    if len(value) > _MAX_EVIDENCE_IDS:
        raise ValueError(f"{field} exceeds bounded size")
    rows = tuple(_safe_id(item, field) for item in value)
    if len(set(rows)) != len(rows):
        raise ValueError(f"{field} must not contain duplicates")
    return tuple(sorted(rows))


def _metrics(value: object, field: str) -> Dict[str, float]:
    if not isinstance(value, Mapping) or not value or len(value) > _MAX_METRICS:
        raise ValueError(f"{field} must be a bounded non-empty mapping")
    result: Dict[str, float] = {}
    for raw_name, raw_value in value.items():
        name = str(raw_name or "").strip()
        if not name or len(name) > 200 or name in result:
            raise ValueError(f"{field} contains invalid metric names")
        result[name] = _finite(raw_value, f"{field}.{name}")
    return dict(sorted(result.items()))


@dataclass(frozen=True)
class ExternalReplicationGroup:
    group_id: str
    runner_id: str
    model_family: str
    operator_domain: str
    implementation_sha256: str
    runner: ReplicaRunner


@dataclass(frozen=True)
class ReplicationIndependenceExecutionReceipt:
    revision: str
    created_at_epoch: int
    sha256: str
    campaign_hash: str
    protocol_hash: str
    group_manifest_hash: str
    repetitions: int


@dataclass(frozen=True)
class ReplicationIndependenceAttestation:
    revision: str
    execution_receipt_sha256: str
    campaign_hash: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    external_implementation_bytes_verified: bool = False
    hidden_provider_dependencies_ruled_out: bool = False
    replication_success_proven: bool = False
    truth_proven: bool = False


def _normalize_groups(
    groups: Sequence[ExternalReplicationGroup],
) -> Tuple[Tuple[ExternalReplicationGroup, ...], Tuple[Dict[str, str], ...], str]:
    if (
        isinstance(groups, (str, bytes, bytearray))
        or not isinstance(groups, Sequence)
        or not _MIN_GROUPS <= len(groups) <= _MAX_GROUPS
    ):
        raise ValueError("replication independence requires 3..12 external groups")
    normalized = []
    rows = []
    for index, raw in enumerate(groups):
        if not isinstance(raw, ExternalReplicationGroup) or not callable(raw.runner):
            raise ValueError(f"external replication group {index} is invalid")
        row = {
            "group_id": _safe_id(raw.group_id, "group_id"),
            "runner_id": _safe_id(raw.runner_id, "runner_id"),
            "model_family": _safe_id(raw.model_family, "model_family"),
            "operator_domain": _safe_id(raw.operator_domain, "operator_domain"),
            "implementation_sha256": _safe_sha(
                raw.implementation_sha256, "implementation_sha256"
            ),
        }
        rows.append(row)
        normalized.append(ExternalReplicationGroup(**row, runner=raw.runner))
    for field in (
        "group_id",
        "runner_id",
        "model_family",
        "operator_domain",
        "implementation_sha256",
    ):
        if len({row[field] for row in rows}) != len(rows):
            raise ValueError(f"all external replication groups must have distinct {field} values")
    order = sorted(range(len(rows)), key=lambda index: rows[index]["group_id"])
    ordered_groups = tuple(normalized[index] for index in order)
    ordered_rows = tuple(rows[index] for index in order)
    return ordered_groups, ordered_rows, _sha(list(ordered_rows))


def _normalize_runner_result(
    raw: object,
    *,
    group_id: str,
    repetition: int,
    protocol_hash: str,
) -> Dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != {"metrics", "evidence_ids", "notes"}:
        raise ValueError("replica runner result schema is invalid")
    notes = str(raw.get("notes") or "").strip()
    if not notes or len(notes.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ValueError("replica runner notes are invalid")
    payload = {
        "group_id": group_id,
        "repetition": repetition,
        "protocol_hash": protocol_hash,
        "metrics": _metrics(raw.get("metrics"), "metrics"),
        "evidence_ids": list(_evidence_ids(raw.get("evidence_ids"), "evidence_ids")),
        "notes": notes,
    }
    payload["result_hash"] = _sha(payload)
    return payload


def build_replication_independence_execution_receipt(
    *,
    repo_root: str | os.PathLike[str],
    frozen_protocol: Mapping[str, Any],
    groups: Sequence[ExternalReplicationGroup],
    created_at_epoch: int,
    repetitions: int = 2,
) -> Dict[str, Any]:
    """Execute the same blinded protocol through structurally distinct groups."""
    root = Path(repo_root).resolve(strict=True)
    identity = repository_identity(root)
    revision = str(identity.get("revision") or "").strip().lower()
    if not identity.get("available") or not identity.get("clean") or not _GIT_SHA_RE.fullmatch(revision):
        raise ValueError("replication independence requires a clean Git checkout")
    if type(created_at_epoch) is not int or created_at_epoch < 0:
        raise ValueError("created_at_epoch must be a non-negative integer")
    if type(repetitions) is not int or not _MIN_REPETITIONS <= repetitions <= _MAX_REPETITIONS:
        raise ValueError("repetitions must be between 2 and 5")

    tracked = _tracked_index(root)
    implementation_sha256 = _hash_tracked_regular(root, tracked, _IMPLEMENTATION_SUBJECT)
    protocol, protocol_hash = _frozen_protocol(frozen_protocol)
    normalized_groups, manifest_rows, manifest_hash = _normalize_groups(groups)
    packet = {
        "schema_version": 1,
        "capability_id": _CAPABILITY_ID,
        "protocol": protocol,
        "protocol_hash": protocol_hash,
        "task": (
            "Independently execute the frozen replication protocol. Do not infer an "
            "expected/champion result; return measured metrics and evidence identifiers."
        ),
    }
    if set(_walk_keys(packet)) & _FORBIDDEN_PROTOCOL_KEYS:
        raise ValueError("replication packet leaked blinded metadata")

    runs = []
    for group in normalized_groups:
        for repetition in range(1, repetitions + 1):
            raw = group.runner(copy.deepcopy(packet))
            runs.append(
                _normalize_runner_result(
                    raw,
                    group_id=group.group_id,
                    repetition=repetition,
                    protocol_hash=protocol_hash,
                )
            )
    runs.sort(key=lambda row: (row["group_id"], row["repetition"]))
    expected_runs = len(normalized_groups) * repetitions
    if len(runs) != expected_runs:
        raise ValueError("replication independence campaign is incomplete")

    campaign_payload = {
        "protocol_hash": protocol_hash,
        "group_manifest_hash": manifest_hash,
        "repetitions": repetitions,
        "runs": runs,
        "independence_structure_satisfied": True,
        "agreement_required": False,
        "external_implementation_bytes_verified": False,
        "hidden_provider_dependencies_ruled_out": False,
        "replication_success_proven": False,
        "truth_proven": False,
    }
    campaign_hash = _sha(campaign_payload)
    return {
        "schema_version": _SCHEMA_VERSION,
        "created_at_epoch": created_at_epoch,
        "implementation_revision": revision,
        "tracked_replication_engine_sha256": implementation_sha256,
        "protocol": protocol,
        "protocol_hash": protocol_hash,
        "groups": list(manifest_rows),
        "group_manifest_hash": manifest_hash,
        "repetitions": repetitions,
        "runs": runs,
        "independence_structure_satisfied": True,
        "agreement_required": False,
        "external_implementation_bytes_verified": False,
        "hidden_provider_dependencies_ruled_out": False,
        "replication_success_proven": False,
        "truth_proven": False,
        "campaign_hash": campaign_hash,
    }


def _read_bounded_json(path: Path) -> Tuple[Mapping[str, Any], bytes]:
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError("replication independence receipt cannot be read") from exc
    if not path.is_file() or info.st_size < 1 or info.st_size > _MAX_RECEIPT_BYTES:
        raise ValueError("replication independence receipt size is invalid")
    data = path.read_bytes()
    if len(data) != info.st_size or len(data) > _MAX_RECEIPT_BYTES:
        raise ValueError("replication independence receipt changed during read")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("replication independence receipt is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("replication independence receipt must be a JSON object")
    return value, data


def validate_replication_independence_receipt(
    path: str | os.PathLike[str],
    *,
    repo_root: str | os.PathLike[str],
    expected_revision: str,
    now: float,
) -> ReplicationIndependenceExecutionReceipt:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    revision = str(expected_revision or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(revision):
        raise ValueError("expected_revision must be a full lowercase Git SHA")
    root = Path(repo_root).resolve(strict=True)
    tracked = _tracked_index(root)
    value, data = _read_bounded_json(Path(path).expanduser().resolve())
    expected_keys = {
        "schema_version", "created_at_epoch", "implementation_revision",
        "tracked_replication_engine_sha256", "protocol", "protocol_hash",
        "groups", "group_manifest_hash", "repetitions", "runs",
        "independence_structure_satisfied", "agreement_required",
        "external_implementation_bytes_verified",
        "hidden_provider_dependencies_ruled_out", "replication_success_proven",
        "truth_proven", "campaign_hash",
    }
    if set(value) != expected_keys or value.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("replication independence receipt schema is invalid")
    if str(value.get("implementation_revision") or "").strip().lower() != revision:
        raise ValueError("replication independence receipt revision mismatch")
    created = value.get("created_at_epoch")
    if type(created) is not int or created < 0:
        raise ValueError("replication independence receipt created_at_epoch is invalid")
    age = current_time - created
    if age < -_MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("replication independence receipt is from the future")
    if age > _MAX_RECEIPT_AGE_SECONDS:
        raise ValueError("replication independence receipt is stale")
    actual_engine_sha = _hash_tracked_regular(root, tracked, _IMPLEMENTATION_SUBJECT)
    if _safe_sha(value.get("tracked_replication_engine_sha256"), "tracked_replication_engine_sha256") != actual_engine_sha:
        raise ValueError("replication engine digest does not match tracked revision")

    protocol, protocol_hash = _frozen_protocol(value.get("protocol"))
    if _safe_sha(value.get("protocol_hash"), "protocol_hash") != protocol_hash:
        raise ValueError("replication protocol_hash mismatch")
    groups = value.get("groups")
    if not isinstance(groups, list) or not _MIN_GROUPS <= len(groups) <= _MAX_GROUPS:
        raise ValueError("replication group manifest size is invalid")
    normalized_groups = []
    for index, row in enumerate(groups):
        if not isinstance(row, dict) or set(row) != {
            "group_id", "runner_id", "model_family", "operator_domain",
            "implementation_sha256",
        }:
            raise ValueError(f"replication group manifest row {index} is invalid")
        normalized_groups.append({
            "group_id": _safe_id(row["group_id"], "group_id"),
            "runner_id": _safe_id(row["runner_id"], "runner_id"),
            "model_family": _safe_id(row["model_family"], "model_family"),
            "operator_domain": _safe_id(row["operator_domain"], "operator_domain"),
            "implementation_sha256": _safe_sha(row["implementation_sha256"], "implementation_sha256"),
        })
    for field in ("group_id", "runner_id", "model_family", "operator_domain", "implementation_sha256"):
        if len({row[field] for row in normalized_groups}) != len(normalized_groups):
            raise ValueError(f"replication group manifest does not have distinct {field} values")
    normalized_groups.sort(key=lambda row: row["group_id"])
    manifest_hash = _sha(normalized_groups)
    if _safe_sha(value.get("group_manifest_hash"), "group_manifest_hash") != manifest_hash:
        raise ValueError("replication group_manifest_hash mismatch")

    repetitions = value.get("repetitions")
    if type(repetitions) is not int or not _MIN_REPETITIONS <= repetitions <= _MAX_REPETITIONS:
        raise ValueError("replication repetitions are invalid")
    runs = value.get("runs")
    if not isinstance(runs, list) or len(runs) != len(normalized_groups) * repetitions:
        raise ValueError("replication campaign run coverage is incomplete")
    group_ids = {row["group_id"] for row in normalized_groups}
    seen = set()
    normalized_runs = []
    for index, row in enumerate(runs):
        if not isinstance(row, dict) or set(row) != {
            "group_id", "repetition", "protocol_hash", "metrics",
            "evidence_ids", "notes", "result_hash",
        }:
            raise ValueError(f"replication run {index} schema is invalid")
        group_id = _safe_id(row["group_id"], "run group_id")
        repetition = row.get("repetition")
        if group_id not in group_ids or type(repetition) is not int or not 1 <= repetition <= repetitions:
            raise ValueError("replication run identity is invalid")
        key = (group_id, repetition)
        if key in seen:
            raise ValueError("replication campaign contains duplicate runs")
        seen.add(key)
        if _safe_sha(row.get("protocol_hash"), "run protocol_hash") != protocol_hash:
            raise ValueError("replication run protocol_hash mismatch")
        payload = {
            "group_id": group_id,
            "repetition": repetition,
            "protocol_hash": protocol_hash,
            "metrics": _metrics(row.get("metrics"), "run metrics"),
            "evidence_ids": list(_evidence_ids(row.get("evidence_ids"), "run evidence_ids")),
            "notes": str(row.get("notes") or "").strip(),
        }
        if not payload["notes"] or len(payload["notes"].encode("utf-8")) > _MAX_TEXT_BYTES:
            raise ValueError("replication run notes are invalid")
        if _safe_sha(row.get("result_hash"), "result_hash") != _sha(payload):
            raise ValueError("replication result_hash mismatch")
        normalized_runs.append({**payload, "result_hash": _sha(payload)})
    expected_pairs = {(group_id, rep) for group_id in group_ids for rep in range(1, repetitions + 1)}
    if seen != expected_pairs:
        raise ValueError("replication campaign is missing group/repetition runs")
    normalized_runs.sort(key=lambda row: (row["group_id"], row["repetition"]))

    for field, expected in (
        ("independence_structure_satisfied", True),
        ("agreement_required", False),
        ("external_implementation_bytes_verified", False),
        ("hidden_provider_dependencies_ruled_out", False),
        ("replication_success_proven", False),
        ("truth_proven", False),
    ):
        if value.get(field) is not expected:
            raise ValueError(f"replication independence boundary {field} is invalid")
    campaign_payload = {
        "protocol_hash": protocol_hash,
        "group_manifest_hash": manifest_hash,
        "repetitions": repetitions,
        "runs": normalized_runs,
        "independence_structure_satisfied": True,
        "agreement_required": False,
        "external_implementation_bytes_verified": False,
        "hidden_provider_dependencies_ruled_out": False,
        "replication_success_proven": False,
        "truth_proven": False,
    }
    campaign_hash = _sha(campaign_payload)
    if _safe_sha(value.get("campaign_hash"), "campaign_hash") != campaign_hash:
        raise ValueError("replication campaign_hash mismatch")
    return ReplicationIndependenceExecutionReceipt(
        revision=revision,
        created_at_epoch=created,
        sha256=_sha_bytes(data),
        campaign_hash=campaign_hash,
        protocol_hash=protocol_hash,
        group_manifest_hash=manifest_hash,
        repetitions=repetitions,
    )


def _route_rule(policy, *, capability_id: int, proof_kind: ProofKind):
    matches = [
        rule for rule in policy.rules
        if rule.capability_id == capability_id and rule.proof_kind is proof_kind
    ]
    if len(matches) != 1:
        raise ValueError("replication independence proof policy route is missing or ambiguous")
    rule = matches[0]
    if rule.subjects != (_SUBJECT,) or rule.verifiers != (_VERIFIER,) or rule.reference_prefixes != (_REFERENCE_PREFIX,):
        raise ValueError("replication independence proof policy route does not match trusted contract")
    return rule


def attest_replication_independence(
    *,
    repo_root: str | os.PathLike[str],
    execution_receipt_path: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    observation_id: str,
    now: float,
    prior_anchor_token: str = "",
    prior_revision: str = "",
    policy_path: str = "config/maturity_proof_policy.json",
) -> ReplicationIndependenceAttestation:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    observation = _safe_id(observation_id, "observation_id")
    root = Path(repo_root).resolve(strict=True)
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("replication independence ledger must live outside audited repository")
    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "").strip().lower()
    if not identity_before.get("available") or not identity_before.get("clean") or not _GIT_SHA_RE.fullmatch(revision):
        raise ValueError("replication independence attestation requires a clean Git checkout")

    receipt = validate_replication_independence_receipt(
        execution_receipt_path,
        repo_root=root,
        expected_revision=revision,
        now=current_time,
    )
    tracked = _tracked_index(root)
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    _route_rule(policy, capability_id=_CAPABILITY_ID, proof_kind=_PROOF_KIND)

    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or not _GIT_SHA_RE.fullmatch(prior):
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not continuity.verify_chain(anchor_token=prior_anchor_token, current_revision=prior):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    receipt_id = f"repind:{receipt.sha256[:16]}:{_CAPABILITY_ID}"
    reference = f"{_REFERENCE_PREFIX}{observation}:{receipt.campaign_hash[:16]}"
    expected = {
        "capability_id": _CAPABILITY_ID,
        "proof_kind": _PROOF_KIND.value,
        "subject": _SUBJECT,
        "verifier": _VERIFIER,
        "reference": reference,
        "implementation_revision": revision,
    }
    added = 0
    reused = 0
    previous = existing.get(receipt_id)
    if previous is not None:
        if not all(previous.get(key) == value for key, value in expected.items()):
            raise ValueError("deterministic replication independence receipt_id collision")
        reused = 1
    else:
        ledger.add(
            receipt_id=receipt_id,
            capability_id=_CAPABILITY_ID,
            proof_kind=_PROOF_KIND,
            subject=_SUBJECT,
            verifier=_VERIFIER,
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
        raise ValueError("trusted maturity audit rejected replication independence attestation")
    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "").strip().lower() != revision
    ):
        raise ValueError("repository changed during replication independence attestation")
    return ReplicationIndependenceAttestation(
        revision=revision,
        execution_receipt_sha256=receipt.sha256,
        campaign_hash=receipt.campaign_hash,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
