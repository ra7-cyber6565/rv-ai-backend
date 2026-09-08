"""External independence attestor for #36 Red-Team AI and #37 Devil's Advocate.

The existing adversarial/scientist-society software benchmarks prove execution
and reproducibility, but they cannot prove that the *validator* was genuinely
independent.  This module adds a fail-closed external-validation contract for
that missing proof class.

Independence is process evidence, not scientific truth:

* at least three externally supplied validators are required;
* validator, runner, model-family, independence-domain and declared external
  implementation digests must all be distinct;
* every validator receives the same frozen, author-blinded challenge packets;
* expected outcomes/champion labels/author identities are never included;
* every validator repeats every challenge at least twice;
* validators may disagree — agreement is neither required nor treated as truth;
* raw structured packets/results are retained in the receipt so validation can
  independently recompute hashes and reject leakage or malformed evidence refs;
* the receipt is fresh, revision-bound, tracked-implementation-bound and HMAC
  ledger anchored before ``independent_validation`` can be minted.

The external implementation digests and independence domains are declarations
made in a trusted external validation context.  This code does not claim hidden
provider/operator dependencies have been ruled out and cannot mint execution,
reproducibility, safety, runtime, live or hardware evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Sequence, Tuple

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


_CAPABILITY_IDS = (36, 37)
_PROOF_KIND = ProofKind.INDEPENDENT
_IMPLEMENTATION_SUBJECTS = {
    36: "research_engine/adversarial_science.py",
    37: "research_engine/scientist_society.py",
}
_SUBJECTS = {
    36: "capability-36-independent-validation",
    37: "capability-37-independent-validation",
}
_VERIFIER = "trusted-independent-validator"
_REFERENCE_PREFIX = "independent:"
_SCHEMA_VERSION = 1
_MAX_RECEIPT_BYTES = 4 * 1024 * 1024
_MAX_TEXT_BYTES = 128 * 1024
_MIN_VALIDATORS = 3
_MAX_VALIDATORS = 12
_MIN_REPETITIONS = 2
_MAX_REPETITIONS = 5
_MAX_CHALLENGES_PER_CAPABILITY = 16
_MAX_FINDINGS = 64
_MAX_EVIDENCE_IDS = 128
_MAX_RECEIPT_AGE_SECONDS = 2 * 60 * 60
_MAX_FUTURE_SKEW_SECONDS = 5 * 60
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_DIMENSIONS = {
    "ASSUMPTION_BREAK",
    "COUNTEREXAMPLE",
    "ALTERNATIVE_MECHANISM",
    "MEASUREMENT_STRESS",
    "CONFOUNDER",
    "NEGATIVE_CONTROL",
    "OOD_STRESS",
    "INCENTIVE_FAILURE",
    "LEAKAGE_PROBE",
    "PLACEBO_CONTROL",
}
_STATUS_BY_CAPABILITY = {
    36: {"FALSIFIED", "NOT_FALSIFIED", "INCONCLUSIVE"},
    37: {"MATERIAL_OBJECTION", "NO_MATERIAL_OBJECTION", "INCONCLUSIVE"},
}
_FORBIDDEN_PACKET_KEYS = {
    "author",
    "author_id",
    "author_agent_id",
    "author_commitment",
    "expected",
    "expected_result",
    "expected_outcome",
    "champion",
    "champion_id",
    "ground_truth",
    "correct_answer",
}

Validator = Callable[[Mapping[str, Any]], Mapping[str, Any]]


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
        raise ValueError("adversarial-independence data must be strict finite JSON") from exc


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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


def _bounded_text(value: object, field: str, *, minimum: int = 1) -> str:
    text = str(value or "").strip()
    if len(text) < minimum or len(text.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ValueError(f"{field} length is invalid")
    return text


def _evidence_ids(values: object, field: str) -> Tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise ValueError(f"{field} must be a sequence")
    if not 1 <= len(values) <= _MAX_EVIDENCE_IDS:
        raise ValueError(f"{field} must contain 1..{_MAX_EVIDENCE_IDS} items")
    normalized = tuple(sorted({_safe_id(item, field) for item in values}))
    if len(normalized) != len(values):
        raise ValueError(f"{field} must not contain duplicates")
    return normalized


def _dimensions(values: object, field: str) -> Tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise ValueError(f"{field} must be a sequence")
    normalized = tuple(sorted({str(item or "").strip().upper() for item in values}))
    if len(normalized) < 2 or len(normalized) > len(_ALLOWED_DIMENSIONS):
        raise ValueError(f"{field} must contain at least two dimensions")
    if any(item not in _ALLOWED_DIMENSIONS for item in normalized):
        raise ValueError(f"{field} contains unsupported dimensions")
    if len(normalized) != len(values):
        raise ValueError(f"{field} must not contain duplicates")
    return normalized


def _walk_keys(value: Any):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key).strip().lower()
            yield from _walk_keys(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            yield from _walk_keys(item)


def _assert_blinded_packet(packet: Mapping[str, Any]) -> None:
    leaked = sorted(set(_walk_keys(packet)) & _FORBIDDEN_PACKET_KEYS)
    if leaked:
        raise ValueError("challenge packet leaked blinded metadata: " + ",".join(leaked))


@dataclass(frozen=True)
class IndependenceChallenge:
    capability_id: int
    challenge_id: str
    statement: str
    evidence_ids: Tuple[str, ...]
    dimensions: Tuple[str, ...]

    def normalized(self) -> "IndependenceChallenge":
        capability_id = self.capability_id
        if type(capability_id) is not int or capability_id not in _CAPABILITY_IDS:
            raise ValueError("challenge capability_id must be 36 or 37")
        return IndependenceChallenge(
            capability_id=capability_id,
            challenge_id=_safe_id(self.challenge_id, "challenge_id"),
            statement=_bounded_text(self.statement, "challenge.statement", minimum=8),
            evidence_ids=_evidence_ids(self.evidence_ids, "challenge.evidence_ids"),
            dimensions=_dimensions(self.dimensions, "challenge.dimensions"),
        )

    def packet(self) -> Dict[str, Any]:
        normalized = self.normalized()
        task = (
            "Independently attempt to falsify or materially weaken this target using "
            "the supplied evidence and declared stress dimensions."
            if normalized.capability_id == 36
            else
            "Independently construct the strongest devil's-advocate objections and "
            "failure modes using the supplied evidence and declared dimensions."
        )
        packet = {
            "schema_version": 1,
            "capability_id": normalized.capability_id,
            "challenge_id": normalized.challenge_id,
            "statement": normalized.statement,
            "evidence_ids": list(normalized.evidence_ids),
            "dimensions": list(normalized.dimensions),
            "task": task,
        }
        _assert_blinded_packet(packet)
        return packet


@dataclass(frozen=True)
class ExternalValidatorSpec:
    validator_id: str
    runner_id: str
    model_family: str
    independence_domain: str
    implementation_sha256: str
    validator: Validator


@dataclass(frozen=True)
class AdversarialIndependenceExecutionReceipt:
    revision: str
    created_at_epoch: int
    sha256: str
    report_hash: str
    validator_manifest_hash: str
    challenge_commitment: str
    repetitions: int


@dataclass(frozen=True)
class AdversarialIndependenceAttestation:
    revision: str
    execution_receipt_sha256: str
    report_hash: str
    validator_manifest_hash: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    hidden_provider_dependencies_ruled_out: bool = False
    external_implementation_bytes_verified: bool = False
    truth_proven: bool = False


def _normalize_validators(
    validators: Sequence[ExternalValidatorSpec],
) -> Tuple[Tuple[ExternalValidatorSpec, ...], Tuple[Dict[str, str], ...], str]:
    if (
        isinstance(validators, (str, bytes, bytearray))
        or not isinstance(validators, Sequence)
        or not _MIN_VALIDATORS <= len(validators) <= _MAX_VALIDATORS
    ):
        raise ValueError("independence validation requires 3..12 validators")
    specs = []
    rows = []
    for index, raw in enumerate(validators):
        if not isinstance(raw, ExternalValidatorSpec) or not callable(raw.validator):
            raise ValueError(f"validator binding {index} is invalid")
        row = {
            "validator_id": _safe_id(raw.validator_id, "validator_id"),
            "runner_id": _safe_id(raw.runner_id, "runner_id"),
            "model_family": _safe_id(raw.model_family, "model_family"),
            "independence_domain": _safe_id(raw.independence_domain, "independence_domain"),
            "implementation_sha256": _safe_sha(
                raw.implementation_sha256, "validator implementation_sha256"
            ),
        }
        rows.append(row)
        specs.append(
            ExternalValidatorSpec(
                validator_id=row["validator_id"],
                runner_id=row["runner_id"],
                model_family=row["model_family"],
                independence_domain=row["independence_domain"],
                implementation_sha256=row["implementation_sha256"],
                validator=raw.validator,
            )
        )
    for field in (
        "validator_id",
        "runner_id",
        "model_family",
        "independence_domain",
        "implementation_sha256",
    ):
        if len({row[field] for row in rows}) != len(rows):
            raise ValueError(f"all external validators must have distinct {field} values")
    order = sorted(range(len(rows)), key=lambda idx: rows[idx]["validator_id"])
    ordered_specs = tuple(specs[idx] for idx in order)
    ordered_rows = tuple(rows[idx] for idx in order)
    return ordered_specs, ordered_rows, _sha(list(ordered_rows))


def _normalize_challenges(
    challenges: Sequence[IndependenceChallenge],
) -> Tuple[Tuple[IndependenceChallenge, ...], Tuple[Dict[str, Any], ...], str]:
    if isinstance(challenges, (str, bytes, bytearray)) or not isinstance(challenges, Sequence):
        raise ValueError("challenges must be a sequence")
    normalized = tuple(item.normalized() for item in challenges)
    if not normalized:
        raise ValueError("at least one challenge per capability is required")
    counts = {36: 0, 37: 0}
    keys = set()
    rows = []
    for item in normalized:
        counts[item.capability_id] += 1
        if counts[item.capability_id] > _MAX_CHALLENGES_PER_CAPABILITY:
            raise ValueError("too many independence challenges")
        key = (item.capability_id, item.challenge_id)
        if key in keys:
            raise ValueError("challenge identifiers must be unique per capability")
        keys.add(key)
        packet = item.packet()
        rows.append({
            "capability_id": item.capability_id,
            "challenge_id": item.challenge_id,
            "packet": packet,
            "packet_sha256": _sha(packet),
        })
    if any(counts[item] < 1 for item in _CAPABILITY_IDS):
        raise ValueError("at least one challenge is required for both capabilities 36 and 37")
    ordered = tuple(sorted(normalized, key=lambda item: (item.capability_id, item.challenge_id)))
    ordered_rows = tuple(sorted(rows, key=lambda row: (row["capability_id"], row["challenge_id"])))
    return ordered, ordered_rows, _sha(list(ordered_rows))


def _normalize_result(
    raw: Mapping[str, Any],
    *,
    packet: Mapping[str, Any],
) -> Dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("external validator must return a mapping")
    if set(raw) != {"status", "tested_dimensions", "findings"}:
        raise ValueError("external validator result schema is invalid")
    capability_id = int(packet["capability_id"])
    status = str(raw.get("status") or "").strip().upper()
    if status not in _STATUS_BY_CAPABILITY[capability_id]:
        raise ValueError("external validator result status is invalid")
    tested = _dimensions(raw.get("tested_dimensions"), "tested_dimensions")
    allowed_dimensions = set(packet.get("dimensions") or ())
    if not set(tested).issubset(allowed_dimensions):
        raise ValueError("validator tested a dimension outside the frozen challenge")

    findings_raw = raw.get("findings")
    if (
        isinstance(findings_raw, (str, bytes, bytearray))
        or not isinstance(findings_raw, Sequence)
        or not 1 <= len(findings_raw) <= _MAX_FINDINGS
    ):
        raise ValueError("validator findings must contain 1..64 items")
    allowed_evidence = set(packet.get("evidence_ids") or ())
    findings = []
    ids = set()
    for index, finding in enumerate(findings_raw):
        if not isinstance(finding, Mapping) or set(finding) != {
            "finding_id", "dimension", "statement", "evidence_ids"
        }:
            raise ValueError(f"finding {index} schema is invalid")
        finding_id = _safe_id(finding.get("finding_id"), "finding_id")
        if finding_id in ids:
            raise ValueError("finding_id values must be unique")
        ids.add(finding_id)
        dimension = str(finding.get("dimension") or "").strip().upper()
        if dimension not in tested:
            raise ValueError("finding dimension was not listed as tested")
        evidence = _evidence_ids(finding.get("evidence_ids"), "finding.evidence_ids")
        if not set(evidence).issubset(allowed_evidence):
            raise ValueError("finding cites evidence outside the frozen challenge")
        findings.append({
            "finding_id": finding_id,
            "dimension": dimension,
            "statement": _bounded_text(finding.get("statement"), "finding.statement", minimum=5),
            "evidence_ids": list(evidence),
        })
    return {
        "status": status,
        "tested_dimensions": list(tested),
        "findings": sorted(findings, key=lambda item: item["finding_id"]),
    }


def build_adversarial_independence_execution_receipt(
    *,
    repo_root: str | os.PathLike[str],
    challenges: Sequence[IndependenceChallenge],
    validators: Sequence[ExternalValidatorSpec],
    created_at_epoch: int,
    repetitions: int = 2,
) -> Dict[str, Any]:
    """Execute externally supplied validators against frozen blinded challenges."""
    if type(created_at_epoch) is not int or created_at_epoch <= 0:
        raise ValueError("created_at_epoch must be a positive integer")
    if type(repetitions) is not int or not _MIN_REPETITIONS <= repetitions <= _MAX_REPETITIONS:
        raise ValueError("repetitions must be between 2 and 5")
    root = Path(repo_root).resolve(strict=True)
    identity = repository_identity(root)
    revision = str(identity.get("revision") or "").strip().lower()
    if not identity.get("available") or not identity.get("clean") or len(revision) != 40:
        raise ValueError("adversarial independence execution requires a clean Git checkout")
    tracked = _tracked_index(root)
    implementation_hashes = {
        str(capability_id): _hash_tracked_regular(root, tracked, subject)
        for capability_id, subject in _IMPLEMENTATION_SUBJECTS.items()
    }
    validators_n, validator_rows, validator_manifest_hash = _normalize_validators(validators)
    challenges_n, challenge_rows, challenge_commitment = _normalize_challenges(challenges)

    runs = []
    for spec in validators_n:
        for challenge in challenges_n:
            packet = challenge.packet()
            packet_hash = _sha(packet)
            for repetition in range(1, repetitions + 1):
                external_packet = json.loads(_canonical(packet).decode("utf-8"))
                _assert_blinded_packet(external_packet)
                raw = spec.validator(external_packet)
                result = _normalize_result(raw, packet=packet)
                run = {
                    "validator_id": spec.validator_id,
                    "capability_id": challenge.capability_id,
                    "challenge_id": challenge.challenge_id,
                    "repetition": repetition,
                    "packet": packet,
                    "packet_sha256": packet_hash,
                    "result": result,
                    "result_sha256": _sha(result),
                }
                run["run_sha256"] = _sha(run)
                runs.append(run)

    report = {
        "schema_version": _SCHEMA_VERSION,
        "created_at_epoch": created_at_epoch,
        "implementation_revision": revision,
        "implementation_subjects": {
            str(key): value for key, value in sorted(_IMPLEMENTATION_SUBJECTS.items())
        },
        "implementation_sha256": implementation_hashes,
        "validator_manifest": list(validator_rows),
        "validator_manifest_hash": validator_manifest_hash,
        "challenge_manifest": list(challenge_rows),
        "challenge_commitment": challenge_commitment,
        "repetitions_per_validator": repetitions,
        "runs": runs,
        "packets_blinded": True,
        "external_independence_structure_satisfied": True,
        "observer_attested_independence_domains": True,
        "observer_attested_external_implementation_digests": True,
        "external_implementation_bytes_verified": False,
        "hidden_provider_dependencies_ruled_out": False,
        "validator_agreement_required": False,
        "agreement_proves_truth": False,
        "truth_proven": False,
    }
    report["report_hash"] = _sha(report)
    if len(_canonical(report)) > _MAX_RECEIPT_BYTES:
        raise ValueError("adversarial independence receipt exceeds size limit")
    return report


def _read_json(path: Path) -> tuple[Mapping[str, Any], bytes]:
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError("adversarial independence receipt cannot be read") from exc
    if not path.is_file() or info.st_size < 1 or info.st_size > _MAX_RECEIPT_BYTES:
        raise ValueError("adversarial independence receipt size is invalid")
    data = path.read_bytes()
    if len(data) != info.st_size:
        raise ValueError("adversarial independence receipt changed during read")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("adversarial independence receipt is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("adversarial independence receipt must be a JSON object")
    return value, data


def _validate_manifest_rows(rows: object) -> tuple[Tuple[Dict[str, str], ...], str]:
    if not isinstance(rows, list) or not _MIN_VALIDATORS <= len(rows) <= _MAX_VALIDATORS:
        raise ValueError("validator_manifest size is invalid")
    normalized = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "validator_id", "runner_id", "model_family", "independence_domain",
            "implementation_sha256",
        }:
            raise ValueError("validator_manifest row schema is invalid")
        normalized.append({
            "validator_id": _safe_id(row.get("validator_id"), "validator_id"),
            "runner_id": _safe_id(row.get("runner_id"), "runner_id"),
            "model_family": _safe_id(row.get("model_family"), "model_family"),
            "independence_domain": _safe_id(row.get("independence_domain"), "independence_domain"),
            "implementation_sha256": _safe_sha(
                row.get("implementation_sha256"), "validator implementation_sha256"
            ),
        })
    for field in (
        "validator_id", "runner_id", "model_family", "independence_domain",
        "implementation_sha256",
    ):
        if len({row[field] for row in normalized}) != len(normalized):
            raise ValueError(f"validator_manifest requires distinct {field} values")
    ordered = tuple(sorted(normalized, key=lambda item: item["validator_id"]))
    if list(ordered) != rows:
        raise ValueError("validator_manifest must use canonical validator_id order")
    return ordered, _sha(list(ordered))


def validate_adversarial_independence_receipt(
    path: str | os.PathLike[str],
    *,
    repo_root: str | os.PathLike[str],
    now: float,
) -> AdversarialIndependenceExecutionReceipt:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    root = Path(repo_root).resolve(strict=True)
    identity = repository_identity(root)
    revision = str(identity.get("revision") or "").strip().lower()
    if not identity.get("available") or not identity.get("clean") or len(revision) != 40:
        raise ValueError("adversarial independence validation requires a clean Git checkout")

    value, raw = _read_json(Path(path).expanduser().resolve())
    required = {
        "schema_version", "created_at_epoch", "implementation_revision",
        "implementation_subjects", "implementation_sha256", "validator_manifest",
        "validator_manifest_hash", "challenge_manifest", "challenge_commitment",
        "repetitions_per_validator", "runs", "packets_blinded",
        "external_independence_structure_satisfied",
        "observer_attested_independence_domains",
        "observer_attested_external_implementation_digests",
        "external_implementation_bytes_verified",
        "hidden_provider_dependencies_ruled_out", "validator_agreement_required",
        "agreement_proves_truth", "truth_proven", "report_hash",
    }
    if set(value) != required or value.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("adversarial independence receipt schema is invalid")
    created = value.get("created_at_epoch")
    if type(created) is not int or created <= 0:
        raise ValueError("created_at_epoch is invalid")
    age = current_time - float(created)
    if age > _MAX_RECEIPT_AGE_SECONDS:
        raise ValueError("adversarial independence receipt is stale")
    if age < -_MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("adversarial independence receipt is from the future")
    if str(value.get("implementation_revision") or "").strip().lower() != revision:
        raise ValueError("adversarial independence receipt revision mismatch")

    tracked = _tracked_index(root)
    expected_subjects = {str(k): v for k, v in sorted(_IMPLEMENTATION_SUBJECTS.items())}
    if value.get("implementation_subjects") != expected_subjects:
        raise ValueError("implementation_subjects are invalid")
    hashes = value.get("implementation_sha256")
    if not isinstance(hashes, dict) or set(hashes) != set(expected_subjects):
        raise ValueError("implementation_sha256 map is invalid")
    for capability_text, subject in expected_subjects.items():
        expected = _hash_tracked_regular(root, tracked, subject)
        if _safe_sha(hashes.get(capability_text), "implementation_sha256") != expected:
            raise ValueError("tracked implementation hash mismatch")

    manifest, manifest_hash = _validate_manifest_rows(value.get("validator_manifest"))
    if value.get("validator_manifest_hash") != manifest_hash:
        raise ValueError("validator_manifest_hash mismatch")
    validator_ids = {row["validator_id"] for row in manifest}

    challenges_raw = value.get("challenge_manifest")
    if not isinstance(challenges_raw, list) or not challenges_raw:
        raise ValueError("challenge_manifest is invalid")
    challenge_lookup: Dict[tuple[int, str], Dict[str, Any]] = {}
    normalized_challenges = []
    counts = {36: 0, 37: 0}
    for row in challenges_raw:
        if not isinstance(row, dict) or set(row) != {
            "capability_id", "challenge_id", "packet", "packet_sha256"
        }:
            raise ValueError("challenge_manifest row schema is invalid")
        capability_id = row.get("capability_id")
        if type(capability_id) is not int or capability_id not in _CAPABILITY_IDS:
            raise ValueError("challenge capability_id is invalid")
        challenge_id = _safe_id(row.get("challenge_id"), "challenge_id")
        packet = row.get("packet")
        if not isinstance(packet, dict):
            raise ValueError("challenge packet is invalid")
        _assert_blinded_packet(packet)
        if packet.get("capability_id") != capability_id or packet.get("challenge_id") != challenge_id:
            raise ValueError("challenge packet identity mismatch")
        _bounded_text(packet.get("statement"), "challenge.statement", minimum=8)
        _evidence_ids(packet.get("evidence_ids"), "challenge.evidence_ids")
        _dimensions(packet.get("dimensions"), "challenge.dimensions")
        _bounded_text(packet.get("task"), "challenge.task", minimum=8)
        packet_hash = _sha(packet)
        if row.get("packet_sha256") != packet_hash:
            raise ValueError("challenge packet hash mismatch")
        key = (capability_id, challenge_id)
        if key in challenge_lookup:
            raise ValueError("duplicate challenge manifest identity")
        challenge_lookup[key] = packet
        counts[capability_id] += 1
        if counts[capability_id] > _MAX_CHALLENGES_PER_CAPABILITY:
            raise ValueError("too many challenges")
        normalized_challenges.append({
            "capability_id": capability_id,
            "challenge_id": challenge_id,
            "packet": packet,
            "packet_sha256": packet_hash,
        })
    if any(counts[item] < 1 for item in _CAPABILITY_IDS):
        raise ValueError("both capability challenge families are required")
    expected_challenges = sorted(
        normalized_challenges, key=lambda item: (item["capability_id"], item["challenge_id"])
    )
    if challenges_raw != expected_challenges:
        raise ValueError("challenge_manifest must use canonical order")
    challenge_commitment = _sha(expected_challenges)
    if value.get("challenge_commitment") != challenge_commitment:
        raise ValueError("challenge_commitment mismatch")

    repetitions = value.get("repetitions_per_validator")
    if type(repetitions) is not int or not _MIN_REPETITIONS <= repetitions <= _MAX_REPETITIONS:
        raise ValueError("repetitions_per_validator is invalid")
    runs = value.get("runs")
    expected_run_count = len(manifest) * len(challenge_lookup) * repetitions
    if not isinstance(runs, list) or len(runs) != expected_run_count:
        raise ValueError("run matrix is incomplete")
    seen_runs = set()
    for run in runs:
        if not isinstance(run, dict) or set(run) != {
            "validator_id", "capability_id", "challenge_id", "repetition",
            "packet", "packet_sha256", "result", "result_sha256", "run_sha256",
        }:
            raise ValueError("run schema is invalid")
        validator_id = _safe_id(run.get("validator_id"), "run.validator_id")
        if validator_id not in validator_ids:
            raise ValueError("run references unknown validator")
        capability_id = run.get("capability_id")
        challenge_id = _safe_id(run.get("challenge_id"), "run.challenge_id")
        key = (capability_id, challenge_id)
        packet = challenge_lookup.get(key)
        if packet is None:
            raise ValueError("run references unknown challenge")
        repetition = run.get("repetition")
        if type(repetition) is not int or not 1 <= repetition <= repetitions:
            raise ValueError("run repetition is invalid")
        run_key = (validator_id, capability_id, challenge_id, repetition)
        if run_key in seen_runs:
            raise ValueError("duplicate run matrix cell")
        seen_runs.add(run_key)
        if run.get("packet") != packet:
            raise ValueError("run packet differs from frozen challenge")
        _assert_blinded_packet(run["packet"])
        packet_hash = _sha(packet)
        if run.get("packet_sha256") != packet_hash:
            raise ValueError("run packet hash mismatch")
        result = _normalize_result(run.get("result"), packet=packet)
        if run.get("result") != result or run.get("result_sha256") != _sha(result):
            raise ValueError("run result hash or canonicalization mismatch")
        payload = {key_name: run[key_name] for key_name in run if key_name != "run_sha256"}
        if run.get("run_sha256") != _sha(payload):
            raise ValueError("run_sha256 mismatch")
    if len(seen_runs) != expected_run_count:
        raise ValueError("run matrix does not cover every validator/challenge/repetition")

    if value.get("packets_blinded") is not True:
        raise ValueError("receipt must attest blinded packets")
    if value.get("external_independence_structure_satisfied") is not True:
        raise ValueError("receipt did not satisfy independence structure")
    if value.get("observer_attested_independence_domains") is not True:
        raise ValueError("independence domains were not observer-attested")
    if value.get("observer_attested_external_implementation_digests") is not True:
        raise ValueError("external implementation digests were not observer-attested")
    if value.get("external_implementation_bytes_verified") is not False:
        raise ValueError("receipt must not claim external implementation bytes were verified")
    if value.get("hidden_provider_dependencies_ruled_out") is not False:
        raise ValueError("receipt must not claim hidden provider dependencies were ruled out")
    if value.get("validator_agreement_required") is not False:
        raise ValueError("validator agreement must not be required for independence")
    if value.get("agreement_proves_truth") is not False or value.get("truth_proven") is not False:
        raise ValueError("independence receipt must not claim scientific truth")

    report_hash = str(value.get("report_hash") or "")
    payload = {key: val for key, val in value.items() if key != "report_hash"}
    if not _SHA256_RE.fullmatch(report_hash) or report_hash != _sha(payload):
        raise ValueError("adversarial independence report_hash mismatch")
    return AdversarialIndependenceExecutionReceipt(
        revision=revision,
        created_at_epoch=created,
        sha256=_sha_bytes(raw),
        report_hash=report_hash,
        validator_manifest_hash=manifest_hash,
        challenge_commitment=challenge_commitment,
        repetitions=repetitions,
    )


def _safe_observation_id(value: object) -> str:
    return _safe_id(value, "observation_id")


def _same_receipt(
    row: Mapping[str, Any],
    *,
    capability_id: int,
    digest: str,
    reference: str,
    revision: str,
) -> bool:
    expected = {
        "capability_id": capability_id,
        "proof_kind": _PROOF_KIND.value,
        "subject": _SUBJECTS[capability_id],
        "subject_sha256": digest,
        "verifier": _VERIFIER,
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_adversarial_independence(
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
) -> AdversarialIndependenceAttestation:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    observation = _safe_observation_id(observation_id)
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "").strip().lower()
    if not identity_before.get("available") or not identity_before.get("clean") or len(revision) != 40:
        raise ValueError("adversarial independence attestation requires a clean Git checkout")
    tracked = _tracked_index(root)
    implementation_hashes = {
        capability_id: _hash_tracked_regular(root, tracked, subject)
        for capability_id, subject in _IMPLEMENTATION_SUBJECTS.items()
    }
    receipt = validate_adversarial_independence_receipt(
        execution_receipt_path,
        repo_root=root,
        now=current_time,
    )
    if receipt.revision != revision:
        raise ValueError("execution receipt revision mismatch")

    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    references: Dict[int, str] = {}
    for capability_id in _CAPABILITY_IDS:
        subject = _SUBJECTS[capability_id]
        reference = f"{_REFERENCE_PREFIX}c{capability_id}:{observation}"
        matches = tuple(
            rule for rule in policy.rules
            if rule.capability_id == capability_id
            and rule.proof_kind is _PROOF_KIND
            and subject in rule.subjects
            and _VERIFIER in rule.verifiers
        )
        if not matches:
            raise ValueError(
                f"committed proof policy has no trusted c{capability_id} independent route"
            )
        if not any(
            not rule.reference_prefixes
            or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
            for rule in matches
        ):
            raise ValueError("generated reference is not allowed by independence proof policy")
        references[capability_id] = reference

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

    receipt_digest = _sha({
        "revision": revision,
        "execution_receipt_sha256": receipt.sha256,
        "report_hash": receipt.report_hash,
        "validator_manifest_hash": receipt.validator_manifest_hash,
        "challenge_commitment": receipt.challenge_commitment,
        "implementation_sha256": {
            str(key): value for key, value in sorted(implementation_hashes.items())
        },
        "proof_kind": _PROOF_KIND.value,
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0
    for capability_id in _CAPABILITY_IDS:
        reference = references[capability_id]
        receipt_id = f"adversarial-independent:{revision[:12]}:c{capability_id}"
        previous = existing.get(receipt_id)
        if previous is not None:
            if not _same_receipt(
                previous,
                capability_id=capability_id,
                digest=receipt_digest,
                reference=reference,
                revision=revision,
            ):
                raise ValueError("deterministic adversarial independence receipt_id collision")
            reused += 1
            continue
        ledger.add(
            receipt_id=receipt_id,
            capability_id=capability_id,
            proof_kind=_PROOF_KIND,
            subject=_SUBJECTS[capability_id],
            subject_sha256=receipt_digest,
            verifier=_VERIFIER,
            observed_at=current_time,
            reference=reference,
            implementation_revision=revision,
        )
        added += 1
    if added + reused != len(_CAPABILITY_IDS):
        raise ValueError("independence attestation did not account for every capability")

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
        raise ValueError("trusted maturity audit rejected independence attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "").strip().lower() != revision
    ):
        raise ValueError("repository changed during independence attestation")

    return AdversarialIndependenceAttestation(
        revision=revision,
        execution_receipt_sha256=receipt.sha256,
        report_hash=receipt.report_hash,
        validator_manifest_hash=receipt.validator_manifest_hash,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
