"""Persistent tamper-evident proof ledger for the 142-capability maturity gate.

A capability name, source file or passing screenshot is not enough.  This ledger
stores explicit proof receipts in a hash chain, supports revocation/expiry, and
invalidates CODE/TEST receipts when the current file hash changes.  Only active
receipts are translated into ``CapabilityEvidence`` for the fail-closed
``capability_registry``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from .capability_registry import (
    CAPABILITY_BY_ID,
    CapabilityEvidence,
    MaturityReport,
    ProofKind,
    assess_capabilities,
)


_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA_VERSION = 1
_LIVE_PROOFS = {ProofKind.RUNTIME, ProofKind.LIVE}


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


def _safe_id(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _safe_sha(value: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA_RE.fullmatch(text):
        raise ValueError("subject_sha256 must be a 64-character SHA-256 hex digest")
    return text


@dataclass(frozen=True)
class ProofReceipt:
    receipt_id: str
    capability_id: int
    proof_kind: ProofKind
    subject: str
    subject_sha256: str
    verifier: str
    observed_at: float
    valid_until: Optional[float]
    reference: str
    sequence: int
    event_hash: str


@dataclass(frozen=True)
class ProofLedgerStatus:
    integrity_valid: bool
    active_receipts: int
    revoked_receipts: int
    expired_receipts: int
    stale_file_receipts: int
    ledger_head_hash: str


class ProofLedger:
    """Cross-process append-only JSONL ledger with a SHA-256 event chain."""

    def __init__(self, path: str, *, lock_timeout_seconds: float = 3.0):
        self.path = os.path.abspath(path)
        self.lock_path = f"{self.path}.lock"
        self.lock_timeout_seconds = max(0.1, float(lock_timeout_seconds))
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        if not os.path.exists(self.path):
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @contextmanager
    def _lock(self):
        deadline = time.monotonic() + self.lock_timeout_seconds
        descriptor = None
        while descriptor is None:
            try:
                descriptor = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                os.write(
                    descriptor,
                    f"pid={os.getpid()} time={time.time()}".encode("ascii", "replace"),
                )
            except FileExistsError:
                # Operations are tiny. A very old lock is treated as a crashed
                # writer; a current lock is never stolen before the timeout.
                try:
                    age = time.time() - os.path.getmtime(self.lock_path)
                except OSError:
                    age = 0.0
                if age > 60.0:
                    try:
                        os.remove(self.lock_path)
                    except OSError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError("proof ledger is locked")
                time.sleep(0.01)
        try:
            yield
        finally:
            try:
                os.close(descriptor)
            finally:
                try:
                    os.remove(self.lock_path)
                except OSError:
                    pass

    def _events(self) -> list[Dict[str, Any]]:
        events = []
        with open(self.path, "r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except Exception as exc:
                    raise ValueError(
                        f"proof ledger line {line_number} is invalid JSON"
                    ) from exc
                if not isinstance(row, dict):
                    raise ValueError(f"proof ledger line {line_number} is not an object")
                events.append(row)
        return events

    @staticmethod
    def _verify_events(events: list[Dict[str, Any]]) -> bool:
        previous_hash = "GENESIS"
        for sequence, row in enumerate(events, start=1):
            if row.get("schema_version") != _SCHEMA_VERSION:
                return False
            if row.get("sequence") != sequence:
                return False
            if row.get("previous_hash") != previous_hash:
                return False
            payload = dict(row)
            claimed_hash = str(payload.pop("event_hash", ""))
            try:
                expected_hash = _sha(_canonical(payload))
            except (TypeError, ValueError):
                return False
            if not hmac.compare_digest(claimed_hash, expected_hash):
                return False
            previous_hash = claimed_hash
        return True

    def verify_chain(self) -> bool:
        try:
            return self._verify_events(self._events())
        except (OSError, ValueError):
            return False

    def _append(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self._lock():
            events = self._events()
            if not self._verify_events(events):
                raise ValueError("proof ledger integrity failure")
            row = {
                "schema_version": _SCHEMA_VERSION,
                "sequence": len(events) + 1,
                **dict(payload),
                "previous_hash": (
                    str(events[-1]["event_hash"]) if events else "GENESIS"
                ),
            }
            row["event_hash"] = _sha(_canonical(row))
            encoded = json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            with open(self.path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return row

    def add(
        self,
        *,
        receipt_id: str,
        capability_id: int,
        proof_kind: ProofKind | str,
        subject: str,
        subject_sha256: str,
        verifier: str,
        observed_at: float,
        reference: str = "",
        valid_until: Optional[float] = None,
    ) -> ProofReceipt:
        receipt_id = _safe_id(receipt_id, "receipt_id")
        verifier = _safe_id(verifier, "verifier")
        if capability_id not in CAPABILITY_BY_ID:
            raise ValueError("unknown capability_id")
        try:
            kind = proof_kind if isinstance(proof_kind, ProofKind) else ProofKind(proof_kind)
        except ValueError as exc:
            raise ValueError("unknown proof kind") from exc
        subject = str(subject or "").strip()
        if not subject or len(subject) > 1_000:
            raise ValueError("subject is required and must be bounded")
        digest = _safe_sha(subject_sha256)
        observation_time = float(observed_at)
        if not math.isfinite(observation_time):
            raise ValueError("observed_at must be finite")
        expiry = None if valid_until is None else float(valid_until)
        if expiry is not None and (
            not math.isfinite(expiry) or expiry <= observation_time
        ):
            raise ValueError("valid_until must be finite and after observed_at")
        if kind in _LIVE_PROOFS and expiry is None:
            raise ValueError("runtime/live proof must have valid_until")
        reference = str(reference or "").strip()[:2_000]

        events = self._events()
        if any(
            row.get("event_type") == "ADD"
            and row.get("receipt_id") == receipt_id
            for row in events
        ):
            raise ValueError("receipt_id already exists")

        row = self._append({
            "event_type": "ADD",
            "receipt_id": receipt_id,
            "capability_id": capability_id,
            "proof_kind": kind.value,
            "subject": subject,
            "subject_sha256": digest,
            "verifier": verifier,
            "observed_at": observation_time,
            "valid_until": expiry,
            "reference": reference,
        })
        return ProofReceipt(
            receipt_id=receipt_id,
            capability_id=capability_id,
            proof_kind=kind,
            subject=subject,
            subject_sha256=digest,
            verifier=verifier,
            observed_at=observation_time,
            valid_until=expiry,
            reference=reference,
            sequence=int(row["sequence"]),
            event_hash=str(row["event_hash"]),
        )

    def revoke(self, receipt_id: str, *, reason: str) -> str:
        receipt_id = _safe_id(receipt_id, "receipt_id")
        reason = str(reason or "").strip()
        if not reason or len(reason) > 1_000:
            raise ValueError("revocation reason is required and must be bounded")
        events = self._events()
        if not any(
            row.get("event_type") == "ADD"
            and row.get("receipt_id") == receipt_id
            for row in events
        ):
            raise KeyError(receipt_id)
        if any(
            row.get("event_type") == "REVOKE"
            and row.get("receipt_id") == receipt_id
            for row in events
        ):
            raise ValueError("receipt already revoked")
        row = self._append({
            "event_type": "REVOKE",
            "receipt_id": receipt_id,
            "reason": reason,
        })
        return str(row["event_hash"])

    def _active_rows(
        self,
        *,
        current_hashes: Mapping[str, str],
        now: float,
    ) -> Tuple[list[Dict[str, Any]], ProofLedgerStatus]:
        current_time = float(now)
        if not math.isfinite(current_time):
            raise ValueError("now must be finite")
        events = self._events()
        if not self._verify_events(events):
            raise ValueError("proof ledger integrity failure")

        revoked = {
            str(row["receipt_id"])
            for row in events
            if row.get("event_type") == "REVOKE"
        }
        active = []
        expired_count = 0
        stale_count = 0
        for row in events:
            if row.get("event_type") != "ADD":
                continue
            if str(row.get("receipt_id")) in revoked:
                continue
            expiry = row.get("valid_until")
            if expiry is not None and current_time >= float(expiry):
                expired_count += 1
                continue
            kind = ProofKind(str(row["proof_kind"]))
            if kind in {ProofKind.CODE, ProofKind.TEST}:
                current_digest = str(current_hashes.get(str(row["subject"]), "")).lower()
                if not _SHA_RE.fullmatch(current_digest) or not hmac.compare_digest(
                    current_digest,
                    str(row["subject_sha256"]),
                ):
                    stale_count += 1
                    continue
            active.append(row)

        head = str(events[-1]["event_hash"]) if events else "GENESIS"
        return active, ProofLedgerStatus(
            integrity_valid=True,
            active_receipts=len(active),
            revoked_receipts=len(revoked),
            expired_receipts=expired_count,
            stale_file_receipts=stale_count,
            ledger_head_hash=head,
        )

    def evidence(
        self,
        *,
        current_hashes: Mapping[str, str],
        now: float,
    ) -> Tuple[Mapping[int, CapabilityEvidence], ProofLedgerStatus]:
        rows, status = self._active_rows(current_hashes=current_hashes, now=now)
        grouped: Dict[int, Dict[ProofKind, list[str]]] = {}
        for row in rows:
            capability_id = int(row["capability_id"])
            kind = ProofKind(str(row["proof_kind"]))
            label = (
                f"{row['subject']}@sha256:{row['subject_sha256']}"
                + (f"#{row['reference']}" if row.get("reference") else "")
            )
            grouped.setdefault(capability_id, {}).setdefault(kind, []).append(label)
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
        return evidence, status

    def maturity_report(
        self,
        *,
        current_hashes: Mapping[str, str],
        now: float,
    ) -> Tuple[MaturityReport, ProofLedgerStatus]:
        evidence, status = self.evidence(current_hashes=current_hashes, now=now)
        return assess_capabilities(evidence), status
