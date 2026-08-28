import math

import pytest

from research_engine.visual_science import (
    AxisSpec,
    ChartSeries,
    ChartSpec,
    VisualScienceEngine,
)


def axis(axis_id="y", minimum=0.0, maximum=10.0, **kwargs):
    return AxisSpec(
        axis_id=axis_id,
        label=kwargs.pop("label", axis_id),
        minimum=minimum,
        maximum=maximum,
        **kwargs,
    )


def series(series_id="s1", x=(0.0, 1.0, 2.0), y=(1.0, 2.0, 3.0), **kwargs):
    return ChartSeries(
        series_id=series_id,
        label=kwargs.pop("label", series_id),
        x=tuple(x),
        y=tuple(y),
        **kwargs,
    )


def spec(*, chart_type="line", y_axes=None, series_values=None, **kwargs):
    return ChartSpec(
        figure_id=kwargs.pop("figure_id", "fig-1"),
        chart_type=chart_type,
        x_axis=kwargs.pop("x_axis", axis("x", 0.0, 10.0)),
        y_axes=tuple(y_axes or (axis(),)),
        series=tuple(series_values or (series(),)),
        **kwargs,
    )


def codes(report):
    return {item.code for item in report.risks}


def test_clean_structured_line_has_computed_trend_and_no_detected_risk():
    report = VisualScienceEngine().audit(spec())
    assert report.status == "NO_DETECTED_VISUAL_RISK"
    assert report.risks == ()
    assert report.high_risk is False
    assert report.strong_claim_allowed is True
    assert report.intent_inference_allowed is False
    assert report.trends[0].direction == "INCREASING"
    assert report.trends[0].slope == pytest.approx(1.0)
    assert report.trends[0].confidence_cap == 1.0


def test_low_confidence_image_extraction_fails_closed_and_caps_reasoning():
    report = VisualScienceEngine().audit(
        spec(extracted_from_image=True, extraction_confidence=0.60)
    )
    assert report.status == "UNVERIFIED_EXTRACTION"
    assert "LOW_EXTRACTION_CONFIDENCE" in codes(report)
    assert report.high_risk is True
    assert report.strong_claim_allowed is False
    assert report.trends[0].confidence_cap <= 0.49


def test_medium_confidence_image_is_usable_but_explicitly_limited():
    report = VisualScienceEngine().audit(
        spec(extracted_from_image=True, extraction_confidence=0.90)
    )
    assert report.status == "REVIEW_REQUIRED"
    assert "LIMITED_EXTRACTION_CONFIDENCE" in codes(report)
    assert report.high_risk is False
    assert report.trends[0].confidence_cap == pytest.approx(0.90)


def test_bar_chart_with_nonzero_baseline_is_high_risk():
    report = VisualScienceEngine().audit(
        spec(
            chart_type="bar",
            y_axes=(axis("y", 90.0, 110.0),),
            series_values=(series(y=(99.0, 100.0, 101.0)),),
        )
    )
    assert "TRUNCATED_BAR_BASELINE" in codes(report)
    assert report.status == "HIGH_RISK_VISUALIZATION"
    assert report.strong_claim_allowed is False


def test_undisclosed_log_scale_and_reversed_axis_are_detected():
    report = VisualScienceEngine().audit(
        spec(
            y_axes=(
                axis(
                    "y",
                    1.0,
                    1000.0,
                    scale="log10",
                    scale_disclosed=False,
                    direction="reversed",
                    direction_disclosed=False,
                ),
            ),
        )
    )
    assert "UNDISCLOSED_LOG_SCALE" in codes(report)
    assert "UNDISCLOSED_REVERSED_AXIS" in codes(report)
    assert report.high_risk is True


def test_dual_axis_strong_alignment_is_reported_as_scale_dependent_not_causal():
    report = VisualScienceEngine().audit(
        spec(
            y_axes=(axis("left", 0.0, 10.0), axis("right", 0.0, 1000.0)),
            series_values=(
                series("a", y=(1.0, 2.0, 3.0), y_axis_id="left"),
                series("b", y=(100.0, 200.0, 300.0), y_axis_id="right"),
            ),
        )
    )
    assert "DUAL_AXIS_CORRELATION_RISK" in codes(report)
    risk = next(item for item in report.risks if item.code == "DUAL_AXIS_CORRELATION_RISK")
    assert risk.quantitative_detail["pearson_r"] == pytest.approx(1.0)
    assert "not causal evidence" in risk.message


