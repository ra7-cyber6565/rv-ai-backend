"""Production audit wiring for capability #68.

The result path may carry an explicit world-model specification plus optional
rollout/counterfactual/calibration requests.  No dynamics are inferred from
prose.  Model outputs remain software predictions and never upgrade truth or
close sim-to-reality by themselves.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Mapping, Sequence

from .world_model import WorldModel, WorldModelSpec

_INSTALLED = False


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping")
    return value


def _sequence(value: object, field: str) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > 10_000:
            raise ValueError(f"{field} exceeds runtime budget")
        return value
    raise ValueError(f"{field} must be a bounded sequence")


def _inputs(result: Mapping[str, Any]):
    if "world_model_inputs" in result:
        return result.get("world_model_inputs")
    coverage = result.get("coverage") if isinstance(result.get("coverage"), Mapping) else {}
    return coverage.get("world_model_inputs")


def _model(spec_raw: Mapping[str, Any]) -> WorldModel:
    return WorldModel(WorldModelSpec(
        state_names=tuple(spec_raw.get("state_names") or ()),
        action_names=tuple(spec_raw.get("action_names") or ()),
        observation_names=tuple(spec_raw.get("observation_names") or ()),
        transition_matrix=tuple(tuple(row) for row in spec_raw.get("transition_matrix") or ()),
        action_matrix=tuple(tuple(row) for row in spec_raw.get("action_matrix") or ()),
        transition_bias=tuple(spec_raw.get("transition_bias") or ()),
        observation_matrix=tuple(tuple(row) for row in spec_raw.get("observation_matrix") or ()),
        observation_bias=tuple(spec_raw.get("observation_bias") or ()),
        lower_bounds=tuple(spec_raw.get("lower_bounds") or ()),
        upper_bounds=tuple(spec_raw.get("upper_bounds") or ()),
        calibration_tolerance=spec_raw.get("calibration_tolerance", 0.20),
    ))


def build_world_model_packet(result: Mapping[str, Any]) -> Dict[str, Any]:
    raw = _inputs(result)
    if raw is None:
        return {
            "ran": True,
            "status": "NO_STRUCTURED_WORLD_MODEL_INPUTS",
            "free_form_dynamics_inference_performed": False,
            "result_status_upgraded": False,
            "world_model_is_reality": False,
            "truth_proven": False,
        }
    contract = _mapping(raw, "world_model_inputs")
    allowed = {"spec", "rollout", "counterfactual", "calibration"}
    unknown = sorted(set(contract) - allowed)
    if unknown:
        raise ValueError("unknown world model input keys: " + ", ".join(unknown))
    model = _model(_mapping(contract.get("spec"), "spec"))
    packet: Dict[str, Any] = {
        "ran": True,
        "status": "AUDITED",
        "model_sha256": model.model_sha256,
        "free_form_dynamics_inference_performed": False,
        "result_status_upgraded": False,
        "world_model_is_reality": False,
        "truth_proven": False,
    }
    if "rollout" in contract:
        item = _mapping(contract["rollout"], "rollout")
        packet["rollout"] = asdict(model.rollout(
            _mapping(item.get("initial_state"), "initial_state"),
            [_mapping(row, "action") for row in _sequence(item.get("actions", ()), "actions")],
        ))
    if "counterfactual" in contract:
        item = _mapping(contract["counterfactual"], "counterfactual")
        packet["counterfactual"] = asdict(model.counterfactual(
            _mapping(item.get("initial_state"), "counterfactual.initial_state"),
            [_mapping(row, "baseline_action") for row in _sequence(item.get("baseline_actions", ()), "baseline_actions")],
            [_mapping(row, "intervention_action") for row in _sequence(item.get("intervention_actions", ()), "intervention_actions")],
        ))
    if "calibration" in contract:
        item = _mapping(contract["calibration"], "calibration")
        packet["calibration"] = asdict(model.calibrate(
            [_mapping(row, "observed_state") for row in _sequence(item.get("observed_states", ()), "observed_states")],
            [_mapping(row, "observed_observation") for row in _sequence(item.get("observed_observations", ()), "observed_observations")],
            [_mapping(row, "calibration_action") for row in _sequence(item.get("actions_between_states", ()), "actions_between_states")],
        ))
    return packet


def apply_world_model_wiring(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    coverage = dict(data.get("coverage") or {})
    try:
        packet = build_world_model_packet(data)
    except Exception as exc:
        packet = {
            "ran": False,
            "status": "ASSESSMENT_ERROR",
            "free_form_dynamics_inference_performed": False,
            "result_status_upgraded": False,
            "world_model_is_reality": False,
            "truth_proven": False,
            "error": type(exc).__name__,
        }
    coverage["world_model"] = packet
    data["coverage"] = coverage
    return data


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from . import result_coverage_gate as result_mod
    original_enforce = result_mod.enforce

    def enforce_with_world_model(result: Dict[str, Any]) -> Dict[str, Any]:
        return apply_world_model_wiring(original_enforce(result))

    result_mod.enforce = enforce_with_world_model
