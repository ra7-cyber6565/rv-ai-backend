import math

import pytest

from research_engine.benchmark_lab import (
    BenchmarkCase,
    ImprovementPolicy,
    build_locked_suite,
    compare_for_controlled_improvement,
    evaluate_candidate,
    verify_suite,
)


def _suite():
    return build_locked_suite(
        "core-v1",
        (
            BenchmarkCase("accuracy-1", {"x": 1}, {"y": 2}, weight=2.0),
            BenchmarkCase("accuracy-2", {"x": 2}, {"y": 4}, weight=1.0),
            BenchmarkCase(
                "safety-1",
                {"request": "unsafe"},
                {"must_refuse": True},
                weight=3.0,
                safety_critical=True,
                tags=("safety",),
            ),
        ),
    )


def _evaluator(score=1.0, safety_pass=True):
    def run(actual_input, expected):
        is_safety = isinstance(expected, dict) and expected.get("must_refuse") is True
        passed = safety_pass if is_safety else score >= 0.5
        return {
            "score": score if not is_safety else (1.0 if safety_pass else 0.0),
            "passed": passed,
            "details": {"checked": True},
        }

    return run


def test_locked_suite_is_order_independent_content_addressed_and_verifiable():
    first = _suite()
    second = build_locked_suite("core-v1", tuple(reversed(first.cases)))
    assert first.suite_hash == second.suite_hash
    assert first.locked is True
    assert verify_suite(first) is True
    assert [case.case_id for case in first.cases] == sorted(case.case_id for case in first.cases)


def test_candidate_report_is_deterministic_and_never_claims_real_world_truth():
    suite = _suite()
    first = evaluate_candidate(
        suite,
        candidate_id="model-a",
        implementation_hash="impl-a",
        evaluator_id="locked-evaluator-v1",
        evaluator=_evaluator(0.8),
    )
    second = evaluate_candidate(
        suite,
        candidate_id="model-a",
        implementation_hash="impl-a",
        evaluator_id="locked-evaluator-v1",
        evaluator=_evaluator(0.8),
    )
    assert first.report_hash == second.report_hash
    assert first.weighted_pass_rate == pytest.approx(1.0)
    assert first.safety_failures == ()
    assert first.benchmark_only is True
    assert first.real_world_superiority_proven is False
    assert first.truth_proven is False


def test_safety_regression_blocks_challenger_even_with_better_mean_score():
    suite = _suite()
    champion = evaluate_candidate(
        suite,
        candidate_id="champion",
        implementation_hash="impl-old",
        evaluator_id="locked-evaluator-v1",
        evaluator=_evaluator(0.6, safety_pass=True),
    )
    challenger = evaluate_candidate(
        suite,
        candidate_id="challenger",
        implementation_hash="impl-new",
        evaluator_id="locked-evaluator-v1",
        evaluator=_evaluator(1.0, safety_pass=False),
    )
    decision = compare_for_controlled_improvement(
        champion,
        challenger,
        policy=ImprovementPolicy(minimum_improvement=0.0),
        independent_validation_ids=("independent-run-1",),
    )
    assert decision.eligible_for_external_approval is False
    assert "challenger_safety_failure" in decision.reasons
    assert decision.human_approval_required is True
    assert decision.automatic_code_change_allowed is False
    assert decision.automatic_deployment_allowed is False
    assert decision.truth_proven is False


def test_challenger_only_becomes_eligible_for_external_approval_not_auto_promoted():
    suite = _suite()
    champion = evaluate_candidate(
        suite,
        candidate_id="champion",
        implementation_hash="impl-old",
        evaluator_id="locked-evaluator-v1",
        evaluator=_evaluator(0.6),
    )
    challenger = evaluate_candidate(
        suite,
        candidate_id="challenger",
        implementation_hash="impl-new",
        evaluator_id="locked-evaluator-v1",
        evaluator=_evaluator(0.9),
    )
    decision = compare_for_controlled_improvement(
        champion,
        challenger,
        policy=ImprovementPolicy(minimum_improvement=0.05, minimum_pass_rate=1.0),
        independent_validation_ids=("replication-a", "replication-b"),
    )
    assert decision.eligible_for_external_approval is True
    assert decision.reasons == ()
    assert decision.human_approval_required is True
    assert decision.automatic_code_change_allowed is False
    assert decision.automatic_deployment_allowed is False
    assert len(decision.comparison_hash) == 64


def test_missing_independent_validation_or_same_implementation_fails_closed():
    suite = _suite()
    champion = evaluate_candidate(
        suite,
        candidate_id="champion",
        implementation_hash="same",
        evaluator_id="evaluator-v1",
        evaluator=_evaluator(0.6),
    )
    challenger = evaluate_candidate(
        suite,
        candidate_id="challenger",
        implementation_hash="same",
        evaluator_id="evaluator-v1",
        evaluator=_evaluator(0.9),
    )
    decision = compare_for_controlled_improvement(champion, challenger)
    assert decision.eligible_for_external_approval is False
    assert "implementation_not_distinct" in decision.reasons
    assert "independent_validation_missing" in decision.reasons


def test_suite_and_evaluator_inputs_have_hard_validation_boundaries():
    with pytest.raises(ValueError, match="1..10000"):
        build_locked_suite("empty", ())
    with pytest.raises(ValueError, match="unique"):
        build_locked_suite(
            "dupes",
            (
                BenchmarkCase("same", 1, 1),
                BenchmarkCase("same", 2, 2),
            ),
        )
    with pytest.raises(ValueError, match="weight"):
        BenchmarkCase("bad", {}, {}, weight=0.0).normalized()
    with pytest.raises(ValueError, match="finite JSON"):
        BenchmarkCase("bad-json", {"x": float("nan")}, {}).normalized()

    suite = _suite()

    def bad_schema(_input, _expected):
        return {"score": 1.0, "passed": True, "secret_extra": 1}

    with pytest.raises(ValueError, match="schema invalid"):
        evaluate_candidate(
            suite,
            candidate_id="bad",
            implementation_hash="impl",
            evaluator_id="eval",
            evaluator=bad_schema,
        )

    def nonfinite(_input, _expected):
        return {"score": math.inf, "passed": True}

    with pytest.raises(ValueError, match="must be finite"):
        evaluate_candidate(
            suite,
            candidate_id="bad2",
            implementation_hash="impl",
            evaluator_id="eval",
            evaluator=nonfinite,
        )


def test_evaluator_exception_is_sanitized_to_case_failure_context():
    suite = _suite()

    def explode(_input, _expected):
        raise RuntimeError("provider secret must not escape through result")

    with pytest.raises(RuntimeError, match="benchmark evaluator failed for case accuracy-1") as exc:
        evaluate_candidate(
            suite,
            candidate_id="boom",
            implementation_hash="impl",
            evaluator_id="eval",
            evaluator=explode,
        )
    assert "provider secret" not in str(exc.value)
