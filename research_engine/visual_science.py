"""Deterministic scientific-figure reasoning and misleading-chart risk detection.

This module is deliberately *not* a computer-vision model.  It consumes a
normalized figure specification produced by a trusted parser/OCR/vision adapter
and performs reproducible quantitative checks over axes, series and provenance.
The extraction confidence is carried into every conclusion so low-confidence
OCR can never silently become a strong scientific claim.

A risk flag means that a visualization can materially distort interpretation;
it is never evidence of deceptive intent or fraud by the author.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


_ALLOWED_CHART_TYPES = {
    "bar",
    "line",
    "scatter",
    "area",
    "stacked_bar",
    "pie",
    "histogram",
    "box",
    "other",
}
_ALLOWED_SCALES = {"linear", "log10", "ln"}
_ALLOWED_DIRECTIONS = {"normal", "reversed"}
_ALLOWED_SEVERITY = {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"}


def _finite(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _probability(value: Any, field_name: str) -> float:
    number = _finite(value, field_name)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{field_name} must be in [0,1]")
    return number


def _canonical_hash(value: Any) -> str:
    body = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _pearson(left: Sequence[float], right: Sequence[float]) -> Optional[float]:
    if len(left) != len(right) or len(left) < 3:
        return None
    mean_left = statistics.fmean(left)
    mean_right = statistics.fmean(right)
    dl = [item - mean_left for item in left]
    dr = [item - mean_right for item in right]
    denom = math.sqrt(sum(item * item for item in dl) * sum(item * item for item in dr))
    if denom <= 0:
        return None
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(dl, dr)) / denom))


def _linear_slope(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    if len(x) != len(y) or len(x) < 2:
        return None
    x_mean = statistics.fmean(x)
    y_mean = statistics.fmean(y)
    denominator = sum((item - x_mean) ** 2 for item in x)
    if denominator <= 0:
        return None
    return sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y)) / denominator


def _sign(value: Optional[float], *, epsilon: float = 1e-12) -> int:
    if value is None or abs(value) <= epsilon:
        return 0
    return 1 if value > 0 else -1


@dataclass(frozen=True)
class AxisSpec:
    axis_id: str
    label: str
    minimum: float
    maximum: float
    scale: str = "linear"
    direction: str = "normal"
    scale_disclosed: bool = True
    direction_disclosed: bool = True

    def validate(self) -> None:
        if not str(self.axis_id).strip():
            raise ValueError("axis_id is required")
        lower = _finite(self.minimum, f"{self.axis_id}.minimum")
        upper = _finite(self.maximum, f"{self.axis_id}.maximum")
        if lower >= upper:
            raise ValueError(f"{self.axis_id} minimum must be below maximum")
        if self.scale not in _ALLOWED_SCALES:
            raise ValueError(f"unsupported axis scale: {self.scale}")
        if self.direction not in _ALLOWED_DIRECTIONS:
            raise ValueError(f"unsupported axis direction: {self.direction}")
        if self.scale != "linear" and lower <= 0:
            raise ValueError("logarithmic axes require positive limits")


@dataclass(frozen=True)
class ChartSeries:
    series_id: str
    label: str
    x: Tuple[float, ...]
    y: Tuple[float, ...]
    y_axis_id: str = "y"
    group: str = ""
    uncertainty: Tuple[float, ...] = ()
    full_x: Tuple[float, ...] = ()
    full_y: Tuple[float, ...] = ()

    def validate(self) -> None:
        if not str(self.series_id).strip():
            raise ValueError("series_id is required")
        if not self.x or len(self.x) != len(self.y):
            raise ValueError(f"series {self.series_id} x/y must be equal non-empty lengths")
        for index, value in enumerate(self.x):
            _finite(value, f"{self.series_id}.x[{index}]")
        for index, value in enumerate(self.y):
            _finite(value, f"{self.series_id}.y[{index}]")
        if self.uncertainty:
            if len(self.uncertainty) != len(self.y):
                raise ValueError("uncertainty length must match y")
            for index, value in enumerate(self.uncertainty):
                if _finite(value, f"{self.series_id}.uncertainty[{index}]") < 0:
                    raise ValueError("uncertainty must be non-negative")
        if bool(self.full_x) != bool(self.full_y) or (self.full_x and len(self.full_x) != len(self.full_y)):
            raise ValueError("full_x/full_y must both be present with equal lengths")
        for index, value in enumerate(self.full_x):
            _finite(value, f"{self.series_id}.full_x[{index}]")
        for index, value in enumerate(self.full_y):
            _finite(value, f"{self.series_id}.full_y[{index}]")


@dataclass(frozen=True)
class ChartSpec:
    figure_id: str
    chart_type: str
    x_axis: AxisSpec
    y_axes: Tuple[AxisSpec, ...]
    series: Tuple[ChartSeries, ...]
    caption: str = ""
    source_locator: str = ""
    extraction_confidence: float = 1.0
    extracted_from_image: bool = False
    width_px: int = 1000
    height_px: int = 700
    inferential_claim: bool = False
    exclusive_parts: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not str(self.figure_id).strip():
            raise ValueError("figure_id is required")
        if self.chart_type not in _ALLOWED_CHART_TYPES:
            raise ValueError(f"unsupported chart_type: {self.chart_type}")
        self.x_axis.validate()
        if not self.y_axes:
            raise ValueError("at least one y axis is required")
        y_ids = [item.axis_id for item in self.y_axes]
        if len(set(y_ids)) != len(y_ids):
            raise ValueError("y axis ids must be unique")
        for axis in self.y_axes:
            axis.validate()
        if not self.series:
            raise ValueError("at least one chart series is required")
        ids = [item.series_id for item in self.series]
        if len(set(ids)) != len(ids):
            raise ValueError("series ids must be unique")
        for item in self.series:
            item.validate()
            if item.y_axis_id not in y_ids:
                raise ValueError(f"series {item.series_id} references unknown y axis")
        _probability(self.extraction_confidence, "extraction_confidence")
        if not isinstance(self.width_px, int) or not isinstance(self.height_px, int):
            raise ValueError("width_px and height_px must be integers")
        if not 100 <= self.width_px <= 100_000 or not 100 <= self.height_px <= 100_000:
            raise ValueError("chart dimensions are outside safe bounds")


@dataclass(frozen=True)
class VisualRisk:
    code: str
    severity: str
    message: str
    quantitative_detail: Mapping[str, float] = field(default_factory=dict)
    affected_series: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.severity not in _ALLOWED_SEVERITY:
            raise ValueError("invalid visual-risk severity")


@dataclass(frozen=True)
class TrendFinding:
    series_id: str
    slope: Optional[float]
    direction: str
    confidence_cap: float
    reason: str


@dataclass(frozen=True)
class VisualAuditReport:
    figure_id: str
    spec_hash: str
    status: str
    extraction_confidence: float
    risks: Tuple[VisualRisk, ...]
    trends: Tuple[TrendFinding, ...]
    high_risk: bool
    strong_claim_allowed: bool
    intent_inference_allowed: bool = False


class VisualScienceEngine:
    """Reproducible quantitative audit of a normalized scientific figure."""

    def __init__(
        self,
        *,
        minimum_extraction_confidence: float = 0.80,
        high_confidence_extraction: float = 0.95,
    ):
        self.minimum_extraction_confidence = _probability(
            minimum_extraction_confidence,
            "minimum_extraction_confidence",
        )
        self.high_confidence_extraction = _probability(
            high_confidence_extraction,
            "high_confidence_extraction",
        )
        if self.high_confidence_extraction < self.minimum_extraction_confidence:
            raise ValueError("high confidence threshold cannot be below minimum")

    @staticmethod
    def _axis_map(spec: ChartSpec) -> Dict[str, AxisSpec]:
        return {item.axis_id: item for item in spec.y_axes}

    @staticmethod
    def _risk(
        code: str,
        severity: str,
        message: str,
        *,
        detail: Optional[Mapping[str, float]] = None,
        series: Sequence[str] = (),
    ) -> VisualRisk:
        return VisualRisk(
            code=code,
            severity=severity,
            message=message,
            quantitative_detail=dict(detail or {}),
            affected_series=tuple(series),
        )

    def _extraction_risks(self, spec: ChartSpec) -> list[VisualRisk]:
        if not spec.extracted_from_image:
            return []
        confidence = float(spec.extraction_confidence)
        if confidence < self.minimum_extraction_confidence:
            return [self._risk(
                "LOW_EXTRACTION_CONFIDENCE",
                "CRITICAL",
                "Image/OCR extraction confidence is too low for scientific interpretation.",
                detail={"confidence": confidence},
            )]
        if confidence < self.high_confidence_extraction:
            return [self._risk(
                "LIMITED_EXTRACTION_CONFIDENCE",
                "MEDIUM",
                "Image/OCR extraction is usable but caps downstream confidence.",
                detail={"confidence": confidence},
            )]
        return []

    def _axis_risks(self, spec: ChartSpec) -> list[VisualRisk]:
        risks: list[VisualRisk] = []
        axes = self._axis_map(spec)
        for axis in spec.y_axes:
            if axis.scale != "linear" and not axis.scale_disclosed:
                risks.append(self._risk(
                    "UNDISCLOSED_LOG_SCALE",
                    "HIGH",
                    "A logarithmic y-axis is not explicitly disclosed.",
                ))
            if axis.direction == "reversed" and not axis.direction_disclosed:
                risks.append(self._risk(
                    "UNDISCLOSED_REVERSED_AXIS",
                    "HIGH",
                    "A reversed y-axis is not explicitly disclosed.",
                ))

        if spec.chart_type in {"bar", "stacked_bar"}:
            for series in spec.series:
                axis = axes[series.y_axis_id]
                values = [float(item) for item in series.y]
                if axis.scale != "linear" or not values:
                    continue
                all_nonnegative = min(values) >= 0
                all_nonpositive = max(values) <= 0
                zero_excluded = (all_nonnegative and axis.minimum > 0) or (
                    all_nonpositive and axis.maximum < 0
                )
                if zero_excluded:
                    displayed_span = axis.maximum - axis.minimum
                    data_span = max(values) - min(values)
                    amplification = displayed_span / max(data_span, 1e-12)
                    risks.append(self._risk(
                        "TRUNCATED_BAR_BASELINE",
                        "HIGH",
                        "Bar length is encoded from a non-zero baseline, which can magnify visual differences.",
                        detail={
                            "axis_min": float(axis.minimum),
                            "axis_max": float(axis.maximum),
                            "displayed_span_to_data_span": float(amplification),
                        },
                        series=(series.series_id,),
                    ))

        if len(spec.y_axes) > 1 and len(spec.series) >= 2:
            series_by_axis: Dict[str, list[ChartSeries]] = {}
            for item in spec.series:
                series_by_axis.setdefault(item.y_axis_id, []).append(item)
            axis_ids = list(series_by_axis)
            if len(axis_ids) >= 2:
                for left_axis_index in range(len(axis_ids)):
                    for right_axis_index in range(left_axis_index + 1, len(axis_ids)):
                        for left in series_by_axis[axis_ids[left_axis_index]]:
                            for right in series_by_axis[axis_ids[right_axis_index]]:
                                if len(left.y) != len(right.y):
                                    continue
                                correlation = _pearson(
                                    [float(value) for value in left.y],
                                    [float(value) for value in right.y],
                                )
                                if correlation is not None and abs(correlation) >= 0.80:
                                    risks.append(self._risk(
                                        "DUAL_AXIS_CORRELATION_RISK",
                                        "MEDIUM",
                                        "Strong co-movement is shown on separate y-scales; visual alignment is scale-dependent and is not causal evidence.",
                                        detail={"pearson_r": float(correlation)},
                                        series=(left.series_id, right.series_id),
                                    ))
        return risks

    def _layout_risks(self, spec: ChartSpec) -> list[VisualRisk]:
        aspect = spec.width_px / spec.height_px
        if spec.chart_type in {"line", "area", "scatter"} and (aspect > 4.0 or aspect < 0.45):
            return [self._risk(
                "EXTREME_ASPECT_RATIO",
                "MEDIUM",
                "Extreme chart aspect ratio can visually exaggerate or flatten slopes.",
                detail={"width_to_height": float(aspect)},
            )]
        return []

    def _uncertainty_risks(self, spec: ChartSpec) -> list[VisualRisk]:
        if not spec.inferential_claim:
            return []
        missing = [item.series_id for item in spec.series if not item.uncertainty]
        if not missing:
            return []
        return [self._risk(
            "MISSING_UNCERTAINTY",
            "MEDIUM",
            "The figure is marked inferential but one or more series omit uncertainty/error information.",
            series=missing,
        )]

    def _window_risks(self, spec: ChartSpec) -> list[VisualRisk]:
        risks: list[VisualRisk] = []
        for series in spec.series:
            if not series.full_x:
                continue
            shown_x = [float(item) for item in series.x]
            full_x = [float(item) for item in series.full_x]
            shown_y = [float(item) for item in series.y]
            full_y = [float(item) for item in series.full_y]
            full_span = max(full_x) - min(full_x)
            shown_span = max(shown_x) - min(shown_x)
            if full_span <= 0:
                continue
            coverage = shown_span / full_span
            shown_slope = _linear_slope(shown_x, shown_y)
            full_slope = _linear_slope(full_x, full_y)
            sign_flip = _sign(shown_slope) != 0 and _sign(full_slope) != 0 and _sign(shown_slope) != _sign(full_slope)
            if coverage < 0.30 and sign_flip:
                risks.append(self._risk(
                    "CHERRY_PICKED_WINDOW_SIGN_FLIP",
                    "HIGH",
                    "The displayed time/range window covers a small fraction of supplied full data and reverses the full-period trend direction.",
                    detail={
                        "displayed_range_fraction": float(coverage),
                        "displayed_slope": float(shown_slope or 0.0),
                        "full_slope": float(full_slope or 0.0),
                    },
                    series=(series.series_id,),
                ))
            elif coverage < 0.15:
                risks.append(self._risk(
                    "NARROW_DISPLAY_WINDOW",
                    "MEDIUM",
                    "The displayed range is a small fraction of the supplied full range; selection sensitivity should be checked.",
                    detail={"displayed_range_fraction": float(coverage)},
                    series=(series.series_id,),
                ))
        return risks

    def _composition_risks(self, spec: ChartSpec) -> list[VisualRisk]:
        if not spec.exclusive_parts or spec.chart_type not in {"pie", "stacked_bar"}:
            return []
        # Exclusive composition charts are expected to sum to either 1 or 100.
        totals = []
        max_len = max(len(item.y) for item in spec.series)
        for index in range(max_len):
            total = sum(float(item.y[index]) for item in spec.series if index < len(item.y))
            totals.append(total)
        bad = []
        for total in totals:
            if not (abs(total - 1.0) <= 0.02 or abs(total - 100.0) <= 2.0):
                bad.append(total)
        if not bad:
            return []
        return [self._risk(
            "EXCLUSIVE_PARTS_DO_NOT_SUM_TO_WHOLE",
            "HIGH",
            "Exclusive composition values do not sum to approximately 1 or 100.",
            detail={"worst_total": float(max(bad, key=lambda item: min(abs(item - 1.0), abs(item - 100.0))))},
        )]

    def _simpson_risks(self, spec: ChartSpec) -> list[VisualRisk]:
        # When subgroup series and one explicit aggregate series share x, detect
        # trend reversals.  This does not decide which view is causally correct.
        aggregates = [item for item in spec.series if item.group.upper() == "AGGREGATE"]
        groups = [item for item in spec.series if item.group and item.group.upper() != "AGGREGATE"]
        if len(aggregates) != 1 or len(groups) < 2:
            return []
        aggregate = aggregates[0]
        aggregate_sign = _sign(_linear_slope(aggregate.x, aggregate.y))
        group_signs = [_sign(_linear_slope(item.x, item.y)) for item in groups]
        nonzero = [item for item in group_signs if item != 0]
        if not nonzero or aggregate_sign == 0:
            return []
        if len(nonzero) == len(groups) and len(set(nonzero)) == 1 and nonzero[0] == -aggregate_sign:
            return [self._risk(
                "SIMPSON_REVERSAL",
                "HIGH",
                "Aggregate trend reverses the direction seen in every supplied subgroup; aggregation/conditioning must be investigated.",
                series=(aggregate.series_id,) + tuple(item.series_id for item in groups),
            )]
        return []

    def _trend_findings(self, spec: ChartSpec, *, critical_extraction: bool) -> Tuple[TrendFinding, ...]:
        findings = []
        confidence_cap = float(spec.extraction_confidence) if spec.extracted_from_image else 1.0
        if critical_extraction:
            confidence_cap = min(confidence_cap, 0.49)
        for series in spec.series:
            slope = _linear_slope(
                [float(value) for value in series.x],
                [float(value) for value in series.y],
            )
            direction_sign = _sign(slope)
            direction = "INCREASING" if direction_sign > 0 else "DECREASING" if direction_sign < 0 else "FLAT_OR_UNRESOLVED"
            findings.append(TrendFinding(
                series_id=series.series_id,
                slope=slope,
                direction=direction,
                confidence_cap=confidence_cap,
                reason=(
                    "Trend is computed from extracted chart values; extraction confidence caps interpretation."
                    if spec.extracted_from_image
                    else "Trend is computed directly from structured chart values."
                ),
            ))
        return tuple(findings)

    def audit(self, spec: ChartSpec) -> VisualAuditReport:
        spec.validate()
        extraction_risks = self._extraction_risks(spec)
        risks = (
            extraction_risks
            + self._axis_risks(spec)
            + self._layout_risks(spec)
            + self._uncertainty_risks(spec)
            + self._window_risks(spec)
            + self._composition_risks(spec)
            + self._simpson_risks(spec)
        )
        # Stable order keeps audit receipts reproducible regardless of check order.
        risks = sorted(
            risks,
            key=lambda item: (item.code, item.affected_series, item.message),
        )
        critical_extraction = any(item.code == "LOW_EXTRACTION_CONFIDENCE" for item in risks)
        high_risk = any(item.severity in {"HIGH", "CRITICAL"} for item in risks)
        strong_claim_allowed = not critical_extraction and not high_risk
        status = (
            "UNVERIFIED_EXTRACTION"
            if critical_extraction
            else "HIGH_RISK_VISUALIZATION"
            if high_risk
            else "REVIEW_REQUIRED"
            if risks
            else "NO_DETECTED_VISUAL_RISK"
        )
        payload = {
            "figure_id": spec.figure_id,
            "chart_type": spec.chart_type,
            "x_axis": spec.x_axis,
            "y_axes": spec.y_axes,
            "series": spec.series,
            "caption": spec.caption,
            "source_locator": spec.source_locator,
            "extraction_confidence": spec.extraction_confidence,
            "extracted_from_image": spec.extracted_from_image,
            "width_px": spec.width_px,
            "height_px": spec.height_px,
            "inferential_claim": spec.inferential_claim,
            "exclusive_parts": spec.exclusive_parts,
            "metadata": dict(spec.metadata),
        }
        return VisualAuditReport(
            figure_id=spec.figure_id,
            spec_hash=_canonical_hash(payload),
            status=status,
            extraction_confidence=float(spec.extraction_confidence),
            risks=tuple(risks),
            trends=self._trend_findings(spec, critical_extraction=critical_extraction),
            high_risk=high_risk,
            strong_claim_allowed=strong_claim_allowed,
            intent_inference_allowed=False,
        )
