import math

import pytest

from research_engine.mechanistic_reasoning import (
    MechanismEquation,
    MechanismModel,
    MechanismTerm,
    MechanismVariable,
    audit_mechanism,
    check_final_state_calibration,
    coefficient_sensitivity,
    compare_intervention,
    mechanism_model_from_mapping,
    simulate_mechanism,
)


def _model(*, falsifier="x should halve each step", coefficient=-1.0, x_max=10.0):
    return MechanismModel(
        model_id="m1",
        variables=(
            MechanismVariable("x", 2.0, -10.0, x_max, "1", "STATE", "sensor:x"),
            MechanismVariable("y", 0.0, -20.0, 20.0, "1", "STATE", "sensor:y"),
            MechanismVariable("u", 1.0, 0.0, 2.0, "1", "EXOGENOUS", "setting:u"),
        ),
        equations=(
            MechanismEquation(
                target="x",
                terms=(MechanismTerm("x", coefficient),),
                mechanism="x changes proportionally to x",
                observable="measure x at every step",
                falsifier=falsifier,
                evidence_refs=("source:1#span-a",),
            ),
            MechanismEquation(
                target="y",
                terms=(MechanismTerm("x", 1.0), MechanismTerm("u", 0.0)),
                mechanism="x drives y while u is an explicit exogenous input",
                observable="measure y at every step",
                falsifier="y increments differ from dt*x",
                evidence_refs=("source:2#span-b",),
            ),
        ),
        dt=0.5,
        steps=2,
    )


def test_complete_mechanism_requires_equations_observables_falsifiers_and_refs():
    audit = audit_mechanism(_model())
    assert audit.complete is True
    assert audit.state_variables == ("x", "y")
    assert audit.exogenous_variables == ("u",)
    assert audit.edge_count == 3
    assert audit.evidence_reference_count == 2
    assert audit.causal_mechanism_proven is False
    assert audit.empirical_validation_proven is False
    assert audit.truth_proven is False


def test_missing_falsifier_blocks_simulation_instead_of_pretending_mechanism_complete():
    model = _model(falsifier="")
    audit = audit_mechanism(model)
    assert audit.complete is False
    assert audit.incomplete_equations == ("x",)
    with pytest.raises(ValueError, match="contract is incomplete"):
        simulate_mechanism(model)


def test_missing_state_equation_is_explicit_blocker():
    model = _model()
    model = MechanismModel(
        model_id=model.model_id,
        variables=model.variables,
        equations=(model.equations[0],),
        dt=model.dt,
        steps=model.steps,
    )
    audit = audit_mechanism(model)
    assert audit.complete is False
    assert audit.missing_equations == ("y",)


def test_unknown_variable_and_duplicate_target_fail_closed():
    model = _model()
    bad_term = MechanismEquation(
        target="x",
        terms=(MechanismTerm("unknown", 1.0),),
        mechanism="m",
        observable="o",
        falsifier="f",
        evidence_refs=("r",),
    )
    with pytest.raises(ValueError, match="unknown variable"):
        audit_mechanism(MechanismModel(model.model_id, model.variables, (bad_term,), 0.5, 2))
    with pytest.raises(ValueError, match="duplicate structural equation"):
        audit_mechanism(MechanismModel(
            model.model_id, model.variables, (model.equations[0], model.equations[0]), 0.5, 2
        ))


def test_non_finite_numbers_are_rejected_before_execution():
    model = _model()
    bad = MechanismModel(model.model_id, model.variables, model.equations, float("nan"), 2)
    with pytest.raises(ValueError, match="finite number"):
        audit_mechanism(bad)


def test_closed_form_euler_trace_is_deterministic():
    first = simulate_mechanism(_model())
    second = simulate_mechanism(_model())
    assert first == second
    assert dict(first.final_state)["x"] == pytest.approx(0.5)
    assert dict(first.final_state)["y"] == pytest.approx(1.5)
    assert first.status == "SIMULATED_MODEL_CONSEQUENCE"
    assert first.model_consequence_only is True
    assert first.causal_mechanism_proven is False
    assert first.real_world_effect_proven is False
    assert first.truth_proven is False


