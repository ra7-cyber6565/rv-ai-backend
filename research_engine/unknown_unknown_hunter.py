"""Bounded blind-spot hunter for capability #85 (Unknown-Unknown Hunter).

Unknown unknowns cannot be proven known by software.  This engine therefore
searches for *exposed blind spots*: missing state coverage, untested assumptions,
unexplained anomalies and interactions between uncovered dimensions.  It emits
concrete probes that could reduce those blind spots while explicitly preserving
``unknown_unknown_proven=False``.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Sequence, Tuple


_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_MAX_ITEMS = 4096
_MAX_STATES = 256
_MAX_TEXT = 20_000


def _id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is empty or invalid")
    return text


def _text(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > _MAX_TEXT:
        raise ValueError(f"{field} is empty or too long")
    return text


def _hash(value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("blind-spot payload must be finite JSON-compatible data") from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _severity(value: object) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError("severity must be finite and in [0,1]")
    return number


@dataclass(frozen=True)
class CoverageDimension:
    dimension_id: str
    expected_states: Tuple[str, ...]
    observed_states: Tuple[str, ...]

    def normalized(self) -> "CoverageDimension":
        dimension_id = _id(self.dimension_id, "dimension_id")
        expected = tuple(sorted({_id(item, "expected_state") for item in self.expected_states}))
        observed = tuple(sorted({_id(item, "observed_state") for item in self.observed_states}))
        if not expected:
            raise ValueError("expected_states must not be empty")
        if len(expected) > _MAX_STATES or len(observed) > _MAX_STATES:
            raise ValueError("coverage state budget exceeded")
        unknown_observed = sorted(set(observed) - set(expected))
        if unknown_observed:
            raise ValueError("observed_states contains undeclared states")
        return CoverageDimension(dimension_id, expected, observed)


@dataclass(frozen=True)
class AssumptionProbe:
    assumption_id: str
    statement: str
    tested: bool
    falsifier: str = ""

    def normalized(self) -> "AssumptionProbe":
        return AssumptionProbe(
            assumption_id=_id(self.assumption_id, "assumption_id"),
            statement=_text(self.statement, "assumption.statement"),
            tested=bool(self.tested),
            falsifier=str(self.falsifier or "").strip()[:_MAX_TEXT],
        )


@dataclass(frozen=True)
class AnomalyProbe:
    anomaly_id: str
    description: str
    severity: float
    explained_by: Tuple[str, ...] = ()

    def normalized(self) -> "AnomalyProbe":
        return AnomalyProbe(
            anomaly_id=_id(self.anomaly_id, "anomaly_id"),
            description=_text(self.description, "anomaly.description"),
            severity=_severity(self.severity),
            explained_by=tuple(sorted({_id(item, "explained_by") for item in self.explained_by})),
        )


@dataclass(frozen=True)
class BlindSpot:
    blind_spot_id: str
    kind: str
    severity: float
    reason: str
    probe: str
    related_ids: Tuple[str, ...]


@dataclass(frozen=True)
class UnknownUnknownReport:
    blind_spots: Tuple[BlindSpot, ...]
    coverage_gap_count: int
    untested_assumption_count: int
    unexplained_anomaly_count: int
    interaction_probe_count: int
    report_hash: str
    blind_spots_found: bool
    unknown_unknown_proven: bool = False
    unknown_unknown_exhaustively_ruled_out: bool = False


def hunt_unknown_unknowns(
    *,
    coverage_dimensions: Sequence[CoverageDimension] = (),
    assumptions: Sequence[AssumptionProbe] = (),
    anomalies: Sequence[AnomalyProbe] = (),
) -> UnknownUnknownReport:
    for name, values in (
        ("coverage_dimensions", coverage_dimensions),
        ("assumptions", assumptions),
        ("anomalies", anomalies),
    ):
        if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
            raise ValueError(f"{name} must be a finite sequence")
        if len(values) > _MAX_ITEMS:
            raise ValueError(f"{name} exceeds bounded size")

    dimensions = tuple(item.normalized() for item in coverage_dimensions)
    assumptions_n = tuple(item.normalized() for item in assumptions)
    anomalies_n = tuple(item.normalized() for item in anomalies)
    for label, ids in (
        ("dimension_id", [item.dimension_id for item in dimensions]),
        ("assumption_id", [item.assumption_id for item in assumptions_n]),
        ("anomaly_id", [item.anomaly_id for item in anomalies_n]),
    ):
        if len(ids) != len(set(ids)):
            raise ValueError(f"{label} values must be unique")

    blind_spots = []
    uncovered_dimensions: Dict[str, Tuple[str, ...]] = {}
    for item in dimensions:
        missing = tuple(sorted(set(item.expected_states) - set(item.observed_states)))
        if not missing:
            continue
        uncovered_dimensions[item.dimension_id] = missing
        severity = min(1.0, len(missing) / max(1, len(item.expected_states)))
        blind_spots.append(BlindSpot(
            blind_spot_id=f"coverage:{item.dimension_id}",
            kind="COVERAGE_GAP",
            severity=severity,
            reason=f"unobserved states: {', '.join(missing)}",
            probe=f"sample or simulate the missing states for {item.dimension_id}",
            related_ids=(item.dimension_id,),
        ))

    for item in assumptions_n:
        if item.tested and item.falsifier:
            continue
        reasons = []
        if not item.tested:
            reasons.append("assumption has not been tested")
        if not item.falsifier:
            reasons.append("no explicit falsifier is registered")
        blind_spots.append(BlindSpot(
            blind_spot_id=f"assumption:{item.assumption_id}",
            kind="UNTESTED_ASSUMPTION",
            severity=0.75 if not item.tested else 0.5,
            reason="; ".join(reasons),
            probe=(
                item.falsifier
                if item.falsifier
                else f"define a discriminating falsification test for {item.assumption_id}"
            ),
            related_ids=(item.assumption_id,),
        ))

    for item in anomalies_n:
        if item.explained_by:
            continue
        blind_spots.append(BlindSpot(
            blind_spot_id=f"anomaly:{item.anomaly_id}",
            kind="UNEXPLAINED_ANOMALY",
            severity=item.severity,
            reason="observed anomaly has no registered explanatory model",
            probe=f"generate competing explanations and a discriminator for {item.anomaly_id}",
            related_ids=(item.anomaly_id,),
        ))

    # Pair uncovered dimensions to reveal interaction cells that one-axis
    # coverage checks miss.  This is intentionally bounded and does not explode
    # into the Cartesian product of every state.
    dimension_ids = sorted(uncovered_dimensions)
    interaction_count = 0
    for left_index, left in enumerate(dimension_ids):
        for right in dimension_ids[left_index + 1:]:
            if interaction_count >= 256:
                break
            interaction_count += 1
            blind_spots.append(BlindSpot(
                blind_spot_id=f"interaction:{left}:{right}",
                kind="UNCOVERED_INTERACTION",
                severity=0.6,
                reason="two dimensions contain uncovered states; their interaction is untested",
                probe=f"stress-test joint regimes across {left} and {right}",
                related_ids=(left, right),
            ))
        if interaction_count >= 256:
            break

    ordered = tuple(sorted(blind_spots, key=lambda item: (-item.severity, item.blind_spot_id)))
    payload = [
        {
            "id": item.blind_spot_id,
            "kind": item.kind,
            "severity": item.severity,
            "reason": item.reason,
            "probe": item.probe,
            "related_ids": item.related_ids,
        }
        for item in ordered
    ]
    return UnknownUnknownReport(
        blind_spots=ordered,
        coverage_gap_count=sum(1 for item in ordered if item.kind == "COVERAGE_GAP"),
        untested_assumption_count=sum(1 for item in ordered if item.kind == "UNTESTED_ASSUMPTION"),
        unexplained_anomaly_count=sum(1 for item in ordered if item.kind == "UNEXPLAINED_ANOMALY"),
        interaction_probe_count=sum(1 for item in ordered if item.kind == "UNCOVERED_INTERACTION"),
        report_hash=_hash(payload),
        blind_spots_found=bool(ordered),
        unknown_unknown_proven=False,
        unknown_unknown_exhaustively_ruled_out=False,
    )
