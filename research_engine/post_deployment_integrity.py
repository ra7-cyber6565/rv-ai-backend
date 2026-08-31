"""Deep integrity verification for persisted post-deployment monitor state.

The stateful drift monitor already keeps deterministic baseline/batch hashes and
an event hash-chain.  This verifier closes a stronger boundary needed by trusted
maturity attestation: it recomputes the hashes of persisted baseline objects,
feature references and batch analyses, binds every audit event back to the exact
persisted payload, and checks the materialized model-state summary against batch
history.

It is deliberately read-only.  It does not mutate monitor state, retrain a model,
claim a deployment is healthy, or mint maturity evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple


_SCHEMA_VERSION = 1
_MAX_STATE_BYTES = 64 * 1024 * 1024
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_ALLOWED_BATCH_STATUSES = {
    "HEALTHY",
    "OBSERVING",
    "WATCH",
    "DEGRADED",
    "INSUFFICIENT_DATA",
    "SCHEMA_MISMATCH",
}
_NON_STREAK_STATUSES = {"INSUFFICIENT_DATA", "SCHEMA_MISMATCH"}


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
        raise ValueError("post-deployment state must contain finite JSON") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_sha(value: object, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA_RE.fullmatch(text):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return text


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _finite(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _read_state(path: Path) -> tuple[Mapping[str, Any], bytes]:
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError("post-deployment state cannot be read") from exc
    if not path.is_file() or not 1 <= info.st_size <= _MAX_STATE_BYTES:
        raise ValueError("post-deployment state size is invalid")
    data = path.read_bytes()
    if len(data) != info.st_size:
        raise ValueError("post-deployment state changed during read")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("post-deployment state is not valid UTF-8 JSON") from exc
    return _mapping(value, "post-deployment state"), data


@dataclass(frozen=True)
class VerifiedPostDeploymentState:
    project_id: str
    state_sha256: str
    event_head_hash: str
    event_count: int
    model_ids: Tuple[str, ...]
    baseline_hashes: Tuple[str, ...]
    batch_ids: Tuple[str, ...]
    batch_analysis_hashes: Tuple[str, ...]
    latest_observed_at_epoch: float


def verify_post_deployment_state(
    path: str | Path,
    *,
    expected_project_id: str = "",
) -> VerifiedPostDeploymentState:
    """Fail closed unless the persisted monitor snapshot is internally bound."""
    state, raw = _read_state(Path(path).expanduser().resolve())
    if set(state) != {
        "schema_version",
        "project_id",
        "baselines",
        "batches",
        "model_state",
        "events",
    }:
        raise ValueError("post-deployment state root schema is invalid")
    if state.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("unsupported post-deployment state schema_version")
    project_id = _safe_id(state.get("project_id"), "project_id")
    if expected_project_id and project_id != _safe_id(expected_project_id, "expected_project_id"):
        raise ValueError("post-deployment project_id does not match expected project")

    baselines = _mapping(state.get("baselines"), "baselines")
    batches = _mapping(state.get("batches"), "batches")
    model_state = _mapping(state.get("model_state"), "model_state")
    events = state.get("events")
    if not isinstance(events, list):
        raise ValueError("events must be a list")
    if not baselines:
        raise ValueError("post-deployment state has no registered baselines")

    baseline_hashes: Dict[str, str] = {}
    for raw_model_id, raw_baseline in baselines.items():
        model_id = _safe_id(raw_model_id, "baseline model_id")
        baseline = dict(_mapping(raw_baseline, f"baseline[{model_id}]"))
        if baseline.get("model_id") != model_id:
            raise ValueError(f"baseline model_id mismatch for {model_id}")
        recorded = _safe_sha(baseline.get("baseline_hash"), f"baseline[{model_id}].baseline_hash")
        body = dict(baseline)
        body.pop("baseline_hash", None)
        if _hash(body) != recorded:
            raise ValueError(f"baseline hash mismatch for {model_id}")
        features = _mapping(baseline.get("features"), f"baseline[{model_id}].features")
        if not features:
            raise ValueError(f"baseline {model_id} has no feature references")
        for raw_name, raw_feature in features.items():
            feature = _safe_id(raw_name, "feature")
            row = _mapping(raw_feature, f"baseline[{model_id}].features[{feature}]")
            reference_hash = _safe_sha(
                row.get("reference_hash"),
                f"baseline[{model_id}].features[{feature}].reference_hash",
            )
            kind = str(row.get("kind") or "")
            if kind == "numeric":
                reference = row.get("reference")
                if not isinstance(reference, list) or not reference:
                    raise ValueError(f"numeric feature {feature} has no reference values")
                if _hash(reference) != reference_hash:
                    raise ValueError(f"numeric feature reference hash mismatch: {feature}")
            elif kind == "categorical":
                counts = _mapping(row.get("counts"), f"feature {feature} counts")
                if not counts or _hash(counts) != reference_hash:
                    raise ValueError(f"categorical feature reference hash mismatch: {feature}")
            else:
                raise ValueError(f"unsupported persisted feature kind: {kind}")
        baseline_hashes[model_id] = recorded

    if set(str(key) for key in model_state) != set(baseline_hashes):
        raise ValueError("model_state keys must match registered baselines exactly")

    batch_records: Dict[tuple[str, str], Mapping[str, Any]] = {}
    batch_analysis_hashes: Dict[tuple[str, str], str] = {}
    for raw_key, raw_record in batches.items():
        record = _mapping(raw_record, f"batch[{raw_key}]")
        model_id = _safe_id(record.get("model_id"), "batch model_id")
        batch_id = _safe_id(record.get("batch_id"), "batch_id")
        if model_id not in baseline_hashes:
            raise ValueError(f"batch references unknown model: {model_id}")
        expected_key = f"{model_id}|{batch_id}"
        if str(raw_key) != expected_key:
            raise ValueError(f"batch key mismatch: {raw_key}")
        if _safe_sha(record.get("baseline_hash"), "batch baseline_hash") != baseline_hashes[model_id]:
            raise ValueError(f"batch baseline hash mismatch: {batch_id}")
        status = str(record.get("status") or "")
        if status not in _ALLOWED_BATCH_STATUSES:
            raise ValueError(f"batch status is invalid: {batch_id}")
        observed_at = _finite(record.get("observed_at_epoch"), "batch observed_at_epoch")
        if observed_at <= 0:
            raise ValueError("batch observed_at_epoch must be > 0")
        analysis_hash = _safe_sha(record.get("analysis_hash"), "batch analysis_hash")
        _safe_sha(record.get("input_fingerprint"), "batch input_fingerprint")
        analysis_body = dict(record)
        analysis_body.pop("analysis_hash", None)
        analysis_body.pop("input_fingerprint", None)
        if _hash(analysis_body) != analysis_hash:
            raise ValueError(f"batch analysis hash mismatch: {batch_id}")
        key = (model_id, batch_id)
        if key in batch_records:
            raise ValueError("duplicate post-deployment batch identity")
        batch_records[key] = record
        batch_analysis_hashes[key] = analysis_hash

    # Reconstruct each materialized model-state summary from its immutable
    # baseline plus chronological batch history. Schema/insufficient windows do
    # not update the stored drift streak by design.
    latest_observed = 0.0
    for model_id, baseline_hash in baseline_hashes.items():
        del baseline_hash  # identity already checked above
        baseline = baselines[model_id]
        baseline_time = _finite(baseline.get("observed_at_epoch"), "baseline observed_at_epoch")
        rows = [
            row for (candidate, _batch), row in batch_records.items()
            if candidate == model_id
        ]
        rows.sort(key=lambda row: (float(row["observed_at_epoch"]), str(row["batch_id"])))
        previous_time = baseline_time
        expected_status = "OBSERVING"
        expected_streak = 0
        for row in rows:
            current_time = float(row["observed_at_epoch"])
            if current_time < previous_time:
                raise ValueError(f"batch history is not monotonic for {model_id}")
            previous_time = current_time
            expected_status = str(row["status"])
            if expected_status not in _NON_STREAK_STATUSES:
                expected_streak = int(row.get("drift_streak", -1))
                if expected_streak < 0:
                    raise ValueError("batch drift_streak is invalid")
        summary = _mapping(model_state.get(model_id), f"model_state[{model_id}]")
        if int(summary.get("drift_streak", -1)) != expected_streak:
            raise ValueError(f"model_state drift_streak mismatch for {model_id}")
        if str(summary.get("last_status") or "") != expected_status:
            raise ValueError(f"model_state last_status mismatch for {model_id}")
        if _finite(summary.get("last_observed_at_epoch"), "model_state last_observed_at_epoch") != previous_time:
            raise ValueError(f"model_state timestamp mismatch for {model_id}")
        latest_observed = max(latest_observed, previous_time)

    expected_payloads: Dict[tuple[str, str, str], str] = {}
    for model_id, baseline in baselines.items():
        expected_payloads[("BASELINE_REGISTERED", str(model_id), str(model_id))] = _hash(baseline)
    for (model_id, batch_id), record in batch_records.items():
        expected_payloads[("BATCH_VALIDATED", model_id, batch_id)] = _hash(record)

    seen_payloads = set()
    previous = "GENESIS"
    for index, raw_event in enumerate(events, start=1):
        event = _mapping(raw_event, f"event[{index}]")
        if event.get("sequence") != index:
            raise ValueError(f"post-deployment event sequence mismatch at {index}")
        if event.get("previous_hash") != previous:
            raise ValueError(f"post-deployment event chain broken at {index}")
        kind = str(event.get("kind") or "")
        model_id = _safe_id(event.get("model_id"), "event model_id")
        object_id = _safe_id(event.get("object_id"), "event object_id")
        identity = (kind, model_id, object_id)
        expected_payload_hash = expected_payloads.get(identity)
        if expected_payload_hash is None:
            raise ValueError(f"event does not map to a persisted payload: {identity}")
        if identity in seen_payloads:
            raise ValueError(f"duplicate post-deployment audit event: {identity}")
        if _safe_sha(event.get("payload_hash"), "event payload_hash") != expected_payload_hash:
            raise ValueError(f"event payload hash mismatch at {index}")
        body = {
            "sequence": event.get("sequence"),
            "kind": kind,
            "model_id": model_id,
            "object_id": object_id,
            "payload_hash": expected_payload_hash,
            "previous_hash": previous,
        }
        event_hash = _safe_sha(event.get("event_hash"), "event_hash")
        if _hash(body) != event_hash:
            raise ValueError(f"post-deployment audit hash mismatch at event {index}")
        seen_payloads.add(identity)
        previous = event_hash

    if seen_payloads != set(expected_payloads):
        missing = sorted(set(expected_payloads) - seen_payloads)
        raise ValueError(f"persisted post-deployment payloads lack audit events: {missing[:3]}")

    return VerifiedPostDeploymentState(
        project_id=project_id,
        state_sha256=hashlib.sha256(raw).hexdigest(),
        event_head_hash=previous,
        event_count=len(events),
        model_ids=tuple(sorted(baseline_hashes)),
        baseline_hashes=tuple(baseline_hashes[key] for key in sorted(baseline_hashes)),
        batch_ids=tuple(
            batch_id for _model, batch_id in sorted(batch_records)
        ),
        batch_analysis_hashes=tuple(
            batch_analysis_hashes[key] for key in sorted(batch_analysis_hashes)
        ),
        latest_observed_at_epoch=latest_observed,
    )
