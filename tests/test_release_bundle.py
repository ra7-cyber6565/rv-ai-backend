"""Exact-revision release bundle verifier regressions."""
from __future__ import annotations

from datetime import datetime, timezone

from scripts.verify_release_bundle import verify_release_bundle


SHA = "2a21a6fbcb0771be746766dad3c6a511a7c3ec5e"
NOW = 2_000_000_000
DEPLOYED_CHECK_NAMES = (
    "health_http",
    "health_state",
    "zero_cost_only",
    "release_state_honest",
    "deployed_revision_matches",
    "health_public_payload_safe",
    "api_http",
    "session_route_advertised",
    "processing_route_advertised",
    "api_public_payload_safe",
    "processing_http",
    "processing_contract",
    "processing_public_payload_safe",
    "session_http",
    "session_capability_shape",
    "private_no_store_headers",
    "missing_capability_rejected",
    "empty_project_capability_accepted",
    "private_list_no_store",
    "no_model_or_research_route_called",
)


def _receipts():
    foundation = {
        "schema_version": 2,
        "created_at_epoch": NOW,
        "passed": True,
        "offline_zero_cost": True,
        "code_revision": SHA,
        "repository_clean": True,
        "code_identity_verified": True,
    }
    live = {
        "schema_version": 2,
        "created_at_epoch": NOW,
        "passed": True,
        "code_revision": SHA,
        "repository_clean": True,
        "contains_answer_or_source_text": False,
        "contains_credentials": False,
        "zero_cost_preflight": {
            "ready": True,
            "zero_cost_only": True,
            "model_layers_usable_now": 1,
            "storage_validated": True,
            "storage_ready": True,
            "blockers": [],
        },
    }
    deployed = {
        "gate": "DEPLOYED_READONLY_ZERO_MODEL_SMOKE",
        "complete": True,
        "checked_at_utc": datetime.fromtimestamp(NOW, tz=timezone.utc).isoformat(),
        "expected_code_revision": SHA,
        "deployed_code_revision": SHA,
        "zero_model_calls_by_construction": True,
        "capabilities_or_secrets_recorded": False,
        "calls": [
            "GET /health",
            "GET /api",
            "GET /api/v1/processing-capabilities",
            "POST /api/v1/session",
        ],
        "checks": [
            {"name": name, "passed": True, "detail": "ok"}
            for name in DEPLOYED_CHECK_NAMES
        ],
    }
    identity = {"available": True, "revision": SHA, "clean": True}
    return foundation, live, deployed, identity


def _verify(foundation, live, deployed, identity):
    return verify_release_bundle(
        foundation,
        live,
        deployed,
        current_identity=identity,
        now_epoch=NOW,
    )


def test_bundle_passes_only_when_every_gate_has_the_same_clean_revision():
    foundation, live, deployed, identity = _receipts()
    result = _verify(foundation, live, deployed, identity)
    assert result["passed"] is True
    assert result["code_revision"] == SHA
    assert result["contains_credentials_or_capabilities"] is False
    assert result["schema_version"] == 3
    assert all(row["passed"] for row in result["checks"])


def test_bundle_fails_closed_on_cross_commit_receipt_mix():
    foundation, live, deployed, identity = _receipts()
    live["code_revision"] = "1" * 40
    result = _verify(foundation, live, deployed, identity)
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["all_receipts_same_revision"] is False
    assert result["passed"] is False
    assert result["code_revision"] == ""


def test_bundle_fails_closed_on_dirty_checkout_or_private_receipt_flags():
    foundation, live, deployed, identity = _receipts()
    identity["clean"] = False
    live["contains_credentials"] = True
    deployed["capabilities_or_secrets_recorded"] = True
    result = _verify(foundation, live, deployed, identity)
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["current_checkout_clean"] is False
    assert checks["live_zero_cost_gate_passed"] is False
    assert checks["deployed_zero_model_gate_passed"] is False
    assert result["passed"] is False


def test_bundle_rejects_handwritten_boolean_only_spoof_receipts():
    foundation, live, deployed, identity = _receipts()
    foundation.pop("schema_version")
    foundation.pop("offline_zero_cost")
    live.pop("zero_cost_preflight")
    deployed.pop("gate")
    deployed.pop("calls")
    deployed.pop("checks")

    result = _verify(foundation, live, deployed, identity)
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["foundation_receipt_contract"] is False
    assert checks["live_receipt_contract"] is False
    assert checks["deployed_receipt_contract"] is False
    assert result["passed"] is False