def test_do_intervention_overrides_structural_equation_but_does_not_claim_observed_effect():
    report = simulate_mechanism(_model(), intervention={"x": 4.0})
    assert dict(report.final_state) == pytest.approx({"u": 1.0, "x": 4.0, "y": 4.0})
    comparison = compare_intervention(_model(), {"x": 4.0})
    assert dict(comparison.final_delta)["x"] == pytest.approx(3.5)
    assert dict(comparison.final_delta)["y"] == pytest.approx(2.5)
    assert comparison.counterfactual_is_model_prediction is True
    assert comparison.intervention_observed_in_reality is False
    assert comparison.causal_effect_proven is False


def test_out_of_bounds_intervention_and_dynamic_explosion_fail_closed():
    with pytest.raises(ValueError, match="outside declared bounds"):
        simulate_mechanism(_model(), intervention={"x": 99.0})
    explosive = _model(coefficient=10.0, x_max=3.0)
    with pytest.raises(ValueError, match="boundary violation"):
        simulate_mechanism(explosive)


def test_calibration_uses_observations_but_does_not_prove_mechanism():
    model = _model()
    report = simulate_mechanism(model)
    calibration = check_final_state_calibration(model, report, {"x": 0.5, "y": 1.5})
    assert calibration.normalized_rmse == pytest.approx(0.0)
    assert calibration.observations_supplied is True
    assert calibration.causal_mechanism_proven is False
    assert calibration.truth_proven is False


def test_calibration_rejects_report_from_different_model():
    report = simulate_mechanism(_model())
    changed = _model()
    changed = MechanismModel(changed.model_id, changed.variables, changed.equations, 0.25, 2)
    with pytest.raises(ValueError, match="does not belong"):
        check_final_state_calibration(changed, report, {"x": 0.5})


def test_coefficient_sensitivity_is_bounded_deterministic_and_truth_neutral():
    first = coefficient_sensitivity(_model(), fraction=0.05)
    second = coefficient_sensitivity(_model(), fraction=0.05)
    assert first == second
    assert first["rows"]
    assert len(first["sensitivity_hash"]) == 64
    assert first["model_consequence_only"] is True
    assert first["causal_mechanism_proven"] is False
    assert first["truth_proven"] is False
    with pytest.raises(ValueError, match="fraction"):
        coefficient_sensitivity(_model(), fraction=0.9)


def test_strict_mapping_schema_prevents_hidden_execution_fields():
    payload = {
        "model_id": "m1",
        "variables": [
            {"id": "x", "initial": 1.0, "min": 0.0, "max": 2.0,
             "unit": "1", "role": "STATE", "observable_ref": "sensor:x"}
        ],
        "equations": [
            {"target": "x", "terms": [{"variable": "x", "coefficient": -0.1,
                                         "transform": "identity"}],
             "bias": 0.0, "decay": 0.0, "mechanism": "decay", "observable": "x",
             "falsifier": "x fails to decay", "evidence_refs": ["source:1"]}
        ],
        "dt": 0.1,
        "steps": 2,
    }
    model = mechanism_model_from_mapping(payload)
    assert audit_mechanism(model).complete is True
    with pytest.raises(ValueError, match="schema is invalid"):
        mechanism_model_from_mapping({**payload, "python": "__import__('os')"})


def test_sigmoid_transform_remains_finite_for_extreme_bounded_state():
    model = MechanismModel(
        model_id="sigmoid",
        variables=(
            MechanismVariable("u", 1000.0, -2000.0, 2000.0, "1", "EXOGENOUS", "u"),
            MechanismVariable("x", 0.0, -10.0, 10.0, "1", "STATE", "x"),
        ),
        equations=(MechanismEquation(
            "x", (MechanismTerm("u", 1.0, "sigmoid"),),
            mechanism="bounded sigmoid drive", observable="x",
            falsifier="x does not change", evidence_refs=("benchmark",),
        ),),
        dt=1.0,
        steps=1,
    )
    report = simulate_mechanism(model)
    assert math.isfinite(dict(report.final_state)["x"])
