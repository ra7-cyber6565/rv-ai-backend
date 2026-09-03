import pytest

from research_engine.autonomous_debugging import (
    FailureFactor,
    PatchCandidate,
    StageObservation,
    diagnose_stage_failures,
    minimize_reproducing_factors,
    plan_graceful_degradation,
    validate_patch_candidates,
)


def test_dependency_root_failure_is_separated_from_downstream_symptoms():
    stages = (
        StageObservation("fetch", "PASS", critical=True),
        StageObservation("parse", "FAIL", ("fetch",), "ParseError", "fp-parse", critical=True),
        StageObservation("analyze", "FAIL", ("parse",), "AnalysisError", "fp-analysis", critical=True),
        StageObservation("optional-chart", "BLOCKED", ("analyze",), critical=False),
    )
    diagnosis = diagnose_stage_failures(stages)
    assert diagnosis.root_failure_ids == ("parse",)
    assert diagnosis.downstream_failure_ids == ("analyze",)
    assert diagnosis.blocked_by_ids["analyze"] == ("parse",)
    assert diagnosis.blocked_by_ids["optional-chart"] == ("analyze",)
    assert diagnosis.root_cause_proven is False
    assert len(diagnosis.diagnosis_hash) == 64


def test_failure_diagnosis_is_order_independent_and_unknown_dependencies_fail_closed():
    stages = (
        StageObservation("a", "PASS"),
        StageObservation("b", "FAIL", ("a",), "ErrorB", "fp-b"),
    )
    first = diagnose_stage_failures(stages)
    second = diagnose_stage_failures(tuple(reversed(stages)))
    assert first.diagnosis_hash == second.diagnosis_hash

    with pytest.raises(ValueError, match="unknown dependencies"):
        diagnose_stage_failures(
            (StageObservation("b", "FAIL", ("missing",), "ErrorB", "fp-b"),)
        )


def test_factor_minimization_finds_one_minimal_reproducer_without_claiming_causality():
    factors = (
        FailureFactor.from_payload("A", {"flag": 1}),
        FailureFactor.from_payload("B", {"noise": 2}),
        FailureFactor.from_payload("C", {"setting": 3}),
    )

    def reproducer(items):
        ids = {item.factor_id for item in items}
        return {"A", "C"}.issubset(ids)

    report = minimize_reproducing_factors(factors, reproducer, max_calls=20)
    assert report.minimal_factor_ids == ("A", "C")
    assert report.reproduced is True
    assert report.one_minimal is True
    assert report.causal_root_proven is False
    assert report.calls_used <= 20


def test_nonreproducing_failure_and_budget_exhaustion_are_explicit():
    factors = (
        FailureFactor.from_payload("A", 1),
        FailureFactor.from_payload("B", 2),
    )
    no_repro = minimize_reproducing_factors(factors, lambda _items: False)
    assert no_repro.reproduced is False
    assert no_repro.minimal_factor_ids == ()
    assert no_repro.one_minimal is False

    limited = minimize_reproducing_factors(factors, lambda _items: True, max_calls=1)
    assert limited.reproduced is True
    assert limited.one_minimal is False
    assert limited.calls_used == 1


def test_validated_patch_is_only_eligible_for_external_approval_never_auto_applied():
    candidate = PatchCandidate(
        candidate_id="patch-a",
        description="Correct bounded parsing of malformed numeric telemetry",
        patch_hash="a" * 64,
        affected_components=("parser",),
        risk="LOW",
    )

    def validator(_candidate):
        return {
            "original_failure_fixed": True,
            "regression_suite_passed": True,
            "safety_suite_passed": True,
            "reproducibility_check_passed": True,
            "metrics": {"tests_passed": 100.0},
        }

    result = validate_patch_candidates((candidate,), validator)[0]
    assert result.eligible_for_external_approval is True
    assert result.rejection_reasons == ()
    assert result.automatic_apply_allowed is False
    assert result.automatic_merge_allowed is False
    assert result.automatic_deploy_allowed is False
    assert len(result.result_hash) == 64


def test_safety_regression_and_high_risk_patch_are_blocked():
    candidate = PatchCandidate(
        candidate_id="patch-risky",
        description="Large risky refactor with unresolved safety regression",
        patch_hash="b" * 64,
        affected_components=("safety-gate", "runtime"),
        risk="HIGH",
    )

    result = validate_patch_candidates(
        (candidate,),
        lambda _candidate: {
            "original_failure_fixed": True,
            "regression_suite_passed": True,
            "safety_suite_passed": False,
            "reproducibility_check_passed": True,
            "metrics": {},
        },
    )[0]
    assert result.eligible_for_external_approval is False
    assert "safety_suite_failed" in result.rejection_reasons
    assert "high_risk_patch_requires_manual_redesign" in result.rejection_reasons


def test_patch_validator_exception_is_sanitized():
    candidate = PatchCandidate(
        "patch-a",
        "Bounded patch candidate",
        "c" * 64,
        ("parser",),
        "LOW",
    )

    def explode(_candidate):
        raise RuntimeError("secret provider diagnostic")

    with pytest.raises(RuntimeError, match="patch validator failed for candidate patch-a") as exc:
        validate_patch_candidates((candidate,), explode)
    assert "secret provider diagnostic" not in str(exc.value)


def test_graceful_degradation_never_skips_or_marks_critical_failure_as_safe():
    stages = (
        StageObservation("retrieve", "PASS", critical=True),
        StageObservation("verify", "FAIL", ("retrieve",), "VerifyError", "fp-v", critical=True),
        StageObservation("pretty-chart", "BLOCKED", ("verify",), critical=False),
        StageObservation("optional-summary", "SKIP", critical=False),
    )
    plan = plan_graceful_degradation(stages)
    assert "retrieve" in plan.executable_stage_ids
    assert "verify" in plan.blocked_critical_stage_ids
    assert set(plan.skipped_optional_stage_ids) == {"optional-summary", "pretty-chart"}
    assert plan.hard_gates_weakened is False
    assert len(plan.plan_hash) == 64


def test_invalid_stage_and_patch_schemas_fail_closed():
    with pytest.raises(ValueError, match="unsupported stage status"):
        StageObservation("x", "MAYBE").normalized()
    with pytest.raises(ValueError, match="failed stage requires error_class"):
        StageObservation("x", "FAIL").normalized()
    with pytest.raises(ValueError, match="non-failed stage"):
        StageObservation("x", "PASS", error_class="Unexpected").normalized()
    with pytest.raises(ValueError, match="SHA-256"):
        PatchCandidate("p", "description", "not-a-hash", ("core",)).normalized()

    good = PatchCandidate("p", "description", "d" * 64, ("core",))
    with pytest.raises(ValueError, match="schema invalid"):
        validate_patch_candidates((good,), lambda _candidate: {"original_failure_fixed": True})
