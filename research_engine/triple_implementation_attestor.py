"""Trusted attestation for capability #40 triple-implementation execution evidence.

A caller-supplied report is not trusted merely because it says
``triple_confirmed``. This attestor binds the report to an exact clean Git
revision, hashes all three tracked implementation subjects itself, recomputes
manifest/result/report hashes and every pairwise tolerance check, then mints
only the policy-approved EXECUTION, INDEPENDENT and REPRODUCIBILITY proofs into
an HMAC-protected proof ledger.

The HMAC key must come from a protected operator environment. This module does
not turn ordinary pull-request CI into independent validation and it does not
claim that cross-implementation agreement proves the underlying scientific
claim true.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from utils.release_identity import repository_identity

from .capability_registry import ProofKind
from .maturity_auditor import (
    TrustedMaturityAudit,
    _hash_tracked_regular,
    _parse_policy,
    _read_policy_bytes,
    _safe_repo_path,
    _tracked_index,
    audit_repository_maturity,
)
from .maturity_proof import ProofLedger


_CAPABILITY_ID = 40
_SCHEMA_VERSION = 1
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024
_MAX_RECEIPT_AGE_SECONDS = 2 * 60 * 60
_MAX_FUTURE_SKEW_SECONDS = 5 * 60
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_SUBJECT = "triple-implementation-run"
_VERIFIER = "trusted-operator"
_REFERENCE_PREFIX = "triple-implementation:"
_REQUIRED_PROOFS: Tuple[ProofKind, ...] = (
    ProofKind.EXECUTION,
    ProofKind.INDEPENDENT,
    ProofKind.REPRODUCIBILITY,
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
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


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _read_bounded_json(path: Path) -> tuple[Mapping[str, Any], bytes]:
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError("triple implementation receipt cannot be read") from exc
    if not path.is_file() or info.st_size < 1 or info.st_size > _MAX_RECEIPT_BYTES:
        raise ValueError("triple implementation receipt size is invalid")
    data = path.read_bytes()
    if len(data) != info.st_size or len(data) > _MAX_RECEIPT_BYTES:
        raise ValueError("triple implementation receipt changed during read")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("triple implementation receipt is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("triple implementation receipt must be a JSON object")
    return value, data


@dataclass(frozen=True)
class TripleExecutionReceipt:
    revision: str
    created_at_epoch: int
    sha256: str
    report_hash: str
    manifest_hash: str
    implementation_subjects: Tuple[str, ...]


@dataclass(frozen=True)
class TripleProofAttestation:
    revision: str
    execution_receipt_sha256: str
    report_hash: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit


def _validate_implementations(
    raw: object,
    *,
    root: Path,
    tracked: Mapping[str, str],
) -> Tuple[Tuple[Dict[str, str], ...], str]:
    if not isinstance(raw, list) or len(raw) != 3:
        raise ValueError("receipt must bind exactly three implementations")
    rows = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) != {
            "implementation_id",
            "runner_id",
            "implementation_family",
            "subject",
            "code_digest",
        }:
            raise ValueError(f"implementation {index} schema is invalid")
        implementation_id = _safe_id(item["implementation_id"], "implementation_id")
        runner_id = _safe_id(item["runner_id"], "runner_id")
        family = _safe_id(item["implementation_family"], "implementation_family")
        subject = _safe_repo_path(item["subject"], field="implementation subject")
        claimed_digest = _safe_sha(item["code_digest"], "code_digest")
        actual_digest = _hash_tracked_regular(root, tracked, subject)
        if claimed_digest != actual_digest:
            raise ValueError(
                f"implementation {implementation_id} code_digest does not match tracked file"
            )
        rows.append({
            "implementation_id": implementation_id,
            "runner_id": runner_id,
            "implementation_family": family,
            "subject": subject,
            "code_digest": actual_digest,
        })

    for field in (
        "implementation_id",
        "runner_id",
        "implementation_family",
        "subject",
        "code_digest",
    ):
        values = [row[field] for row in rows]
        if len(set(values)) != 3:
            raise ValueError(f"{field} values must be distinct across all three implementations")

    rows.sort(key=lambda row: row["implementation_id"])
    manifest_payload = [
        {
            "implementation_id": row["implementation_id"],
            "runner_id": row["runner_id"],
            "implementation_family": row["implementation_family"],
            "code_digest": row["code_digest"],
        }
        for row in rows
    ]
    return tuple(rows), _sha(_canonical(manifest_payload))


def _validate_report(
    report: object,
    implementations: Sequence[Mapping[str, str]],
    manifest_hash: str,
) -> str:
    if not isinstance(report, dict) or set(report) != {
        "protocol_hash",
        "manifest_hash",
        "results",
        "comparisons",
        "triple_confirmed",
        "execution_complete",
        "independence_structure_satisfied",
        "truth_proven",
        "agreement_is_not_truth",
        "reasons",
        "report_hash",
    }:
        raise ValueError("triple implementation report schema is invalid")

    protocol_hash = _safe_sha(report["protocol_hash"], "protocol_hash")
    if _safe_sha(report["manifest_hash"], "manifest_hash") != manifest_hash:
        raise ValueError("report manifest_hash does not match tracked implementations")
    claimed_report_hash = _safe_sha(report["report_hash"], "report_hash")

    if report.get("triple_confirmed") is not True:
        raise ValueError("triple implementation report is not confirmed")
    if report.get("execution_complete") is not True:
        raise ValueError("triple implementation execution is incomplete")
    if report.get("independence_structure_satisfied") is not True:
        raise ValueError("triple implementation independence structure did not pass")
    if report.get("truth_proven") is not False:
        raise ValueError("triple implementation report must not claim truth_proven")
    if report.get("agreement_is_not_truth") is not True:
        raise ValueError(
            "triple implementation report must preserve agreement-is-not-truth boundary"
        )
    if report.get("reasons") != []:
        raise ValueError("confirmed triple implementation report must have no blocking reasons")

    expected_by_id = {row["implementation_id"]: row for row in implementations}
    results_raw = report.get("results")
    if not isinstance(results_raw, list) or len(results_raw) != 3:
        raise ValueError("report must contain exactly three implementation results")

    metrics_by_id: Dict[str, Dict[str, float]] = {}
    seen_ids = set()
    for index, item in enumerate(results_raw):
        if not isinstance(item, dict) or set(item) != {
            "implementation_id",
            "runner_id",
            "implementation_family",
            "code_digest",
            "protocol_hash",
            "metrics",
            "result_hash",
            "error",
        }:
            raise ValueError(f"result {index} schema is invalid")
        implementation_id = _safe_id(
            item["implementation_id"], "result implementation_id"
        )
        if implementation_id in seen_ids or implementation_id not in expected_by_id:
            raise ValueError("report result implementation identities are invalid")
        seen_ids.add(implementation_id)
        expected = expected_by_id[implementation_id]
        if str(item.get("runner_id") or "").strip() != expected["runner_id"]:
            raise ValueError("report runner_id does not match tracked manifest")
        if (
            str(item.get("implementation_family") or "").strip()
            != expected["implementation_family"]
        ):
            raise ValueError("report implementation_family does not match tracked manifest")
        if (
            _safe_sha(item.get("code_digest"), "result code_digest")
            != expected["code_digest"]
        ):
            raise ValueError("report code_digest does not match tracked manifest")
        if _safe_sha(item.get("protocol_hash"), "result protocol_hash") != protocol_hash:
            raise ValueError("result protocol_hash mismatch")
        if item.get("error") != "":
            raise ValueError("confirmed report contains an implementation error")

        metrics_raw = item.get("metrics")
        if (
            not isinstance(metrics_raw, dict)
            or not metrics_raw
            or len(metrics_raw) > 1_000
        ):
            raise ValueError("result metrics must be a bounded non-empty object")
        metrics: Dict[str, float] = {}
        for raw_name, raw_value in metrics_raw.items():
            if (
                not isinstance(raw_name, str)
                or not raw_name.strip()
                or len(raw_name) > 200
            ):
                raise ValueError("metric name is invalid")
            name = raw_name.strip()
            if name in metrics:
                raise ValueError("duplicate normalized metric name")
            metrics[name] = _finite_number(raw_value, f"metric {name}")
        metrics = dict(sorted(metrics.items()))

        result_payload = {
            "implementation_id": implementation_id,
            "runner_id": expected["runner_id"],
            "implementation_family": expected["implementation_family"],
            "code_digest": expected["code_digest"],
            "protocol_hash": protocol_hash,
            "metrics": metrics,
        }
        if (
            _safe_sha(item.get("result_hash"), "result_hash")
            != _sha(_canonical(result_payload))
        ):
            raise ValueError("result_hash verification failed")
        metrics_by_id[implementation_id] = metrics

    if set(seen_ids) != set(expected_by_id):
        raise ValueError("report is missing an implementation result")
    metric_sets = {tuple(metrics) for metrics in metrics_by_id.values()}
    if len(metric_sets) != 1:
        raise ValueError("all three implementations must report the same metric set")
    metric_names = next(iter(metric_sets))

    comparisons_raw = report.get("comparisons")
    expected_keys = {
        (left, right, metric)
        for left, right in combinations(sorted(expected_by_id), 2)
        for metric in metric_names
    }
    if (
        not isinstance(comparisons_raw, list)
        or len(comparisons_raw) != len(expected_keys)
    ):
        raise ValueError("report does not contain every all-pairs metric comparison")
    seen_comparisons = set()
    for index, item in enumerate(comparisons_raw):
        if not isinstance(item, dict) or set(item) != {
            "left_id",
            "right_id",
            "metric",
            "left_value",
            "right_value",
            "tolerance",
            "absolute_delta",
            "passed",
        }:
            raise ValueError(f"comparison {index} schema is invalid")
        left = _safe_id(item["left_id"], "comparison left_id")
        right = _safe_id(item["right_id"], "comparison right_id")
        metric = str(item.get("metric") or "").strip()
        if (
            left == right
            or left not in expected_by_id
            or right not in expected_by_id
            or metric not in metric_names
        ):
            raise ValueError("comparison identity or metric is invalid")
        canonical_pair = tuple(sorted((left, right)))
        key = (canonical_pair[0], canonical_pair[1], metric)
        if key in seen_comparisons:
            raise ValueError("duplicate pairwise metric comparison")
        seen_comparisons.add(key)

        left_value = _finite_number(item.get("left_value"), "comparison left_value")
        right_value = _finite_number(item.get("right_value"), "comparison right_value")
        if (
            left_value != metrics_by_id[left][metric]
            or right_value != metrics_by_id[right][metric]
        ):
            raise ValueError("comparison values do not match implementation metrics")
        tolerance = _finite_number(item.get("tolerance"), "comparison tolerance")
        if tolerance < 0.0:
            raise ValueError("comparison tolerance must be non-negative")
        delta = _finite_number(
            item.get("absolute_delta"), "comparison absolute_delta"
        )
        expected_delta = abs(left_value - right_value)
        if not math.isclose(
            delta, expected_delta, rel_tol=1e-12, abs_tol=1e-15
        ):
            raise ValueError("comparison absolute_delta is inconsistent")
        passed = expected_delta <= tolerance or math.isclose(
            expected_delta, tolerance, rel_tol=1e-12, abs_tol=1e-15
        )
        if item.get("passed") is not True or not passed:
            raise ValueError("comparison did not genuinely pass tolerance")

    if seen_comparisons != expected_keys:
        raise ValueError("report all-pairs comparison coverage is incomplete")

    report_payload = {
        key: value for key, value in report.items() if key != "report_hash"
    }
    if _sha(_canonical(report_payload)) != claimed_report_hash:
        raise ValueError("report_hash verification failed")
    return claimed_report_hash


def validate_triple_execution_receipt(
    path: str | os.PathLike[str],
    *,
    repo_root: str | os.PathLike[str],
    expected_revision: str,
    now: float,
) -> TripleExecutionReceipt:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    revision = str(expected_revision or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(revision):
        raise ValueError("expected_revision must be a full lowercase Git SHA")

    root = Path(repo_root).resolve(strict=True)
    tracked = _tracked_index(root)
    value, data = _read_bounded_json(Path(path).expanduser().resolve())
    if set(value) != {
        "schema_version",
        "created_at_epoch",
        "implementation_revision",
        "implementations",
        "report",
    }:
        raise ValueError("triple implementation receipt top-level schema is invalid")
    if value.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported triple implementation receipt schema_version")
    created = value.get("created_at_epoch")
    if type(created) is not int or created <= 0:
        raise ValueError("triple implementation receipt created_at_epoch is invalid")
    if created > current_time + _MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("triple implementation receipt is from the future")
    if current_time - created > _MAX_RECEIPT_AGE_SECONDS:
        raise ValueError("triple implementation receipt is stale")
    receipt_revision = str(value.get("implementation_revision") or "").strip().lower()
    if (
        not _GIT_SHA_RE.fullmatch(receipt_revision)
        or receipt_revision != revision
    ):
        raise ValueError(
            "triple implementation receipt revision does not match current Git HEAD"
        )

    implementations, manifest_hash = _validate_implementations(
        value.get("implementations"), root=root, tracked=tracked
    )
    report_hash = _validate_report(
        value.get("report"), implementations, manifest_hash
    )
    return TripleExecutionReceipt(
        revision=revision,
        created_at_epoch=created,
        sha256=_sha(data),
        report_hash=report_hash,
        manifest_hash=manifest_hash,
        implementation_subjects=tuple(
            row["subject"] for row in implementations
        ),
    )


def _outside_repo(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return False
    except ValueError:
        return True


def _required_policy_rules(policy) -> None:
    for kind in _REQUIRED_PROOFS:
        allowed = any(
            rule.capability_id == _CAPABILITY_ID
            and rule.proof_kind == kind
            and _SUBJECT in rule.subjects
            and _VERIFIER in rule.verifiers
            and any(
                prefix == _REFERENCE_PREFIX
                for prefix in rule.reference_prefixes
            )
            for rule in policy.rules
        )
        if not allowed:
            raise ValueError(
                f"committed proof policy does not authorize capability 40 "
                f"{kind.value} attestation"
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
    return all(row.get(key) == value for key, value in expected.items())


def attest_triple_implementation_proofs(
    *,
    repo_root: str | os.PathLike[str],
    execution_receipt_path: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> TripleProofAttestation:
    """Mint only trusted #40 execution/independent/reproducibility proofs."""
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
    if (
        not identity.get("available")
        or not identity.get("clean")
        or not revision
    ):
        raise ValueError(
            "triple implementation attestation requires a clean Git checkout"
        )

    receipt = validate_triple_execution_receipt(
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
            raise ValueError(
                "existing maturity ledger requires prior trusted anchor and revision"
            )
        continuity = ProofLedger(
            str(ledger_target), integrity_key=integrity_key
        )
        if not continuity.verify_chain(
            anchor_token=prior_anchor_token,
            current_revision=prior,
        ):
            raise ValueError(
                "existing maturity ledger failed prior anchor continuity check"
            )
    elif prior_anchor_token or prior_revision:
        raise ValueError(
            "prior anchor/revision supplied for an empty maturity ledger"
        )

    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    reference = _REFERENCE_PREFIX + receipt.report_hash
    added = 0
    reused = 0
    for kind in _REQUIRED_PROOFS:
        receipt_id = f"triple:c40:{kind.value}:{receipt.sha256[:16]}"
        previous = existing.get(receipt_id)
        if previous is not None:
            if not _same_receipt(
                previous,
                kind=kind,
                digest=receipt.sha256,
                reference=reference,
                revision=revision,
            ):
                raise ValueError(
                    "deterministic triple maturity receipt_id collision"
                )
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
    return TripleProofAttestation(
        revision=revision,
        execution_receipt_sha256=receipt.sha256,
        report_hash=receipt.report_hash,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor_token,
        audit=audit,
    )
