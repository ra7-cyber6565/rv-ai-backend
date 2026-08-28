"""Fail-closed input validation boundary for post-deployment monitoring.

This guard exists because batch fingerprints must never become the first place
that malformed numeric input is discovered.  It validates known numeric feature
samples and supplied outcome metrics before the underlying validator computes a
JSON fingerprint, so NaN/Infinity are rejected with domain-specific finite-value
errors instead of leaking serializer errors.

The guard is deterministic, performs no network/model calls, changes no model,
and is idempotently installed at package import time.
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Mapping, Optional, Sequence

from . import post_deployment_validation as _pdv


_INSTALLED_ATTR = "_post_deployment_input_guard_installed"


def _prevalidate(
    validator: _pdv.PostDeploymentValidator,
    model_id: object,
    feature_samples: Mapping[str, Sequence[Any]],
    observed_metrics: Optional[Mapping[str, float]],
) -> None:
    """Validate finite domain inputs before canonical fingerprinting.

    Unknown/missing feature names are intentionally left to the original
    schema-mismatch path.  For known features we reuse the validator's own
    normalization routine so validation semantics stay identical.
    """
    if not isinstance(feature_samples, Mapping):
        raise ValueError("feature_samples must be a mapping")

    baseline = validator.load()["baselines"].get(str(model_id))
    if baseline is None:
        # Preserve the original validator's KeyError/ID validation ordering.
        return

    baseline_features = baseline.get("features") or {}
    for raw_feature, values in feature_samples.items():
        feature = str(raw_feature)
        reference = baseline_features.get(feature)
        if reference is None:
            # Unknown features must still be classified by the schema gate.
            continue
        kind = str(reference.get("kind", "")).strip().lower()
        _pdv._normalize_feature_values(feature, kind, values)

    if observed_metrics is not None:
        if not isinstance(observed_metrics, Mapping):
            raise ValueError("observed_metrics must be a mapping")
        for raw_metric, value in observed_metrics.items():
            metric = str(raw_metric)
            _pdv._finite(value, f"observed_metrics[{metric}]")


def install() -> None:
    cls = _pdv.PostDeploymentValidator
    if getattr(cls, _INSTALLED_ATTR, False):
        return

    original = cls.observe_batch

    @wraps(original)
    def guarded_observe_batch(
        self: _pdv.PostDeploymentValidator,
        model_id: str,
        batch_id: str,
        *,
        feature_samples: Mapping[str, Sequence[Any]],
        observed_at_epoch: float,
        observed_metrics: Optional[Mapping[str, float]] = None,
    ) -> _pdv.BatchValidation:
        _prevalidate(self, model_id, feature_samples, observed_metrics)
        return original(
            self,
            model_id,
            batch_id,
            feature_samples=feature_samples,
            observed_at_epoch=observed_at_epoch,
            observed_metrics=observed_metrics,
        )

    cls.observe_batch = guarded_observe_batch  # type: ignore[assignment]
    setattr(cls, _INSTALLED_ATTR, True)
