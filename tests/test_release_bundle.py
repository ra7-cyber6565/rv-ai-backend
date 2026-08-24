"""Exact-revision release bundle verifier regressions."""
from __future__ import annotations

from scripts.verify_release_bundle import verify_release_bundle


SHA = "2a21a6fbcb0771be746766dad3c6a511a7c3ec5e"


def _receipts():
    foundation = {
        "passed": True,
        "code_revision": SHA,
        "repository_clean": True,
        "code_identity_verified": True,
    }
    live = {
        "passed": True,
        "code_revision": SHA,
        "repository_clean": True,
        "contains_answer_or_source_text": False,
        "contains_credentials": False,
    }
    deployed = {
        "complete": True,
        "expected_code_revision": SHA,
        "deployed_code_revision": SHA,
        "zero_model_calls_by_construction": True,
        "capabilities_or_secrets_recorded": False,
    }
    identity = {"available": True, "revision": SHA, "clean": True}
    return foundation, live, deployed, identity


def test_bundle_passes_only_when_every_gate_has_the_same_clean_revision():
    foundation, live, deployed, identity = _receipts()
    result = verify_release_bundle(
        foundation, live, deployed, current_identity=identity,
    )
    assert result["passed"] is True
    assert result["code_revision"] == SHA
    assert result["contains_credentials_or_capabilities"] is False
    assert all(row["passed"] for row in result["checks"])


def test_bundle_fails_closed_on_cross_commit_receipt_mix():
    foundation, live, deployed, identity = _receipts()
    live["code_revision"] = "1" * 40
    result = verify_release_bundle(
        foundation, live, deployed, current_identity=identity,
    )
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["all_receipts_same_revision"] is False
    assert result["passed"] is False
    assert result["code_revision"] == ""


def test_bundle_fails_closed_on_dirty_checkout_or_private_receipt_flags():
    foundation, live, deployed, identity = _receipts()
    identity["clean"] = False
    live["contains_credentials"] = True
    deployed["capabilities_or_secrets_recorded"] = True
    result = verify_release_bundle(
        foundation, live, deployed, current_identity=identity,
    )
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["current_checkout_clean"] is False
    assert checks["live_zero_cost_gate_passed"] is False
    assert checks["deployed_zero_model_gate_passed"] is False
    assert result["passed"] is False

