"""Trusted deterministic execution attestor for capability #109 Data Forensics.

The core auditor reports structural/statistical anomalies and deliberately keeps
``fraud_proven=False``.  This attestor executes a locked corpus twice on the
exact clean repository revision, verifies deterministic report hashes, and may
mint only EXECUTION and REPRODUCIBILITY proof receipts.  It does not infer
malicious intent, provenance truth, or real-world fraud from anomalies.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from utils.release_identity import repository_identity

from .capability_registry import ProofKind
from .data_forensics import ColumnRule, audit_rows
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


_CAPABILITY_ID = 109
_REQUIRED = (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY)
_SUBJECT = "data-forensics-benchmark"
_VERIFIER = "trusted-operator"
_PREFIX = "data-forensics:"
_ENGINE_SUBJECT = "research_engine/data_forensics.py"
_BENCHMARK_VERSION = "data-forensics-benchmark-v1"


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


def _report(report) -> Mapping[str, Any]:
    return asdict(report)


def _codes(report) -> set[str]:
    return {issue.code for issue in report.issues}


def run_data_forensics_benchmark() -> Mapping[str, Any]:
    """Execute a fixed corpus covering clean, corrupt and suspicious tables."""
    clean_rules = (
        ColumnRule("id", kind="numeric", required=True, monotonic_increasing=True),
        ColumnRule("value", kind="numeric", required=True, minimum=0, maximum=100),
        ColumnRule("time", kind="timestamp", required=True, monotonic_increasing=True),
    )
    clean = audit_rows(
        [
            {"id": 1, "value": 10.0, "time": "2026-01-01T00:00:00+00:00"},
            {"id": 2, "value": 11.0, "time": "2026-01-01T00:01:00+00:00"},
            {"id": 3, "value": 12.0, "time": "2026-01-01T00:02:00+00:00"},
        ],
        clean_rules,
        primary_key="id",
    )

    conflicting = audit_rows(
        [
            {"id": "a", "value": 1.0},
            {"id": "a", "value": 2.0},
        ],
        (ColumnRule("value", kind="numeric", required=True),),
        primary_key="id",
    )

    invalid_numeric = audit_rows(
        [
            {"id": 1, "value": 1.0},
            {"id": 2, "value": float("nan")},
            {"id": 3, "value": float("inf")},
        ],
        (ColumnRule("value", kind="numeric", required=True),),
        primary_key="id",
    )

    temporal = audit_rows(
        [
            {"id": 1, "time": "2026-01-01T00:02:00+00:00"},
            {"id": 2, "time": "2026-01-01T00:01:00+00:00"},
        ],
        (ColumnRule("time", kind="timestamp", required=True, monotonic_increasing=True),),
        primary_key="id",
    )

    warning_only = audit_rows(
        [
            {"id": 1, "value": 1.0},
            {"id": 2, "value": 1.1},
            {"id": 3, "value": 0.9},
            {"id": 4, "value": 1.0},
            {"id": 5, "value": 1.2},
            {"id": 6, "value": 0.8},
            {"id": 7, "value": 50.0},
        ],
        (ColumnRule("value", kind="numeric", required=True, robust_outlier_z=6.0),),
        primary_key="id",
    )

    duplicate = audit_rows(
        [
            {"id": 1, "value": 4.0},
            {"id": 1, "value": 4.0},
        ],
        (ColumnRule("value", kind="numeric", required=True),),
        primary_key="id",
    )

    reports = {
        "clean": _report(clean),
        "conflicting_primary_key": _report(conflicting),
        "invalid_numeric": _report(invalid_numeric),
        "temporal_reversal": _report(temporal),
        "warning_only_outlier": _report(warning_only),
        "duplicate_row": _report(duplicate),
    }
    checks = {
        "clean_table_passes_without_issues": (
            clean.passed is True
            and clean.critical_count == 0
            and clean.warning_count == 0
            and not clean.issues
        ),
        "conflicting_primary_key_is_critical": (
            "conflicting_primary_key" in _codes(conflicting)
            and conflicting.passed is False
            and conflicting.critical_count >= 1
        ),
        "nonfinite_measurements_fail_closed": (
            "nonfinite_numeric" in _codes(invalid_numeric)
            and invalid_numeric.passed is False
        ),
        "temporal_order_reversal_is_detected": (
            "order_reversal" in _codes(temporal)
            and temporal.passed is False
        ),
        "robust_outlier_is_warning_not_fraud": (
            "robust_outlier" in _codes(warning_only)
            and warning_only.passed is True
            and warning_only.warning_count >= 1
        ),
        "duplicate_row_is_preserved_as_warning": (
            "duplicate_row" in _codes(duplicate)
            and "duplicate_primary_key" in _codes(duplicate)
            and duplicate.passed is True
        ),
        "no_report_claims_fraud_proven": all(
            report.fraud_proven is False
            for report in (
                clean,
                conflicting,
                invalid_numeric,
                temporal,
                warning_only,
                duplicate,
            )
        ),
        "content_hashes_are_present_and_distinct": (
            all(len(report.dataset_sha256) == 64 for report in (
                clean,
                conflicting,
                invalid_numeric,
                temporal,
                warning_only,
                duplicate,
            ))
            and len({
                report.dataset_sha256 for report in (
                    clean,
                    conflicting,
                    invalid_numeric,
                    temporal,
                    warning_only,
                    duplicate,
                )
            }) == 6
        ),
    }
    payload = {
        "benchmark_version": _BENCHMARK_VERSION,
        "checks": checks,
        "reports": reports,
        "locked_structured_tabular_corpus": True,
        "external_dataset_provenance_verified": False,
        "malicious_intent_inferred": False,
        "fraud_proven": False,
        "truth_proven": False,
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


@dataclass(frozen=True)
class DataForensicsExecutionAttestation:
    revision: str
    engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    external_dataset_provenance_verified: bool = False
    malicious_intent_inferred: bool = False
    fraud_proven: bool = False
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


def attest_data_forensics_execution(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> DataForensicsExecutionAttestation:
    """Mint only EXECUTION/REPRODUCIBILITY receipts for capability #109."""
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    reference = _safe_reference(run_reference)
    root = Path(repo_root).resolve(strict=True)
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "")
    if not identity_before.get("available") or not identity_before.get("clean") or not revision:
        raise ValueError("data-forensics attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _ENGINE_SUBJECT)
    import research_engine.data_forensics as loaded_forensics
    if Path(str(loaded_forensics.__file__)).resolve(strict=True) != (root / _ENGINE_SUBJECT).resolve(strict=True):
        raise ValueError("data-forensics runtime is not loaded from the audited repository")

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
            raise ValueError(
                f"committed policy has no data-forensics {kind.value} rule"
            )
        if not any(
            not rule.reference_prefixes
            or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
            for rule in matching
        ):
            raise ValueError("run_reference is not allowed by data-forensics proof policy")

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

    first = run_data_forensics_benchmark()
    second = run_data_forensics_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("data-forensics benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("data-forensics benchmark is not deterministic")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    digest_payload = {
        key: value for key, value in first.items()
        if key not in {"benchmark_passed", "benchmark_sha256"}
    }
    if len(benchmark_digest) != 64 or benchmark_digest != _sha(digest_payload):
        raise ValueError("data-forensics benchmark digest verification failed")

    receipt_digest = _sha({
        "revision": revision,
        "engine_sha256": engine_digest,
        "benchmark_sha256": benchmark_digest,
        "subject": _SUBJECT,
        "capability_id": _CAPABILITY_ID,
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0

    # Preflight both routes before mutating the append-only ledger.
    pending = []
    for kind in _REQUIRED:
        receipt_id = f"data-forensics:{revision[:12]}:c109:{kind.value}"
        previous = existing.get(receipt_id)
        if previous is not None:
            if not _same_receipt(
                previous,
                kind=kind,
                digest=receipt_digest,
                reference=reference,
                revision=revision,
            ):
                raise ValueError("deterministic data-forensics receipt_id collision")
            reused += 1
            continue
        pending.append((receipt_id, kind))

    for receipt_id, kind in pending:
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
        raise ValueError("trusted maturity audit rejected data-forensics attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during data-forensics attestation")

    return DataForensicsExecutionAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        benchmark_sha256=benchmark_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
