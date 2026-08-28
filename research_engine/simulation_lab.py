"""Deterministic digital-twin, FMEA/fault-injection and black-swan lab.

Software simulation is evidence about a model, not proof about the physical
world.  Twin reports therefore keep calibration error and the sim-to-reality
status explicit.  Physical capabilities still require separate hardware and
safety evidence before the maturity registry can call them verified.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Tuple


def _finite(value: float, field: str) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(output):
        raise ValueError(f"{field} must be finite")
    return output


def _canonical_hash(value: object) -> str:
    body = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DigitalTwinSpec:
    state_names: Tuple[str, ...]
    transition_matrix: Tuple[Tuple[float, ...], ...]
    bias: Tuple[float, ...]
    lower_bounds: Tuple[float, ...]
    upper_bounds: Tuple[float, ...]
    calibration_tolerance: float = 0.20

    def validate(self) -> None:
        size = len(self.state_names)
        if not size or len(set(self.state_names)) != size:
            raise ValueError("state_names must be non-empty and unique")
        if any(
            not name or not str(name).isidentifier() or str(name).startswith("_")
            for name in self.state_names
        ):
            raise ValueError("state_names must be safe identifiers")
        if (
            len(self.transition_matrix) != size
            or any(len(row) != size for row in self.transition_matrix)
        ):
            raise ValueError("transition_matrix must be square")
        if (
            len(self.bias) != size
            or len(self.lower_bounds) != size
            or len(self.upper_bounds) != size
        ):
            raise ValueError("bias/bounds must match state dimension")
        for row_index, row in enumerate(self.transition_matrix):
            for column_index, value in enumerate(row):
                _finite(value, f"A[{row_index},{column_index}]")
        for index, value in enumerate(self.bias):
            _finite(value, f"bias[{index}]")
        for index, (lower, upper) in enumerate(
            zip(self.lower_bounds, self.upper_bounds)
        ):
            lower = _finite(lower, f"lower_bounds[{index}]")
            upper = _finite(upper, f"upper_bounds[{index}]")
            if lower >= upper:
                raise ValueError("each lower bound must be below upper bound")
        tolerance = _finite(self.calibration_tolerance, "calibration_tolerance")
        if not 0 < tolerance <= 10:
            raise ValueError("calibration_tolerance must be in (0,10]")


@dataclass(frozen=True)
class TwinCalibrationReport:
    calibrated: bool
    normalized_rmse: float
    per_state_rmse: Mapping[str, float]
    one_step_predictions: int
    model_hash: str
    sim_to_reality_gap_open: bool


@dataclass(frozen=True)
class TwinSimulation:
    states: Tuple[Mapping[str, float], ...]
    bound_violations: Tuple[Tuple[int, str, float], ...]
    model_hash: str
    software_only: bool = True
    hardware_validated: bool = False


class DigitalTwin:
    """Bounded linear state-space twin with explicit calibration validation."""

    def __init__(self, spec: DigitalTwinSpec):
        spec.validate()
        self.spec = spec
        self.model_hash = _canonical_hash({
            "state_names": spec.state_names,
            "transition_matrix": spec.transition_matrix,
            "bias": spec.bias,
            "lower_bounds": spec.lower_bounds,
            "upper_bounds": spec.upper_bounds,
            "calibration_tolerance": spec.calibration_tolerance,
        })

    def _vector(
        self,
        state: Mapping[str, float] | Sequence[float],
    ) -> list[float]:
        if isinstance(state, Mapping):
            if set(state) != set(self.spec.state_names):
                raise ValueError("state mapping keys must exactly match state_names")
            return [
                _finite(state[name], f"state.{name}")
                for name in self.spec.state_names
            ]
        values = list(state)
        if len(values) != len(self.spec.state_names):
            raise ValueError("state vector has wrong dimension")
        return [_finite(value, "state") for value in values]

    def _mapping(self, values: Sequence[float]) -> Dict[str, float]:
        return {
            name: float(value)
            for name, value in zip(self.spec.state_names, values)
        }

    def predict_next(
        self,
        state: Mapping[str, float] | Sequence[float],
        intervention: Optional[Mapping[str, float]] = None,
    ) -> Dict[str, float]:
        vector = self._vector(state)
        additive = {name: 0.0 for name in self.spec.state_names}
        for name, value in dict(intervention or {}).items():
            if name not in additive:
                raise ValueError(f"unknown intervention variable: {name}")
            additive[name] = _finite(value, f"intervention.{name}")

        output = []
        for index, row in enumerate(self.spec.transition_matrix):
            value = (
                sum(float(coefficient) * item for coefficient, item in zip(row, vector))
                + float(self.spec.bias[index])
                + additive[self.spec.state_names[index]]
            )
            if not math.isfinite(value):
                raise ValueError("twin produced non-finite state")
            output.append(value)
        return self._mapping(output)

    def simulate(
        self,
        initial_state: Mapping[str, float] | Sequence[float],
        steps: int,
        interventions: Optional[Mapping[int, Mapping[str, float]]] = None,
    ) -> TwinSimulation:
        if not isinstance(steps, int) or not 1 <= steps <= 10_000:
            raise ValueError("steps must be an integer in 1..10000")
        schedule = dict(interventions or {})
        if any(
            not isinstance(step, int) or step < 1 or step > steps
            for step in schedule
        ):
            raise ValueError("intervention step outside simulation horizon")

        current = self._mapping(self._vector(initial_state))
        states = [current]
        violations = []
        for step in range(1, steps + 1):
            current = self.predict_next(current, schedule.get(step))
            states.append(current)
            for index, name in enumerate(self.spec.state_names):
                value = current[name]
                if (
                    value < self.spec.lower_bounds[index]
                    or value > self.spec.upper_bounds[index]
                ):
                    violations.append((step, name, value))
        return TwinSimulation(tuple(states), tuple(violations), self.model_hash)

    def validate_calibration(
        self,
        observed: Sequence[Mapping[str, float] | Sequence[float]],
    ) -> TwinCalibrationReport:
        if len(observed) < 3:
            raise ValueError("at least 3 observed states are required")
        vectors = [self._vector(item) for item in observed]
        size = len(self.spec.state_names)
        squared_errors: list[list[float]] = [[] for _ in range(size)]
        predictions = 0
        for left, right in zip(vectors, vectors[1:]):
            predicted = self._vector(self.predict_next(left))
            for index in range(size):
                squared_errors[index].append((predicted[index] - right[index]) ** 2)
            predictions += 1

        root_mean_square = [
            math.sqrt(sum(values) / len(values))
            for values in squared_errors
        ]
        spans = []
        for index in range(size):
            values = [row[index] for row in vectors]
            observed_span = max(values) - min(values)
            configured_span = (
                self.spec.upper_bounds[index] - self.spec.lower_bounds[index]
            )
            spans.append(max(observed_span, configured_span * 0.01, 1e-12))
        normalized_rmse = math.sqrt(
            sum(
                (rmse / span) ** 2
                for rmse, span in zip(root_mean_square, spans)
            ) / size
        )
        return TwinCalibrationReport(
            calibrated=normalized_rmse <= self.spec.calibration_tolerance,
            normalized_rmse=normalized_rmse,
            per_state_rmse={
                name: root_mean_square[index]
                for index, name in enumerate(self.spec.state_names)
            },
            one_step_predictions=predictions,
            model_hash=self.model_hash,
            # Simulation never closes this by itself.  A hardware/live validation
            # receipt has to close it elsewhere in the proof system.
            sim_to_reality_gap_open=True,
        )


@dataclass(frozen=True)
class FaultMode:
    name: str
    variable: str
    delta: float
    severity: int
    occurrence: int
    detectability: int
    duration_steps: int = 1

    @property
    def rpn(self) -> int:
        return self.severity * self.occurrence * self.detectability

    def validate(self) -> None:
        if not str(self.name).strip():
            raise ValueError("fault name required")
        _finite(self.delta, "fault delta")
        for field in ("severity", "occurrence", "detectability"):
            value = getattr(self, field)
            if not isinstance(value, int) or not 1 <= value <= 10:
                raise ValueError(f"{field} must be 1..10")
        if not isinstance(self.duration_steps, int) or not 1 <= self.duration_steps <= 1_000:
            raise ValueError("duration_steps must be 1..1000")


@dataclass(frozen=True)
class FaultImpact:
    name: str
    rpn: int
    peak_normalized_deviation: float
    bound_violations: int
    recovery_steps: Optional[int]
    recovered: bool


@dataclass(frozen=True)
class FaultCampaign:
    ranked_fmea: Tuple[FaultImpact, ...]
    baseline_hash: str
    injection_step: int
    software_only: bool = True
    safety_review_required: bool = True


def run_fault_campaign(
    twin: DigitalTwin,
    initial_state: Mapping[str, float] | Sequence[float],
    faults: Sequence[FaultMode],
    *,
    steps: int = 20,
    injection_step: int = 3,
    recovery_tolerance: float = 0.05,
) -> FaultCampaign:
    """Rank FMEA risks and run each fault against the same frozen baseline."""
    if not faults:
        raise ValueError("at least one fault mode required")
    if not 1 <= injection_step <= steps:
        raise ValueError("injection_step outside horizon")
    if not 0 < recovery_tolerance <= 1:
        raise ValueError("recovery_tolerance must be in (0,1]")

    baseline = twin.simulate(initial_state, steps)
    impacts = []
    for fault in faults:
        fault.validate()
        if fault.variable not in twin.spec.state_names:
            raise ValueError(f"unknown fault variable: {fault.variable}")
        schedule: Dict[int, Mapping[str, float]] = {}
        final_fault_step = min(
            steps,
            injection_step + fault.duration_steps - 1,
        )
        for step in range(injection_step, final_fault_step + 1):
            schedule[step] = {fault.variable: fault.delta}
        stressed = twin.simulate(initial_state, steps, schedule)

        peak_deviation = 0.0
        for index, (normal_state, fault_state) in enumerate(
            zip(baseline.states, stressed.states)
        ):
            if index < injection_step:
                continue
            for state_index, name in enumerate(twin.spec.state_names):
                scale = max(
                    twin.spec.upper_bounds[state_index]
                    - twin.spec.lower_bounds[state_index],
                    1e-12,
                )
                peak_deviation = max(
                    peak_deviation,
                    abs(float(fault_state[name]) - float(normal_state[name])) / scale,
                )

        recovery_steps: Optional[int] = None
        for index in range(final_fault_step + 1, len(stressed.states)):
            max_deviation = 0.0
            for state_index, name in enumerate(twin.spec.state_names):
                scale = max(
                    twin.spec.upper_bounds[state_index]
                    - twin.spec.lower_bounds[state_index],
                    1e-12,
                )
                max_deviation = max(
                    max_deviation,
                    abs(stressed.states[index][name] - baseline.states[index][name])
                    / scale,
                )
            if max_deviation <= recovery_tolerance:
                recovery_steps = index - final_fault_step
                break

        impacts.append(FaultImpact(
            name=fault.name,
            rpn=fault.rpn,
            peak_normalized_deviation=peak_deviation,
            bound_violations=len(stressed.bound_violations),
            recovery_steps=recovery_steps,
            recovered=recovery_steps is not None,
        ))

    impacts.sort(
        key=lambda item: (
            -item.rpn,
            -item.bound_violations,
            -item.peak_normalized_deviation,
            item.name,
        )
    )
    return FaultCampaign(
        ranked_fmea=tuple(impacts),
        baseline_hash=_canonical_hash([dict(row) for row in baseline.states]),
        injection_step=injection_step,
    )


@dataclass(frozen=True)
class AgentSpec:
    name: str
    response: float
    inertia: float
    coupling: float
    noise_scale: float = 0.0

    def validate(self) -> None:
        if not str(self.name).strip():
            raise ValueError("agent name required")
        if not 0 <= _finite(self.inertia, "inertia") <= 1:
            raise ValueError("inertia must be 0..1")
        if not -10 <= _finite(self.response, "response") <= 10:
            raise ValueError("response out of bounds")
        if not -10 <= _finite(self.coupling, "coupling") <= 10:
            raise ValueError("coupling out of bounds")
        if not 0 <= _finite(self.noise_scale, "noise_scale") <= 100:
            raise ValueError("noise_scale out of bounds")


@dataclass(frozen=True)
class AgentSimulation:
    aggregate: Tuple[float, ...]
    per_agent: Mapping[str, Tuple[float, ...]]
    seed: int
    simulation_hash: str
    synthetic_only: bool = True


def run_agent_environment(
    agents: Sequence[AgentSpec],
    initial: Mapping[str, float],
    *,
    external_signal: Sequence[float],
    shocks: Optional[Mapping[int, float]] = None,
    seed: int = 20_260_828,
) -> AgentSimulation:
    """Seeded agent-based synthetic environment with explicit shock schedule."""
    if not agents:
        raise ValueError("at least one agent required")
    if len({agent.name for agent in agents}) != len(agents):
        raise ValueError("agent names must be unique")
    for agent in agents:
        agent.validate()
    if set(initial) != {agent.name for agent in agents}:
        raise ValueError("initial state must contain every agent exactly once")

    signals = [_finite(value, "external_signal") for value in external_signal]
    if not signals or len(signals) > 10_000:
        raise ValueError("external_signal length must be 1..10000")
    shock_map = {
        int(step): _finite(value, "shock")
        for step, value in dict(shocks or {}).items()
    }
    if any(step < 0 or step >= len(signals) for step in shock_map):
        raise ValueError("shock step outside horizon")

    random_source = random.Random(int(seed))
    current = {
        name: _finite(value, f"initial.{name}")
        for name, value in initial.items()
    }
    traces = {name: [current[name]] for name in current}
    aggregate = [statistics.fmean(current.values())]

    for step, signal in enumerate(signals):
        population_mean = statistics.fmean(current.values())
        shock = shock_map.get(step, 0.0)
        next_state: Dict[str, float] = {}
        for agent in agents:
            previous = current[agent.name]
            noise = (
                random_source.gauss(0.0, agent.noise_scale)
                if agent.noise_scale
                else 0.0
            )
            value = (
                agent.inertia * previous
                + (1 - agent.inertia)
                * (previous + agent.response * (signal - previous))
                + agent.coupling * (population_mean - previous)
                + shock
                + noise
            )
            if not math.isfinite(value):
                raise ValueError("agent simulation produced non-finite value")
            next_state[agent.name] = value
            traces[agent.name].append(value)
        current = next_state
        aggregate.append(statistics.fmean(current.values()))

    payload = {
        "aggregate": aggregate,
        "per_agent": traces,
        "seed": int(seed),
    }
    return AgentSimulation(
        aggregate=tuple(aggregate),
        per_agent={name: tuple(values) for name, values in traces.items()},
        seed=int(seed),
        simulation_hash=_canonical_hash(payload),
    )


@dataclass(frozen=True)
class StressSeries:
    name: str
    values: Tuple[float, ...]
    max_abs_step: float
    max_drawdown_abs: float
    finite: bool


@dataclass(frozen=True)
class BlackSwanReport:
    baseline: StressSeries
    scenarios: Tuple[StressSeries, ...]
    seed: int
    scenario_hash: str
    synthetic_only: bool = True
    future_guarantee: bool = False


def _stress_metrics(name: str, values: Sequence[float]) -> StressSeries:
    data = [float(value) for value in values]
    finite = all(math.isfinite(value) for value in data)
    max_step = (
        max((abs(right - left) for left, right in zip(data, data[1:])), default=0.0)
        if finite
        else math.inf
    )
    peak = data[0] if data and finite else 0.0
    drawdown = 0.0
    if finite:
        for value in data:
            peak = max(peak, value)
            drawdown = max(drawdown, peak - value)
    else:
        drawdown = math.inf
    return StressSeries(name, tuple(data), max_step, drawdown, finite)


def black_swan_suite(
    baseline: Sequence[float],
    *,
    seed: int = 20_260_828,
) -> BlackSwanReport:
    """Create deterministic tail, volatility, regime and liquidity stresses.

    This is a falsification/stress lane.  Passing these synthetic scenarios is
    not a promise about unseen real black swans.
    """
    values = [_finite(value, "baseline") for value in baseline]
    if len(values) < 8 or len(values) > 10_000:
        raise ValueError("baseline must contain 8..10000 finite values")
    differences = [right - left for left, right in zip(values, values[1:])]
    absolute_difference_median = statistics.median(abs(item) for item in differences)
    dispersion = statistics.pstdev(differences) if len(differences) > 1 else 0.0
    scale = max(
        absolute_difference_median,
        dispersion,
        max(abs(item) for item in differences) * 0.05,
        1e-6,
    )
    random_source = random.Random(int(seed))
    size = len(values)
    scenarios = []

    # Persistent tail gap: large surprise then a new lower level.
    crash = list(values)
    crash_index = max(2, size // 3)
    shock = (8.0 + random_source.random() * 2.0) * scale
    for index in range(crash_index, size):
        crash[index] -= shock
    scenarios.append(_stress_metrics("tail_crash", crash))

    # Volatility clustering: same signs, much larger local increments.
    cluster = [values[0]]
    start = max(1, size // 3)
    end = min(size - 1, start + max(3, size // 4))
    for index, difference in enumerate(differences, start=1):
        multiplier = 4.0 if start <= index <= end else 1.0
        cluster.append(cluster[-1] + difference * multiplier)
    scenarios.append(_stress_metrics("volatility_cluster", cluster))

    # Structural break: the learned direction becomes the wrong direction.
    reversal = [values[0]]
    pivot = size // 2
    for index, difference in enumerate(differences, start=1):
        reversal.append(
            reversal[-1] + (-difference if index >= pivot else difference)
        )
    scenarios.append(_stress_metrics("regime_reversal", reversal))

    # Flat/no-update interval followed by a catch-up gap.
    freeze = list(values)
    start = max(2, size // 2 - 1)
    stop = min(size - 1, start + 3)
    anchor = freeze[start - 1]
    for index in range(start, stop):
        freeze[index] = anchor
    if stop < size:
        freeze[stop] = anchor + (values[stop] - values[start - 1]) * 2.5
    scenarios.append(_stress_metrics("liquidity_freeze_gap", freeze))

    payload = {scenario.name: list(scenario.values) for scenario in scenarios}
    return BlackSwanReport(
        baseline=_stress_metrics("baseline", values),
        scenarios=tuple(scenarios),
        seed=int(seed),
        scenario_hash=_canonical_hash(payload),
    )
