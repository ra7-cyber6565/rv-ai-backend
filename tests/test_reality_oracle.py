import math

import pytest

from research_engine.reality_oracle import (
    evaluate_reality,
    freeze_prediction_contract,
    make_observation_receipt,
)


PROTO = "a" * 64
DIGEST = "b" * 64


def _prediction(**overrides):
    data = {
        "prediction_id": "pred-1",
        "hypothesis_id": "H1",
        "metric": "accuracy",
        "unit": "fraction",
        "rule": "absolute",
        "target": 0.80,
        "tolerance": 0.02,
        "preregistered_at": "2026-08-30T00:00:00+00:00",
        "evaluation_after": "2026-08-30T01:00:00+00:00",
        "protocol_hash": PROTO,
    }
    data.update(overrides)
    return freeze_prediction_contract(**data)


def _observation(**overrides):
    data = {
        "observation_id": "obs-1",
        "metric": "accuracy",
        "unit": "fraction",
        "observed_value": 0.81,
        "observed_at": "2026-08-30T02:00:00+00:00",
        "source_id": "sensor-1",
        "source_kind": "sensor",
        "source_digest": DIGEST,
        "raw_reference": "lab://run/1/metric/accuracy",
    }
    data.update(overrides)
    return make_observation_receipt(**data)


def test_absolute_match_does_not_claim_truth_or_live_authenticity():
    result = evaluate_reality(_prediction(), _observation())
    assert result.status == "MATCH"
    assert result.matched is True
    assert result.residual == pytest.approx(0.01)
    assert result.truth_proven is False
    assert result.observation_authenticity_proven is False
    assert result.live_observation_proven is False
    assert len(result.evaluation_hash) == 64


def test_absolute_miss_is_explicit():
    result = evaluate_reality(_prediction(), _observation(observed_value=0.90))
    assert result.status == "MISS"
    assert result.matched is False
    assert result.normalized_error == pytest.approx(0.10)


def test_interval_rule_handles_inside_and_outside_values():
    prediction = _prediction(
        rule="interval", target=None, tolerance=0.0, lower=0.70, upper=0.90
    )
    inside = evaluate_reality(prediction, _observation(observed_value=0.75))
    outside = evaluate_reality(prediction, _observation(observed_value=0.95))
    assert inside.status == "MATCH"
    assert inside.residual == 0.0
    assert outside.status == "MISS"
    assert outside.residual == pytest.approx(0.05)


def test_relative_rule_uses_precommitted_relative_tolerance():
    prediction = _prediction(rule="relative", target=100.0, tolerance=0.05)
    observation = _observation(unit="fraction", observed_value=104.0)
    result = evaluate_reality(prediction, observation)
    assert result.status == "MATCH"
    assert result.normalized_error == pytest.approx(0.04)


def test_relative_rule_near_zero_target_is_inconclusive_not_divide_by_zero():
    prediction = _prediction(rule="relative", target=0.0, tolerance=0.05)
    result = evaluate_reality(prediction, _observation(observed_value=0.01))
    assert result.status == "INCONCLUSIVE"
    assert result.matched is None
    assert "near-zero" in result.reasons[0]


def test_directional_rule_supports_threshold_predictions():
    prediction = _prediction(
        rule="directional", target=0.8, tolerance=0.0, direction=">="
    )
    assert evaluate_reality(prediction, _observation(observed_value=0.8)).matched is True
    assert evaluate_reality(prediction, _observation(observed_value=0.79)).matched is False


def test_metric_or_unit_mismatch_fails_closed_as_inconclusive():
    prediction = _prediction()
    metric = evaluate_reality(prediction, _observation(metric="loss"))
    unit = evaluate_reality(prediction, _observation(unit="percent"))
    assert metric.status == "INCONCLUSIVE"
    assert metric.matched is None
    assert metric.reasons == ("metric mismatch",)
    assert unit.status == "INCONCLUSIVE"
    assert unit.reasons == ("unit mismatch",)


def test_observation_before_evaluation_window_is_not_scored():
    result = evaluate_reality(
        _prediction(),
        _observation(observed_at="2026-08-30T00:30:00+00:00"),
    )
    assert result.status == "INCONCLUSIVE"
    assert "before evaluation window" in result.reasons[0]


def test_prediction_contract_rejects_reverse_time_and_invalid_rule_mix():
    with pytest.raises(ValueError, match="must not precede"):
        _prediction(evaluation_after="2026-08-29T23:00:00+00:00")
    with pytest.raises(ValueError, match="cannot mix"):
        _prediction(lower=0.1)
    with pytest.raises(ValueError, match="requires lower"):
        _prediction(rule="interval", target=None, lower=0.9, upper=0.1)


def test_nan_inf_and_boolean_numeric_inputs_are_rejected():
    for bad in (math.nan, math.inf, -math.inf, True):
        with pytest.raises(ValueError):
            _observation(observed_value=bad)
    with pytest.raises(ValueError):
        _prediction(tolerance=math.nan)


def test_observation_requires_bounded_provenance_and_sha256_digest():
    with pytest.raises(ValueError, match="source_kind"):
        _observation(source_kind="self_asserted")
    with pytest.raises(ValueError, match="SHA-256"):
        _observation(source_digest="not-a-digest")
    with pytest.raises(ValueError, match="raw_reference"):
        _observation(raw_reference="")


def test_contract_and_receipt_hashes_are_deterministic_and_change_on_content():
    p1 = _prediction()
    p2 = _prediction()
    p3 = _prediction(target=0.81)
    o1 = _observation()
    o2 = _observation()
    o3 = _observation(observed_value=0.82)
    assert p1.contract_hash == p2.contract_hash
    assert p1.contract_hash != p3.contract_hash
    assert o1.receipt_hash == o2.receipt_hash
    assert o1.receipt_hash != o3.receipt_hash


def test_timezone_is_mandatory_to_prevent_ambiguous_ordering():
    with pytest.raises(ValueError, match="timezone"):
        _prediction(preregistered_at="2026-08-30T00:00:00")
    with pytest.raises(ValueError, match="timezone"):
        _observation(observed_at="2026-08-30T02:00:00")
