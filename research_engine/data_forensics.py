"""Deterministic tabular data-forensics checks with row-level evidence.

The auditor detects malformed, conflicting and statistically suspicious data.
An anomaly is *not* automatically labelled fraud: the report keeps
``fraud_proven=False`` because manipulation requires independent evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ColumnRule:
    name: str
    kind: str = "any"  # any | numeric | timestamp | text
    required: bool = False
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    monotonic_increasing: bool = False
    max_step: Optional[float] = None
    robust_outlier_z: float = 6.0

    def validate(self) -> None:
        if not self.name:
            raise ValueError("column rule name required")
        if self.kind not in {"any", "numeric", "timestamp", "text"}:
            raise ValueError("unsupported column kind")
        if self.minimum is not None and not math.isfinite(float(self.minimum)):
            raise ValueError("minimum must be finite")
        if self.maximum is not None and not math.isfinite(float(self.maximum)):
            raise ValueError("maximum must be finite")
        if (
            self.minimum is not None
            and self.maximum is not None
            and float(self.minimum) > float(self.maximum)
        ):
            raise ValueError("minimum cannot exceed maximum")
        if self.max_step is not None and (
            not math.isfinite(float(self.max_step)) or float(self.max_step) < 0
        ):
            raise ValueError("max_step must be finite and >=0")
        if (
            not math.isfinite(float(self.robust_outlier_z))
            or not 2 <= float(self.robust_outlier_z) <= 100
        ):
            raise ValueError("robust_outlier_z must be 2..100")


@dataclass(frozen=True)
class ForensicIssue:
    code: str
    severity: str
    column: str
    row_index: Optional[int]
    detail: str


@dataclass(frozen=True)
class DataForensicsReport:
    dataset_sha256: str
    row_count: int
    issues: Tuple[ForensicIssue, ...]
    critical_count: int
    warning_count: int
    passed: bool
    fraud_proven: bool = False


def _hashable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return {"__nonfinite__": "nan"}
        if math.isinf(value):
            return {"__nonfinite__": "inf" if value > 0 else "-inf"}
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _hashable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_hashable(item) for item in value]
    return {
        "__type__": type(value).__name__,
        "__repr__": repr(value)[:200],
    }


def _sha_rows(rows: Any) -> str:
    body = json.dumps(
        _hashable(rows),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _numeric(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp(value: Any) -> Optional[float]:
    if isinstance(value, datetime):
        return value.timestamp()
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def audit_rows(
    rows: Sequence[Mapping[str, Any]],
    rules: Sequence[ColumnRule],
    *,
    primary_key: Optional[str] = None,
    max_rows: int = 100_000,
) -> DataForensicsReport:
    """Audit a bounded table and return deterministic, row-addressable issues."""
    if not rows:
        raise ValueError("at least one row is required")
    if len(rows) > max_rows:
        raise ValueError("row limit exceeded")
    if not rules:
        raise ValueError("at least one column rule required")
    if len({rule.name for rule in rules}) != len(rules):
        raise ValueError("duplicate column rules")
    for rule in rules:
        rule.validate()

    clean_rows = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("each row must be a mapping")
        clean_rows.append(dict(row))

    issues: list[ForensicIssue] = []

    def add(
        code: str,
        severity: str,
        column: str,
        row_index: Optional[int],
        detail: str,
    ) -> None:
        issues.append(ForensicIssue(code, severity, column, row_index, detail))

    # Byte/structure-equivalent duplicates are suspicious but not proof of fraud.
    row_hash_seen: dict[str, int] = {}
    for row_index, row in enumerate(clean_rows):
        digest = _sha_rows(row)
        if digest in row_hash_seen:
            add(
                "duplicate_row",
                "warning",
                "",
                row_index,
                f"exact duplicate of row {row_hash_seen[digest]}",
            )
        else:
            row_hash_seen[digest] = row_index

    # A duplicate primary key with different content is stronger evidence of
    # corruption than an exact duplicated row, so it is release-critical.
    if primary_key:
        seen_keys: dict[str, int] = {}
        for row_index, row in enumerate(clean_rows):
            value = row.get(primary_key)
            if value is None or value == "":
                add(
                    "missing_primary_key",
                    "critical",
                    primary_key,
                    row_index,
                    "primary key is missing",
                )
                continue
            key = json.dumps(
                _hashable(value),
                sort_keys=True,
                separators=(",", ":"),
            )
            if key in seen_keys:
                previous = seen_keys[key]
                if _sha_rows(row) == _sha_rows(clean_rows[previous]):
                    add(
                        "duplicate_primary_key",
                        "warning",
                        primary_key,
                        row_index,
                        f"same key and identical row as {previous}",
                    )
                else:
                    add(
                        "conflicting_primary_key",
                        "critical",
                        primary_key,
                        row_index,
                        f"same key has different row content than {previous}",
                    )
            else:
                seen_keys[key] = row_index

    for rule in rules:
        parsed: list[tuple[int, Any]] = []
        for row_index, row in enumerate(clean_rows):
            present = (
                rule.name in row
                and row[rule.name] is not None
                and row[rule.name] != ""
            )
            if rule.required and not present:
                add(
                    "missing_required",
                    "critical",
                    rule.name,
                    row_index,
                    "required value is missing",
                )
                continue
            if not present:
                continue
            value = row[rule.name]

            if rule.kind == "numeric":
                number = _numeric(value)
                if number is None:
                    add(
                        "invalid_numeric",
                        "critical",
                        rule.name,
                        row_index,
                        "value is not numeric",
                    )
                    continue
                if not math.isfinite(number):
                    add(
                        "nonfinite_numeric",
                        "critical",
                        rule.name,
                        row_index,
                        "NaN/Infinity is not valid measured data",
                    )
                    continue
                parsed.append((row_index, number))
                if rule.minimum is not None and number < float(rule.minimum):
                    add(
                        "below_minimum",
                        "critical",
                        rule.name,
                        row_index,
                        f"{number} < {rule.minimum}",
                    )
                if rule.maximum is not None and number > float(rule.maximum):
                    add(
                        "above_maximum",
                        "critical",
                        rule.name,
                        row_index,
                        f"{number} > {rule.maximum}",
                    )

            elif rule.kind == "timestamp":
                stamp = _timestamp(value)
                if stamp is None or not math.isfinite(stamp):
                    add(
                        "invalid_timestamp",
                        "critical",
                        rule.name,
                        row_index,
                        "timestamp could not be parsed",
                    )
                    continue
                parsed.append((row_index, stamp))

            elif rule.kind == "text":
                if not isinstance(value, str):
                    add(
                        "invalid_text",
                        "warning",
                        rule.name,
                        row_index,
                        "text column contains non-string value",
                    )
                else:
                    parsed.append((row_index, value))
            else:
                parsed.append((row_index, value))

        if rule.monotonic_increasing and parsed:
            previous_index, previous_value = parsed[0]
            for row_index, value in parsed[1:]:
                try:
                    backwards = value < previous_value
                except TypeError:
                    backwards = True
                if backwards:
                    add(
                        "order_reversal",
                        "critical",
                        rule.name,
                        row_index,
                        f"value goes backward relative to row {previous_index}",
                    )
                previous_index, previous_value = row_index, value

        if (
            rule.max_step is not None
            and rule.kind in {"numeric", "timestamp"}
            and len(parsed) > 1
        ):
            limit = float(rule.max_step)
            for (left_index, left), (right_index, right) in zip(parsed, parsed[1:]):
                if abs(float(right) - float(left)) > limit:
                    add(
                        "abrupt_step",
                        "warning",
                        rule.name,
                        right_index,
                        f"step from row {left_index} exceeds {limit}",
                    )

        # Median absolute deviation is robust to the very extreme point it is
        # intended to flag.  Keep it a warning: an outlier may be the discovery.
        if rule.kind == "numeric" and len(parsed) >= 7:
            values = [float(value) for _, value in parsed]
            median = statistics.median(values)
            deviations = [abs(value - median) for value in values]
            mad = statistics.median(deviations)
            if mad > 0:
                for row_index, value in parsed:
                    robust_z = 0.67448975 * abs(float(value) - median) / mad
                    if robust_z > rule.robust_outlier_z:
                        add(
                            "robust_outlier",
                            "warning",
                            rule.name,
                            row_index,
                            f"robust z={robust_z:.3f}",
                        )

    issues.sort(
        key=lambda issue: (
            issue.row_index if issue.row_index is not None else -1,
            issue.column,
            issue.code,
        )
    )
    critical_count = sum(issue.severity == "critical" for issue in issues)
    warning_count = sum(issue.severity == "warning" for issue in issues)
    return DataForensicsReport(
        dataset_sha256=_sha_rows(clean_rows),
        row_count=len(clean_rows),
        issues=tuple(issues),
        critical_count=critical_count,
        warning_count=warning_count,
        passed=(critical_count == 0),
        fraud_proven=False,
    )
