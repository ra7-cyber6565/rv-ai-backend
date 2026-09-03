import math

import pytest

from research_engine.negative_evidence import (
    anti_hallucination_gate,
    assess_negative_evidence,
    preserve_null_result,
)


def test_unknown_citation_blocks_strong_claim_even_at_extreme_model_confidence():
    result = anti_hallucination_gate(
        claim_id="c1",
        requested_level="SUPPORTED",
        cited_evidence_ids=("e1", "e-missing"),
        verified_evidence_ids=("e1",),
        contradictions_present=False,
        capture_integrity_passed=True,
        model_confidence=0.9999,
    )
    assert result.allowed_level == "HYPOTHESIS"
    assert result.blocked is True
    assert result.missing_evidence_ids == ("e-missing",)
    assert result.model_confidence_overrode_evidence is False
    assert result.truth_proven is False


def test_strong_claim_without_any_citation_is_blocked():
    result = anti_hallucination_gate(
        claim_id="c1",
        requested_level="MEASURED",
        cited_evidence_ids=(),
        verified_evidence_ids=(),
        contradictions_present=False,
        capture_integrity_passed=True,
        model_confidence=1.0,
    )
    assert result.allowed_level == "HYPOTHESIS"
    assert "no cited evidence" in result.blockers[0]


def test_contradiction_or_capture_failure_blocks_promotion():
    contradiction = anti_hallucination_gate(
        claim_id="c1",
        requested_level="SUPPORTED",
        cited_evidence_ids=("e1",),
        verified_evidence_ids=("e1",),
        contradictions_present=True,
        capture_integrity_passed=True,
        model_confidence=0.9,
    )
    capture = anti_hallucination_gate(
        claim_id="c2",
        requested_level="SUPPORTED",
        cited_evidence_ids=("e1",),
        verified_evidence_ids=("e1",),
        contradictions_present=False,
        capture_integrity_passed=False,
        model_confidence=0.9,
    )
    assert contradiction.allowed_level == "HYPOTHESIS"
    assert capture.allowed_level == "HYPOTHESIS"


def test_measured_label_needs_separate_measurement_proof():
    result = anti_hallucination_gate(
        claim_id="c1",
        requested_level="MEASURED",
        cited_evidence_ids=("e1",),
        verified_evidence_ids=("e1",),
        contradictions_present=False,
        capture_integrity_passed=True,
        model_confidence=0.8,
    )
    assert result.allowed_level == "SUPPORTED"
    assert "direct measurement" in result.blockers[0]
    assert result.truth_proven is False


def test_weak_or_undeclared_search_is_only_absence_of_evidence():
    weak = assess_negative_evidence(
        hypothesis_id="H1",
        target_observation="expected signal",
        search_scope=("dataset-A",),
        detection_sensitivity=0.4,
        coverage_fraction=0.9,
        negative_observation=True,
    )
    empty = assess_negative_evidence(
        hypothesis_id="H1",
        target_observation="expected signal",
        search_scope=(),
        detection_sensitivity=1.0,
        coverage_fraction=1.0,
        negative_observation=True,
    )
    assert weak.status == "ABSENCE_OF_EVIDENCE_ONLY"
    assert weak.evidence_of_absence_strength == 0.0
    assert empty.status == "ABSENCE_OF_EVIDENCE_ONLY"
    assert empty.universal_absence_proven is False


def test_strong_negative_search_is_bounded_not_universal_absence():
    result = assess_negative_evidence(
        hypothesis_id="H1",
        target_observation="expected signal",
        search_scope=("dataset-A", "dataset-B"),
        detection_sensitivity=0.95,
        coverage_fraction=0.9,
        negative_observation=True,
    )
    assert result.status == "BOUNDED_EVIDENCE_OF_ABSENCE"
    assert result.evidence_of_absence_strength == pytest.approx(0.855)
    assert result.universal_absence_proven is False


def test_nonnegative_observation_is_not_negative_evidence():
    result = assess_negative_evidence(
        hypothesis_id="H1",
        target_observation="expected signal",
        search_scope=("dataset-A",),
        detection_sensitivity=1.0,
        coverage_fraction=1.0,
        negative_observation=False,
    )
    assert result.status == "ABSENCE_OF_EVIDENCE_ONLY"
    assert "not negative" in result.reasons[0]


def test_negative_result_when_interval_inside_smallest_effect_band():
    result = preserve_null_result(
        experiment_id="exp1",
        hypothesis_id="H1",
        protocol_hash="a" * 64,
        metric="effect",
        effect_estimate=0.01,
        interval_lower=-0.04,
        interval_upper=0.05,
        smallest_effect_of_interest=0.1,
    )
    assert result.status == "NEGATIVE"
    assert result.adequately_sensitive is True
    assert result.supports_positive_claim is False
    assert result.proves_no_effect is False


def test_wide_interval_crossing_zero_is_null_not_no_effect_proof():
    result = preserve_null_result(
        experiment_id="exp1",
        hypothesis_id="H1",
        protocol_hash="a" * 64,
        metric="effect",
        effect_estimate=0.1,
        interval_lower=-0.5,
        interval_upper=0.7,
        smallest_effect_of_interest=0.1,
    )
    assert result.status == "NULL"
    assert result.adequately_sensitive is False
    assert result.proves_no_effect is False
    assert result.supports_positive_claim is False


def test_interval_not_crossing_zero_but_not_negligible_is_inconclusive_here():
    result = preserve_null_result(
        experiment_id="exp1",
        hypothesis_id="H1",
        protocol_hash="a" * 64,
        metric="effect",
        effect_estimate=0.4,
        interval_lower=0.2,
        interval_upper=0.6,
        smallest_effect_of_interest=0.1,
    )
    assert result.status == "INCONCLUSIVE"
    assert result.supports_positive_claim is False


def test_invalid_interval_protocol_and_numeric_values_fail_closed():
    base = dict(
        experiment_id="exp1",
        hypothesis_id="H1",
        protocol_hash="a" * 64,
        metric="effect",
        effect_estimate=0.0,
        interval_lower=-0.1,
        interval_upper=0.1,
        smallest_effect_of_interest=0.05,
    )
    with pytest.raises(ValueError, match="SHA-256"):
        preserve_null_result(**{**base, "protocol_hash": "bad"})
    with pytest.raises(ValueError, match="<="):
        preserve_null_result(**{**base, "interval_lower": 1.0, "interval_upper": -1.0})
    for bad in (math.nan, math.inf, -math.inf, True):
        with pytest.raises(ValueError):
            preserve_null_result(**{**base, "effect_estimate": bad})


def test_hashes_are_deterministic():
    kwargs = dict(
        hypothesis_id="H1",
        target_observation="expected signal",
        search_scope=("a", "b"),
        detection_sensitivity=0.9,
        coverage_fraction=0.9,
        negative_observation=True,
    )
    assert assess_negative_evidence(**kwargs).record_hash == assess_negative_evidence(**kwargs).record_hash
