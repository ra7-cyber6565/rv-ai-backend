import math

import pytest

from research_engine.multiphysics_simulation import (
    CoupledPhysicsModel,
    PhysicsInputs,
    PhysicsState,
    SimulationBudget,
    convergence_check,
    parameter_sweep,
    simulate_coupled,
)


def test_deterministic_coupled_run_and_honest_metadata():
    model = CoupledPhysicsModel()
    state = PhysicsState()
    inputs = PhysicsInputs(voltage_input=2.0, heat_input=1.0, force_input=0.5)

    first = simulate_coupled(model, state, inputs, duration=2.0, dt=0.01)
    second = simulate_coupled(model, state, inputs, duration=2.0, dt=0.01)

    assert first.trajectory_hash == second.trajectory_hash
    assert first.model_hash == second.model_hash
    assert first.input_hash == second.input_hash
    assert first.final_state.vector() == pytest.approx(second.final_state.vector())
    assert first.integration_method == "RK4_FIXED_STEP"
    assert first.steps == 200
    assert first.coupling_active is True
    assert first.software_only is True
    assert first.hardware_validated is False
    assert first.truth_proven is False


def test_zero_coupling_electrical_drive_does_not_heat_or_move_mechanics():
    model = CoupledPhysicsModel(
        joule_heating_gain=0.0,
        thermal_expansion_gain=0.0,
        electromechanical_force_gain=0.0,
        back_emf_gain=0.0,
    )
    result = simulate_coupled(
        model,
        PhysicsState(),
        PhysicsInputs(voltage_input=2.0),
        duration=1.0,
        dt=0.01,
    )
    assert result.coupling_active is False
    assert result.final_state.current > 0.0
    assert result.final_state.temperature == pytest.approx(20.0, abs=1e-12)
    assert result.final_state.position == pytest.approx(0.0, abs=1e-12)
    assert result.final_state.velocity == pytest.approx(0.0, abs=1e-12)


def test_electrical_drive_propagates_through_declared_couplings():
    result = simulate_coupled(
        CoupledPhysicsModel(),
        PhysicsState(),
        PhysicsInputs(voltage_input=3.0),
        duration=2.0,
        dt=0.01,
    )
    assert result.final_state.current > 0.0
    assert result.final_state.temperature > 20.0
    assert abs(result.final_state.position) > 1e-6
    assert abs(result.final_state.velocity) > 1e-6


def test_convergence_check_is_numerical_evidence_not_physical_truth():
    report = convergence_check(
        CoupledPhysicsModel(),
        PhysicsState(),
        PhysicsInputs(voltage_input=1.5, heat_input=0.4),
        duration=1.0,
        coarse_dt=0.02,
        tolerance=1e-3,
    )
    assert math.isfinite(report.normalized_terminal_error)
    assert report.normalized_terminal_error >= 0.0
    assert report.converged is True
    assert report.software_only is True
    assert report.hardware_validated is False
    assert report.truth_proven is False
    assert len(report.coarse_hash) == 64
    assert len(report.fine_hash) == 64


def test_invalid_model_state_and_input_fail_closed():
    with pytest.raises(ValueError, match="thermal_capacity"):
        CoupledPhysicsModel(thermal_capacity=0.0).validated()
    with pytest.raises(ValueError, match="mass must be finite"):
        CoupledPhysicsModel(mass=float("nan")).validated()
    with pytest.raises(ValueError, match="resistance"):
        CoupledPhysicsModel(resistance=-1.0).validated()
    with pytest.raises(ValueError, match="state.temperature must be finite"):
        PhysicsState(temperature=float("nan")).validated()
    with pytest.raises(ValueError, match="inputs.voltage_input must be finite"):
        PhysicsInputs(voltage_input=float("inf")).validated()


def test_time_grid_and_resource_budgets_fail_closed():
    model = CoupledPhysicsModel()
    state = PhysicsState()
    inputs = PhysicsInputs(voltage_input=1.0)
    with pytest.raises(ValueError, match="dt must be <= duration"):
        simulate_coupled(model, state, inputs, duration=1.0, dt=2.0)
    with pytest.raises(ValueError, match="integer multiple"):
        simulate_coupled(model, state, inputs, duration=1.0, dt=0.3)
    with pytest.raises(ValueError, match="max_steps"):
        simulate_coupled(
            model,
            state,
            inputs,
            duration=1.0,
            dt=0.01,
            budget=SimulationBudget(max_steps=50),
        )
    with pytest.raises(ValueError, match="max_abs_state"):
        simulate_coupled(
            model,
            state,
            PhysicsInputs(voltage_input=100.0),
            duration=1.0,
            dt=0.01,
            budget=SimulationBudget(max_abs_state=0.5),
        )


def test_parameter_sweep_is_bounded_and_deterministic():
    models = (
        CoupledPhysicsModel(resistance=1.0),
        CoupledPhysicsModel(resistance=2.0),
        CoupledPhysicsModel(resistance=0.5),
    )
    first = parameter_sweep(
        models,
        PhysicsState(),
        PhysicsInputs(voltage_input=2.0),
        duration=1.0,
        dt=0.02,
    )
    second = parameter_sweep(
        tuple(reversed(models)),
        PhysicsState(),
        PhysicsInputs(voltage_input=2.0),
        duration=1.0,
        dt=0.02,
    )
    assert [item.model_hash for item in first] == [item.model_hash for item in second]
    assert [item.trajectory_hash for item in first] == [item.trajectory_hash for item in second]
    assert len(first) == 3
    assert all(item.hardware_validated is False for item in first)

    with pytest.raises(ValueError, match="1..1000"):
        parameter_sweep(
            (),
            PhysicsState(),
            PhysicsInputs(),
            duration=1.0,
            dt=0.1,
        )
