"""Role-separated maturity attestation for capability #89 Champion-Challenger.

The existing :mod:`scientific_memory` implementation is authoritative.  This
module adds narrow proof routes without duplicating the lifecycle engine:

* EXECUTION: a fixed champion/challenger promotion benchmark executes.
* REPRODUCIBILITY: independent benchmark runs reproduce the same logical result.
* PERSISTENCE: state is atomically saved, reloaded and its audit chain/tamper
  rejection are exercised outside the audited repository.
* RUNTIME/LIVE: a protected external observer must HMAC-sign a fresh receipt
  binding the exact clean Git revision, persisted ScientificMemory state, a
  concrete champion->challenger promotion, distinct implementations/holdouts,
  precommitted objective improvement, live data sources and observation window.

Offline tests can therefore never manufacture runtime/live maturity evidence.
None of these receipts prove scientific truth, universal superiority, or that a
promotion will remain superior under future distribution shift.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

from utils.release_identity import repository_identity

from . import scientific_memory as sm
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


_CAPABILITY_ID = 89
_ENGINE_SUBJECT = "research_engine/scientific_memory.py"
_SCHEMA_VERSION = 1
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024
_MAX_AGE_SECONDS = 2 * 60 * 60
_MAX_FUTURE_SKEW_SECONDS = 5 * 60
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_GIT40 = re.compile(r"^[0-9a-f]{40}$")
_ID = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")

_ROUTE = {
    ProofKind.EXECUTION: (
        "capability-89-execution-run",
        "trusted-execution-attestor",
        "execution:c89:",
    ),
    ProofKind.REPRODUCIBILITY: (
        "capability-89-reproducibility-run",
        "trusted-reproducibility-attestor",
        "reproducibility:c89:",
    ),
    ProofKind.PERSISTENCE: (
        "capability-89-persistence-observation",
        "trusted-persistence-attestor",
        "persistence:c89:",
    ),
    ProofKind.RUNTIME: (
        "capability-89-runtime-observation",
        "trusted-runtime-attestor",
        "runtime:c89:",
    ),
    ProofKind.LIVE: (
        "capability-89-live-observation",
        "trusted-live-observer",
        "live:c89:",
    ),
}
_EXPIRING = {ProofKind.RUNTIME, ProofKind.LIVE}


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("champion-challenger evidence must be finite JSON") from exc


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _finite(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _prepare_repo(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
):
    root = Path(repo_root).resolve(strict=True)
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")
    identity = repository_identity(root)
    revision = str(identity.get("revision") or "")
    if not identity.get("available") or not identity.get("clean") or not revision:
        raise ValueError("champion-challenger attestation requires a clean Git checkout")
    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _ENGINE_SUBJECT)
    imported = Path(str(sm.__file__)).resolve(strict=True)
    expected = (root / _ENGINE_SUBJECT).resolve(strict=True)
    if imported != expected:
        raise ValueError("ScientificMemory runtime is not loaded from audited repository")
    return root, ledger_target, revision, tracked, engine_digest


def _policy_allows(policy, *, kind: ProofKind, reference: str) -> None:
    subject, verifier, prefix = _ROUTE[kind]
    matching = tuple(
        rule for rule in policy.rules
        if rule.capability_id == _CAPABILITY_ID
        and rule.proof_kind is kind
        and subject in rule.subjects
        and verifier in rule.verifiers
    )
    if not matching:
        raise ValueError(f"committed proof policy has no capability-89 {kind.value} route")
    if not reference.startswith(prefix):
        raise ValueError(f"{kind.value} reference is not capability-bound")
    if not any(
        not rule.reference_prefixes
        or any(reference.startswith(item) for item in rule.reference_prefixes)
        for rule in matching
    ):
        raise ValueError(f"{kind.value} reference is not allowed by proof policy")


def _continuity(
    *,
    ledger_target: Path,
    integrity_key: bytes,
    prior_anchor_token: str,
    prior_revision: str,
) -> None:
    exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or not prior:
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not ledger.verify_chain(anchor_token=prior_anchor_token, current_revision=prior):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")


def _model_view(record: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "model_id": record.get("model_id"),
        "metrics": dict(record.get("metrics") or {}),
        "holdout_id": record.get("holdout_id"),
        "implementation_hash": record.get("implementation_hash"),
        "independent_validation_ids": list(record.get("independent_validation_ids") or []),
        "status": record.get("status"),
        "rejection_reasons": list(record.get("rejection_reasons") or []),
    }


def run_champion_challenger_benchmark(storage_root: str | os.PathLike[str]) -> Mapping[str, Any]:
    """Exercise promotion/rejection/persistence without claiming live operation."""
    root = Path(storage_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="champion-challenger-", dir=str(root)))
    try:
        memory = sm.ScientificMemory("benchmark", directory=str(work))
        memory.register_model(
            "champion-v1",
            metrics={"quality": 0.80, "loss": 0.20},
            holdout_id="holdout-a",
            implementation_hash="impl-a",
            independent_validation_ids=("validation-a",),
            status="champion",
        )
        memory.register_model(
            "challenger-v2",
            metrics={"quality": 0.86, "loss": 0.14},
            holdout_id="holdout-b",
            implementation_hash="impl-b",
            independent_validation_ids=("validation-b",),
            status="challenger",
        )
        promoted = memory.promote_challenger(
            "champion-v1",
            "challenger-v2",
            objectives={"quality": "max", "loss": "min"},
            require_independent_validation=True,
            require_distinct_holdout=True,
        )
        memory.register_model(
            "challenger-unvalidated",
            metrics={"quality": 0.99, "loss": 0.01},
            holdout_id="holdout-c",
            implementation_hash="impl-c",
            independent_validation_ids=(),
            status="challenger",
        )
        blocked_unvalidated = memory.promote_challenger(
            "challenger-v2",
            "challenger-unvalidated",
            objectives={"quality": "max", "loss": "min"},
            require_independent_validation=True,
            require_distinct_holdout=True,
        )
        memory.register_model(
            "challenger-worse",
            metrics={"quality": 0.82, "loss": 0.18},
            holdout_id="holdout-d",
            implementation_hash="impl-d",
            independent_validation_ids=("validation-d",),
            status="challenger",
        )
        blocked_worse = memory.promote_challenger(
            "challenger-v2",
            "challenger-worse",
            objectives={"quality": "max", "loss": "min"},
            require_independent_validation=True,
            require_distinct_holdout=True,
        )
        memory.reject_model("challenger-worse", reasons=("objective regression",))
        memory.save()

        reloaded = sm.ScientificMemory("benchmark", directory=str(work))
        data = reloaded.load()
        integrity = reloaded.audit_integrity()
        models = data["models"]

        # Mutate a copy of the persistent file; the canonical state remains intact.
        canonical_path = Path(reloaded.path)
        raw = json.loads(canonical_path.read_text(encoding="utf-8"))
        tamper_rejected = False
        if raw.get("audit_chain"):
            tampered = dict(raw)
            tampered["audit_chain"] = [dict(item) for item in raw["audit_chain"]]
            tampered["audit_chain"][0]["event_hash"] = "0" * 64
            tamper_dir = work / "tamper"
            tamper_dir.mkdir()
            tamper_path = tamper_dir / "benchmark.scientific.json"
            tamper_path.write_text(json.dumps(tampered), encoding="utf-8")
            try:
                sm.ScientificMemory("benchmark", directory=str(tamper_dir)).load()
            except ValueError:
                tamper_rejected = True

        logical = {
            "promoted": promoted.promoted,
            "promoted_reasons": list(promoted.reasons),
            "unvalidated_promoted": blocked_unvalidated.promoted,
            "unvalidated_reasons": list(blocked_unvalidated.reasons),
            "worse_promoted": blocked_worse.promoted,
            "worse_reasons": list(blocked_worse.reasons),
            "models": {
                model_id: _model_view(models[model_id])
                for model_id in sorted(models)
            },
        }
        checks = {
            "better_challenger_promoted": promoted.promoted is True,
            "old_champion_retired": models["champion-v1"]["status"] == "retired",
            "new_champion_persisted": models["challenger-v2"]["status"] == "champion",
            "unvalidated_blocked": (
                blocked_unvalidated.promoted is False
                and "challenger has no independent validation" in blocked_unvalidated.reasons
            ),
            "worse_blocked": (
                blocked_worse.promoted is False
                and any("did not improve" in reason for reason in blocked_worse.reasons)
            ),
            "rejected_model_preserved": models["challenger-worse"]["status"] == "rejected",
            "persistence_reload_integrity": integrity["valid"] is True,
            "audit_chain_has_lifecycle_events": int(integrity["events"]) >= 8,
            "tamper_rejected_on_reload": tamper_rejected,
            "distinct_implementation_and_holdout": (
                models["champion-v1"]["implementation_hash"]
                != models["challenger-v2"]["implementation_hash"]
                and models["champion-v1"]["holdout_id"]
                != models["challenger-v2"]["holdout_id"]
            ),
        }
        payload = {
            "benchmark_version": "champion-challenger-v1",
            "checks": checks,
            "logical": logical,
            "truth_proven": False,
            "live_operation_proven": False,
            "future_superiority_proven": False,
        }
        return {
            **payload,
            "benchmark_passed": all(checks.values()),
            "logical_sha256": _sha(logical),
            "benchmark_sha256": _sha(payload),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


@dataclass(frozen=True)
class ChampionChallengerAttestation:
    revision: str
    engine_sha256: str
    proof_kind: str
    evidence_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    truth_proven: bool = False
    future_superiority_proven: bool = False
    cross_machine_durability_proven: bool = False


def _same(
    row: Mapping[str, Any],
    *,
    kind: ProofKind,
    digest: str,
    reference: str,
    revision: str,
    valid_until: Optional[float],
) -> bool:
    subject, verifier, _prefix = _ROUTE[kind]
    expected = {
        "capability_id": _CAPABILITY_ID,
        "proof_kind": kind.value,
        "subject": subject,
        "subject_sha256": digest,
        "verifier": verifier,
        "reference": reference,
        "implementation_revision": revision,
        "valid_until": valid_until,
    }
    return all(row.get(key) == value for key, value in expected.items())


def _mint(
    *,
    root: Path,
    ledger_target: Path,
    integrity_key: bytes,
    revision: str,
    engine_digest: str,
    kind: ProofKind,
    evidence_digest: str,
    reference: str,
    current_time: float,
    policy_path: str,
    valid_until: Optional[float] = None,
) -> ChampionChallengerAttestation:
    subject, verifier, _prefix = _ROUTE[kind]
    receipt_digest = _sha({
        "revision": revision,
        "engine_sha256": engine_digest,
        "evidence_sha256": evidence_digest,
        "proof_kind": kind.value,
        "capability_id": _CAPABILITY_ID,
    })
    bucket = f":{int(valid_until or 0)}" if valid_until is not None else ""
    receipt_id = f"champion:{revision[:12]}:{kind.value}:{evidence_digest[:12]}{bucket}"
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    previous = existing.get(receipt_id)
    added = reused = 0
    if previous is not None:
        if not _same(
            previous,
            kind=kind,
            digest=receipt_digest,
            reference=reference,
            revision=revision,
            valid_until=valid_until,
        ):
            raise ValueError("deterministic champion-challenger receipt_id collision")
        reused = 1
    else:
        ledger.add(
            receipt_id=receipt_id,
            capability_id=_CAPABILITY_ID,
            proof_kind=kind,
            subject=subject,
            subject_sha256=receipt_digest,
            verifier=verifier,
            observed_at=current_time,
            valid_until=valid_until,
            reference=reference,
            implementation_revision=revision,
        )
        added = 1
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
        raise ValueError("trusted maturity audit rejected champion-challenger attestation")
    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during champion-challenger attestation")
    return ChampionChallengerAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        proof_kind=kind.value,
        evidence_sha256=evidence_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )


def attest_champion_challenger_software(
    *,
    repo_root: str | os.PathLike[str],
    storage_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    proof_kind: ProofKind,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> ChampionChallengerAttestation:
    """Mint exactly one EXECUTION, REPRODUCIBILITY or PERSISTENCE proof."""
    if proof_kind not in {
        ProofKind.EXECUTION,
        ProofKind.REPRODUCIBILITY,
        ProofKind.PERSISTENCE,
    }:
        raise ValueError("software attestor only accepts execution/reproducibility/persistence")
    current_time = _finite(now, "now")
    reference = _safe_reference(run_reference)
    root, ledger_target, revision, tracked, engine_digest = _prepare_repo(
        repo_root=repo_root, ledger_path=ledger_path
    )
    storage = Path(storage_root).expanduser().resolve()
    if not _outside_repo(root, storage):
        raise ValueError("storage_root must live outside the audited repository")
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    _policy_allows(policy, kind=proof_kind, reference=reference)
    _continuity(
        ledger_target=ledger_target,
        integrity_key=integrity_key,
        prior_anchor_token=prior_anchor_token,
        prior_revision=prior_revision,
    )

    first = run_champion_challenger_benchmark(storage)
    second = run_champion_challenger_benchmark(storage)
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("champion-challenger benchmark failed")
    if first.get("logical_sha256") != second.get("logical_sha256"):
        raise ValueError("champion-challenger logical benchmark is not reproducible")
    if first.get("checks") != second.get("checks"):
        raise ValueError("champion-challenger benchmark checks are not reproducible")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    if not _SHA64.fullmatch(benchmark_digest):
        raise ValueError("champion-challenger benchmark digest is invalid")
    return _mint(
        root=root,
        ledger_target=ledger_target,
        integrity_key=integrity_key,
        revision=revision,
        engine_digest=engine_digest,
        kind=proof_kind,
        evidence_digest=benchmark_digest,
        reference=reference,
        current_time=current_time,
        policy_path=policy_path,
    )


def _read_json(path: Path, label: str) -> tuple[Mapping[str, Any], bytes]:
    try:
        stat = path.stat()
    except OSError as exc:
        raise ValueError(f"{label} cannot be read") from exc
    if not path.is_file() or not 1 <= stat.st_size <= _MAX_RECEIPT_BYTES:
        raise ValueError(f"{label} size is invalid")
    raw = path.read_bytes()
    if len(raw) != stat.st_size:
        raise ValueError(f"{label} changed during read")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value, raw


def _strict_ids(value: object, field: str, *, minimum: int) -> Tuple[str, ...]:
    if not isinstance(value, list) or not minimum <= len(value) <= 10_000:
        raise ValueError(f"{field} must be a bounded list")
    rows = tuple(_safe_id(item, field) for item in value)
    if len(set(rows)) != len(rows):
        raise ValueError(f"{field} values must be distinct")
    return rows


def _objectives(value: object) -> Mapping[str, str]:
    if not isinstance(value, dict) or not 1 <= len(value) <= 32:
        raise ValueError("objectives must be a bounded mapping")
    out = {}
    for metric, direction in value.items():
        metric_id = _safe_id(metric, "objective metric")
        direction_text = str(direction or "").strip().lower()
        if direction_text not in {"max", "min"}:
            raise ValueError("objective direction must be max/min")
        out[metric_id] = direction_text
    return out


@dataclass(frozen=True)
class ValidatedChampionChallengerLiveReceipt:
    revision: str
    created_at_epoch: int
    project_id: str
    prior_champion_id: str
    promoted_challenger_id: str
    deployment_id: str
    runtime_instance_id: str
    observer_id: str
    state_sha256: str
    audit_head_hash: str
    objectives: Mapping[str, str]
    live_data_source_ids: Tuple[str, ...]
    evaluation_ids: Tuple[str, ...]
    receipt_sha256: str


def validate_champion_challenger_live_receipt(
    *,
    memory_state_path: str | os.PathLike[str],
    observer_receipt_path: str | os.PathLike[str],
    observer_key: bytes,
    expected_revision: str,
    now: float,
) -> ValidatedChampionChallengerLiveReceipt:
    if not isinstance(observer_key, (bytes, bytearray)) or len(observer_key) < 32:
        raise ValueError("observer_key must contain at least 32 bytes")
    current_time = _finite(now, "now")
    revision = str(expected_revision or "").strip().lower()
    if not _GIT40.fullmatch(revision):
        raise ValueError("expected_revision must be a full lowercase Git SHA")
    receipt, receipt_bytes = _read_json(
        Path(observer_receipt_path).expanduser().resolve(),
        "champion-challenger live receipt",
    )
    expected_keys = {
        "schema_version",
        "created_at_epoch",
        "implementation_revision",
        "project_id",
        "prior_champion_id",
        "promoted_challenger_id",
        "deployment_id",
        "runtime_instance_id",
        "observer_id",
        "state_sha256",
        "audit_head_hash",
        "objectives",
        "observation_window_start_epoch",
        "observation_window_end_epoch",
        "live_data_source_ids",
        "evaluation_ids",
        "champion_challenger_comparison_observed",
        "promotion_decision_observed",
        "persistent_state_reloaded",
        "runtime_observation_complete",
        "live_observation_complete",
        "automatic_ungated_promotion_observed",
        "truth_proven",
        "signature",
    }
    if set(receipt) != expected_keys:
        raise ValueError("champion-challenger live receipt schema is invalid")
    if receipt.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported champion-challenger live schema_version")
    created = receipt.get("created_at_epoch")
    if type(created) is not int or created <= 0:
        raise ValueError("live receipt created_at_epoch is invalid")
    if created > current_time + _MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("champion-challenger live receipt is from the future")
    if current_time - created >= _MAX_AGE_SECONDS:
        raise ValueError("champion-challenger live receipt is stale")
    if str(receipt.get("implementation_revision") or "").strip().lower() != revision:
        raise ValueError("live receipt revision does not match current Git HEAD")

    project_id = _safe_id(receipt.get("project_id"), "project_id")
    prior_champion_id = _safe_id(receipt.get("prior_champion_id"), "prior_champion_id")
    promoted_challenger_id = _safe_id(receipt.get("promoted_challenger_id"), "promoted_challenger_id")
    if prior_champion_id == promoted_challenger_id:
        raise ValueError("champion and challenger must be distinct")
    deployment_id = _safe_id(receipt.get("deployment_id"), "deployment_id")
    runtime_instance_id = _safe_id(receipt.get("runtime_instance_id"), "runtime_instance_id")
    observer_id = _safe_id(receipt.get("observer_id"), "observer_id")
    objectives = _objectives(receipt.get("objectives"))
    live_sources = _strict_ids(receipt.get("live_data_source_ids"), "live_data_source_ids", minimum=1)
    evaluation_ids = _strict_ids(receipt.get("evaluation_ids"), "evaluation_ids", minimum=2)
    window_start = _finite(receipt.get("observation_window_start_epoch"), "observation_window_start_epoch")
    window_end = _finite(receipt.get("observation_window_end_epoch"), "observation_window_end_epoch")
    if window_start <= 0 or window_end <= window_start or window_end > created:
        raise ValueError("champion-challenger observation window is invalid")
    for field in (
        "champion_challenger_comparison_observed",
        "promotion_decision_observed",
        "persistent_state_reloaded",
        "runtime_observation_complete",
        "live_observation_complete",
    ):
        if receipt.get(field) is not True:
            raise ValueError(f"live receipt requires {field}=true")
    if receipt.get("automatic_ungated_promotion_observed") is not False:
        raise ValueError("ungated automatic promotion cannot support maturity proof")
    if receipt.get("truth_proven") is not False:
        raise ValueError("live receipt must not claim truth_proven")

    state_path = Path(memory_state_path).expanduser().resolve(strict=True)
    if not state_path.is_file() or state_path.stat().st_size > _MAX_RECEIPT_BYTES:
        raise ValueError("ScientificMemory state file is invalid")
    state_raw = state_path.read_bytes()
    state_sha = hashlib.sha256(state_raw).hexdigest()
    if str(receipt.get("state_sha256") or "").strip().lower() != state_sha:
        raise ValueError("live receipt does not bind exact ScientificMemory state")
    memory = sm.ScientificMemory(project_id, directory=str(state_path.parent))
    if Path(memory.path).resolve() != state_path:
        raise ValueError("memory_state_path does not match project_id")
    state = memory.load()
    integrity = memory.audit_integrity()
    if str(receipt.get("audit_head_hash") or "").strip().lower() != str(integrity["head_hash"]):
        raise ValueError("live receipt audit head does not match ScientificMemory state")
    models = state.get("models") or {}
    champion = models.get(prior_champion_id)
    challenger = models.get(promoted_challenger_id)
    if not isinstance(champion, Mapping) or not isinstance(challenger, Mapping):
        raise ValueError("live receipt model IDs are absent from ScientificMemory state")
    if champion.get("status") != "retired" or challenger.get("status") != "champion":
        raise ValueError("persisted model lifecycle does not show challenger promotion")
    if champion.get("implementation_hash") == challenger.get("implementation_hash"):
        raise ValueError("live champion/challenger implementations must be distinct")
    if champion.get("holdout_id") == challenger.get("holdout_id"):
        raise ValueError("live champion/challenger holdouts must be distinct")
    if not challenger.get("independent_validation_ids"):
        raise ValueError("live challenger lacks independent validation metadata")
    for metric, direction in objectives.items():
        if metric not in champion.get("metrics", {}) or metric not in challenger.get("metrics", {}):
            raise ValueError(f"objective metric is absent from persisted models: {metric}")
        old = _finite(champion["metrics"][metric], metric)
        new = _finite(challenger["metrics"][metric], metric)
        if direction == "max" and not new > old:
            raise ValueError(f"live challenger did not improve objective: {metric}")
        if direction == "min" and not new < old:
            raise ValueError(f"live challenger did not improve objective: {metric}")

    signature = str(receipt.get("signature") or "").strip().lower()
    if not _SHA64.fullmatch(signature):
        raise ValueError("live receipt signature is invalid")
    unsigned = dict(receipt)
    unsigned.pop("signature", None)
    expected_signature = hmac.new(bytes(observer_key), _canonical(unsigned), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("live receipt signature verification failed")

    return ValidatedChampionChallengerLiveReceipt(
        revision=revision,
        created_at_epoch=created,
        project_id=project_id,
        prior_champion_id=prior_champion_id,
        promoted_challenger_id=promoted_challenger_id,
        deployment_id=deployment_id,
        runtime_instance_id=runtime_instance_id,
        observer_id=observer_id,
        state_sha256=state_sha,
        audit_head_hash=str(integrity["head_hash"]),
        objectives=objectives,
        live_data_source_ids=live_sources,
        evaluation_ids=evaluation_ids,
        receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
    )


def attest_champion_challenger_live(
    *,
    repo_root: str | os.PathLike[str],
    memory_state_path: str | os.PathLike[str],
    observer_receipt_path: str | os.PathLike[str],
    observer_key: bytes,
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    proof_kind: ProofKind,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> ChampionChallengerAttestation:
    """Mint exactly one short-lived RUNTIME or LIVE proof from signed evidence."""
    if proof_kind not in {ProofKind.RUNTIME, ProofKind.LIVE}:
        raise ValueError("live attestor only accepts runtime/live")
    current_time = _finite(now, "now")
    reference = _safe_reference(run_reference)
    root, ledger_target, revision, tracked, engine_digest = _prepare_repo(
        repo_root=repo_root, ledger_path=ledger_path
    )
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    _policy_allows(policy, kind=proof_kind, reference=reference)
    _continuity(
        ledger_target=ledger_target,
        integrity_key=integrity_key,
        prior_anchor_token=prior_anchor_token,
        prior_revision=prior_revision,
    )
    receipt = validate_champion_challenger_live_receipt(
        memory_state_path=memory_state_path,
        observer_receipt_path=observer_receipt_path,
        observer_key=observer_key,
        expected_revision=revision,
        now=current_time,
    )
    valid_until = float(receipt.created_at_epoch + _MAX_AGE_SECONDS)
    return _mint(
        root=root,
        ledger_target=ledger_target,
        integrity_key=integrity_key,
        revision=revision,
        engine_digest=engine_digest,
        kind=proof_kind,
        evidence_digest=receipt.receipt_sha256,
        reference=reference,
        current_time=current_time,
        policy_path=policy_path,
        valid_until=valid_until,
    )
