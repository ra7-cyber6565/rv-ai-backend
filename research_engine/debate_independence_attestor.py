"""External independence attestor for capability #19 Debate Tournament.

The deterministic Scientist Society benchmark proves that the tournament code
executes and reproduces, but it cannot prove that a real judge is independent.
This module closes that proof-route *interface* without turning CI into external
validation.

A trusted independent validator must run the same frozen candidate set through
at least three externally configured judge domains.  Judge, runner, model-family
and observer-attested independence-domain identities must all be distinct.  The
candidate author identity is committed for audit but never placed in the judge
packet.  Every judge is exercised repeatedly against the same candidate
commitment.  Judges are allowed to disagree: independence is a property of the
validation process, not evidence that the winning hypothesis is true.

Only ``independent_validation`` for capability 19 can be minted.  The receipt is
bound to a clean Git revision and to the tracked ``scientist_society.py`` bytes,
then anchored through the existing HMAC proof ledger.  Hidden provider/operator
dependencies remain explicitly unproven.
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
from .scientist_society import DebateTournament, TournamentCandidate


_CAPABILITY_ID = 19
_PROOF_KIND = ProofKind.INDEPENDENT
_SCHEMA_VERSION = 1
_IMPLEMENTATION_SUBJECT = "research_engine/scientist_society.py"
_SUBJECT = "capability-19-independent-validation"
_VERIFIER = "trusted-independent-validator"
_REFERENCE_PREFIX = "independent:"
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024
_MAX_CANDIDATES = 32
_MIN_JUDGES = 3
_MAX_JUDGES = 12
_MIN_RUNS = 2
_MAX_RUNS = 5
_MAX_RECEIPT_AGE_SECONDS = 2 * 60 * 60
_MAX_FUTURE_SKEW_SECONDS = 5 * 60
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
Judge = Callable[[Mapping[str, Any]], Mapping[str, Any]]


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
        raise ValueError("debate-independence data must be strict JSON") from exc


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


@dataclass(frozen=True)
class DebateJudgeSpec:
    judge_id: str
    runner_id: str
    model_family: str
    independence_domain: str
    judge: Judge


@dataclass(frozen=True)
class DebateIndependenceExecutionReceipt:
    revision: str
    created_at_epoch: int
    sha256: str
    report_hash: str
    candidate_commitment: str
    judge_manifest_hash: str
    run_count: int


@dataclass(frozen=True)
class DebateIndependenceAttestation:
    revision: str
    execution_receipt_sha256: str
    report_hash: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    hidden_provider_dependencies_ruled_out: bool = False
    truth_proven: bool = False


def _candidate_manifest(
    candidates: Sequence[TournamentCandidate],
) -> Tuple[Tuple[TournamentCandidate, ...], Tuple[Dict[str, Any], ...], str]:
    if (
        isinstance(candidates, (str, bytes, bytearray))
        or not isinstance(candidates, Sequence)
        or not 2 <= len(candidates) <= _MAX_CANDIDATES
    ):
        raise ValueError("debate independence requires 2..32 candidates")
    normalized = []
    rows = []
    seen = set()
    for index, raw in enumerate(candidates):
        if not isinstance(raw, TournamentCandidate):
            raise ValueError(f"candidate {index} is invalid")
        hypothesis_id = _safe_id(raw.hypothesis_id, "hypothesis_id")
        if hypothesis_id in seen:
            raise ValueError("hypothesis_id values must be unique")
        seen.add(hypothesis_id)
        statement = str(raw.statement or "").strip()
        if not statement or len(statement.encode("utf-8")) > 256 * 1024:
            raise ValueError("candidate statement is empty or too large")
        evidence_ids = tuple(
            sorted({_safe_id(item, "evidence_id") for item in tuple(raw.evidence_ids)})
        )
        if not evidence_ids:
            raise ValueError("every debate candidate must cite evidence ids")
        author_id = _safe_id(raw.author_agent_id, "author_agent_id")
        normalized.append(
            TournamentCandidate(
                hypothesis_id=hypothesis_id,
                statement=statement,
                evidence_ids=evidence_ids,
                author_agent_id=author_id,
            )
        )
        rows.append({
            "hypothesis_id": hypothesis_id,
            "statement_sha256": _sha(statement),
            "evidence_ids_sha256": _sha(list(evidence_ids)),
            "evidence_count": len(evidence_ids),
            # The author is committed for post-hoc audit but not disclosed to judges.
            "author_commitment": _sha({"hypothesis_id": hypothesis_id, "author": author_id}),
        })
    rows.sort(key=lambda row: row["hypothesis_id"])
    return tuple(normalized), tuple(rows), _sha(rows)


def _judge_manifest(judges: Sequence[DebateJudgeSpec]) -> Tuple[Tuple[DebateJudgeSpec, ...], Tuple[Dict[str, str], ...], str]:
    if (
        isinstance(judges, (str, bytes, bytearray))
        or not isinstance(judges, Sequence)
        or not _MIN_JUDGES <= len(judges) <= _MAX_JUDGES
    ):
        raise ValueError("debate independence requires 3..12 external judges")
    normalized = []
    rows = []
    for index, raw in enumerate(judges):
        if not isinstance(raw, DebateJudgeSpec) or not callable(raw.judge):
            raise ValueError(f"judge binding {index} is invalid")
        row = {
            "judge_id": _safe_id(raw.judge_id, "judge_id"),
            "runner_id": _safe_id(raw.runner_id, "runner_id"),
            "model_family": _safe_id(raw.model_family, "model_family"),
            "independence_domain": _safe_id(raw.independence_domain, "independence_domain"),
        }
        rows.append(row)
        normalized.append(
            DebateJudgeSpec(
                judge_id=row["judge_id"],
                runner_id=row["runner_id"],
                model_family=row["model_family"],
                independence_domain=row["independence_domain"],
                judge=raw.judge,
            )
        )
    for field in ("judge_id", "runner_id", "model_family", "independence_domain"):
        if len({row[field] for row in rows}) != len(rows):
            raise ValueError(f"all debate judges must have distinct {field} values")
    order = sorted(range(len(rows)), key=lambda idx: rows[idx]["judge_id"])
    ordered_specs = tuple(normalized[idx] for idx in order)
    ordered_rows = tuple(rows[idx] for idx in order)
    return ordered_specs, ordered_rows, _sha(list(ordered_rows))


def _guarded_judge(spec: DebateJudgeSpec, audit_packets: list[Dict[str, Any]]) -> Judge:
    def judge(packet: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(packet, Mapping):
            raise ValueError("judge packet must be a mapping")
        encoded = _canonical(packet)
        lowered = encoded.lower()
        # DebateTournament is supposed to omit author_agent_id.  Enforce this
        # independently so a future regression cannot silently de-blind judges.
        if b"author_agent_id" in lowered or b"author_commitment" in lowered:
            raise ValueError("judge packet leaked candidate author identity")
        for slot in ("candidate_A", "candidate_B"):
            candidate = packet.get(slot)
            if not isinstance(candidate, Mapping):
                raise ValueError("judge packet candidate is invalid")
            if set(candidate) != {"hypothesis_id", "statement", "evidence_ids"}:
                raise ValueError("judge packet contains unexpected candidate metadata")
        raw = spec.judge(json.loads(encoded.decode("utf-8")))
        if not isinstance(raw, Mapping):
            raise ValueError("external judge must return a mapping")
        audit_packets.append({
            "packet_sha256": _sha_bytes(encoded),
            "result_sha256": _sha(dict(raw)),
        })
        return raw
    return judge


def build_debate_independence_execution_receipt(
    *,
    repo_root: str | os.PathLike[str],
    candidates: Sequence[TournamentCandidate],
    judges: Sequence[DebateJudgeSpec],
    created_at_epoch: int,
    repetitions: int = 2,
) -> Dict[str, Any]:
    """Run real externally configured judges and build an auditable receipt."""
    if type(created_at_epoch) is not int or created_at_epoch <= 0:
        raise ValueError("created_at_epoch must be a positive integer")
    if type(repetitions) is not int or not _MIN_RUNS <= repetitions <= _MAX_RUNS:
        raise ValueError("repetitions must be between 2 and 5")

    root = Path(repo_root).resolve(strict=True)
    identity = repository_identity(root)
    revision = str(identity.get("revision") or "").strip().lower()
    if not identity.get("available") or not identity.get("clean") or len(revision) != 40:
        raise ValueError("debate-independence execution requires a clean Git checkout")
    tracked = _tracked_index(root)
    implementation_sha256 = _hash_tracked_regular(root, tracked, _IMPLEMENTATION_SUBJECT)
    bound_candidates, candidate_rows, candidate_commitment = _candidate_manifest(candidates)
    bound_judges, judge_rows, judge_manifest_hash = _judge_manifest(judges)

    runs = []
    for spec in bound_judges:
        judge_runs = []
        for repetition in range(repetitions):
            observed_packets: list[Dict[str, Any]] = []
            result = DebateTournament(_guarded_judge(spec, observed_packets)).run(bound_candidates)
            if not observed_packets:
                raise ValueError("external judge did not receive any debate packets")
            if result.status not in {"WINNER_SELECTED", "INCONCLUSIVE"}:
                raise ValueError("debate tournament returned an invalid status")
            match_rows = [
                {
                    "round_number": match.round_number,
                    "left_id": match.left_id,
                    "right_id": match.right_id,
                    "winner_id": match.winner_id,
                    "confidence": match.confidence,
                    "reasons_sha256": _sha(list(match.reasons)),
                    "evidence_ids_sha256": _sha(list(match.evidence_ids)),
                    "judge_hash": _safe_sha(match.judge_hash, "judge_hash"),
                }
                for match in result.matches
            ]
            payload = {
                "repetition": repetition + 1,
                "candidate_commitment": candidate_commitment,
                "judge_manifest_hash": judge_manifest_hash,
                "judge_id": spec.judge_id,
                "status": result.status,
                "winner_id": result.winner_id,
                "matches": match_rows,
                "packet_audit": observed_packets,
            }
            judge_runs.append({**payload, "run_hash": _sha(payload)})
        runs.append({
            "judge_id": spec.judge_id,
            "runs": judge_runs,
        })

    report = {
        "schema_version": _SCHEMA_VERSION,
        "created_at_epoch": created_at_epoch,
        "implementation_revision": revision,
        "implementation_subject": _IMPLEMENTATION_SUBJECT,
        "implementation_sha256": implementation_sha256,
        "candidate_manifest": list(candidate_rows),
        "candidate_commitment": candidate_commitment,
        "judge_manifest": list(judge_rows),
        "judge_manifest_hash": judge_manifest_hash,
        "repetitions_per_judge": repetitions,
        "runs": runs,
        "candidate_authorship_blinded": True,
        "external_independence_structure_satisfied": True,
        "observer_asserted_independence_domains": True,
        "hidden_provider_dependencies_ruled_out": False,
        "judge_agreement_required": False,
        "agreement_proves_truth": False,
        "truth_proven": False,
    }
    report["report_hash"] = _sha(report)
    if len(_canonical(report)) > _MAX_RECEIPT_BYTES:
        raise ValueError("debate-independence receipt exceeds size limit")
    return report


def _read_json(path: Path) -> tuple[Mapping[str, Any], bytes]:
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError("debate-independence receipt cannot be read") from exc
    if not path.is_file() or info.st_size < 1 or info.st_size > _MAX_RECEIPT_BYTES:
        raise ValueError("debate-independence receipt size is invalid")
    data = path.read_bytes()
    if len(data) != info.st_size:
        raise ValueError("debate-independence receipt changed during read")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("debate-independence receipt is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("debate-independence receipt must be a JSON object")
    return value, data


def validate_debate_independence_receipt(
    path: str | os.PathLike[str],
    *,
    repo_root: str | os.PathLike[str],
    now: float,
) -> DebateIndependenceExecutionReceipt:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    root = Path(repo_root).resolve(strict=True)
    identity = repository_identity(root)
    revision = str(identity.get("revision") or "").strip().lower()
    if not identity.get("available") or not identity.get("clean") or len(revision) != 40:
        raise ValueError("debate-independence validation requires a clean Git checkout")

    value, raw = _read_json(Path(path).expanduser().resolve())
    required = {
        "schema_version", "created_at_epoch", "implementation_revision",
        "implementation_subject", "implementation_sha256", "candidate_manifest",
        "candidate_commitment", "judge_manifest", "judge_manifest_hash",
        "repetitions_per_judge", "runs", "candidate_authorship_blinded",
        "external_independence_structure_satisfied",
        "observer_asserted_independence_domains",
        "hidden_provider_dependencies_ruled_out", "judge_agreement_required",
        "agreement_proves_truth", "truth_proven", "report_hash",
    }
    if set(value) != required or value.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("debate-independence receipt schema is invalid")
    created = value.get("created_at_epoch")
    if type(created) is not int or created <= 0:
        raise ValueError("created_at_epoch is invalid")
    age = current_time - float(created)
    if age > _MAX_RECEIPT_AGE_SECONDS:
        raise ValueError("debate-independence receipt is stale")
    if age < -_MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("debate-independence receipt is from the future")
    if str(value.get("implementation_revision") or "").lower() != revision:
        raise ValueError("debate-independence receipt revision mismatch")
    if value.get("implementation_subject") != _IMPLEMENTATION_SUBJECT:
        raise ValueError("debate-independence implementation subject mismatch")
    tracked = _tracked_index(root)
    actual_sha = _hash_tracked_regular(root, tracked, _IMPLEMENTATION_SUBJECT)
    if _safe_sha(value.get("implementation_sha256"), "implementation_sha256") != actual_sha:
        raise ValueError("debate-independence implementation hash mismatch")

    candidate_manifest = value.get("candidate_manifest")
    if not isinstance(candidate_manifest, list) or not 2 <= len(candidate_manifest) <= _MAX_CANDIDATES:
        raise ValueError("candidate manifest size is invalid")
    candidate_ids = set()
    normalized_candidates = []
    for row in candidate_manifest:
        if not isinstance(row, dict) or set(row) != {
            "hypothesis_id", "statement_sha256", "evidence_ids_sha256",
            "evidence_count", "author_commitment",
        }:
            raise ValueError("candidate manifest row is invalid")
        hypothesis_id = _safe_id(row["hypothesis_id"], "hypothesis_id")
        if hypothesis_id in candidate_ids:
            raise ValueError("candidate manifest contains duplicate hypothesis ids")
        candidate_ids.add(hypothesis_id)
        evidence_count = row.get("evidence_count")
        if type(evidence_count) is not int or evidence_count <= 0:
            raise ValueError("candidate evidence_count is invalid")
        normalized_candidates.append({
            "hypothesis_id": hypothesis_id,
            "statement_sha256": _safe_sha(row["statement_sha256"], "statement_sha256"),
            "evidence_ids_sha256": _safe_sha(row["evidence_ids_sha256"], "evidence_ids_sha256"),
            "evidence_count": evidence_count,
            "author_commitment": _safe_sha(row["author_commitment"], "author_commitment"),
        })
    normalized_candidates.sort(key=lambda row: row["hypothesis_id"])
    candidate_commitment = _safe_sha(value.get("candidate_commitment"), "candidate_commitment")
    if _sha(normalized_candidates) != candidate_commitment:
        raise ValueError("candidate commitment verification failed")

    judge_manifest = value.get("judge_manifest")
    if not isinstance(judge_manifest, list) or not _MIN_JUDGES <= len(judge_manifest) <= _MAX_JUDGES:
        raise ValueError("judge manifest size is invalid")
    normalized_judges = []
    for row in judge_manifest:
        if not isinstance(row, dict) or set(row) != {
            "judge_id", "runner_id", "model_family", "independence_domain"
        }:
            raise ValueError("judge manifest row is invalid")
        normalized_judges.append({key: _safe_id(row[key], key) for key in row})
    for field in ("judge_id", "runner_id", "model_family", "independence_domain"):
        if len({row[field] for row in normalized_judges}) != len(normalized_judges):
            raise ValueError(f"judge manifest lacks distinct {field} values")
    normalized_judges.sort(key=lambda row: row["judge_id"])
    judge_manifest_hash = _safe_sha(value.get("judge_manifest_hash"), "judge_manifest_hash")
    if _sha(normalized_judges) != judge_manifest_hash:
        raise ValueError("judge manifest hash verification failed")

    repetitions = value.get("repetitions_per_judge")
    if type(repetitions) is not int or not _MIN_RUNS <= repetitions <= _MAX_RUNS:
        raise ValueError("repetitions_per_judge is invalid")
    runs = value.get("runs")
    if not isinstance(runs, list) or len(runs) != len(normalized_judges):
        raise ValueError("receipt must contain runs for every judge")
    expected_judges = {row["judge_id"] for row in normalized_judges}
    seen_judges = set()
    for judge_row in runs:
        if not isinstance(judge_row, dict) or set(judge_row) != {"judge_id", "runs"}:
            raise ValueError("judge run row is invalid")
        judge_id = _safe_id(judge_row["judge_id"], "judge_id")
        if judge_id not in expected_judges or judge_id in seen_judges:
            raise ValueError("judge run identity is invalid")
        seen_judges.add(judge_id)
        repeated = judge_row.get("runs")
        if not isinstance(repeated, list) or len(repeated) != repetitions:
            raise ValueError("every judge must have the declared repetition count")
        for expected_index, run in enumerate(repeated, 1):
            if not isinstance(run, dict) or set(run) != {
                "repetition", "candidate_commitment", "judge_manifest_hash",
                "judge_id", "status", "winner_id", "matches", "packet_audit", "run_hash"
            }:
                raise ValueError("debate run schema is invalid")
            if run.get("repetition") != expected_index or run.get("judge_id") != judge_id:
                raise ValueError("debate run identity/repetition mismatch")
            if _safe_sha(run.get("candidate_commitment"), "candidate_commitment") != candidate_commitment:
                raise ValueError("debate run candidate commitment mismatch")
            if _safe_sha(run.get("judge_manifest_hash"), "judge_manifest_hash") != judge_manifest_hash:
                raise ValueError("debate run judge manifest mismatch")
            if run.get("status") not in {"WINNER_SELECTED", "INCONCLUSIVE"}:
                raise ValueError("debate run status is invalid")
            winner = run.get("winner_id")
            if winner is not None and _safe_id(winner, "winner_id") not in candidate_ids:
                raise ValueError("debate run winner_id is invalid")
            matches = run.get("matches")
            packets = run.get("packet_audit")
            if not isinstance(matches, list) or not matches:
                raise ValueError("debate run must contain at least one match")
            if not isinstance(packets, list) or len(packets) != len(matches):
                raise ValueError("packet audit must account for every debate match")
            for packet in packets:
                if not isinstance(packet, dict) or set(packet) != {"packet_sha256", "result_sha256"}:
                    raise ValueError("packet audit row is invalid")
                _safe_sha(packet["packet_sha256"], "packet_sha256")
                _safe_sha(packet["result_sha256"], "result_sha256")
            for match in matches:
                if not isinstance(match, dict) or set(match) != {
                    "round_number", "left_id", "right_id", "winner_id", "confidence",
                    "reasons_sha256", "evidence_ids_sha256", "judge_hash"
                }:
                    raise ValueError("debate match row is invalid")
                if type(match.get("round_number")) is not int or match["round_number"] <= 0:
                    raise ValueError("debate match round_number is invalid")
                left = _safe_id(match.get("left_id"), "left_id")
                right = _safe_id(match.get("right_id"), "right_id")
                if left == right or left not in candidate_ids or right not in candidate_ids:
                    raise ValueError("debate match candidate ids are invalid")
                match_winner = match.get("winner_id")
                if match_winner is not None and match_winner not in {left, right}:
                    raise ValueError("debate match winner is invalid")
                confidence = match.get("confidence")
                if confidence is not None:
                    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                        raise ValueError("debate match confidence is invalid")
                    confidence = float(confidence)
                    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
                        raise ValueError("debate match confidence is invalid")
                _safe_sha(match.get("reasons_sha256"), "reasons_sha256")
                _safe_sha(match.get("evidence_ids_sha256"), "evidence_ids_sha256")
                _safe_sha(match.get("judge_hash"), "judge_hash")
            payload = {key: val for key, val in run.items() if key != "run_hash"}
            if _safe_sha(run.get("run_hash"), "run_hash") != _sha(payload):
                raise ValueError("debate run_hash verification failed")
    if seen_judges != expected_judges:
        raise ValueError("receipt is missing a judge run")

    if value.get("candidate_authorship_blinded") is not True:
        raise ValueError("candidate authorship blinding was not attested")
    if value.get("external_independence_structure_satisfied") is not True:
        raise ValueError("external independence structure did not pass")
    if value.get("observer_asserted_independence_domains") is not True:
        raise ValueError("independence domains were not observer-attested")
    if value.get("hidden_provider_dependencies_ruled_out") is not False:
        raise ValueError("receipt must not overclaim hidden dependency exclusion")
    if value.get("judge_agreement_required") is not False:
        raise ValueError("independent validation must not require judge agreement")
    if value.get("agreement_proves_truth") is not False or value.get("truth_proven") is not False:
        raise ValueError("debate independence receipt must not claim truth")
    claimed_report_hash = _safe_sha(value.get("report_hash"), "report_hash")
    payload = {key: val for key, val in value.items() if key != "report_hash"}
    if _sha(payload) != claimed_report_hash:
        raise ValueError("debate-independence report_hash verification failed")

    return DebateIndependenceExecutionReceipt(
        revision=revision,
        created_at_epoch=created,
        sha256=_sha_bytes(raw),
        report_hash=claimed_report_hash,
        candidate_commitment=candidate_commitment,
        judge_manifest_hash=judge_manifest_hash,
        run_count=len(normalized_judges) * repetitions,
    )


def _same_receipt(row: Mapping[str, Any], *, digest: str, reference: str, revision: str) -> bool:
    expected = {
        "capability_id": _CAPABILITY_ID,
        "proof_kind": _PROOF_KIND.value,
        "subject": _SUBJECT,
        "subject_sha256": digest,
        "verifier": _VERIFIER,
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_debate_independence(
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
) -> DebateIndependenceAttestation:
    observation = _safe_id(observation_id, "observation_id")
    root = Path(repo_root).resolve(strict=True)
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")
    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "").strip().lower()
    if not identity_before.get("available") or not identity_before.get("clean") or len(revision) != 40:
        raise ValueError("debate-independence attestation requires a clean Git checkout")

    validated = validate_debate_independence_receipt(
        execution_receipt_path,
        repo_root=root,
        now=now,
    )
    if validated.revision != revision:
        raise ValueError("debate-independence receipt revision changed during validation")
    tracked = _tracked_index(root)
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    reference = f"{_REFERENCE_PREFIX}c{_CAPABILITY_ID}:{observation}"
    matching = tuple(
        rule for rule in policy.rules
        if rule.capability_id == _CAPABILITY_ID
        and rule.proof_kind is _PROOF_KIND
        and _SUBJECT in rule.subjects
        and _VERIFIER in rule.verifiers
    )
    if not matching:
        raise ValueError("committed proof policy has no trusted debate independence route")
    if not any(
        not rule.reference_prefixes
        or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
        for rule in matching
    ):
        raise ValueError("debate independence reference is not allowed by proof policy")

    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or len(prior) != 40:
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not continuity.verify_chain(anchor_token=prior_anchor_token, current_revision=prior):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    digest = _sha({
        "execution_receipt_sha256": validated.sha256,
        "report_hash": validated.report_hash,
        "candidate_commitment": validated.candidate_commitment,
        "judge_manifest_hash": validated.judge_manifest_hash,
        "run_count": validated.run_count,
        "revision": revision,
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    receipt_id = f"debate-independence:{revision[:12]}:c{_CAPABILITY_ID}"
    previous = existing.get(receipt_id)
    if previous is not None:
        if not _same_receipt(previous, digest=digest, reference=reference, revision=revision):
            raise ValueError("deterministic debate-independence receipt_id collision")
        added, reused = 0, 1
    else:
        ledger.add(
            receipt_id=receipt_id,
            capability_id=_CAPABILITY_ID,
            proof_kind=_PROOF_KIND,
            subject=_SUBJECT,
            subject_sha256=digest,
            verifier=_VERIFIER,
            observed_at=float(now),
            reference=reference,
            implementation_revision=revision,
        )
        added, reused = 1, 0

    anchor = ledger.create_anchor(current_revision=revision, issued_at=float(now))
    audit = audit_repository_maturity(
        repo_root=root,
        ledger_path=ledger_target,
        integrity_key=integrity_key,
        anchor_token=anchor,
        now=float(now),
        policy_path=policy_path,
    )
    if not audit.audit_valid:
        raise ValueError("trusted maturity audit rejected debate-independence attestation")
    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "").strip().lower() != revision
    ):
        raise ValueError("repository changed during debate-independence attestation")

    return DebateIndependenceAttestation(
        revision=revision,
        execution_receipt_sha256=validated.sha256,
        report_hash=validated.report_hash,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
        hidden_provider_dependencies_ruled_out=False,
        truth_proven=False,
    )
