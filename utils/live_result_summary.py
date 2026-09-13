"""Bounded public diagnostics for returned research results, never their text.

Apply this both when constructing the child receipt and when publishing it.
Unknown counters remain null: absence is not evidence of zero calls or failures.
This module diagnoses execution; it does not decide whether a gate passes.
"""
from collections.abc import Mapping

from research_engine.model_errors import KINDS

DEPTH_MODES = {"QUICK", "DEEP", "MAXIMUM", "MARATHON", "COMPANY", "COMPANY_PLUS"}
ROLES = {"evidence", "validation", "mechanism", "red_team", "data_quality", "implementation"}
PASSES = {"analysis", "critique", "hypothesis", "synthesis", "specialist_handoff"} | {
    "company_" + role for role in ROLES
}
COUNTERS = (
    "logical_reasoning_calls", "actual_http_attempts", "successful_calls",
    "failed_http_attempts", "same_model_retries", "model_switches",
    "key_switches", "provider_fallbacks", "passes_requested", "passes_with_output", "passes_empty",
)


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _enum(value, allowed, default="UNKNOWN"):
    return value if type(value) is str and value in allowed else default


def mode_name(value):
    return _enum(value.strip().upper() if type(value) is str else None, DEPTH_MODES)


def _count(value):
    return value if type(value) is int and 0 <= value <= 1_000_000 else None


def _boolean(value):
    return value if type(value) is bool else None


def _passes(value):
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(item for item in value[:32] if type(item) is str and item in PASSES))


def _accounting(value):
    raw = _mapping(value)
    return {key: _count(raw.get(key)) for key in COUNTERS}


def company_execution_summary(value):
    """Keep only fixed roles/states, receipt counts and chief execution passes."""
    raw = _mapping(value)
    workers = raw.get("workers")
    workers = workers if isinstance(workers, list) else []
    chief = _mapping(raw.get("chief_execution"))
    return {
        "status": _enum(raw.get("status"), {"DRAFTS_READY", "PARTIAL"}),
        "requested_workers": _count(raw.get("requested_workers")),
        "completed_workers": _count(raw.get("completed_workers")),
        "accounting_complete": _boolean(raw.get("accounting_complete")),
        "workers_truncated": len(workers) > 6 or raw.get("workers_truncated") is True,
        "workers": [{
            "role": _enum(_mapping(row).get("role"), ROLES),
            "status": _enum(_mapping(row).get("status"), {"DRAFT_READY", "PARTIAL", "FAILED"}),
            "error": _enum(_mapping(row).get("error"), {
                "", "worker_deadline", "worker_process_failed", "no_model_output",
                "worker_unavailable", "invalid_worker_report",
            }),
            "accounting_complete": _boolean(_mapping(row).get("accounting_complete")),
            "provider_output_capture_complete": _boolean(_mapping(row).get("provider_output_capture_complete")),
            "accounting": _accounting(_mapping(row).get("accounting")),
        } for row in workers[:6]],
        "chief_execution": {
            "done_passes": _passes(chief.get("done_passes")),
            "accounting": _accounting(chief.get("accounting")),
        },
    }


def sanitize_result_summary(value):
    """Do not forward arbitrary identifiers, model labels, hashes or messages."""
    raw = _mapping(value)
    out = {key: mode_name(raw.get(key)) for key in (
        "requested_depth_mode", "reported_depth_mode",
    )}
    out["status"] = _enum(raw.get("status"), {
        "COMPLETE", "PARTIAL", "RESEARCH INCOMPLETE", "BLOCKED", "FAILED", "NOT_RUN",
    })
    out["discovery_status"] = _enum(raw.get("discovery_status"), {
        "ASSESSMENT_READY", "NO_TESTABLE_HYPOTHESES",
    })
    for key in ("sources", "on_topic_sources", "full_text_sources_read", "citations", "hypotheses"):
        out[key] = _count(raw.get(key))
    for key in ("failure_kind", "primary_failure_kind", "recovered_primary_failure_kind"):
        out[key] = _enum(raw.get(key), set(KINDS) | {""}, "unknown")
    events = raw.get("failure_events")
    events = events if isinstance(events, list) else []
    out["failure_events"] = [{
        "kind": _enum(_mapping(row).get("kind"), set(KINDS), "unknown"),
        "attempt": _count(_mapping(row).get("attempt")),
        **({"origin": "shared_run_cooldown"}
           if _mapping(row).get("origin") == "shared_run_cooldown" else {}),
    } for row in events[:12]]
    out["failure_events_truncated"] = len(events) > 12 or raw.get("failure_events_truncated") is True
    out["missing_passes"] = _passes(raw.get("missing_passes"))
    out["company"] = company_execution_summary(raw.get("company"))
    return out
