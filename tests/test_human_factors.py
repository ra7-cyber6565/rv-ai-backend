import pytest

from research_engine.human_factors import (
    HumanFactorsRequirement,
    HumanStudyEvidence,
    audit_human_factors,
)


def _study(study_id="s1", requirement_id="r1", **kwargs):
    return HumanStudyEvidence(
        study_id=study_id,
        requirement_id=requirement_id,
        task_id=kwargs.pop("task_id", "task-A"),
        environment=kwargs.pop("environment", "FIELD"),
        provenance_ref=f"receipt://{study_id}",
        participant_count=kwargs.pop("participant_count", 20),
        successful_tasks=kwargs.pop("successful_tasks", 19),
        attempted_tasks=kwargs.pop("attempted_tasks", 20),
        critical_errors=kwargs.pop("critical_errors", 0),
        adverse_events=kwargs.pop("adverse_events", 0),
        completion_seconds=kwargs.pop("completion_seconds", tuple(range(10, 30))),
        workload_scores=kwargs.pop("workload_scores", (20.0,) * 20),
        real_humans_observed=kwargs.pop("real_humans_observed", True),
        independent=kwargs.pop("independent", True),
        ethics_reviewed=kwargs.pop("ethics_reviewed", True),
        consent_documented=kwargs.pop("consent_documented", True),
        safety_reviewed=kwargs.pop("safety_reviewed", True),
        **kwargs,
    )


def _requirement(**kwargs):
    return HumanFactorsRequirement(
        requirement_id=kwargs.pop("requirement_id", "r1"),
        task_id=kwargs.pop("task_id", "task-A"),
        minimum_participants=kwargs.pop("minimum_participants", 20),
        minimum_task_success=kwargs.pop("minimum_task_success", 0.9),
        maximum_critical_error_rate=kwargs.pop("maximum_critical_error_rate", 0.05),
        maximum_adverse_event_rate=kwargs.pop("maximum_adverse_event_rate", 0.01),
        maximum_p95_completion_seconds=kwargs.pop("maximum_p95_completion_seconds", 30.0),
        maximum_p95_workload_score=kwargs.pop("maximum_p95_workload_score", 40.0),
        require_real_humans=kwargs.pop("require_real_humans", True),
        require_field_or_operational=kwargs.pop("require_field_or_operational", True),
        require_independent=kwargs.pop("require_independent", True),
        require_ethics_review=kwargs.pop("require_ethics_review", True),
        require_consent=kwargs.pop("require_consent", True),
        require_safety_review=kwargs.pop("require_safety_review", True),
        **kwargs,
    )


def test_real_human_field_study_can_pass_contract_without_population_truth_claim():
    report = audit_human_factors(requirements=[_requirement()], studies=[_study()])
    audit = report.audits[0]
    assert audit.passed is True
    assert audit.task_success_rate == pytest.approx(0.95)
    assert audit.critical_error_rate == 0
    assert audit.adverse_event_rate == 0
    assert audit.p95_completion_seconds == 28
    assert audit.p95_workload_score == 20
    assert report.all_requirements_passed is True
    assert report.agent_simulation_promoted_to_human_evidence is False
    assert report.population_generalization_proven is False
    assert report.human_safety_truth_proven is False
    assert report.external_certification_claimed is False


def test_agent_or_simulated_study_cannot_satisfy_real_human_requirement():
    report = audit_human_factors(
        requirements=[_requirement(require_independent=False)],
        studies=[_study(
            environment="SIMULATION",
            real_humans_observed=False,
            independent=False,
        )],
    )
    audit = report.audits[0]
    assert audit.passed is False
    assert "real_human_observation_missing" in audit.blockers
    assert "field_or_operational_study_missing" in audit.blockers
    assert report.agent_simulation_promoted_to_human_evidence is False


def test_missing_ethics_consent_safety_or_independence_blocks_even_good_metrics():
    report = audit_human_factors(
        requirements=[_requirement()],
        studies=[_study(
            independent=False,
            ethics_reviewed=False,
            consent_documented=False,
            safety_reviewed=False,
        )],
    )
    blockers = set(report.audits[0].blockers)
    assert {
        "independent_study_missing",
        "ethics_review_missing",
        "consent_documentation_missing",
        "safety_review_missing",
    }.issubset(blockers)


def test_bad_metrics_and_small_sample_fail_closed():
    report = audit_human_factors(
        requirements=[_requirement(minimum_participants=50)],
        studies=[_study(
            participant_count=10,
            successful_tasks=7,
            attempted_tasks=10,
            critical_errors=2,
            adverse_events=1,
            completion_seconds=(10, 20, 50),
            workload_scores=(20, 40, 80),
        )],
    )
    blockers = set(report.audits[0].blockers)
    assert "participant_count_below_requirement" in blockers
    assert "task_success_below_requirement" in blockers
    assert "critical_error_rate_above_requirement" in blockers
    assert "adverse_event_rate_above_requirement" in blockers
    assert "p95_completion_time_above_requirement" in blockers
    assert "p95_workload_above_requirement" in blockers


def test_wrong_task_does_not_get_borrowed_and_invalid_data_fail_closed():
    report = audit_human_factors(
        requirements=[_requirement()],
        studies=[_study(task_id="other-task")],
    )
    assert report.audits[0].passed is False
    assert "human_study_evidence_missing" in report.audits[0].blockers

    with pytest.raises(ValueError, match="task success counts"):
        audit_human_factors(
            requirements=[_requirement()],
            studies=[_study(successful_tasks=21, attempted_tasks=20)],
        )
    with pytest.raises(ValueError, match="must be finite"):
        audit_human_factors(
            requirements=[_requirement()],
            studies=[_study(completion_seconds=(10.0, float("nan")))],
        )
    with pytest.raises(ValueError, match="must be unique"):
        audit_human_factors(
            requirements=[_requirement()],
            studies=[_study("dup"), _study("dup")],
        )
