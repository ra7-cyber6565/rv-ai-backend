"""Trusted independent-validation attestation for capability #103.

The literature-debate engine can measure independence *inside* a literature set,
but that is not the same thing as independently validating the implementation.
This attestor keeps those concepts separate.

A trusted operator supplies a bounded JSON validation receipt produced against a
frozen case manifest.  The attestor derives the exact clean Git revision, hashes
the tracked debate engine and production-wiring files itself, requires at least
two distinct external validator identities/families/artifacts to have evaluated
the same case manifest with every case passing, recomputes all hashes, and only
then mints the policy-approved ``independent_validation`` proof.

This proves an independent implementation-validation event for the exact
revision.  It does not prove that any debated scientific proposition is true and
it does not treat literature consensus as truth.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

from utils.release_identity import repository_identity

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


_CAPABILITY_ID = 103
_SCHEMA_VERSION = 1
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024
_MAX_RECEIPT_AGE_SECONDS = 2 * 60 * 60
_MAX_FUTURE_SKEW_SECONDS = 5 * 60
_MAX_VALIDATORS = 16
_MAX_CASES = 10_000
_SUBJECT = "literature-debate-independent-validation"
_VERIFIER = "trusted-operator"
_REFERENCE_PREFIX = "literature-debate:"
_ENGINE_SUBJECTS = (
    "research_engine/literature_debate.py",
    "research_engine/literature_debate_wiring.py",
)
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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


def _read_bounded_json(path: Path) -> tuple[Mapping[str, Any], bytes]:
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError("literature debate validation receipt cannot be read") from exc
    if not path.is_file() or info.st_size < 1 or info.st_size > _MAX_RECEIPT_BYTES:
        raise ValueError("literature debate validation receipt size is invalid")
    data = path.read_bytes()
    if len(data) != info.st_size or len(data) > _MAX_RECEIPT_BYTES:
        raise ValueError("literature debate validation receipt changed during read")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("literature debate validation receipt is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("literature debate validation receipt must be a JSON object")
    return value, data


@dataclass(frozen=True)
class LiteratureDebateValidationReceipt:
    revision: str
    created_at_epoch: int
    receipt_sha256: str
    validation_sha256: str
    case_manifest_sha256: str
    engine_sha256: str
    wiring_sha256: str
    validator_count: int
    total_cases: int


@dataclass(frozen=True)
class LiteratureDebateIndependentAttestation:
    revision: str
    validation_receipt_sha256: str
    validation_sha256: str
    validator_count: int
    total_cases: int
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    truth_proven: bool = False
    consensus_proves_truth: bool = False


def validate_literature_debate_validation_receipt(
    path: str | os.PathLike[str],
    *,
    repo_root: str | os.PathLike[str],
    expected_revision: str,
    now: float,
) -> LiteratureDebateValidationReceipt:
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
        "schema_version",
        "created_at_epoch",
        "implementation_revision",
        "implementation_subjects",
        "case_manifest_sha256",
        "total_cases",
        "validators",
        "independent_validation_passed",
        "truth_proven",
        "consensus_proves_truth",
        "validation_sha256",
    }
    if set(value) != expected_keys:
        raise ValueError("literature debate validation receipt schema is invalid")
    if value.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported literature debate validation receipt schema")

    created = value.get("created_at_epoch")
    if isinstance(created, bool) or not isinstance(created, int):
        raise ValueError("created_at_epoch must be an integer")
    age = current_time - float(created)
    if age < -_MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("literature debate validation receipt is from the future")
    if age > _MAX_RECEIPT_AGE_SECONDS:
        raise ValueError("literature debate validation receipt is stale")
    if str(value.get("implementation_revision") or "").strip().lower() != revision:
        raise ValueError("literature debate validation receipt revision mismatch")

    subjects = value.get("implementation_subjects")
    if not isinstance(subjects, dict) or set(subjects) != set(_ENGINE_SUBJECTS):
        raise ValueError("implementation_subjects must bind the debate engine and wiring")
    actual_digests: Dict[str, str] = {}
    for subject in _ENGINE_SUBJECTS:
        claimed = _safe_sha(subjects.get(subject), f"digest for {subject}")
        actual = _hash_tracked_regular(root, tracked, subject)
        if claimed != actual:
            raise ValueError(f"tracked digest mismatch for {subject}")
        actual_digests[subject] = actual

    case_manifest = _safe_sha(value.get("case_manifest_sha256"), "case_manifest_sha256")
    total_cases = value.get("total_cases")
    if (
        isinstance(total_cases, bool)
        or not isinstance(total_cases, int)
        or total_cases < 1
        or total_cases > _MAX_CASES
    ):
        raise ValueError("total_cases is outside the validation budget")

    validators = value.get("validators")
    if not isinstance(validators, list) or not 2 <= len(validators) <= _MAX_VALIDATORS:
        raise ValueError("at least two bounded independent validators are required")
    normalized = []
    ids = set()
    families = set()
    artifacts = set()
    for index, item in enumerate(validators):
        if not isinstance(item, dict) or set(item) != {
            "validator_id",
            "validator_family",
            "validator_artifact_sha256",
            "case_manifest_sha256",
            "passed_cases",
            "total_cases",
            "decision",
            "result_sha256",
        }:
            raise ValueError(f"validator {index} schema is invalid")
        validator_id = _safe_id(item.get("validator_id"), "validator_id")
        family = _safe_id(item.get("validator_family"), "validator_family")
        artifact = _safe_sha(
            item.get("validator_artifact_sha256"), "validator_artifact_sha256"
        )
        if validator_id in ids or family in families or artifact in artifacts:
            raise ValueError(
                "validator identities, families, and artifacts must all be distinct"
            )
        ids.add(validator_id)
        families.add(family)
        artifacts.add(artifact)
        if _safe_sha(item.get("case_manifest_sha256"), "validator case manifest") != case_manifest:
            raise ValueError("all validators must use the same frozen case manifest")
        passed = item.get("passed_cases")
        validator_total = item.get("total_cases")
        if (
            isinstance(passed, bool)
            or not isinstance(passed, int)
            or isinstance(validator_total, bool)
            or not isinstance(validator_total, int)
            or validator_total != total_cases
            or passed != total_cases
        ):
            raise ValueError("every independent validator must pass every frozen case")
        if item.get("decision") != "PASS":
            raise ValueError("every independent validator decision must be PASS")
        payload = {
            "validator_id": validator_id,
            "validator_family": family,
            "validator_artifact_sha256": artifact,
            "case_manifest_sha256": case_manifest,
            "passed_cases": passed,
            "total_cases": validator_total,
            "decision": "PASS",
        }
        result_sha = _safe_sha(item.get("result_sha256"), "result_sha256")
        if result_sha != _sha(payload):
            raise ValueError("validator result_sha256 verification failed")
        normalized.append({**payload, "result_sha256": result_sha})

    if value.get("independent_validation_passed") is not True:
        raise ValueError("independent validation did not pass")
    if value.get("truth_proven") is not False:
        raise ValueError("independent validation receipt must not claim truth_proven")
    if value.get("consensus_proves_truth") is not False:
        raise ValueError("independent validation receipt must preserve consensus-is-not-truth")

    validation_payload = {
        "schema_version": _SCHEMA_VERSION,
        "created_at_epoch": created,
        "implementation_revision": revision,
        "implementation_subjects": actual_digests,
        "case_manifest_sha256": case_manifest,
        "total_cases": total_cases,
        "validators": normalized,
        "independent_validation_passed": True,
        "truth_proven": False,
        "consensus_proves_truth": False,
    }
    validation_sha = _safe_sha(value.get("validation_sha256"), "validation_sha256")
    if validation_sha != _sha(validation_payload):
        raise ValueError("validation_sha256 verification failed")

    return LiteratureDebateValidationReceipt(
        revision=revision,
        created_at_epoch=created,
        receipt_sha256=_sha_bytes(raw),
        validation_sha256=validation_sha,
        case_manifest_sha256=case_manifest,
        engine_sha256=actual_digests[_ENGINE_SUBJECTS[0]],
        wiring_sha256=actual_digests[_ENGINE_SUBJECTS[1]],
        validator_count=len(normalized),
        total_cases=total_cases,
    )


def _same_receipt(
    row: Mapping[str, Any],
    *,
    digest: str,
    reference: str,
    revision: str,
) -> bool:
    expected = {
        "capability_id": _CAPABILITY_ID,
        "proof_kind": ProofKind.INDEPENDENT.value,
        "subject": _SUBJECT,
        "subject_sha256": digest,
        "verifier": _VERIFIER,
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_literature_debate_independent_validation(
    *,
    repo_root: str | os.PathLike[str],
    validation_receipt_path: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> LiteratureDebateIndependentAttestation:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    reference = _safe_reference(run_reference)
    if not reference.startswith(_REFERENCE_PREFIX):
        raise ValueError("run_reference is not a literature-debate trusted reference")
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "")
    if not identity_before.get("available") or not identity_before.get("clean") or not revision:
        raise ValueError("independent literature debate attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    rules = tuple(
        rule for rule in policy.rules
        if rule.capability_id == _CAPABILITY_ID
        and rule.proof_kind is ProofKind.INDEPENDENT
        and _SUBJECT in rule.subjects
        and _VERIFIER in rule.verifiers
    )
    if not rules:
        raise ValueError("committed proof policy has no trusted independent-validation rule")
    if not any(
        not rule.reference_prefixes
        or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
        for rule in rules
    ):
        raise ValueError("run_reference is not allowed by literature debate proof policy")

    validated = validate_literature_debate_validation_receipt(
        validation_receipt_path,
        repo_root=root,
        expected_revision=revision,
        now=current_time,
    )

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

    proof_digest = _sha({
        "revision": revision,
        "validation_sha256": validated.validation_sha256,
        "receipt_sha256": validated.receipt_sha256,
        "engine_sha256": validated.engine_sha256,
        "wiring_sha256": validated.wiring_sha256,
        "case_manifest_sha256": validated.case_manifest_sha256,
        "validator_count": validated.validator_count,
        "total_cases": validated.total_cases,
        "subject": _SUBJECT,
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    receipt_id = f"litdebate:{revision[:12]}:independent"
    previous = existing.get(receipt_id)
    added = reused = 0
    if previous is not None:
        if not _same_receipt(
            previous,
            digest=proof_digest,
            reference=reference,
            revision=revision,
        ):
            raise ValueError("deterministic literature debate receipt_id collision")
        reused = 1
    else:
        ledger.add(
            receipt_id=receipt_id,
            capability_id=_CAPABILITY_ID,
            proof_kind=ProofKind.INDEPENDENT,
            subject=_SUBJECT,
            subject_sha256=proof_digest,
            verifier=_VERIFIER,
            observed_at=current_time,
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
        raise ValueError("trusted maturity audit rejected literature debate validation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during literature debate attestation")

    return LiteratureDebateIndependentAttestation(
        revision=revision,
        validation_receipt_sha256=validated.receipt_sha256,
        validation_sha256=validated.validation_sha256,
        validator_count=validated.validator_count,
        total_cases=validated.total_cases,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
