import math

import pytest

from research_engine.confidence_governance import (
    CalibrationSample,
    calibrate_domain_confidence,
    fit_domain_profiles,
    gate_claim_strength,
)


def _samples(domain, count, *, confidence=0.8, outcome_rate=0.75):
    successes = int(round(count * outcome_rate))
    return [
        CalibrationSample(
            domain=domain,
            predicted_confidence=confidence,
            outcome=index < successes,
            sample_id=f"{domain}-{index}",
        )
        for index in range(count)
    ]


def test_profiles_are_domain_specific_and_do_not_pool_unrelated_history():
    samples = _samples("physics", 40, confidence=0.9, outcome_rate=0.9)
    samples += _samples("trading", 40, confidence=0.9, outcome_rate=0.2)
    profiles = fit_domain_profiles(samples, minimum_domain_samples=20)
    assert set(profiles) == {"physics", "trading"}
    assert profiles["physics"].base_rate == pytest.approx(0.9)
    assert profiles["trading"].base_rate == pytest.approx(0.2)
    p = calibrate_domain_confidence(0.9, "physics", profiles)
    t = calibrate_domain_confidence(0.9, "trading", profiles)
    assert p.calibrated_score > t.calibrated_score
    assert p.confidence_is_truth_probability is False
    assert t.confidence_is_truth_probability is False


def test_unknown_domain_fails_conservatively_to_neutral_score():
    profiles = fit_domain_profiles(_samples("physics", 20))
    result = calibrate_domain_confidence(0.99, "medicine", profiles)
    assert result.profile_status == "NO_DOMAIN_HISTORY"
    assert result.calibrated_score == 0.5
    assert result.sample_count == 0
    assert "no domain-specific" in result.reasons[0]


def test_sparse_history_is_explicit_and_heavily_shrunk():
    profiles = fit_domain_profiles(
        _samples("rare-domain", 3, confidence=0.99, outcome_rate=1.0),
        minimum_domain_samples=20,
    )
    result = calibrate_domain_confidence(0.99, "rare-domain", profiles)
    assert result.profile_status == "SPARSE_HISTORY"
    assert result.calibrated_score < 0.8
    assert any("sparse" in reason for reason in result.reasons)


def test_brier_and_ece_are_resolved_outcome_diagnostics_not_truth_scores():
    profiles = fit_domain_profiles(
        _samples("science", 20, confidence=0.8, outcome_rate=0.5),
        minimum_domain_samples=20,
    )
    profile = profiles["science"]
    assert profile.status == "CALIBRATED_HISTORY"
    assert 0 <= profile.brier_score <= 1
    assert 0 <= profile.expected_calibration_error <= 1
    assert profile.truth_probability_interpretation_allowed is False
    assert len(profile.profile_hash) == 64


def test_duplicate_sample_ids_fail_closed_even_across_domains():
    with pytest.raises(ValueError, match="unique"):
        fit_domain_profiles([
            CalibrationSample("physics", 0.8, True, "same"),
            CalibrationSample("trading", 0.2, False, "same"),
        ])


def test_nan_inf_boolean_or_invalid_domain_are_rejected():
    for bad in (math.nan, math.inf, -math.inf, True):
        with pytest.raises(ValueError):
            fit_domain_profiles([CalibrationSample("physics", bad, True, "x")])
    with pytest.raises(ValueError, match="domain"):
        fit_domain_profiles([CalibrationSample("bad domain!", 0.5, True, "x")])


def test_high_confidence_cannot_overcome_missing_evidence():
    decision = gate_claim_strength(
        requested_epistemic_level="MEASURED",
        confidence_score=0.999999,
        evidence_sufficient=False,
        independent_validation=True,
        measured_directly=True,
        contradictions_present=False,
    )
    assert decision.allowed_epistemic_level == "HYPOTHESIS"
    assert decision.blocked is True
    assert "evidence_insufficient" in decision.blockers
    assert decision.confidence_upgraded_claim is False
    assert decision.truth_proven is False


def test_high_confidence_cannot_hide_contradictions():
    decision = gate_claim_strength(
        requested_epistemic_level="SUPPORTED",
        confidence_score=1.0,
        evidence_sufficient=True,
        independent_validation=True,
        measured_directly=False,
        contradictions_present=True,
    )
    assert decision.allowed_epistemic_level == "HYPOTHESIS"
    assert "contradictions_unresolved" in decision.blockers
    assert decision.confidence_upgraded_claim is False


def test_measured_label_requires_direct_measurement_even_at_high_confidence():
    independent = gate_claim_strength(
        requested_epistemic_level="MEASURED",
        confidence_score=0.99,
        evidence_sufficient=True,
        independent_validation=True,
        measured_directly=False,
        contradictions_present=False,
    )
    single = gate_claim_strength(
        requested_epistemic_level="MEASURED",
        confidence_score=0.99,
        evidence_sufficient=True,
        independent_validation=False,
        measured_directly=False,
        contradictions_present=False,
    )
    assert independent.allowed_epistemic_level == "SUPPORTED"
    assert single.allowed_epistemic_level == "INFERRED"
    assert "direct_measurement_missing" in independent.blockers
    assert "direct_measurement_missing" in single.blockers


def test_supported_label_requires_independent_validation():
    decision = gate_claim_strength(
        requested_epistemic_level="SUPPORTED",
        confidence_score=0.95,
        evidence_sufficient=True,
        independent_validation=False,
        measured_directly=False,
        contradictions_present=False,
    )
    assert decision.allowed_epistemic_level == "INFERRED"
    assert decision.blockers == ("independent_validation_missing",)


def test_low_confidence_does_not_auto_downgrade_valid_epistemic_type():
    decision = gate_claim_strength(
        requested_epistemic_level="SUPPORTED",
        confidence_score=0.1,
        evidence_sufficient=True,
        independent_validation=True,
        measured_directly=False,
        contradictions_present=False,
    )
    assert decision.allowed_epistemic_level == "SUPPORTED"
    assert decision.blocked is False
    assert decision.confidence_upgraded_claim is False


def test_calibration_and_decision_hashes_are_deterministic():
    profiles = fit_domain_profiles(_samples("physics", 25))
    first = calibrate_domain_confidence(0.8, "physics", profiles)
    second = calibrate_domain_confidence(0.8, "physics", profiles)
    assert first.calibration_hash == second.calibration_hash

    kwargs = dict(
        requested_epistemic_level="SUPPORTED",
        confidence_score=0.8,
        evidence_sufficient=True,
        independent_validation=True,
        measured_directly=False,
        contradictions_present=False,
    )
    assert gate_claim_strength(**kwargs).decision_hash == gate_claim_strength(**kwargs).decision_hash
