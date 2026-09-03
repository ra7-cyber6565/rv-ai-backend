import hashlib

import pytest

from research_engine.triple_implementation import (
    TripleImplementationEngine,
    TripleImplementationSpec,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _spec(
    implementation_id: str,
    runner_id: str,
    family: str,
    digest_label: str,
    runner,
):
    return TripleImplementationSpec(
        implementation_id=implementation_id,
        runner_id=runner_id,
        implementation_family=family,
        code_digest=_digest(digest_label),
        runner=runner,
    )


def test_triple_confirmation_requires_all_three_and_all_pairwise_metrics():
    seen = []

    def runner(value, *, mutate=False):
        def execute(protocol):
            seen.append((value, dict(protocol)))
            if mutate:
                protocol["mutated_by_runner"] = value
            return {"metrics": {"effect": value, "n": 100}}
        return execute

    engine = TripleImplementationEngine([
        _spec("I1", "runner-python", "python", "impl-python", runner(0.50, mutate=True)),
        _spec("I2", "runner-rust", "rust", "impl-rust", runner(0.51)),
        _spec("I3", "runner-julia", "julia", "impl-julia", runner(0.49)),
    ])
    report = engine.run(
        {"protocol_id": "P1", "dataset_commitment": "abc123"},
        metric_tolerances={"effect": 0.02, "n": 0},
    )

    assert report.triple_confirmed is True
    assert report.execution_complete is True
    assert report.independence_structure_satisfied is True
    assert report.truth_proven is False
    assert report.agreement_is_not_truth is True
    assert report.reasons == ()
    assert len(report.results) == 3
    assert len(report.comparisons) == 6
    assert all(item.passed for item in report.comparisons)
    assert len({item.runner_id for item in report.results}) == 3
    assert len({item.code_digest for item in report.results}) == 3
    assert len({item.implementation_family for item in report.results}) == 3
    # Each runner receives an isolated copy of the same frozen protocol.
    assert all("mutated_by_runner" not in packet for _, packet in seen)
    assert len(report.protocol_hash) == 64
    assert len(report.manifest_hash) == 64
    assert len(report.report_hash) == 64


def test_all_pairs_check_catches_disagreement_hidden_by_reference_only_comparison():
    # A↔B and A↔C are each inside 0.15, but B↔C differs by 0.20.
    def runner(value):
        return lambda protocol: {"metrics": {"effect": value}}

    engine = TripleImplementationEngine([
        _spec("I1", "r1", "family-a", "a", runner(0.0)),
        _spec("I2", "r2", "family-b", "b", runner(0.1)),
        _spec("I3", "r3", "family-c", "c", runner(-0.1)),
    ])
    report = engine.run(
        {"protocol_id": "P2"},
        metric_tolerances={"effect": 0.15},
    )
    assert report.triple_confirmed is False
    assert any(
        item.left_id == "I2"
        and item.right_id == "I3"
        and item.passed is False
        for item in report.comparisons
    )
    assert "differs beyond tolerance" in " ".join(report.reasons)


def test_third_implementation_failure_or_missing_metric_blocks_confirmation():
    good = lambda value: (
        lambda protocol: {"metrics": {"effect": value, "n": 100}}
    )

    def failed(protocol):
        raise RuntimeError("third implementation crashed")

    failed_report = TripleImplementationEngine([
        _spec("I1", "r1", "f1", "a", good(0.5)),
        _spec("I2", "r2", "f2", "b", good(0.5)),
        _spec("I3", "r3", "f3", "c", failed),
    ]).run({"protocol_id": "P3"}, metric_tolerances={"effect": 0.01, "n": 0})
    assert failed_report.execution_complete is False
    assert failed_report.triple_confirmed is False
    assert "RuntimeError" in " ".join(failed_report.reasons)

    missing = lambda protocol: {"metrics": {"effect": 0.5}}
    missing_report = TripleImplementationEngine([
        _spec("I1", "r1", "f1", "a", good(0.5)),
        _spec("I2", "r2", "f2", "b", good(0.5)),
        _spec("I3", "r3", "f3", "c", missing),
    ]).run({"protocol_id": "P4"}, metric_tolerances={"effect": 0.01, "n": 0})
    assert missing_report.triple_confirmed is False
    assert "missing required metrics" in " ".join(missing_report.reasons)


def test_precommitted_identity_cannot_be_spoofed_by_runner_output():
    def spoof(protocol):
        return {
            "code_digest": _digest("different-code"),
            "metrics": {"effect": 0.5},
        }

    normal = lambda protocol: {"metrics": {"effect": 0.5}}
    report = TripleImplementationEngine([
        _spec("I1", "r1", "f1", "a", spoof),
        _spec("I2", "r2", "f2", "b", normal),
        _spec("I3", "r3", "f3", "c", normal),
    ]).run({"protocol_id": "P5"}, metric_tolerances={"effect": 0.01})
    assert report.triple_confirmed is False
    assert "override pre-committed code_digest" in " ".join(report.reasons)


@pytest.mark.parametrize(
    "specs, error_fragment",
    [
        (
            [
                _spec("I1", "r1", "f1", "a", lambda p: {"metrics": {"x": 1}}),
                _spec("I2", "r2", "f2", "b", lambda p: {"metrics": {"x": 1}}),
            ],
            "exactly three",
        ),
        (
            [
                _spec("I1", "same", "f1", "a", lambda p: {"metrics": {"x": 1}}),
                _spec("I2", "same", "f2", "b", lambda p: {"metrics": {"x": 1}}),
                _spec("I3", "r3", "f3", "c", lambda p: {"metrics": {"x": 1}}),
            ],
            "runner_id values must be distinct",
        ),
        (
            [
                _spec("I1", "r1", "same-family", "a", lambda p: {"metrics": {"x": 1}}),
                _spec("I2", "r2", "same-family", "b", lambda p: {"metrics": {"x": 1}}),
                _spec("I3", "r3", "f3", "c", lambda p: {"metrics": {"x": 1}}),
            ],
            "implementation_family values must be distinct",
        ),
        (
            [
                _spec("I1", "r1", "f1", "same", lambda p: {"metrics": {"x": 1}}),
                _spec("I2", "r2", "f2", "same", lambda p: {"metrics": {"x": 1}}),
                _spec("I3", "r3", "f3", "c", lambda p: {"metrics": {"x": 1}}),
            ],
            "code_digest values must be distinct",
        ),
    ],
)
def test_invalid_triple_identity_configuration_fails_closed(specs, error_fragment):
    with pytest.raises(ValueError, match=error_fragment):
        TripleImplementationEngine(specs)


def test_manifest_and_protocol_hashes_are_deterministic_and_order_independent():
    runner = lambda protocol: {"metrics": {"effect": 0.5}}
    specs = [
        _spec("I1", "r1", "f1", "a", runner),
        _spec("I2", "r2", "f2", "b", runner),
        _spec("I3", "r3", "f3", "c", runner),
    ]
    first = TripleImplementationEngine(specs)
    second = TripleImplementationEngine(list(reversed(specs)))
    assert first.manifest_hash == second.manifest_hash

    report_a = first.run(
        {"b": 2, "a": 1},
        metric_tolerances={"effect": 0.01},
    )
    report_b = second.run(
        {"a": 1, "b": 2},
        metric_tolerances={"effect": 0.01},
    )
    assert report_a.protocol_hash == report_b.protocol_hash
    assert report_a.report_hash == report_b.report_hash


@pytest.mark.parametrize("bad_tolerance", [-0.1, float("inf"), float("nan")])
def test_invalid_metric_tolerance_is_rejected(bad_tolerance):
    runner = lambda protocol: {"metrics": {"effect": 0.5}}
    engine = TripleImplementationEngine([
        _spec("I1", "r1", "f1", "a", runner),
        _spec("I2", "r2", "f2", "b", runner),
        _spec("I3", "r3", "f3", "c", runner),
    ])
    with pytest.raises(ValueError, match="invalid tolerance"):
        engine.run(
            {"protocol_id": "P6"},
            metric_tolerances={"effect": bad_tolerance},
        )


def test_nonfinite_runner_metric_fails_closed_instead_of_entering_agreement():
    good = lambda protocol: {"metrics": {"effect": 0.5}}
    bad = lambda protocol: {"metrics": {"effect": float("nan")}}
    report = TripleImplementationEngine([
        _spec("I1", "r1", "f1", "a", good),
        _spec("I2", "r2", "f2", "b", good),
        _spec("I3", "r3", "f3", "c", bad),
    ]).run({"protocol_id": "P7"}, metric_tolerances={"effect": 0.01})
    assert report.triple_confirmed is False
    assert "not finite" in " ".join(report.reasons)
