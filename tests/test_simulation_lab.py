import pytest

from research_engine.simulation_lab import (
    AgentSpec,
    DigitalTwin,
    DigitalTwinSpec,
    FaultMode,
    black_swan_suite,
    run_agent_environment,
    run_fault_campaign,
)


def _stable_twin():
    return DigitalTwin(
        DigitalTwinSpec(
            state_names=("temperature",),
            transition_matrix=((0.5,),),
            bias=(2.5,),
            lower_bounds=(0.0,),
            upper_bounds=(10.0,),
            calibration_tolerance=0.05,
        )
    )


def test_digital_twin_is_deterministic_and_keeps_sim_to_reality_gap_open():
    twin = _stable_twin()
    first = twin.simulate({"temperature": 5.0}, 8)
    second = twin.simulate({"temperature": 5.0}, 8)
    assert first.states == second.states
    assert first.model_hash == second.model_hash
    assert first.bound_violations == ()
    assert first.software_only is True
    assert first.hardware_validated is False

    calibration = twin.validate_calibration(first.states)
    assert calibration.calibrated is True
    assert calibration.normalized_rmse == pytest.approx(0.0)
    assert calibration.one_step_predictions == 8
    assert calibration.sim_to_reality_gap_open is True


def test_bad_observations_do_not_fake_calibrated_twin():
    twin = _stable_twin()
    report = twin.validate_calibration([
        {"temperature": 5.0},
        {"temperature": 9.0},
        {"temperature": 1.0},
        {"temperature": 9.0},
    ])
    assert report.calibrated is False
    assert report.normalized_rmse > twin.spec.calibration_tolerance


def test_fault_campaign_ranks_fmea_and_measures_boundary_damage_and_recovery():
    twin = _stable_twin()
    report = run_fault_campaign(
        twin,
        {"temperature": 5.0},
        [
            FaultMode(
                "heater stuck high",
                "temperature",
                20.0,
                severity=9,
                occurrence=4,
                detectability=5,
                duration_steps=1,
            ),
            FaultMode(
                "small sensor bias",
                "temperature",
                1.0,
                severity=3,
                occurrence=5,
                detectability=4,
                duration_steps=2,
            ),
        ],
        steps=12,
        injection_step=2,
    )
    assert [item.name for item in report.ranked_fmea] == [
        "heater stuck high",
        "small sensor bias",
    ]
    high = report.ranked_fmea[0]
    assert high.rpn == 180
    assert high.bound_violations >= 1
    assert high.peak_normalized_deviation > 1.0
    assert high.recovered is True
    assert report.software_only is True
    assert report.safety_review_required is True


def test_invalid_twin_and_fault_dimensions_fail_closed():
    with pytest.raises(ValueError, match="square"):
        DigitalTwin(
            DigitalTwinSpec(
                state_names=("x", "y"),
                transition_matrix=((1.0,), (0.0, 1.0)),
                bias=(0.0, 0.0),
                lower_bounds=(-1.0, -1.0),
                upper_bounds=(1.0, 1.0),
            )
        )
    twin = _stable_twin()
    with pytest.raises(ValueError, match="unknown fault variable"):
        run_fault_campaign(
            twin,
            {"temperature": 5.0},
            [FaultMode("bad", "pressure", 1, 5, 5, 5)],
        )


def test_agent_environment_is_seed_reproducible_and_shock_sensitive():
    agents = [
        AgentSpec("fast", response=1.0, inertia=0.4, coupling=0.1, noise_scale=0.1),
        AgentSpec("slow", response=0.5, inertia=0.8, coupling=0.2, noise_scale=0.1),
    ]
    kwargs = dict(
        agents=agents,
        initial={"fast": 0.0, "slow": 1.0},
        external_signal=[1.0] * 12,
        shocks={5: -3.0},
    )
    first = run_agent_environment(**kwargs, seed=7)
    second = run_agent_environment(**kwargs, seed=7)
    other_seed = run_agent_environment(**kwargs, seed=8)
    assert first.simulation_hash == second.simulation_hash
    assert first.aggregate == second.aggregate
    assert first.simulation_hash != other_seed.simulation_hash
    assert first.aggregate[6] < first.aggregate[5]
    assert first.synthetic_only is True


def test_black_swan_suite_is_seeded_and_materially_stresses_baseline():
    baseline = [100.0 + index for index in range(20)]
    first = black_swan_suite(baseline, seed=99)
    second = black_swan_suite(baseline, seed=99)
    assert first.scenario_hash == second.scenario_hash
    assert [scenario.name for scenario in first.scenarios] == [
        "tail_crash",
        "volatility_cluster",
        "regime_reversal",
        "liquidity_freeze_gap",
    ]
    assert all(scenario.finite for scenario in first.scenarios)
    assert max(scenario.max_abs_step for scenario in first.scenarios) > first.baseline.max_abs_step
    assert max(scenario.max_drawdown_abs for scenario in first.scenarios) > first.baseline.max_drawdown_abs
    assert first.synthetic_only is True
    assert first.future_guarantee is False


def test_black_swan_suite_rejects_short_or_nonfinite_data():
    with pytest.raises(ValueError):
        black_swan_suite([1.0, 2.0])
    with pytest.raises(ValueError, match="finite"):
        black_swan_suite([1.0] * 7 + [float("nan")])
