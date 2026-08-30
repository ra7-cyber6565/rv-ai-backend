"""Trusted runtime/live attestation for capability #41 Reality Oracle.

A JSON field saying ``live=true`` is not evidence. This attestor validates a
fresh observation signed by a protected observer key, binds it to an exact clean
Git revision, reconstructs the prediction contract and observation receipt,
recomputes the oracle evaluation twice, checks committed proof-policy routes,
and only then mints EXECUTION, REPRODUCIBILITY, RUNTIME and LIVE receipts.

The observer HMAC proves that a holder of the configured external observer key
signed the measurement packet. Operational key custody and the physical truth
of a sensor remain external trust assumptions; therefore this module never
sets ``truth_proven``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence, Tuple

from utils.release_identity import repository_identity

from .capability_registry import ProofKind
from .maturity_attestor import _existing_adds, _outside_repo, _safe_reference
from .maturity_auditor import (
    TrustedMaturityAudit,
    _parse_policy,
    _read_policy_bytes,
    _tracked_index,
    audit_repository_maturity,
)
from .maturity_proof import ProofLedger
from .reality_oracle import (
    evaluate_reality,
    freeze_prediction_contract,
    make_observation_receipt,
)


_CAPABILITY_ID = 41
_SCHEMA_VERSION = 1
_SUBJECT = "reality-oracle-live"
_VERIFIER = "trusted-live-observer"
_REFERENCE_PREFIX = "reality-oracle:"
_REQUIRED: Tuple[ProofKind, ...] = (
    ProofKind.EXECUTION,
    ProofKind.REPRODUCIBILITY,
    ProofKind.RUNTIME,
    ProofKind.LIVE,
)
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024
_MAX_RECEIPT_AGE_SECONDS = 2 * 60 * 60
_MAX_OBSERVATION_AGE_SECONDS = 2 * 60 * 60
_MAX_FUTURE_SKEW_SECONDS = 5 * 60
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_SIGNATURE_DOMAIN = b"reality-oracle-live-v1\0"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_ID_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _unix(iso_value: str) -> float:
    parsed = datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc).timestamp()


def _read_json(path: Path) -> tuple[Mapping[str, Any], bytes]:
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError("reality oracle receipt cannot be read") from exc
    if not path.is_file() or info.st_size < 1 or info.st_size > _MAX_RECEIPT_BYTES:
        raise ValueError("reality oracle receipt size is invalid")
    data = path.read_bytes()
    if len(data) != info.st_size:
        raise ValueError("reality oracle receipt changed during read")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("reality oracle receipt is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("reality oracle receipt must be a JSON object")
    return value, data


def observation_signature(
    *,
    observer_key: bytes,
    revision: str,
    prediction_contract_hash: str,
    observation: Mapping[str, Any],
) -> str:
    """Create the external-observer signature payload used by trusted runtimes."""
    if not isinstance(observer_key, (bytes, bytearray)) or len(observer_key) < 32:
        raise ValueError("observer_key must contain at least 32 bytes")
    payload = {
        "implementation_revision": str(revision),
        "prediction_contract_hash": str(prediction_contract_hash),
        "observation": dict(observation),
    }
    return hmac.new(bytes(observer_key), _SIGNATURE_DOMAIN + _canonical(payload), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class LiveOracleReceipt:
    revision: str
    created_at_epoch: int
    observer_id: str
    observation_id: str
    evaluation_hash: str
    sha256: str


@dataclass(frozen=True)
class RealityOracleAttestation:
    revision: str
    execution_receipt_sha256: str
    observer_id: str
    evaluation_hash: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    observation_authenticity_verified: bool = True
    live_observation_verified: bool = True
    truth_proven: bool = False


def validate_live_oracle_receipt(
    path: str | os.PathLike[str],
    *,
    expected_revision: str,
    observer_keys: Mapping[str, bytes],
    now: float,
) -> LiveOracleReceipt:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    revision = str(expected_revision or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(revision):
        raise ValueError("expected_revision must be a full lowercase Git SHA")

    value, raw_bytes = _read_json(Path(path).expanduser().resolve())
    if set(value) != {
        "schema_version",
        "created_at_epoch",
        "implementation_revision",
        "prediction",
        "observation",
        "evaluation",
        "observer",
    }:
        raise ValueError("reality oracle receipt schema is invalid")
    if value.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported reality oracle receipt schema")
    if str(value.get("implementation_revision") or "").strip().lower() != revision:
        raise ValueError("reality oracle receipt revision mismatch")

    created = value.get("created_at_epoch")
    if isinstance(created, bool) or not isinstance(created, int):
        raise ValueError("created_at_epoch must be an integer")
    if created > current_time + _MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("reality oracle receipt is from the future")
    if current_time - created > _MAX_RECEIPT_AGE_SECONDS:
        raise ValueError("reality oracle receipt is stale")

    pred = value.get("prediction")
    if not isinstance(pred, dict) or set(pred) != {
        "prediction_id", "hypothesis_id", "metric", "unit", "rule", "target",
        "lower", "upper", "direction", "tolerance", "preregistered_at",
        "evaluation_after", "protocol_hash", "contract_hash",
    }:
        raise ValueError("prediction contract schema is invalid")
    rebuilt_prediction = freeze_prediction_contract(
        **{key: pred[key] for key in pred if key != "contract_hash"}
    )
    if rebuilt_prediction.to_dict() != pred:
        raise ValueError("prediction contract hash/content verification failed")

    obs = value.get("observation")
    if not isinstance(obs, dict) or set(obs) != {
        "observation_id", "metric", "unit", "observed_value", "observed_at",
        "source_id", "source_kind", "source_digest", "raw_reference", "receipt_hash",
    }:
        raise ValueError("observation receipt schema is invalid")
    if str(obs.get("source_kind") or "").strip().lower() == "dataset":
        raise ValueError("static dataset observation cannot mint LIVE evidence")
    rebuilt_observation = make_observation_receipt(
        **{key: obs[key] for key in obs if key != "receipt_hash"}
    )
    if rebuilt_observation.to_dict() != obs:
        raise ValueError("observation receipt hash/content verification failed")
    observed_epoch = _unix(rebuilt_observation.observed_at)
    if observed_epoch > current_time + _MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("observation timestamp is from the future")
    if current_time - observed_epoch > _MAX_OBSERVATION_AGE_SECONDS:
        raise ValueError("observation is too old to count as live")

    observer = value.get("observer")
    if not isinstance(observer, dict) or set(observer) != {"observer_id", "signature"}:
        raise ValueError("observer attestation schema is invalid")
    observer_id = _safe_id(observer.get("observer_id"), "observer_id")
    key = observer_keys.get(observer_id)
    if not isinstance(key, (bytes, bytearray)) or len(key) < 32:
        raise ValueError("observer is not configured with a trusted key")
    expected_signature = observation_signature(
        observer_key=bytes(key),
        revision=revision,
        prediction_contract_hash=rebuilt_prediction.contract_hash,
        observation=rebuilt_observation.to_dict(),
    )
    signature = str(observer.get("signature") or "").strip().lower()
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("observer signature verification failed")

    evaluation = value.get("evaluation")
    if not isinstance(evaluation, dict):
        raise ValueError("evaluation must be an object")
    first = evaluate_reality(rebuilt_prediction, rebuilt_observation)
    second = evaluate_reality(rebuilt_prediction, rebuilt_observation)
    if first.to_dict() != second.to_dict():
        raise ValueError("reality oracle evaluation is not reproducible")
    if first.status not in {"MATCH", "MISS"}:
        raise ValueError("inconclusive observation cannot mint live oracle proof")
    if first.to_dict() != evaluation:
        raise ValueError("reality oracle evaluation content/hash verification failed")
    if first.truth_proven or first.live_observation_proven or first.observation_authenticity_proven:
        raise ValueError("untrusted oracle evaluation must preserve authenticity/truth boundary")

    return LiveOracleReceipt(
        revision=revision,
        created_at_epoch=created,
        observer_id=observer_id,
        observation_id=rebuilt_observation.observation_id,
        evaluation_hash=first.evaluation_hash,
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )


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


def attest_reality_oracle_live(
    *,
    repo_root: str | os.PathLike[str],
    receipt_path: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    observer_keys: Mapping[str, bytes],
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> RealityOracleAttestation:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    reference = _safe_reference(run_reference)
    root = Path(repo_root).resolve(strict=True)
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "")
    if not identity_before.get("available") or not identity_before.get("clean") or not revision:
        raise ValueError("reality oracle attestation requires a clean Git checkout")

    live_receipt = validate_live_oracle_receipt(
        receipt_path,
        expected_revision=revision,
        observer_keys=observer_keys,
        now=current_time,
    )

    tracked = _tracked_index(root)
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
            raise ValueError(f"committed proof policy has no trusted {kind.value} rule")
        if not any(
            not rule.reference_prefixes
            or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
            for rule in matching
        ):
            raise ValueError("run_reference is not allowed by reality oracle proof policy")

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

    digest = _sha({
        "receipt_sha256": live_receipt.sha256,
        "evaluation_hash": live_receipt.evaluation_hash,
        "observer_id": live_receipt.observer_id,
        "revision": revision,
        "subject": _SUBJECT,
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0
    for kind in _REQUIRED:
        receipt_id = f"reality:{revision[:12]}:{live_receipt.observation_id}:{kind.value}"
        previous = existing.get(receipt_id)
        if previous is not None:
            if not _same_receipt(
                previous,
                kind=kind,
                digest=digest,
                reference=reference,
                revision=revision,
            ):
                raise ValueError("deterministic reality oracle receipt_id collision")
            reused += 1
            continue
        ledger.add(
            receipt_id=receipt_id,
            capability_id=_CAPABILITY_ID,
            proof_kind=kind,
            subject=_SUBJECT,
            subject_sha256=digest,
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
        raise ValueError("trusted maturity audit rejected reality oracle attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during reality oracle attestation")

    return RealityOracleAttestation(
        revision=revision,
        execution_receipt_sha256=live_receipt.sha256,
        observer_id=live_receipt.observer_id,
        evaluation_hash=live_receipt.evaluation_hash,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
