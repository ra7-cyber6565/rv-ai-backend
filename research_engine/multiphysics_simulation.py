"""Bounded deterministic coupled thermal/mechanical/electrical simulation.

This is a software simulation foundation for capability #26.  It intentionally
makes no hardware-validity claim: every result is labelled ``software_only`` and
``hardware_validated=False``.  A real-world maturity proof still requires
separate hardware, safety and sim-to-reality evidence.

The solver integrates a small but genuinely coupled ODE system with classical
RK4, explicit resource budgets, finite-value checks, convergence diagnostics,
and deterministic hashes.  It is suitable for falsifiable computational
experiments and regression tests; it is not a general CFD/FEA replacement.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple


_MAX_STEPS = 200_000
_MAX_SWEEP_CASES = 1_000
_MAX_ABS_STATE_DEFAULT = 1e9


def _finite(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _positive(value: object, field: str) -> float:
    number = _finite(value, field)
    if number <= 0:
        raise ValueError(f"{field} must be > 0")
    return number


def _nonnegative(value: object, field: str) -> float:
    number = _finite(value, field)
    if number < 0:
        raise ValueError(f"{field} must be >= 0")
    return number


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CoupledPhysicsModel:
    """Lumped coupled thermal/mechanical/electrical model parameters."""

    thermal_capacity: float = 10.0
    thermal_loss: float = 0.5
    thermal_input_gain: float = 1.0
    joule_heating_gain: float = 1.0

    mass: float = 1.0
    damping: float = 0.2
    stiffness: float = 2.0
    force_input_gain: float = 1.0
    thermal_expansion_gain: float = 0.02
    electromechanical_force_gain: float = 0.5

    inductance: float = 1.0
    resistance: float = 1.0
    voltage_input_gain: float = 1.0
    back_emf_gain: float = 0.2

    def validated(self) -> "CoupledPhysicsModel":
        _positive(self.thermal_capacity, "thermal_capacity")
        _nonnegative(self.thermal_loss, "thermal_loss")
        _finite(self.thermal_input_gain, "thermal_input_gain")
        _nonnegative(self.joule_heating_gain, "joule_heating_gain")
        _positive(self.mass, "mass")
        _nonnegative(self.damping, "damping")
        _nonnegative(self.stiffness, "stiffness")
        _finite(self.force_input_gain, "force_input_gain")
        _finite(self.thermal_expansion_gain, "thermal_expansion_gain")
        _finite(self.electromechanical_force_gain, "electromechanical_force_gain")
        _positive(self.inductance, "inductance")
        _nonnegative(self.resistance, "resistance")
        _finite(self.voltage_input_gain, "voltage_input_gain")
        _finite(self.back_emf_gain, "back_emf_gain")
        return self

    def as_dict(self) -> Dict[str, float]:
        self.validated()
        return {name: float(getattr(self, name)) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class PhysicsState:
    temperature: float = 20.0
    position: float = 0.0
    velocity: float = 0.0
    current: float = 0.0

    def validated(self) -> "PhysicsState":
        for name in self.__dataclass_fields__:
            _finite(getattr(self, name), f"state.{name}")
        return self

    def vector(self) -> Tuple[float, float, float, float]:
        self.validated()
        return (
            float(self.temperature),
            float(self.position),
            float(self.velocity),
            float(self.current),
        )


@dataclass(frozen=True)
class PhysicsInputs:
    ambient_temperature: float = 20.0
    heat_input: float = 0.0
    force_input: float = 0.0
    voltage_input: float = 0.0

    def validated(self) -> "PhysicsInputs":
        for name in self.__dataclass_fields__:
            _finite(getattr(self, name), f"inputs.{name}")
        return self

    def as_dict(self) -> Dict[str, float]:
        self.validated()
        return {name: float(getattr(self, name)) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class SimulationBudget:
    max_steps: int = 50_000
    max_abs_state: float = _MAX_ABS_STATE_DEFAULT

    def validated(self) -> "SimulationBudget":
        if type(self.max_steps) is not int or not 1 <= self.max_steps <= _MAX_STEPS:
            raise ValueError(f"max_steps must be an integer in [1,{_MAX_STEPS}]")
        _positive(self.max_abs_state, "max_abs_state")
        return self


@dataclass(frozen=True)
class SimulationPoint:
    time: float
    state: PhysicsState


@dataclass(frozen=True)
class MultiPhysicsResult:
    model_hash: str
    input_hash: str
    trajectory_hash: str
    integration_method: str
    dt: float
    duration: float
    steps: int
    points: Tuple[SimulationPoint, ...]
    peak_abs_state: Mapping[str, float]
    coupling_active: bool
    software_only: bool = True
    hardware_validated: bool = False
    truth_proven: bool = False

    @property
    def final_state(self) -> PhysicsState:
        return self.points[-1].state


@dataclass(frozen=True)
class ConvergenceReport:
    coarse_hash: str
    fine_hash: str
    normalized_terminal_error: float
    tolerance: float
    converged: bool
    software_only: bool = True
    hardware_validated: bool = False
    truth_proven: bool = False


def _coupling_active(model: CoupledPhysicsModel) -> bool:
    return any(
        abs(value) > 0.0
        for value in (
            model.joule_heating_gain,
            model.thermal_expansion_gain,
            model.electromechanical_force_gain,
            model.back_emf_gain,
        )
    )


def _derivative(
    model: CoupledPhysicsModel,
    inputs: PhysicsInputs,
    vector: Sequence[float],
) -> Tuple[float, float, float, float]:
    temperature, position, velocity, current = map(float, vector)
    ambient = float(inputs.ambient_temperature)

    electrical_heat = (
        model.joule_heating_gain * model.resistance * current * current
    )
    d_temperature = (
        model.thermal_input_gain * inputs.heat_input
        + electrical_heat
        - model.thermal_loss * (temperature - ambient)
    ) / model.thermal_capacity

    d_position = velocity
    mechanical_force = (
        model.force_input_gain * inputs.force_input
        + model.electromechanical_force_gain * current
        + model.thermal_expansion_gain * (temperature - ambient)
        - model.damping * velocity
        - model.stiffness * position
    )
    d_velocity = mechanical_force / model.mass

    d_current = (
        model.voltage_input_gain * inputs.voltage_input
        - model.resistance * current
        - model.back_emf_gain * velocity
    ) / model.inductance

    derivative = (d_temperature, d_position, d_velocity, d_current)
    if not all(math.isfinite(value) for value in derivative):
        raise ValueError("multi-physics derivative became non-finite")
    return derivative


def _add_scaled(
    vector: Sequence[float],
    derivative: Sequence[float],
    scale: float,
) -> Tuple[float, ...]:
    return tuple(float(value) + scale * float(delta) for value, delta in zip(vector, derivative))


def _rk4_step(
    model: CoupledPhysicsModel,
    inputs: PhysicsInputs,
    vector: Sequence[float],
    dt: float,
) -> Tuple[float, float, float, float]:
    k1 = _derivative(model, inputs, vector)
    k2 = _derivative(model, inputs, _add_scaled(vector, k1, dt / 2.0))
    k3 = _derivative(model, inputs, _add_scaled(vector, k2, dt / 2.0))
    k4 = _derivative(model, inputs, _add_scaled(vector, k3, dt))
    out = tuple(
        float(value) + (dt / 6.0) * (a + 2.0 * b + 2.0 * c + d)
        for value, a, b, c, d in zip(vector, k1, k2, k3, k4)
    )
    if not all(math.isfinite(value) for value in out):
        raise ValueError("multi-physics state became non-finite")
    return out  # type: ignore[return-value]


def _state_from_vector(vector: Sequence[float]) -> PhysicsState:
    return PhysicsState(
        temperature=float(vector[0]),
        position=float(vector[1]),
        velocity=float(vector[2]),
        current=float(vector[3]),
    )


def simulate_coupled(
    model: CoupledPhysicsModel,
    initial_state: PhysicsState,
    inputs: PhysicsInputs,
    *,
    duration: float,
    dt: float,
    budget: SimulationBudget = SimulationBudget(),
    retain_every: int = 1,
) -> MultiPhysicsResult:
    """Run one bounded deterministic RK4 simulation."""
    model.validated()
    initial_state.validated()
    inputs.validated()
    budget.validated()
    duration_value = _positive(duration, "duration")
    dt_value = _positive(dt, "dt")
    if dt_value > duration_value:
        raise ValueError("dt must be <= duration")
    if type(retain_every) is not int or retain_every < 1:
        raise ValueError("retain_every must be an integer >= 1")

    raw_steps = duration_value / dt_value
    steps = int(round(raw_steps))
    if steps < 1 or abs(steps * dt_value - duration_value) > max(1e-12, duration_value * 1e-10):
        raise ValueError("duration must be an integer multiple of dt")
    if steps > budget.max_steps:
        raise ValueError("simulation exceeds max_steps budget")

    vector = initial_state.vector()
    points = [SimulationPoint(time=0.0, state=initial_state)]
    peak = {
        "temperature": abs(vector[0]),
        "position": abs(vector[1]),
        "velocity": abs(vector[2]),
        "current": abs(vector[3]),
    }
    names = tuple(peak)

    for step in range(1, steps + 1):
        vector = _rk4_step(model, inputs, vector, dt_value)
        for index, name in enumerate(names):
            absolute = abs(vector[index])
            peak[name] = max(peak[name], absolute)
            if absolute > budget.max_abs_state:
                raise ValueError(f"multi-physics state exceeded max_abs_state at {name}")
        if step % retain_every == 0 or step == steps:
            points.append(
                SimulationPoint(
                    time=round(step * dt_value, 15),
                    state=_state_from_vector(vector),
                )
            )

    model_payload = model.as_dict()
    input_payload = {
        "initial_state": initial_state.vector(),
        "inputs": inputs.as_dict(),
        "duration": duration_value,
        "dt": dt_value,
        "retain_every": retain_every,
        "budget": {
            "max_steps": budget.max_steps,
            "max_abs_state": float(budget.max_abs_state),
        },
    }
    trajectory_payload = [
        {
            "time": point.time,
            "state": point.state.vector(),
        }
        for point in points
    ]
    return MultiPhysicsResult(
        model_hash=_hash(model_payload),
        input_hash=_hash(input_payload),
        trajectory_hash=_hash(trajectory_payload),
        integration_method="RK4_FIXED_STEP",
        dt=dt_value,
        duration=duration_value,
        steps=steps,
        points=tuple(points),
        peak_abs_state={name: round(value, 15) for name, value in peak.items()},
        coupling_active=_coupling_active(model),
    )


def convergence_check(
    model: CoupledPhysicsModel,
    initial_state: PhysicsState,
    inputs: PhysicsInputs,
    *,
    duration: float,
    coarse_dt: float,
    tolerance: float = 1e-4,
    budget: SimulationBudget = SimulationBudget(),
) -> ConvergenceReport:
    """Compare dt against dt/2; convergence is numerical, not physical truth."""
    tolerance_value = _nonnegative(tolerance, "tolerance")
    coarse = simulate_coupled(
        model,
        initial_state,
        inputs,
        duration=duration,
        dt=coarse_dt,
        budget=budget,
        retain_every=max(1, int(round(float(duration) / float(coarse_dt)))),
    )
    fine_dt = float(coarse_dt) / 2.0
    fine = simulate_coupled(
        model,
        initial_state,
        inputs,
        duration=duration,
        dt=fine_dt,
        budget=budget,
        retain_every=max(1, int(round(float(duration) / fine_dt))),
    )
    coarse_vector = coarse.final_state.vector()
    fine_vector = fine.final_state.vector()
    errors = []
    for coarse_value, fine_value in zip(coarse_vector, fine_vector):
        scale = max(1.0, abs(fine_value))
        errors.append(abs(coarse_value - fine_value) / scale)
    normalized = max(errors)
    return ConvergenceReport(
        coarse_hash=coarse.trajectory_hash,
        fine_hash=fine.trajectory_hash,
        normalized_terminal_error=normalized,
        tolerance=tolerance_value,
        converged=normalized <= tolerance_value,
    )


def parameter_sweep(
    models: Sequence[CoupledPhysicsModel],
    initial_state: PhysicsState,
    inputs: PhysicsInputs,
    *,
    duration: float,
    dt: float,
    budget: SimulationBudget = SimulationBudget(),
) -> Tuple[MultiPhysicsResult, ...]:
    if isinstance(models, (str, bytes, bytearray)) or not isinstance(models, Sequence):
        raise ValueError("models must be a finite sequence")
    if not 1 <= len(models) <= _MAX_SWEEP_CASES:
        raise ValueError(f"models must contain 1..{_MAX_SWEEP_CASES} cases")
    results = [
        simulate_coupled(
            model,
            initial_state,
            inputs,
            duration=duration,
            dt=dt,
            budget=budget,
            retain_every=max(1, int(round(float(duration) / float(dt)))),
        )
        for model in models
    ]
    return tuple(sorted(results, key=lambda item: (item.model_hash, item.trajectory_hash)))
