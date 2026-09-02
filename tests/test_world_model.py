import pytest

from research_engine.world_model import WorldModel, WorldModelSpec


def _model():
    return WorldModel(WorldModelSpec(
        state_names=("position", "velocity"),
        action_names=("thrust",),
        observation_names=("sensor_position",),
        transition_matrix=((1.0, 1.0), (0.0, 1.0)),
        action_matrix=((0.0,), (1.0,)),
        transition_bias=(0.0, 0.0),
        observation_matrix=((1.0, 0.0),),
        observation_bias=(0.0,),
        lower_bounds=(-100.0, -20.0),
        upper_bounds=(100.0, 20.0),
        calibration_tolerance=0.05,
    ))


def test_action_changes_state_and_observation_without_claiming_reality():
    model = _model()
    next_state = model.predict_next(
        {"position": 0.0, "velocity": 1.0}, {"thrust": 2.0}
    )
    assert next_state == {"position": 1.0, "velocity": 3.0}
    assert model.observe(next_state) == {"sensor_position": 1.0}
    rollout = model.rollout(
        {"position": 0.0, "velocity": 1.0},
        [{"thrust": 2.0}, {"thrust": 0.0}],
    )
    assert len(rollout.steps) == 3
    assert rollout.software_only is True
    assert rollout.world_model_is_reality is False
    assert rollout.sim_to_reality_gap_open is True


def test_counterfactual_compares_frozen_equal_horizons_not_causal_truth():
    model = _model()
    report = model.counterfactual(
        {"position": 0.0, "velocity": 0.0},
        [{"thrust": 0.0}, {"thrust": 0.0}],
        [{"thrust": 1.0}, {"thrust": 1.0}],
    )
    assert report.final_state_delta["position"] == pytest.approx(1.0)
    assert report.final_state_delta["velocity"] == pytest.approx(2.0)
    assert report.max_normalized_state_divergence > 0
    assert report.causal_effect_proven is False
    assert report.world_model_is_reality is False


def test_exact_generated_observations_and_transitions_calibrate():
    model = _model()
    states = [
        {"position": 0.0, "velocity": 1.0},
        {"position": 1.0, "velocity": 2.0},
        {"position": 3.0, "velocity": 2.0},
    ]
    actions = [{"thrust": 1.0}, {"thrust": 0.0}]
    observations = [model.observe(state) for state in states]
    report = model.calibrate(states, observations, actions)
    assert report.calibrated is True
    assert report.state_normalized_rmse == pytest.approx(0.0)
    assert report.observation_normalized_rmse == pytest.approx(0.0)
    assert report.one_step_predictions == 2
    assert report.ood_observed_states == 0
    assert report.sim_to_reality_gap_open is True
    assert report.truth_proven is False


def test_bad_observation_fit_or_ood_state_blocks_calibration():
    model = _model()
    states = [
        {"position": 0.0, "velocity": 1.0},
        {"position": 1.0, "velocity": 2.0},
        {"position": 300.0, "velocity": 2.0},
    ]
    observations = [
        {"sensor_position": 50.0},
        {"sensor_position": 50.0},
        {"sensor_position": 50.0},
    ]
    report = model.calibrate(states, observations, [{"thrust": 1.0}, {"thrust": 0.0}])
    assert report.calibrated is False
    assert report.ood_observed_states == 1


def test_mismatched_dimensions_and_names_fail_closed():
    with pytest.raises(ValueError, match="transition_matrix"):
        WorldModel(WorldModelSpec(
            state_names=("x", "y"),
            action_names=("u",),
            observation_names=("z",),
            transition_matrix=((1.0,),),
            action_matrix=((1.0,), (1.0,)),
            transition_bias=(0.0, 0.0),
            observation_matrix=((1.0, 0.0),),
            observation_bias=(0.0,),
            lower_bounds=(-1.0, -1.0),
            upper_bounds=(1.0, 1.0),
        ))
    with pytest.raises(ValueError, match="keys must exactly match"):
        _model().predict_next({"position": 0.0, "velocity": 0.0}, {"wrong": 1.0})


def test_nonfinite_values_and_horizon_mismatch_fail_closed():
    model = _model()
    with pytest.raises(ValueError, match="finite"):
        model.predict_next(
            {"position": float("nan"), "velocity": 0.0}, {"thrust": 0.0}
        )
    with pytest.raises(ValueError, match="horizons must match"):
        model.counterfactual(
            {"position": 0.0, "velocity": 0.0},
            [{"thrust": 0.0}],
            [],
        )


def test_calibration_requires_aligned_real_observation_sequences():
    model = _model()
    states = [
        {"position": 0.0, "velocity": 0.0},
        {"position": 0.0, "velocity": 0.0},
        {"position": 0.0, "velocity": 0.0},
    ]
    with pytest.raises(ValueError, match="align with states"):
        model.calibrate(states, [{"sensor_position": 0.0}], [{"thrust": 0.0}] * 2)
    with pytest.raises(ValueError, match="align with state transitions"):
        model.calibrate(
            states,
            [{"sensor_position": 0.0}] * 3,
            [{"thrust": 0.0}],
        )


def test_model_hash_is_deterministic_for_same_spec():
    assert _model().model_sha256 == _model().model_sha256
    assert len(_model().model_sha256) == 64
