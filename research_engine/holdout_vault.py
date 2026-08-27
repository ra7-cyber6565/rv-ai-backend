"""Application-level sealed holdout vault and double-blind evaluation state machine.

The goal is to prevent accidental/post-hoc optimization on final evaluation data:
- the dataset is stored behind an evaluator capability token;
- builder-facing APIs never return holdout bytes or the token;
- candidate implementation + evaluation protocol are frozen before evaluation;
- the evaluator receives the frozen candidate packet and holdout bytes, but not the
  hypothesis narrative supplied to a builder;
- evaluation is one-shot by default and hash-audited.

This is an application security boundary, not DRM against an operating-system
administrator who can directly read the storage directory. Stronger deployment
is possible by putting this directory behind a separate evaluator service/KMS.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping, Optional


_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_id(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is empty or contains unsupported characters")
    return text


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_json(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VaultCreation:
    vault_id: str
    evaluator_token: str
    dataset_sha256: str
    state: str


@dataclass(frozen=True)
class EvaluationReceipt:
    vault_id: str
    candidate_id: str
    dataset_sha256: str
    protocol_hash: str
    result_hash: str
    result: Mapping[str, Any]
    evaluated_at: str


class HoldoutVault:
    """Filesystem-backed sealed holdout vault with one-shot evaluator token."""

    def __init__(self, directory: str):
        self.directory = os.path.abspath(directory)
        os.makedirs(self.directory, exist_ok=True)

    def _meta_path(self, vault_id: str) -> str:
        return os.path.join(self.directory, f"{_safe_id(vault_id, 'vault_id')}.json")

    def _data_path(self, vault_id: str) -> str:
        return os.path.join(self.directory, f"{_safe_id(vault_id, 'vault_id')}.holdout")

    @staticmethod
    def _write_atomic(path: str, data: bytes, *, mode: int = 0o600) -> None:
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".vault_", dir=directory)
        try:
            try:
                os.fchmod(fd, mode)
            except (AttributeError, OSError):
                pass
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            try:
                os.chmod(path, mode)
            except OSError:
                pass
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)

    def _load(self, vault_id: str) -> Dict[str, Any]:
        path = self._meta_path(vault_id)
        if not os.path.exists(path):
            raise KeyError(vault_id)
        with open(path, "r", encoding="utf-8") as handle:
            meta = json.load(handle)
        if meta.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("unsupported holdout vault schema")
        return meta

    def _save(self, meta: Mapping[str, Any]) -> None:
        data = json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        self._write_atomic(self._meta_path(str(meta["vault_id"])), data)

    def create(
        self,
        vault_id: str,
        dataset: bytes,
        *,
        dataset_label: str,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> VaultCreation:
        vault_id = _safe_id(vault_id, "vault_id")
        if not isinstance(dataset, (bytes, bytearray)) or not dataset:
            raise ValueError("dataset must be non-empty bytes")
        if os.path.exists(self._meta_path(vault_id)) or os.path.exists(self._data_path(vault_id)):
            raise ValueError("vault_id already exists")
        token = secrets.token_urlsafe(32)
        dataset_bytes = bytes(dataset)
        digest = _sha_bytes(dataset_bytes)
        self._write_atomic(self._data_path(vault_id), dataset_bytes)
        meta = {
            "schema_version": _SCHEMA_VERSION,
            "vault_id": vault_id,
            "dataset_label": str(dataset_label).strip()[:300],
            "dataset_sha256": digest,
            "dataset_bytes": len(dataset_bytes),
            "public_metadata": dict(metadata or {}),
            "token_hash": _sha_bytes(token.encode("utf-8")),
            "state": "SEALED",
            "created_at": _now(),
            "candidate": None,
            "evaluation": None,
        }
        if not meta["dataset_label"]:
            raise ValueError("dataset_label is required")
        self._save(meta)
        return VaultCreation(vault_id, token, digest, "SEALED")

    def builder_view(self, vault_id: str) -> Dict[str, Any]:
        """Safe metadata visible to model/strategy builders; never data/token/path."""
        meta = self._load(vault_id)
        return {
            "vault_id": meta["vault_id"],
            "dataset_label": meta["dataset_label"],
            "dataset_sha256_commitment": meta["dataset_sha256"],
            "dataset_bytes": meta["dataset_bytes"],
            "public_metadata": dict(meta.get("public_metadata") or {}),
            "state": meta["state"],
            "candidate_frozen": bool(meta.get("candidate")),
            "evaluated": bool(meta.get("evaluation")),
        }

    def freeze_candidate(
        self,
        vault_id: str,
        *,
        candidate_id: str,
        implementation_hash: str,
        protocol_hash: str,
        evaluator_instructions: Mapping[str, Any],
        theory_blind: bool = True,
    ) -> Dict[str, Any]:
        meta = self._load(vault_id)
        if meta["state"] != "SEALED" or meta.get("candidate") is not None:
            raise ValueError("candidate can only be frozen once while vault is SEALED")
        candidate = {
            "candidate_id": _safe_id(candidate_id, "candidate_id"),
            "implementation_hash": str(implementation_hash).strip(),
            "protocol_hash": str(protocol_hash).strip(),
            "evaluator_instructions": dict(evaluator_instructions),
            "theory_blind": bool(theory_blind),
            "frozen_at": _now(),
        }
        if not candidate["implementation_hash"] or not candidate["protocol_hash"]:
            raise ValueError("implementation_hash and protocol_hash are required")
        candidate["freeze_hash"] = _sha_json(
            {key: value for key, value in candidate.items() if key not in {"frozen_at", "freeze_hash"}}
        )
        meta["candidate"] = candidate
        meta["state"] = "FROZEN"
        self._save(meta)
        return dict(candidate)

    @staticmethod
    def _validate_result(result: Any) -> Dict[str, Any]:
        if not isinstance(result, Mapping):
            raise ValueError("evaluator must return a mapping")
        clean = dict(result)
        encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if len(encoded) > 256 * 1024:
            raise ValueError("evaluation result is too large")
        return clean

    def evaluate(
        self,
        vault_id: str,
        *,
        evaluator_token: str,
        evaluator: Callable[[bytes, Mapping[str, Any]], Mapping[str, Any]],
    ) -> EvaluationReceipt:
        """Run the frozen evaluator exactly once over the holdout bytes."""
        meta = self._load(vault_id)
        if meta["state"] != "FROZEN" or not meta.get("candidate"):
            raise ValueError("vault must have a frozen candidate before evaluation")
        if meta.get("evaluation") is not None:
            raise ValueError("holdout evaluation is one-shot and already completed")
        supplied_hash = _sha_bytes(str(evaluator_token or "").encode("utf-8"))
        if not hmac.compare_digest(supplied_hash, str(meta["token_hash"])):
            raise PermissionError("invalid evaluator capability token")

        with open(self._data_path(vault_id), "rb") as handle:
            dataset = handle.read()
        digest = _sha_bytes(dataset)
        if not hmac.compare_digest(digest, str(meta["dataset_sha256"])):
            raise ValueError("holdout dataset integrity check failed")

        evaluator_packet = {
            "vault_id": meta["vault_id"],
            "dataset_sha256": meta["dataset_sha256"],
            "public_metadata": dict(meta.get("public_metadata") or {}),
            "candidate": dict(meta["candidate"]),
        }
        result = self._validate_result(evaluator(dataset, evaluator_packet))
        receipt = {
            "vault_id": meta["vault_id"],
            "candidate_id": meta["candidate"]["candidate_id"],
            "dataset_sha256": digest,
            "protocol_hash": meta["candidate"]["protocol_hash"],
            "candidate_freeze_hash": meta["candidate"]["freeze_hash"],
            "result_hash": _sha_json(result),
            "result": result,
            "evaluated_at": _now(),
        }
        meta["evaluation"] = receipt
        meta["state"] = "EVALUATED"
        meta["token_hash"] = _sha_bytes(secrets.token_bytes(32))
        self._save(meta)
        return EvaluationReceipt(
            vault_id=receipt["vault_id"],
            candidate_id=receipt["candidate_id"],
            dataset_sha256=receipt["dataset_sha256"],
            protocol_hash=receipt["protocol_hash"],
            result_hash=receipt["result_hash"],
            result=dict(receipt["result"]),
            evaluated_at=receipt["evaluated_at"],
        )

    def evaluation_receipt(self, vault_id: str) -> Optional[Dict[str, Any]]:
        meta = self._load(vault_id)
        receipt = meta.get("evaluation")
        return dict(receipt) if isinstance(receipt, Mapping) else None

    def verify_integrity(self, vault_id: str) -> bool:
        meta = self._load(vault_id)
        with open(self._data_path(vault_id), "rb") as handle:
            digest = _sha_bytes(handle.read())
        return hmac.compare_digest(digest, str(meta["dataset_sha256"]))


@dataclass(frozen=True)
class BlindPacket:
    evaluation_id: str
    candidate_id: str
    implementation_hash: str
    protocol_hash: str
    instructions: Mapping[str, Any]


class DoubleBlindCoordinator:
    """Keep builder theory and evaluator holdout knowledge on separate surfaces."""

    def __init__(self):
        self._evaluations: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        evaluation_id: str,
        *,
        candidate_id: str,
        builder_theory: str,
        implementation_hash: str,
        protocol_hash: str,
        evaluator_instructions: Mapping[str, Any],
    ) -> None:
        evaluation_id = _safe_id(evaluation_id, "evaluation_id")
        if evaluation_id in self._evaluations:
            raise ValueError("evaluation_id already exists")
        if not str(builder_theory).strip():
            raise ValueError("builder_theory is required")
        self._evaluations[evaluation_id] = {
            "candidate_id": _safe_id(candidate_id, "candidate_id"),
            "builder_theory": str(builder_theory),
            "implementation_hash": str(implementation_hash).strip(),
            "protocol_hash": str(protocol_hash).strip(),
            "evaluator_instructions": dict(evaluator_instructions),
            "result": None,
        }

    def evaluator_packet(self, evaluation_id: str) -> BlindPacket:
        record = self._evaluations[_safe_id(evaluation_id, "evaluation_id")]
        return BlindPacket(
            evaluation_id=evaluation_id,
            candidate_id=record["candidate_id"],
            implementation_hash=record["implementation_hash"],
            protocol_hash=record["protocol_hash"],
            instructions=dict(record["evaluator_instructions"]),
        )

    def record_result(self, evaluation_id: str, result: Mapping[str, Any]) -> None:
        record = self._evaluations[_safe_id(evaluation_id, "evaluation_id")]
        if record["result"] is not None:
            raise ValueError("blind evaluation result is immutable")
        record["result"] = dict(result)

    def reveal_after_evaluation(self, evaluation_id: str) -> Dict[str, Any]:
        record = self._evaluations[_safe_id(evaluation_id, "evaluation_id")]
        if record["result"] is None:
            raise ValueError("theory remains sealed until evaluation result exists")
        return {
            "evaluation_id": evaluation_id,
            "candidate_id": record["candidate_id"],
            "builder_theory": record["builder_theory"],
            "result": dict(record["result"]),
        }
