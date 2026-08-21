"""Regression tests for the strict local foundation-gate runner."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import run_foundation_gate as gate


def test_safe_env_forces_offline_zero_cost(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "should-not-survive")
    monkeypatch.setenv("GROQ_API_KEY", "should-not-survive")
    monkeypatch.setenv("OPENROUTER_API_KEY", "should-not-survive")
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    monkeypatch.setenv("CLOUD_ARCHIVE_PROVIDER", "google_drive")
    monkeypatch.setenv("GOOGLE_DRIVE_RCLONE_REMOTE", "private-remote")
    monkeypatch.setenv("TERABOX_CLIENT_SECRET", "secret")
    monkeypatch.setenv("INFINITY_ADMIN_TOKEN", "admin-secret-that-must-not-survive")
    monkeypatch.setenv("INFINITY_DATA_ROOT", str(tmp_path))

    env = gate._safe_env()

    assert env["ZERO_COST_ONLY"] == "true"
    assert env["GEMINI_API_KEY"] == ""
    assert env["GEMINI_ZERO_COST_CONFIRMED"] == "false"
    assert env["GROQ_API_KEY"] == ""
    assert env["GROQ_ZERO_COST_CONFIRMED"] == "false"
    assert env["OPENROUTER_API_KEY"] == ""
    assert env["OPENROUTER_MODEL"] == "openrouter/free"
    assert env["OLLAMA_ENABLED"] == "false"
    assert env["CLOUD_ARCHIVE_PROVIDER"] == "none"
    assert env["GOOGLE_DRIVE_RCLONE_REMOTE"] == ""
    assert env["TERABOX_CLIENT_SECRET"] == ""
    assert env["INFINITY_ADMIN_TOKEN"] == ""
    assert env["INFINITY_OFFLINE_TEST"] == "true"


def test_default_stage_plan_contains_real_release_gates():
    plan = gate.build_stage_plan("python")
    names = [name for name, _ in plan]

    assert names[0] == "compileall"
    assert "focused_pytest" in names
    assert "all_pytest" in names
    assert "core_regression" in names
    assert "provider_bypass_audit" in names
    assert "architecture_audit" in names
    assert "benchmark_superconductivity_v2" in names

    all_pytest = next(command for name, command in plan if name == "all_pytest")
    assert all_pytest == ["python", "-m", "pytest", "-q", "tests"]

    focused_command = next(command for name, command in plan if name == "focused_pytest")
    assert "tests/test_reasoning_router.py" in focused_command
    assert "tests/test_reasoning_router_integration.py" in focused_command
    assert "tests/test_reasoning_zero_cost.py" in focused_command
    assert "tests/test_offline_reasoner.py" in focused_command
    assert "tests/test_reasoning_status.py" in focused_command
    assert "tests/test_quick_chat_resilience.py" in focused_command
    assert "tests/test_gemini_diag_zero_call.py" in focused_command
    assert "tests/test_provider_bypass_audit.py" in focused_command
    assert "tests/test_architecture_audit.py" in focused_command
    assert "tests/test_release_state.py" in focused_command
    assert "tests/test_repo_hygiene.py" in focused_command
    assert "tests/test_admin_guard.py" in focused_command
    assert "tests/test_foundation_gate_runner.py" in focused_command


def test_pytest_only_file_is_not_mistaken_for_script_harness(tmp_path):
    pytest_only = tmp_path / "test_only.py"
    pytest_only.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    assert gate._has_main_harness(pytest_only) is False

    script = tmp_path / "test_script.py"
    script.write_text(
        "def main():\n    return 0\n\nif __name__ == '__main__':\n    raise SystemExit(main())\n",
        encoding="utf-8",
    )
    assert gate._has_main_harness(script) is True


def test_provider_and_architecture_audits_run_before_benchmark():
    names = [name for name, _ in gate.build_stage_plan("python")]
    assert names.index("provider_bypass_audit") < names.index("architecture_audit")
    assert names.index("architecture_audit") < names.index("benchmark_superconductivity_v2")


def test_receipt_fails_closed_when_any_stage_fails(tmp_path):
    path = tmp_path / "audit" / "gate.json"
    stages = [
        gate.StageResult("good", ["python", "good.py"], 0, 0.1, "passed", []),
        gate.StageResult("bad", ["python", "bad.py"], 1, 0.2, "failed", ["boom"]),
    ]

    receipt = gate._write_receipt(path, stages)

    assert receipt.passed is False
    assert receipt.failed_stages == ["bad"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["offline_zero_cost"] is True
    assert payload["passed"] is False
    assert payload["stages"][1]["output_tail"] == ["boom"]


def test_receipt_passes_only_when_every_stage_passes(tmp_path):
    path = tmp_path / "gate.json"
    stages = [
        gate.StageResult("one", ["python", "one.py"], 0, 0.1, "passed", []),
        gate.StageResult("two", ["python", "two.py"], 0, 0.1, "passed", []),
    ]

    receipt = gate._write_receipt(path, stages)

    assert receipt.passed is True
    assert receipt.failed_stages == []
    assert path.is_file()
    assert not Path(str(path) + ".tmp").exists()
