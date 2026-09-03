"""Regression tests for the strict local foundation-gate runner."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import run_foundation_gate as gate


_CLEAN_IDENTITY = {
    "available": True,
    "revision": "2a21a6fbcb0771be746766dad3c6a511a7c3ec5e",
    "clean": True,
}


def test_safe_env_forces_offline_zero_cost(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "should-not-survive")
    monkeypatch.setenv("GEMINI_API_KEY_2", "backup-should-not-survive")
    monkeypatch.setenv("GEMINI_API_KEY9", "backup-nine-should-not-survive")
    monkeypatch.setenv("GEMINI_API_KEYS", "list-one,list-two")
    monkeypatch.setenv("GEMINI_API_KEY_BACKUP", "named-backup")
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
    assert env["GEMINI_API_KEY_2"] == ""
    assert env["GEMINI_API_KEY9"] == ""
    assert env["GEMINI_API_KEYS"] == ""
    assert env["GEMINI_API_KEY_BACKUP"] == ""
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
    assert env["PYTHONPATH"].split(gate.os.pathsep)[0] == str(gate.REPO_ROOT)


def test_default_stage_plan_contains_real_release_gates():
    plan = gate.build_stage_plan("python")
    names = [name for name, _ in plan]

    assert names[0] == "compileall"
    assert "focused_pytest" in names
    assert "all_pytest" in names
    assert "offline_api_smoke" in names
    assert "core_regression" in names
    assert "provider_bypass_audit" in names
    assert "architecture_audit" in names
    assert "benchmark_cross_domain" in names
    assert "benchmark_superconductivity_v2" in names
    assert "benchmark_dark_matter_acceptance" in names

    all_pytest = next(command for name, command in plan if name == "all_pytest")
    assert all_pytest == ["python", "-m", "pytest", "-q", "tests"]

    smoke = next(command for name, command in plan if name == "offline_api_smoke")
    assert smoke == ["python", "scripts/run_offline_api_smoke.py"]

    focused_command = next(command for name, command in plan if name == "focused_pytest")
    for required in (
        "tests/test_body_limit.py",
        "tests/test_archive_runtime.py",
        "tests/test_archive_integration.py",
        "tests/test_archive_routes.py",
        "tests/test_research_job_archive_retention.py",
        "tests/test_api_input_bounds.py",
        "tests/test_cors_private_headers.py",
        "tests/test_web_job_capability.py",
        "tests/test_web_source_link_safety.py",
        "tests/test_source_prompt_guard.py",
        "tests/test_source_output_safety.py",
        "tests/test_project_access.py",
        "tests/test_project_route_guards.py",
        "tests/test_project_wiring.py",
        "tests/test_private_response_headers.py",
        "tests/test_reasoning_router.py",
        "tests/test_reasoning_router_integration.py",
        "tests/test_reasoning_zero_cost.py",
        "tests/test_provider_health.py",
        "tests/test_offline_reasoner.py",
        "tests/test_reasoning_status.py",
        "tests/test_gemini_key_status.py",
        "tests/test_quick_chat_resilience.py",
        "tests/test_chat_resilience.py",
        "tests/test_gemini_diag_zero_call.py",
        "tests/test_quota_backup.py",
        "tests/test_provider_bypass_audit.py",
        "tests/test_architecture_audit.py",
        "tests/test_release_state.py",
        "tests/test_repo_hygiene.py",
        "tests/test_admin_guard.py",
        "tests/test_job_access.py",
        "tests/test_job_routes_access.py",
        "tests/test_network_safety.py",
        "tests/test_patents.py",
        "tests/test_live_zero_cost_gate.py",
        "tests/test_release_identity.py",
        "tests/test_release_bundle.py",
        "tests/test_windows_launchers.py",
        "tests/test_unverified_semantics.py",
        "tests/test_foundation_gate_runner.py",
    ):
        assert required in focused_command


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


def test_audits_and_cross_domain_run_before_superconductivity_benchmark():
    names = [name for name, _ in gate.build_stage_plan("python")]
    assert names.index("provider_bypass_audit") < names.index("architecture_audit")
    assert names.index("architecture_audit") < names.index("benchmark_cross_domain")
    assert names.index("benchmark_cross_domain") < names.index("benchmark_superconductivity_v2")
    assert names.index("benchmark_superconductivity_v2") < names.index("benchmark_dark_matter_acceptance")


def test_real_api_smoke_runs_after_pytest_before_core_regression():
    names = [name for name, _ in gate.build_stage_plan("python")]
    assert names.index("all_pytest") < names.index("offline_api_smoke")
    assert names.index("offline_api_smoke") < names.index("core_regression")


def test_receipt_fails_closed_when_any_stage_fails(tmp_path):
    path = tmp_path / "audit" / "gate.json"
    stages = [
        gate.StageResult("good", ["python", "good.py"], 0, 0.1, "passed", []),
        gate.StageResult("bad", ["python", "bad.py"], 1, 0.2, "failed", ["boom"]),
    ]

    receipt = gate._write_receipt(path, stages, identity=_CLEAN_IDENTITY)

    assert receipt.passed is False
    assert receipt.failed_stages == ["bad"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["offline_zero_cost"] is True
    assert payload["code_identity_verified"] is True
    assert payload["code_revision"] == _CLEAN_IDENTITY["revision"]
    assert payload["passed"] is False
    assert payload["stages"][1]["output_tail"] == ["boom"]


def test_receipt_passes_only_when_every_stage_passes(tmp_path):
    path = tmp_path / "gate.json"
    stages = [
        gate.StageResult("one", ["python", "one.py"], 0, 0.1, "passed", []),
        gate.StageResult("two", ["python", "two.py"], 0, 0.1, "passed", []),
    ]

    receipt = gate._write_receipt(path, stages, identity=_CLEAN_IDENTITY)

    assert receipt.passed is True
    assert receipt.failed_stages == []
    assert path.is_file()
    assert not Path(str(path) + ".tmp").exists()


def test_receipt_fails_closed_for_dirty_or_unknown_checkout(tmp_path):
    stages = [
        gate.StageResult("one", ["python", "one.py"], 0, 0.1, "passed", []),
    ]
    for identity in (
        {**_CLEAN_IDENTITY, "clean": False},
        {"available": False, "revision": "", "clean": False},
    ):
        receipt = gate._write_receipt(
            tmp_path / f"{len(identity['revision'])}.json",
            stages,
            identity=identity,
        )
        assert receipt.passed is False
        assert receipt.code_identity_verified is False
        assert "clean_repository_identity" in receipt.failed_stages
