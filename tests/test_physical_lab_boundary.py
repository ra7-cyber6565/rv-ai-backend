import pytest

from research_engine.physical_lab_boundary import (
    DeviceEnvelope,
    LabAction,
    ParameterLimit,
    PhysicalLabBoundary,
    SensorReading,
)


SECRET = b"s" * 32


def _lab(*, observation_only=False):
    lab = PhysicalLabBoundary(SECRET)
    lab.register_device(
        DeviceEnvelope(
            device_id="benign-device-v1",
            parameters={
                "temperature": ParameterLimit(0.0, 80.0, "C"),
                "position": ParameterLimit(-1.0, 1.0, "mm"),
            },
            observation_only=observation_only,
            emergency_stop_supported=True,
        )
    )
    return lab


def test_dry_run_validates_bounded_action_but_never_claims_hardware():
    lab = _lab()
    action = LabAction(
        action_id="a1",
        device_id="benign-device-v1",
        action_type="SET_SAFE_SETPOINT",
        parameters={"temperature": 30.0},
    )
    receipt = lab.execute(action, dry_run=True)
    assert receipt.status == "DRY_RUN_VALIDATED"
    assert receipt.dry_run is True
    assert receipt.hardware_validated is False
    assert receipt.physical_execution_proven is False
    assert receipt.truth_proven is False
    assert len(receipt.action_hash) == 64


def test_observation_only_and_out_of_envelope_actuation_fail_closed():
    observation = _lab(observation_only=True)
    with pytest.raises(PermissionError, match="observation-only"):
        observation.execute(
            LabAction(
                "a1",
                "benign-device-v1",
                "SET_SAFE_SETPOINT",
                {"temperature": 25.0},
            )
        )

    lab = _lab()
    with pytest.raises(PermissionError, match="outside safe range"):
        lab.execute(
            LabAction(
                "a2",
                "benign-device-v1",
                "SET_SAFE_SETPOINT",
                {"temperature": 100.0},
            )
        )
    with pytest.raises(PermissionError, match="outside registered safety envelope"):
        lab.execute(
            LabAction(
                "a3",
                "benign-device-v1",
                "SET_SAFE_SETPOINT",
                {"pressure": 1.0},
            )
        )


def test_non_dry_run_setpoint_requires_exact_short_lived_single_use_approval():
    lab = _lab()
    action = LabAction(
        "set-1",
        "benign-device-v1",
        "SET_SAFE_SETPOINT",
        {"temperature": 35.0},
    )
    with pytest.raises(PermissionError, match="human approval token"):
        lab.execute(action, dry_run=False, callback=lambda item: {"accepted": item.action_id})

    token = lab.issue_human_approval(action, now_epoch=1000, ttl_seconds=60)
    seen = []
    receipt = lab.execute(
        action,
        dry_run=False,
        now_epoch=1010,
        approval_token=token.token,
        callback=lambda item: seen.append(item.action_id) or {"accepted": True},
    )
    assert seen == ["set-1"]
    assert receipt.status == "CALLBACK_ACCEPTED_RESULT"
    assert receipt.hardware_validated is False
    assert receipt.physical_execution_proven is False

    with pytest.raises(PermissionError, match="already consumed"):
        lab.execute(
            action,
            dry_run=False,
            now_epoch=1020,
            approval_token=token.token,
            callback=lambda _item: {"accepted": True},
        )


def test_approval_token_is_bound_to_exact_action_and_expires():
    lab = _lab()
    action = LabAction(
        "set-1",
        "benign-device-v1",
        "SET_SAFE_SETPOINT",
        {"temperature": 30.0},
    )
    token = lab.issue_human_approval(action, now_epoch=1000, ttl_seconds=10)
    changed = LabAction(
        "set-2",
        "benign-device-v1",
        "SET_SAFE_SETPOINT",
        {"temperature": 31.0},
    )
    with pytest.raises(PermissionError, match="not bound"):
        lab.execute(
            changed,
            dry_run=False,
            now_epoch=1005,
            approval_token=token.token,
            callback=lambda _item: {},
        )
    with pytest.raises(PermissionError, match="expired"):
        lab.execute(
            action,
            dry_run=False,
            now_epoch=1011,
            approval_token=token.token,
            callback=lambda _item: {},
        )


