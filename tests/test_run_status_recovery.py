"""Recovered provider attempts must not remain the final run failure."""
from __future__ import annotations

from research_engine.run_status import COMPLETE, PARTIAL, evaluate


def test_complete_run_clears_recovered_timeout_but_keeps_technical_audit():
    status = evaluate(
        planned_passes=["analysis", "hypothesis", "synthesis"],
        done_passes=["analysis", "hypothesis", "synthesis"],
        failure_kind="request_timeout",
        failure_reason="deep reasoning request timed out before compact recovery",
        source_count=5,
        technical_details=["TimeoutError during first provider attempt"],
    )
    assert status.code == COMPLETE
    assert status.failure_kind == ""
    assert status.reason == ""
    assert status.banner == ""
    assert status.technical, "recovered attempt must remain auditable"


def test_partial_run_keeps_timeout_as_the_actual_failure_reason():
    status = evaluate(
        planned_passes=["analysis", "hypothesis", "synthesis"],
        done_passes=["analysis", "synthesis"],
        failure_kind="request_timeout",
        source_count=5,
    )
    assert status.code == PARTIAL
    assert status.failure_kind == "request_timeout"
    assert "waqt-seema" in status.reason
