"""Persistent proof ledger for the 142-capability maturity gate.

Two integrity modes are intentionally distinct:

* ``sha256-chain`` detects accidental/unsophisticated mutation but is NOT called
  cryptographic integrity against an attacker who can rewrite the whole file.
* ``hmac-sha256`` uses an externally supplied secret. A signed external anchor
  binds the current head+sequence+implementation revision, closing the otherwise
  unavoidable valid-prefix truncation/rollback gap.

The secret is never stored in the ledger. A trusted caller must keep the latest
anchor outside the mutable ledger (for example a protected CI/remote receipt).
Without both a keyed chain and a matching trusted anchor,
``cryptographic_integrity`` is false.

CODE/TEST receipts are stale when current file hashes change. Every non-file
verification proof is also bound to the exact implementation revision it
observed, so old execution/reproducibility/safety/runtime evidence cannot migrate
onto changed code.
"""
from __future__ import annotations

import base64
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
_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SCHEMA_VERSION = 1
_ANCHOR_VERSION = 1
_MAX_ANCHOR_CHARS = 8_192
_SHA_CHAIN = "sha256-chain"
_HMAC_CHAIN = "hmac-sha256"
_LIVE_PROOFS = {ProofKind.RUNTIME, ProofKind.LIVE}
_FILE_HASH_PROOFS = {ProofKind.CODE, ProofKind.TEST}
_REVISION_BOUND_PROOFS = {
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


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    """Decode only the one canonical unpadded base64url spelling.

    ``urlsafe_b64decode`` accepts alternate final characters whose unused pad
    bits decode to the same bytes. That makes a signed token textually malleable.
    Re-encoding and constant-time comparison rejects those aliases as well as
    padding/non-base64url input.
    """
    raw = str(text or "")
    if not raw or not _B64URL_RE.fullmatch(raw):
        raise ValueError("invalid base64url")
    padding = "=" * ((4 - len(raw) % 4) % 4)
    decoded = base64.urlsafe_b64decode((raw + padding).encode("ascii"))
    if not hmac.compare_digest(_b64(decoded), raw):
        raise ValueError("non-canonical base64url")
    return decoded


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


def _safe_revision(value: str, *, required: bool) -> str:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ValueError("implementation_revision is required for this proof kind")
        return ""
    if not _ID_RE.fullmatch(text):
        raise ValueError("implementation_revision is invalid")
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
    implementation_revision: str
    integrity_mode: str
    sequence: int
    event_hash: str


@dataclass(frozen=True)
class ProofLedgerStatus:
    integrity_valid: bool
    active_receipts: int
    revoked_receipts: int
    expired_receipts: int
    stale_file_receipts: int
    stale_revision_receipts: int
    keyed_events: int
    unkeyed_events: int
    anchor_verified: bool
    cryptographic_integrity: bool
    ledger_head_hash: str


class ProofLedger:
    """Append-only JSONL chain with optional external-key HMAC integrity."""

    def __init__(
        self,
        path: str,
        *,
        lock_timeout_seconds: float = 3.0,
        integrity_key: Optional[bytes] = None,
    ):
        self.path = os.path.abspath(path)
        self.lock_path = f"{self.path}.lock"
        self.lock_timeout_seconds = max(0.1, float(lock_timeout_seconds))
        if integrity_key is not None:
            if not isinstance(integrity_key, (bytes, bytearray)) or len(integrity_key) < 32:
                raise ValueError("integrity_key must be at least 32 bytes")
            self._integrity_key: Optional[bytes] = bytes(integrity_key)
        else:
            self._integrity_key = None
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        if not os.path.exists(self.path):
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @property
    def integrity_mode(self) -> str:
        return _HMAC_CHAIN if self._integrity_key is not None else _SHA_CHAIN

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

    def _digest(self, payload: Mapping[str, Any], mode: str) -> str:
        encoded = _canonical(payload)
        if mode == _SHA_CHAIN:
            return _sha(encoded)
        if mode == _HMAC_CHAIN:
            if self._integrity_key is None:
                raise ValueError("HMAC ledger requires integrity_key")
            return hmac.new(
                self._integrity_key, encoded, hashlib.sha256
            ).hexdigest()
        raise ValueError("unknown ledger integrity mode")

    def _verify_events(self, events: list[Dict[str, Any]]) -> bool:
        previous_hash = "GENESIS"
        keyed_started = False
        for sequence, row in enumerate(events, start=1):
            if row.get("schema_version") != _SCHEMA_VERSION:
                return False
            if row.get("sequence") != sequence:
                return False
            if row.get("previous_hash") != previous_hash:
                return False
            # Historical v1 rows did not carry an integrity_mode and are treated
            # as plain SHA rows. Once keyed mode starts, downgrade back to plain
            # SHA is rejected.
            mode = str(row.get("integrity_mode") or _SHA_CHAIN)
            if mode == _HMAC_CHAIN:
                keyed_started = True
                if self._integrity_key is None:
                    return False
            elif mode == _SHA_CHAIN:
                if keyed_started:
                    return False
            else:
                return False
            payload = dict(row)
            claimed_hash = str(payload.pop("event_hash", ""))
            try:
                expected_hash = self._digest(payload, mode)
            except (TypeError, ValueError):
                return False
            if not hmac.compare_digest(claimed_hash, expected_hash):
                return False
            previous_hash = claimed_hash
        return True

    def verify_chain(
        self,
        *,
        anchor_token: str = "",
        current_revision: str = "",
    ) -> bool:
        try:
            events = self._events()
            if not self._verify_events(events):
                return False
            if anchor_token:
                return self.verify_anchor(
                    anchor_token, current_revision=current_revision
                )
            return True
        except (OSError, ValueError):
            return False

    def _append(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self._lock():
            events = self._events()
            if not self._verify_events(events):
                raise ValueError("proof ledger integrity failure")
            mode = self.integrity_mode
            # A keyed history can never be extended by a no-key writer.
            if events and str(events[-1].get("integrity_mode") or _SHA_CHAIN) == _HMAC_CHAIN \
                    and mode != _HMAC_CHAIN:
                raise ValueError("keyed proof ledger cannot be extended without integrity_key")
            row = {
                "schema_version": _SCHEMA_VERSION,
                "sequence": len(events) + 1,
                **dict(payload),
                "integrity_mode": mode,
                "previous_hash": (
                    str(events[-1]["event_hash"]) if events else "GENESIS"
                ),
            }
            row["event_hash"] = self._digest(row, mode)
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
        implementation_revision: str = "",
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
        revision = _safe_revision(
            implementation_revision,
            required=(kind in _REVISION_BOUND_PROOFS),
        )
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
            "implementation_revision": revision,
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
            implementation_revision=revision,
            integrity_mode=str(row["integrity_mode"]),
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

    def create_anchor(
        self,
        *,
        current_revision: str,
        issued_at: float,
    ) -> str:
        """Create an HMAC anchor to be stored outside the mutable ledger."""
        if self._integrity_key is None:
            raise ValueError("integrity_key is required to create an anchor")
        revision = _safe_revision(current_revision, required=True)
        timestamp = float(issued_at)
        if not math.isfinite(timestamp):
            raise ValueError("issued_at must be finite")
        events = self._events()
        if not events or not self._verify_events(events):
            raise ValueError("valid non-empty ledger required for anchor")
        last_mode = str(events[-1].get("integrity_mode") or _SHA_CHAIN)
        if last_mode != _HMAC_CHAIN:
            raise ValueError("latest ledger event is not keyed")
        payload = {
            "v": _ANCHOR_VERSION,
            "sequence": len(events),
            "head_hash": str(events[-1]["event_hash"]),
            "implementation_revision": revision,
            "issued_at": timestamp,
        }
        body = _canonical(payload)
        signature = hmac.new(
            self._integrity_key,
            b"proof-ledger-anchor-v1\x00" + body,
            hashlib.sha256,
        ).digest()
        return f"{_b64(body)}.{_b64(signature)}"

    def verify_anchor(self, token: str, *, current_revision: str) -> bool:
        """Verify a trusted external anchor against this exact ledger head."""
        if self._integrity_key is None:
            return False
        text = str(token or "").strip()
        if not text or len(text) > _MAX_ANCHOR_CHARS or text.count(".") != 1:
            return False
        try:
            revision = _safe_revision(current_revision, required=True)
            body_b64, signature_b64 = text.split(".", 1)
            body = _unb64(body_b64)
            signature = _unb64(signature_b64)
            expected = hmac.new(
                self._integrity_key,
                b"proof-ledger-anchor-v1\x00" + body,
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(signature, expected):
                return False
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("v") != _ANCHOR_VERSION:
                return False
            if not hmac.compare_digest(body, _canonical(payload)):
                return False
            sequence = payload.get("sequence")
            head_hash = str(payload.get("head_hash") or "")
            anchor_revision = str(payload.get("implementation_revision") or "")
            issued_at = float(payload.get("issued_at"))
            if type(sequence) is not int or sequence <= 0:
                return False
            if not _SHA_RE.fullmatch(head_hash) or not math.isfinite(issued_at):
                return False
            if not hmac.compare_digest(anchor_revision, revision):
                return False
            events = self._events()
            if not self._verify_events(events) or len(events) != sequence:
                return False
            if not events:
                return False
            if str(events[-1].get("integrity_mode") or _SHA_CHAIN) != _HMAC_CHAIN:
                return False
            return hmac.compare_digest(str(events[-1]["event_hash"]), head_hash)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError):
            return False
        except Exception:
            # Invalid base64 and malformed attacker-controlled token input fail closed.
            return False

    def _active_rows(
        self,
        *,
        current_hashes: Mapping[str, str],
        now: float,
        current_revision: str = "",
        anchor_token: str = "",
        require_cryptographic_integrity: bool = False,
    ) -> Tuple[list[Dict[str, Any]], ProofLedgerStatus]:
        current_time = float(now)
        if not math.isfinite(current_time):
            raise ValueError("now must be finite")
        revision = _safe_revision(current_revision, required=False)
        events = self._events()
        if not self._verify_events(events):
            raise ValueError("proof ledger integrity failure")

        keyed_events = sum(
            str(row.get("integrity_mode") or _SHA_CHAIN) == _HMAC_CHAIN
            for row in events
        )
        unkeyed_events = len(events) - keyed_events
        anchor_verified = bool(
            anchor_token
            and revision
            and self.verify_anchor(anchor_token, current_revision=revision)
        )
        cryptographic_integrity = bool(
            self._integrity_key is not None
            and events
            and str(events[-1].get("integrity_mode") or _SHA_CHAIN) == _HMAC_CHAIN
            and anchor_verified
        )
        if require_cryptographic_integrity and not cryptographic_integrity:
            raise ValueError(
                "keyed ledger plus matching trusted external anchor required"
            )

        revoked = {
            str(row["receipt_id"])
            for row in events
            if row.get("event_type") == "REVOKE"
        }
        active = []
        expired_count = 0
        stale_file_count = 0
        stale_revision_count = 0
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
            if kind in _FILE_HASH_PROOFS:
                current_digest = str(current_hashes.get(str(row["subject"]), "")).lower()
                if not _SHA_RE.fullmatch(current_digest) or not hmac.compare_digest(
                    current_digest,
                    str(row["subject_sha256"]),
                ):
                    stale_file_count += 1
                    continue
            if kind in _REVISION_BOUND_PROOFS:
                receipt_revision = str(row.get("implementation_revision") or "").strip()
                if (
                    not revision
                    or not receipt_revision
                    or not hmac.compare_digest(revision, receipt_revision)
                ):
                    stale_revision_count += 1
                    continue
            active.append(row)

        head = str(events[-1]["event_hash"]) if events else "GENESIS"
        return active, ProofLedgerStatus(
            integrity_valid=True,
            active_receipts=len(active),
            revoked_receipts=len(revoked),
            expired_receipts=expired_count,
            stale_file_receipts=stale_file_count,
            stale_revision_receipts=stale_revision_count,
            keyed_events=keyed_events,
            unkeyed_events=unkeyed_events,
            anchor_verified=anchor_verified,
            cryptographic_integrity=cryptographic_integrity,
            ledger_head_hash=head,
        )

    def evidence(
        self,
        *,
        current_hashes: Mapping[str, str],
        now: float,
        current_revision: str = "",
        anchor_token: str = "",
        require_cryptographic_integrity: bool = False,
    ) -> Tuple[Mapping[int, CapabilityEvidence], ProofLedgerStatus]:
        rows, status = self._active_rows(
            current_hashes=current_hashes,
            now=now,
            current_revision=current_revision,
            anchor_token=anchor_token,
            require_cryptographic_integrity=require_cryptographic_integrity,
        )
        grouped: Dict[int, Dict[ProofKind, list[str]]] = {}
        for row in rows:
            capability_id = int(row["capability_id"])
            kind = ProofKind(str(row["proof_kind"]))
            revision = str(row.get("implementation_revision") or "")
            label = (
                f"{row['subject']}@sha256:{row['subject_sha256']}"
                + (f"@rev:{revision}" if revision else "")
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
        current_revision: str = "",
        anchor_token: str = "",
        require_cryptographic_integrity: bool = False,
    ) -> Tuple[MaturityReport, ProofLedgerStatus]:
        evidence, status = self.evidence(
            current_hashes=current_hashes,
            now=now,
            current_revision=current_revision,
            anchor_token=anchor_token,
            require_cryptographic_integrity=require_cryptographic_integrity,
        )
        return assess_capabilities(evidence), status
