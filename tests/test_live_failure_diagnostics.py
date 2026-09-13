"""Actual failure serialization and privacy, without provider calls."""
import json
import subprocess

from scripts import run_live_zero_cost_gate as live
from scripts import run_hosted_live_gate as hosted
from utils import live_failure_diagnostics as diagnostics


def test_actual_public_failure_location_and_cause_survive_hosted_summary():
    try:
        try:
            live.run_live("PRIVATE_INVALID_MODE")
        except ValueError as cause:
            raise RuntimeError("PRIVATE_PROVIDER_BODY") from cause
    except RuntimeError as error:
        receipt = live._failure_receipt(
            ready={"depth_mode": "COMPANY"}, started=live.time.time(),
            failure_code="live_research_execution_failed", error=error,
        )
    summary = hosted.summarize({"COMPANY": {"passed": False, "receipt": receipt}})["COMPANY"]
    assert summary["passed"] is False
    assert summary["failure_code"] == "live_research_execution_failed"
    errors = summary["diagnostics"]["errors"]
    assert [row["kind"] for row in errors] == ["runtime_error", "value_error"]
    assert any(frame["module"] == "scripts.run_live_zero_cost_gate" for frame in errors[1]["frames"])
    assert "PRIVATE" not in json.dumps(summary)
    assert str(diagnostics.ROOT) not in json.dumps(summary)


def test_private_filename_exception_name_message_and_locals_are_not_serialized():
    private_error = type("PRIVATE_CLASS_NAME", (Exception,), {
        "__str__": lambda self: (_ for _ in ()).throw(AssertionError("must not format exception")),
    })
    try:
        # Fixed test code only: verifies that traceback filenames cannot carry
        # private content into the public receipt.
        exec(compile("secret = 'PRIVATE_LOCAL'\nraise error('PRIVATE_MESSAGE')",
                     "/PRIVATE_DIRECTORY/PRIVATE_SOURCE.py", "exec"), {"error": private_error})
    except Exception as error:
        result = diagnostics.exception_diagnostics(error)
    assert result["errors"][0]["kind"] == "other_error"
    assert "PRIVATE" not in json.dumps(result)
    assert all(frame["module"] in diagnostics._public_modules().values()
               for frame in result["errors"][0]["frames"])


def test_hosted_boundary_discards_forged_diagnostics_and_arbitrary_failure_code():
    record = {"passed": False, "failure_code": "PRIVATE_PROVIDER_PAYLOAD", "diagnostics": {
        "secret": "PRIVATE_KEY", "errors": [{"kind": "PRIVATE_CLASS", "message": "PRIVATE_MESSAGE",
            "frames": [{"module": "PRIVATE_FILENAME", "line": 1},
                       {"module": "scripts.run_live_zero_cost_gate", "line": True},
                       {"module": "scripts.run_live_zero_cost_gate", "line": 0},
                       {"module": "scripts.run_live_zero_cost_gate", "line": 1_000_001}]}]}}
    clean = hosted.summarize({"COMPANY": {"passed": False, "receipt": record}})["COMPANY"]
    assert "failure_code" not in clean
    assert clean["diagnostics"] == {"schema": 1, "errors": [{"kind": "other_error", "frames": []}]}
    assert "PRIVATE" not in json.dumps(clean)


def test_cycles_and_long_frame_payloads_are_bounded():
    error = RuntimeError("PRIVATE")
    error.__cause__ = error
    assert len(diagnostics.exception_diagnostics(error)["errors"]) == 1
    frame = {"module": "scripts.run_live_zero_cost_gate", "line": 10}
    result = diagnostics.sanitize_diagnostics({"errors": [
        {"kind": "runtime_error", "frames": [frame] * 1000}] * 1000})
    assert len(result["errors"]) == 3
    assert all(len(row["frames"]) == 8 for row in result["errors"])


def test_missing_inventory_keeps_failure_kind_without_exposing_paths(monkeypatch):
    diagnostics._public_modules.cache_clear()
    try:
        with monkeypatch.context() as patcher:
            def unavailable(*args, **kwargs):
                raise subprocess.TimeoutExpired("PRIVATE_COMMAND", 3)
            patcher.setattr(diagnostics.subprocess, "run", unavailable)
            assert diagnostics.exception_diagnostics(TypeError("PRIVATE")) == {
                "schema": 1, "errors": [{"kind": "type_error", "frames": []}]}
    finally:
        diagnostics._public_modules.cache_clear()


def test_unknown_or_malformed_diagnostics_have_no_public_payload():
    for raw in (None, "PRIVATE", {"errors": "PRIVATE"}, {"errors": [None, "PRIVATE"]}):
        assert diagnostics.sanitize_diagnostics(raw) == {"schema": 1, "errors": []}