def test_stop_does_not_require_approval_but_still_does_not_prove_physical_execution():
    lab = _lab()
    called = []
    receipt = lab.execute(
        LabAction("stop-1", "benign-device-v1", "STOP"),
        dry_run=False,
        callback=lambda item: called.append(item.action_type) or {"stop_requested": True},
    )
    assert called == ["STOP"]
    assert receipt.hardware_validated is False
    assert receipt.physical_execution_proven is False


def test_sensor_ingestion_enforces_calibration_unit_range_monotonicity_and_hash_chain():
    lab = _lab()
    first = lab.ingest_sensor_reading(
        SensorReading(
            reading_id="r1",
            device_id="benign-device-v1",
            sensor_id="temperature",
            timestamp_epoch=1000,
            value=25.0,
            unit="C",
            calibration_reference="cal-v1",
        )
    )
    second = lab.ingest_sensor_reading(
        SensorReading(
            reading_id="r2",
            device_id="benign-device-v1",
            sensor_id="temperature",
            timestamp_epoch=1001,
            value=25.5,
            unit="C",
            calibration_reference="cal-v1",
        )
    )
    assert first.accepted is True
    assert first.hardware_validated is False
    assert first.truth_proven is False
    assert first.chain_hash != second.chain_hash
    assert lab.sensor_chain_head == second.chain_hash

    with pytest.raises(ValueError, match="strictly monotonic"):
        lab.ingest_sensor_reading(
            SensorReading("r3", "benign-device-v1", "temperature", 1001, 26.0, "C", "cal-v1")
        )
    with pytest.raises(ValueError, match="unit"):
        lab.ingest_sensor_reading(
            SensorReading("r4", "benign-device-v1", "temperature", 1002, 26.0, "K", "cal-v1")
        )
    with pytest.raises(ValueError, match="outside registered"):
        lab.ingest_sensor_reading(
            SensorReading("r5", "benign-device-v1", "temperature", 1002, 100.0, "C", "cal-v1")
        )


def test_duplicate_reading_nonfinite_values_and_unknown_sensor_fail_closed():
    lab = _lab()
    reading = SensorReading("r1", "benign-device-v1", "temperature", 1000, 25.0, "C", "cal-v1")
    lab.ingest_sensor_reading(reading)
    with pytest.raises(ValueError, match="already exists"):
        lab.ingest_sensor_reading(reading)
    with pytest.raises(ValueError, match="must be finite"):
        lab.ingest_sensor_reading(
            SensorReading("r2", "benign-device-v1", "temperature", 1001, float("nan"), "C", "cal-v1")
        )
    with pytest.raises(PermissionError, match="outside registered"):
        lab.ingest_sensor_reading(
            SensorReading("r3", "benign-device-v1", "humidity", 1001, 10.0, "pct", "cal-v1")
        )


def test_prohibited_action_types_and_high_risk_parameter_names_are_rejected():
    lab = _lab()
    with pytest.raises(ValueError, match="unsupported or prohibited"):
        lab.execute(LabAction("bad", "benign-device-v1", "IGNITE", {}))
    with pytest.raises(ValueError, match="prohibited high-risk"):
        LabAction(
            "bad2",
            "benign-device-v1",
            "SET_SAFE_SETPOINT",
            {"ignition_voltage": 1.0},
        ).normalized()


def test_callback_errors_are_sanitized():
    lab = _lab()
    action = LabAction(
        "set-err",
        "benign-device-v1",
        "SET_SAFE_SETPOINT",
        {"temperature": 30.0},
    )
    token = lab.issue_human_approval(action, now_epoch=1000)

    def fail(_action):
        raise RuntimeError("hardware provider secret")

    with pytest.raises(RuntimeError, match="physical adapter callback failed") as exc:
        lab.execute(
            action,
            dry_run=False,
            now_epoch=1001,
            approval_token=token.token,
            callback=fail,
        )
    assert "provider secret" not in str(exc.value)
