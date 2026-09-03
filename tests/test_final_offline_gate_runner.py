"""Regression tests for the final offline proof wrapper.

These tests are pure Python: no network, model, cloud, deployment or attestation
secret is required.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from scripts.run_final_offline_gate import (
    DOES_NOT_PROVE,
    SCOPE,
    StageResult,
    build_stage_plan,
    make_receipt,
    safe_offline_env,
    validate_foundation_receipt,
)


def _stage(name: str = "x", *, passed: bool = True) -> StageResult:
    return StageResult(
        name=name,
        command_kind="offline_subprocess",
        returncode=0 if passed else 1,
        duration_seconds=0.01,
        timed_out=False,
        passed=passed,
    )


def test_offline_env_blanks_provider_and_operator_secrets():
    env = safe_offline_env({
        "GEMINI_API_KEY": "secret-gemini",
        "GEMINI_API_KEY_2": "secret-backup",
        "GROQ_API_KEY": "secret-groq",
        "OPENROUTER_API_KEY": "secret-router",
        "OPENAI_API_KEY": "secret-openai",
        "ANTHROPIC_API_KEY": "secret-anthropic",
        "INFINITY_OPERATOR_ATTESTATION_KEY": "operator-secret",
        "TERABOX_CLIENT_SECRET": "cloud-secret",
    })
    for name in (
        "GEMINI_API_KEY", "GEMINI_API_KEY_2", "GROQ_API_KEY",
        "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "INFINITY_OPERATOR_ATTESTATION_KEY", "TERABOX_CLIENT_SECRET",
    ):
        assert env[name] == ""
    assert env["ZERO_COST_ONLY"] == "true"
    assert env["GEMINI_ZERO_COST_CONFIRMED"] == "false"
    assert env["GROQ_ZERO_COST_CONFIRMED"] == "false"
    assert env["OLLAMA_ENABLED"] == "false"
    assert env["CLOUD_ARCHIVE_PROVIDER"] == "none"
    assert env["ALLOW_FULLTEXT_FETCH"] == "false"
    assert env["ALLOW_YT_TRANSCRIPT"] == "false"
    assert env["ALLOW_NETWORK_RESEARCH"] == "false"


def test_stage_plan_contains_only_offline_proof_children(tmp_path: Path):
    plan = build_stage_plan(
        "python-test",
        foundation_receipt=tmp_path / "foundation.json",
        quick=False,
    )
    names = [name for name, _ in plan]
    flattened = " ".join(arg for _, cmd in plan for arg in cmd).lower()
    assert names == ["foundation_offline_gate", "source_boundary_audit"]
    assert "run_foundation_gate.py" in flattened
    assert "audit_source_boundary.py" in flattened
    assert "run_live_zero_cost_gate.py" not in flattened
    assert "run_deployed" not in flattened
    assert "attest_" not in flattened
    assert "verify_release_bundle.py" not in flattened


def test_quick_flag_is_forwarded_only_to_foundation(tmp_path: Path):
    plan = build_stage_plan(
        "python-test",
        foundation_receipt=tmp_path / "foundation.json",
        quick=True,
    )
    assert "--quick" in plan[0][1]
    assert "--quick" not in plan[1][1]


def test_pass_receipt_still_refuses_release_and_production_claims():
    receipt = make_receipt(
        [_stage("foundation_offline_gate"), _stage("source_boundary_audit")],
        foundation_receipt_validated=True,
    )
    assert receipt.passed is True
    assert receipt.scope == SCOPE == "offline_code_and_fixture_proof_only"
    assert receipt.offline_zero_cost is True
    assert receipt.release_ready is False
    assert receipt.production_ready is False
    assert receipt.does_not_prove == DOES_NOT_PROVE
    assert "live provider availability" in receipt.does_not_prove
    assert "deployed production acceptance" in receipt.does_not_prove
    assert "operator maturity attestation" in receipt.does_not_prove


def test_failed_child_or_missing_foundation_receipt_fails_closed():
    child_failure = make_receipt(
        [_stage("foundation_offline_gate", passed=False)],
        foundation_receipt_validated=True,
    )
    assert child_failure.passed is False
    assert "foundation_offline_gate" in child_failure.failed_stages

    receipt_failure = make_receipt(
        [_stage("foundation_offline_gate", passed=True)],
        foundation_receipt_validated=False,
    )
    assert receipt_failure.passed is False
    assert "foundation_receipt_validation" in receipt_failure.failed_stages


def test_foundation_receipt_validation_requires_clean_identity(tmp_path: Path):
    path = tmp_path / "foundation.json"
    good = {
        "passed": True,
        "offline_zero_cost": True,
        "code_identity_verified": True,
        "repository_clean": True,
        "code_revision": "abc123",
    }
    path.write_text(json.dumps(good), encoding="utf-8")
    assert validate_foundation_receipt(path) is True

    for key, value in (
        ("passed", False),
        ("offline_zero_cost", False),
        ("code_identity_verified", False),
        ("repository_clean", False),
        ("code_revision", ""),
    ):
        bad = dict(good)
        bad[key] = value
        path.write_text(json.dumps(bad), encoding="utf-8")
        assert validate_foundation_receipt(path) is False


def test_final_receipt_schema_contains_no_secret_values():
    receipt = make_receipt([_stage()], foundation_receipt_validated=True)
    serialized = json.dumps(asdict(receipt), sort_keys=True).lower()
    for forbidden in (
        "api_key", "client_secret", "private_secret", "operator-secret",
        "gemini_api_key", "groq_api_key", "openrouter_api_key",
    ):
        assert forbidden not in serialized
