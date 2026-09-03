"""Trusted independent-validation attestor for capability #140 Anti-Confirmation.

The anti-confirmation engine must not earn INDEPENDENT proof merely because the
same system says that it searched for counter-evidence.  This attestor accepts a
fresh external campaign bound to the exact clean Git revision and requires:

* a precommitted hypothesis/protocol/search-space/stopping rule;
* at least two explicit falsification criteria and three falsification-targeted
  attempts;
* a validator whose team, runner, model and implementation digest are all
  distinct from the originator;
* evidence/null-result recording and an explicit truth-is-not-proven boundary;
* deterministic campaign hashing, HMAC proof-ledger continuity and an external
  anchor.

A campaign is allowed to conclude that the hypothesis survived.  Anti-
confirmation is about genuinely trying to falsify a claim, not fabricating a
negative outcome.  This module mints only ``INDEPENDENT`` proof and never turns
an external campaign into execution, reproducibility, safety, live, hardware or
scientific-truth proof.
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
from .maturity_attestor import _existing_adds, _outside_repo
from .maturity_auditor import (
    TrustedMaturityAudit,
    _parse_policy,
    _read_policy_bytes,
    _tracked_index,
    audit_repository_maturity,
)
from .maturity_proof import ProofLedger


_CAPABILITY_ID = 140
_SCHEMA_VERSION = 1
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024
_MAX_RECEIPT_AGE_SECONDS = 2 * 60 * 60
_MAX_FUTURE_SKEW_SECONDS = 5 * 60
_MAX_CRITERIA = 64
_MAX_TESTS = 256
_MIN_CRITERIA = 2
_MIN_TESTS = 3
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_SUBJECT = "anti-confirmation-campaign"
_VERIFIER = "anti-confirmation-independent-validator"
_REFERENCE_PREFIX = "anti-confirmation:"
_ALLOWED_OUTCOMES = {"supporting", "contradicting", "inconclusive", "null"}
_ALLOWED_CONCLUSIONS = {"survived", "weakened", "falsified", "inconclusive"}


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
        raise ValueError("anti-confirmation campaign cannot be read") from exc
    if not path.is_file() or info.st_size < 1 or info.st_size > _MAX_RECEIPT_BYTES:
        raise ValueError("anti-confirmation campaign size is invalid")
    data = path.read_bytes()
    if len(data) != info.st_size or len(data) > _MAX_RECEIPT_BYTES:
        raise ValueError("anti-confirmation campaign changed during read")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("anti-confirmation campaign is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("anti-confirmation campaign must be a JSON object")
    return value, data


def _identity(value: object, field: str) -> Dict[str, str]:
    required = {"team_id", "runner_id", "model_id", "implementation_digest"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError(f"{field} identity schema is invalid")
    return {
        "team_id": _safe_id(value["team_id"], f"{field}.team_id"),
        "runner_id": _safe_id(value["runner_id"], f"{field}.runner_id"),
        "model_id": _safe_id(value["model_id"], f"{field}.model_id"),
        "implementation_digest": _safe_sha(
            value["implementation_digest"], f"{field}.implementation_digest"
        ),
    }


def _require_independence(originator: Mapping[str, str], validator: Mapping[str, str]) -> None:
    for field in ("team_id", "runner_id", "model_id", "implementation_digest"):
        if originator[field] == validator[field]:
            raise ValueError(
                f"independent validator must use a distinct {field} from originator"
            )


def _criteria(value: object) -> Tuple[Dict[str, str], ...]:
    if not isinstance(value, list) or not (_MIN_CRITERIA <= len(value) <= _MAX_CRITERIA):
        raise ValueError("falsification_criteria must contain at least two bounded criteria")
    rows = []
    seen = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {"criterion_id", "description_hash"}:
            raise ValueError(f"falsification criterion {index} schema is invalid")
        criterion_id = _safe_id(item["criterion_id"], "criterion_id")
        if criterion_id in seen:
            raise ValueError("duplicate falsification criterion_id")
        seen.add(criterion_id)
        rows.append({
            "criterion_id": criterion_id,
            "description_hash": _safe_sha(item["description_hash"], "description_hash"),
        })
    return tuple(rows)


def _tests(
    value: object,
    *,
    criterion_ids: set[str],
    validator: Mapping[str, str],
) -> Tuple[Dict[str, Any], ...]:
    if not isinstance(value, list) or not (_MIN_TESTS <= len(value) <= _MAX_TESTS):
        raise ValueError("tests must contain at least three bounded falsification attempts")
    rows = []
    seen_ids = set()
    seen_evidence = set()
    covered = set()
    for index, item in enumerate(value):
        required = {
            "test_id",
            "criterion_id",
            "method_hash",
            "evidence_hash",
            "targets_falsification",
            "outcome",
            "performed_by_team_id",
            "performed_by_runner_id",
        }
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError(f"anti-confirmation test {index} schema is invalid")
        test_id = _safe_id(item["test_id"], "test_id")
        if test_id in seen_ids:
            raise ValueError("duplicate anti-confirmation test_id")
        seen_ids.add(test_id)
        criterion_id = _safe_id(item["criterion_id"], "criterion_id")
        if criterion_id not in criterion_ids:
            raise ValueError("anti-confirmation test references an unknown criterion")
        covered.add(criterion_id)
        if item.get("targets_falsification") is not True:
            raise ValueError("every anti-confirmation test must explicitly target falsification")
        outcome = str(item.get("outcome") or "").strip().lower()
        if outcome not in _ALLOWED_OUTCOMES:
            raise ValueError("anti-confirmation test outcome is invalid")
        team_id = _safe_id(item["performed_by_team_id"], "performed_by_team_id")
        runner_id = _safe_id(item["performed_by_runner_id"], "performed_by_runner_id")
        if team_id != validator["team_id"] or runner_id != validator["runner_id"]:
            raise ValueError("anti-confirmation test was not performed by independent validator")
        evidence_hash = _safe_sha(item["evidence_hash"], "evidence_hash")
        if evidence_hash in seen_evidence:
            raise ValueError("anti-confirmation evidence_hash must be unique per test")
        seen_evidence.add(evidence_hash)
        rows.append({
            "test_id": test_id,
            "criterion_id": criterion_id,
            "method_hash": _safe_sha(item["method_hash"], "method_hash"),
            "evidence_hash": evidence_hash,
            "targets_falsification": True,
            "outcome": outcome,
            "performed_by_team_id": team_id,
            "performed_by_runner_id": runner_id,
        })
    if len(covered) < _MIN_CRITERIA:
        raise ValueError("anti-confirmation tests must cover at least two falsification criteria")
    return tuple(rows)


@dataclass(frozen=True)
class AntiConfirmationCampaignReceipt:
    revision: str
    created_at_epoch: int
    campaign_id: str
    campaign_sha256: str
    receipt_sha256: str
    test_count: int
    criterion_count: int
    conclusion: str


@dataclass(frozen=True)
class AntiConfirmationAttestation:
    revision: str
    campaign_sha256: str
    receipt_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    truth_proven: bool = False


def validate_anti_confirmation_campaign(
    path: str | os.PathLike[str],
    *,
    expected_revision: str,
    now: float,
) -> AntiConfirmationCampaignReceipt:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    revision = str(expected_revision or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(revision):
        raise ValueError("expected_revision must be a full lowercase Git SHA")

    value, data = _read_bounded_json(Path(path).expanduser().resolve())
    required = {
        "schema_version",
        "created_at_epoch",
        "implementation_revision",
        "campaign_id",
        "hypothesis_id",
        "hypothesis_hash",
        "protocol_hash",
        "search_space_hash",
        "stopping_rule_hash",
        "originator",
        "independent_validator",
        "falsification_criteria",
        "tests",
        "negative_evidence_search_completed",
        "null_results_recorded",
        "conclusion",
        "truth_proven",
        "campaign_hash",
    }
    if set(value) != required:
        raise ValueError("anti-confirmation campaign top-level schema is invalid")
    if value.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported anti-confirmation campaign schema_version")
    created = value.get("created_at_epoch")
    if type(created) is not int or created <= 0:
        raise ValueError("anti-confirmation campaign created_at_epoch is invalid")
    if created > current_time + _MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("anti-confirmation campaign is from the future")
    if current_time - created > _MAX_RECEIPT_AGE_SECONDS:
        raise ValueError("anti-confirmation campaign is stale")
    receipt_revision = str(value.get("implementation_revision") or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(receipt_revision) or receipt_revision != revision:
        raise ValueError("anti-confirmation campaign revision does not match current Git HEAD")

    _safe_id(value["campaign_id"], "campaign_id")
    _safe_id(value["hypothesis_id"], "hypothesis_id")
    _safe_sha(value["hypothesis_hash"], "hypothesis_hash")
    _safe_sha(value["protocol_hash"], "protocol_hash")
    _safe_sha(value["search_space_hash"], "search_space_hash")
    _safe_sha(value["stopping_rule_hash"], "stopping_rule_hash")
    originator = _identity(value["originator"], "originator")
    validator = _identity(value["independent_validator"], "independent_validator")
    _require_independence(originator, validator)
    criteria = _criteria(value["falsification_criteria"])
    tests = _tests(
        value["tests"],
        criterion_ids={item["criterion_id"] for item in criteria},
        validator=validator,
    )
    if value.get("negative_evidence_search_completed") is not True:
        raise ValueError("negative-evidence search must be completed")
    if value.get("null_results_recorded") is not True:
        raise ValueError("null-result recording must be complete")
    conclusion = str(value.get("conclusion") or "").strip().lower()
    if conclusion not in _ALLOWED_CONCLUSIONS:
        raise ValueError("anti-confirmation campaign conclusion is invalid")
    if value.get("truth_proven") is not False:
        raise ValueError("anti-confirmation campaign must not claim truth_proven")

    claimed_hash = _safe_sha(value["campaign_hash"], "campaign_hash")
    payload = {key: item for key, item in value.items() if key != "campaign_hash"}
    actual_hash = _sha(_canonical(payload))
    if claimed_hash != actual_hash:
        raise ValueError("anti-confirmation campaign_hash verification failed")

    return AntiConfirmationCampaignReceipt(
        revision=revision,
        created_at_epoch=created,
        campaign_id=str(value["campaign_id"]),
        campaign_sha256=actual_hash,
        receipt_sha256=_sha(data),
        test_count=len(tests),
        criterion_count=len(criteria),
        conclusion=conclusion,
    )


def _policy_rule(policy) -> None:
    allowed = any(
        rule.capability_id == _CAPABILITY_ID
        and rule.proof_kind is ProofKind.INDEPENDENT
        and _SUBJECT in rule.subjects
        and _VERIFIER in rule.verifiers
        and _REFERENCE_PREFIX in rule.reference_prefixes
        for rule in policy.rules
    )
    if not allowed:
        raise ValueError("committed proof policy does not authorize anti-confirmation independent validation")


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


def attest_anti_confirmation_independence(
    *,
    repo_root: str | os.PathLike[str],
    campaign_path: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> AntiConfirmationAttestation:
    """Mint exactly one capability-140 INDEPENDENT proof from external evidence."""
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "").strip().lower()
    if (
        not identity_before.get("available")
        or not identity_before.get("clean")
        or not _GIT_SHA_RE.fullmatch(revision)
    ):
        raise ValueError("anti-confirmation attestation requires a clean Git checkout")

    receipt = validate_anti_confirmation_campaign(
        campaign_path,
        expected_revision=revision,
        now=current_time,
    )
    tracked = _tracked_index(root)
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    _policy_rule(policy)

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

    reference = _REFERENCE_PREFIX + receipt.campaign_sha256
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    receipt_id = f"anti-confirmation:c140:{receipt.receipt_sha256[:16]}"
    previous = existing.get(receipt_id)
    added = reused = 0
    if previous is not None:
        if not _same_receipt(
            previous,
            digest=receipt.receipt_sha256,
            reference=reference,
            revision=revision,
        ):
            raise ValueError("deterministic anti-confirmation receipt_id collision")
        reused = 1
    else:
        ledger.add(
            receipt_id=receipt_id,
            capability_id=_CAPABILITY_ID,
            proof_kind=ProofKind.INDEPENDENT,
            subject=_SUBJECT,
            subject_sha256=receipt.receipt_sha256,
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
        raise ValueError("trusted maturity audit rejected anti-confirmation attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "").strip().lower() != revision
    ):
        raise ValueError("repository changed during anti-confirmation attestation")

    return AntiConfirmationAttestation(
        revision=revision,
        campaign_sha256=receipt.campaign_sha256,
        receipt_sha256=receipt.receipt_sha256,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
