import json

import pytest

from research_engine.post_deployment_validation import (
    DriftPolicy,
    MetricRule,
    PostDeploymentValidator,
)


def _reference_features():
    return {
        "latency": [float(i) for i in range(40)],
        "region": ["A"] * 20 + ["B"] * 20,
    }


def _stable_features():
    return {
        "latency": [float(i) for i in range(40)],
        "region": ["A"] * 20 + ["B"] * 20,
    }


def _drifted_features():
    return {
        "latency": [1000.0 + i for i in range(40)],
        "region": ["X"] * 20 + ["Y"] * 20,
    }


def _validator(tmp_path, *, metric_rules=None, policy=None):
    validator = PostDeploymentValidator(str(tmp_path), project_id="postdeploy-test")
    validator.register_baseline(
        "model-v1",
        feature_kinds={"latency": "numeric", "region": "categorical"},
        feature_samples=_reference_features(),
        observed_at_epoch=1000,
        policy=policy or DriftPolicy(),
        metric_rules=metric_rules,
        implementation_hash="impl-sha-1",
        dataset_hash="dataset-sha-1",
    )
    return validator


def test_stable_features_without_outcomes_are_observing_not_healthy(tmp_path):
    validator = _validator(tmp_path)
    result = validator.observe_batch(
        "model-v1",
        "batch-1",
        feature_samples=_stable_features(),
        observed_at_epoch=1100,
    )
    assert result.status == "OBSERVING"
    assert result.outcome_status == "NO_OUTCOME_DATA"
    assert result.confirmed_drift is False
    assert result.drift_streak == 0
    assert result.automatic_model_change_allowed is False


def test_good_observed_metric_allows_healthy_status(tmp_path):
    validator = _validator(
        tmp_path,
        metric_rules={
            "accuracy": MetricRule(
                baseline=0.90,
                direction="max",
                max_relative_degradation=0.10,
            )
        },
    )
    result = validator.observe_batch(
        "model-v1",
        "batch-1",
        feature_samples=_stable_features(),
        observed_at_epoch=1100,
        observed_metrics={"accuracy": 0.86},
    )
    assert result.status == "HEALTHY"
    assert result.outcome_status == "VALIDATED_FOR_OBSERVED_METRICS"
    assert result.confirmed_drift is False


def test_single_drift_window_is_watch_and_second_confirms_degraded(tmp_path):
    validator = _validator(tmp_path)
    first = validator.observe_batch(
        "model-v1",
        "batch-1",
        feature_samples=_drifted_features(),
        observed_at_epoch=1100,
    )
    second = validator.observe_batch(
        "model-v1",
        "batch-2",
        feature_samples=_drifted_features(),
        observed_at_epoch=1200,
    )
    assert first.status == "WATCH"
    assert first.drift_streak == 1
    assert first.confirmed_drift is False
    assert second.status == "DEGRADED"
    assert second.drift_streak == 2
    assert second.confirmed_drift is True
    assert any(item["severity"] == "HIGH" for item in second.feature_findings)


def test_clean_window_resets_unconfirmed_drift_streak(tmp_path):
    validator = _validator(tmp_path)
    drift = validator.observe_batch(
        "model-v1",
        "batch-1",
        feature_samples=_drifted_features(),
        observed_at_epoch=1100,
    )
    clean = validator.observe_batch(
        "model-v1",
        "batch-2",
        feature_samples=_stable_features(),
        observed_at_epoch=1200,
    )
    assert drift.drift_streak == 1
    assert clean.drift_streak == 0
    assert clean.status == "OBSERVING"
    assert validator.model_state("model-v1")["drift_streak"] == 0


def test_performance_degradation_requires_confirmation_windows(tmp_path):
    validator = _validator(
        tmp_path,
        metric_rules={
            "accuracy": MetricRule(
                baseline=0.90,
                direction="max",
                max_relative_degradation=0.05,
            )
        },
    )
    first = validator.observe_batch(
        "model-v1",
        "batch-1",
        feature_samples=_stable_features(),
        observed_at_epoch=1100,
        observed_metrics={"accuracy": 0.60},
    )
    second = validator.observe_batch(
        "model-v1",
        "batch-2",
        feature_samples=_stable_features(),
        observed_at_epoch=1200,
        observed_metrics={"accuracy": 0.60},
    )
    assert first.status == "WATCH"
    assert first.outcome_status == "DEGRADED"
    assert second.status == "DEGRADED"
    assert second.confirmed_drift is True
    assert second.performance_findings[0]["breached"] is True


def test_feature_schema_mismatch_fails_closed_without_advancing_streak(tmp_path):
    validator = _validator(tmp_path)
    result = validator.observe_batch(
        "model-v1",
        "batch-1",
        feature_samples={"latency": [float(i) for i in range(40)]},
        observed_at_epoch=1100,
    )
    assert result.status == "SCHEMA_MISMATCH"
    assert result.confirmed_drift is False
    assert result.feature_findings[0]["kind"] == "SCHEMA_MISMATCH"
    assert validator.model_state("model-v1")["drift_streak"] == 0


def test_metric_schema_mismatch_fails_closed(tmp_path):
    validator = _validator(
        tmp_path,
        metric_rules={"accuracy": MetricRule(baseline=0.90, direction="max")},
    )
    result = validator.observe_batch(
        "model-v1",
        "batch-1",
        feature_samples=_stable_features(),
        observed_at_epoch=1100,
        observed_metrics={"other_metric": 0.9},
    )
    assert result.status == "SCHEMA_MISMATCH"
    assert result.outcome_status == "METRIC_SCHEMA_MISMATCH"
    assert result.performance_findings[0]["severity"] == "HIGH"


