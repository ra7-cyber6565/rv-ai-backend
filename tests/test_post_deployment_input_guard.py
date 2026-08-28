import math

import pytest

from research_engine.post_deployment_input_guard import install
from research_engine.post_deployment_validation import (
    DriftPolicy,
    MetricRule,
    PostDeploymentValidator,
)


def _validator(tmp_path, *, with_metric=False):
    validator = PostDeploymentValidator(str(tmp_path), project_id="finite-guard")
    metric_rules = None
    if with_metric:
        metric_rules = {"accuracy": MetricRule(baseline=0.9, direction="max")}
    validator.register_baseline(
        "model-v1",
        feature_kinds={"latency": "numeric", "region": "categorical"},
        feature_samples={
            "latency": [float(index) for index in range(40)],
            "region": ["A"] * 20 + ["B"] * 20,
        },
        observed_at_epoch=1000,
        policy=DriftPolicy(),
        metric_rules=metric_rules,
        implementation_hash="impl-1",
        dataset_hash="data-1",
    )
    return validator


def _stable_features():
    return {
        "latency": [float(index) for index in range(40)],
        "region": ["A"] * 20 + ["B"] * 20,
    }


def test_nan_numeric_feature_fails_domain_validation_before_json_fingerprint(tmp_path):
    validator = _validator(tmp_path)
    features = _stable_features()
    features["latency"][-1] = float("nan")
    with pytest.raises(ValueError, match=r"latency\[39\] must be finite"):
        validator.observe_batch(
            "model-v1",
            "batch-nan",
            feature_samples=features,
            observed_at_epoch=1100,
        )


def test_infinite_metric_fails_domain_validation_before_json_fingerprint(tmp_path):
    validator = _validator(tmp_path, with_metric=True)
    with pytest.raises(ValueError, match=r"observed_metrics\[accuracy\] must be finite"):
        validator.observe_batch(
            "model-v1",
            "batch-inf",
            feature_samples=_stable_features(),
            observed_at_epoch=1100,
            observed_metrics={"accuracy": math.inf},
        )


def test_unknown_feature_still_reaches_original_schema_mismatch_path(tmp_path):
    validator = _validator(tmp_path)
    features = _stable_features()
    features["unexpected"] = ["x"] * 40
    result = validator.observe_batch(
        "model-v1",
        "batch-schema",
        feature_samples=features,
        observed_at_epoch=1100,
    )
    assert result.status == "SCHEMA_MISMATCH"
    assert result.confirmed_drift is False
    finding = result.feature_findings[0]
    assert finding["kind"] == "SCHEMA_MISMATCH"
    assert finding["unexpected_features"] == ["unexpected"]


def test_missing_baseline_error_order_is_preserved_even_with_nonfinite_input(tmp_path):
    validator = PostDeploymentValidator(str(tmp_path), project_id="no-baseline")
    with pytest.raises(KeyError, match="no baseline registered"):
        validator.observe_batch(
            "missing-model",
            "batch-1",
            feature_samples={"latency": [float("nan")]},
            observed_at_epoch=1100,
        )


def test_guard_install_is_idempotent():
    before = PostDeploymentValidator.observe_batch
    install()
    after_first = PostDeploymentValidator.observe_batch
    install()
    after_second = PostDeploymentValidator.observe_batch
    assert before is after_first
    assert after_first is after_second
