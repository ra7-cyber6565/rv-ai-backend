"""Compile the 142-capability registry against the committed proof policy.

This module answers a different question from the receipt auditor:

* receipt audit: which trusted proofs are active for this exact revision?
* policy coverage: could the trusted auditor accept every proof class the
  registry requires if legitimate evidence were produced?

A missing policy route is a first-class blocker.  Otherwise a capability can be
implemented and even have real evidence, while the trusted auditor has no
committed rule capable of accepting that evidence.

The compiler is deliberately fail-closed and purely diagnostic.  It never
creates proof receipts, never upgrades maturity, and never treats a mapped route
as evidence that the underlying capability works.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence, Tuple

from .capability_registry import CAPABILITIES, CAPABILITY_BY_ID, ProofKind
from .maturity_auditor import (
    ProofRule,
    RepositoryProofPolicy,
    _hash_tracked_regular,
    _parse_policy,
    _read_policy_bytes,
    _tracked_index,
)


_FILE_PROOFS = {ProofKind.CODE, ProofKind.TEST}
_EXTERNAL_PROOFS = {
    ProofKind.EXECUTION,
    ProofKind.INDEPENDENT,
    ProofKind.PERSISTENCE,
    ProofKind.RUNTIME,
    ProofKind.LIVE,
    ProofKind.HARDWARE,
    ProofKind.SAFETY,
    ProofKind.REPRODUCIBILITY,
}


@dataclass(frozen=True)
class PolicyCoverageGap:
    capability_id: int
    capability_name: str
    proof_kind: ProofKind
    category: str


@dataclass(frozen=True)
class InvalidPolicySubject:
    capability_id: int
    proof_kind: ProofKind
    subject: str
    reason: str


@dataclass(frozen=True)
class PolicyCoverageReport:
    capabilities_checked: int
    required_routes: int
    mapped_routes: int
    gaps: Tuple[PolicyCoverageGap, ...]
    invalid_file_subjects: Tuple[InvalidPolicySubject, ...]

    @property
    def complete(self) -> bool:
        return not self.gaps and not self.invalid_file_subjects

    @property
    def file_proof_gaps(self) -> Tuple[PolicyCoverageGap, ...]:
        return tuple(gap for gap in self.gaps if gap.proof_kind in _FILE_PROOFS)

    @property
    def wiring_gaps(self) -> Tuple[PolicyCoverageGap, ...]:
        return tuple(gap for gap in self.gaps if gap.proof_kind is ProofKind.WIRING)

    @property
    def external_route_gaps(self) -> Tuple[PolicyCoverageGap, ...]:
        return tuple(gap for gap in self.gaps if gap.proof_kind in _EXTERNAL_PROOFS)

    @property
    def blocking_capability_ids(self) -> Tuple[int, ...]:
        return tuple(sorted({gap.capability_id for gap in self.gaps} | {
            item.capability_id for item in self.invalid_file_subjects
        }))

    def to_dict(self) -> dict:
        return {
            "capabilities_checked": self.capabilities_checked,
            "required_routes": self.required_routes,
            "mapped_routes": self.mapped_routes,
            "complete": self.complete,
            "blocking_capability_ids": list(self.blocking_capability_ids),
            "gaps": [
                {
                    "capability_id": gap.capability_id,
                    "capability_name": gap.capability_name,
                    "proof_kind": gap.proof_kind.value,
                    "category": gap.category,
                }
                for gap in self.gaps
            ],
            "invalid_file_subjects": [
                {
                    "capability_id": item.capability_id,
                    "proof_kind": item.proof_kind.value,
                    "subject": item.subject,
                    "reason": item.reason,
                }
                for item in self.invalid_file_subjects
            ],
        }


def _category(kind: ProofKind) -> str:
    if kind in _FILE_PROOFS:
        return "file_proof_route_missing"
    if kind is ProofKind.WIRING:
        return "production_wiring_route_missing"
    return "external_attestation_route_missing"


def _selected_capabilities(capability_ids: Sequence[int] | None):
    if capability_ids is None:
        return CAPABILITIES
    ids = tuple(capability_ids)
    if not ids:
        raise ValueError("capability_ids must not be empty")
    if len(set(ids)) != len(ids):
        raise ValueError("capability_ids must be unique")
    unknown = [item for item in ids if type(item) is not int or item not in CAPABILITY_BY_ID]
    if unknown:
        raise ValueError("capability_ids contains an unknown capability")
    return tuple(CAPABILITY_BY_ID[item] for item in ids)


def compile_policy_coverage(
    policy: RepositoryProofPolicy,
    *,
    capability_ids: Sequence[int] | None = None,
) -> PolicyCoverageReport:
    """Report every required proof class with no committed acceptance rule."""
    capabilities = _selected_capabilities(capability_ids)
    mapped = {(rule.capability_id, rule.proof_kind) for rule in policy.rules}
    required_routes = 0
    mapped_routes = 0
    gaps = []
    for capability in capabilities:
        for kind in capability.required_proofs:
            required_routes += 1
            if (capability.id, kind) in mapped:
                mapped_routes += 1
                continue
            gaps.append(PolicyCoverageGap(
                capability_id=capability.id,
                capability_name=capability.name,
                proof_kind=kind,
                category=_category(kind),
            ))
    return PolicyCoverageReport(
        capabilities_checked=len(capabilities),
        required_routes=required_routes,
        mapped_routes=mapped_routes,
        gaps=tuple(gaps),
        invalid_file_subjects=(),
    )


def audit_repository_policy_coverage(
    repo_root: str | Path,
    *,
    policy_path: str = "config/maturity_proof_policy.json",
    capability_ids: Sequence[int] | None = None,
) -> PolicyCoverageReport:
    """Compile policy and verify every CODE/TEST subject is tracked + hashable."""
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    tracked = _tracked_index(root)
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    base = compile_policy_coverage(policy, capability_ids=capability_ids)
    selected = {item.id for item in _selected_capabilities(capability_ids)}

    invalid = []
    for rule in policy.rules:
        if rule.capability_id not in selected or rule.proof_kind not in _FILE_PROOFS:
            continue
        for subject in rule.subjects:
            try:
                _hash_tracked_regular(root, tracked, subject)
            except ValueError as exc:
                invalid.append(InvalidPolicySubject(
                    capability_id=rule.capability_id,
                    proof_kind=rule.proof_kind,
                    subject=subject,
                    reason=str(exc),
                ))

    return PolicyCoverageReport(
        capabilities_checked=base.capabilities_checked,
        required_routes=base.required_routes,
        mapped_routes=base.mapped_routes,
        gaps=base.gaps,
        invalid_file_subjects=tuple(invalid),
    )


def load_policy_coverage(
    policy_bytes: bytes,
    *,
    capability_ids: Sequence[int] | None = None,
) -> PolicyCoverageReport:
    """Parse canonical policy bytes with the same strict parser as the auditor."""
    return compile_policy_coverage(
        _parse_policy(policy_bytes),
        capability_ids=capability_ids,
    )
