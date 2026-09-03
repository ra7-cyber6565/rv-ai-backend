import math

import pytest

from research_engine.research_strategy import (
    ResearchSignals,
    RoundProgress,
    adapt_depth_after_rounds,
    assess_research_saturation,
    select_research_strategy,
)


def _signals(**overrides):
    data = dict(
        complexity=0.5,
        uncertainty=0.5,
        stakes=0.5,
        novelty=0.5,
        evidence_gap=0.5,
        contradiction_pressure=0.3,
        unresolved_critical_gaps=0,
        unresolved_contradictions=0,
        user_latency_priority=0.5,
        resource_pressure=0.5,
    )
    data.update(overrides)
    return ResearchSignals(**data)


def _round(index, **overrides):
    data = dict(
        round_index=index,
        new_relevant_sources=0,
        new_independent_sources=0,
        claims_newly_supported=0,
        contradictions_resolved=0,
        novel_evidence_fraction=0.02,
        remaining_critical_gaps=0,
        remaining_contradictions=0,
    )
    data.update(overrides)
    return RoundProgress(**data)


def test_high_stakes_quick_is_ineligible_even_under_cost_pressure():
    decision = select_research_strategy(_signals(
        stakes=0.95,
        resource_pressure=1.0,
        user_latency_priority=1.0,
    ))
    quick = next(row for row in decision.scores if row.mode == "QUICK")
    assert quick.eligible is False
    assert any("high stakes" in blocker for blocker in quick.blockers)
    assert decision.selected_mode != "QUICK"
    assert decision.evidence_floor_overrode_cost is True
    assert decision.truth_probability is False


def test_critical_gap_forbids_quick_and_large_gap_requires_fulltext_depth():
    decision = select_research_strategy(_signals(
        unresolved_critical_gaps=2,
        evidence_gap=0.9,
        resource_pressure=1.0,
    ))
    quick = next(row for row in decision.scores if row.mode == "QUICK")
    assert quick.eligible is False
    assert any("critical evidence gaps" in blocker for blocker in quick.blockers)
    assert any("full-text" in blocker for blocker in quick.blockers)


def test_unresolved_contradictions_require_red_team_capable_strategy():
    decision = select_research_strategy(_signals(
        unresolved_contradictions=1,
        contradiction_pressure=0.9,
    ))
    quick = next(row for row in decision.scores if row.mode == "QUICK")
    assert quick.eligible is False
    assert any("red-team" in blocker for blocker in quick.blockers)
    assert decision.selected_config["use_red_team"] is True


def test_strategy_is_deterministic_and_bounded_to_existing_presets():
    first = select_research_strategy(_signals())
    second = select_research_strategy(_signals())
    assert first.decision_hash == second.decision_hash
    assert first.selected_mode in {"QUICK", "DEEP", "MAXIMUM", "MARATHON"}
    assert first.selected_config["max_sources"] <= 40
    assert first.selected_config["gemini_calls"] <= 4


def test_invalid_nan_inf_or_negative_counts_fail_closed():
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            select_research_strategy(_signals(complexity=bad))
    with pytest.raises(ValueError):
        select_research_strategy(_signals(unresolved_critical_gaps=-1))


def test_two_consecutive_low_gain_rounds_can_saturate_when_no_gaps_remain():
    result = assess_research_saturation([_round(1), _round(2)])
    assert result.saturated is True
    assert result.consecutive_low_gain_rounds == 2
    assert result.recommended_action == "STOP_EARLY_SATURATED"
    assert result.truth_proven is False


def test_single_low_gain_round_is_not_enough():
    result = assess_research_saturation([_round(1)])
    assert result.saturated is False
    assert "minimum research rounds" in result.blockers[0]


def test_critical_gap_blocks_saturation_despite_zero_marginal_gain():
    result = assess_research_saturation([
        _round(1, remaining_critical_gaps=1),
        _round(2, remaining_critical_gaps=1),
    ])
    assert result.saturated is False
    assert "critical evidence gaps remain" in result.blockers


def test_unresolved_contradiction_blocks_saturation():
    result = assess_research_saturation([
        _round(1, remaining_contradictions=1),
        _round(2, remaining_contradictions=1),
    ])
    assert result.saturated is False
    assert "unresolved contradictions remain" in result.blockers


def test_recent_high_information_gain_prevents_saturation():
    result = assess_research_saturation([
        _round(1),
        _round(2, new_independent_sources=3, claims_newly_supported=2, novel_evidence_fraction=0.8),
    ])
    assert result.saturated is False
    assert result.consecutive_low_gain_rounds == 0
    assert "marginal information gain" in result.blockers[-1]


def test_require_all_rounds_blocks_early_stop_even_when_saturated_otherwise():
    result = assess_research_saturation([_round(1), _round(2)], require_all_rounds=True)
    assert result.saturated is False
    assert "configured depth requires all research rounds" in result.blockers


def test_adaptive_depth_stops_only_on_true_saturation():
    result = adapt_depth_after_rounds("DEEP", _signals(), [_round(1), _round(2)])
    assert result["action"] == "STOP"
    assert result["next_mode"] == "DEEP"
    assert result["truth_proven"] is False


def test_adaptive_depth_escalates_at_most_one_tier_per_round():
    result = adapt_depth_after_rounds(
        "QUICK",
        _signals(
            complexity=1.0,
            uncertainty=1.0,
            stakes=1.0,
            novelty=1.0,
            evidence_gap=1.0,
            contradiction_pressure=1.0,
            unresolved_critical_gaps=5,
            unresolved_contradictions=5,
        ),
        [
            _round(1, new_independent_sources=3, remaining_critical_gaps=5, remaining_contradictions=5),
            _round(2, new_independent_sources=3, remaining_critical_gaps=5, remaining_contradictions=5),
        ],
    )
    assert result["action"] == "CONTINUE"
    assert result["next_mode"] == "DEEP"


def test_round_indices_must_be_unique_and_increasing():
    with pytest.raises(ValueError, match="unique and increasing"):
        assess_research_saturation([_round(2), _round(1)])
    with pytest.raises(ValueError, match="unique and increasing"):
        assess_research_saturation([_round(1), _round(1)])
