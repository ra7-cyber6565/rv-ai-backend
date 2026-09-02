import pytest

from research_engine.unknown_unknown_hunter import (
    AnomalyProbe,
    AssumptionProbe,
    CoverageDimension,
    hunt_unknown_unknowns,
)


def test_hunter_surfaces_coverage_assumption_anomaly_and_interaction_blind_spots():
    report = hunt_unknown_unknowns(
        coverage_dimensions=[
            CoverageDimension("market_regime", ("trend", "range", "crash"), ("trend", "range")),
            CoverageDimension("liquidity", ("high", "low"), ("high",)),
        ],
        assumptions=[
            AssumptionProbe("A1", "spread remains bounded during execution", False, "measure stress spread"),
            AssumptionProbe("A2", "timestamps are synchronized", True, ""),
        ],
        anomalies=[
            AnomalyProbe("X1", "unexpected tail loss cluster", 0.9, ()),
            AnomalyProbe("X2", "known holiday volume drop", 0.2, ("calendar_model",)),
        ],
    )
    kinds = [item.kind for item in report.blind_spots]
    assert report.coverage_gap_count == 2
    assert report.untested_assumption_count == 2
    assert report.unexplained_anomaly_count == 1
    assert report.interaction_probe_count == 1
    assert kinds.count("COVERAGE_GAP") == 2
    assert "UNCOVERED_INTERACTION" in kinds
    assert report.blind_spots_found is True
    assert report.unknown_unknown_proven is False
    assert report.unknown_unknown_exhaustively_ruled_out is False


def test_fully_covered_inputs_do_not_fake_claim_unknown_unknowns_are_gone():
    report = hunt_unknown_unknowns(
        coverage_dimensions=[CoverageDimension("regime", ("a", "b"), ("a", "b"))],
        assumptions=[AssumptionProbe("A1", "explicit bounded assumption", True, "reject if metric > 1")],
        anomalies=[AnomalyProbe("X1", "explained observation", 0.1, ("H1",))],
    )
    assert report.blind_spots == ()
    assert report.blind_spots_found is False
    assert report.unknown_unknown_proven is False
    assert report.unknown_unknown_exhaustively_ruled_out is False


def test_observed_state_outside_declared_universe_fails_closed():
    with pytest.raises(ValueError, match="undeclared states"):
        hunt_unknown_unknowns(
            coverage_dimensions=[CoverageDimension("regime", ("known",), ("known", "mystery"))]
        )


def test_duplicate_ids_fail_closed():
    with pytest.raises(ValueError, match="dimension_id values must be unique"):
        hunt_unknown_unknowns(
            coverage_dimensions=[
                CoverageDimension("same", ("a",), ()),
                CoverageDimension("same", ("a",), ()),
            ]
        )
    with pytest.raises(ValueError, match="assumption_id values must be unique"):
        hunt_unknown_unknowns(
            assumptions=[
                AssumptionProbe("A", "first assumption", False),
                AssumptionProbe("A", "second assumption", False),
            ]
        )


@pytest.mark.parametrize("severity", [-0.01, 1.01, float("nan"), float("inf")])
def test_anomaly_severity_must_be_finite_unit_interval(severity):
    with pytest.raises(ValueError, match="severity"):
        hunt_unknown_unknowns(
            anomalies=[AnomalyProbe("X", "bounded anomaly description", severity)]
        )


def test_report_hash_is_deterministic_under_input_order_changes():
    dimensions = [
        CoverageDimension("b", ("x", "y"), ("x",)),
        CoverageDimension("a", ("x", "y"), ("x",)),
    ]
    assumptions = [
        AssumptionProbe("B", "second assumption", False),
        AssumptionProbe("A", "first assumption", False),
    ]
    first = hunt_unknown_unknowns(coverage_dimensions=dimensions, assumptions=assumptions)
    second = hunt_unknown_unknowns(
        coverage_dimensions=list(reversed(dimensions)),
        assumptions=list(reversed(assumptions)),
    )
    assert first.report_hash == second.report_hash
    assert first.blind_spots == second.blind_spots


def test_uncovered_interaction_generation_is_bounded():
    dimensions = [
        CoverageDimension(f"d{i}", ("seen", "missing"), ("seen",))
        for i in range(40)
    ]
    report = hunt_unknown_unknowns(coverage_dimensions=dimensions)
    assert report.interaction_probe_count == 256
    assert sum(1 for item in report.blind_spots if item.kind == "UNCOVERED_INTERACTION") == 256
