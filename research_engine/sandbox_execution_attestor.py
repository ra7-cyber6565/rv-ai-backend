"""Trusted execution attestor for the bounded numeric AST sandbox.

This module specializes only the software EXECUTION and REPRODUCIBILITY proof
routes for capability #23 (Code Sandbox).  It deliberately does NOT mint the
SAFETY proof also required by #23 and does not mint any proof for #114
(Sandboxed Reality): the in-process AST interpreter is not an OS/container
security boundary for hostile native/Python runtimes.

The locked benchmark executes a deterministic numeric experiment, repeats it
byte-identically, and checks a fixed adversarial corpus covering imports,
attributes/reflection, filesystem access, dynamic import/code, unsupported
control flow, and resource budgets.  These checks prove only the tracked
software behaviour for this exact revision and fixture set.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Tuple

from utils.release_identity import repository_identity

from . import code_sandbox as sandbox
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


_CAPABILITY_ID = 23
_REQUIRED = (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY)
_SUBJECT = "numeric-sandbox-benchmark"
_VERIFIER = "trusted-operator"
_ENGINE_SUBJECT = "research_engine/code_sandbox.py"
_BENCHMARK_VERSION = "numeric-sandbox-benchmark-v1"


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


def _rejected(source: str, *, policy: sandbox.SandboxPolicy | None = None) -> str:
    try:
        sandbox.NumericCodeSandbox(policy).run(source)
    except sandbox.SandboxLimitExceeded as exc:
        return f"LIMIT:{type(exc).__name__}:{str(exc)}"
    except sandbox.SandboxViolation as exc:
        return f"VIOLATION:{type(exc).__name__}:{str(exc)}"
    return "ACCEPTED"


def run_sandbox_benchmark() -> Mapping[str, Any]:
    """Execute a fixed deterministic sandbox and adversarial fixture set."""
    program = """
total = 0
for i in range(20):
    total += i * i
mean = total / 20
root = sqrt(total)
print(total)
print(round(mean, 3))
""".strip()
    valid = sandbox.NumericCodeSandbox().run(program)

    attacks = {
        "import": "import os",
        "from_import": "from pathlib import Path",
        "attribute_reflection": "x = (1).__class__",
        "filesystem_open": "x = open('secret.txt')",
        "dynamic_import": "x = __import__('os')",
        "attribute_call": "x = 'abc'.upper()",
        "function_definition": "def f():\n    return 1",
        "lambda": "x = lambda y: y",
        "while_loop": "while True:\n    pass",
        "try_except": "try:\n    x = 1\nexcept:\n    x = 2",
        "with_statement": "with open('x') as f:\n    x = 1",
        "comprehension": "x = [i for i in range(10)]",
    }
    attack_results = {name: _rejected(source) for name, source in attacks.items()}

    budget_results = {
        "loop_budget": _rejected(
            "x = 0\nfor i in range(11):\n    x += i",
            policy=sandbox.SandboxPolicy(max_loop_iterations=10),
        ),
        "operation_budget": _rejected(
            "x = 0\nfor i in range(100):\n    x += 1",
            policy=sandbox.SandboxPolicy(
                max_operations=20,
                max_loop_iterations=1_000,
            ),
        ),
        "exponent_budget": _rejected("x = 2 ** 1001"),
    }

    checks = {
        "valid_numeric_program_executes": (
            valid.outputs.get("total") == 2470
            and math.isclose(float(valid.outputs.get("mean", -1)), 123.5)
            and valid.stdout == "2470\n123.5"
            and valid.deterministic is True
        ),
        "result_declares_no_network_filesystem_or_subprocess": (
            valid.network_allowed is False
            and valid.filesystem_allowed is False
            and valid.subprocess_allowed is False
        ),
        "fixed_attack_corpus_is_rejected": all(
            value != "ACCEPTED" for value in attack_results.values()
        ),
        "resource_budget_attacks_are_rejected": all(
            value.startswith("LIMIT:") for value in budget_results.values()
        ),
    }
    payload = {
        "benchmark_version": _BENCHMARK_VERSION,
        "checks": checks,
        "valid_result": asdict(valid),
        "attack_results": attack_results,
        "budget_results": budget_results,
        "in_process_ast_interpreter": True,
        "os_container_isolation_observed": False,
        "native_code_isolation_observed": False,
        "safety_certified": False,
        "network_observed": False,
        "filesystem_observed": False,
        "subprocess_observed": False,
        "truth_proven": False,
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


@dataclass(frozen=True)
class SandboxExecutionAttestation:
    revision: str
    engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    os_container_isolation_observed: bool = False
    native_code_isolation_observed: bool = False
    safety_certified: bool = False
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
        "subject": _SUBJECT,
        "subject_sha256": digest,
        "verifier": _VERIFIER,
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_sandbox_execution(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> SandboxExecutionAttestation:
    """Run sandbox benchmark and mint only EXECUTION/REPRO receipts for #23."""
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    reference = _safe_reference(run_reference)
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "")
    if not identity_before.get("available") or not identity_before.get("clean") or not revision:
        raise ValueError("sandbox attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _ENGINE_SUBJECT)
    if Path(str(sandbox.__file__)).resolve(strict=True) != (root / _ENGINE_SUBJECT).resolve(strict=True):
        raise ValueError("sandbox runtime is not loaded from the audited repository")

    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    for kind in _REQUIRED:
        matching = tuple(
            rule for rule in policy.rules
            if rule.capability_id == _CAPABILITY_ID
            and rule.proof_kind is kind
            and _SUBJECT in rule.subjects
            and _VERIFIER in rule.verifiers
        )
        if not matching:
            raise ValueError(f"committed proof policy has no trusted sandbox {kind.value} rule")
        if not any(
            not rule.reference_prefixes
            or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
            for rule in matching
        ):
            raise ValueError("run_reference is not allowed by sandbox proof policy")

    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or not prior:
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not continuity.verify_chain(
            anchor_token=prior_anchor_token,
            current_revision=prior,
        ):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    first = run_sandbox_benchmark()
    second = run_sandbox_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("sandbox benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("sandbox benchmark is not deterministic")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    payload_for_digest = {
        key: value for key, value in first.items()
        if key not in {"benchmark_passed", "benchmark_sha256"}
    }
    if len(benchmark_digest) != 64 or benchmark_digest != _sha(payload_for_digest):
        raise ValueError("sandbox benchmark digest verification failed")

    receipt_digest = _sha({
        "revision": revision,
        "engine_sha256": engine_digest,
        "benchmark_sha256": benchmark_digest,
        "subject": _SUBJECT,
        "capability": _CAPABILITY_ID,
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0
    for kind in _REQUIRED:
        receipt_id = f"numeric-sandbox:{revision[:12]}:{kind.value}"
        previous = existing.get(receipt_id)
        if previous is not None:
            if not _same_receipt(
                previous,
                kind=kind,
                digest=receipt_digest,
                reference=reference,
                revision=revision,
            ):
                raise ValueError("deterministic sandbox receipt_id collision")
            reused += 1
            continue
        ledger.add(
            receipt_id=receipt_id,
            capability_id=_CAPABILITY_ID,
            proof_kind=kind,
            subject=_SUBJECT,
            subject_sha256=receipt_digest,
            verifier=_VERIFIER,
            observed_at=current_time,
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
        raise ValueError("trusted maturity audit rejected sandbox attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during sandbox attestation")

    return SandboxExecutionAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        benchmark_sha256=benchmark_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
