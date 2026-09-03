import math

import pytest

from research_engine.sim_to_reality import (
    PhysicalComparisonSample,
    SimToRealityProtocol,
    VariableTolerance,
    evaluate_sim_to_reality_gap,
    verify_report_hash,
)


MODEL_HASH = "a" * 64
RECEIPT_HASH = "b" * 64


def _protocol(**overrides):
    values = dict(
        protocol_id="thermal-rig-v1",
        model_hash=MODEL_HASH,
        variables=(
            VariableTolerance(
                name="temperature",
                scale=100.0,
                max_nrmse=0.10,
                max_abs_normalized_bias=0.05,
                max_p95_normalized_error=0.15,
                min_uncertainty_coverage=0.80,
            ),
        ),
        min_holdout_samples=6,
        min_regimes=2,
        min_samples_per_regime=3,
        min_distinct_sessions=2,
        uncertainty_z=1.96,
    )
    values.update(overrides)
    return SimToRealityProtocol(**values)


def _samples(*, error=2.0, uncertainty=2.0):
    rows = []
    for index in range(6):
        regime = "cold" if index < 3 else "hot"
        session = "s1" if index % 2 == 0 else "s2"
        observed = 20.0 + index * 10.0
        rows.append(PhysicalComparisonSample(
            sample_id=f"sample-{index}",
            regime=regime,
            session_id=session,
            timestamp_epoch=1000.0 + index,
            predicted={"temperature": observed + error},
            observed={"temperature": observed},
            prediction_uncertainty={"temperature": uncertainty},
            measurement_uncertainty={"temperature": uncertainty},
            hardware_receipt_hash=RECEIPT_HASH,
        ))
    return rows


def test_good_software_fit_quantifies_gap_but_never_closes_physical_gap():
    report = evaluate_sim_to_reality_gap(_protocol(), _samples())
    assert report.structure_sufficient is True
    assert report.software_fit_passed is True
    assert report.sim_to_reality_gap_quantified is True
    assert report.gap_closed is False
    assert report.hardware_validated is False
    assert report.safety_validated is False
    assert report.external_hardware_attestation_required is True
    assert verify_report_hash(report.to_dict()) is True


def test_large_bias_fails_model_fit():
    report = evaluate_sim_to_reality_gap(_protocol(), _samples(error=30.0, uncertainty=30.0))
    metric = report.global_metrics["temperature"]
    assert metric.abs_normalized_bias > 0.05
    assert report.software_fit_passed is False
    assert report.gap_closed is False


def test_low_uncertainty_coverage_fails_even_when_error_magnitude_thresholds_pass():
    report = evaluate_sim_to_reality_gap(_protocol(), _samples(error=2.0, uncertainty=0.01))
    metric = report.global_metrics["temperature"]
    assert metric.nrmse < 0.10
    assert metric.uncertainty_coverage == 0.0
    assert metric.passed is False
    assert report.software_fit_passed is False


def test_insufficient_regime_and_session_structure_fails_closed():
    rows = _samples()[:3]
    rows = [
        PhysicalComparisonSample(
            sample_id=item.sample_id,
            regime="only",
            session_id="single-session",
            timestamp_epoch=item.timestamp_epoch,
            predicted=item.predicted,
            observed=item.observed,
            prediction_uncertainty=item.prediction_uncertainty,
            measurement_uncertainty=item.measurement_uncertainty,
            hardware_receipt_hash=item.hardware_receipt_hash,
        )
        for item in rows
    ]
    report = evaluate_sim_to_reality_gap(_protocol(), rows)
    assert report.structure_sufficient is False
    assert report.software_fit_passed is False
    assert "insufficient_holdout_samples" in report.blockers
    assert "insufficient_regime_coverage" in report.blockers
    assert "insufficient_distinct_sessions" in report.blockers


