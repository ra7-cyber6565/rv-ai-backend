import math

import pytest

from research_engine.adversarial_science import (
    AttackObservation,
    AttackProposal,
    AttackTarget,
    FalsificationPolicy,
    execute_registered_attacks,
    plan_falsification_campaign,
    red_team_coverage,
)


def _targets():
    return (
        AttackTarget("H1", "Champion mechanism produces the measured effect", 1.0, 0.45, True),
        AttackTarget("H2", "Alternative mechanism explains the same observation", 0.70, 0.65),
    )


def _proposals():
    return (
        AttackProposal(
            "A1", "H1", "COUNTEREXAMPLE", 2.0, 0.95, "group-counter",
            "observe a predeclared counterexample", "counterexample satisfies rejection criterion",
        ),
        AttackProposal(
            "A2", "H1", "ASSUMPTION_BREAK", 2.0, 0.85, "group-assumption",
            "remove the strongest assumption", "effect collapses after assumption removal",
        ),
        AttackProposal(
            "A3", "H2", "NEGATIVE_CONTROL", 2.0, 0.80, "group-control",
            "run the registered negative control", "control reproduces the claimed effect",
        ),
        AttackProposal(
            "A4", "H2", "OOD_STRESS", 2.0, 0.75, "group-ood",
            "evaluate the locked out-of-distribution case", "effect reverses outside training regime",
        ),
        AttackProposal(
            "A5", "H1", "PLACEBO_CONTROL", 1.0, 0.70, "group-placebo",
            "run the placebo arm", "placebo matches the claimed treatment response",
            safety_status="BLOCKED",
        ),
        AttackProposal(
            "A6", "H2", "LEAKAGE_PROBE", 1.0, 0.70, "group-leakage",
            "audit temporal and feature leakage", "registered leakage probe detects forbidden leakage",
            safety_status="REVIEW_REQUIRED",
        ),
    )


def _policy(**updates):
    values = dict(
        total_budget=8.0,
        champion_reserve_fraction=0.30,
        max_target_budget_fraction=0.70,
        min_attacks_per_target=1,
        min_attack_type_diversity=3,
        min_independent_groups=3,
        allow_review_required=False,
    )
    values.update(updates)
    return FalsificationPolicy(**values)


def test_budget_plan_reserves_champion_and_builds_diverse_red_team_campaign():
    plan = plan_falsification_campaign(_targets(), _proposals(), _policy())
    assert plan.status == "READY"
    assert plan.blockers == ()
    assert plan.planning_only is True
    assert plan.attacks_executed is False
    assert plan.truth_proven is False
    assert plan.survival_is_truth is False
    assert plan.champion_target_id == "H1"
    assert plan.champion_spent_budget >= plan.champion_reserved_budget
    assert plan.target_attack_counts["H1"] >= 1
    assert plan.target_attack_counts["H2"] >= 1
    assert len(plan.attack_types) >= 3
    assert len(plan.independent_groups) >= 3
    assert plan.spent_budget <= plan.total_budget
    assert len(plan.plan_hash) == 64

    rejected = {row.attack_id: row.reason for row in plan.rejected_attacks}
    assert rejected["A5"] == "safety_blocked"
    assert rejected["A6"] == "safety_review_required"


def test_planning_is_deterministic_and_order_invariant():
    first = plan_falsification_campaign(_targets(), _proposals(), _policy())
    second = plan_falsification_campaign(
        tuple(reversed(_targets())), tuple(reversed(_proposals())), _policy()
    )
    assert first.plan_hash == second.plan_hash
    assert first.selected_attacks == second.selected_attacks
    assert first.target_budget == second.target_budget


def test_exactly_one_precommitted_champion_is_required():
    with pytest.raises(ValueError, match="exactly one"):
        plan_falsification_campaign(
            (
                AttackTarget("H1", "first claim is sufficiently long", 1.0, 0.5),
                AttackTarget("H2", "second claim is sufficiently long", 0.8, 0.5),
            ),
            _proposals(),
            _policy(),
        )
    with pytest.raises(ValueError, match="exactly one"):
        plan_falsification_campaign(
            (
                AttackTarget("H1", "first claim is sufficiently long", 1.0, 0.5, True),
                AttackTarget("H2", "second claim is sufficiently long", 0.8, 0.5, True),
            ),
            _proposals(),
            _policy(),
        )


def test_duplicate_unknown_and_nonfinite_attack_inputs_fail_closed():
    duplicated = list(_proposals())
    duplicated.append(_proposals()[0])
    with pytest.raises(ValueError, match="attack_id values must be unique"):
        plan_falsification_campaign(_targets(), duplicated, _policy())

    unknown = list(_proposals())
    unknown[0] = AttackProposal(
        "UNKNOWN", "H999", "COUNTEREXAMPLE", 1.0, 0.5, "g",
        "observe the registered unknown target", "unknown target would be rejected",
    )
    with pytest.raises(ValueError, match="unknown target_id"):
        plan_falsification_campaign(_targets(), unknown, _policy())

    broken = list(_proposals())
    broken[0] = AttackProposal(
        "BAD", "H1", "COUNTEREXAMPLE", math.nan, 0.5, "g",
        "observe the registered bad case", "bad case would falsify the claim",
    )
    with pytest.raises(ValueError, match="finite"):
        plan_falsification_campaign(_targets(), broken, _policy())


