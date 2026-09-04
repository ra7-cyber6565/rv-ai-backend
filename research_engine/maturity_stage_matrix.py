"""Strict A-F maturity matrix for the 142-capability research architecture.

The matrix is deliberately downstream of :mod:`maturity_auditor`.  It never
accepts caller-supplied revisions, file hashes or self-asserted proof labels.
The trusted maturity audit first derives a clean Git HEAD, validates the keyed
proof ledger and external anchor, applies committed proof policy, and rejects
stale/unapproved receipts.  Only that accepted proof state is grouped into the
user-facing A-F stages here.

Stage scores are proof-completion scores, not truth/safety/profitability or
real-world success probabilities.  A proof kind that a capability does not
semantically require is reported ``NOT_REQUIRED`` rather than fabricated.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Mapping, Tuple

from utils.release_identity import repository_identity

from .capability_registry import CAPABILITIES, ProofKind
from .maturity_auditor import (
    _REGULAR_GIT_MODES,
    _safe_repo_path,
    _tracked_index,
    audit_repository_maturity,
)

_STAGE_POLICY_SCHEMA = 1
_MAX_STAGE_POLICY_BYTES = 128 * 1024
_STAGE_IDS = ("A", "B", "C", "D", "E", "F")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class StageSpec:
    stage_id: str
    name: str
    proof_kinds: Tuple[ProofKind, ...]


@dataclass(frozen=True)
class StagePolicy:
    stages: Tuple[StageSpec, ...]
    final_stage: str
    sha256: str


@dataclass(frozen=True)
class CapabilityStageState:
    capability_id: int
    capability_name: str
    stage_id: str
    stage_name: str
    local_status: str
    cumulative_status: str
    applicable_proofs: Tuple[str, ...]
    local_missing_proofs: Tuple[str, ...]
    cumulative_missing_proofs: Tuple[str, ...]


@dataclass(frozen=True)
class StageSummary:
    stage_id: str
    name: str
    verified_capabilities: int
    total_capabilities: int
    proof_completion_score: float
    all_capabilities_max: bool
    blocking_capability_ids: Tuple[int, ...]


@dataclass(frozen=True)
class MaturityStageMatrix:
    revision: str
    audit_valid: bool
    cryptographic_integrity: bool
    stage_policy_sha256: str
    maturity_audit_sha256: str
    stages: Tuple[StageSummary, ...]
    capability_states: Tuple[CapabilityStageState, ...]
    final_verified: int
    total_capabilities: int
    final_score: float
    all_142_verified: bool
    matrix_sha256: str

    def stage(self, stage_id: str) -> StageSummary:
        key = str(stage_id or "").strip().upper()
        for item in self.stages:
            if item.stage_id == key:
                return item
        raise KeyError(key)

    def capability(self, capability_id: int) -> Tuple[CapabilityStageState, ...]:
        return tuple(
            item for item in self.capability_states
            if item.capability_id == capability_id
        )


def _read_stage_policy(
    root: Path,
    tracked: Mapping[str, str],
    path: str,
) -> bytes:
    canonical = _safe_repo_path(path, field="stage_policy_path")
    if tracked.get(canonical) not in _REGULAR_GIT_MODES:
        raise ValueError("stage policy must be a tracked regular file")
    target = root.joinpath(*PurePosixPath(canonical).parts)
    root_resolved = root.resolve(strict=True)
    try:
        info = target.lstat()
        resolved = target.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("stage policy escapes or cannot be resolved") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError("stage policy must not be a symlink")
    if info.st_size < 1 or info.st_size > _MAX_STAGE_POLICY_BYTES:
        raise ValueError("stage policy size is invalid")
    payload = target.read_bytes()
    if len(payload) != info.st_size or len(payload) > _MAX_STAGE_POLICY_BYTES:
        raise ValueError("stage policy changed during read")
    return payload


def parse_stage_policy(payload: bytes) -> StagePolicy:
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("stage policy is not valid UTF-8 JSON") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version", "stages", "final_stage"
    }:
        raise ValueError("stage policy top-level schema is invalid")
    if raw.get("schema_version") != _STAGE_POLICY_SCHEMA:
        raise ValueError("unsupported stage policy schema_version")
    if raw.get("final_stage") != "F":
        raise ValueError("stage policy final_stage must be F")
    stages_raw = raw.get("stages")
    if not isinstance(stages_raw, list) or len(stages_raw) != len(_STAGE_IDS):
        raise ValueError("stage policy must define exactly A-F")

    stages = []
    seen_proofs: Dict[ProofKind, str] = {}
    for expected_id, item in zip(_STAGE_IDS, stages_raw):
        if not isinstance(item, dict) or set(item) != {"id", "name", "proof_kinds"}:
            raise ValueError(f"stage {expected_id} schema is invalid")
        stage_id = str(item.get("id") or "")
        name = str(item.get("name") or "").strip()
        values = item.get("proof_kinds")
        if stage_id != expected_id or not name or len(name) > 160:
            raise ValueError(f"stage {expected_id} identity is invalid")
        if not isinstance(values, list) or len(values) > len(ProofKind):
            raise ValueError(f"stage {expected_id} proof_kinds are invalid")
        kinds = []
        for value in values:
            try:
                kind = ProofKind(value)
            except ValueError as exc:
                raise ValueError(
                    f"stage {expected_id} contains unknown proof kind"
                ) from exc
            if kind in kinds:
                raise ValueError(f"stage {expected_id} contains duplicate proof kind")
            if stage_id == "F":
                raise ValueError("stage F must not directly own proof kinds")
            prior = seen_proofs.get(kind)
            if prior is not None:
                raise ValueError(
                    f"proof kind {kind.value} is assigned to both {prior} and {stage_id}"
                )
            seen_proofs[kind] = stage_id
            kinds.append(kind)
        stages.append(StageSpec(stage_id=stage_id, name=name, proof_kinds=tuple(kinds)))

    if stages[-1].proof_kinds:
        raise ValueError("stage F must not directly own proof kinds")
    missing = set(ProofKind) - set(seen_proofs)
    extra = set(seen_proofs) - set(ProofKind)
    if missing or extra:
        labels = sorted(kind.value for kind in missing)
        raise ValueError(f"stages A-E must partition every proof kind; missing={labels}")

    return StagePolicy(
        stages=tuple(stages),
        final_stage="F",
        sha256=_sha(_canonical(raw)),
    )


def _build_matrix(audit, policy: StagePolicy) -> MaturityStageMatrix:
    if len(CAPABILITIES) != 142 or tuple(item.id for item in CAPABILITIES) != tuple(range(1, 143)):
        raise ValueError("capability registry is not exactly contiguous 1..142")
    if len(audit.maturity_report.results) != 142:
        raise ValueError("trusted maturity audit does not contain exactly 142 results")

    audit_valid = bool(audit.audit_valid)
    states = []
    summaries = []
    cumulative_stage_proofs: set[ProofKind] = set()
    report_by_id = {item.capability_id: item for item in audit.maturity_report.results}

    for stage in policy.stages:
        if stage.stage_id != "F":
            cumulative_stage_proofs.update(stage.proof_kinds)
        verified_ids = []
        blockers = []

        for spec in CAPABILITIES:
            result = report_by_id.get(spec.id)
            if result is None:
                raise ValueError(f"trusted maturity audit is missing capability {spec.id}")
            required = set(spec.required_proofs)
            missing = set(result.missing_proofs)

            if stage.stage_id == "F":
                applicable = tuple(sorted(required, key=lambda value: value.value))
                local_missing = tuple(sorted(missing, key=lambda value: value.value))
                cumulative_missing = local_missing
                local_ok = audit_valid and result.status == "VERIFIED" and not local_missing
                local_status = "VERIFIED" if local_ok else (
                    "AUDIT_INVALID" if not audit_valid else "INCOMPLETE"
                )
                cumulative_status = local_status
            else:
                applicable_set = required.intersection(stage.proof_kinds)
                cumulative_required = required.intersection(cumulative_stage_proofs)
                local_missing_set = missing.intersection(applicable_set)
                cumulative_missing_set = missing.intersection(cumulative_required)
                applicable = tuple(sorted(applicable_set, key=lambda value: value.value))
                local_missing = tuple(sorted(local_missing_set, key=lambda value: value.value))
                cumulative_missing = tuple(
                    sorted(cumulative_missing_set, key=lambda value: value.value)
                )
                if not audit_valid:
                    local_status = "AUDIT_INVALID"
                    cumulative_status = "AUDIT_INVALID"
                else:
                    local_status = (
                        "NOT_REQUIRED" if not applicable
                        else "VERIFIED" if not local_missing
                        else "INCOMPLETE"
                    )
                    cumulative_status = (
                        "VERIFIED" if not cumulative_missing else "INCOMPLETE"
                    )

            state = CapabilityStageState(
                capability_id=spec.id,
                capability_name=spec.name,
                stage_id=stage.stage_id,
                stage_name=stage.name,
                local_status=local_status,
                cumulative_status=cumulative_status,
                applicable_proofs=tuple(value.value for value in applicable),
                local_missing_proofs=tuple(value.value for value in local_missing),
                cumulative_missing_proofs=tuple(value.value for value in cumulative_missing),
            )
            states.append(state)
            if cumulative_status == "VERIFIED":
                verified_ids.append(spec.id)
            else:
                blockers.append(spec.id)

        total = len(CAPABILITIES)
        score = round((len(verified_ids) / total) * 100.0, 2) if total else 0.0
        summaries.append(StageSummary(
            stage_id=stage.stage_id,
            name=stage.name,
            verified_capabilities=len(verified_ids),
            total_capabilities=total,
            proof_completion_score=score,
            all_capabilities_max=(len(verified_ids) == total),
            blocking_capability_ids=tuple(blockers),
        ))

    final = summaries[-1]
    all_verified = (
        audit_valid
        and bool(audit.max_level_eligible)
        and final.verified_capabilities == 142
        and final.all_capabilities_max
    )
    if all_verified != bool(audit.max_level_eligible):
        raise ValueError("stage F disagrees with the trusted maturity auditor")

    payload = {
        "revision": audit.revision,
        "audit_valid": audit_valid,
        "cryptographic_integrity": bool(audit.cryptographic_integrity),
        "stage_policy_sha256": policy.sha256,
        "maturity_audit_sha256": audit.audit_sha256,
        "stages": [
            {
                "id": item.stage_id,
                "verified": item.verified_capabilities,
                "total": item.total_capabilities,
                "score": item.proof_completion_score,
                "all_max": item.all_capabilities_max,
                "blockers": list(item.blocking_capability_ids),
            }
            for item in summaries
        ],
        "final_verified": final.verified_capabilities,
        "total_capabilities": final.total_capabilities,
        "final_score": final.proof_completion_score,
        "all_142_verified": all_verified,
    }
    return MaturityStageMatrix(
        revision=audit.revision,
        audit_valid=audit_valid,
        cryptographic_integrity=bool(audit.cryptographic_integrity),
        stage_policy_sha256=policy.sha256,
        maturity_audit_sha256=audit.audit_sha256,
        stages=tuple(summaries),
        capability_states=tuple(states),
        final_verified=final.verified_capabilities,
        total_capabilities=final.total_capabilities,
        final_score=final.proof_completion_score,
        all_142_verified=all_verified,
        matrix_sha256=_sha(_canonical(payload)),
    )


def audit_repository_stage_matrix(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    anchor_token: str,
    now: float,
    proof_policy_path: str = "config/maturity_proof_policy.json",
    stage_policy_path: str = "config/maturity_stage_policy.json",
) -> MaturityStageMatrix:
    """Run the cryptographically anchored maturity audit and derive A-F stages."""
    root = Path(repo_root).resolve(strict=True)
    audit = audit_repository_maturity(
        repo_root=root,
        ledger_path=ledger_path,
        integrity_key=integrity_key,
        anchor_token=anchor_token,
        now=now,
        policy_path=proof_policy_path,
    )
    tracked = _tracked_index(root)
    policy_bytes = _read_stage_policy(root, tracked, stage_policy_path)
    policy = parse_stage_policy(policy_bytes)
    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != audit.revision
    ):
        raise ValueError("repository changed during stage-matrix audit")
    return _build_matrix(audit, policy)