def test_duplicate_sample_id_is_rejected():
    rows = _samples()
    rows[-1] = PhysicalComparisonSample(
        sample_id=rows[0].sample_id,
        regime=rows[-1].regime,
        session_id=rows[-1].session_id,
        timestamp_epoch=rows[-1].timestamp_epoch,
        predicted=rows[-1].predicted,
        observed=rows[-1].observed,
        prediction_uncertainty=rows[-1].prediction_uncertainty,
        measurement_uncertainty=rows[-1].measurement_uncertainty,
        hardware_receipt_hash=rows[-1].hardware_receipt_hash,
    )
    with pytest.raises(ValueError, match="sample_id values must be unique"):
        evaluate_sim_to_reality_gap(_protocol(), rows)


def test_schema_drift_in_physical_sample_is_rejected():
    rows = _samples()
    bad = PhysicalComparisonSample(
        sample_id="bad",
        regime="hot",
        session_id="s3",
        timestamp_epoch=2000,
        predicted={"wrong": 1.0},
        observed={"temperature": 1.0},
        prediction_uncertainty={"temperature": 1.0},
        measurement_uncertainty={"temperature": 1.0},
        hardware_receipt_hash=RECEIPT_HASH,
    )
    with pytest.raises(ValueError, match="keys must exactly match"):
        evaluate_sim_to_reality_gap(_protocol(), [*rows, bad])


def test_nonfinite_and_negative_uncertainty_fail_closed():
    with pytest.raises(ValueError, match="must be finite"):
        evaluate_sim_to_reality_gap(
            _protocol(),
            [
                PhysicalComparisonSample(
                    sample_id="x",
                    regime="r",
                    session_id="s",
                    timestamp_epoch=1,
                    predicted={"temperature": math.nan},
                    observed={"temperature": 1},
                    prediction_uncertainty={"temperature": 1},
                    measurement_uncertainty={"temperature": 1},
                    hardware_receipt_hash=RECEIPT_HASH,
                )
            ],
        )
    with pytest.raises(ValueError, match="cannot contain negative"):
        evaluate_sim_to_reality_gap(
            _protocol(),
            [
                PhysicalComparisonSample(
                    sample_id="x",
                    regime="r",
                    session_id="s",
                    timestamp_epoch=1,
                    predicted={"temperature": 1},
                    observed={"temperature": 1},
                    prediction_uncertainty={"temperature": -1},
                    measurement_uncertainty={"temperature": 1},
                    hardware_receipt_hash=RECEIPT_HASH,
                )
            ],
        )


def test_sample_commitment_and_report_are_order_invariant():
    rows = _samples()
    forward = evaluate_sim_to_reality_gap(_protocol(), rows)
    reverse = evaluate_sim_to_reality_gap(_protocol(), list(reversed(rows)))
    assert forward.sample_commitment_hash == reverse.sample_commitment_hash
    assert forward.report_hash == reverse.report_hash
    assert forward.to_dict() == reverse.to_dict()


def test_report_hash_detects_tampering():
    report = evaluate_sim_to_reality_gap(_protocol(), _samples()).to_dict()
    assert verify_report_hash(report) is True
    report["software_fit_passed"] = False
    assert verify_report_hash(report) is False


def test_threshold_sensitivity_marks_near_boundary_conclusion():
    protocol = _protocol(
        variables=(VariableTolerance(
            name="temperature",
            scale=100.0,
            max_nrmse=0.10,
            max_abs_normalized_bias=0.10,
            max_p95_normalized_error=0.10,
            min_uncertainty_coverage=0.0,
        ),)
    )
    # 9.5 / 100 = 0.095: passes nominal and 1.1x, fails strict 0.9x.
    report = evaluate_sim_to_reality_gap(
        protocol,
        _samples(error=9.5, uncertainty=100.0),
    )
    assert report.software_fit_passed is True
    assert report.threshold_sensitive is True
    assert "threshold_sensitive_conclusion" in report.blockers
    assert report.gap_closed is False


def test_protocol_hash_changes_when_precommitted_tolerance_changes():
    first = _protocol()
    second = _protocol(
        variables=(VariableTolerance(
            name="temperature",
            scale=100.0,
            max_nrmse=0.11,
            max_abs_normalized_bias=0.05,
            max_p95_normalized_error=0.15,
            min_uncertainty_coverage=0.80,
        ),)
    )
    assert first.protocol_hash != second.protocol_hash
