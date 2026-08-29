import pytest

from research_engine.claim_insurance import ClaimInsuranceInput, assess_claim_insurance


def _claim(**overrides):
    data = dict(
        claim_id="C1",
        statement="This high-impact claim is supported by measured evidence.",
        impact_if_wrong=0.9,
        supporting_evidence_ids=("E1", "E2", "E3"),
        independent_groups=("G1", "G2"),
        uncertainty_upper_bound=0.2,
        falsifier="reject if preregistered endpoint reverses direction",
        revalidation_trigger="revalidate after dataset or model revision",
        monitoring_signal="track endpoint drift and contradiction rate",
        rollback_plan="revert dependent recommendation and reopen claim",
        strong_label_requested=True,
    )
    data.update(overrides)
    return ClaimInsuranceInput(**data)


def test_high_impact_claim_needs_full_downside_contract():
    result = assess_claim_insurance(_claim())
    assert result.required_support_count == 3
    assert result.required_independent_groups == 2
    assert result.blockers == ()
    assert result.eligible_for_operational_reliance is True
    assert result.strong_label_allowed_by_insurance_gate is True
    assert result.truth_guaranteed is False
    assert result.monetary_insurance is False
    assert len(result.assessment_hash) == 64


@pytest.mark.parametrize(
    "field, value, blocker",
    [
        ("supporting_evidence_ids", ("E1", "E2"), "insufficient_supporting_evidence"),
        ("independent_groups", ("G1",), "insufficient_independent_evidence"),
        ("uncertainty_upper_bound", 0.3, "uncertainty_exceeds_impact_tolerance"),
        ("falsifier", "", "falsifier_missing"),
        ("revalidation_trigger", "", "revalidation_trigger_missing"),
        ("monitoring_signal", "", "monitoring_signal_missing"),
        ("rollback_plan", "", "rollback_plan_missing"),
    ],
)
def test_each_missing_protection_blocks_high_impact_reliance(field, value, blocker):
    result = assess_claim_insurance(_claim(**{field: value}))
    assert blocker in result.blockers
    assert result.eligible_for_operational_reliance is False
    assert result.strong_label_allowed_by_insurance_gate is False


def test_impact_adapts_evidence_floor_without_ever_guaranteeing_truth():
    medium = assess_claim_insurance(_claim(
        impact_if_wrong=0.6,
        supporting_evidence_ids=("E1", "E2"),
        uncertainty_upper_bound=0.35,
    ))
    low = assess_claim_insurance(_claim(
        impact_if_wrong=0.2,
        supporting_evidence_ids=("E1",),
        independent_groups=("G1",),
        uncertainty_upper_bound=0.55,
    ))
    assert medium.required_support_count == 2
    assert medium.eligible_for_operational_reliance is True
    assert low.required_support_count == 1
    assert low.required_independent_groups == 1
    assert low.eligible_for_operational_reliance is True
    assert medium.truth_guaranteed is low.truth_guaranteed is False


def test_no_strong_label_request_does_not_magically_create_one():
    result = assess_claim_insurance(_claim(strong_label_requested=False))
    assert result.eligible_for_operational_reliance is True
    assert result.strong_label_allowed_by_insurance_gate is False


@pytest.mark.parametrize("field,value", [
    ("impact_if_wrong", float("nan")),
    ("impact_if_wrong", 1.1),
    ("uncertainty_upper_bound", float("inf")),
    ("uncertainty_upper_bound", -0.1),
])
def test_nonfinite_or_out_of_range_risk_inputs_fail_closed(field, value):
    with pytest.raises(ValueError):
        assess_claim_insurance(_claim(**{field: value}))


def test_assessment_hash_is_order_independent_for_set_like_evidence():
    first = assess_claim_insurance(_claim())
    second = assess_claim_insurance(_claim(
        supporting_evidence_ids=("E3", "E1", "E2", "E2"),
        independent_groups=("G2", "G1", "G1"),
    ))
    assert first.assessment_hash == second.assessment_hash
