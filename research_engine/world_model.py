"""Bounded state-action-observation world model for capability #68.

The model represents explicit latent state dynamics, controllable actions and an
observation model.  It supports deterministic rollouts, counterfactual action
plans and calibration against observed state/observation sequences.  A good fit
is evidence about this model only; it never closes the sim-to-reality gap by
itself.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Mapping, Sequence, Tuple

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
_MAX_DIM = 128
_MAX_STEPS = 10_000


def _finite(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _names(values: Sequence[str], field: str, *, allow_empty: bool = False) -> Tuple[str, ...]:
    names = tuple(str(value or "").strip() for value in values)
    if not names and not allow_empty:
        raise ValueError(f"{field} must not be empty")
    if len(names) > _MAX_DIM or len(set(names)) != len(names):
        raise ValueError(f"{field} must be unique and bounded")
    if any(not _NAME.fullmatch(name) for name in names):
        raise ValueError(f"{field} contains invalid identifier")
    return names


@dataclass(frozen=True)
class WorldModelSpec:
    state_names: Tuple[str, ...]
    action_names: Tuple[str, ...]
    observation_names: Tuple[str, ...]
    transition_matrix: Tuple[Tuple[float, ...], ...]
    action_matrix: Tuple[Tuple[float, ...], ...]
    transition_bias: Tuple[float, ...]
    observation_matrix: Tuple[Tuple[float, ...], ...]
    observation_bias: Tuple[float, ...]
    lower_bounds: Tuple[float, ...]
    upper_bounds: Tuple[float, ...]
    calibration_tolerance: float = 0.20

    def normalized(self) -> "WorldModelSpec":
        states = _names(self.state_names, "state_names")
        actions = _names(self.action_names, "action_names", allow_empty=True)
        observations = _names(self.observation_names, "observation_names")
        if set(states) & set(actions) or set(states) & set(observations) or set(actions) & set(observations):
            raise ValueError("state/action/observation names must be disjoint")
        n, m, p = len(states), len(actions), len(observations)
        if len(self.transition_matrix) != n or any(len(row) != n for row in self.transition_matrix):
            raise ValueError("transition_matrix must be state x state")
        if len(self.action_matrix) != n or any(len(row) != m for row in self.action_matrix):
            raise ValueError("action_matrix must be state x action")
        if len(self.transition_bias) != n:
            raise ValueError("transition_bias must match state dimension")
        if len(self.observation_matrix) != p or any(len(row) != n for row in self.observation_matrix):
            raise ValueError("observation_matrix must be observation x state")
        if len(self.observation_bias) != p:
            raise ValueError("observation_bias must match observation dimension")
        if len(self.lower_bounds) != n or len(self.upper_bounds) != n:
            raise ValueError("bounds must match state dimension")

        transition = tuple(tuple(_finite(v, "transition_matrix") for v in row) for row in self.transition_matrix)
        action = tuple(tuple(_finite(v, "action_matrix") for v in row) for row in self.action_matrix)
        transition_bias = tuple(_finite(v, "transition_bias") for v in self.transition_bias)
        observation = tuple(tuple(_finite(v, "observation_matrix") for v in row) for row in self.observation_matrix)
        observation_bias = tuple(_finite(v, "observation_bias") for v in self.observation_bias)
        lower = tuple(_finite(v, "lower_bounds") for v in self.lower_bounds)
        upper = tuple(_finite(v, "upper_bounds") for v in self.upper_bounds)
        if any(lo >= hi for lo, hi in zip(lower, upper)):
            raise ValueError("each lower bound must be below upper bound")
        tolerance = _finite(self.calibration_tolerance, "calibration_tolerance")
        if not 0 < tolerance <= 10:
            raise ValueError("calibration_tolerance must be in (0,10]")
        return WorldModelSpec(
            states, actions, observations, transition, action, transition_bias,
            observation, observation_bias, lower, upper, tolerance,
        )


@dataclass(frozen=True)
class WorldStep:
    state: Mapping[str, float]
    observation: Mapping[str, float]
    ood_state_variables: Tuple[str, ...]


@dataclass(frozen=True)
class WorldRollout:
    steps: Tuple[WorldStep, ...]
    model_sha256: str
    software_only: bool = True
    world_model_is_reality: bool = False
    sim_to_reality_gap_open: bool = True


@dataclass(frozen=True)
class CounterfactualReport:
    baseline: WorldRollout
    intervention: WorldRollout
    final_state_delta: Mapping[str, float]
    max_normalized_state_divergence: float
    causal_effect_proven: bool = False
    world_model_is_reality: bool = False


@dataclass(frozen=True)
class WorldModelCalibration:
    state_normalized_rmse: float
    observation_normalized_rmse: float
    calibrated: bool
    one_step_predictions: int
    ood_observed_states: int
    model_sha256: str
    sim_to_reality_gap_open: bool = True
    truth_proven: bool = False


class WorldModel:
    def __init__(self, spec: WorldModelSpec):
        self.spec = spec.normalized()
        self.model_sha256 = _hash({
            "state_names": self.spec.state_names,
            "action_names": self.spec.action_names,
            "observation_names": self.spec.observation_names,
            "transition_matrix": self.spec.transition_matrix,
            "action_matrix": self.spec.action_matrix,
            "transition_bias": self.spec.transition_bias,
            "observation_matrix": self.spec.observation_matrix,
            "observation_bias": self.spec.observation_bias,
            "lower_bounds": self.spec.lower_bounds,
            "upper_bounds": self.spec.upper_bounds,
            "calibration_tolerance": self.spec.calibration_tolerance,
        })

    def _vector(self, values: Mapping[str, float], names: Tuple[str, ...], field: str) -> Tuple[float, ...]:
        if not isinstance(values, Mapping) or set(values) != set(names):
            raise ValueError(f"{field} keys must exactly match declared names")
        return tuple(_finite(values[name], f"{field}.{name}") for name in names)

    @staticmethod
    def _mapping(names: Tuple[str, ...], values: Sequence[float]) -> Mapping[str, float]:
        return {name: float(value) for name, value in zip(names, values)}

    def _ood(self, state: Sequence[float]) -> Tuple[str, ...]:
        return tuple(
            name for name, value, lo, hi in zip(
                self.spec.state_names, state, self.spec.lower_bounds, self.spec.upper_bounds
            ) if value < lo or value > hi
        )

    def observe(self, state: Mapping[str, float]) -> Mapping[str, float]:
        vector = self._vector(state, self.spec.state_names, "state")
        output = []
        for row, bias in zip(self.spec.observation_matrix, self.spec.observation_bias):
            value = sum(coef * x for coef, x in zip(row, vector)) + bias
            if not math.isfinite(value):
                raise ValueError("observation model produced non-finite value")
            output.append(value)
        return self._mapping(self.spec.observation_names, output)

    def predict_next(
        self,
        state: Mapping[str, float],
        action: Mapping[str, float] | None = None,
    ) -> Mapping[str, float]:
        state_vector = self._vector(state, self.spec.state_names, "state")
        action_map = {} if action is None else action
        if self.spec.action_names:
            action_vector = self._vector(action_map, self.spec.action_names, "action")
        else:
            if action_map:
                raise ValueError("model declares no actions")
            action_vector = ()
        output = []
        for row_a, row_b, bias in zip(
            self.spec.transition_matrix,
            self.spec.action_matrix,
            self.spec.transition_bias,
        ):
            value = (
                sum(coef * x for coef, x in zip(row_a, state_vector))
                + sum(coef * u for coef, u in zip(row_b, action_vector))
                + bias
            )
            if not math.isfinite(value):
                raise ValueError("transition model produced non-finite value")
            output.append(value)
        return self._mapping(self.spec.state_names, output)

    def rollout(
        self,
        initial_state: Mapping[str, float],
        actions: Sequence[Mapping[str, float]],
    ) -> WorldRollout:
        if isinstance(actions, (str, bytes, bytearray)) or not isinstance(actions, Sequence):
            raise ValueError("actions must be a finite sequence")
        if len(actions) > _MAX_STEPS:
            raise ValueError("rollout exceeds step budget")
        state = self._mapping(
            self.spec.state_names,
            self._vector(initial_state, self.spec.state_names, "initial_state"),
        )
        steps = [WorldStep(state, self.observe(state), self._ood(tuple(state.values())))]
        for action in actions:
            state = self.predict_next(state, action)
            state_vector = tuple(state[name] for name in self.spec.state_names)
            steps.append(WorldStep(state, self.observe(state), self._ood(state_vector)))
        return WorldRollout(tuple(steps), self.model_sha256)

    def counterfactual(
        self,
        initial_state: Mapping[str, float],
        baseline_actions: Sequence[Mapping[str, float]],
        intervention_actions: Sequence[Mapping[str, float]],
    ) -> CounterfactualReport:
        if len(baseline_actions) != len(intervention_actions):
            raise ValueError("baseline and intervention horizons must match")
        baseline = self.rollout(initial_state, baseline_actions)
        intervention = self.rollout(initial_state, intervention_actions)
        final_baseline = baseline.steps[-1].state
        final_intervention = intervention.steps[-1].state
        delta = {
            name: final_intervention[name] - final_baseline[name]
            for name in self.spec.state_names
        }
        max_divergence = 0.0
        for left, right in zip(baseline.steps, intervention.steps):
            for index, name in enumerate(self.spec.state_names):
                span = max(self.spec.upper_bounds[index] - self.spec.lower_bounds[index], 1e-12)
                max_divergence = max(
                    max_divergence,
                    abs(right.state[name] - left.state[name]) / span,
                )
        return CounterfactualReport(
            baseline=baseline,
            intervention=intervention,
            final_state_delta=delta,
            max_normalized_state_divergence=max_divergence,
        )

    def calibrate(
        self,
        observed_states: Sequence[Mapping[str, float]],
        observed_observations: Sequence[Mapping[str, float]],
        actions_between_states: Sequence[Mapping[str, float]],
    ) -> WorldModelCalibration:
        if len(observed_states) < 3:
            raise ValueError("at least 3 observed states are required")
        if len(observed_observations) != len(observed_states):
            raise ValueError("observed observations must align with states")
        if len(actions_between_states) != len(observed_states) - 1:
            raise ValueError("actions_between_states must align with state transitions")
        if len(observed_states) > _MAX_STEPS + 1:
            raise ValueError("calibration sequence exceeds budget")

        states = [self._vector(row, self.spec.state_names, "observed_state") for row in observed_states]
        observations = [
            self._vector(row, self.spec.observation_names, "observed_observation")
            for row in observed_observations
        ]
        state_sq = [[] for _ in self.spec.state_names]
        obs_sq = [[] for _ in self.spec.observation_names]
        ood_count = 0
        for state in states:
            if self._ood(state):
                ood_count += 1
        for index, state in enumerate(states):
            mapped_state = self._mapping(self.spec.state_names, state)
            predicted_obs = self._vector(
                self.observe(mapped_state), self.spec.observation_names, "predicted_observation"
            )
            for j, (predicted, actual) in enumerate(zip(predicted_obs, observations[index])):
                obs_sq[j].append((predicted - actual) ** 2)
            if index < len(states) - 1:
                predicted_state = self._vector(
                    self.predict_next(mapped_state, actions_between_states[index]),
                    self.spec.state_names,
                    "predicted_state",
                )
                for j, (predicted, actual) in enumerate(zip(predicted_state, states[index + 1])):
                    state_sq[j].append((predicted - actual) ** 2)

        state_norms = []
        for index, errors in enumerate(state_sq):
            rmse = math.sqrt(sum(errors) / len(errors))
            span = max(self.spec.upper_bounds[index] - self.spec.lower_bounds[index], 1e-12)
            state_norms.append(rmse / span)
        observation_norms = []
        for index, errors in enumerate(obs_sq):
            rmse = math.sqrt(sum(errors) / len(errors))
            values = [row[index] for row in observations]
            scale = max(max(values) - min(values), max(abs(v) for v in values), 1.0)
            observation_norms.append(rmse / scale)
        state_score = math.sqrt(sum(v * v for v in state_norms) / len(state_norms))
        obs_score = math.sqrt(sum(v * v for v in observation_norms) / len(observation_norms))
        calibrated = (
            state_score <= self.spec.calibration_tolerance
            and obs_score <= self.spec.calibration_tolerance
            and ood_count == 0
        )
        return WorldModelCalibration(
            state_normalized_rmse=state_score,
            observation_normalized_rmse=obs_score,
            calibrated=calibrated,
            one_step_predictions=len(states) - 1,
            ood_observed_states=ood_count,
            model_sha256=self.model_sha256,
            sim_to_reality_gap_open=True,
            truth_proven=False,
        )
