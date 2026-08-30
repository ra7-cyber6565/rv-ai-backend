"""Persistent memory governance for capabilities #49, #53, #55 and #56.

This module complements, rather than replaces, ``ScientificMemory`` and
``ProceduralMemory``:

* #49 Knowledge Decay: deterministic time/reliability decay that can only lower
  a usable confidence ceiling until re-verification.
* #53 Memory Consolidation: non-destructive exact/declared-equivalence grouping
  with complete provenance retention. It never invents semantic equivalence.
* #55 Failure Memory: append-only, hash-chained failure records with explicit
  resolution history.
* #56 Mistake Taxonomy: bounded, stable mistake classes and recurrence analytics.

No consolidation deletes source memories, no failure is erased by resolution,
and a decayed memory is never automatically promoted back to fresh without a
new verification event.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


_SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_ALLOWED_MISTAKES = {
    "EVIDENCE_MISREAD",
    "SOURCE_QUALITY",
    "RELEVANCE_ERROR",
    "CAUSAL_ERROR",
    "LEAKAGE",
    "OVERFIT",
    "CALIBRATION_ERROR",
    "TOOL_FAILURE",
    "DATA_QUALITY",
    "ASSUMPTION_FAILURE",
    "IMPLEMENTATION_BUG",
    "REPRODUCIBILITY_FAILURE",
    "SECURITY_BOUNDARY",
    "RUNTIME_DRIFT",
    "UNKNOWN",
}
_MAX_RECORDS = 1_000_000


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
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _probability(value: object, field: str) -> float:
    number = _finite(value, field)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be in [0,1]")
    return number


def _timestamp(value: object, field: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _timestamp_text(value: object, field: str) -> str:
    return _timestamp(value, field).isoformat(timespec="seconds")


def _text(value: object, field: str, *, maximum: int = 8000) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum:
        raise ValueError(f"{field} is required and bounded")
    return text


@dataclass(frozen=True)
class DecayPolicy:
    half_life_days: float
    stale_after_days: float
    minimum_confidence_floor: float = 0.0

    def normalized(self) -> "DecayPolicy":
        half_life = _finite(self.half_life_days, "half_life_days")
        stale_after = _finite(self.stale_after_days, "stale_after_days")
        floor = _probability(self.minimum_confidence_floor, "minimum_confidence_floor")
        if half_life <= 0 or stale_after <= 0:
            raise ValueError("decay durations must be > 0")
        return DecayPolicy(half_life, stale_after, floor)


@dataclass(frozen=True)
class DecayAssessment:
    memory_id: str
    original_confidence: float
    usable_confidence_ceiling: float
    age_days: float
    decay_factor: float
    stale: bool
    revalidation_required: bool
    confidence_increased_by_decay: bool
    assessment_hash: str


def assess_knowledge_decay(
    *,
    memory_id: str,
    confidence: float,
    last_verified_at: str,
    now: str,
    policy: DecayPolicy,
) -> DecayAssessment:
    memory_id = _safe_id(memory_id, "memory_id")
    confidence = _probability(confidence, "confidence")
    policy = policy.normalized()
    verified = _timestamp(last_verified_at, "last_verified_at")
    current = _timestamp(now, "now")
    if current < verified:
        raise ValueError("now must not precede last verification")
    age_days = (current - verified).total_seconds() / 86400.0
    decay_factor = 0.5 ** (age_days / policy.half_life_days)
    raw_ceiling = confidence * decay_factor
    ceiling = max(policy.minimum_confidence_floor, raw_ceiling)
    # A configured floor must never cause stale-memory confidence to exceed its
    # original confidence.
    ceiling = min(confidence, ceiling)
    stale = age_days >= policy.stale_after_days
    payload = {
        "memory_id": memory_id,
        "original_confidence": confidence,
        "usable_confidence_ceiling": ceiling,
        "age_days": age_days,
        "decay_factor": decay_factor,
        "stale": stale,
        "revalidation_required": stale,
        "confidence_increased_by_decay": False,
    }
    return DecayAssessment(
        memory_id=memory_id,
        original_confidence=confidence,
        usable_confidence_ceiling=ceiling,
        age_days=age_days,
        decay_factor=decay_factor,
        stale=stale,
        revalidation_required=stale,
        confidence_increased_by_decay=False,
        assessment_hash=_sha(payload),
    )


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    content: Mapping[str, Any]
    provenance_ids: Tuple[str, ...]
    equivalence_key: str = ""


@dataclass(frozen=True)
class ConsolidationGroup:
    canonical_memory_id: str
    member_ids: Tuple[str, ...]
    provenance_ids: Tuple[str, ...]
    content_hash: str
    equivalence_key: str
    exact_content_match: bool
    destructive_merge_performed: bool = False


def consolidate_memories(records: Sequence[MemoryRecord]) -> Tuple[ConsolidationGroup, ...]:
    """Return deterministic consolidation views without mutating/deleting inputs.

    Records are grouped only when their canonical JSON content is identical OR
    the caller supplied the same non-empty ``equivalence_key``. A declared key
    is an explicit upstream assertion, not a semantic inference by this module.
    """
    if isinstance(records, (str, bytes, bytearray)) or not isinstance(records, Sequence):
        raise ValueError("records must be a finite sequence")
    if not 1 <= len(records) <= _MAX_RECORDS:
        raise ValueError("records must contain 1..1,000,000 items")
    normalized = []
    ids = set()
    for record in records:
        if not isinstance(record, MemoryRecord):
            raise ValueError("records must contain MemoryRecord objects")
        memory_id = _safe_id(record.memory_id, "memory_id")
        if memory_id in ids:
            raise ValueError("memory_id values must be unique")
        ids.add(memory_id)
        if not isinstance(record.content, Mapping):
            raise ValueError("memory content must be a mapping")
        content = dict(record.content)
        content_hash = _sha(content)
        provenance = tuple(sorted({_safe_id(item, "provenance_id") for item in record.provenance_ids}))
        if not provenance:
            raise ValueError("every memory record requires provenance")
        equivalence_key = str(record.equivalence_key or "").strip()
        if equivalence_key:
            _safe_id(equivalence_key, "equivalence_key")
        grouping_key = f"declared:{equivalence_key}" if equivalence_key else f"exact:{content_hash}"
        normalized.append((grouping_key, memory_id, content_hash, provenance, equivalence_key))

    groups: Dict[str, list[tuple[str, str, Tuple[str, ...], str]]] = {}
    for grouping_key, memory_id, content_hash, provenance, equivalence_key in normalized:
        groups.setdefault(grouping_key, []).append((memory_id, content_hash, provenance, equivalence_key))

    output = []
    for grouping_key, members in sorted(groups.items()):
        member_ids = tuple(sorted(row[0] for row in members))
        provenance = tuple(sorted({p for row in members for p in row[2]}))
        hashes = {row[1] for row in members}
        equivalence_key = members[0][3]
        exact = len(hashes) == 1
        # For declared-equivalence groups with differing content, derive a group
        # digest from all member content hashes; never pretend they are exact.
        content_hash = next(iter(hashes)) if exact else _sha(sorted(hashes))
        output.append(ConsolidationGroup(
            canonical_memory_id=member_ids[0],
            member_ids=member_ids,
            provenance_ids=provenance,
            content_hash=content_hash,
            equivalence_key=equivalence_key,
            exact_content_match=exact,
            destructive_merge_performed=False,
        ))
    return tuple(output)


@dataclass(frozen=True)
class FailureRecord:
    failure_id: str
    occurred_at: str
    mistake_class: str
    component: str
    symptom: str
    root_cause: str
    severity: float
    recurrence_key: str
    evidence_ids: Tuple[str, ...]
    remediation: str
    resolved: bool
    resolution: str
    event_hash: str


class FailureMemory:
    """Atomic persistent failure ledger with a hash-chained event history."""

    def __init__(self, directory: str, project_id: str = "default"):
        self.directory = os.path.abspath(directory)
        self.project_id = _safe_id(project_id, "project_id")
        self._data: Optional[Dict[str, Any]] = None

    @property
    def path(self) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", self.project_id)
        return os.path.join(self.directory, f"{safe}.failures.json")

    def _blank(self) -> Dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "project_id": self.project_id,
            "failures": {},
            "audit_chain": [],
        }

    def load(self) -> Dict[str, Any]:
        if self._data is not None:
            return self._data
        if not os.path.exists(self.path):
            self._data = self._blank()
            return self._data
        with open(self.path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or data.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("invalid failure memory schema")
        if data.get("project_id") != self.project_id:
            raise ValueError("failure memory project mismatch")
        if not isinstance(data.get("failures"), dict) or not isinstance(data.get("audit_chain"), list):
            raise ValueError("invalid failure memory structure")
        self._verify_chain(data["audit_chain"])
        self._data = data
        return data

    @staticmethod
    def _verify_chain(chain: Sequence[Mapping[str, Any]]) -> None:
        previous = "GENESIS"
        for index, event in enumerate(chain, 1):
            if not isinstance(event, Mapping) or event.get("previous_hash") != previous:
                raise ValueError(f"failure audit chain broken at event {index}")
            payload = {
                "sequence": event.get("sequence"),
                "kind": event.get("kind"),
                "failure_id": event.get("failure_id"),
                "details_hash": event.get("details_hash"),
                "previous_hash": event.get("previous_hash"),
            }
            expected = _sha(payload)
            if event.get("event_hash") != expected:
                raise ValueError(f"failure audit chain hash mismatch at event {index}")
            previous = expected

    def _append_event(self, kind: str, failure_id: str, details: Mapping[str, Any]) -> str:
        data = self.load()
        chain = data["audit_chain"]
        previous = chain[-1]["event_hash"] if chain else "GENESIS"
        payload = {
            "sequence": len(chain) + 1,
            "kind": str(kind),
            "failure_id": failure_id,
            "details_hash": _sha(dict(details)),
            "previous_hash": previous,
        }
        event_hash = _sha(payload)
        chain.append({**payload, "event_hash": event_hash})
        return event_hash

    def save(self) -> None:
        data = self.load()
        self._verify_chain(data["audit_chain"])
        os.makedirs(self.directory, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".failure_", suffix=".json", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.remove(temp)

    def record_failure(
        self,
        failure_id: str,
        *,
        occurred_at: str,
        mistake_class: str,
        component: str,
        symptom: str,
        root_cause: str,
        severity: float,
        recurrence_key: str,
        evidence_ids: Sequence[str],
        remediation: str,
    ) -> Dict[str, Any]:
        failure_id = _safe_id(failure_id, "failure_id")
        mistake = str(mistake_class or "").strip().upper()
        if mistake not in _ALLOWED_MISTAKES:
            raise ValueError("unsupported mistake_class")
        occurred = _timestamp_text(occurred_at, "occurred_at")
        component = _safe_id(component, "component")
        symptom = _text(symptom, "symptom")
        root_cause = _text(root_cause, "root_cause")
        severity = _probability(severity, "severity")
        recurrence_key = _safe_id(recurrence_key, "recurrence_key")
        remediation = _text(remediation, "remediation")
        evidence = tuple(sorted({_safe_id(item, "evidence_id") for item in evidence_ids}))
        if not evidence:
            raise ValueError("failure requires at least one evidence_id")
        store = self.load()["failures"]
        if failure_id in store:
            raise ValueError("failure_id already exists")
        record = {
            "failure_id": failure_id,
            "occurred_at": occurred,
            "mistake_class": mistake,
            "component": component,
            "symptom": symptom,
            "root_cause": root_cause,
            "severity": severity,
            "recurrence_key": recurrence_key,
            "evidence_ids": list(evidence),
            "remediation": remediation,
            "resolved": False,
            "resolution": "",
        }
        event_hash = self._append_event("failure_recorded", failure_id, record)
        record["event_hash"] = event_hash
        store[failure_id] = record
        return dict(record)

    def resolve_failure(
        self,
        failure_id: str,
        *,
        resolution: str,
        evidence_ids: Sequence[str],
    ) -> Dict[str, Any]:
        failure_id = _safe_id(failure_id, "failure_id")
        record = self.load()["failures"].get(failure_id)
        if not record:
            raise KeyError(failure_id)
        if record.get("resolved"):
            raise ValueError("failure is already resolved")
        resolution = _text(resolution, "resolution")
        evidence = tuple(sorted({_safe_id(item, "evidence_id") for item in evidence_ids}))
        if not evidence:
            raise ValueError("resolution requires evidence")
        details = {"resolution": resolution, "evidence_ids": list(evidence)}
        event_hash = self._append_event("failure_resolved", failure_id, details)
        record["resolved"] = True
        record["resolution"] = resolution
        record["resolution_evidence_ids"] = list(evidence)
        record["resolution_event_hash"] = event_hash
        return dict(record)

    def recurrence_report(self) -> Dict[str, Any]:
        groups: Dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        for record in self.load()["failures"].values():
            key = (record["mistake_class"], record["recurrence_key"])
            groups.setdefault(key, []).append(record)
        rows = []
        for (mistake, recurrence_key), records in sorted(groups.items()):
            rows.append({
                "mistake_class": mistake,
                "recurrence_key": recurrence_key,
                "count": len(records),
                "unresolved": sum(1 for row in records if not row.get("resolved")),
                "max_severity": max(float(row["severity"]) for row in records),
                "failure_ids": sorted(row["failure_id"] for row in records),
            })
        rows.sort(key=lambda row: (-row["count"], -row["max_severity"], row["recurrence_key"]))
        return {
            "total_failures": len(self.load()["failures"]),
            "distinct_patterns": len(rows),
            "patterns": rows,
            "taxonomy": sorted(_ALLOWED_MISTAKES),
        }

    def audit_integrity(self) -> Dict[str, Any]:
        chain = self.load()["audit_chain"]
        self._verify_chain(chain)
        return {
            "valid": True,
            "events": len(chain),
            "head_hash": chain[-1]["event_hash"] if chain else "GENESIS",
        }