def test_undersized_or_mostly_missing_batch_is_not_treated_as_healthy(tmp_path):
    validator = _validator(tmp_path)
    result = validator.observe_batch(
        "model-v1",
        "batch-1",
        feature_samples={
            "latency": [None] * 20 + [float(i) for i in range(20)],
            "region": ["A"] * 40,
        },
        observed_at_epoch=1100,
    )
    assert result.status == "INSUFFICIENT_DATA"
    assert result.confirmed_drift is False
    assert any(item["kind"] == "INSUFFICIENT_DATA" for item in result.feature_findings)


def test_batch_id_is_immutable_but_exact_replay_is_idempotent(tmp_path):
    validator = _validator(tmp_path)
    first = validator.observe_batch(
        "model-v1",
        "batch-1",
        feature_samples=_stable_features(),
        observed_at_epoch=1100,
    )
    replay = validator.observe_batch(
        "model-v1",
        "batch-1",
        feature_samples=_stable_features(),
        observed_at_epoch=1100,
    )
    assert replay.analysis_hash == first.analysis_hash
    with pytest.raises(ValueError, match="batch_id is immutable"):
        validator.observe_batch(
            "model-v1",
            "batch-1",
            feature_samples=_drifted_features(),
            observed_at_epoch=1100,
        )


def test_baseline_is_immutable_for_same_model_version(tmp_path):
    validator = _validator(tmp_path)
    same = validator.register_baseline(
        "model-v1",
        feature_kinds={"latency": "numeric", "region": "categorical"},
        feature_samples=_reference_features(),
        observed_at_epoch=1000,
        implementation_hash="impl-sha-1",
        dataset_hash="dataset-sha-1",
    )
    assert same["baseline_hash"]
    with pytest.raises(ValueError, match="baseline is immutable"):
        validator.register_baseline(
            "model-v1",
            feature_kinds={"latency": "numeric", "region": "categorical"},
            feature_samples=_reference_features(),
            observed_at_epoch=1000,
            implementation_hash="impl-sha-CHANGED",
            dataset_hash="dataset-sha-1",
        )


def test_post_deployment_timestamps_cannot_move_backward(tmp_path):
    validator = _validator(tmp_path)
    validator.observe_batch(
        "model-v1",
        "batch-1",
        feature_samples=_stable_features(),
        observed_at_epoch=1200,
    )
    with pytest.raises(ValueError, match="timestamps must be monotonic"):
        validator.observe_batch(
            "model-v1",
            "batch-2",
            feature_samples=_stable_features(),
            observed_at_epoch=1100,
        )


def test_nonfinite_inputs_and_invalid_policy_fail_closed(tmp_path):
    with pytest.raises(ValueError):
        DriftPolicy(psi_warning=0.3, psi_high=0.2).validate()
    validator = _validator(tmp_path)
    bad = _stable_features()
    bad["latency"] = [float(i) for i in range(39)] + [float("nan")]
    with pytest.raises(ValueError, match="must be finite"):
        validator.observe_batch(
            "model-v1",
            "batch-1",
            feature_samples=bad,
            observed_at_epoch=1100,
        )

    with pytest.raises(ValueError, match=r"observed_metrics\[accuracy\] must be finite"):
        validator.observe_batch(
            "model-v1",
            "batch-2",
            feature_samples=_stable_features(),
            observed_at_epoch=1200,
            observed_metrics={"accuracy": float("inf")},
        )


def test_persistence_roundtrip_preserves_state_and_history(tmp_path):
    validator = _validator(tmp_path)
    result = validator.observe_batch(
        "model-v1",
        "batch-1",
        feature_samples=_drifted_features(),
        observed_at_epoch=1100,
    )
    validator.save()

    loaded = PostDeploymentValidator(str(tmp_path), project_id="postdeploy-test")
    assert loaded.model_state("model-v1")["drift_streak"] == 1
    history = loaded.batch_history("model-v1")
    assert len(history) == 1
    assert history[0]["analysis_hash"] == result.analysis_hash
    assert loaded.audit_integrity()["valid"] is True


def test_audit_chain_tampering_is_detected(tmp_path):
    validator = _validator(tmp_path)
    validator.observe_batch(
        "model-v1",
        "batch-1",
        feature_samples=_stable_features(),
        observed_at_epoch=1100,
    )
    validator.save()

    with open(validator.path, "r", encoding="utf-8") as handle:
        state = json.load(handle)
    state["events"][0]["event_hash"] = "0" * 64
    with open(validator.path, "w", encoding="utf-8") as handle:
        json.dump(state, handle)

    loaded = PostDeploymentValidator(str(tmp_path), project_id="postdeploy-test")
    with pytest.raises(ValueError, match="audit"):
        loaded.audit_integrity()


def test_monitor_never_authorizes_automatic_model_change(tmp_path):
    policy = DriftPolicy(confirmation_windows=1)
    validator = _validator(tmp_path, policy=policy)
    result = validator.observe_batch(
        "model-v1",
        "batch-1",
        feature_samples=_drifted_features(),
        observed_at_epoch=1100,
    )
    assert result.status == "DEGRADED"
    assert result.confirmed_drift is True
    assert result.automatic_model_change_allowed is False
