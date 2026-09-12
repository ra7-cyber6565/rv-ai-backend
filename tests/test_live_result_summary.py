"""Real result serialization through child evaluation and hosted publication."""
import copy
import json

import pytest

from research_engine.models import ResearchResult
from scripts.run_hosted_live_gate import summarize
from scripts.run_live_zero_cost_gate import evaluate_result
from utils.live_result_summary import sanitize_result_summary


def returned_result(mode="COMPANY"):
    return ResearchResult(
        mode=mode, status="RESEARCH INCOMPLETE", hypotheses=[],
        answer="PRIVATE_ANSWER", failure_kind="auth_failure",
        missing_passes=["analysis", "synthesis", "specialist_handoff", "company_evidence"],
        api_accounting={"primary_failure_kind": "auth_failure", "failure_events": [{
            "kind": "auth_failure", "attempt": 1, "model": "PRIVATE_MODEL",
            "label": "analysis", "detail": "PRIVATE_KEY",
        }]},
        verification={"research_company": {
            "status": "PARTIAL", "requested_workers": 4, "completed_workers": 0,
            "accounting_complete": True,
            "workers": [{
                "role": role, "status": "FAILED", "error": "no_model_output",
                "worker_id": "PRIVATE_WORKER", "report": {"text": "PRIVATE_SOURCE"},
                "accounting_complete": True,
                "accounting": {"actual_http_attempts": 1, "successful_calls": 0},
            } for role in ("evidence", "validation", "mechanism", "red_team")],
            "chief_execution": {"done_passes": [], "accounting": {
                "actual_http_attempts": 1, "successful_calls": 0,
            }},
        }},
    ).to_dict()


@pytest.mark.parametrize("mode", ["MAXIMUM", "MARATHON", "COMPANY", "COMPANY_PLUS"])
def test_mode_matches_real_serialized_result_without_coverage_mode(mode):
    result = returned_result(mode)
    assert "mode" not in result["coverage"]
    receipt = evaluate_result(result, required_depth_mode=mode)
    checks = {row["name"]: row["passed"] for row in receipt["checks"]}
    assert checks["depth_mode_matches"] is True
    assert checks["status_complete"] is False
    assert receipt["passed"] is False
    assert receipt["summary"]["reported_depth_mode"] == mode


@pytest.mark.parametrize("change", ["wrong", "missing", "malformed", "conflict", "invalid_legacy"])
def test_coverage_or_requested_mode_cannot_fabricate_an_executed_mode(change):
    result = returned_result()
    result["coverage"]["mode"] = "COMPANY"
    if change == "wrong":
        result["mode"] = "MAXIMUM"
    elif change == "missing":
        del result["mode"]
    elif change == "malformed":
        result["mode"] = {"mode": "COMPANY", "secret": "PRIVATE_KEY"}
    elif change == "conflict":
        result["coverage"]["mode"] = "MAXIMUM"
    else:
        result["coverage"]["mode"] = []
    receipt = evaluate_result(result, required_depth_mode="COMPANY")
    assert next(row for row in receipt["checks"] if row["name"] == "depth_mode_matches")["passed"] is False
    assert receipt["summary"]["requested_depth_mode"] == "COMPANY"
    assert receipt["passed"] is False
    assert "PRIVATE" not in json.dumps(receipt["checks"])


def test_failed_result_keeps_worker_chief_and_provider_diagnostics_through_host():
    child = evaluate_result(returned_result(), required_depth_mode="COMPANY")
    public = summarize({"COMPANY": {"passed": child["passed"], "receipt": child}})["COMPANY"]
    assert public["passed"] is False
    assert "PRIVATE" not in json.dumps(public)
    summary = public["summary"]
    assert summary["status"] == "RESEARCH INCOMPLETE"
    assert summary["reported_depth_mode"] == summary["requested_depth_mode"] == "COMPANY"
    assert summary["hypotheses"] == 0
    assert summary["primary_failure_kind"] == "auth_failure"
    assert summary["failure_events"] == [{"kind": "auth_failure", "attempt": 1}]
    assert summary["missing_passes"] == ["analysis", "synthesis", "specialist_handoff", "company_evidence"]
    company = summary["company"]
    assert company["requested_workers"] == 4
    assert len(company["workers"]) == 4
    assert company["workers"][0]["error"] == "no_model_output"
    assert company["workers"][0]["accounting"]["successful_calls"] == 0
    assert company["chief_execution"]["done_passes"] == []
    assert company["chief_execution"]["accounting"]["successful_calls"] == 0
    assert company["chief_execution"]["accounting"]["passes_empty"] is None
    checks = {row["name"]: row["passed"] for row in public["checks"]}
    assert checks["depth_mode_matches"] is True
    assert checks["company_workers_executed"] is False
    assert checks["company_chief_executed"] is False


def test_host_revalidates_injected_summary_and_bounds_lists_without_false_zero():
    raw = evaluate_result(returned_result(), required_depth_mode="COMPANY")["summary"]
    raw.update(status="PRIVATE_KEY", reported_depth_mode="PRIVATE_KEY", sources=True,
               hypotheses="0", citations=-1, on_topic_sources=10**12,
               failure_kind="private_key", failure_events=[{
                   "kind": "private_key", "attempt": True, "detail": "PRIVATE_SOURCE",
               }] * 100, missing_passes=["PRIVATE_SOURCE", "analysis", "analysis"])
    company = raw["company"]
    company["workers"] *= 10
    company["workers"][0].update(role="private_role", status="PRIVATE_KEY", error="private_error")
    company["chief_execution"].update(done_passes=["PRIVATE_KEY", "synthesis"])
    untouched = copy.deepcopy(raw)
    public = summarize({"COMPANY": {"passed": False, "receipt": {"summary": raw}}})
    assert raw == untouched
    assert "private" not in json.dumps(public).lower()
    clean = public["COMPANY"]["summary"]
    assert clean["status"] == clean["reported_depth_mode"] == "UNKNOWN"
    assert all(clean[key] is None for key in ("sources", "hypotheses", "citations", "on_topic_sources"))
    assert clean["failure_kind"] == "unknown"
    assert clean["failure_events_truncated"] is True
    assert len(clean["failure_events"]) == 12
    assert clean["failure_events"][0] == {"kind": "unknown", "attempt": None}
    assert clean["company"]["workers_truncated"] is True
    assert len(clean["company"]["workers"]) == 6
    assert clean["company"]["chief_execution"]["done_passes"] == ["synthesis"]
    assert sanitize_result_summary(clean) == clean


@pytest.mark.parametrize("malformed", [None, [], "PRIVATE_KEY", True])
def test_missing_or_malformed_diagnostics_are_unknown_not_zero(malformed):
    summary = sanitize_result_summary({
        "company": {"workers": malformed, "chief_execution": malformed},
        "failure_events": malformed, "missing_passes": malformed,
    })
    assert summary["hypotheses"] is None
    assert summary["company"]["chief_execution"]["accounting"]["successful_calls"] is None
    assert summary["company"]["workers"] == []
    assert "PRIVATE" not in json.dumps(summary)
