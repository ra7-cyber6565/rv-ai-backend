"""Trusted execution/independence/reproducibility attestation for #18 Blind Analysis.

The core :mod:`research_engine.scientist_society` already redacts
``ResearchTask.expected_result`` from runners whose ``AgentSpec`` is marked
blind.  This module turns that mechanism into an auditable external execution
protocol without pretending that a unit test, a role label, or agreement proves
scientific truth.

Two boundaries are intentionally separate:

* ``build_blind_analysis_execution_receipt`` must be run in a trusted external
  operator process with the *actual* independently configured runners.  It
  executes the frozen blind task at least twice and records only hashes and
  runner-identity metadata; the hidden expected result is never written into the
  receipt.
* ``attest_blind_analysis_proofs`` validates that receipt against the exact clean
  Git revision and committed proof policy, then mints only capability #18
  EXECUTION, INDEPENDENT and REPRODUCIBILITY receipts into the HMAC ledger.

The structural independence check requires distinct runner ids, model families
and perspectives.  It cannot prove that two external providers secretly share
training data, infrastructure, or operators; that residual boundary remains the
responsibility of the trusted external observer.  Blindness and cross-run
repeatability are evidence about process integrity, never proof that an answer
is true.
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


_CAPABILITY_ID = 18
_SCHEMA_VERSION = 1
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024
_MAX_TASK_BYTES = 512 * 1024
_MAX_RECEIPT_AGE_SECONDS = 2 * 60 * 60
_MAX_FUTURE_SKEW_SECONDS = 5 * 60
_MAX_AGENTS = 16
_MIN_RUNS = 2
_MAX_RUNS = 5
_IMPLEMENTATION_SUBJECT = "research_engine/scientist_society.py"
_SUBJECT = "blind-analysis-run"
_VERIFIER = "trusted-blind-analysis-observer"
_REFERENCE_PREFIX = "blind-analysis:"
_REQUIRED_PROOFS: Tuple[ProofKind, ...] = (
    ProofKind.EXECUTION,
    ProofKind.INDEPENDENT,
    ProofKind.REPRODUCIBILITY,
)
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
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
        raise ValueError("blind-analysis receipt data must be strict JSON") from exc


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _outside_repo(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return False
    except ValueError:
        return True


def _blind_packet(task: ResearchTask) -> Dict[str, Any]:
    packet = {
        "question": str(task.question),
        "evidence": [dict(item) for item in tuple(task.evidence)],
        "hypothesis": task.hypothesis,
        "expected_result": None,
        "constraints": dict(task.constraints),
    }
    encoded = _canonical(packet)
    if len(encoded) > _MAX_TASK_BYTES:
        raise ValueError("blind-analysis task exceeds bounded JSON size")
    return packet


def _agent_manifest(agents: Sequence[Tuple[AgentSpec, Runner]]) -> Tuple[Dict[str, str], ...]:
    if not isinstance(agents, Sequence) or not 2 <= len(agents) <= _MAX_AGENTS:
        raise ValueError("blind analysis requires 2..16 agents")
    rows = []
    for index, pair in enumerate(agents):
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise ValueError(f"agent binding {index} is invalid")
        spec, runner = pair
        if not isinstance(spec, AgentSpec) or not callable(runner):
            raise ValueError(f"agent binding {index} is invalid")
        if spec.blind_to_expected_result is not True:
            raise ValueError("every blind-analysis agent must be blind_to_expected_result")
        rows.append({
            "agent_id": _safe_id(spec.agent_id, "agent_id"),
            "runner_id": _safe_id(spec.runner_id, "runner_id"),
            "model_family": _safe_id(spec.model_family, "model_family"),
            "perspective": _safe_id(spec.perspective, "perspective"),
        })
    for field in ("agent_id", "runner_id"):
        values = [row[field] for row in rows]
        if len(set(values)) != len(values):
            raise ValueError(f"{field} values must be distinct")
    if len({row["model_family"] for row in rows}) < 2:
        raise ValueError("blind analysis requires at least two model families")
    if len({row["perspective"] for row in rows}) < 2:
        raise ValueError("blind analysis requires at least two perspectives")
    return tuple(rows)


def build_blind_analysis_execution_receipt(
    *,
    repo_root: str | os.PathLike[str],
    task: ResearchTask,
    agents: Sequence[Tuple[AgentSpec, Runner]],
    created_at_epoch: int,
    repetitions: int = 2,
) -> Dict[str, Any]:
    """Execute a frozen blind task and return a strict external receipt.

    The hidden expected result is used only to construct a one-way commitment;
    runner packets are produced by ``ScientistSociety`` with that field removed.
    The commitment is an audit binding, not a confidentiality mechanism against
    brute-force guessing of a low-entropy target.
    """
    if type(created_at_epoch) is not int or created_at_epoch <= 0:
        raise ValueError("created_at_epoch must be a positive integer")
    if type(repetitions) is not int or not _MIN_RUNS <= repetitions <= _MAX_RUNS:
        raise ValueError("repetitions must be between 2 and 5")
    if not isinstance(task, ResearchTask) or not str(task.question).strip():
        raise ValueError("a non-empty ResearchTask is required")
    expected = str(task.expected_result or "").strip()
    if not expected:
        raise ValueError("blind analysis requires a hidden expected_result")

    root = Path(repo_root).resolve(strict=True)
    identity = repository_identity(root)
    revision = str(identity.get("revision") or "")
    if not identity.get("available") or not identity.get("clean") or not revision:
        raise ValueError("blind-analysis execution requires a clean Git checkout")
    tracked = _tracked_index(root)
    implementation_sha256 = _hash_tracked_regular(
        root, tracked, _IMPLEMENTATION_SUBJECT
    )

    manifest = _agent_manifest(agents)
    manifest_hash = _sha(_canonical(list(manifest)))
    packet = _blind_packet(task)
    blind_packet_hash = _sha(_canonical(packet))
    hidden_commitment = _sha(
        b"blind-analysis-hidden-target-v1\x00" + expected.encode("utf-8")
    )
    protocol_payload = {
        "blind_packet_hash": blind_packet_hash,
        "hidden_expected_result_commitment": hidden_commitment,
        "agent_manifest_hash": manifest_hash,
    }
    protocol_hash = _sha(_canonical(protocol_payload))

    run_rows = []
    for run_index in range(repetitions):
        society = ScientistSociety(
            agents,
            minimum_independent_runners=2,
            max_workers=min(len(agents), 16),
        )
        run = society.run(task)
        if run.successful_agents != len(agents):
            raise ValueError("blind-analysis run contains failed agents")
        if run.blind_outputs != len(agents):
            raise ValueError("blind-analysis run exposed expected result to an agent")
        if not run.independent or run.distinct_runner_ids < 2:
            raise ValueError("blind-analysis run lacks distinct runner identities")
        if run.distinct_model_families < 2 or run.distinct_perspectives < 2:
            raise ValueError("blind-analysis run lacks model/perspective diversity")

        outputs_by_id = {item.agent_id: item for item in run.outputs}
        agent_rows = []
        for manifest_row in manifest:
            output = outputs_by_id.get(manifest_row["agent_id"])
            if output is None or output.error or not output.answer:
                raise ValueError("blind-analysis output is missing or failed")
            if output.blind is not True:
                raise ValueError("blind-analysis output is not marked blind")
            if output.runner_id != manifest_row["runner_id"]:
                raise ValueError("blind-analysis runner identity changed during run")
            if output.model_family != manifest_row["model_family"]:
                raise ValueError("blind-analysis model family changed during run")
            if output.perspective != manifest_row["perspective"]:
                raise ValueError("blind-analysis perspective changed during run")
            agent_rows.append({
                **manifest_row,
                "blind": True,
                "task_packet_hash": blind_packet_hash,
                "output_hash": _safe_sha(output.output_hash, "output_hash"),
                "success": True,
                "error": "",
            })
        agent_rows.sort(key=lambda row: row["agent_id"])
        run_payload = {
            "run_id": f"run-{run_index + 1}",
            "protocol_hash": protocol_hash,
            "agents": agent_rows,
        }
        run_rows.append({**run_payload, "run_hash": _sha(_canonical(run_payload))})

    report_payload = {
        "schema_version": _SCHEMA_VERSION,
        "created_at_epoch": created_at_epoch,
        "implementation_revision": revision,
        "implementation_subject": _IMPLEMENTATION_SUBJECT,
        "implementation_sha256": implementation_sha256,
        "protocol": {
            "task": packet,
            "blind_packet_hash": blind_packet_hash,
            "hidden_expected_result_commitment": hidden_commitment,
            "agent_manifest": list(manifest),
            "agent_manifest_hash": manifest_hash,
            "protocol_hash": protocol_hash,
        },
        "runs": run_rows,
        "execution_complete": True,
        "blindness_structure_satisfied": True,
        "independence_structure_satisfied": True,
        "reproducibility_structure_satisfied": True,
        "expected_result_not_written_to_receipt": True,
        "truth_proven": False,
        "blindness_does_not_prove_truth": True,
    }
    report_payload["report_hash"] = _sha(_canonical(report_payload))
    if len(_canonical(report_payload)) > _MAX_RECEIPT_BYTES:
        raise ValueError("blind-analysis execution receipt exceeds size limit")
    return report_payload


@dataclass(frozen=True)
class BlindExecutionReceipt:
    revision: str
    created_at_epoch: int
    sha256: str
    report_hash: str
    protocol_hash: str
    agent_manifest_hash: str
    run_count: int


@dataclass(frozen=True)
class BlindProofAttestation:
    revision: str
    execution_receipt_sha256: str
    report_hash: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit


def _read_bounded_json(path: Path) -> tuple[Mapping[str, Any], bytes]:
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError("blind-analysis receipt cannot be read") from exc
    if not path.is_file() or info.st_size < 1 or info.st_size > _MAX_RECEIPT_BYTES:
        raise ValueError("blind-analysis receipt size is invalid")
    data = path.read_bytes()
    if len(data) != info.st_size or len(data) > _MAX_RECEIPT_BYTES:
        raise ValueError("blind-analysis receipt changed during read")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("blind-analysis receipt is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("blind-analysis receipt must be a JSON object")
    return value, data


def _validate_protocol(value: object) -> tuple[str, str, str]:
    if not isinstance(value, dict) or set(value) != {
        "task",
        "blind_packet_hash",
        "hidden_expected_result_commitment",
        "agent_manifest",
        "agent_manifest_hash",
        "protocol_hash",
    }:
        raise ValueError("blind-analysis protocol schema is invalid")
    task = value.get("task")
    if not isinstance(task, dict) or set(task) != {
        "question", "evidence", "hypothesis", "expected_result", "constraints"
    }:
        raise ValueError("blind-analysis task schema is invalid")
    if not isinstance(task.get("question"), str) or not task["question"].strip():
        raise ValueError("blind-analysis question is invalid")
    if task.get("expected_result") is not None:
        raise ValueError("blind-analysis receipt must not contain expected_result")
    if not isinstance(task.get("evidence"), list) or not all(
        isinstance(item, dict) for item in task["evidence"]
    ):
        raise ValueError("blind-analysis evidence is invalid")
    if task.get("hypothesis") is not None and not isinstance(task.get("hypothesis"), str):
        raise ValueError("blind-analysis hypothesis is invalid")
    if not isinstance(task.get("constraints"), dict):
        raise ValueError("blind-analysis constraints are invalid")
    if len(_canonical(task)) > _MAX_TASK_BYTES:
        raise ValueError("blind-analysis task exceeds bounded JSON size")

    blind_hash = _safe_sha(value.get("blind_packet_hash"), "blind_packet_hash")
    if _sha(_canonical(task)) != blind_hash:
        raise ValueError("blind_packet_hash verification failed")
    commitment = _safe_sha(
        value.get("hidden_expected_result_commitment"),
        "hidden_expected_result_commitment",
    )
    manifest_raw = value.get("agent_manifest")
    if not isinstance(manifest_raw, list) or not 2 <= len(manifest_raw) <= _MAX_AGENTS:
        raise ValueError("blind-analysis agent_manifest size is invalid")
    manifest = []
    for index, row in enumerate(manifest_raw):
        if not isinstance(row, dict) or set(row) != {
            "agent_id", "runner_id", "model_family", "perspective"
        }:
            raise ValueError(f"blind-analysis agent manifest row {index} is invalid")
        manifest.append({
            "agent_id": _safe_id(row["agent_id"], "agent_id"),
            "runner_id": _safe_id(row["runner_id"], "runner_id"),
            "model_family": _safe_id(row["model_family"], "model_family"),
            "perspective": _safe_id(row["perspective"], "perspective"),
        })
    if len({row["agent_id"] for row in manifest}) != len(manifest):
        raise ValueError("blind-analysis agent ids must be distinct")
    if len({row["runner_id"] for row in manifest}) < 2:
        raise ValueError("blind-analysis requires at least two runner ids")
    if len({row["model_family"] for row in manifest}) < 2:
        raise ValueError("blind-analysis requires at least two model families")
    if len({row["perspective"] for row in manifest}) < 2:
        raise ValueError("blind-analysis requires at least two perspectives")
    manifest.sort(key=lambda row: row["agent_id"])
    manifest_hash = _safe_sha(value.get("agent_manifest_hash"), "agent_manifest_hash")
    if _sha(_canonical(manifest)) != manifest_hash:
        raise ValueError("agent_manifest_hash verification failed")
    protocol_hash = _safe_sha(value.get("protocol_hash"), "protocol_hash")
    expected_protocol = {
        "blind_packet_hash": blind_hash,
        "hidden_expected_result_commitment": commitment,
        "agent_manifest_hash": manifest_hash,
    }
    if _sha(_canonical(expected_protocol)) != protocol_hash:
        raise ValueError("protocol_hash verification failed")
    return blind_hash, manifest_hash, protocol_hash


def _validate_runs(
    value: object,
    *,
    blind_packet_hash: str,
    manifest_hash: str,
    protocol_hash: str,
    manifest: Sequence[Mapping[str, str]],
) -> int:
    if not isinstance(value, list) or not _MIN_RUNS <= len(value) <= _MAX_RUNS:
        raise ValueError("blind-analysis receipt must contain 2..5 runs")
    expected_manifest = {
        row["agent_id"]: (
            row["runner_id"], row["model_family"], row["perspective"]
        )
        for row in manifest
    }
    seen_run_ids = set()
    for index, run in enumerate(value):
        if not isinstance(run, dict) or set(run) != {
            "run_id", "protocol_hash", "agents", "run_hash"
        }:
            raise ValueError(f"blind-analysis run {index} schema is invalid")
        run_id = _safe_id(run["run_id"], "run_id")
        if run_id in seen_run_ids:
            raise ValueError("blind-analysis run ids must be distinct")
        seen_run_ids.add(run_id)
        if _safe_sha(run["protocol_hash"], "run protocol_hash") != protocol_hash:
            raise ValueError("blind-analysis run protocol_hash mismatch")
        agents = run.get("agents")
        if not isinstance(agents, list) or len(agents) != len(expected_manifest):
            raise ValueError("blind-analysis run agent set is incomplete")
        seen_agents = set()
        normalized = []
        for agent_index, row in enumerate(agents):
            if not isinstance(row, dict) or set(row) != {
                "agent_id", "runner_id", "model_family", "perspective", "blind",
                "task_packet_hash", "output_hash", "success", "error",
            }:
                raise ValueError(
                    f"blind-analysis run {index} agent {agent_index} schema is invalid"
                )
            agent_id = _safe_id(row["agent_id"], "agent_id")
            if agent_id in seen_agents or agent_id not in expected_manifest:
                raise ValueError("blind-analysis run agent identities are invalid")
            seen_agents.add(agent_id)
            expected = expected_manifest[agent_id]
            identity = (
                _safe_id(row["runner_id"], "runner_id"),
                _safe_id(row["model_family"], "model_family"),
                _safe_id(row["perspective"], "perspective"),
            )
            if identity != expected:
                raise ValueError("blind-analysis run agent manifest changed")
            if row.get("blind") is not True:
                raise ValueError("blind-analysis run contains an unblinded agent")
            if _safe_sha(row.get("task_packet_hash"), "task_packet_hash") != blind_packet_hash:
                raise ValueError("blind-analysis runner received a different task packet")
            _safe_sha(row.get("output_hash"), "output_hash")
            if row.get("success") is not True or row.get("error") != "":
                raise ValueError("blind-analysis run contains a failed agent")
            normalized.append(dict(row))
        if set(seen_agents) != set(expected_manifest):
            raise ValueError("blind-analysis run is missing an agent")
        normalized.sort(key=lambda row: row["agent_id"])
        run_payload = {
            "run_id": run_id,
            "protocol_hash": protocol_hash,
            "agents": normalized,
        }
        if _safe_sha(run.get("run_hash"), "run_hash") != _sha(_canonical(run_payload)):
            raise ValueError("blind-analysis run_hash verification failed")
    # Reproducibility here means the same frozen blinded protocol and independent
    # manifest executed successfully more than once; stochastic answers need not
    # be byte-identical across repeats.
    if not manifest_hash:
        raise ValueError("blind-analysis manifest hash is missing")
    return len(value)


def validate_blind_analysis_execution_receipt(
    path: str | os.PathLike[str],
    *,
    repo_root: str | os.PathLike[str],
    expected_revision: str,
    now: float,
) -> BlindExecutionReceipt:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    revision = str(expected_revision or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(revision):
        raise ValueError("expected_revision must be a full lowercase Git SHA")
    root = Path(repo_root).resolve(strict=True)
    tracked = _tracked_index(root)
    value, raw = _read_bounded_json(Path(path).expanduser().resolve())
    expected_keys = {
        "schema_version", "created_at_epoch", "implementation_revision",
        "implementation_subject", "implementation_sha256", "protocol", "runs",
        "execution_complete", "blindness_structure_satisfied",
        "independence_structure_satisfied", "reproducibility_structure_satisfied",
        "expected_result_not_written_to_receipt", "truth_proven",
        "blindness_does_not_prove_truth", "report_hash",
    }
    if set(value) != expected_keys:
        raise ValueError("blind-analysis receipt top-level schema is invalid")
    if value.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported blind-analysis receipt schema_version")
    created = value.get("created_at_epoch")
    if type(created) is not int or created <= 0:
        raise ValueError("blind-analysis created_at_epoch is invalid")
    if created > current_time + _MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("blind-analysis receipt is from the future")
    if current_time - created > _MAX_RECEIPT_AGE_SECONDS:
        raise ValueError("blind-analysis receipt is stale")
    receipt_revision = str(value.get("implementation_revision") or "").strip().lower()
    if receipt_revision != revision or not _GIT_SHA_RE.fullmatch(receipt_revision):
        raise ValueError("blind-analysis receipt revision does not match current Git HEAD")
    if value.get("implementation_subject") != _IMPLEMENTATION_SUBJECT:
        raise ValueError("blind-analysis implementation subject is invalid")
    actual_impl = _hash_tracked_regular(root, tracked, _IMPLEMENTATION_SUBJECT)
    if _safe_sha(value.get("implementation_sha256"), "implementation_sha256") != actual_impl:
        raise ValueError("blind-analysis implementation hash does not match tracked code")
    for field in (
        "execution_complete",
        "blindness_structure_satisfied",
        "independence_structure_satisfied",
        "reproducibility_structure_satisfied",
        "expected_result_not_written_to_receipt",
        "blindness_does_not_prove_truth",
    ):
        if value.get(field) is not True:
            raise ValueError(f"blind-analysis receipt requires {field}=true")
    if value.get("truth_proven") is not False:
        raise ValueError("blind-analysis receipt must not claim truth_proven")

    blind_hash, manifest_hash, protocol_hash = _validate_protocol(value.get("protocol"))
    manifest = value["protocol"]["agent_manifest"]
    run_count = _validate_runs(
        value.get("runs"),
        blind_packet_hash=blind_hash,
        manifest_hash=manifest_hash,
        protocol_hash=protocol_hash,
        manifest=manifest,
    )
    claimed_report_hash = _safe_sha(value.get("report_hash"), "report_hash")
    report_payload = {key: item for key, item in value.items() if key != "report_hash"}
    if _sha(_canonical(report_payload)) != claimed_report_hash:
        raise ValueError("blind-analysis report_hash verification failed")
    return BlindExecutionReceipt(
        revision=revision,
        created_at_epoch=created,
        sha256=_sha(raw),
        report_hash=claimed_report_hash,
        protocol_hash=protocol_hash,
        agent_manifest_hash=manifest_hash,
        run_count=run_count,
    )


def _required_policy_rules(policy) -> None:
    for kind in _REQUIRED_PROOFS:
        if not any(
            rule.capability_id == _CAPABILITY_ID
            and rule.proof_kind == kind
            and _SUBJECT in rule.subjects
            and _VERIFIER in rule.verifiers
            and _REFERENCE_PREFIX in rule.reference_prefixes
            for rule in policy.rules
        ):
            raise ValueError(
                f"committed proof policy does not authorize capability 18 {kind.value} attestation"
            )


def _existing_adds(ledger: ProofLedger) -> Mapping[str, Mapping[str, Any]]:
    return {
        str(row.get("receipt_id") or ""): row
        for row in ledger._events()  # noqa: SLF001 - trusted same-package attestor
        if row.get("event_type") == "ADD"
    }


def _same_receipt(
    row: Mapping[str, Any],
    *,
    kind: ProofKind,
    digest: str,
    reference: str,
    revision: str,
) -> bool:
    expected = {
        "capability_id": _CAPABILITY_ID,
        "proof_kind": kind.value,
        "subject": _SUBJECT,
        "subject_sha256": digest,
        "verifier": _VERIFIER,
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == item for key, item in expected.items())


def attest_blind_analysis_proofs(
    *,
    repo_root: str | os.PathLike[str],
    execution_receipt_path: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> BlindProofAttestation:
    """Mint only trusted #18 execution/independent/reproducibility proofs."""
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity = repository_identity(root)
    revision = str(identity.get("revision") or "")
    if not identity.get("available") or not identity.get("clean") or not revision:
        raise ValueError("blind-analysis attestation requires a clean Git checkout")

    receipt = validate_blind_analysis_execution_receipt(
        execution_receipt_path,
        repo_root=root,
        expected_revision=revision,
        now=current_time,
    )
    tracked = _tracked_index(root)
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    _required_policy_rules(policy)

    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or not _GIT_SHA_RE.fullmatch(prior):
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not continuity.verify_chain(
            anchor_token=prior_anchor_token,
            current_revision=prior,
        ):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    reference = _REFERENCE_PREFIX + receipt.report_hash
    added = 0
    reused = 0
    for kind in _REQUIRED_PROOFS:
        receipt_id = f"blind:c18:{kind.value}:{receipt.sha256[:16]}"
        previous = existing.get(receipt_id)
        if previous is not None:
            if not _same_receipt(
                previous,
                kind=kind,
                digest=receipt.sha256,
                reference=reference,
                revision=revision,
            ):
                raise ValueError("deterministic blind-analysis maturity receipt_id collision")
            reused += 1
            continue
        ledger.add(
            receipt_id=receipt_id,
            capability_id=_CAPABILITY_ID,
            proof_kind=kind,
            subject=_SUBJECT,
            subject_sha256=receipt.sha256,
            verifier=_VERIFIER,
            observed_at=current_time,
            reference=reference,
            implementation_revision=revision,
        )
        added += 1

    anchor_token = ledger.create_anchor(
        current_revision=revision,
        issued_at=current_time,
    )
    audit = audit_repository_maturity(
        repo_root=root,
        ledger_path=ledger_target,
        integrity_key=integrity_key,
        anchor_token=anchor_token,
        now=current_time,
        policy_path=policy_path,
    )
    return BlindProofAttestation(
        revision=revision,
        execution_receipt_sha256=receipt.sha256,
        report_hash=receipt.report_hash,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor_token,
        audit=audit,
    )
