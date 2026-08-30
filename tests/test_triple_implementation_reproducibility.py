import hashlib

from research_engine.triple_implementation import (
    TripleImplementationEngine,
    TripleImplementationSpec,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _spec(index: int, runner):
    return TripleImplementationSpec(
        implementation_id=f"I{index}",
        runner_id=f"runner-{index}",
        implementation_family=f"family-{index}",
        code_digest=_digest(f"implementation-{index}"),
        runner=runner,
    )


def test_each_implementation_executes_twice_before_triple_confirmation():
    calls = {1: 0, 2: 0, 3: 0}

    def runner(index, value):
        def execute(protocol):
            calls[index] += 1
            return {"metrics": {"effect": value, "n": 100}}
        return execute

    report = TripleImplementationEngine([
        _spec(1, runner(1, 0.50)),
        _spec(2, runner(2, 0.51)),
        _spec(3, runner(3, 0.49)),
    ]).run(
        {"protocol_id": "repeat-check", "seed": 7},
        metric_tolerances={"effect": 0.02, "n": 0.0},
    )

    assert report.triple_confirmed is True
    assert calls == {1: 2, 2: 2, 3: 2}


def test_internally_nondeterministic_path_cannot_hide_behind_cross_path_tolerance():
    counter = {"value": 0}

    def nondeterministic(protocol):
        counter["value"] += 1
        # Both values remain close enough to the other implementations that a
        # one-shot all-pairs comparison would pass. Repeated execution must block.
        value = 0.500 if counter["value"] % 2 else 0.501
        return {"metrics": {"effect": value}}

    stable = lambda value: (
        lambda protocol: {"metrics": {"effect": value}}
    )
    report = TripleImplementationEngine([
        _spec(1, nondeterministic),
        _spec(2, stable(0.5005)),
        _spec(3, stable(0.5007)),
    ]).run(
        {"protocol_id": "nondeterminism-attack", "seed": 11},
        metric_tolerances={"effect": 0.01},
    )

    assert report.triple_confirmed is False
    assert report.execution_complete is False
    assert any(
        "not reproducible across repeated execution" in reason
        for reason in report.reasons
    )
    failed = {item.implementation_id: item for item in report.results}
    assert failed["I1"].error
    assert failed["I1"].metrics == {}


def test_mutation_in_first_execution_cannot_contaminate_second_or_other_paths():
    seen = []

    def mutator(protocol):
        seen.append(dict(protocol))
        protocol["poison"] = len(seen)
        return {"metrics": {"effect": 1.0}}

    stable = lambda protocol: {"metrics": {"effect": 1.0}}
    original = {"protocol_id": "isolation", "locked": {"x": 1}}
    report = TripleImplementationEngine([
        _spec(1, mutator),
        _spec(2, stable),
        _spec(3, stable),
    ]).run(original, metric_tolerances={"effect": 0.0})

    assert report.triple_confirmed is True
    assert len(seen) == 2
    assert all("poison" not in packet for packet in seen)
    assert original == {"protocol_id": "isolation", "locked": {"x": 1}}
