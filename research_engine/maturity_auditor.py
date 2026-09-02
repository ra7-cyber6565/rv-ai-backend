"""Trusted repository-derived maturity auditing.

This is the high-trust facade around ``ProofLedger``. Callers cannot provide a
revision or current file hashes. The auditor derives the exact Git checkout,
requires a clean worktree, reads a committed proof policy, hashes tracked regular
files itself, verifies the keyed ledger + external anchor, and only then maps
accepted receipts into the 142-capability registry.

The resulting percentage remains a proof-completion score. It is not a truth,
safety, profitability, or real-world success probability.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Mapping, Sequence, Tuple

from utils.release_identity import repository_identity

from .capability_registry import (
    CAPABILITY_BY_ID,
    CapabilityEvidence,
    MaturityReport,
    ProofKind,
    assess_capabilities,
)
from .maturity_proof import ProofLedger, ProofLedgerStatus


_POLICY_SCHEMA_VERSION = 1
_MAX_POLICY_BYTES = 1_048_576
_MAX_EVIDENCE_FILE_BYTES = 16 * 1024 * 1024
_REGULAR_GIT_MODES = {"100644", "100755"}
_REVISION_BOUND = {
    ProofKind.WIRING,
    ProofKind.EXECUTION,
    ProofKind.INDEPENDENT,
    ProofKind.PERSISTENCE,
    ProofKind.RUNTIME,
    ProofKind.LIVE,
    ProofKind.HARDWARE,
    ProofKind.SAFETY,
    ProofKind.REPRODUCIBILITY,
}
_FILE_PROOFS = {ProofKind.CODE, ProofKind.TEST}
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_repo_path(value: object, *, field: str) -> str:
    text = str(value or "")
    if not text or len(text) > 1_000 or "\\" in text or "\x00" in text:
        raise ValueError(f"{field} is not a safe repository path")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field} is not a safe repository path")
    normalized = path.as_posix()
    if normalized != text:
        raise ValueError(f"{field} must use canonical POSIX spelling")
    return normalized


def _safe_token(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_TOKEN_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


@dataclass(frozen=True)
class ProofRule:
    capability_id: int
    proof_kind: ProofKind
    subjects: Tuple[str, ...]
    verifiers: Tuple[str, ...]
    reference_prefixes: Tuple[str, ...] = ()

    def allows(self, row: Mapping[str, Any]) -> bool:
        if int(row.get("capability_id", -1)) != self.capability_id:
            return False
        if str(row.get("proof_kind") or "") != self.proof_kind.value:
            return False
        if str(row.get("subject") or "") not in self.subjects:
            return False
        if str(row.get("verifier") or "") not in self.verifiers:
            return False
        if self.reference_prefixes:
            reference = str(row.get("reference") or "")
            if not any(reference.startswith(prefix) for prefix in self.reference_prefixes):
                return False
        return True


@dataclass(frozen=True)
class RepositoryProofPolicy:
    rules: Tuple[ProofRule, ...]
    sha256: str

    def allows(self, row: Mapping[str, Any]) -> bool:
        return any(rule.allows(row) for rule in self.rules)


@dataclass(frozen=True)
class ReceiptRejection:
    receipt_id: str
    reason: str


@dataclass(frozen=True)
class CapabilityBlocker:
    capability_id: int
    name: str
    missing_proofs: Tuple[str, ...]


@dataclass(frozen=True)
class TrustedMaturityAudit:
    revision: str
    repository_clean: bool
    cryptographic_integrity: bool
    tracked_regular_files: int
    accepted_receipts: int
    rejected_receipts: Tuple[ReceiptRejection, ...]
    policy_sha256: str
    maturity_report: MaturityReport
    ledger_status: ProofLedgerStatus
    blockers: Tuple[CapabilityBlocker, ...]
    audit_sha256: str

    @property
    def audit_valid(self) -> bool:
        return (
            self.repository_clean
            and self.cryptographic_integrity
            and not self.rejected_receipts
        )

    @property
    def max_level_eligible(self) -> bool:
        return self.audit_valid and self.maturity_report.all_verified


def _run_git(root: Path, args: Sequence[str], *, binary: bool = False):
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=not binary,
            encoding=None if binary else "utf-8",
            errors=None if binary else "strict",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise ValueError("trusted Git inspection failed") from exc
    if proc.returncode != 0:
        raise ValueError("trusted Git inspection failed")
    return proc.stdout


def _tracked_index(root: Path) -> Mapping[str, str]:
    raw = _run_git(root, ["ls-files", "--stage", "-z"], binary=True)
    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError("Git index output was not binary")
    tracked: Dict[str, str] = {}
    for record in bytes(raw).split(b"\x00"):
        if not record:
            continue
        try:
            metadata, path_bytes = record.split(b"\t", 1)
            mode_b, _object_b, stage_b = metadata.split(b" ", 2)
            path = path_bytes.decode("utf-8", "strict")
            mode = mode_b.decode("ascii", "strict")
            stage = stage_b.decode("ascii", "strict")
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Git index contains an unsupported path record") from exc
        canonical = _safe_repo_path(path, field="tracked path")
        if stage != "0":
            raise ValueError("repository index contains unmerged entries")
        if canonical in tracked:
            raise ValueError("repository index contains duplicate paths")
        tracked[canonical] = mode
    return tracked


def _hash_tracked_regular(
    root: Path,
    tracked: Mapping[str, str],
    subject: str,
    *,
    max_bytes: int = _MAX_EVIDENCE_FILE_BYTES,
) -> str:
    canonical = _safe_repo_path(subject, field="evidence subject")
    mode = tracked.get(canonical)
    if mode is None:
        raise ValueError("evidence subject is not tracked")
    if mode not in _REGULAR_GIT_MODES:
        raise ValueError("evidence subject is not a tracked regular file")

    root_resolved = root.resolve(strict=True)
    candidate = root.joinpath(*PurePosixPath(canonical).parts)
    try:
        info = candidate.lstat()
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("evidence subject escapes or cannot be resolved") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError("evidence subject is not a regular non-symlink file")
    if info.st_size < 0 or info.st_size > max_bytes:
        raise ValueError("evidence subject exceeds the hashing budget")

    hasher = hashlib.sha256()
    total = 0
    with candidate.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("evidence subject exceeds the hashing budget")
            hasher.update(chunk)
    return hasher.hexdigest()


def _read_policy_bytes(
    root: Path,
    tracked: Mapping[str, str],
    policy_path: str,
) -> bytes:
    canonical = _safe_repo_path(policy_path, field="policy_path")
    mode = tracked.get(canonical)
    if mode not in _REGULAR_GIT_MODES:
        raise ValueError("proof policy must be a tracked regular file")
    candidate = root.joinpath(*PurePosixPath(canonical).parts)
    root_resolved = root.resolve(strict=True)
    try:
        info = candidate.lstat()
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("proof policy escapes or cannot be resolved") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError("proof policy must not be a symlink")
    if info.st_size < 1 or info.st_size > _MAX_POLICY_BYTES:
        raise ValueError("proof policy size is invalid")
    data = candidate.read_bytes()
    if len(data) != info.st_size or len(data) > _MAX_POLICY_BYTES:
        raise ValueError("proof policy changed during read")

    # Compile the optional tracked route-extension manifest into the same bounded
    # rule schema consumed below.  This changes policy semantics only: it creates
    # no receipts and therefore cannot inflate maturity by itself.
    from .maturity_policy_extensions import merge_policy_route_extensions

    merged = merge_policy_route_extensions(
        root=root,
        tracked=tracked,
        base_policy_bytes=data,
    )
    if len(merged) > _MAX_POLICY_BYTES:
        raise ValueError("merged proof policy exceeds size budget")
    return merged


def _parse_policy(data: bytes) -> RepositoryProofPolicy:
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("proof policy is not valid UTF-8 JSON") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "rules"}:
        raise ValueError("proof policy top-level schema is invalid")
    if raw.get("schema_version") != _POLICY_SCHEMA_VERSION:
        raise ValueError("unsupported proof policy schema_version")
    rules_raw = raw.get("rules")
    if not isinstance(rules_raw, list) or len(rules_raw) > 2_000:
        raise ValueError("proof policy rules must be a bounded list")

    rules = []
    seen = set()
    for index, item in enumerate(rules_raw):
        if not isinstance(item, dict) or set(item) != {
            "capability_id",
            "proof_kind",
            "subjects",
            "verifiers",
            "reference_prefixes",
        }:
            raise ValueError(f"proof policy rule {index} schema is invalid")
        capability_id = item.get("capability_id")
        if type(capability_id) is not int or capability_id not in CAPABILITY_BY_ID:
            raise ValueError(f"proof policy rule {index} capability_id is invalid")
        try:
            proof_kind = ProofKind(item.get("proof_kind"))
        except ValueError as exc:
            raise ValueError(f"proof policy rule {index} proof_kind is invalid") from exc

        subjects_raw = item.get("subjects")
        verifiers_raw = item.get("verifiers")
        prefixes_raw = item.get("reference_prefixes")
        if (
            not isinstance(subjects_raw, list)
            or not subjects_raw
            or len(subjects_raw) > 50
            or not isinstance(verifiers_raw, list)
            or not verifiers_raw
            or len(verifiers_raw) > 20
            or not isinstance(prefixes_raw, list)
            or len(prefixes_raw) > 20
        ):
            raise ValueError(f"proof policy rule {index} lists are invalid")
        if proof_kind not in CAPABILITY_BY_ID[capability_id].required_proofs:
            raise ValueError(
                f"proof policy rule {index} names a proof not required by capability"
            )

        subjects = []
        for subject in subjects_raw:
            if not isinstance(subject, str):
                raise ValueError(f"proof policy rule {index} subject must be a string")
            if proof_kind in _FILE_PROOFS:
                text = _safe_repo_path(subject, field=f"rule {index} subject")
            else:
                text = _safe_token(subject, field=f"rule {index} subject")
            subjects.append(text)
        if len(set(subjects)) != len(subjects):
            raise ValueError(f"proof policy rule {index} has duplicate subjects")

        if any(not isinstance(value, str) for value in verifiers_raw):
            raise ValueError(f"proof policy rule {index} verifier must be a string")
        verifiers = tuple(
            _safe_token(value, field=f"rule {index} verifier")
            for value in verifiers_raw
        )
        if len(set(verifiers)) != len(verifiers):
            raise ValueError(f"proof policy rule {index} has duplicate verifiers")

        prefixes = []
        for value in prefixes_raw:
            if not isinstance(value, str):
                raise ValueError(
                    f"proof policy rule {index} reference prefix must be a string"
                )
            text = value
            if not text or len(text) > 200 or any(ord(ch) < 32 for ch in text):
                raise ValueError(f"proof policy rule {index} reference prefix is invalid")
            prefixes.append(text)
        if len(set(prefixes)) != len(prefixes):
            raise ValueError(f"proof policy rule {index} has duplicate reference prefixes")

        if proof_kind in _REVISION_BOUND and not prefixes:
            raise ValueError(
                f"proof policy rule {index} for {proof_kind.value} "
                "must constrain reference_prefixes"
            )

        key = (capability_id, proof_kind.value, tuple(sorted(subjects)))
        if key in seen:
            raise ValueError("proof policy contains duplicate capability/proof rules")
        seen.add(key)
        rules.append(
            ProofRule(
                capability_id=capability_id,
                proof_kind=proof_kind,
                subjects=tuple(subjects),
                verifiers=verifiers,
                reference_prefixes=tuple(prefixes),
            )
        )

    return RepositoryProofPolicy(
        rules=tuple(rules),
        sha256=_sha(_canonical(raw)),
    )


def _active_add_rows(
    ledger: ProofLedger,
    *,
    current_hashes: Mapping[str, str],
    now: float,
    revision: str,
    anchor_token: str,
) -> Tuple[list[Dict[str, Any]], ProofLedgerStatus]:
    return ledger._active_rows(  # noqa: SLF001 - same-package trusted facade
        current_hashes=current_hashes,
        now=now,
        current_revision=revision,
        anchor_token=anchor_token,
        require_cryptographic_integrity=True,
    )


def audit_repository_maturity(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    anchor_token: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
) -> TrustedMaturityAudit:
    """Run a fail-closed maturity audit against the exact clean Git checkout."""
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "")
    if not identity_before.get("available") or not identity_before.get("clean") or not revision:
        raise ValueError("trusted maturity audit requires a clean Git checkout")

    tracked = _tracked_index(root)
    policy_bytes = _read_policy_bytes(root, tracked, policy_path)
    policy = _parse_policy(policy_bytes)

    ledger = ProofLedger(str(ledger_path), integrity_key=integrity_key)
    if not anchor_token:
        raise ValueError("trusted external anchor is required")
    if not ledger.verify_chain(
        anchor_token=anchor_token,
        current_revision=revision,
    ):
        raise ValueError("proof ledger or trusted external anchor verification failed")

    events = ledger._events()  # noqa: SLF001 - chain verified immediately above
    revoked = {
        str(row.get("receipt_id") or "")
        for row in events
        if row.get("event_type") == "REVOKE"
    }
    current_hashes: Dict[str, str] = {}
    pre_rejections = []
    for row in events:
        if row.get("event_type") != "ADD":
            continue
        receipt_id = str(row.get("receipt_id") or "")
        if receipt_id in revoked:
            continue
        try:
            kind = ProofKind(str(row.get("proof_kind") or ""))
        except ValueError:
            pre_rejections.append(ReceiptRejection(receipt_id, "unknown_proof_kind"))
            continue
        if kind not in _FILE_PROOFS:
            continue
        subject = str(row.get("subject") or "")
        try:
            canonical = _safe_repo_path(subject, field="evidence subject")
            current_hashes[canonical] = _hash_tracked_regular(root, tracked, canonical)
        except ValueError as exc:
            pre_rejections.append(ReceiptRejection(receipt_id, str(exc)))

    active_rows, ledger_status = _active_add_rows(
        ledger,
        current_hashes=current_hashes,
        now=current_time,
        revision=revision,
        anchor_token=anchor_token,
    )

    grouped: Dict[int, Dict[ProofKind, list[str]]] = {}
    rejections = list(pre_rejections)
    accepted = 0
    for row in active_rows:
        receipt_id = str(row.get("receipt_id") or "")
        if not policy.allows(row):
            rejections.append(
                ReceiptRejection(receipt_id, "active_receipt_not_allowed_by_policy")
            )
            continue
        capability_id = int(row["capability_id"])
        kind = ProofKind(str(row["proof_kind"]))
        revision_label = str(row.get("implementation_revision") or "")
        label = (
            f"{row['subject']}@sha256:{row['subject_sha256']}"
            + (f"@rev:{revision_label}" if revision_label else "")
            + f"@verifier:{row['verifier']}"
            + (f"#{row['reference']}" if row.get("reference") else "")
        )
        grouped.setdefault(capability_id, {}).setdefault(kind, []).append(label)
        accepted += 1

    evidence = {
        capability_id: CapabilityEvidence(
            capability_id=capability_id,
            proofs={
                kind: tuple(sorted(set(values)))
                for kind, values in proofs.items()
            },
        )
        for capability_id, proofs in grouped.items()
    }
    report = assess_capabilities(evidence)
    blockers = tuple(
        CapabilityBlocker(
            capability_id=result.capability_id,
            name=result.name,
            missing_proofs=tuple(proof.value for proof in result.missing_proofs),
        )
        for result in report.results
        if result.status != "VERIFIED"
    )

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during maturity audit")

    rejections = tuple(sorted(
        set(rejections),
        key=lambda item: (item.receipt_id, item.reason),
    ))
    tracked_regular_files = sum(
        mode in _REGULAR_GIT_MODES for mode in tracked.values()
    )
    audit_payload = {
        "revision": revision,
        "repository_clean": True,
        "cryptographic_integrity": ledger_status.cryptographic_integrity,
        "tracked_regular_files": tracked_regular_files,
        "accepted_receipts": accepted,
        "rejected_receipts": [
            {"receipt_id": item.receipt_id, "reason": item.reason}
            for item in rejections
        ],
        "policy_sha256": policy.sha256,
        "verified": report.verified,
        "total": report.total,
        "proof_completion_score": report.proof_completion_score,
        "blocking_capability_ids": list(report.blocking_capability_ids),
        "ledger_head_hash": ledger_status.ledger_head_hash,
    }
    return TrustedMaturityAudit(
        revision=revision,
        repository_clean=True,
        cryptographic_integrity=ledger_status.cryptographic_integrity,
        tracked_regular_files=tracked_regular_files,
        accepted_receipts=accepted,
        rejected_receipts=rejections,
        policy_sha256=policy.sha256,
        maturity_report=report,
        ledger_status=ledger_status,
        blockers=blockers,
        audit_sha256=_sha(_canonical(audit_payload)),
    )
