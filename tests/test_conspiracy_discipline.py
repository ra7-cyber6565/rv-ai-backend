import pytest

from research_engine.conspiracy_discipline import (
    ConspiracyHypothesisInput,
    HypothesisEvidence,
    assess_conspiracy_hypothesis,
)


def _e(eid, sid, group, supports=True, **kwargs):
    return HypothesisEvidence(eid, sid, group, supports, **kwargs)


def _hypothesis(**overrides):
    data = dict(
        hypothesis_id="H1",
        statement="A coordinated mechanism produces a measurable observable effect.",
        mechanism="Specified actors change a specified variable through a measurable channel.",
        falsifier="reject if preregistered discriminator remains absent in the locked holdout",
        preregistered_predictions=("observable Z changes before outcome Y under condition X",),
        evidence=(
            _e("E1", "S1", "G1", True, direct_observation=True),
            _e("E2", "S2", "G2", True),
        ),
        disconfirming_search_performed=True,
        alternative_explanations_considered=("ordinary market incentives explain the same pattern",),
    )
    data.update(overrides)
    return ConspiracyHypothesisInput(**data)


def test_disciplined_hypothesis_can_be_researched_without_claiming_truth():
    result = assess_conspiracy_hypothesis(_hypothesis())
    assert result.blockers == ()
    assert result.eligible_for_neutral_research is True
    assert result.eligible_for_strong_label is True
    assert result.independent_support_groups == 2
    assert result.absence_of_evidence_treated_as_proof is False
    assert result.truth_proven is False


def test_absence_of_expected_evidence_never_counts_as_positive_support():
    result = assess_conspiracy_hypothesis(_hypothesis(evidence=(
        _e("E1", "S1", "G1", True, absence_of_expected_evidence=True),
        _e("E2", "S2", "G2", True, absence_of_expected_evidence=True),
    )))
    assert result.independent_support_groups == 0
    assert "insufficient_independent_support" in result.blockers
    assert result.eligible_for_neutral_research is True
    assert result.eligible_for_strong_label is False


@pytest.mark.parametrize(
    "field,value,blocker",
    [
        ("mechanism", "", "mechanism_missing"),
        ("falsifier", "", "falsifier_missing"),
        ("preregistered_predictions", (), "preregistered_prediction_missing"),
        ("disconfirming_search_performed", False, "disconfirming_search_missing"),
        ("alternative_explanations_considered", (), "alternative_explanation_missing"),
        ("evidence", (_e("E1", "S1", "G1", True),), "insufficient_independent_support"),
    ],
)
def test_missing_scientific_discipline_blocks_strong_label_not_research(field, value, blocker):
    result = assess_conspiracy_hypothesis(_hypothesis(**{field: value}))
    assert blocker in result.blockers
    assert result.eligible_for_neutral_research is True
    assert result.eligible_for_strong_label is False


def test_contradicting_evidence_is_surfaced_and_blocks_unqualified_strong_label():
    result = assess_conspiracy_hypothesis(_hypothesis(evidence=(
        _e("E1", "S1", "G1", True),
        _e("E2", "S2", "G2", True),
        _e("E3", "S3", "G3", False),
    )))
    assert result.independent_contradiction_groups == 1
    assert "contradicting_evidence_present" in result.blockers
    assert result.eligible_for_strong_label is False


def test_incomplete_provenance_cannot_sneak_into_strong_label():
    result = assess_conspiracy_hypothesis(_hypothesis(evidence=(
        _e("E1", "S1", "G1", True),
        _e("E2", "S2", "G2", True, provenance_complete=False),
        _e("E3", "S3", "G3", True),
    )))
    assert "incomplete_provenance_present" in result.blockers
    assert result.eligible_for_strong_label is False


def test_duplicate_source_cannot_be_counted_twice_as_independent_evidence():
    with pytest.raises(ValueError, match="one source cannot be duplicated"):
        assess_conspiracy_hypothesis(_hypothesis(evidence=(
            _e("E1", "S1", "G1", True),
            _e("E2", "S1", "G2", True),
        )))


def test_assessment_hash_is_independent_of_set_like_ordering():
    first = assess_conspiracy_hypothesis(_hypothesis())
    second = assess_conspiracy_hypothesis(_hypothesis(
        evidence=(
            _e("E2", "S2", "G2", True),
            _e("E1", "S1", "G1", True, direct_observation=True),
        ),
    ))
    assert first.assessment_hash == second.assessment_hash
