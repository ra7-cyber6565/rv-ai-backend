"""Core types and input-safety helpers for AI-2 validation."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional

UNKNOWN = "UNKNOWN / NOT TESTED"
TO_ESTIMATE = "TO BE ESTIMATED"


class HypothesisStatus(str, Enum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL PASS"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAIL = "FAIL"


class TestState(str, Enum):
    PROPOSED = "TEST PROPOSED"
    POSSIBLE = "TEST POSSIBLE"
    PERFORMED = "TEST PERFORMED"
    OBSERVED = "RESULT OBSERVED"


class VariableRole(str, Enum):
    INDEPENDENT = "independent"
    DEPENDENT = "dependent"
    CONTROL = "control"
    MEDIATOR = "mediator"
    CONFOUNDER = "confounder"
    STATE = "state"
    UNCERTAINTY = "uncertainty"
    PARAMETER = "parameter"


@dataclass(frozen=True)
class VariableSpec:
    symbol: str
    definition: str
    unit: str
    interpretation: str
    role: str
    value_status: str = UNKNOWN

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BaselineSpec:
    baseline_id: str
    name: str
    reason: str
    metric: str = UNKNOWN
    result: Any = UNKNOWN
    status: str = "TO BE MEASURED"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HypothesisSpec:
    hypothesis_id: str
    statement: str
    mechanism: str
    prediction: str
    null_hypothesis: str
    variables: List[str]
    baseline_id: str
    test: str
    falsification_condition: str
    scope: str = "Only the explicitly tested population/time/regime."
    status: HypothesisStatus = HypothesisStatus.INCONCLUSIVE
    status_reason: str = "No observed result has been supplied."

    def to_dict(self) -> Dict[str, Any]:
        row = asdict(self)
        row["status"] = self.status.value
        return row


@dataclass
class ExperimentSpec:
    test_id: str
    hypothesis_id: str
    hypothesis: str
    variables: List[str]
    dataset_sample: str
    experimental_setup: str
    prediction: str
    null_hypothesis: str
    metric: str
    baseline: str
    confounders: List[str]
    falsification_condition: str
    replication_method: str
    state: TestState = TestState.PROPOSED
    decision_rule: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        row = asdict(self)
        row["state"] = self.state.value
        return row


def mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def listify(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def text(value: Any, default: str = "") -> str:
    out = " ".join(str(value or "").split()).strip()
    return out or default


def known(value: Any) -> bool:
    value_text = text(value).upper()
    return bool(value_text) and value_text not in {UNKNOWN.upper(), TO_ESTIMATE.upper()} and not value_text.startswith("TO BE SPECIFIED")


def number(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def numbers(values: Any) -> List[float]:
    out: List[float] = []
    for value in listify(values):
        parsed = number(value)
        if parsed is not None:
            out.append(parsed)
    return out


__all__ = [
    "UNKNOWN", "TO_ESTIMATE", "HypothesisStatus", "TestState", "VariableRole",
    "VariableSpec", "BaselineSpec", "HypothesisSpec", "ExperimentSpec",
    "mapping", "listify", "text", "known", "number", "numbers",
]
