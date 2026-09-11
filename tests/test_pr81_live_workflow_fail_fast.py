"""Regression guard for the branch-scoped PR81 live acceptance ordering.

The safe one-call model diagnostic must run after the strict zero-cost/storage
preflight but before Docker build and the expensive fixed Max research run. This
keeps invalid/rejected live credentials fail-fast without weakening acceptance.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pr81-trading-live-acceptance.yml"


def test_live_model_probe_precedes_executor_and_full_max_run():
    text = WORKFLOW.read_text(encoding="utf-8")
    zero_cost = text.index("Confirm strict zero-cost live preflight")
    probe = text.index("Validate configured live model with one safe call")
    executor = text.index("Prepare immutable isolated executor image")
    live_run = text.index("Run fixed Max trading live acceptance")

    assert zero_cost < probe < executor < live_run
    assert "diagnose_live_model_request.py --prompt-chars 12000" in text


def test_live_probe_remains_single_call_no_fallback_contract():
    diagnostic = (ROOT / "scripts" / "diagnose_live_model_request.py").read_text(
        encoding="utf-8"
    )
    assert '"generation_calls": 1' in diagnostic
    assert '"retry_calls": 0' in diagnostic
    assert '"fallback_calls": 0' in diagnostic
    assert "return 0 if out.get(\"response_received\") and out.get(\"text_ok\") else 1" in diagnostic
