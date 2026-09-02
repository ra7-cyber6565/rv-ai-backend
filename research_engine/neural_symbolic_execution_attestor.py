"""Trusted EXECUTION/REPRODUCIBILITY attestor for #67 Neural+Symbolic Hybrid.

Unlike the core auditor, this attestor requires an external neural runner to be
actually invoked on a frozen structured task. The runner must return the exact
formal-logic contract supplied by the benchmark; the attestor hashes that output
and independently executes the symbolic verifier. The same runner is invoked
again and the complete benchmark packet must be byte-equivalent before a
reproducibility receipt is minted.

This proves a bounded external-neural + symbolic execution path for one frozen
contract. It does not prove model quality, external independence, or scientific
truth.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from utils.release_identity import repository_identity

from . import neural_symbolic_hybrid as hybrid
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


_CAPABILITY_ID = 67
_ENGINE_SUBJECT = "research_engine/neural_symbolic_hybrid.py"
_BENCHMARK_VERSION = "neural-symbolic-execution-v1"
_REQUIRED = (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY)
_VERIFIERS = {
    ProofKind.EXECUTION: "trusted-execution-attestor",
    ProofKind.REPRODUCIBILITY: "trusted-reproducibility-attestor",
}
_NAMESPACES = {
    ProofKind.EXECUTION: "execution",
    ProofKind.REPRODUCIBILITY: "reproducibility",
}
_SUFFIXES = {
    ProofKind.EXECUTION: "execution-run",
    ProofKind.REPRODUCIBILITY: "reproducibility-run",
}
Runner = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("benchmark payload must be finite JSON-compatible data") from exc


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_id(value: object, field: str, maximum: int = 120) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum:
        raise ValueError(f"{field} is invalid")
    if any(not (ch.isalnum() or ch in "_.@/+~-") for ch in text):
        raise ValueError(f"{field} is invalid")
    return text


def _subject(kind: ProofKind) -> str:
    return f"capability-{_CAPABILITY_ID}-{_SUFFIXES[kind]}"


def _reference(kind: ProofKind, observation_id: str) -> str:
    return f"{_NAMESPACES[kind]}:c{_CAPABILITY_ID}:{observation_id}"


def _contract() -> Mapping[str, Any]:
    atom_a = {"atom": "A"}
    atom_b = {"atom": "B"}
    return {
        "atoms": ["A", "B"],
        "premises": [
            {"implies": [atom_a, atom_b]},
            atom_a,
        ],
        "conclusion": atom_b,
    }


def run_neural_symbolic_execution_benchmark(
    *,
    runner: Runner,
    runner_id: str,
    runner_revision: str,
) -> Mapping[str, Any]:
    if not callable(runner):
        raise ValueError("runner must be callable")
    model_id = _safe_id(runner_id, "runner_id")
    model_revision = _safe_id(runner_revision, "runner_revision")
    contract = _contract()
    task = {
        "benchmark_version": _BENCHMARK_VERSION,
        "instruction": (
            "Return only the supplied structured formal_logic contract plus a finite "
            "model_confidence. Do not convert prose into logic and do not claim truth."
        ),
        "formal_logic": contract,
    }
    response = runner(task)
    if not isinstance(response, Mapping):
        raise ValueError("neural runner response must be a mapping")
    allowed = {"formal_logic", "model_confidence", "self_reported_proved"}
    if set(response) != allowed:
        raise ValueError("neural runner response schema is invalid")
    returned_contract = response.get("formal_logic")
    if not isinstance(returned_contract, Mapping) or dict(returned_contract) != dict(contract):
        raise ValueError("neural runner changed the frozen formal_logic contract")
    confidence = float(response.get("model_confidence"))
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError("model_confidence must be finite and in [0,1]")
    if not isinstance(response.get("self_reported_proved"), bool):
        raise ValueError("self_reported_proved must be boolean")

    output_digest = _sha(dict(response))
    proposal = hybrid.NeuralProposal(
        proposal_id="benchmark-proposal",
        model_id=model_id,
        model_revision=model_revision,
        model_output_sha256=output_digest,
        model_confidence=confidence,
        formal_logic=contract,
        self_reported_proved=bool(response["self_reported_proved"]),
    )
    report = hybrid.audit_neural_symbolic((proposal,))
    audit = report.audits[0]
    checks = {
        "external_runner_called": True,
        "runner_contract_preserved": returned_contract == contract,
        "output_digest_bound": audit.model_output_sha256 == output_digest,
        "runner_identity_bound": (
            audit.model_id == model_id and audit.model_revision == model_revision
        ),
        "symbolic_verifier_executed": report.symbolic_verification_executed is True,
        "symbolic_entailment_proved": (
            audit.symbolic_status == "PROVED"
            and audit.symbolic_entailed is True
            and audit.symbolic_consistent is True
            and audit.hybrid_gate_passed is True
        ),
        "self_report_cannot_override_gate": audit.neural_self_report_can_override_symbolic_gate is False,
        "no_natural_language_formalization": audit.natural_language_formalization_performed is False,
        "truth_boundary": report.truth_proven is False and audit.truth_proven is False,
    }
    payload = {
        "benchmark_version": _BENCHMARK_VERSION,
        "task_sha256": _sha(task),
        "runner_id": model_id,
        "runner_revision": model_revision,
        "runner_response": dict(response),
        "runner_response_sha256": output_digest,
        "checks": checks,
        "hybrid_report": asdict(report),
        "external_neural_runner_executed": True,
        "external_independence_proven": False,
        "truth_proven": False,
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


@dataclass(frozen=True)
class NeuralSymbolicExecutionAttestation:
    revision: str
    engine_sha256: str
    benchmark_sha256: str
    runner_id: str
    runner_revision: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    external_neural_runner_executed: bool = True
    external_independence_proven: bool = False
    truth_proven: bool = False


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
        "subject": _subject(kind),
        "subject_sha256": digest,
        "verifier": _VERIFIERS[kind],
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_neural_symbolic_execution(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    observation_id: str,
    runner: Runner,
    runner_id: str,
    runner_revision: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> NeuralSymbolicExecutionAttestation:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    observation = _safe_id(observation_id, "observation_id")
    model_id = _safe_id(runner_id, "runner_id")
    model_revision = _safe_id(runner_revision, "runner_revision")
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "").strip().lower()
    if not identity_before.get("available") or not identity_before.get("clean") or len(revision) != 40:
        raise ValueError("neural-symbolic attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _ENGINE_SUBJECT)
    imported_engine = Path(str(hybrid.__file__)).resolve(strict=True)
    audited_engine = (root / _ENGINE_SUBJECT).resolve(strict=True)
    if imported_engine != audited_engine:
        raise ValueError("Neural-Symbolic runtime is not loaded from the audited repository")

    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    references = {}
    for kind in _REQUIRED:
        subject = _subject(kind)
        verifier = _VERIFIERS[kind]
        reference = _reference(kind, observation)
        matching = tuple(
            rule for rule in policy.rules
            if rule.capability_id == _CAPABILITY_ID
            and rule.proof_kind is kind
            and subject in rule.subjects
            and verifier in rule.verifiers
        )
        if not matching:
            raise ValueError(f"committed proof policy has no trusted {kind.value} rule")
        if not any(
            not rule.reference_prefixes
            or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
            for rule in matching
        ):
            raise ValueError("generated reference is not allowed by proof policy")
        references[kind] = reference

    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or len(prior) != 40:
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not continuity.verify_chain(
            anchor_token=prior_anchor_token,
            current_revision=prior,
        ):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    first = run_neural_symbolic_execution_benchmark(
        runner=runner,
        runner_id=model_id,
        runner_revision=model_revision,
    )
    second = run_neural_symbolic_execution_benchmark(
        runner=runner,
        runner_id=model_id,
        runner_revision=model_revision,
    )
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("neural-symbolic benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("neural-symbolic external execution is not reproducible")
    if first.get("external_neural_runner_executed") is not True:
        raise ValueError("neural-symbolic attestation requires actual runner execution")
    if first.get("external_independence_proven") is not False:
        raise ValueError("benchmark must not claim external independence")
    if first.get("truth_proven") is not False:
        raise ValueError("benchmark must not claim scientific truth")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    payload_for_digest = {
        key: value for key, value in first.items()
        if key not in {"benchmark_passed", "benchmark_sha256"}
    }
    if len(benchmark_digest) != 64 or benchmark_digest != _sha(payload_for_digest):
        raise ValueError("neural-symbolic benchmark digest verification failed")

    receipt_digest = _sha({
        "revision": revision,
        "engine_sha256": engine_digest,
        "benchmark_sha256": benchmark_digest,
        "runner_id": model_id,
        "runner_revision": model_revision,
        "capability_id": _CAPABILITY_ID,
        "proof_kinds": [kind.value for kind in _REQUIRED],
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0
    for kind in _REQUIRED:
        reference = references[kind]
        receipt_id = f"neural-symbolic:{revision[:12]}:{kind.value}"
        previous = existing.get(receipt_id)
        if previous is not None:
            if not _same_receipt(
                previous,
                kind=kind,
                digest=receipt_digest,
                reference=reference,
                revision=revision,
            ):
                raise ValueError("deterministic neural-symbolic receipt_id collision")
            reused += 1
            continue
        ledger.add(
            receipt_id=receipt_id,
            capability_id=_CAPABILITY_ID,
            proof_kind=kind,
            subject=_subject(kind),
            subject_sha256=receipt_digest,
            verifier=_VERIFIERS[kind],
            observed_at=current_time,
            reference=reference,
            implementation_revision=revision,
        )
        added += 1

    if added + reused != len(_REQUIRED):
        raise ValueError("neural-symbolic attestation did not account for every proof route")

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
        raise ValueError("trusted maturity audit rejected neural-symbolic attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "").strip().lower() != revision
    ):
        raise ValueError("repository changed during neural-symbolic attestation")

    return NeuralSymbolicExecutionAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        benchmark_sha256=benchmark_digest,
        runner_id=model_id,
        runner_revision=model_revision,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
