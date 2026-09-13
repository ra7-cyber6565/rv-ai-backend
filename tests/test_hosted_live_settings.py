"""Offline configuration failures must be cheap, specific and secret-free."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from scripts.check_hosted_live_settings import inspect_settings


def configured():
    return {
        "ZERO_COST_ONLY": "true", "GEMINI_ZERO_COST_CONFIRMED": "true",
        "GEMINI_API_KEY": "PRIVATE_TEST_KEY", "GEMINI_MODEL": "PRIVATE_TEST_MODEL",
    }


def test_empty_settings_report_every_missing_input_without_network():
    result = inspect_settings({})
    assert result["state"] == "BLOCKED"
    assert set(result["blocker_codes"]) == {
        "zero_cost_only_required", "gemini_key_missing",
        "gemini_zero_cost_confirmation_required", "explicit_model_identifier_required",
    }
    assert result["network_calls"] == 0


@pytest.mark.parametrize("flag", ["true", "TRUE", " true\n", "1", "yes", "on"])
def test_confirmation_matches_runtime_policy_without_claiming_provider_access(flag):
    env = dict(configured(), GEMINI_ZERO_COST_CONFIRMED=flag)
    result = inspect_settings(env)
    assert result["passed"] is True
    assert result["provider_access_verified"] is False
    assert result["billing_state_verified"] is False
    assert "PRIVATE" not in json.dumps(result)
    assert env["GEMINI_ZERO_COST_CONFIRMED"] == flag


@pytest.mark.parametrize("flag", ["false", "'true'", "true confirmed", "GEMINI_ZERO_COST_CONFIRMED=true", ""])
def test_misfilled_confirmation_is_not_automatically_enabled(flag):
    result = inspect_settings(dict(configured(), GEMINI_ZERO_COST_CONFIRMED=flag))
    assert result["passed"] is False
    assert result["blocker_codes"] == ["gemini_zero_cost_confirmation_required"]


def test_cli_needs_only_stdlib_and_never_prints_input_values():
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_hosted_live_settings.py"
    for env, expected in [(configured(), 0), (dict(configured(), GEMINI_MODEL="  "), 2)]:
        result = subprocess.run([sys.executable, "-I", "-S", str(script)],
                                env=env, capture_output=True, text=True, timeout=10)
        assert result.returncode == expected
        assert "PRIVATE" not in result.stdout + result.stderr
        assert json.loads(result.stdout)["network_calls"] == 0


def test_workflow_checks_settings_before_setup_and_does_not_run_foundation_after_failure():
    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "foundation-tests.yml"
    steps = yaml.safe_load(path.read_text())["jobs"]["offline-regression"]["steps"]
    settings = next(row for row in steps if row.get("id") == "live_settings")
    install = next(row for row in steps if row["name"] == "Install dependencies")
    foundation = next(row for row in steps if row["name"] == "Run strict zero-cost foundation gate")
    assert steps.index(settings) < steps.index(install)
    assert "workflow_dispatch" in settings["if"] and "inputs.live_company" in settings["if"]
    assert "steps.live_settings.outcome != 'failure'" in foundation["if"]
    assert "secrets." not in json.dumps(install)
    assert settings["env"]["GEMINI_MODEL"] == "${{ vars.INFINITY_LIVE_GEMINI_MODEL }}"