def test_unsafe_or_unaffordable_campaign_stays_incomplete_not_fake_ready():
    proposals = (
        AttackProposal(
            "C1", "H1", "COUNTEREXAMPLE", 9.0, 0.9, "g1",
            "observe champion counterexample", "registered champion falsifier fires",
        ),
        AttackProposal(
            "C2", "H2", "NEGATIVE_CONTROL", 9.0, 0.9, "g2",
            "run alternative negative control", "negative control contradicts alternative",
        ),
    )
    plan = plan_falsification_campaign(
        _targets(), proposals, _policy(total_budget=4.0, min_attack_type_diversity=1, min_independent_groups=1)
    )
    assert plan.status == "INCOMPLETE"
    assert "champion_reserve_not_met" in plan.blockers
    assert any(item.startswith("target_coverage_incomplete:") for item in plan.blockers)
    assert plan.selected_attacks == ()
    assert plan.truth_proven is False


def test_target_budget_cap_prevents_one_claim_from_consuming_entire_attack_budget():
    proposals = (
        AttackProposal(
            "A1", "H1", "COUNTEREXAMPLE", 3.0, 0.99, "g1",
            "counterexample one is measured", "counterexample one rejects the claim",
        ),
        AttackProposal(
            "A2", "H1", "ASSUMPTION_BREAK", 3.0, 0.98, "g2",
            "assumption break is measured", "assumption break rejects the claim",
        ),
        AttackProposal(
            "A3", "H1", "OOD_STRESS", 3.0, 0.97, "g3",
            "out of distribution stress is measured", "OOD stress rejects the claim",
        ),
        AttackProposal(
            "A4", "H2", "NEGATIVE_CONTROL", 2.0, 0.60, "g4",
            "negative control is measured", "negative control rejects the alternative",
        ),
    )
    plan = plan_falsification_campaign(
        _targets(), proposals,
        _policy(total_budget=10.0, max_target_budget_fraction=0.6, min_attack_type_diversity=2, min_independent_groups=2),
    )
    assert plan.target_budget["H1"] <= 6.0
    assert plan.target_budget["H2"] > 0.0


def test_complete_execution_distinguishes_falsified_from_survived_without_truth_upgrade():
    plan = plan_falsification_campaign(_targets(), _proposals(), _policy())
    observations = []
    h1_attacks = [row for row in plan.selected_attacks if row.target_id == "H1"]
    falsifier = h1_attacks[0].attack_id
    for row in plan.selected_attacks:
        observations.append(
            AttackObservation(
                row.attack_id,
                "FALSIFIED" if row.attack_id == falsifier else "NOT_FALSIFIED",
                "registered measurement completed",
                "observer-1",
            )
        )
    report = execute_registered_attacks(plan, observations)
    assert report.execution_complete is True
    assert "H1" in report.falsified_target_ids
    assert "H2" in report.survived_target_ids
    assert report.truth_proven is False
    assert report.survival_is_truth is False
    assert report.scientific_verification_implied is False
    assert len(report.report_hash) == 64


def test_all_registered_attacks_surviving_still_does_not_prove_truth():
    plan = plan_falsification_campaign(_targets(), _proposals(), _policy())
    observations = [
        AttackObservation(row.attack_id, "NOT_FALSIFIED", "no registered falsifier fired", "observer-2")
        for row in plan.selected_attacks
    ]
    report = execute_registered_attacks(plan, observations)
    assert report.execution_complete is True
    assert set(report.survived_target_ids) == {"H1", "H2"}
    assert report.falsified_target_ids == ()
    assert report.truth_proven is False
    assert report.survival_is_truth is False


def test_post_hoc_attack_observation_is_rejected():
    plan = plan_falsification_campaign(_targets(), _proposals(), _policy())
    with pytest.raises(ValueError, match="unplanned attack"):
        execute_registered_attacks(
            plan,
            [AttackObservation("POSTHOC", "FALSIFIED", "invented after seeing data", "observer")],
        )


def test_missing_or_inconclusive_observation_does_not_count_as_survival():
    plan = plan_falsification_campaign(_targets(), _proposals(), _policy())
    first = plan.selected_attacks[0]
    partial = execute_registered_attacks(
        plan,
        [AttackObservation(first.attack_id, "NOT_FALSIFIED", "one attack completed", "observer")],
    )
    assert partial.execution_complete is False
    assert partial.inconclusive_target_ids

    complete = []
    for row in plan.selected_attacks:
        complete.append(
            AttackObservation(
                row.attack_id,
                "INCONCLUSIVE" if row.attack_id == first.attack_id else "NOT_FALSIFIED",
                "registered observation",
                "observer",
            )
        )
    inconclusive = execute_registered_attacks(plan, complete)
    assert inconclusive.execution_complete is True
    assert first.target_id in inconclusive.inconclusive_target_ids
    assert first.target_id not in inconclusive.survived_target_ids


def test_incomplete_plan_cannot_be_executed_as_if_valid():
    plan = plan_falsification_campaign(
        _targets(),
        (
            AttackProposal(
                "ONLY", "H1", "COUNTEREXAMPLE", 1.0, 0.9, "g1",
                "champion attack is measured", "champion attack rejects the claim",
            ),
        ),
        _policy(min_attack_type_diversity=1, min_independent_groups=1),
    )
    assert plan.status == "INCOMPLETE"
    with pytest.raises(ValueError, match="incomplete falsification plan"):
        execute_registered_attacks(
            plan,
            [AttackObservation("ONLY", "NOT_FALSIFIED", "completed", "observer")],
        )


def test_red_team_coverage_is_audit_metadata_not_quality_probability():
    plan = plan_falsification_campaign(_targets(), _proposals(), _policy())
    coverage = red_team_coverage(plan)
    assert coverage["status"] == "READY"
    assert coverage["target_coverage"] == 1.0
    assert coverage["champion_reserve_met"] is True
    assert coverage["planning_only"] is True
    assert coverage["truth_proven"] is False
