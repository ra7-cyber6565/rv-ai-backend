import hashlib
import json

import pytest

from research_engine.post_deployment_integrity import verify_post_deployment_state
from research_engine.post_deployment_validation import (
    DriftPolicy,
    MetricRule,
    PostDeploymentValidator,
)


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _make_state(tmp_path):
    validator = PostDeploymentValidator(str(tmp_path), project_id="live-project")
    policy = DriftPolicy(min_batch_samples=30, confirmation_windows=2, numeric_bins=5)
    reference = [float(index) for index in range(40)]
    baseline = validator.register_baseline(
        "model-v1",
        feature_kinds={"score": "numeric"},
        feature_samples={"score": reference},
        observed_at_epoch=1000,
        policy=policy,
        metric_rules={
            "accuracy": MetricRule(
                baseline=0.80,
                direction="max",
                max_relative_degradation=0.10,
            )
        },
        implementation_hash="impl-v1",
        dataset_hash="dataset-v1",
    )
    first = validator.observe_batch(
        "model-v1",
        "batch-1",
        feature_samples={"score": [float(index) for index in range(40)]},
        observed_at_epoch=1100,
        observed_metrics={"accuracy": 0.81},
    )
    second = validator.observe_batch(
        "model-v1",
        "batch-2",
        feature_samples={"score": [float(index) + 0.1 for index in range(40)]},
        observed_at_epoch=1200,
        observed_metrics={"accuracy": 0.80},
    )
    validator.save()
    return validator.path, baseline, first, second


def _load(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _save(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2)


def test_valid_persisted_state_recomputes_all_bound_hashes(tmp_path):
    path, baseline, first, second = _make_state(tmp_path)
    report = verify_post_deployment_state(path, expected_project_id="live-project")
    assert report.project_id == "live-project"
    assert report.model_ids == ("model-v1",)
    assert report.baseline_hashes == (baseline["baseline_hash"],)
    assert report.batch_ids == ("batch-1", "batch-2")
    assert report.batch_analysis_hashes == (first.analysis_hash, second.analysis_hash)
    assert report.event_count == 3
    assert len(report.state_sha256) == 64
    assert len(report.event_head_hash) == 64
    assert report.latest_observed_at_epoch == 1200


def test_baseline_payload_tamper_fails_closed(tmp_path):
    path, _baseline, _first, _second = _make_state(tmp_path)
    data = _load(path)
    data["baselines"]["model-v1"]["implementation_hash"] = "attacker-rewrite"
    _save(path, data)
    with pytest.raises(ValueError, match="baseline hash mismatch"):
        verify_post_deployment_state(path)


def test_feature_reference_tamper_fails_even_if_outer_baseline_hash_is_recomputed(tmp_path):
    path, _baseline, _first, _second = _make_state(tmp_path)
    data = _load(path)
    baseline = data["baselines"]["model-v1"]
    baseline["features"]["score"]["reference"][0] = 9999.0
    body = dict(baseline)
    body.pop("baseline_hash")
    baseline["baseline_hash"] = _hash(body)
    _save(path, data)
    with pytest.raises(ValueError, match="numeric feature reference hash mismatch"):
        verify_post_deployment_state(path)


def test_batch_analysis_tamper_fails_closed(tmp_path):
    path, _baseline, _first, _second = _make_state(tmp_path)
    data = _load(path)
    data["batches"]["model-v1|batch-2"]["outcome_status"] = "NO_OUTCOME_DATA"
    _save(path, data)
    with pytest.raises(ValueError, match="batch analysis hash mismatch"):
        verify_post_deployment_state(path)


def test_recomputed_batch_hash_still_must_match_bound_event_payload(tmp_path):
    path, _baseline, _first, _second = _make_state(tmp_path)
    data = _load(path)
    record = data["batches"]["model-v1|batch-2"]
    record["outcome_status"] = "NO_OUTCOME_DATA"
    body = dict(record)
    body.pop("analysis_hash")
    body.pop("input_fingerprint")
    record["analysis_hash"] = _hash(body)
    _save(path, data)
    with pytest.raises(ValueError, match="event payload hash mismatch"):
        verify_post_deployment_state(path)


def test_missing_audit_event_fails_closed(tmp_path):
    path, _baseline, _first, _second = _make_state(tmp_path)
    data = _load(path)
    data["events"].pop()
    _save(path, data)
    with pytest.raises(ValueError, match="lack audit events"):
        verify_post_deployment_state(path)


def test_materialized_model_state_tamper_fails_closed(tmp_path):
    path, _baseline, _first, _second = _make_state(tmp_path)
    data = _load(path)
    data["model_state"]["model-v1"]["last_status"] = "DEGRADED"
    _save(path, data)
    with pytest.raises(ValueError, match="last_status mismatch"):
        verify_post_deployment_state(path)


def test_project_identity_mismatch_fails_closed(tmp_path):
    path, _baseline, _first, _second = _make_state(tmp_path)
    with pytest.raises(ValueError, match="does not match expected project"):
        verify_post_deployment_state(path, expected_project_id="other-project")
