"""Fail-closed software boundary for future physical-lab and sensor adapters.

This module is intentionally conservative.  It provides a typed, auditable
interface for low-risk observation and bounded setpoint requests, but it does
NOT claim that hardware exists, that a command reached hardware, or that a
sensor reading is physically authentic.  Those claims require an independent
hardware/runtime attestation outside this process.

Safety properties:
* dangerous/high-energy action classes are not supported at all;
* all actuator-like requests are dry-run unless a short-lived HMAC approval
  token binds the exact device, action and canonical parameters;
* every setpoint is constrained by an immutable registered safety envelope;
* STOP is always allowed through a dedicated callback and never needs a token;
* sensor timestamps are monotonic and values must be finite/in-range;
* callbacks receive only already-validated data and errors are sanitized;
* software records never mint ``hardware_validated`` or ``truth_proven``.

This is a software safety/control foundation for blueprint capabilities #125 and
#126, not their final hardware proof.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple


_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_ALLOWED_ACTIONS = {"READ_SENSOR", "SET_SAFE_SETPOINT", "STOP"}
_FORBIDDEN_PARAMETER_TERMS = {
    "weapon", "explosive", "detonator", "ignition", "toxin", "poison",
    "radiation", "pathogen", "firearm", "shock", "electrocution",
}
_MAX_PARAMETERS = 100
_MAX_READINGS = 100_000
_MAX_TOKEN_TTL_SECONDS = 15 * 60


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is empty or invalid")
    return text


def _finite(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("lab payload must be finite JSON-compatible data") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _clean_parameter_name(value: object) -> str:
    name = _safe_id(value, "parameter")
    lowered = name.lower()
    if any(term in lowered for term in _FORBIDDEN_PARAMETER_TERMS):
        raise ValueError("parameter belongs to a prohibited high-risk class")
    return name


@dataclass(frozen=True)
class ParameterLimit:
    minimum: float
    maximum: float
    unit: str

    def normalized(self, name: str) -> "ParameterLimit":
        minimum = _finite(self.minimum, f"{name}.minimum")
        maximum = _finite(self.maximum, f"{name}.maximum")
        if maximum <= minimum:
            raise ValueError(f"{name}.maximum must be > minimum")
        unit = _safe_id(self.unit, f"{name}.unit")
        return ParameterLimit(minimum=minimum, maximum=maximum, unit=unit)


@dataclass(frozen=True)
class DeviceEnvelope:
    device_id: str
    parameters: Mapping[str, ParameterLimit]
    observation_only: bool = True
    emergency_stop_supported: bool = True

    def normalized(self) -> "DeviceEnvelope":
        device_id = _safe_id(self.device_id, "device_id")
        if not isinstance(self.parameters, Mapping) or len(self.parameters) > _MAX_PARAMETERS:
            raise ValueError("parameters must be a bounded mapping")
        normalized: Dict[str, ParameterLimit] = {}
        for raw_name, limit in self.parameters.items():
            name = _clean_parameter_name(raw_name)
            if not isinstance(limit, ParameterLimit):
                raise ValueError(f"parameter limit {name} must be ParameterLimit")
            normalized[name] = limit.normalized(name)
        return DeviceEnvelope(
            device_id=device_id,
            parameters=dict(sorted(normalized.items())),
            observation_only=bool(self.observation_only),
            emergency_stop_supported=bool(self.emergency_stop_supported),
        )


@dataclass(frozen=True)
class LabAction:
    action_id: str
    device_id: str
    action_type: str
    parameters: Mapping[str, float] = field(default_factory=dict)

    def normalized(self) -> "LabAction":
        action_id = _safe_id(self.action_id, "action_id")
        device_id = _safe_id(self.device_id, "device_id")
        action_type = str(self.action_type or "").strip().upper()
        if action_type not in _ALLOWED_ACTIONS:
            raise ValueError("unsupported or prohibited physical action type")
        if not isinstance(self.parameters, Mapping) or len(self.parameters) > _MAX_PARAMETERS:
            raise ValueError("action parameters must be a bounded mapping")
        parameters = {
            _clean_parameter_name(name): _finite(value, f"parameters[{name}]")
            for name, value in self.parameters.items()
        }
        if action_type in {"READ_SENSOR", "STOP"} and parameters:
            raise ValueError(f"{action_type} does not accept setpoint parameters")
        if action_type == "SET_SAFE_SETPOINT" and not parameters:
            raise ValueError("SET_SAFE_SETPOINT requires at least one parameter")
        return LabAction(
            action_id=action_id,
            device_id=device_id,
            action_type=action_type,
            parameters=dict(sorted(parameters.items())),
        )


@dataclass(frozen=True)
class ApprovalToken:
    token: str
    expires_at_epoch: int


@dataclass(frozen=True)
class ActionReceipt:
    action_id: str
    device_id: str
    action_type: str
    status: str
    action_hash: str
    callback_result_hash: Optional[str]
    dry_run: bool
    hardware_validated: bool = False
    physical_execution_proven: bool = False
    truth_proven: bool = False


@dataclass(frozen=True)
class SensorReading:
    reading_id: str
    device_id: str
    sensor_id: str
    timestamp_epoch: float
    value: float
    unit: str
    calibration_reference: str

    def normalized(self) -> "SensorReading":
        timestamp = _finite(self.timestamp_epoch, "timestamp_epoch")
        if timestamp <= 0:
            raise ValueError("timestamp_epoch must be > 0")
        return SensorReading(
            reading_id=_safe_id(self.reading_id, "reading_id"),
            device_id=_safe_id(self.device_id, "device_id"),
            sensor_id=_safe_id(self.sensor_id, "sensor_id"),
            timestamp_epoch=timestamp,
            value=_finite(self.value, "sensor value"),
            unit=_safe_id(self.unit, "unit"),
            calibration_reference=_safe_id(self.calibration_reference, "calibration_reference"),
        )


@dataclass(frozen=True)
class SensorReceipt:
    reading_hash: str
    chain_hash: str
    accepted: bool
    hardware_validated: bool = False
    truth_proven: bool = False


class PhysicalLabBoundary:
    """In-memory safety boundary. Persist/audit externally for real deployment."""

    def __init__(self, approval_secret: bytes):
        if not isinstance(approval_secret, (bytes, bytearray)) or len(approval_secret) < 32:
            raise ValueError("approval_secret must contain at least 32 bytes")
        self._secret = bytes(approval_secret)
        self._devices: Dict[str, DeviceEnvelope] = {}
        self._used_nonces: set[str] = set()
        self._last_sensor_time: Dict[Tuple[str, str], float] = {}
        self._reading_ids: set[str] = set()
        self._sensor_chain = "GENESIS"
        self._reading_count = 0

    def register_device(self, envelope: DeviceEnvelope) -> DeviceEnvelope:
        normalized = envelope.normalized()
        existing = self._devices.get(normalized.device_id)
        if existing is not None and existing != normalized:
            raise ValueError("device safety envelope is immutable")
        self._devices[normalized.device_id] = normalized
        return normalized

    def _validate_action_against_envelope(self, action: LabAction) -> tuple[LabAction, DeviceEnvelope]:
        action = action.normalized()
        envelope = self._devices.get(action.device_id)
        if envelope is None:
            raise KeyError(f"device is not registered: {action.device_id}")
        if action.action_type == "SET_SAFE_SETPOINT":
            if envelope.observation_only:
                raise PermissionError("device is observation-only")
            for name, value in action.parameters.items():
                limit = envelope.parameters.get(name)
                if limit is None:
                    raise PermissionError(f"parameter is outside registered safety envelope: {name}")
                if not limit.minimum <= value <= limit.maximum:
                    raise PermissionError(f"setpoint outside safe range: {name}")
        if action.action_type == "STOP" and not envelope.emergency_stop_supported:
            raise PermissionError("registered device does not expose emergency stop")
        return action, envelope

    def action_hash(self, action: LabAction) -> str:
        normalized, _ = self._validate_action_against_envelope(action)
        return _hash({
            "action_id": normalized.action_id,
            "device_id": normalized.device_id,
            "action_type": normalized.action_type,
            "parameters": normalized.parameters,
        })

    def issue_human_approval(
        self,
        action: LabAction,
        *,
        now_epoch: float,
        ttl_seconds: int = 300,
    ) -> ApprovalToken:
        """Mint a short-lived token after the *caller* has obtained human approval.

        The method does not itself prove that a human approved anything; the
        integration layer is responsible for authentication/consent evidence.
        """
        normalized, _ = self._validate_action_against_envelope(action)
        if normalized.action_type != "SET_SAFE_SETPOINT":
            raise ValueError("approval tokens are only used for bounded setpoints")
        now = _finite(now_epoch, "now_epoch")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= _MAX_TOKEN_TTL_SECONDS:
            raise ValueError("ttl_seconds is outside the allowed range")
        expires = int(now) + ttl_seconds
        nonce = secrets.token_hex(16)
        payload = {
            "action_hash": self.action_hash(normalized),
            "device_id": normalized.device_id,
            "expires_at_epoch": expires,
            "nonce": nonce,
        }
        body = _canonical(payload)
        signature = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        token = body.hex() + "." + signature
        return ApprovalToken(token=token, expires_at_epoch=expires)

    def _consume_approval(self, action: LabAction, token: str, now_epoch: float) -> None:
        try:
            body_hex, supplied_signature = str(token).split(".", 1)
            body = bytes.fromhex(body_hex)
            payload = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise PermissionError("approval token is malformed") from exc
        expected_signature = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_signature, supplied_signature):
            raise PermissionError("approval token signature is invalid")
        if not isinstance(payload, dict) or set(payload) != {
            "action_hash", "device_id", "expires_at_epoch", "nonce"
        }:
            raise PermissionError("approval token payload is invalid")
        now = _finite(now_epoch, "now_epoch")
        if type(payload["expires_at_epoch"]) is not int or now > payload["expires_at_epoch"]:
            raise PermissionError("approval token expired")
        nonce = _safe_id(payload["nonce"], "nonce")
        if nonce in self._used_nonces:
            raise PermissionError("approval token already consumed")
        if payload["device_id"] != action.device_id or payload["action_hash"] != self.action_hash(action):
            raise PermissionError("approval token is not bound to this exact action")
        self._used_nonces.add(nonce)

    def execute(
        self,
        action: LabAction,
        *,
        now_epoch: Optional[float] = None,
        approval_token: Optional[str] = None,
        callback: Optional[Callable[[LabAction], Any]] = None,
        dry_run: bool = True,
    ) -> ActionReceipt:
        action, _ = self._validate_action_against_envelope(action)
        action_hash = self.action_hash(action)

        if dry_run:
            return ActionReceipt(
                action_id=action.action_id,
                device_id=action.device_id,
                action_type=action.action_type,
                status="DRY_RUN_VALIDATED",
                action_hash=action_hash,
                callback_result_hash=None,
                dry_run=True,
            )
        if callback is None or not callable(callback):
            raise ValueError("non-dry-run execution requires an explicit callback")

        if action.action_type == "SET_SAFE_SETPOINT":
            if approval_token is None:
                raise PermissionError("bounded setpoint requires a human approval token")
            current = time.time() if now_epoch is None else _finite(now_epoch, "now_epoch")
            self._consume_approval(action, approval_token, current)
        elif action.action_type == "READ_SENSOR":
            raise PermissionError("sensor reads must enter through ingest_sensor_reading")
        # STOP deliberately requires no approval token so a safety layer can
        # always attempt an emergency stop through its registered callback.

        try:
            callback_result = callback(action)
        except Exception as exc:
            raise RuntimeError("physical adapter callback failed") from exc
        callback_hash = _hash(callback_result)
        return ActionReceipt(
            action_id=action.action_id,
            device_id=action.device_id,
            action_type=action.action_type,
            status="CALLBACK_ACCEPTED_RESULT",
            action_hash=action_hash,
            callback_result_hash=callback_hash,
            dry_run=False,
            # Software cannot prove the callback actually touched hardware.
            hardware_validated=False,
            physical_execution_proven=False,
        )

    def ingest_sensor_reading(self, reading: SensorReading) -> SensorReceipt:
        if self._reading_count >= _MAX_READINGS:
            raise ValueError("sensor reading budget exhausted")
        normalized = reading.normalized()
        envelope = self._devices.get(normalized.device_id)
        if envelope is None:
            raise KeyError(f"device is not registered: {normalized.device_id}")
        if normalized.reading_id in self._reading_ids:
            raise ValueError("reading_id already exists")
        limit = envelope.parameters.get(normalized.sensor_id)
        if limit is None:
            raise PermissionError("sensor is outside registered device envelope")
        if normalized.unit != limit.unit:
            raise ValueError("sensor unit does not match registered envelope")
        if not limit.minimum <= normalized.value <= limit.maximum:
            raise ValueError("sensor value is outside registered safe/credible range")
        key = (normalized.device_id, normalized.sensor_id)
        previous_time = self._last_sensor_time.get(key)
        if previous_time is not None and normalized.timestamp_epoch <= previous_time:
            raise ValueError("sensor timestamps must be strictly monotonic")

        payload = {
            "reading_id": normalized.reading_id,
            "device_id": normalized.device_id,
            "sensor_id": normalized.sensor_id,
            "timestamp_epoch": normalized.timestamp_epoch,
            "value": normalized.value,
            "unit": normalized.unit,
            "calibration_reference": normalized.calibration_reference,
        }
        reading_hash = _hash(payload)
        chain_hash = _hash({"previous_hash": self._sensor_chain, "reading_hash": reading_hash})
        self._sensor_chain = chain_hash
        self._reading_ids.add(normalized.reading_id)
        self._last_sensor_time[key] = normalized.timestamp_epoch
        self._reading_count += 1
        return SensorReceipt(
            reading_hash=reading_hash,
            chain_hash=chain_hash,
            accepted=True,
            hardware_validated=False,
            truth_proven=False,
        )

    @property
    def sensor_chain_head(self) -> str:
        return self._sensor_chain
