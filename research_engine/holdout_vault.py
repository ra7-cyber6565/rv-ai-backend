"""Application-level sealed holdout vault and double-blind evaluation state machine.

The builder never receives holdout bytes/token/path. Candidate implementation and
protocol are frozen before one-shot evaluation. Dataset/result commitments are
SHA-256 audited. This is an application boundary, not DRM against an OS admin;
stronger deployments should isolate the vault behind a separate evaluator/KMS.
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


def _required_text(value: Any, field: str, max_length: int = 1000) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    if len(text) > max_length:
        raise ValueError(f"{field} is too long")
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
        required = {"schema_version", "vault_id", "dataset_sha256", "token_hash", "state"}
        if meta.get("schema_version") != _SCHEMA_VERSION or not required.issubset(meta):
            raise ValueError("unsupported or corrupted holdout vault metadata")
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
        label = _required_text(dataset_label, "dataset_label", 300)
        if not isinstance(dataset, (bytes, bytearray)) or not dataset:
            raise ValueError("dataset must be non-empty bytes")
        data_path = self._data_path(vault_id)
        meta_path = self._meta_path(vault_id)
        if os.path.exists(meta_path) or os.path.exists(data_path):
            raise ValueError("vault_id already exists")

        dataset_bytes = bytes(dataset)
        digest = _sha_bytes(dataset_bytes)
        token = secrets.token_urlsafe(32)
        meta = {
            "schema_version": _SCHEMA_VERSION,
            "vault_id": vault_id,
            "dataset_label": label,
            "dataset_sha256": digest,
            "dataset_bytes": len(dataset_bytes),
            "public_metadata": dict(metadata or {}),
            "token_hash": _sha_bytes(token.encode("utf-8")),
            "state": "SEALED",
            "created_at": _now(),
            "candidate": None,
            "evaluation": None,
        }
        # Validate everything before persisting either member, avoiding orphaned data.
        json.dumps(meta, ensure_ascii=False, sort_keys=True)
        self._write_atomic(data_path, dataset_bytes)
        try:
            self._save(meta)
        except Exception:
            try:
                os.remove(data_path)
            except OSError:
                pass
            raise
        return VaultCreation(vault_id, token, digest, "SEALED")

    def builder_view(self, vault_id: str) -> Dict[str, Any]:
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
        if not isinstance(evaluator_instructions, Mapping):
            raise ValueError("evaluator_instructions must be a mapping")
        candidate = {
            "candidate_id": _safe_id(candidate_id, "candidate_id"),
            "implementation_hash": _required_text(implementation_hash, "implementation_hash"),
            "protocol_hash": _required_text(protocol_hash, "protocol_hash"),
            "evaluator_instructions": dict(evaluator_instructions),
            "theory_blind": bool(theory_blind),
            "frozen_at": _now(),
        }
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
        try:
            encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("evaluation result must be finite JSON-serializable data") from exc
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

        packet = {
            "vault_id": meta["vault_id"],
            "dataset_sha256": meta["dataset_sha256"],
            "public_metadata": dict(meta.get("public_metadata") or {}),
            "candidate": dict(meta["candidate"]),
        }
        result = self._validate_result(evaluator(dataset, packet))
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
            vault_id=receipt["vault_id"], candidate_id=receipt["candidate_id"],
            dataset_sha256=receipt["dataset_sha256"], protocol_hash=receipt["protocol_hash"],
            result_hash=receipt["result_hash"], result=dict(receipt["result"]),
            evaluated_at=receipt["evaluated_at"],
        )

    def evaluation_receipt(self, vault_id: str) -> Optional[Dict[str, Any]]:
        receipt = self._load(vault_id).get("evaluation")
        return dict(receipt) if isinstance(receipt, Mapping) else None

    def verify_integrity(self, vault_id: str) -> bool:
        meta = self._load(vault_id)
        try:
            with open(self._data_path(vault_id), "rb") as handle:
                digest = _sha_bytes(handle.read())
        except OSError:
            return False
        return hmac.compare_digest(digest, str(meta["dataset_sha256"]))


@dataclass(frozen=True)
class BlindPacket:
    evaluation_id: str
    candidate_id: str
    implementation_hash: str
    protocol_hash: str
    instructions: Mapping[str, Any]


class DoubleBlindCoordinator:
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
        if not isinstance(evaluator_instructions, Mapping):
            raise ValueError("evaluator_instructions must be a mapping")
        record = {
            "candidate_id": _safe_id(candidate_id, "candidate_id"),
            "builder_theory": _required_text(builder_theory, "builder_theory", 20000),
            "implementation_hash": _required_text(implementation_hash, "implementation_hash"),
            "protocol_hash": _required_text(protocol_hash, "protocol_hash"),
            "evaluator_instructions": dict(evaluator_instructions),
            "result": None,
        }
        self._evaluations[evaluation_id] = record

    def evaluator_packet(self, evaluation_id: str) -> BlindPacket:
        evaluation_id = _safe_id(evaluation_id, "evaluation_id")
        record = self._evaluations[evaluation_id]
        return BlindPacket(
            evaluation_id=evaluation_id, candidate_id=record["candidate_id"],
            implementation_hash=record["implementation_hash"], protocol_hash=record["protocol_hash"],
            instructions=dict(record["evaluator_instructions"]),
        )

    def record_result(self, evaluation_id: str, result: Mapping[str, Any]) -> None:
        evaluation_id = _safe_id(evaluation_id, "evaluation_id")
        record = self._evaluations[evaluation_id]
        if record["result"] is not None:
            raise ValueError("blind evaluation result is immutable")
        record["result"] = HoldoutVault._validate_result(result)

    def reveal_after_evaluation(self, evaluation_id: str) -> Dict[str, Any]:
        evaluation_id = _safe_id(evaluation_id, "evaluation_id")
        record = self._evaluations[evaluation_id]
        if record["result"] is None:
            raise ValueError("theory remains sealed until evaluation result exists")
        return {
            "evaluation_id": evaluation_id,
            "candidate_id": record["candidate_id"],
            "builder_theory": record["builder_theory"],
            "result": dict(record["result"]),
        }