def test_inferential_chart_without_uncertainty_is_flagged():
    report = VisualScienceEngine().audit(spec(inferential_claim=True))
    assert "MISSING_UNCERTAINTY" in codes(report)
    assert report.status == "REVIEW_REQUIRED"


def test_inferential_chart_with_uncertainty_does_not_trigger_missing_uncertainty():
    report = VisualScienceEngine().audit(
        spec(
            inferential_claim=True,
            series_values=(series(uncertainty=(0.1, 0.1, 0.1)),),
        )
    )
    assert "MISSING_UNCERTAINTY" not in codes(report)


def test_small_display_window_that_reverses_full_trend_is_high_risk():
    report = VisualScienceEngine().audit(
        spec(
            x_axis=axis("x", 0.0, 10.0),
            series_values=(
                series(
                    x=(0.0, 1.0, 2.0),
                    y=(3.0, 2.0, 1.0),
                    full_x=tuple(float(item) for item in range(11)),
                    full_y=tuple(float(item) for item in range(11)),
                ),
            ),
        )
    )
    assert "CHERRY_PICKED_WINDOW_SIGN_FLIP" in codes(report)
    risk = next(item for item in report.risks if item.code == "CHERRY_PICKED_WINDOW_SIGN_FLIP")
    assert risk.quantitative_detail["displayed_range_fraction"] == pytest.approx(0.2)
    assert report.high_risk is True


def test_exclusive_composition_must_sum_to_whole():
    report = VisualScienceEngine().audit(
        spec(
            chart_type="pie",
            exclusive_parts=True,
            series_values=(
                series("a", x=(0.0,), y=(60.0,)),
                series("b", x=(0.0,), y=(55.0,)),
            ),
        )
    )
    assert "EXCLUSIVE_PARTS_DO_NOT_SUM_TO_WHOLE" in codes(report)
    assert report.high_risk is True


def test_simpson_reversal_between_aggregate_and_all_subgroups_is_detected():
    report = VisualScienceEngine().audit(
        spec(
            series_values=(
                series("agg", y=(1.0, 2.0, 3.0), group="AGGREGATE"),
                series("g1", y=(3.0, 2.0, 1.0), group="A"),
                series("g2", y=(6.0, 5.0, 4.0), group="B"),
            ),
        )
    )
    assert "SIMPSON_REVERSAL" in codes(report)
    assert report.high_risk is True


def test_extreme_aspect_ratio_warns_about_slope_perception():
    report = VisualScienceEngine().audit(spec(width_px=5000, height_px=500))
    assert "EXTREME_ASPECT_RATIO" in codes(report)


def test_validation_rejects_nonfinite_values_and_unknown_axis_reference():
    with pytest.raises(ValueError, match="finite"):
        VisualScienceEngine().audit(
            spec(series_values=(series(y=(1.0, math.inf, 3.0)),))
        )
    with pytest.raises(ValueError, match="unknown y axis"):
        VisualScienceEngine().audit(
            spec(series_values=(series(y_axis_id="missing"),))
        )


def test_log_axis_requires_positive_limits():
    with pytest.raises(ValueError, match="positive"):
        VisualScienceEngine().audit(
            spec(y_axes=(axis("y", 0.0, 10.0, scale="log10"),))
        )


def test_risk_does_not_authorize_inference_of_deceptive_intent():
    report = VisualScienceEngine().audit(
        spec(
            chart_type="bar",
            y_axes=(axis("y", 99.0, 101.0),),
            series_values=(series(y=(99.5, 100.0, 100.5)),),
        )
    )
    assert report.high_risk is True
    assert report.intent_inference_allowed is False


def test_same_input_produces_same_hash_and_risk_order():
    engine = VisualScienceEngine()
    item = spec(
        chart_type="bar",
        y_axes=(axis("y", 90.0, 110.0),),
        series_values=(series(y=(99.0, 100.0, 101.0)),),
        inferential_claim=True,
    )
    first = engine.audit(item)
    second = engine.audit(item)
    assert first.spec_hash == second.spec_hash
    assert [risk.code for risk in first.risks] == [risk.code for risk in second.risks]