def test_live_receipt_requires_confirmed_free_model_and_validated_storage():
    foundation, live, deployed, identity = _receipts()
    live["zero_cost_preflight"]["model_layers_usable_now"] = 0
    live["zero_cost_preflight"]["storage_ready"] = False
    live["zero_cost_preflight"]["blockers"] = ["no confirmed/free model"]

    result = _verify(foundation, live, deployed, identity)
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["live_receipt_contract"] is False
    assert checks["live_zero_cost_gate_passed"] is False
    assert result["passed"] is False


def test_deployed_receipt_requires_exact_zero_model_gate_identity():
    foundation, live, deployed, identity = _receipts()
    deployed["gate"] = "GENERIC_SMOKE"

    result = _verify(foundation, live, deployed, identity)
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["deployed_receipt_contract"] is False
    assert checks["deployed_zero_model_gate_passed"] is False
    assert result["passed"] is False


def test_live_receipt_malformed_model_count_fails_closed_without_crashing():
    foundation, live, deployed, identity = _receipts()
    live["zero_cost_preflight"]["model_layers_usable_now"] = "not-a-number"

    result = _verify(foundation, live, deployed, identity)
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["live_receipt_contract"] is False
    assert result["passed"] is False


def test_deployed_receipt_rejects_model_or_research_route_in_call_ledger():
    foundation, live, deployed, identity = _receipts()
    deployed["calls"].append("POST /api/v1/chat")

    result = _verify(foundation, live, deployed, identity)
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["deployed_receipt_contract"] is False
    assert checks["deployed_zero_model_gate_passed"] is False
    assert result["passed"] is False


def test_deployed_receipt_rejects_get_api_prefix_escape():
    """`GET /api` must not accidentally authorize every `GET /api/v1/...`."""
    foundation, live, deployed, identity = _receipts()
    deployed["calls"].append("GET /api/v1/research-jobs")

    result = _verify(foundation, live, deployed, identity)
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["deployed_receipt_contract"] is False
    assert result["passed"] is False


def test_expected_normalized_reading_session_probe_remains_allowed():
    foundation, live, deployed, identity = _receipts()
    deployed["calls"].extend([
        "GET /api/v1/reading-sessions",
        "GET /api/v1/reading-sessions",
        "OPTIONS /api/v1/session",
    ])

    result = _verify(foundation, live, deployed, identity)
    assert result["passed"] is True


def test_missing_or_failed_required_deployed_check_fails_closed():
    foundation, live, deployed, identity = _receipts()
    deployed["checks"] = [
        row for row in deployed["checks"]
        if row["name"] != "missing_capability_rejected"
    ]
    result = _verify(foundation, live, deployed, identity)
    assert result["passed"] is False

    foundation, live, deployed, identity = _receipts()
    for row in deployed["checks"]:
        if row["name"] == "private_no_store_headers":
            row["passed"] = False
            break
    result = _verify(foundation, live, deployed, identity)
    assert result["passed"] is False


def test_duplicate_deployed_check_name_is_rejected():
    foundation, live, deployed, identity = _receipts()
    deployed["checks"].append(dict(deployed["checks"][0]))
    result = _verify(foundation, live, deployed, identity)
    assert result["passed"] is False


def test_stale_live_receipt_cannot_be_replayed_forever():
    foundation, live, deployed, identity = _receipts()
    live["created_at_epoch"] = NOW - (24 * 60 * 60) - 1

    result = _verify(foundation, live, deployed, identity)
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["live_receipt_fresh"] is False
    assert result["passed"] is False


def test_stale_foundation_receipt_requires_a_new_offline_proof():
    foundation, live, deployed, identity = _receipts()
    foundation["created_at_epoch"] = NOW - (7 * 24 * 60 * 60) - 1

    result = _verify(foundation, live, deployed, identity)
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["foundation_receipt_fresh"] is False
    assert result["passed"] is False


def test_future_dated_deployed_receipt_beyond_clock_skew_fails_closed():
    foundation, live, deployed, identity = _receipts()
    deployed["checked_at_utc"] = datetime.fromtimestamp(
        NOW + 301, tz=timezone.utc,
    ).isoformat()

    result = _verify(foundation, live, deployed, identity)
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["deployed_receipt_fresh"] is False
    assert result["passed"] is False


def test_malformed_deployed_timestamp_fails_closed_without_exception():
    foundation, live, deployed, identity = _receipts()
    deployed["checked_at_utc"] = "not-a-timestamp"

    result = _verify(foundation, live, deployed, identity)
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["deployed_receipt_fresh"] is False
    assert result["passed"] is False
