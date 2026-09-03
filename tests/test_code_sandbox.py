import pytest

from research_engine.code_sandbox import (
    NumericCodeSandbox,
    SandboxLimitExceeded,
    SandboxPolicy,
    SandboxViolation,
)


def test_numeric_sandbox_executes_deterministic_bounded_experiment():
    source = """
total = 0
for i in range(10):
    total += i * i
root = sqrt(total)
print(total)
"""
    first = NumericCodeSandbox().run(source)
    second = NumericCodeSandbox().run(source)
    assert first.code_sha256 == second.code_sha256
    assert first.outputs == second.outputs
    assert first.stdout == "285"
    assert first.outputs["total"] == 285
    assert first.outputs["root"] == pytest.approx(285 ** 0.5)
    assert first.deterministic is True
    assert first.network_allowed is False
    assert first.filesystem_allowed is False
    assert first.subprocess_allowed is False


def test_inputs_are_cleaned_and_can_drive_numeric_experiment():
    result = NumericCodeSandbox().run(
        "score = sum(values) / len(values)\nprint(round(score, 3))",
        inputs={"values": [1.0, 2.0, 6.0]},
    )
    assert result.outputs["score"] == pytest.approx(3.0)
    assert result.stdout == "3.0"


@pytest.mark.parametrize(
    "source",
    [
        "import os",
        "from pathlib import Path",
        "x = (1).__class__",
        "x = open('secret.txt')",
        "x = __import__('os')",
        "while True:\n    pass",
        "def f():\n    return 1",
        "x = [i for i in range(10)]",
        "x = lambda y: y",
        "try:\n    x = 1\nexcept:\n    x = 2",
        "with open('x') as f:\n    x = 1",
    ],
)
def test_unsafe_python_surfaces_are_rejected(source):
    with pytest.raises(SandboxViolation):
        NumericCodeSandbox().run(source)


def test_loop_operation_and_numeric_budgets_fail_closed():
    with pytest.raises(SandboxLimitExceeded, match="range too large|loop budget"):
        NumericCodeSandbox(
            SandboxPolicy(max_loop_iterations=10)
        ).run("x = 0\nfor i in range(11):\n    x += i")

    with pytest.raises(SandboxLimitExceeded, match="operation budget"):
        NumericCodeSandbox(
            SandboxPolicy(max_operations=20, max_loop_iterations=1_000)
        ).run("x = 0\nfor i in range(100):\n    x += 1")

    with pytest.raises(SandboxLimitExceeded, match="exponent"):
        NumericCodeSandbox().run("x = 2 ** 1001")


def test_nonfinite_and_reserved_inputs_are_rejected():
    with pytest.raises(SandboxViolation, match="non-finite"):
        NumericCodeSandbox().run("x = value", inputs={"value": float("nan")})
    with pytest.raises(SandboxViolation, match="reserved"):
        NumericCodeSandbox().run("x = 1", inputs={"open": 2})


def test_unknown_function_and_attribute_call_fail_closed():
    with pytest.raises(SandboxViolation, match="function not allowed"):
        NumericCodeSandbox().run("x = sorted([3, 2, 1])")
    with pytest.raises(SandboxViolation, match="direct calls"):
        NumericCodeSandbox().run("x = 'abc'.upper()")
