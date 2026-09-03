import pytest

from research_engine.manufacturing_reality import (
    ManufacturingEvidence,
    ManufacturingRequirement,
    audit_manufacturing_reality,
)


def _measured(evidence_id, requirement_id, **kwargs):
    return ManufacturingEvidence(
        evidence_id=evidence_id,
        requirement_id=requirement_id,
        environment=kwargs.pop("environment", "PILOT"),
        provenance_ref=f"receipt://{evidence_id}",
        sample_size=kwargs.pop("sample_size", 100),
        measured=kwargs.pop("measured", True),
        hardware_observed=kwargs.pop("hardware_observed", True),
        independent=kwargs.pop("independent", True),
        reproducible=kwargs.pop("reproducible", True),
        **kwargs,
    )


def test_process_capability_computes_cpk_and_does_not_claim_factory_truth():
    report = audit_manufacturing_reality(
        requirements=[ManufacturingRequirement(
            "dim", "PROCESS_CAPABILITY", unit="mm",
            lower_spec=9.5, upper_spec=10.5, minimum_cpk=1.33,
            minimum_sample_size=50, require_independent=True,
        )],
        evidence=[_measured("study-1", "dim", mean=10.0, stddev=0.1)],
    )
    audit = report.audits[0]
    assert audit.passed is True
    assert audit.cp == pytest.approx(1.6666666667)
    assert audit.cpk == pytest.approx(1.6666666667)
    assert report.all_requirements_passed is True
    assert report.factory_execution_proven is False
    assert report.hardware_authenticity_proven is False
    assert report.manufacturability_truth_proven is False
    assert report.external_certification_claimed is False


def test_unfavorable_capability_study_cannot_be_hidden_by_better_study():
    report = audit_manufacturing_reality(
        requirements=[ManufacturingRequirement(
            "dim", "PROCESS_CAPABILITY", unit="mm",
            lower_spec=9.5, upper_spec=10.5, minimum_cpk=1.33,
            minimum_sample_size=50,
        )],
        evidence=[
            _measured("good", "dim", mean=10.0, stddev=0.08, sample_size=50),
            _measured("bad", "dim", mean=10.3, stddev=0.15, sample_size=50),
        ],
    )
    audit = report.audits[0]
    assert audit.passed is False
    assert "cpk_below_requirement" in audit.blockers
    assert audit.cpk < 1.33


def test_yield_and_tolerance_require_real_measured_hardware_evidence():
    requirements = [
        ManufacturingRequirement("yield", "YIELD", minimum_yield=0.95, minimum_sample_size=100),
        ManufacturingRequirement(
            "tol", "TOLERANCE_VERIFICATION", unit="mm",
            lower_spec=0.9, upper_spec=1.1, minimum_sample_size=3,
        ),
    ]
    evidence = [
        _measured("yield-study", "yield", accepted_count=98, total_count=100, sample_size=100),
        _measured("tol-study", "tol", measured_values=(0.95, 1.0, 1.05), sample_size=3),
    ]
    report = audit_manufacturing_reality(requirements=requirements, evidence=evidence)
    assert all(item.passed for item in report.audits)
    assert report.audits[0].observed_yield == pytest.approx(0.98)
    assert report.audits[1].out_of_tolerance_count == 0

    simulated = audit_manufacturing_reality(
        requirements=[requirements[0]],
        evidence=[_measured(
            "sim", "yield", accepted_count=100, total_count=100,
            measured=False, hardware_observed=False, environment="SIMULATION",
        )],
    )
    assert simulated.audits[0].passed is False
    assert "measured_evidence_missing" in simulated.audits[0].blockers
    assert "hardware_observation_missing" in simulated.audits[0].blockers
    assert simulated.simulation_promoted_to_measurement is False


def test_qualitative_gate_needs_explicit_pass_and_required_environment():
    report = audit_manufacturing_reality(
        requirements=[ManufacturingRequirement(
            "material", "QUALITATIVE_GATE", minimum_sample_size=1,
            require_production_environment=True,
        )],
        evidence=[_measured(
            "material-check", "material", explicit_pass=True, environment="LAB",
        )],
    )
    assert report.audits[0].passed is False
    assert "production_environment_evidence_missing" in report.audits[0].blockers


def test_invalid_counts_nonfinite_stats_unknown_requirement_and_duplicates_fail_closed():
    requirement = ManufacturingRequirement(
        "yield", "YIELD", minimum_yield=0.9, minimum_sample_size=1,
    )
    with pytest.raises(ValueError, match="accepted_count/total_count"):
        audit_manufacturing_reality(
            requirements=[requirement],
            evidence=[_measured("bad", "yield", accepted_count=11, total_count=10)],
        )
    with pytest.raises(ValueError, match="must be finite"):
        audit_manufacturing_reality(
            requirements=[ManufacturingRequirement(
                "cpk", "PROCESS_CAPABILITY", lower_spec=0, upper_spec=1,
                minimum_cpk=1.0,
            )],
            evidence=[_measured("bad", "cpk", mean=0.5, stddev=float("nan"))],
        )
    with pytest.raises(ValueError, match="unknown requirement_id"):
        audit_manufacturing_reality(
            requirements=[requirement],
            evidence=[_measured("other", "missing", accepted_count=1, total_count=1)],
        )
    with pytest.raises(ValueError, match="must be unique"):
        audit_manufacturing_reality(
            requirements=[requirement],
            evidence=[
                _measured("dup", "yield", accepted_count=1, total_count=1),
                _measured("dup", "yield", accepted_count=1, total_count=1),
            ],
        )
