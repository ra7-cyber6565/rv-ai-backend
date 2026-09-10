"""Regression tests for bounded specialist -> chief handoff semantics."""
from research_engine.company_handoff_guard import chief_handoff
from research_engine.research_company import attach_company_passes


_COUNT_KEYS = (
    "logical_reasoning_calls", "actual_http_attempts", "successful_calls",
    "failed_http_attempts", "same_model_retries", "model_switches",
    "key_switches", "provider_fallbacks", "passes_requested",
    "passes_with_output", "passes_empty",
)


def _accounting():
    return {key: 0 for key in _COUNT_KEYS}


def _verbose_report():
    long_claim = "measured worker claim with source context " * 80
    long_hyp = "testable mechanism with explicit baseline and falsifier " * 45
    return {
        "summary": "bounded summary " * 220,
        "claims": [
            {"text": long_claim, "source_ids": ["S1", "S2"],
             "kind": "SOURCE_REPORTED", "entailment_verified": False}
            for _ in range(10)
        ],
        "hypotheses": [
            {"hypothesis": long_hyp, "prediction": long_hyp,
             "baseline": long_hyp, "test": long_hyp,
             "falsification": long_hyp}
            for _ in range(5)
        ],
        "limitations": [("limitation " * 90) for _ in range(9)],
        "assumptions": [("assumption " * 90) for _ in range(9)],
        "contradictions": [("contradiction " * 90) for _ in range(9)],
        "remaining_questions": [("remaining question " * 90) for _ in range(9)],
        "contract_issues": [],
        "tool_results": [],
        "status": "DRAFT_READY",
        "experiments_performed": False,
    }


def _company(report=None):
    report = report or _verbose_report()
    roles = ("evidence", "validation", "mechanism", "red_team")
    workers = [
        {"role": role, "status": "DRAFT_READY", "report": report,
         "accounting": _accounting(), "accounting_complete": True}
        for role in roles
    ]
    return {
        "workers": workers,
        "requested_workers": len(workers),
        "completed_workers": len(workers),
        "logical_call_budget": 8,
        "accounting_complete": True,
    }


def test_verbose_worker_reports_are_structurally_compacted_not_false_failed():
    company = _company()
    prompt = chief_handoff(company)

    assert set(company["handoff_compacted_roles"]) == {
        "evidence", "validation", "mechanism", "red_team"
    }
    assert company["handoff_truncated_roles"] == []
    assert company["handoff_structured_compaction"] is True
    assert company["handoff_worker_roles"] == [
        "evidence", "validation", "mechanism", "red_team"
    ]
    # Every semantic category remains represented; omitted full-detail counts
    # are explicit instead of silently pretending the chief saw the full report.
    for token in (
        '"claims"', '"hypotheses"', '"limitations"', '"assumptions"',
        '"contradictions"', '"remaining_questions"', '"handoff_compaction"',
    ):
        assert token in prompt
    assert all(
        company["handoff_omitted_counts"][role]["claims"] > 0
        for role in company["handoff_compacted_roles"]
    )


def test_structured_compaction_allows_real_specialist_handoff_pass():
    company = _company()
    chief_handoff(company)
    out = {
        "planned_passes": ["analysis"],
        "done_passes": ["analysis"],
        "notes": [],
        "api_accounting": {},
        "calls": 0,
        "attempts": 0,
        "models_tried": [],
    }

    attach_company_passes(out, company)

    assert "specialist_handoff" in out["planned_passes"]
    assert "specialist_handoff" in out["done_passes"]
    assert not any("Complete specialist handoff was not confirmed" in note
                   for note in out["notes"])


def test_actual_handoff_truncation_still_fails_closed():
    company = _company({
        "summary": "small", "claims": [], "hypotheses": [],
        "limitations": [], "assumptions": [], "contradictions": [],
        "remaining_questions": [], "contract_issues": [], "tool_results": [],
        "status": "DRAFT_READY", "experiments_performed": False,
    })
    chief_handoff(company)
    # Simulate a downstream integrity check detecting an actually incomplete
    # handoff. Existing attach semantics must remain fail-closed.
    company["handoff_truncated_roles"] = ["evidence"]
    out = {
        "planned_passes": ["analysis"], "done_passes": ["analysis"],
        "notes": [], "api_accounting": {}, "calls": 0, "attempts": 0,
        "models_tried": [],
    }

    attach_company_passes(out, company)

    assert "specialist_handoff" in out["planned_passes"]
    assert "specialist_handoff" not in out["done_passes"]
    assert any("Complete specialist handoff was not confirmed" in note
               for note in out["notes"])
