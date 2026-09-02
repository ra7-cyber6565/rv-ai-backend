import pytest

from research_engine.physical_reality import (
    PhysicalConstraint,
    PhysicalObservation,
    audit_physical_reality,
)


def _obs(obs_id, variable, value, *, unit="m", kind="MEASURED", time=None):
    return PhysicalObservation(
        observation_id=obs_id,
        variable=variable,
        value=value,
        unit=unit,
        evidence_kind=kind,
        provenance_ref=f"receipt://{obs_id}",
        timestamp_seconds=time,
    )


def test_measured_range_and_conservation_can_pass_without_claiming_physical_truth():
    report = audit_physical_reality(
        observations=[
            _obs("a", "inflow", 4.0, unit="kg"),
            _obs("b", "outflow", 4.01, unit="kg"),
        ],
        constraints=[
            PhysicalConstraint("range", "RANGE", ("a",), "kg", lower=3.0, upper=5.0, require_real_measurement=True),
            PhysicalConstraint(
                "mass-balance",
                "CONSERVATION",
                ("a", "b"),
                "kg",
                coefficients={"a": 1.0, "b": -1.0},
                target=0.0,
                tolerance=0.02,
                require_real_measurement=True,
            ),
        ],
    )
    assert report.all_constraints_verified is True
    assert report.all_calculations_passed is True
    assert report.hardware_authenticity_proven is False
    assert report.physical_truth_proven is False
    assert report.simulation_promoted_to_measurement is False
    assert len(report.report_sha256) == 64


def test_simulation_can_satisfy_math_but_not_real_measurement_requirement():
    report = audit_physical_reality(
        observations=[_obs("sim", "position", 0.5, kind="SIMULATION")],
        constraints=[PhysicalConstraint(
            "safe-range", "RANGE", ("sim",), "m",
            lower=0.0, upper=1.0, require_real_measurement=True,
        )],
    )
    audit = report.audits[0]
    assert audit.calculation_passed is True
    assert audit.evidence_sufficient is False
    assert audit.verified_constraint is False
    assert audit.blockers == ("real_measurement_missing",)
    assert report.all_constraints_verified is False


def test_linear_bounds_use_exact_named_observations():
    report = audit_physical_reality(
        observations=[_obs("x", "x", 2.0), _obs("y", "y", 3.0)],
        constraints=[PhysicalConstraint(
            "linear", "LINEAR_BOUNDS", ("x", "y"), "m",
            coefficients={"x": 2.0, "y": -1.0}, lower=0.9, upper=1.1,
        )],
    )
    assert report.audits[0].calculated_value == pytest.approx(1.0)
    assert report.audits[0].verified_constraint is True


def test_rate_limit_requires_same_variable_unit_and_increasing_time():
    report = audit_physical_reality(
        observations=[
            _obs("p0", "position", 0.0, time=10.0),
            _obs("p1", "position", 2.0, time=12.0),
        ],
        constraints=[PhysicalConstraint(
            "rate", "RATE_LIMIT", ("p0", "p1"), "m", max_abs_rate=1.1,
        )],
    )
    assert report.audits[0].calculated_value == pytest.approx(1.0)
    assert report.audits[0].calculation_passed is True

    with pytest.raises(ValueError, match="strictly increasing"):
        audit_physical_reality(
            observations=[
                _obs("a", "position", 0.0, time=10.0),
                _obs("b", "position", 1.0, time=10.0),
            ],
            constraints=[PhysicalConstraint("r", "RATE_LIMIT", ("a", "b"), "m", max_abs_rate=1.0)],
        )


def test_unknown_observation_unit_mismatch_duplicate_ids_and_nonfinite_fail_closed():
    with pytest.raises(ValueError, match="unknown observation_id"):
        audit_physical_reality(
            observations=[_obs("a", "x", 1.0)],
            constraints=[PhysicalConstraint("r", "RANGE", ("missing",), "m", lower=0, upper=2)],
        )
    with pytest.raises(ValueError, match="units must match"):
        audit_physical_reality(
            observations=[_obs("a", "x", 1.0, unit="m")],
            constraints=[PhysicalConstraint("r", "RANGE", ("a",), "kg", lower=0, upper=2)],
        )
    with pytest.raises(ValueError, match="must be unique"):
        audit_physical_reality(
            observations=[_obs("a", "x", 1.0), _obs("a", "x", 1.0)],
            constraints=[PhysicalConstraint("r", "RANGE", ("a",), "m", lower=0, upper=2)],
        )
    with pytest.raises(ValueError, match="must be finite"):
        audit_physical_reality(
            observations=[_obs("a", "x", float("nan"))],
            constraints=[PhysicalConstraint("r", "RANGE", ("a",), "m", lower=0, upper=2)],
        )
