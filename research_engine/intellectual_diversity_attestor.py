"""External independence attestor for #16 Agent Society and #17 Intellectual Diversity.

This module deliberately separates *software execution* from *external independence*.
The existing ScientistSociety can count runner/model/perspective identities, but a
unit test cannot prove that real providers, operators or implementation lineages
are independent.  A trusted external observer therefore has to execute the same
bounded task with actual configured runners and explicitly attest an independence
boundary for each runner.

The receipt requires at least three successful agents with distinct runner ids,
model families, perspectives, roles and observer-attested independence domains.
It also requires more than one evidence portfolio so decorative role labels alone
cannot satisfy the diversity gate.  Repeated runs must preserve the frozen agent
manifest and all structural diversity constraints, but they are not required to
produce identical prose.

The attestor mints only ``independent_validation`` for capabilities 16 and 17.
It never mints execution/reproducibility/live/hardware/safety evidence, and neither
agreement nor diversity is treated as proof that an answer is true.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from utils.release_identity import repository_identity

from .capability_registry import ProofKind
from .maturity_attestor import _existing_adds, _outside_repo
from .maturity_auditor import (
    TrustedMaturityAudit,
    _hash_tracked_regular,
    _parse_policy,
    _read_policy_bytes,
    _tracked_index,
    audit_repository_maturity,
)
from .maturity_proof import ProofLedger
from .scientist_society import AgentSpec, ResearchTask, Runner, ScientistSociety


_CAPABILITY_IDS = (16, 17)
_PROOF_KIND = ProofKind.INDEPENDENT
_SCHEMA_VERSION = 1
_IMPLEMENTATION_SUBJECT = "research_engine/scientist_society.py"
_SUBJECT = "scientist-society-independent-validation"
_VERIFIER = "trusted-independent-validator"
_REFERENCE_PREFIX = "scientist-society-independent:"
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024
_MAX_TASK_BYTES = 512 * 1024
_MAX_RECEIPT_AGE_SECONDS = 2 * 60 * 60
_MAX_FUTURE_SKEW_SECONDS = 5 * 60
_MIN_AGENTS = 3
_MAX_AGENTS = 16
_MIN_RUNS = 2
_MAX_RUNS = 5
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")


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
        raise ValueError("intellectual-diversity receipt data must be strict JSON") from exc


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha(value: Any) -> str:
    return _sha_bytes(_canonical(value))


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_ID_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _safe_sha(value: object, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"{field} must be a SHA-256 hex digest")
    return text


def _task_commitment(task: ResearchTask) -> str:
    if not isinstance(task, ResearchTask) or not str(task.question).strip():
        raise ValueError("a non-empty ResearchTask is required")
    payload = {
        "question": str(task.question),
        "evidence": [dict(item) for item in tuple(task.evidence)],
        "hypothesis": task.hypothesis,
        "expected_result": task.expected_result,
        "constraints": dict(task.constraints),
    }
    encoded = _canonical(payload)
    if len(encoded) > _MAX_TASK_BYTES:
        raise ValueError("intellectual-diversity task exceeds bounded JSON size")
    return _sha_bytes(encoded)


def _manifest(
    agents: Sequence[Tuple[AgentSpec, Runner]],
    independence_domains: Mapping[str, str],
) -> Tuple[Dict[str, str], ...]:
    if (
        isinstance(agents, (str, bytes, bytearray))
        or not isinstance(agents, Sequence)
        or not _MIN_AGENTS <= len(agents) <= _MAX_AGENTS
    ):
        raise ValueError("intellectual diversity requires 3..16 agents")
    if not isinstance(independence_domains, Mapping):
        raise ValueError("independence_domains must be a mapping")

    rows = []
    seen_agents = set()
    seen_runners = set()
    for index, pair in enumerate(agents):
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise ValueError(f"agent binding {index} is invalid")
        spec, runner = pair
        if not isinstance(spec, AgentSpec) or not callable(runner):
            raise ValueError(f"agent binding {index} is invalid")
        agent_id = _safe_id(spec.agent_id, "agent_id")
        runner_id = _safe_id(spec.runner_id, "runner_id")
        if agent_id in seen_agents or runner_id in seen_runners:
            raise ValueError("agent_id and runner_id values must be distinct")
        seen_agents.add(agent_id)
        seen_runners.add(runner_id)
        domain = _safe_id(independence_domains.get(runner_id), "independence_domain")
        rows.append({
            "agent_id": agent_id,
            "runner_id": runner_id,
            "role": _safe_id(spec.role, "role"),
            "model_family": _safe_id(spec.model_family, "model_family"),
            "perspective": _safe_id(spec.perspective, "perspective"),
            "independence_domain": domain,
        })

    expected_runner_keys = {row["runner_id"] for row in rows}
    provided_runner_keys = {str(key).strip() for key in independence_domains}
    if provided_runner_keys != expected_runner_keys:
        raise ValueError("independence_domains must match runner ids exactly")
    for field in ("role", "model_family", "perspective", "independence_domain"):
        if len({row[field] for row in rows}) < _MIN_AGENTS:
            raise ValueError(f"intellectual diversity requires at least three distinct {field} values")
    rows.sort(key=lambda row: row["agent_id"])
    return tuple(rows)


def build_intellectual_diversity_execution_receipt(
    *,
    repo_root: str | os.PathLike[str],
    task: ResearchTask,
    agents: Sequence[Tuple[AgentSpec, Runner]],
    independence_domains: Mapping[str, str],
    created_at_epoch: int,
    repetitions: int = 2,
) -> Dict[str, Any]:
    """Run actual externally configured agents and build a privacy-bounded receipt."""
    if type(created_at_epoch) is not int or created_at_epoch <= 0:
        raise ValueError("created_at_epoch must be a positive integer")
    if type(repetitions) is not int or not _MIN_RUNS <= repetitions <= _MAX_RUNS:
        raise ValueError("repetitions must be between 2 and 5")

    root = Path(repo_root).resolve(strict=True)
    identity = repository_identity(root)
    revision = str(identity.get("revision") or "").strip().lower()
    if not identity.get("available") or not identity.get("clean") or len(revision) != 40:
        raise ValueError("intellectual-diversity execution requires a clean Git checkout")
    tracked = _tracked_index(root)
    implementation_sha256 = _hash_tracked_regular(root, tracked, _IMPLEMENTATION_SUBJECT)
    manifest = _manifest(agents, independence_domains)
    manifest_hash = _sha(list(manifest))
    task_hash = _task_commitment(task)

    run_rows = []
    for run_index in range(repetitions):
        society = ScientistSociety(
            agents,
            minimum_independent_runners=_MIN_AGENTS,
            max_workers=min(len(agents), _MAX_AGENTS),
        )
        result = society.run(task)
        if result.successful_agents != len(agents):
            raise ValueError("intellectual-diversity run contains failed agents")
        if result.distinct_runner_ids < _MIN_AGENTS:
            raise ValueError("intellectual-diversity run lacks distinct runners")
        if result.distinct_model_families < _MIN_AGENTS:
            raise ValueError("intellectual-diversity run lacks distinct model families")
        if result.distinct_perspectives < _MIN_AGENTS:
            raise ValueError("intellectual-diversity run lacks distinct perspectives")

        outputs = {item.agent_id: item for item in result.outputs}
        agent_rows = []
        evidence_sets = set()
        for manifest_row in manifest:
            output = outputs.get(manifest_row["agent_id"])
            if output is None or output.error or not output.answer:
                raise ValueError("intellectual-diversity output is missing or failed")
            if output.runner_id != manifest_row["runner_id"]:
                raise ValueError("runner identity changed during intellectual-diversity run")
            if output.model_family != manifest_row["model_family"]:
                raise ValueError("model family changed during intellectual-diversity run")
            if output.perspective != manifest_row["perspective"]:
                raise ValueError("perspective changed during intellectual-diversity run")
            if not output.evidence_ids:
                raise ValueError("every intellectual-diversity output must cite evidence ids")
            evidence_hash = _sha(list(output.evidence_ids))
            evidence_sets.add(evidence_hash)
            agent_rows.append({
                **manifest_row,
                "output_hash": _safe_sha(output.output_hash, "output_hash"),
                "evidence_set_hash": evidence_hash,
                "evidence_count": len(output.evidence_ids),
                "success": True,
            })
        if len(evidence_sets) < 2:
            raise ValueError("intellectual diversity requires at least two evidence portfolios")
        agent_rows.sort(key=lambda row: row["agent_id"])
        payload = {
            "run_id": f"run-{run_index + 1}",
            "task_commitment": task_hash,
            "agent_manifest_hash": manifest_hash,
            "agents": agent_rows,
        }
        run_rows.append({**payload, "run_hash": _sha(payload)})

    report = {
        "schema_version": _SCHEMA_VERSION,
        "created_at_epoch": created_at_epoch,
        "implementation_revision": revision,
        "implementation_subject": _IMPLEMENTATION_SUBJECT,
        "implementation_sha256": implementation_sha256,
        "task_commitment": task_hash,
        "agent_manifest": list(manifest),
        "agent_manifest_hash": manifest_hash,
        "runs": run_rows,
        "external_independence_structure_satisfied": True,
        "observer_asserted_independence_domains": True,
        "hidden_provider_dependencies_ruled_out": False,
        "agreement_proves_truth": False,
        "truth_proven": False,
    }
    report["report_hash"] = _sha(report)
    if len(_canonical(report)) > _MAX_RECEIPT_BYTES:
        raise ValueError("intellectual-diversity receipt exceeds size limit")
    return report


@dataclass(frozen=True)
class DiversityExecutionReceipt:
    revision: str
    created_at_epoch: int
    sha256: str
    report_hash: str
    task_commitment: str
    manifest_hash: str
    run_count: int


@dataclass(frozen=True)
class DiversityProofAttestation:
    revision: str
    execution_receipt_sha256: str
    report_hash: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit


def _read_json(path: Path) -> tuple[Mapping[str, Any], bytes]:
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError("intellectual-diversity receipt cannot be read") from exc
    if not path.is_file() or info.st_size < 1 or info.st_size > _MAX_RECEIPT_BYTES:
        raise ValueError("intellectual-diversity receipt size is invalid")
    data = path.read_bytes()
    if len(data) != info.st_size:
        raise ValueError("intellectual-diversity receipt changed during read")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("intellectual-diversity receipt is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("intellectual-diversity receipt must be a JSON object")
    return value, data


def validate_intellectual_diversity_receipt(
    path: str | os.PathLike[str],
    *,
    repo_root: str | os.PathLike[str],
    now: float,
) -> DiversityExecutionReceipt:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    root = Path(repo_root).resolve(strict=True)
    identity = repository_identity(root)
    revision = str(identity.get("revision") or "").strip().lower()
    if not identity.get("available") or not identity.get("clean") or len(revision) != 40:
        raise ValueError("intellectual-diversity validation requires a clean Git checkout")

    value, raw = _read_json(Path(path).expanduser().resolve())
    required = {
        "schema_version", "created_at_epoch", "implementation_revision",
        "implementation_subject", "implementation_sha256", "task_commitment",
        "agent_manifest", "agent_manifest_hash", "runs",
        "external_independence_structure_satisfied",
        "observer_asserted_independence_domains",
        "hidden_provider_dependencies_ruled_out", "agreement_proves_truth",
        "truth_proven", "report_hash",
    }
    if set(value) != required or value.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("intellectual-diversity receipt schema is invalid")
    created = value.get("created_at_epoch")
    if type(created) is not int or created <= 0:
        raise ValueError("created_at_epoch is invalid")
    age = current_time - float(created)
    if age > _MAX_RECEIPT_AGE_SECONDS:
        raise ValueError("intellectual-diversity receipt is stale")
    if age < -_MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("intellectual-diversity receipt is from the future")
    if str(value.get("implementation_revision") or "").lower() != revision:
        raise ValueError("intellectual-diversity receipt revision mismatch")
    if value.get("implementation_subject") != _IMPLEMENTATION_SUBJECT:
        raise ValueError("intellectual-diversity implementation subject mismatch")
    tracked = _tracked_index(root)
    actual_sha = _hash_tracked_regular(root, tracked, _IMPLEMENTATION_SUBJECT)
    if _safe_sha(value.get("implementation_sha256"), "implementation_sha256") != actual_sha:
        raise ValueError("intellectual-diversity implementation hash mismatch")
    task_hash = _safe_sha(value.get("task_commitment"), "task_commitment")

    manifest_raw = value.get("agent_manifest")
    if not isinstance(manifest_raw, list) or not _MIN_AGENTS <= len(manifest_raw) <= _MAX_AGENTS:
        raise ValueError("intellectual-diversity agent manifest size is invalid")
    manifest = []
    for row in manifest_raw:
        if not isinstance(row, dict) or set(row) != {
            "agent_id", "runner_id", "role", "model_family", "perspective", "independence_domain"
        }:
            raise ValueError("intellectual-diversity agent manifest row is invalid")
        manifest.append({key: _safe_id(row[key], key) for key in row})
    for field in ("agent_id", "runner_id", "role", "model_family", "perspective", "independence_domain"):
        values = [row[field] for row in manifest]
        if len(set(values)) < _MIN_AGENTS:
            raise ValueError(f"intellectual-diversity manifest lacks distinct {field} values")
    manifest.sort(key=lambda row: row["agent_id"])
    manifest_hash = _safe_sha(value.get("agent_manifest_hash"), "agent_manifest_hash")
    if _sha(manifest) != manifest_hash:
        raise ValueError("intellectual-diversity manifest hash mismatch")

    runs = value.get("runs")
    if not isinstance(runs, list) or not _MIN_RUNS <= len(runs) <= _MAX_RUNS:
        raise ValueError("intellectual-diversity run count is invalid")
    expected_ids = [row["agent_id"] for row in manifest]
    run_ids = set()
    for run in runs:
        if not isinstance(run, dict) or set(run) != {
            "run_id", "task_commitment", "agent_manifest_hash", "agents", "run_hash"
        }:
            raise ValueError("intellectual-diversity run schema is invalid")
        run_id = _safe_id(run.get("run_id"), "run_id")
        if run_id in run_ids:
            raise ValueError("intellectual-diversity run ids must be unique")
        run_ids.add(run_id)
        if run.get("task_commitment") != task_hash or run.get("agent_manifest_hash") != manifest_hash:
            raise ValueError("intellectual-diversity frozen protocol changed between runs")
        rows = run.get("agents")
        if not isinstance(rows, list) or len(rows) != len(manifest):
            raise ValueError("intellectual-diversity run agent set is invalid")
        normalized = []
        evidence_sets = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "agent_id", "runner_id", "role", "model_family", "perspective",
                "independence_domain", "output_hash", "evidence_set_hash",
                "evidence_count", "success",
            }:
                raise ValueError("intellectual-diversity run agent row is invalid")
            identity_row = {
                key: _safe_id(row[key], key)
                for key in ("agent_id", "runner_id", "role", "model_family", "perspective", "independence_domain")
            }
            if row.get("success") is not True:
                raise ValueError("intellectual-diversity run contains failed output")
            _safe_sha(row.get("output_hash"), "output_hash")
            evidence_hash = _safe_sha(row.get("evidence_set_hash"), "evidence_set_hash")
            evidence_count = row.get("evidence_count")
            if type(evidence_count) is not int or evidence_count < 1:
                raise ValueError("intellectual-diversity evidence_count is invalid")
            evidence_sets.add(evidence_hash)
            normalized.append(identity_row)
        normalized.sort(key=lambda row: row["agent_id"])
        if [row["agent_id"] for row in normalized] != expected_ids or normalized != manifest:
            raise ValueError("intellectual-diversity agent identity changed between runs")
        if len(evidence_sets) < 2:
            raise ValueError("intellectual-diversity run lacks evidence portfolio diversity")
        payload = {key: run[key] for key in run if key != "run_hash"}
        if _safe_sha(run.get("run_hash"), "run_hash") != _sha(payload):
            raise ValueError("intellectual-diversity run hash mismatch")

    if value.get("external_independence_structure_satisfied") is not True:
        raise ValueError("external independence structure is not satisfied")
    if value.get("observer_asserted_independence_domains") is not True:
        raise ValueError("independence domains were not attested by observer")
    if value.get("hidden_provider_dependencies_ruled_out") is not False:
        raise ValueError("receipt must not claim hidden dependencies were ruled out")
    if value.get("agreement_proves_truth") is not False or value.get("truth_proven") is not False:
        raise ValueError("intellectual diversity must not claim scientific truth")

    report_hash = _safe_sha(value.get("report_hash"), "report_hash")
    body = {key: item for key, item in value.items() if key != "report_hash"}
    if report_hash != _sha(body):
        raise ValueError("intellectual-diversity report hash mismatch")
    return DiversityExecutionReceipt(
        revision=revision,
        created_at_epoch=created,
        sha256=_sha_bytes(raw),
        report_hash=report_hash,
        task_commitment=task_hash,
        manifest_hash=manifest_hash,
        run_count=len(runs),
    )


def _same_receipt(
    row: Mapping[str, Any], *, capability_id: int, digest: str, reference: str, revision: str
) -> bool:
    expected = {
        "capability_id": capability_id,
        "proof_kind": _PROOF_KIND.value,
        "subject": _SUBJECT,
        "subject_sha256": digest,
        "verifier": _VERIFIER,
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_intellectual_diversity_proofs(
    *,
    repo_root: str | os.PathLike[str],
    execution_receipt_path: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    observation_id: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> DiversityProofAttestation:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    observation = _safe_id(observation_id, "observation_id")
    root = Path(repo_root).resolve(strict=True)
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "").strip().lower()
    if not identity_before.get("available") or not identity_before.get("clean") or len(revision) != 40:
        raise ValueError("intellectual-diversity attestation requires a clean Git checkout")
    execution = validate_intellectual_diversity_receipt(
        execution_receipt_path, repo_root=root, now=current_time
    )
    if execution.revision != revision:
        raise ValueError("intellectual-diversity receipt revision mismatch")

    tracked = _tracked_index(root)
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    reference = f"{_REFERENCE_PREFIX}{observation}"
    for capability_id in _CAPABILITY_IDS:
        matching = tuple(
            rule for rule in policy.rules
            if rule.capability_id == capability_id
            and rule.proof_kind is _PROOF_KIND
            and _SUBJECT in rule.subjects
            and _VERIFIER in rule.verifiers
        )
        if not matching:
            raise ValueError(f"committed proof policy has no specialized c{capability_id} independence rule")
        if not any(
            not rule.reference_prefixes
            or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
            for rule in matching
        ):
            raise ValueError("generated independence reference is not allowed by proof policy")

    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or len(prior) != 40:
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not continuity.verify_chain(anchor_token=prior_anchor_token, current_revision=prior):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    digest = execution.sha256
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = 0
    reused = 0
    for capability_id in _CAPABILITY_IDS:
        receipt_id = f"scientist-society-independent:{revision[:12]}:{digest[:12]}:c{capability_id}"
        previous = existing.get(receipt_id)
        if previous is not None:
            if not _same_receipt(
                previous,
                capability_id=capability_id,
                digest=digest,
                reference=reference,
                revision=revision,
            ):
                raise ValueError("deterministic intellectual-diversity receipt_id collision")
            reused += 1
            continue
        ledger.add(
            receipt_id=receipt_id,
            capability_id=capability_id,
            proof_kind=_PROOF_KIND,
            subject=_SUBJECT,
            subject_sha256=digest,
            verifier=_VERIFIER,
            observed_at=current_time,
            reference=reference,
            implementation_revision=revision,
        )
        added += 1
    if added + reused != len(_CAPABILITY_IDS):
        raise ValueError("intellectual-diversity attestation did not account for every route")

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
        raise ValueError("trusted maturity audit rejected intellectual-diversity attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "").strip().lower() != revision
    ):
        raise ValueError("repository changed during intellectual-diversity attestation")

    return DiversityProofAttestation(
        revision=revision,
        execution_receipt_sha256=execution.sha256,
        report_hash=execution.report_hash,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
