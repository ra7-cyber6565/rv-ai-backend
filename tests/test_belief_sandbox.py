import pytest

from research_engine.belief_sandbox import CandidateBelief, assess_sandbox_belief


def _belief(**overrides):
    data = dict(
        belief_id="B1",
        statement="A bounded candidate belief predicts a measurable outcome.",
        evidence_ids=("E1", "E2"),
        independent_groups=("G1", "G2"),
        falsifier="reject if preregistered outcome is absent",
        preregistered_predictions=("endpoint rises by at least the frozen threshold",),
        resolved_predictions=1,
        falsification_attempts=1,
        contradictions=(),
    )
    data.update(overrides)
    return CandidateBelief(**data)


def test_passing_sandbox_only_allows_promotion_proposal_not_canonical_mutation():
    result = assess_sandbox_belief(_belief())
    assert result.blockers == ()
    assert result.promotion_proposal_eligible is True
    assert result.canonical_state_mutated is False
    assert result.truth_proven is False
    assert len(result.sandbox_hash) == 64


@pytest.mark.parametrize(
    "overrides,blocker",
    [
        ({"evidence_ids": ("E1",)}, "insufficient_evidence"),
        ({"independent_groups": ("G1",)}, "insufficient_independence"),
        ({"falsifier": ""}, "falsifier_missing"),
        (
            {"preregistered_predictions": (), "resolved_predictions": 0},
            "preregistered_prediction_missing",
        ),
        ({"resolved_predictions": 0}, "insufficient_resolved_predictions"),
        ({"falsification_attempts": 0}, "insufficient_falsification_attempts"),
        (
            {"contradictions": ("credible contradiction remains unresolved",)},
            "unresolved_contradictions",
        ),
    ],
)
def test_each_missing_promotion_condition_blocks(overrides, blocker):
    result = assess_sandbox_belief(_belief(**overrides))
    assert blocker in result.blockers
    assert result.promotion_proposal_eligible is False
    assert result.canonical_state_mutated is False


def test_resolved_prediction_count_cannot_exceed_preregistered_predictions():
    with pytest.raises(ValueError, match="cannot exceed"):
        assess_sandbox_belief(_belief(resolved_predictions=2))


def test_thresholds_cannot_be_negative_or_unbounded():
    with pytest.raises(ValueError, match="minimum_evidence"):
        assess_sandbox_belief(_belief(), minimum_evidence=-1)
    with pytest.raises(ValueError, match="minimum_falsification_attempts"):
        assess_sandbox_belief(_belief(), minimum_falsification_attempts=1_000_001)


def test_set_like_inputs_are_hash_order_independent():
    first = assess_sandbox_belief(_belief())
    second = assess_sandbox_belief(_belief(
        evidence_ids=("E2", "E1", "E1"),
        independent_groups=("G2", "G1", "G1"),
    ))
    assert first.sandbox_hash == second.sandbox_hash
