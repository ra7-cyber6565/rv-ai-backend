"""Trusted persistence/runtime attestation for memory-governance capabilities.

Capabilities covered:
* #49 Knowledge Decay -> PERSISTENCE + RUNTIME
* #53 Memory Consolidation -> PERSISTENCE
* #55 Failure Memory -> PERSISTENCE
* #56 Mistake Taxonomy -> PERSISTENCE

The attestor binds to an exact clean Git revision, verifies the imported module
is the tracked file, executes a real out-of-repo write/fsync/reload/tamper-check
benchmark, recomputes deterministic decay/consolidation outputs, checks the
committed proof policy, and mints only the explicitly required proof classes.
Runtime evidence is deliberately short-lived and refreshable; persistence
receipts remain stable.  It does not claim LIVE evidence, scientific truth, or
cross-machine durability.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from utils.release_identity import repository_identity

from . import memory_governance as mg
from .capability_registry import ProofKind
from .maturity_attestor import _existing_adds, _outside_repo, _safe_reference
from .maturity_auditor import (
    TrustedMaturityAudit,
    _hash_tracked_regular,
    _parse_policy,
    _read_policy_bytes,
    _tracked_index,
    audit_repository_maturity,
)
from .maturity_proof import ProofLedger


_MODEL_SUBJECT = "research_engine/memory_governance.py"
_VERIFIER = "trusted-operator"
_SUBJECT = "memory-governance-runtime"
_RUNTIME_PROOF_TTL_SECONDS = 3600.0
_REQUIRED: Mapping[int, Tuple[ProofKind, ...]] = {
    49: (ProofKind.PERSISTENCE, ProofKind.RUNTIME),
    53: (ProofKind.PERSISTENCE,),
    55: (ProofKind.PERSISTENCE,),
    56: (ProofKind.PERSISTENCE,),
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _runtime_bucket(now: float) -> int:
    return int(math.floor(now / _RUNTIME_PROOF_TTL_SECONDS))


def _runtime_valid_until(now: float) -> float:
    """Return the exclusive end of the current runtime-proof time bucket."""
    return float((_runtime_bucket(now) + 1) * _RUNTIME_PROOF_TTL_SECONDS)


def run_memory_governance_benchmark(storage_root: str | os.PathLike[str]) -> Mapping[str, Any]:
    root = Path(storage_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="memory-governance-", dir=str(root)))
    try:
        decay_a = mg.assess_knowledge_decay(
            memory_id="benchmark-memory",
            confidence=0.8,
            last_verified_at="2026-01-01T00:00:00+00:00",
            now="2026-01-31T00:00:00+00:00",
            policy=mg.DecayPolicy(half_life_days=30, stale_after_days=20),
        )
        decay_b = mg.assess_knowledge_decay(
            memory_id="benchmark-memory",
            confidence=0.8,
            last_verified_at="2026-01-01T00:00:00+00:00",
            now="2026-01-31T00:00:00+00:00",
            policy=mg.DecayPolicy(half_life_days=30, stale_after_days=20),
        )
        consolidation_a = mg.consolidate_memories((
            mg.MemoryRecord("m1", {"claim": "A", "value": 1}, ("src1",)),
            mg.MemoryRecord("m2", {"value": 1, "claim": "A"}, ("src2",)),
        ))
        consolidation_b = mg.consolidate_memories((
            mg.MemoryRecord("m1", {"claim": "A", "value": 1}, ("src1",)),
            mg.MemoryRecord("m2", {"value": 1, "claim": "A"}, ("src2",)),
        ))

        store = mg.FailureMemory(str(work), project_id="benchmark")
        store.record_failure(
            "failure-1",
            occurred_at="2026-08-30T00:00:00+00:00",
            mistake_class="IMPLEMENTATION_BUG",
            component="benchmark",
            symptom="deterministic fixture failure",
            root_cause="fixture root cause",
            severity=0.8,
            recurrence_key="fixture-pattern",
            evidence_ids=("log-1",),
            remediation="apply fixture remediation",
        )
        store.save()
        first_integrity = store.audit_integrity()
        loaded = mg.FailureMemory(str(work), project_id="benchmark")
        reload_integrity = loaded.audit_integrity()
        loaded.resolve_failure(
            "failure-1",
            resolution="fixture remediation verified",
            evidence_ids=("test-1",),
        )
        loaded.save()
        final = mg.FailureMemory(str(work), project_id="benchmark")
        final_integrity = final.audit_integrity()
        recurrence = final.recurrence_report()

        # Tamper a copy, never the canonical benchmark state. Reload must reject.
        tampered_path = work / "tampered.failures.json"
        payload = json.loads(Path(final.path).read_text(encoding="utf-8"))
        payload["audit_chain"][0]["details_hash"] = "0" * 64
        tampered_path.write_text(json.dumps(payload), encoding="utf-8")
        canonical = Path(final.path)
        backup = work / "canonical.backup"
        canonical.replace(backup)
        tampered_path.replace(canonical)
        tamper_rejected = False
        try:
            mg.FailureMemory(str(work), project_id="benchmark").load()
        except ValueError:
            tamper_rejected = True
        finally:
            canonical.unlink(missing_ok=True)
            backup.replace(canonical)

        checks = {
            "decay_deterministic": asdict(decay_a) == asdict(decay_b),
            "decay_only_lowers": decay_a.usable_confidence_ceiling <= decay_a.original_confidence,
            "decay_stale_requires_revalidation": decay_a.stale and decay_a.revalidation_required,
            "consolidation_deterministic": [asdict(x) for x in consolidation_a] == [asdict(x) for x in consolidation_b],
            "consolidation_non_destructive": all(not x.destructive_merge_performed for x in consolidation_a),
            "provenance_preserved": consolidation_a[0].provenance_ids == ("src1", "src2"),
            "initial_persistence_integrity": first_integrity["valid"] is True,
            "reload_persistence_integrity": reload_integrity["valid"] is True,
            "resolution_persisted": final.load()["failures"]["failure-1"]["resolved"] is True,
            "final_audit_integrity": final_integrity["valid"] is True and final_integrity["events"] == 2,
            "taxonomy_present": "IMPLEMENTATION_BUG" in recurrence["taxonomy"],
            "recurrence_persisted": recurrence["total_failures"] == 1,
            "tamper_rejected_on_reload": tamper_rejected,
        }
        payload = {
            "benchmark_version": "memory-governance-runtime-v1",
            "checks": checks,
            "decay_hash": decay_a.assessment_hash,
            "consolidation": [asdict(x) for x in consolidation_a],
            "audit_head": final_integrity["head_hash"],
        }
        return {
            **payload,
            "benchmark_passed": all(checks.values()),
            "benchmark_sha256": _sha(payload),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


@dataclass(frozen=True)
class MemoryGovernanceAttestation:
    revision: str
    engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    live_proven: bool = False
    cross_machine_durability_proven: bool = False
    truth_proven: bool = False


def _same_receipt(
    row: Mapping[str, Any],
    *,
    capability_id: int,
    kind: ProofKind,
    digest: str,
    reference: str,
    revision: str,
    valid_until: Optional[float],
) -> bool:
    expected = {
        "capability_id": capability_id,
        "proof_kind": kind.value,
        "subject": _SUBJECT,
        "subject_sha256": digest,
        "verifier": _VERIFIER,
        "reference": reference,
        "implementation_revision": revision,
        "valid_until": valid_until,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_memory_governance(
    *,
    repo_root: str | os.PathLike[str],
    storage_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> MemoryGovernanceAttestation:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    reference = _safe_reference(run_reference)
    root = Path(repo_root).resolve(strict=True)
    storage = Path(storage_root).expanduser().resolve()
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, storage):
        raise ValueError("storage_root must live outside the audited repository")
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "")
    if not identity_before.get("available") or not identity_before.get("clean") or not revision:
        raise ValueError("memory governance attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _MODEL_SUBJECT)
    imported_engine = Path(str(mg.__file__)).resolve(strict=True)
    audited_engine = (root / _MODEL_SUBJECT).resolve(strict=True)
    if imported_engine != audited_engine:
        raise ValueError("memory governance runtime is not loaded from audited repository")

    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    for capability_id, kinds in _REQUIRED.items():
        for kind in kinds:
            matching = tuple(
                rule for rule in policy.rules
                if rule.capability_id == capability_id
                and rule.proof_kind is kind
                and _SUBJECT in rule.subjects
                and _VERIFIER in rule.verifiers
            )
            if not matching:
                raise ValueError(f"committed proof policy has no trusted capability {capability_id} {kind.value} rule")
            if not any(
                not rule.reference_prefixes
                or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
                for rule in matching
            ):
                raise ValueError("run_reference is not allowed by memory governance proof policy")

    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or not prior:
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not continuity.verify_chain(anchor_token=prior_anchor_token, current_revision=prior):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    first = run_memory_governance_benchmark(storage)
    second = run_memory_governance_benchmark(storage)
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("memory governance runtime benchmark failed")
    # Audit-head hashes differ because they are content-derived from identical
    # logical events and omit wall-clock time, therefore exact canonical equality
    # is expected and is a reproducibility sanity check even though REPRO proof is
    # not required by these registry capabilities.
    if _canonical(first) != _canonical(second):
        raise ValueError("memory governance runtime benchmark is not deterministic")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    if len(benchmark_digest) != 64:
        raise ValueError("memory governance benchmark digest is invalid")

    receipt_digest = _sha({
        "revision": revision,
        "engine_sha256": engine_digest,
        "benchmark_sha256": benchmark_digest,
        "subject": _SUBJECT,
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0
    runtime_bucket = _runtime_bucket(current_time)
    runtime_expiry = _runtime_valid_until(current_time)
    for capability_id, kinds in _REQUIRED.items():
        for kind in kinds:
            valid_until = runtime_expiry if kind is ProofKind.RUNTIME else None
            bucket_suffix = f":b{runtime_bucket}" if kind is ProofKind.RUNTIME else ""
            receipt_id = (
                f"memory:{revision[:12]}:c{capability_id}:{kind.value}{bucket_suffix}"
            )
            previous = existing.get(receipt_id)
            if previous is not None:
                if not _same_receipt(
                    previous,
                    capability_id=capability_id,
                    kind=kind,
                    digest=receipt_digest,
                    reference=reference,
                    revision=revision,
                    valid_until=valid_until,
                ):
                    raise ValueError("deterministic memory governance receipt_id collision")
                reused += 1
                continue
            ledger.add(
                receipt_id=receipt_id,
                capability_id=capability_id,
                proof_kind=kind,
                subject=_SUBJECT,
                subject_sha256=receipt_digest,
                verifier=_VERIFIER,
                observed_at=current_time,
                valid_until=valid_until,
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
        raise ValueError("trusted maturity audit rejected memory governance attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during memory governance attestation")

    return MemoryGovernanceAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        benchmark_sha256=benchmark_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
