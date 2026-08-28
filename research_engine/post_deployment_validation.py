"""Persistent distribution-shift and post-deployment validation foundation.

The monitor is deliberately conservative:

* a stable feature distribution is **not** treated as validated model quality;
* missing outcome metrics produce ``NO_OUTCOME_DATA`` rather than success;
* schema mismatches and undersized windows fail closed;
* one noisy window produces ``WATCH``; configurable consecutive drift windows
  are required before ``DEGRADED``;
* the monitor never retrains, promotes, rolls back, or mutates a model;
* live/runtime maturity still requires independent deployment evidence outside
  this module and its unit tests.

Inputs are normalized batch observations supplied by an outer runtime adapter.
No network access, model execution, or privileged side effects occur here.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .statistical_validation import population_stability_index


_SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_ALLOWED_KINDS = {"numeric", "categorical"}
_ALLOWED_DIRECTIONS = {"max", "min"}
_ALLOWED_STATUSES = {
    "HEALTHY",
    "OBSERVING",
    "WATCH",
    "DEGRADED",
    "INSUFFICIENT_DATA",
    "SCHEMA_MISMATCH",
}
_MAX_FEATURES = 500
_MAX_VALUES_PER_FEATURE = 100_000
_MAX_REFERENCE_VALUES = 10_000
_MAX_CATEGORIES = 5_000


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is empty or invalid")
    return text


def _finite(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _nonnegative(value: object, field: str) -> float:
    number = _finite(value, field)
    if number < 0:
        raise ValueError(f"{field} must be >= 0")
    return number


def _probability(value: object, field: str) -> float:
    number = _finite(value, field)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be in [0,1]")
    return number


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _downsample_sorted(values: Sequence[float], limit: int = _MAX_REFERENCE_VALUES) -> Tuple[float, ...]:
    ordered = sorted(float(value) for value in values)
    if len(ordered) <= limit:
        return tuple(ordered)
    # Deterministic quantile-grid sample.  Endpoints are retained and repeated
    # calls over the same reference produce the same persisted fingerprint.
    last = len(ordered) - 1
    indices = [round(index * last / (limit - 1)) for index in range(limit)]
    return tuple(ordered[index] for index in indices)


def _categorical_counts(values: Sequence[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _jensen_shannon_from_counts(
    reference: Mapping[str, int],
    current: Mapping[str, int],
) -> float:
    ref_total = sum(int(value) for value in reference.values())
    cur_total = sum(int(value) for value in current.values())
    if ref_total <= 0 or cur_total <= 0:
        raise ValueError("categorical distributions must contain observations")
    keys = sorted(set(reference) | set(current))
    js = 0.0
    for key in keys:
        p = max(0, int(reference.get(key, 0))) / ref_total
        q = max(0, int(current.get(key, 0))) / cur_total
        midpoint = (p + q) / 2.0
        if p > 0:
            js += 0.5 * p * math.log(p / midpoint)
        if q > 0:
            js += 0.5 * q * math.log(q / midpoint)
    # Normalize natural-log JSD to [0,1].
    return round(js / math.log(2.0), 12)


def _normalize_feature_values(
    feature: str,
    kind: str,
    values: Sequence[Any],
) -> tuple[list[Any], float, int]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise ValueError(f"feature {feature} values must be a sequence")
    if len(values) > _MAX_VALUES_PER_FEATURE:
        raise ValueError(f"feature {feature} exceeds the per-window value limit")
    missing = 0
    clean: list[Any] = []
    for index, value in enumerate(values):
        if value is None:
            missing += 1
            continue
        if kind == "numeric":
            clean.append(_finite(value, f"{feature}[{index}]"))
        else:
            text = str(value)
            if len(text) > 1000:
                raise ValueError(f"{feature}[{index}] categorical value is too long")
            clean.append(text)
    total = len(values)
    missing_rate = (missing / total) if total else 1.0
    return clean, missing_rate, total


@dataclass(frozen=True)
class DriftPolicy:
    min_batch_samples: int = 30
    psi_warning: float = 0.10
    psi_high: float = 0.25
    categorical_js_warning: float = 0.05
    categorical_js_high: float = 0.15
    missingness_delta_warning: float = 0.05
    missingness_delta_high: float = 0.15
    confirmation_windows: int = 2
    numeric_bins: int = 10

    def validate(self) -> None:
        if not isinstance(self.min_batch_samples, int) or self.min_batch_samples < 2:
            raise ValueError("min_batch_samples must be an integer >= 2")
        if not isinstance(self.confirmation_windows, int) or self.confirmation_windows < 1:
            raise ValueError("confirmation_windows must be an integer >= 1")
        if not isinstance(self.numeric_bins, int) or not 2 <= self.numeric_bins <= 100:
            raise ValueError("numeric_bins must be between 2 and 100")
        pairs = (
            (self.psi_warning, self.psi_high, "psi"),
            (self.categorical_js_warning, self.categorical_js_high, "categorical_js"),
            (self.missingness_delta_warning, self.missingness_delta_high, "missingness_delta"),
        )
        for warning, high, name in pairs:
            warning_value = _nonnegative(warning, f"{name}_warning")
            high_value = _nonnegative(high, f"{name}_high")
            if high_value < warning_value:
                raise ValueError(f"{name}_high must be >= warning threshold")

    def as_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "min_batch_samples": self.min_batch_samples,
            "psi_warning": float(self.psi_warning),
            "psi_high": float(self.psi_high),
            "categorical_js_warning": float(self.categorical_js_warning),
            "categorical_js_high": float(self.categorical_js_high),
            "missingness_delta_warning": float(self.missingness_delta_warning),
            "missingness_delta_high": float(self.missingness_delta_high),
            "confirmation_windows": self.confirmation_windows,
            "numeric_bins": self.numeric_bins,
        }


@dataclass(frozen=True)
class MetricRule:
    baseline: float
    direction: str
    max_relative_degradation: float = 0.10
    max_absolute_degradation: Optional[float] = None

    def validate(self, metric: str) -> None:
        _finite(self.baseline, f"{metric}.baseline")
        if self.direction not in _ALLOWED_DIRECTIONS:
            raise ValueError(f"{metric}.direction must be max or min")
        _probability(self.max_relative_degradation, f"{metric}.max_relative_degradation")
        if self.max_absolute_degradation is not None:
            _nonnegative(self.max_absolute_degradation, f"{metric}.max_absolute_degradation")

    def as_dict(self, metric: str) -> Dict[str, Any]:
        self.validate(metric)
        return {
            "baseline": float(self.baseline),
            "direction": self.direction,
            "max_relative_degradation": float(self.max_relative_degradation),
            "max_absolute_degradation": (
                None if self.max_absolute_degradation is None else float(self.max_absolute_degradation)
            ),
        }


@dataclass(frozen=True)
class BatchValidation:
    model_id: str
    batch_id: str
    status: str
    outcome_status: str
    drift_streak: int
    confirmed_drift: bool
    feature_findings: Tuple[Mapping[str, Any], ...]
    performance_findings: Tuple[Mapping[str, Any], ...]
    analysis_hash: str
    automatic_model_change_allowed: bool = False


class PostDeploymentValidator:
    """Persistent, deterministic monitor over normalized post-deployment batches."""

    def __init__(self, directory: str, project_id: str = "default"):
        self.directory = os.path.abspath(os.path.expanduser(str(directory)))
        self.project_id = _safe_id(project_id, "project_id")
        self._data: Optional[Dict[str, Any]] = None

    @property
    def path(self) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", self.project_id)
        return os.path.join(self.directory, f"{safe}.post-deployment.json")

    def _blank(self) -> Dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "project_id": self.project_id,
            "baselines": {},
            "batches": {},
            "model_state": {},
            "events": [],
        }

    def load(self) -> Dict[str, Any]:
        if self._data is not None:
            return self._data
        if not os.path.exists(self.path):
            self._data = self._blank()
            return self._data
        with open(self.path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("post-deployment state root must be an object")
        if data.get("schema_version") != _SCHEMA_VERSION or data.get("project_id") != self.project_id:
            raise ValueError("post-deployment state schema/project mismatch")
        for field in ("baselines", "batches", "model_state"):
            if not isinstance(data.get(field), dict):
                raise ValueError(f"invalid post-deployment state field: {field}")
        if not isinstance(data.get("events"), list):
            raise ValueError("invalid post-deployment events field")
        self._data = data
        return data

    def save(self) -> None:
        data = self.load()
        os.makedirs(self.directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=".postdeploy_", suffix=".json", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def _event(self, kind: str, model_id: str, object_id: str, payload: Mapping[str, Any]) -> None:
        events = self.load()["events"]
        previous = events[-1]["event_hash"] if events else "GENESIS"
        body = {
            "sequence": len(events) + 1,
            "kind": kind,
            "model_id": model_id,
            "object_id": object_id,
            "payload_hash": _hash(payload),
            "previous_hash": previous,
        }
        events.append({**body, "event_hash": _hash(body)})

    def audit_integrity(self) -> Mapping[str, Any]:
        previous = "GENESIS"
        for index, event in enumerate(self.load()["events"], start=1):
            if event.get("previous_hash") != previous:
                raise ValueError(f"post-deployment audit chain broken at event {index}")
            body = {
                "sequence": event.get("sequence"),
                "kind": event.get("kind"),
                "model_id": event.get("model_id"),
                "object_id": event.get("object_id"),
                "payload_hash": event.get("payload_hash"),
                "previous_hash": event.get("previous_hash"),
            }
            expected = _hash(body)
            if event.get("event_hash") != expected:
                raise ValueError(f"post-deployment audit hash mismatch at event {index}")
            previous = expected
        return {"valid": True, "events": len(self.load()["events"]), "head_hash": previous}

    def register_baseline(
        self,
        model_id: str,
        *,
        feature_kinds: Mapping[str, str],
        feature_samples: Mapping[str, Sequence[Any]],
        observed_at_epoch: float,
        policy: DriftPolicy = DriftPolicy(),
        metric_rules: Optional[Mapping[str, MetricRule]] = None,
        implementation_hash: str,
        dataset_hash: str,
    ) -> Mapping[str, Any]:
        model_id = _safe_id(model_id, "model_id")
        observed_at = _nonnegative(observed_at_epoch, "observed_at_epoch")
        if observed_at <= 0:
            raise ValueError("observed_at_epoch must be > 0")
        policy.validate()
        if not feature_kinds or len(feature_kinds) > _MAX_FEATURES:
            raise ValueError("feature_kinds must contain 1..500 features")
        expected_features = tuple(sorted(str(name) for name in feature_kinds))
        if tuple(sorted(str(name) for name in feature_samples)) != expected_features:
            raise ValueError("baseline feature schema and sample keys must match exactly")
        if not str(implementation_hash).strip() or not str(dataset_hash).strip():
            raise ValueError("implementation_hash and dataset_hash are required")

        features: Dict[str, Any] = {}
        for feature in expected_features:
            _safe_id(feature, "feature")
            kind = str(feature_kinds[feature]).lower().strip()
            if kind not in _ALLOWED_KINDS:
                raise ValueError(f"unsupported feature kind for {feature}: {kind}")
            clean, missing_rate, total = _normalize_feature_values(feature, kind, feature_samples[feature])
            if total < policy.min_batch_samples or len(clean) < policy.min_batch_samples:
                raise ValueError(f"baseline feature {feature} has insufficient observations")
            if kind == "numeric":
                reference = _downsample_sorted(clean)
                if len(reference) < policy.numeric_bins:
                    raise ValueError(f"baseline feature {feature} is too small for numeric bins")
                feature_record = {
                    "kind": kind,
                    "count": total,
                    "nonmissing_count": len(clean),
                    "missing_rate": round(missing_rate, 12),
                    "reference": list(reference),
                    "reference_hash": _hash(reference),
                }
            else:
                counts = _categorical_counts([str(value) for value in clean])
                if len(counts) > _MAX_CATEGORIES:
                    raise ValueError(f"baseline feature {feature} has too many categories")
                feature_record = {
                    "kind": kind,
                    "count": total,
                    "nonmissing_count": len(clean),
                    "missing_rate": round(missing_rate, 12),
                    "counts": counts,
                    "reference_hash": _hash(counts),
                }
            features[feature] = feature_record

        metrics: Dict[str, Any] = {}
        for metric, rule in sorted((metric_rules or {}).items()):
            _safe_id(metric, "metric")
            if not isinstance(rule, MetricRule):
                raise ValueError(f"metric rule {metric} must be MetricRule")
            metrics[metric] = rule.as_dict(metric)

        baseline = {
            "model_id": model_id,
            "observed_at_epoch": observed_at,
            "policy": policy.as_dict(),
            "features": features,
            "metric_rules": metrics,
            "implementation_hash": str(implementation_hash).strip(),
            "dataset_hash": str(dataset_hash).strip(),
        }
        baseline["baseline_hash"] = _hash(baseline)
        store = self.load()["baselines"]
        existing = store.get(model_id)
        if existing is not None:
            if existing.get("baseline_hash") != baseline["baseline_hash"]:
                raise ValueError("model baseline is immutable; register a new model/version id")
            return dict(existing)
        store[model_id] = baseline
        self.load()["model_state"][model_id] = {
            "drift_streak": 0,
            "last_observed_at_epoch": observed_at,
            "last_status": "OBSERVING",
        }
        self._event("BASELINE_REGISTERED", model_id, model_id, baseline)
        return dict(baseline)

    @staticmethod
    def _metric_degradation(rule: Mapping[str, Any], observed: float) -> tuple[float, float, bool]:
        baseline = float(rule["baseline"])
        direction = str(rule["direction"])
        absolute = (baseline - observed) if direction == "max" else (observed - baseline)
        harmful_absolute = max(0.0, absolute)
        denominator = max(abs(baseline), 1e-12)
        relative = harmful_absolute / denominator
        relative_limit = float(rule["max_relative_degradation"])
        absolute_limit = rule.get("max_absolute_degradation")
        breached = relative > relative_limit
        if absolute_limit is not None:
            breached = breached or harmful_absolute > float(absolute_limit)
        return harmful_absolute, relative, breached

    def observe_batch(
        self,
        model_id: str,
        batch_id: str,
        *,
        feature_samples: Mapping[str, Sequence[Any]],
        observed_at_epoch: float,
        observed_metrics: Optional[Mapping[str, float]] = None,
    ) -> BatchValidation:
        model_id = _safe_id(model_id, "model_id")
        batch_id = _safe_id(batch_id, "batch_id")
        baseline = self.load()["baselines"].get(model_id)
        if not baseline:
            raise KeyError(f"no baseline registered for model {model_id}")
        observed_at = _nonnegative(observed_at_epoch, "observed_at_epoch")
        if observed_at <= float(baseline["observed_at_epoch"]):
            raise ValueError("batch observation must occur after the baseline")
        state = self.load()["model_state"][model_id]
        if observed_at < float(state["last_observed_at_epoch"]):
            raise ValueError("post-deployment batch timestamps must be monotonic")

        # Validate known scientific fields before provenance fingerprinting.  A
        # serializer error must never mask the actual domain failure (e.g. NaN).
        if not isinstance(feature_samples, Mapping):
            raise ValueError("feature_samples must be a mapping")
        baseline_features = baseline.get("features") or {}
        for raw_feature, values in feature_samples.items():
            feature = str(raw_feature)
            reference = baseline_features.get(feature)
            if reference is not None:
                _normalize_feature_values(feature, str(reference["kind"]), values)
        if observed_metrics is not None:
            if not isinstance(observed_metrics, Mapping):
                raise ValueError("observed_metrics must be a mapping")
            for raw_metric, value in observed_metrics.items():
                metric = str(raw_metric)
                _finite(value, f"observed_metrics[{metric}]")

        batch_key = f"{model_id}|{batch_id}"
        existing = self.load()["batches"].get(batch_key)
        fingerprint_payload = {
            "model_id": model_id,
            "batch_id": batch_id,
            "observed_at_epoch": observed_at,
            "feature_samples": feature_samples,
            "observed_metrics": observed_metrics,
        }
        try:
            input_fingerprint = _hash(fingerprint_payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "batch inputs must be finite JSON-compatible values"
            ) from exc
        if existing is not None:
            if existing.get("input_fingerprint") != input_fingerprint:
                raise ValueError("batch_id is immutable and was already observed with different input")
            return self._result_from_record(existing)

        expected = set(baseline["features"])
        supplied = {str(name) for name in feature_samples}
        feature_findings: list[Dict[str, Any]] = []
        performance_findings: list[Dict[str, Any]] = []
        raw_drift = False
        high_drift = False
        insufficient = False
        schema_mismatch = expected != supplied
        policy = baseline["policy"]

        if schema_mismatch:
            feature_findings.append({
                "feature": "*schema*",
                "kind": "SCHEMA_MISMATCH",
                "severity": "HIGH",
                "missing_features": sorted(expected - supplied),
                "unexpected_features": sorted(supplied - expected),
            })
        else:
            for feature in sorted(expected):
                reference = baseline["features"][feature]
                kind = reference["kind"]
                clean, missing_rate, total = _normalize_feature_values(feature, kind, feature_samples[feature])
                if total < int(policy["min_batch_samples"]) or len(clean) < int(policy["min_batch_samples"]):
                    insufficient = True
                    feature_findings.append({
                        "feature": feature,
                        "kind": "INSUFFICIENT_DATA",
                        "severity": "HIGH",
                        "count": total,
                        "nonmissing_count": len(clean),
                    })
                    continue

                missing_delta = abs(float(reference["missing_rate"]) - missing_rate)
                finding: Dict[str, Any] = {
                    "feature": feature,
                    "kind": kind,
                    "count": total,
                    "nonmissing_count": len(clean),
                    "missing_rate": round(missing_rate, 12),
                    "missingness_delta": round(missing_delta, 12),
                    "severity": "NONE",
                }
                if kind == "numeric":
                    psi = population_stability_index(
                        reference["reference"],
                        [float(value) for value in clean],
                        bins=int(policy["numeric_bins"]),
                    )
                    finding["psi"] = psi
                    distribution_warning = psi >= float(policy["psi_warning"])
                    distribution_high = psi >= float(policy["psi_high"])
                else:
                    counts = _categorical_counts([str(value) for value in clean])
                    if len(counts) > _MAX_CATEGORIES:
                        raise ValueError(f"feature {feature} has too many categories")
                    js = _jensen_shannon_from_counts(reference["counts"], counts)
                    finding["jensen_shannon"] = js
                    distribution_warning = js >= float(policy["categorical_js_warning"])
                    distribution_high = js >= float(policy["categorical_js_high"])

                missing_warning = missing_delta >= float(policy["missingness_delta_warning"])
                missing_high = missing_delta >= float(policy["missingness_delta_high"])
                if distribution_high or missing_high:
                    finding["severity"] = "HIGH"
                    high_drift = True
                    raw_drift = True
                elif distribution_warning or missing_warning:
                    finding["severity"] = "WARNING"
                    raw_drift = True
                feature_findings.append(finding)

        metric_rules = baseline.get("metric_rules") or {}
        metrics = observed_metrics or {}
        outcome_status = "NO_OUTCOME_DATA" if not metric_rules or not metrics else "OBSERVED"
        if metric_rules and metrics:
            missing_metrics = sorted(set(metric_rules) - set(metrics))
            unexpected_metrics = sorted(set(metrics) - set(metric_rules))
            if missing_metrics or unexpected_metrics:
                schema_mismatch = True
                performance_findings.append({
                    "metric": "*schema*",
                    "kind": "METRIC_SCHEMA_MISMATCH",
                    "severity": "HIGH",
                    "missing_metrics": missing_metrics,
                    "unexpected_metrics": unexpected_metrics,
                })
                outcome_status = "METRIC_SCHEMA_MISMATCH"
            else:
                performance_breach = False
                for metric in sorted(metric_rules):
                    observed = _finite(metrics[metric], f"observed_metrics[{metric}]")
                    harmful_absolute, relative, breached = self._metric_degradation(metric_rules[metric], observed)
                    performance_findings.append({
                        "metric": metric,
                        "baseline": float(metric_rules[metric]["baseline"]),
                        "observed": observed,
                        "harmful_absolute_change": round(harmful_absolute, 12),
                        "relative_degradation": round(relative, 12),
                        "breached": breached,
                        "severity": "HIGH" if breached else "NONE",
                    })
                    performance_breach = performance_breach or breached
                if performance_breach:
                    raw_drift = True
                    high_drift = True
                    outcome_status = "DEGRADED"
                else:
                    outcome_status = "VALIDATED_FOR_OBSERVED_METRICS"

        if schema_mismatch:
            status = "SCHEMA_MISMATCH"
            new_streak = int(state.get("drift_streak", 0))
            confirmed = False
        elif insufficient:
            status = "INSUFFICIENT_DATA"
            new_streak = int(state.get("drift_streak", 0))
            confirmed = False
        else:
            new_streak = int(state.get("drift_streak", 0)) + 1 if raw_drift else 0
            confirmed = raw_drift and new_streak >= int(policy["confirmation_windows"])
            if confirmed:
                status = "DEGRADED"
            elif raw_drift:
                status = "WATCH"
            elif outcome_status == "VALIDATED_FOR_OBSERVED_METRICS":
                status = "HEALTHY"
            else:
                status = "OBSERVING"

        if status not in _ALLOWED_STATUSES:
            raise RuntimeError(f"internal invalid post-deployment status: {status}")

        analysis_payload = {
            "model_id": model_id,
            "batch_id": batch_id,
            "baseline_hash": baseline["baseline_hash"],
            "observed_at_epoch": observed_at,
            "status": status,
            "outcome_status": outcome_status,
            "drift_streak": new_streak,
            "confirmed_drift": confirmed,
            "high_drift_observed": high_drift,
            "feature_findings": feature_findings,
            "performance_findings": performance_findings,
            "automatic_model_change_allowed": False,
        }
        record = {
            **analysis_payload,
            "analysis_hash": _hash(analysis_payload),
            "input_fingerprint": input_fingerprint,
        }
        self.load()["batches"][batch_key] = record
        state["last_observed_at_epoch"] = observed_at
        state["last_status"] = status
        if not schema_mismatch and not insufficient:
            state["drift_streak"] = new_streak
        self._event("BATCH_VALIDATED", model_id, batch_id, record)
        return self._result_from_record(record)

    @staticmethod
    def _result_from_record(record: Mapping[str, Any]) -> BatchValidation:
        return BatchValidation(
            model_id=str(record["model_id"]),
            batch_id=str(record["batch_id"]),
            status=str(record["status"]),
            outcome_status=str(record["outcome_status"]),
            drift_streak=int(record["drift_streak"]),
            confirmed_drift=bool(record["confirmed_drift"]),
            feature_findings=tuple(dict(item) for item in record.get("feature_findings", [])),
            performance_findings=tuple(dict(item) for item in record.get("performance_findings", [])),
            analysis_hash=str(record["analysis_hash"]),
            automatic_model_change_allowed=False,
        )

    def model_state(self, model_id: str) -> Mapping[str, Any]:
        model_id = _safe_id(model_id, "model_id")
        state = self.load()["model_state"].get(model_id)
        if state is None:
            raise KeyError(model_id)
        return dict(state)

    def batch_history(self, model_id: str) -> Tuple[Mapping[str, Any], ...]:
        model_id = _safe_id(model_id, "model_id")
        rows = [
            dict(row) for row in self.load()["batches"].values()
            if row.get("model_id") == model_id
        ]
        rows.sort(key=lambda row: (float(row["observed_at_epoch"]), str(row["batch_id"])))
        return tuple(rows)
