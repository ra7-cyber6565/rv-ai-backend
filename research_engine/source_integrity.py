"""Source-integrity, poisoning and independence-aware consensus foundation.

Implements conservative software foundations for blueprint #115 (Data Poisoning
Defense), #116 (Dynamic Source Trust), #117 (Fraud/Manipulation Detector) and
#118 (Consensus Is Not Proof).  Trust is updated only from explicit resolved
outcomes and is never treated as truth.  Repeated/syndicated evidence is grouped
before consensus is counted, and anomaly findings only quarantine for review;
they do not silently delete evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Sequence, Tuple


_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_MAX_SOURCES = 100_000
_MAX_EDGES = 500_000


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is empty or invalid")
    return text


def _text(value: object, field: str, max_len: int = 10_000) -> str:
    text = str(value or "").strip()
    if not text or len(text) > max_len:
        raise ValueError(f"{field} is empty or too long")
    return text


def _probability(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be finite and in [0,1]")
    return number


def _positive(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} must be finite and > 0")
    return number


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("source integrity payload must be finite JSON-compatible data") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class SourceObservation:
    source_id: str
    publisher_id: str
    independence_group: str
    content_hash: str
    published_at_epoch: float
    primary_source: bool = False
    provenance_complete: bool = True
    parent_source_ids: Tuple[str, ...] = ()
    claim_fingerprint: str = ""

    def normalized(self) -> "SourceObservation":
        content_hash = str(self.content_hash or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", content_hash):
            raise ValueError("content_hash must be a SHA-256 hex digest")
        try:
            published = float(self.published_at_epoch)
        except (TypeError, ValueError) as exc:
            raise ValueError("published_at_epoch must be numeric") from exc
        if not math.isfinite(published) or published <= 0:
            raise ValueError("published_at_epoch must be finite and > 0")
        parents = tuple(sorted({_safe_id(item, "parent_source_id") for item in self.parent_source_ids}))
        source_id = _safe_id(self.source_id, "source_id")
        if source_id in parents:
            raise ValueError("source cannot cite itself as parent")
        fingerprint = str(self.claim_fingerprint or "").strip()
        if fingerprint:
            fingerprint = _safe_id(fingerprint, "claim_fingerprint")
        return SourceObservation(
            source_id=source_id,
            publisher_id=_safe_id(self.publisher_id, "publisher_id"),
            independence_group=_safe_id(self.independence_group, "independence_group"),
            content_hash=content_hash,
            published_at_epoch=published,
            primary_source=bool(self.primary_source),
            provenance_complete=bool(self.provenance_complete),
            parent_source_ids=parents,
            claim_fingerprint=fingerprint,
        )


@dataclass(frozen=True)
class ResolvedSourceOutcome:
    source_id: str
    correct: bool
    weight: float = 1.0
    resolution_id: str = ""

    def normalized(self) -> "ResolvedSourceOutcome":
        return ResolvedSourceOutcome(
            source_id=_safe_id(self.source_id, "source_id"),
            correct=bool(self.correct),
            weight=_positive(self.weight, "weight"),
            resolution_id=_safe_id(self.resolution_id, "resolution_id"),
        )


@dataclass(frozen=True)
class SourceTrustState:
    source_id: str
    alpha: float
    beta: float
    posterior_mean: float
    resolved_weight: float
    trust_is_truth_probability: bool = False


@dataclass(frozen=True)
class IntegrityFinding:
    finding_id: str
    kind: str
    severity: str
    source_ids: Tuple[str, ...]
    explanation: str
    finding_hash: str
    fraud_proven: bool = False


@dataclass(frozen=True)
class SourceIntegrityReport:
    source_count: int
    unique_content_count: int
    independence_group_count: int
    effective_independent_support: int
    findings: Tuple[IntegrityFinding, ...]
    quarantine_candidates: Tuple[str, ...]
    report_hash: str
    consensus_proves_truth: bool = False
    fraud_proven: bool = False


class DynamicSourceTrust:
    """Beta-Bernoulli reliability memory with explicit resolved outcomes only."""

    def __init__(self, *, prior_alpha: float = 1.0, prior_beta: float = 1.0):
        self.prior_alpha = _positive(prior_alpha, "prior_alpha")
        self.prior_beta = _positive(prior_beta, "prior_beta")
        self._states: Dict[str, Tuple[float, float]] = {}
        self._resolution_ids: set[str] = set()

    def update(self, outcomes: Sequence[ResolvedSourceOutcome]) -> Tuple[SourceTrustState, ...]:
        if isinstance(outcomes, (str, bytes, bytearray)) or not isinstance(outcomes, Sequence):
            raise ValueError("outcomes must be a finite sequence")
        normalized = tuple(item.normalized() for item in outcomes)
        if len({item.resolution_id for item in normalized}) != len(normalized):
            raise ValueError("resolution_id values must be unique within update")
        if any(item.resolution_id in self._resolution_ids for item in normalized):
            raise ValueError("resolved source outcome already applied")
        for item in normalized:
            alpha, beta = self._states.get(item.source_id, (self.prior_alpha, self.prior_beta))
            if item.correct:
                alpha += item.weight
            else:
                beta += item.weight
            self._states[item.source_id] = (alpha, beta)
            self._resolution_ids.add(item.resolution_id)
        return tuple(self.state(source_id) for source_id in sorted({item.source_id for item in normalized}))

    def state(self, source_id: str) -> SourceTrustState:
        source_id = _safe_id(source_id, "source_id")
        alpha, beta = self._states.get(source_id, (self.prior_alpha, self.prior_beta))
        return SourceTrustState(
            source_id=source_id,
            alpha=alpha,
            beta=beta,
            posterior_mean=alpha / (alpha + beta),
            resolved_weight=(alpha + beta) - (self.prior_alpha + self.prior_beta),
            trust_is_truth_probability=False,
        )


def _finding(kind: str, severity: str, source_ids: Sequence[str], explanation: str) -> IntegrityFinding:
    ids = tuple(sorted({_safe_id(item, "source_id") for item in source_ids}))
    payload = {"kind": kind, "severity": severity, "source_ids": ids, "explanation": explanation}
    digest = _hash(payload)
    return IntegrityFinding(
        finding_id=f"{kind.lower()}-{digest[:16]}",
        kind=kind,
        severity=severity,
        source_ids=ids,
        explanation=explanation,
        finding_hash=digest,
        fraud_proven=False,
    )


def _detect_cycles(by_id: Mapping[str, SourceObservation]) -> Tuple[Tuple[str, ...], ...]:
    cycles: set[Tuple[str, ...]] = set()
    visiting: set[str] = set()
    visited: set[str] = set()
    path: list[str] = []

    def walk(node: str) -> None:
        if node in visiting:
            try:
                start = path.index(node)
            except ValueError:
                return
            cycle = tuple(path[start:] + [node])
            core = cycle[:-1]
            if core:
                rotations = [tuple(core[index:] + core[:index]) for index in range(len(core))]
                cycles.add(min(rotations))
            return
        if node in visited:
            return
        visiting.add(node)
        path.append(node)
        for parent in by_id[node].parent_source_ids:
            if parent in by_id:
                walk(parent)
        path.pop()
        visiting.remove(node)
        visited.add(node)

    for source_id in sorted(by_id):
        walk(source_id)
    return tuple(sorted(cycles))


def analyze_source_integrity(sources: Sequence[SourceObservation]) -> SourceIntegrityReport:
    if isinstance(sources, (str, bytes, bytearray)) or not isinstance(sources, Sequence):
        raise ValueError("sources must be a finite sequence")
    if not 1 <= len(sources) <= _MAX_SOURCES:
        raise ValueError(f"sources must contain 1..{_MAX_SOURCES} items")
    normalized = tuple(item.normalized() for item in sources)
    by_id = {item.source_id: item for item in normalized}
    if len(by_id) != len(normalized):
        raise ValueError("source_id values must be unique")
    edge_count = sum(len(item.parent_source_ids) for item in normalized)
    if edge_count > _MAX_EDGES:
        raise ValueError("source genealogy edge limit exceeded")

    findings = []
    quarantine: set[str] = set()

    # Missing provenance is a review signal, not automatic falsehood.
    missing_provenance = [item.source_id for item in normalized if not item.provenance_complete]
    if missing_provenance:
        findings.append(_finding(
            "MISSING_PROVENANCE",
            "MEDIUM",
            missing_provenance,
            "One or more sources lack complete declared provenance.",
        ))
        quarantine.update(missing_provenance)

    # Exact-content syndication must not masquerade as independent evidence.
    by_content: Dict[str, list[SourceObservation]] = {}
    for item in normalized:
        by_content.setdefault(item.content_hash, []).append(item)
    for rows in by_content.values():
        if len(rows) > 1:
            ids = [item.source_id for item in rows]
            groups = {item.independence_group for item in rows}
            severity = "HIGH" if len(groups) > 1 else "LOW"
            findings.append(_finding(
                "DUPLICATE_OR_SYNDICATED_CONTENT",
                severity,
                ids,
                "Exact content duplication is counted once for effective independence.",
            ))
            if severity == "HIGH":
                quarantine.update(ids)

    # Same claim fingerprint appearing under many nominal independence groups is
    # a coordination/poisoning signal, not proof of manipulation.
    by_claim: Dict[str, list[SourceObservation]] = {}
    for item in normalized:
        if item.claim_fingerprint:
            by_claim.setdefault(item.claim_fingerprint, []).append(item)
    for rows in by_claim.values():
        groups = {item.independence_group for item in rows}
        publishers = {item.publisher_id for item in rows}
        if len(rows) >= 3 and len(groups) >= 3 and len(publishers) < len(rows):
            ids = [item.source_id for item in rows]
            findings.append(_finding(
                "COORDINATED_CLAIM_PATTERN",
                "MEDIUM",
                ids,
                "Repeated claim fingerprint spans nominal independence groups with publisher overlap.",
            ))
            quarantine.update(ids)

    for cycle in _detect_cycles(by_id):
        findings.append(_finding(
            "CIRCULAR_SOURCE_GENEALOGY",
            "HIGH",
            cycle,
            "Sources form a circular genealogy and cannot independently validate one another.",
        ))
        quarantine.update(cycle)

    # Parent chronology: a child cannot derive from a parent published later,
    # barring bad metadata/versioning. Surface the inconsistency.
    for item in normalized:
        bad_parents = [
            parent for parent in item.parent_source_ids
            if parent in by_id and by_id[parent].published_at_epoch > item.published_at_epoch
        ]
        if bad_parents:
            ids = [item.source_id, *bad_parents]
            findings.append(_finding(
                "PROVENANCE_CHRONOLOGY_ANOMALY",
                "HIGH",
                ids,
                "Declared parent source is timestamped later than its child source.",
            ))
            quarantine.update(ids)

    # Effective independent support collapses exact copies first, then counts one
    # representative per independence group.
    representatives: Dict[str, set[str]] = {}
    for item in normalized:
        representatives.setdefault(item.independence_group, set()).add(item.content_hash)
    effective = len(representatives)

    ordered_findings = tuple(sorted(findings, key=lambda item: (item.kind, item.finding_id)))
    payload = {
        "sources": [
            {
                "source_id": item.source_id,
                "publisher_id": item.publisher_id,
                "independence_group": item.independence_group,
                "content_hash": item.content_hash,
                "published_at_epoch": item.published_at_epoch,
                "primary_source": item.primary_source,
                "provenance_complete": item.provenance_complete,
                "parent_source_ids": item.parent_source_ids,
                "claim_fingerprint": item.claim_fingerprint,
            }
            for item in sorted(normalized, key=lambda row: row.source_id)
        ],
        "findings": [item.finding_hash for item in ordered_findings],
        "quarantine_candidates": sorted(quarantine),
        "effective_independent_support": effective,
    }
    return SourceIntegrityReport(
        source_count=len(normalized),
        unique_content_count=len(by_content),
        independence_group_count=len(representatives),
        effective_independent_support=effective,
        findings=ordered_findings,
        quarantine_candidates=tuple(sorted(quarantine)),
        report_hash=_hash(payload),
        consensus_proves_truth=False,
        fraud_proven=False,
    )
