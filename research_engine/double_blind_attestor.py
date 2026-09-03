"""Trusted preregistration and proof attestation for capability #98.

Ordinary CI may prove CODE/TEST only. Strong double-blind proof requires two
operator-side phases:

1. Before any evaluator result exists, issue an HMAC protected commitment for
   the sealed study. The token binds Git revision, blind arms, evaluator
   identities/families/implementation hashes, frozen tolerances, instructions
   hash, assignment commitment and seal hash.
2. After reveal, independently revalidate the final report against that earlier
   commitment and the protected assignment key. Only then may the attestor mint
   EXECUTION and INDEPENDENT proofs. REPRODUCIBILITY is minted only when every
   recomputed evaluator-pair/arm/metric comparison genuinely passes.

Agreement remains evidence about reproducibility, never proof of scientific
truth or profitability. The HMAC/proof keys must come from a protected operator
environment; this module does not make ordinary PR CI an independent evaluator.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import os
import re
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from utils.release_identity import repository_identity

from .capability_registry import ProofKind
from .maturity_auditor import (
    TrustedMaturityAudit,
    _parse_policy,
    _read_policy_bytes,
    _tracked_index,
    audit_repository_maturity,
)
from .maturity_proof import ProofLedger


_CAPABILITY_ID = 98
_SCHEMA_VERSION = 1
_SUBJECT = "double-blind-evaluation-run"
_VERIFIER = "trusted-operator"
_REFERENCE_PREFIX = "double-blind:"
_TOKEN_DOMAIN = b"double-blind-preregistration-v1\x00"
_MAX_TOKEN_AGE_SECONDS = 24 * 60 * 60
_MAX_FUTURE_SKEW_SECONDS = 5 * 60
_MAX_ARMS = 32
_MAX_EVALUATORS = 16
_MAX_METRICS = 256
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_REQUIRED_POLICY_PROOFS: Tuple[ProofKind, ...] = (
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
    ).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_ID_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _safe_sha(value: object, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return text


def _strong_key(value: bytes, field: str) -> bytes:
    if not isinstance(value, bytes) or len(value) < 32:
        raise ValueError(f"{field} must contain at least 32 bytes")
    return value


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(text: str, field: str) -> bytes:
    if not isinstance(text, str) or not text or len(text) > 1_000_000:
        raise ValueError(f"{field} is invalid")
    try:
        raw = base64.b64decode(
            text + "=" * ((4 - len(text) % 4) % 4),
            altchars=b"-_",
            validate=True,
        )
    except Exception as exc:
        raise ValueError(f"{field} is not canonical base64url") from exc
    if _b64encode(raw) != text:
        raise ValueError(f"{field} is not canonical base64url")
    return raw


def _clean_revision(repo_root: Path) -> str:
    identity = repository_identity(repo_root)
    revision = str(identity.get("revision") or "").strip().lower()
    if (
        not identity.get("available")
        or not identity.get("clean")
        or not _GIT_SHA_RE.fullmatch(revision)
    ):
        raise ValueError("double-blind attestation requires a clean Git checkout")
    return revision


def _arm_id(
    assignment_key: bytes,
    *,
    study_id: str,
    protocol_hash: str,
    candidate_id: str,
    artifact_digest: str,
) -> str:
    body = (
        b"double-blind-arm-v1\x00"
        + study_id.encode("utf-8")
        + b"\x00"
        + protocol_hash.encode("ascii")
        + b"\x00"
        + candidate_id.encode("utf-8")
        + b"\x00"
        + artifact_digest.encode("ascii")
    )
    return "arm_" + hmac.new(
        assignment_key, body, hashlib.sha256
    ).hexdigest()[:32]


def _assignment_commitment(assignment_key: bytes) -> str:
    return _sha(b"double-blind-assignment-key-v1\x00" + assignment_key)


def _token(body: Mapping[str, Any], integrity_key: bytes) -> str:
    encoded = _b64encode(_canonical(body))
    mac = hmac.new(
        integrity_key,
        _TOKEN_DOMAIN + encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return encoded + "." + _b64encode(mac)


def _decode_token(token: str, integrity_key: bytes) -> Mapping[str, Any]:
    if not isinstance(token, str) or token.count(".") != 1:
        raise ValueError("preregistration token is malformed")
    body_text, mac_text = token.split(".", 1)
    body_raw = _b64decode(body_text, "preregistration body")
    mac = _b64decode(mac_text, "preregistration MAC")
    expected = hmac.new(
        integrity_key,
        _TOKEN_DOMAIN + body_text.encode("ascii"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("preregistration token MAC verification failed")
    try:
        value = json.loads(body_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("preregistration body is not UTF-8 JSON") from exc
    if not isinstance(value, dict) or _canonical(value) != body_raw:
        raise ValueError("preregistration body is not canonical JSON")
    return value


@dataclass(frozen=True)
class DoubleBlindProtocolCommitment:
    token: str
    revision: str
    study_id: str
    protocol_hash: str
    seal_hash: str
    issued_at_epoch: int


@dataclass(frozen=True)
class DoubleBlindProofAttestation:
    revision: str
    report_hash: str
    reproducibility_satisfied: bool
    proofs_minted: Tuple[ProofKind, ...]
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit


def issue_double_blind_protocol_commitment(
    *,
    study: Any,
    repo_root: str | os.PathLike[str],
    integrity_key: bytes,
    now: float,
) -> DoubleBlindProtocolCommitment:
    """Commit a sealed study before the first evaluator result is accepted."""
    key = _strong_key(integrity_key, "integrity_key")
    current_time = _finite(now, "now")
    issued = int(current_time)
    if issued <= 0:
        raise ValueError("now must be positive")
    root = Path(repo_root).resolve(strict=True)
    revision = _clean_revision(root)

    view = study.builder_view()
    if view.get("sealed") is not True or view.get("revealed") is not False:
        raise ValueError("study must be sealed and unrevealed before preregistration")
    if int(view.get("completed_results") or 0) != 0:
        raise ValueError("preregistration must occur before any evaluator result")

    study_id = _safe_id(getattr(study, "study_id", ""), "study_id")
    protocol_hash = _safe_sha(
        getattr(study, "protocol_hash", ""), "protocol_hash"
    )
    seal_hash = _safe_sha(getattr(study, "_seal_hash", ""), "seal_hash")
    assignment_commitment = _safe_sha(
        getattr(study, "assignment_commitment", ""), "assignment_commitment"
    )

    candidates = list(getattr(study, "_candidates", {}).values())
    evaluators = list(getattr(study, "_evaluators", {}).values())
    tolerances = dict(getattr(study, "_tolerances", {}))
    instructions = dict(getattr(study, "_instructions", {}))
    if not (2 <= len(candidates) <= _MAX_ARMS):
        raise ValueError("preregistered study candidate count is invalid")
    if not (2 <= len(evaluators) <= _MAX_EVALUATORS):
        raise ValueError("preregistered study evaluator count is invalid")
    if not tolerances or len(tolerances) > _MAX_METRICS:
        raise ValueError("preregistered metric tolerance set is invalid")

    arm_rows = []
    for row in candidates:
        arm_rows.append({
            "arm_id": _safe_id(row.get("arm_id"), "arm_id"),
            "artifact_digest": _safe_sha(
                row.get("artifact_digest"), "artifact_digest"
            ),
        })
    evaluator_rows = []
    for row in evaluators:
        evaluator_rows.append({
            "evaluator_id": _safe_id(row.get("evaluator_id"), "evaluator_id"),
            "evaluator_family": _safe_id(
                row.get("evaluator_family"), "evaluator_family"
            ),
            "evaluator_implementation_hash": _safe_sha(
                row.get("evaluator_implementation_hash"),
                "evaluator_implementation_hash",
            ),
        })
    for field in (
        "evaluator_id",
        "evaluator_family",
        "evaluator_implementation_hash",
    ):
        values = [row[field] for row in evaluator_rows]
        if len(set(values)) != len(values):
            raise ValueError(f"{field} must be distinct at preregistration")

    clean_tolerances: Dict[str, float] = {}
    for name, value in tolerances.items():
        metric = _safe_id(name, "metric name")
        number = _finite(value, f"tolerance {metric}")
        if number < 0:
            raise ValueError("metric tolerance must be non-negative")
        clean_tolerances[metric] = number
    clean_tolerances = dict(sorted(clean_tolerances.items()))
    instructions_hash = _sha(_canonical(instructions))

    seal_payload = {
        "study_id": study_id,
        "protocol_hash": protocol_hash,
        "assignment_commitment": assignment_commitment,
        "arms": sorted(arm_rows, key=lambda row: row["arm_id"]),
        "evaluators": sorted(
            evaluator_rows, key=lambda row: row["evaluator_id"]
        ),
        "metric_tolerances": clean_tolerances,
        "instructions_hash": instructions_hash,
    }
    if _sha(_canonical(seal_payload)) != seal_hash:
        raise ValueError("study seal_hash does not match frozen preregistration state")

    body = {
        "schema_version": _SCHEMA_VERSION,
        "issued_at_epoch": issued,
        "implementation_revision": revision,
        "study_id": study_id,
        "protocol_hash": protocol_hash,
        "assignment_commitment": assignment_commitment,
        "seal_hash": seal_hash,
        "arms": seal_payload["arms"],
        "evaluators": seal_payload["evaluators"],
        "metric_tolerances": clean_tolerances,
        "instructions_hash": instructions_hash,
    }
    return DoubleBlindProtocolCommitment(
        token=_token(body, key),
        revision=revision,
        study_id=study_id,
        protocol_hash=protocol_hash,
        seal_hash=seal_hash,
        issued_at_epoch=issued,
    )


def _validate_commitment(
    *,
    token: str,
    integrity_key: bytes,
    assignment_key: bytes,
    revision: str,
    now: float,
) -> Mapping[str, Any]:
    body = _decode_token(token, integrity_key)
    expected_keys = {
        "schema_version", "issued_at_epoch", "implementation_revision",
        "study_id", "protocol_hash", "assignment_commitment", "seal_hash",
        "arms", "evaluators", "metric_tolerances", "instructions_hash",
    }
    if set(body) != expected_keys or body.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("preregistration token schema is invalid")
    issued = body.get("issued_at_epoch")
    if type(issued) is not int or issued <= 0:
        raise ValueError("preregistration issued_at_epoch is invalid")
    current = _finite(now, "now")
    if issued > current + _MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("preregistration token is from the future")
    if current - issued > _MAX_TOKEN_AGE_SECONDS:
        raise ValueError("preregistration token is stale")
    if str(body.get("implementation_revision") or "") != revision:
        raise ValueError("preregistration revision does not match current Git HEAD")
    key = _strong_key(assignment_key, "assignment_key")
    if _safe_sha(body.get("assignment_commitment"), "assignment_commitment") != _assignment_commitment(key):
        raise ValueError("assignment_key does not match preregistration commitment")
    return body


def _report_dict(report: Any) -> Mapping[str, Any]:
    value = report.to_dict() if hasattr(report, "to_dict") else report
    if not isinstance(value, Mapping):
        raise ValueError("double-blind report must be a mapping or to_dict object")
    return dict(value)


def _validate_report(
    report_value: Mapping[str, Any],
    commitment: Mapping[str, Any],
    assignment_key: bytes,
) -> tuple[str, bool]:
    expected_top = {
        "study_id", "protocol_hash", "assignment_commitment", "candidates",
        "evaluators", "results", "comparisons", "execution_complete",
        "blinding_structure_satisfied", "independence_structure_satisfied",
        "reproducibility_satisfied", "truth_proven", "profitability_proven",
        "report_hash",
    }
    if set(report_value) != expected_top:
        raise ValueError("double-blind report schema is invalid")
    study_id = _safe_id(report_value["study_id"], "study_id")
    protocol_hash = _safe_sha(report_value["protocol_hash"], "protocol_hash")
    if study_id != commitment["study_id"] or protocol_hash != commitment["protocol_hash"]:
        raise ValueError("report study/protocol does not match preregistration")
    if report_value.get("execution_complete") is not True:
        raise ValueError("double-blind execution is incomplete")
    if report_value.get("blinding_structure_satisfied") is not True:
        raise ValueError("double-blind structure did not pass")
    if report_value.get("independence_structure_satisfied") is not True:
        raise ValueError("double-blind evaluator independence structure did not pass")
    if report_value.get("truth_proven") is not False:
        raise ValueError("double-blind report must not claim truth_proven")
    if report_value.get("profitability_proven") is not False:
        raise ValueError("double-blind report must not claim profitability_proven")
    if _safe_sha(report_value["assignment_commitment"], "assignment_commitment") != commitment["assignment_commitment"]:
        raise ValueError("report assignment commitment mismatch")

    arms_by_id = {
        _safe_id(row["arm_id"], "committed arm_id"): _safe_sha(
            row["artifact_digest"], "committed artifact_digest"
        )
        for row in commitment["arms"]
    }
    candidates = report_value.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != len(arms_by_id):
        raise ValueError("report candidate set does not match preregistered arms")
    seen_arms = set()
    for row in candidates:
        if not isinstance(row, Mapping) or set(row) != {
            "candidate_id", "arm_id", "artifact_digest", "theory_hash"
        }:
            raise ValueError("report candidate schema is invalid")
        candidate_id = _safe_id(row["candidate_id"], "candidate_id")
        arm_id = _safe_id(row["arm_id"], "arm_id")
        artifact = _safe_sha(row["artifact_digest"], "artifact_digest")
        _safe_sha(row["theory_hash"], "theory_hash")
        expected_arm = _arm_id(
            assignment_key,
            study_id=study_id,
            protocol_hash=protocol_hash,
            candidate_id=candidate_id,
            artifact_digest=artifact,
        )
        if arm_id != expected_arm or arms_by_id.get(arm_id) != artifact:
            raise ValueError("candidate blind arm does not match preregistration")
        if arm_id in seen_arms:
            raise ValueError("duplicate report blind arm")
        seen_arms.add(arm_id)
    if seen_arms != set(arms_by_id):
        raise ValueError("report does not cover every preregistered blind arm")

    committed_evaluators = {
        row["evaluator_id"]: dict(row) for row in commitment["evaluators"]
    }
    evaluators = report_value.get("evaluators")
    if not isinstance(evaluators, list) or len(evaluators) != len(committed_evaluators):
        raise ValueError("report evaluator set does not match preregistration")
    observed_evaluators = {}
    for row in evaluators:
        if not isinstance(row, Mapping) or set(row) != {
            "evaluator_id", "evaluator_family", "evaluator_implementation_hash"
        }:
            raise ValueError("report evaluator schema is invalid")
        eid = _safe_id(row["evaluator_id"], "evaluator_id")
        clean = {
            "evaluator_id": eid,
            "evaluator_family": _safe_id(row["evaluator_family"], "evaluator_family"),
            "evaluator_implementation_hash": _safe_sha(
                row["evaluator_implementation_hash"],
                "evaluator_implementation_hash",
            ),
        }
        if eid in observed_evaluators or clean != committed_evaluators.get(eid):
            raise ValueError("report evaluator identity does not match preregistration")
        observed_evaluators[eid] = clean
    for field in ("evaluator_id", "evaluator_family", "evaluator_implementation_hash"):
        values = [row[field] for row in observed_evaluators.values()]
        if len(set(values)) != len(values):
            raise ValueError(f"report {field} values are not structurally independent")

    tolerances = {
        _safe_id(name, "metric name"): _finite(value, f"tolerance {name}")
        for name, value in commitment["metric_tolerances"].items()
    }
    if any(value < 0 for value in tolerances.values()):
        raise ValueError("committed metric tolerance is negative")
    result_rows = report_value.get("results")
    expected_cells = {
        (eid, arm_id)
        for eid in observed_evaluators
        for arm_id in arms_by_id
    }
    if not isinstance(result_rows, list) or len(result_rows) != len(expected_cells):
        raise ValueError("report does not contain the full evaluator-arm matrix")
    metrics_by_cell: Dict[tuple[str, str], Dict[str, float]] = {}
    for row in result_rows:
        if not isinstance(row, Mapping) or set(row) != {
            "evaluator_id", "arm_id", "metrics", "result_hash"
        }:
            raise ValueError("report result schema is invalid")
        eid = _safe_id(row["evaluator_id"], "result evaluator_id")
        arm_id = _safe_id(row["arm_id"], "result arm_id")
        cell = (eid, arm_id)
        if cell not in expected_cells or cell in metrics_by_cell:
            raise ValueError("report result matrix contains invalid/duplicate cell")
        metrics_raw = row["metrics"]
        if not isinstance(metrics_raw, Mapping) or set(metrics_raw) != set(tolerances):
            raise ValueError("result metrics do not match preregistered metric set")
        metrics = {
            name: _finite(metrics_raw[name], f"metric {name}")
            for name in sorted(tolerances)
        }
        result_payload = {
            "evaluator_id": eid,
            "arm_id": arm_id,
            "metrics": metrics,
            "protocol_hash": protocol_hash,
            "seal_hash": commitment["seal_hash"],
        }
        if _safe_sha(row["result_hash"], "result_hash") != _sha(_canonical(result_payload)):
            raise ValueError("result_hash verification failed")
        metrics_by_cell[cell] = metrics
    if set(metrics_by_cell) != expected_cells:
        raise ValueError("report result matrix coverage is incomplete")

    expected_comparisons: Dict[tuple[str, str, str, str], Dict[str, Any]] = {}
    evaluator_ids = sorted(observed_evaluators)
    for arm_id in sorted(arms_by_id):
        for metric, tolerance in sorted(tolerances.items()):
            for left, right in combinations(evaluator_ids, 2):
                left_value = metrics_by_cell[(left, arm_id)][metric]
                right_value = metrics_by_cell[(right, arm_id)][metric]
                delta = abs(left_value - right_value)
                passed = delta <= tolerance or math.isclose(
                    delta, tolerance, rel_tol=1e-12, abs_tol=1e-15
                )
                expected_comparisons[(arm_id, metric, left, right)] = {
                    "arm_id": arm_id,
                    "metric": metric,
                    "left_evaluator_id": left,
                    "right_evaluator_id": right,
                    "left_value": left_value,
                    "right_value": right_value,
                    "tolerance": tolerance,
                    "absolute_delta": delta,
                    "passed": passed,
                }
    comparisons = report_value.get("comparisons")
    if not isinstance(comparisons, list) or len(comparisons) != len(expected_comparisons):
        raise ValueError("report pairwise comparison coverage is incomplete")
    seen = set()
    for row in comparisons:
        if not isinstance(row, Mapping):
            raise ValueError("comparison row must be a mapping")
        left = _safe_id(row.get("left_evaluator_id"), "left_evaluator_id")
        right = _safe_id(row.get("right_evaluator_id"), "right_evaluator_id")
        canonical_pair = tuple(sorted((left, right)))
        key = (
            _safe_id(row.get("arm_id"), "comparison arm_id"),
            _safe_id(row.get("metric"), "comparison metric"),
            canonical_pair[0], canonical_pair[1],
        )
        expected = expected_comparisons.get(key)
        if key in seen or expected is None:
            raise ValueError("comparison identity is invalid or duplicated")
        seen.add(key)
        for numeric in (
            "left_value", "right_value", "tolerance", "absolute_delta"
        ):
            actual_number = _finite(row.get(numeric), f"comparison {numeric}")
            expected_number = float(expected[numeric])
            if not math.isclose(actual_number, expected_number, rel_tol=1e-12, abs_tol=1e-15):
                raise ValueError(f"comparison {numeric} is inconsistent")
        if row.get("passed") is not expected["passed"]:
            raise ValueError("comparison passed flag is inconsistent")
    if seen != set(expected_comparisons):
        raise ValueError("report comparison matrix coverage is incomplete")

    reproducible = all(row["passed"] for row in expected_comparisons.values())
    if report_value.get("reproducibility_satisfied") is not reproducible:
        raise ValueError("report reproducibility flag is inconsistent")
    claimed_hash = _safe_sha(report_value["report_hash"], "report_hash")
    payload = {key: value for key, value in report_value.items() if key != "report_hash"}
    if _sha(_canonical(payload)) != claimed_hash:
        raise ValueError("report_hash verification failed")
    return claimed_hash, reproducible


def _required_policy_rules(policy: Any) -> None:
    for kind in _REQUIRED_POLICY_PROOFS:
        allowed = any(
            rule.capability_id == _CAPABILITY_ID
            and rule.proof_kind == kind
            and _SUBJECT in rule.subjects
            and _VERIFIER in rule.verifiers
            and _REFERENCE_PREFIX in rule.reference_prefixes
            for rule in policy.rules
        )
        if not allowed:
            raise ValueError(
                f"committed proof policy does not authorize capability 98 {kind.value} attestation"
            )


def _outside_repo(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return False
    except ValueError:
        return True


def _existing_adds(ledger: ProofLedger) -> Mapping[str, Mapping[str, Any]]:
    return {
        str(row.get("receipt_id") or ""): row
        for row in ledger._events()  # noqa: SLF001 - trusted same-package attestor
        if row.get("event_type") == "ADD"
    }


def attest_double_blind_proofs(
    *,
    report: Any,
    preregistration_token: str,
    assignment_key: bytes,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> DoubleBlindProofAttestation:
    """Mint trusted #98 proofs after revalidating a preregistered blind run."""
    proof_key = _strong_key(integrity_key, "integrity_key")
    assignment = _strong_key(assignment_key, "assignment_key")
    current_time = _finite(now, "now")
    root = Path(repo_root).resolve(strict=True)
    revision = _clean_revision(root)
    commitment = _validate_commitment(
        token=preregistration_token,
        integrity_key=proof_key,
        assignment_key=assignment,
        revision=revision,
        now=current_time,
    )
    report_hash, reproducible = _validate_report(
        _report_dict(report), commitment, assignment
    )

    tracked = _tracked_index(root)
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    _required_policy_rules(policy)
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")
    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or not _GIT_SHA_RE.fullmatch(prior):
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=proof_key)
        if not continuity.verify_chain(
            anchor_token=prior_anchor_token,
            current_revision=prior,
        ):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    kinds = [ProofKind.EXECUTION, ProofKind.INDEPENDENT]
    if reproducible:
        kinds.append(ProofKind.REPRODUCIBILITY)
    reference = _REFERENCE_PREFIX + report_hash
    ledger = ProofLedger(str(ledger_target), integrity_key=proof_key)
    existing = _existing_adds(ledger)
    added = 0
    reused = 0
    for kind in kinds:
        receipt_id = f"dbl:c98:{kind.value}:{report_hash[:16]}"
        expected = {
            "capability_id": _CAPABILITY_ID,
            "proof_kind": kind.value,
            "subject": _SUBJECT,
            "subject_sha256": report_hash,
            "verifier": _VERIFIER,
            "reference": reference,
            "implementation_revision": revision,
        }
        previous = existing.get(receipt_id)
        if previous is not None:
            if not all(previous.get(key) == value for key, value in expected.items()):
                raise ValueError("deterministic double-blind receipt_id collision")
            reused += 1
            continue
        ledger.add(
            receipt_id=receipt_id,
            capability_id=_CAPABILITY_ID,
            proof_kind=kind,
            subject=_SUBJECT,
            subject_sha256=report_hash,
            verifier=_VERIFIER,
            observed_at=current_time,
            reference=reference,
            implementation_revision=revision,
        )
        added += 1

    anchor = ledger.create_anchor(
        current_revision=revision,
        issued_at=current_time,
    )
    audit = audit_repository_maturity(
        repo_root=root,
        ledger_path=ledger_target,
        integrity_key=proof_key,
        anchor_token=anchor,
        now=current_time,
        policy_path=policy_path,
    )
    return DoubleBlindProofAttestation(
        revision=revision,
        report_hash=report_hash,
        reproducibility_satisfied=reproducible,
        proofs_minted=tuple(kinds),
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
