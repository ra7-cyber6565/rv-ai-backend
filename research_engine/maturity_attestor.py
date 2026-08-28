"""Convert one trusted Foundation gate receipt into conservative maturity proofs.

A green Foundation run is useful evidence for source-code presence and test
coverage, but it is not independent validation, safety, reproducibility, live
operation, persistence or hardware evidence.  This module therefore attests
ONLY committed-policy CODE/TEST rules and deliberately refuses to mint any
stronger proof class.

Trust model
-----------
The caller supplies the HMAC key from a protected environment.  The receipt is
accepted only for the exact clean Git checkout being audited.  Existing ledgers
can be extended only when the caller also presents the prior trusted anchor and
its revision, preventing silent rollback/re-anchoring of an old valid prefix.
The new ledger head is anchored and immediately passed through the trusted
repository maturity auditor, which emits the exact 142-capability blockers.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple

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


_RECEIPT_SCHEMA_VERSION = 2
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024
_MAX_RECEIPT_AGE_SECONDS = 6 * 60 * 60
_MAX_FUTURE_SKEW_SECONDS = 5 * 60
_MAX_STAGES = 2_000
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_REFERENCE_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,500}$")
_REQUIRED_STAGES: Tuple[str, ...] = (
    "compileall",
    "focused_pytest",
    "all_pytest",
    "offline_api_smoke",
    "core_regression",
    "provider_bypass_audit",
    "architecture_audit",
    "benchmark_cross_domain",
    "benchmark_superconductivity_v2",
)
_FILE_PROOFS = {ProofKind.CODE, ProofKind.TEST}


@dataclass(frozen=True)
class FoundationReceipt:
    revision: str
    created_at_epoch: int
    sha256: str
    stages: Tuple[str, ...]


@dataclass(frozen=True)
class CodeTestAttestation:
    revision: str
    foundation_receipt_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_reference(value: object) -> str:
    text = str(value or "").strip()
    if not _SAFE_REFERENCE_RE.fullmatch(text):
        raise ValueError("run_reference is invalid")
    return text


def _read_bounded_json(path: Path) -> tuple[Mapping[str, Any], bytes]:
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError("Foundation receipt cannot be read") from exc
    if not path.is_file() or info.st_size < 1 or info.st_size > _MAX_RECEIPT_BYTES:
        raise ValueError("Foundation receipt size is invalid")
    data = path.read_bytes()
    if len(data) != info.st_size or len(data) > _MAX_RECEIPT_BYTES:
        raise ValueError("Foundation receipt changed during read")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Foundation receipt is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Foundation receipt must be a JSON object")
    return value, data


def _valid_command(command: object) -> tuple[str, ...]:
    if (
        not isinstance(command, list)
        or not command
        or len(command) > 10_000
        or any(not isinstance(item, str) or not item or len(item) > 2_000 for item in command)
    ):
        raise ValueError("Foundation stage command is invalid")
    return tuple(command)


def _require_suffix(command: Sequence[str], suffix: Sequence[str], stage: str) -> None:
    if len(command) < len(suffix) + 1 or tuple(command[-len(suffix):]) != tuple(suffix):
        raise ValueError(f"Foundation stage {stage} command is not canonical")


def _validate_stage(stage: object) -> tuple[str, tuple[str, ...]]:
    if not isinstance(stage, dict) or set(stage) != {
        "name",
        "command",
        "returncode",
        "duration_seconds",
        "status",
        "output_tail",
    }:
        raise ValueError("Foundation stage schema is invalid")
    name = stage.get("name")
    if not isinstance(name, str) or not name or len(name) > 500:
        raise ValueError("Foundation stage name is invalid")
    command = _valid_command(stage.get("command"))
    returncode = stage.get("returncode")
    if type(returncode) is not int or returncode != 0:
        raise ValueError(f"Foundation stage {name} did not exit cleanly")
    duration = stage.get("duration_seconds")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool):
        raise ValueError(f"Foundation stage {name} duration is invalid")
    duration = float(duration)
    if not math.isfinite(duration) or duration < 0:
        raise ValueError(f"Foundation stage {name} duration is invalid")
    if stage.get("status") != "passed":
        raise ValueError(f"Foundation stage {name} did not pass")
    output_tail = stage.get("output_tail")
    if (
        not isinstance(output_tail, list)
        or len(output_tail) > 1_000
        or any(not isinstance(line, str) or len(line) > 20_000 for line in output_tail)
    ):
        raise ValueError(f"Foundation stage {name} output_tail is invalid")
    return name, command


def _validate_required_stage_commands(commands: Mapping[str, Sequence[str]]) -> None:
    _require_suffix(commands["compileall"], ("-m", "compileall", "-q", "."), "compileall")
    _require_suffix(commands["all_pytest"], ("-m", "pytest", "-q", "tests"), "all_pytest")

    focused = commands["focused_pytest"]
    if len(focused) < 6 or tuple(focused[1:4]) != ("-m", "pytest", "-q"):
        raise ValueError("Foundation stage focused_pytest command is not canonical")
    focused_tests = focused[4:]
    if not focused_tests or any(
        not item.startswith("tests/test_") or not item.endswith(".py")
        for item in focused_tests
    ):
        raise ValueError("Foundation focused_pytest file set is invalid")

    exact_suffixes = {
        "offline_api_smoke": ("scripts/run_offline_api_smoke.py",),
        "core_regression": ("test_research_engine.py",),
        "provider_bypass_audit": ("scripts/audit_provider_bypass.py",),
        "architecture_audit": ("scripts/audit_architecture.py",),
        "benchmark_cross_domain": ("tests/benchmark_cross_domain.py",),
        "benchmark_superconductivity_v2": ("tests/benchmark_superconductivity.py",),
    }
    for name, suffix in exact_suffixes.items():
        _require_suffix(commands[name], suffix, name)


def validate_foundation_receipt(
    path: str | os.PathLike[str],
    *,
    expected_revision: str,
    now: float,
) -> FoundationReceipt:
    """Validate a green Foundation receipt against one exact Git revision."""
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    revision = str(expected_revision or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(revision):
        raise ValueError("expected_revision must be a full lowercase Git SHA")

    value, data = _read_bounded_json(Path(path).expanduser().resolve())
    required_top = {
        "schema_version",
        "created_at_epoch",
        "python",
        "repo_root",
        "code_revision",
        "repository_clean",
        "code_identity_verified",
        "offline_zero_cost",
        "passed",
        "failed_stages",
        "stages",
    }
    if set(value) != required_top:
        raise ValueError("Foundation receipt top-level schema is invalid")
    if value.get("schema_version") != _RECEIPT_SCHEMA_VERSION:
        raise ValueError("unsupported Foundation receipt schema_version")

    created = value.get("created_at_epoch")
    if type(created) is not int or created <= 0:
        raise ValueError("Foundation receipt created_at_epoch is invalid")
    if created > current_time + _MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("Foundation receipt is from the future")
    if current_time - created > _MAX_RECEIPT_AGE_SECONDS:
        raise ValueError("Foundation receipt is stale")

    receipt_revision = str(value.get("code_revision") or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(receipt_revision) or receipt_revision != revision:
        raise ValueError("Foundation receipt code_revision does not match current Git HEAD")
    if value.get("repository_clean") is not True:
        raise ValueError("Foundation receipt repository_clean must be true")
    if value.get("code_identity_verified") is not True:
        raise ValueError("Foundation receipt code_identity_verified must be true")
    if value.get("offline_zero_cost") is not True:
        raise ValueError("Foundation receipt offline_zero_cost must be true")
    if value.get("passed") is not True:
        raise ValueError("Foundation receipt did not pass")
    if value.get("failed_stages") != []:
        raise ValueError("Foundation receipt contains failed_stages")
    if not isinstance(value.get("python"), str) or not value.get("python"):
        raise ValueError("Foundation receipt python is invalid")
    if not isinstance(value.get("repo_root"), str) or not value.get("repo_root"):
        raise ValueError("Foundation receipt repo_root is invalid")

    stages_raw = value.get("stages")
    if not isinstance(stages_raw, list) or not stages_raw or len(stages_raw) > _MAX_STAGES:
        raise ValueError("Foundation receipt stages must be a bounded non-empty list")
    commands: dict[str, tuple[str, ...]] = {}
    for stage in stages_raw:
        name, command = _validate_stage(stage)
        if name in commands:
            raise ValueError("Foundation receipt contains duplicate stage names")
        commands[name] = command
    missing = [name for name in _REQUIRED_STAGES if name not in commands]
    if missing:
        raise ValueError("Foundation receipt is missing required stages: " + ", ".join(missing))
    _validate_required_stage_commands(commands)

    return FoundationReceipt(
        revision=revision,
        created_at_epoch=created,
        sha256=_sha(data),
        stages=tuple(commands),
    )


def _outside_repo(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return False
    except ValueError:
        return True


def _existing_adds(ledger: ProofLedger) -> Mapping[str, Mapping[str, Any]]:
    events = ledger._events()  # noqa: SLF001 - trusted same-package attestor
    return {
        str(row.get("receipt_id") or ""): row
        for row in events
        if row.get("event_type") == "ADD"
    }


def _same_code_test_receipt(
    row: Mapping[str, Any],
    *,
    capability_id: int,
    proof_kind: ProofKind,
    subject: str,
    subject_sha256: str,
    reference: str,
) -> bool:
    expected = {
        "capability_id": capability_id,
        "proof_kind": proof_kind.value,
        "subject": subject,
        "subject_sha256": subject_sha256,
        "verifier": "github-actions",
        "reference": reference,
        "implementation_revision": "",
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_foundation_code_test_proofs(
    *,
    repo_root: str | os.PathLike[str],
    foundation_receipt_path: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> CodeTestAttestation:
    """Mint only policy-approved CODE/TEST receipts from one green gate run."""
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
        raise ValueError("Foundation attestation requires a clean Git checkout")

    receipt = validate_foundation_receipt(
        foundation_receipt_path,
        expected_revision=revision,
        now=current_time,
    )
    tracked = _tracked_index(root)
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    eligible_rules = tuple(
        rule for rule in policy.rules
        if rule.proof_kind in _FILE_PROOFS and "github-actions" in rule.verifiers
    )
    if not eligible_rules:
        raise ValueError("committed proof policy has no github-actions CODE/TEST rules")

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
    added = 0
    reused = 0
    for rule in eligible_rules:
        for subject in rule.subjects:
            digest = _hash_tracked_regular(root, tracked, subject)
            receipt_id = (
                f"gha:{receipt.sha256[:12]}:c{rule.capability_id}:"
                f"{rule.proof_kind.value}:{_sha(subject.encode('utf-8'))[:12]}"
            )
            previous = existing.get(receipt_id)
            if previous is not None:
                if not _same_code_test_receipt(
                    previous,
                    capability_id=rule.capability_id,
                    proof_kind=rule.proof_kind,
                    subject=subject,
                    subject_sha256=digest,
                    reference=reference,
                ):
                    raise ValueError("deterministic maturity receipt_id collision")
                reused += 1
                continue
            ledger.add(
                receipt_id=receipt_id,
                capability_id=rule.capability_id,
                proof_kind=rule.proof_kind,
                subject=subject,
                subject_sha256=digest,
                verifier="github-actions",
                observed_at=current_time,
                reference=reference,
            )
            added += 1

    if added + reused <= 0:
        raise ValueError("Foundation attestation produced no CODE/TEST receipts")

    anchor = ledger.create_anchor(
        current_revision=revision,
        issued_at=current_time,
    )
    audit = audit_repository_maturity(
        repo_root=root,
        ledger_path=ledger_target,
        integrity_key=integrity_key,
        anchor_token=anchor,
        now=current_time,
        policy_path=policy_path,
    )
    if not audit.audit_valid:
        raise ValueError("trusted maturity audit rejected Foundation attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during Foundation attestation")

    return CodeTestAttestation(
        revision=revision,
        foundation_receipt_sha256=receipt.sha256,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
