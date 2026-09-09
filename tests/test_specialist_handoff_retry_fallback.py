"""Behavior-level regression coverage for specialist handoff completion semantics."""

from research_engine.research_company import attach_company_passes


_MISSING_HANDOFF_NOTE = (
    "Complete specialist handoff was not confirmed; it was missing, clipped, "
    "or chief analysis did not finish."
)


def _out(done_passes):
    return {
        "planned_passes": [],
        "done_passes": list(done_passes),
        "notes": [],
        "api_accounting": {},
    }


def _company(*, prepared=True, truncated=False):
    return {
        "handoff_prepared": prepared,
        "handoff_truncated_roles": ["validation"] if truncated else [],
        "workers": [],
        "logical_call_budget": 4,
        "accounting_complete": True,
        "completed_workers": 0,
        "requested_workers": 0,
    }


def test_successful_analysis_still_confirms_specialist_handoff():
    out = _out(["analysis"])
    attach_company_passes(out, _company())

    assert "specialist_handoff" in out["done_passes"]
    assert _MISSING_HANDOFF_NOTE not in out["notes"]


def test_successful_synthesis_is_bounded_fallback_handoff_consumer():
    out = _out(["synthesis"])
    attach_company_passes(out, _company())

    assert "specialist_handoff" in out["done_passes"]
    assert _MISSING_HANDOFF_NOTE not in out["notes"]
    assert any("synthesis fallback" in note for note in out["notes"])


def test_no_successful_consumer_keeps_handoff_incomplete():
    out = _out([])
    attach_company_passes(out, _company())

    assert "specialist_handoff" not in out["done_passes"]
    assert _MISSING_HANDOFF_NOTE in out["notes"]


def test_truncated_handoff_cannot_be_recovered_by_synthesis():
    out = _out(["synthesis"])
    attach_company_passes(out, _company(truncated=True))

    assert "specialist_handoff" not in out["done_passes"]
    assert _MISSING_HANDOFF_NOTE in out["notes"]


def test_missing_handoff_cannot_be_recovered_by_synthesis():
    out = _out(["synthesis"])
    attach_company_passes(out, _company(prepared=False))

    assert "specialist_handoff" not in out["done_passes"]
    assert _MISSING_HANDOFF_NOTE in out["notes"]
