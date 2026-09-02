"""Adversarial/offline tests for #40 Triple Independent Implementation.

These tests do not require R to be installed.  A runner fixture exercises the
real R backend protocol and generated-code boundary deterministically; a separate
test proves that a genuinely missing R runtime fails closed rather than being
simulated or silently replaced.
"""
from __future__ import annotations

from types import SimpleNamespace

from research_engine.advanced_discovery import SafeNumericExecutor
from research_engine.triple_implementation import (
    DecimalMathBackend,
    RScriptFormulaBackend,
    TripleIndependentImplementation,
    TripleImplementationPolicy,
)


class _Runner:
    def __init__(self, stdout: str = "5", returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return SimpleNamespace(
            stdout=self.stdout,
            stderr=self.stderr,
            returncode=self.returncode,
        )


def _engine(stdout: str = "5"):
    runner = _Runner(stdout=stdout)
    r = RScriptFormulaBackend(executable="Rscript-test", runner=runner)
    return TripleIndependentImplementation(SafeNumericExecutor(), r_backend=r), runner


def _task(expression="sqrt(x ** 2 + y ** 2)", variables=None, **extra):
    row = {
        "task_id": "pythagoras",
        "expression": expression,
        "variables": variables or {"x": 3, "y": 4},
    }
    row.update(extra)
    return row


def test_three_independent_paths_must_all_agree():
    engine, runner = _engine("5")
    report = engine.run([_task()])

    assert report["status"] == "TRIPLE_AGREEMENT"
    assert report["all_requested_tasks_agree"] is True
    row = report["results"][0]
    assert row["verified"] is True
    assert row["pairwise_agreement"] == {
        "python_vs_r": True,
        "python_vs_math": True,
        "r_vs_math": True,
    }
    assert [x["backend"] for x in row["implementations"]] == [
        "python_sandbox", "rscript", "independent_decimal_math",
    ]
    argv, kwargs = runner.calls[0]
    assert argv[:3] == ["Rscript-test", "--vanilla", "-e"]
    assert kwargs["shell"] is False
    assert "sqrt(" in argv[3]
    assert report["maturity_proof"]["real_r_runtime_observed_this_run"] is True
    assert report["maturity_proof"]["hardware_validation"] is False
    assert report["maturity_proof"]["live_independent_validation"] is False


def test_two_out_of_three_is_not_majority_vote():
    engine, _ = _engine("5.25")
    report = engine.run([_task()])

    assert report["status"] == "DISAGREEMENT"
    assert report["all_requested_tasks_agree"] is False
    row = report["results"][0]
    assert row["verified"] is False
    assert row["pairwise_agreement"]["python_vs_math"] is True
    assert row["pairwise_agreement"]["python_vs_r"] is False
    assert row["pairwise_agreement"]["r_vs_math"] is False
    assert "majority" in row["note"].lower()


def test_missing_r_runtime_fails_closed():
    r = RScriptFormulaBackend(executable="")
    engine = TripleIndependentImplementation(SafeNumericExecutor(), r_backend=r)
    report = engine.run([_task()])

    assert report["status"] == "INCOMPLETE"
    assert report["all_requested_tasks_agree"] is False
    row = report["results"][0]
    assert row["verified"] is False
    assert "rscript" in row["missing_or_failed_backends"]
    rrow = next(x for x in row["implementations"] if x["backend"] == "rscript")
    assert rrow["error"] == "rscript_not_found"
    assert report["maturity_proof"]["real_r_runtime_observed_this_run"] is False


def test_malicious_code_is_rejected_before_r_runner_is_called():
    engine, runner = _engine("1")
    payloads = (
        "__import__('os').system('id')",
        "open('/etc/passwd').read()",
        "(1).__class__",
        "[x for x in range(10)]",
        "x if x else 0",
    )
    for index, payload in enumerate(payloads):
        report = engine.run([{
            "task_id": f"mal{index}",
            "expression": payload,
            "variables": {"x": 1},
        }])
        assert report["status"] == "INCOMPLETE"
        row = report["results"][0]
        assert row["status"] == "INVALID_TASK"
        assert row["verified"] is False
    assert runner.calls == []


def test_nonfinite_and_oversized_inputs_fail_validation_before_execution():
    engine, runner = _engine("1")
    for value in (float("inf"), float("nan"), 1e30):
        report = engine.run([_task(expression="x + 1", variables={"x": value})])
        assert report["results"][0]["status"] == "INVALID_TASK"
        assert report["results"][0]["verified"] is False
    assert runner.calls == []


def test_r_protocol_never_surfaces_raw_stderr_or_provider_details():
    runner = _Runner(stdout="not-a-number", returncode=0, stderr="SECRET_TOKEN=/tmp/private trace")
    engine = TripleIndependentImplementation(
        SafeNumericExecutor(),
        r_backend=RScriptFormulaBackend(executable="Rscript-test", runner=runner),
    )
    report = engine.run([_task()])
    text = repr(report)

    assert report["status"] == "INCOMPLETE"
    rrow = next(x for x in report["results"][0]["implementations"] if x["backend"] == "rscript")
    assert rrow["error"] == "rscript_protocol_error"
    assert "SECRET_TOKEN" not in text
    assert "/tmp/private" not in text


def test_wrong_python_backend_is_detected_even_when_r_and_math_agree():
    class WrongPython:
        def evaluate(self, expression, variables):
            return {"ok": True, "value": 6.0}

    runner = _Runner(stdout="5")
    engine = TripleIndependentImplementation(
        WrongPython(),
        r_backend=RScriptFormulaBackend(executable="Rscript-test", runner=runner),
    )
    report = engine.run([_task()])
    row = report["results"][0]

    assert report["status"] == "DISAGREEMENT"
    assert row["pairwise_agreement"]["r_vs_math"] is True
    assert row["pairwise_agreement"]["python_vs_r"] is False
    assert row["verified"] is False


def test_tolerance_does_not_hide_large_mismatch():
    engine, _ = _engine("5.0000005")
    strict = engine.run([_task(abs_tolerance=1e-12, rel_tolerance=1e-12)])
    assert strict["status"] == "DISAGREEMENT"

    engine2, _ = _engine("5.0000000005")
    tolerant = engine2.run([_task(abs_tolerance=1e-8, rel_tolerance=1e-8)])
    assert tolerant["status"] == "TRIPLE_AGREEMENT"


def test_too_many_tasks_fails_closed_without_running_backends():
    policy = TripleImplementationPolicy(max_tasks=2)
    runner = _Runner(stdout="2")
    engine = TripleIndependentImplementation(
        SafeNumericExecutor(), policy=policy,
        r_backend=RScriptFormulaBackend(policy, executable="Rscript-test", runner=runner),
        math_backend=DecimalMathBackend(policy),
    )
    report = engine.run([
        _task(expression="x + 1", variables={"x": 1}),
        {**_task(expression="x + 1", variables={"x": 1}), "task_id": "second"},
        {**_task(expression="x + 1", variables={"x": 1}), "task_id": "third"},
    ])

    assert report["status"] == "INVALID_TASK_SET"
    assert report["all_requested_tasks_agree"] is False
    assert runner.calls == []


def test_non_integer_or_dynamic_power_is_rejected_for_cross_language_semantics():
    engine, runner = _engine("2")
    for expression, variables in (
        ("x ** y", {"x": 2, "y": 3}),
        ("x ** 0.5", {"x": 4}),
        ("x ** 13", {"x": 2}),
    ):
        report = engine.run([_task(expression=expression, variables=variables)])
        assert report["results"][0]["status"] == "INVALID_TASK"
    assert runner.calls == []


def test_run_from_verification_is_fail_closed_and_deterministic():
    engine, _ = _engine("5")
    verification = {"data_for_verification": {"triple_implementation_tasks": [_task()]}}
    first = engine.run_from_verification(verification)

    engine2, _ = _engine("5")
    second = engine2.run_from_verification(verification)
    assert first == second

    bad = engine.run_from_verification({"triple_implementation_tasks": {"expression": "1+1"}})
    assert bad["status"] == "INVALID_TASK_SET"
    assert bad["all_requested_tasks_agree"] is False


def test_no_tasks_is_honest_not_a_vacuous_pass():
    engine, _ = _engine("0")
    report = engine.run([])
    assert report["status"] == "NO_TASKS"
    assert report["tasks_triple_agreed"] == 0
    assert report["all_requested_tasks_agree"] is False
