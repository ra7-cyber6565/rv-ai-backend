"""Static honesty regression for API release-state wording."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_api_info_does_not_claim_production_ready_during_foundation_phase():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "RV AI Backend - Production Ready" not in text
    assert "foundation_verification_pending" in text
    assert '"release_state": RELEASE_STATE' in text


def test_release_state_is_separate_from_runtime_health():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '"status": "degraded" if degraded else "healthy"' in text
    assert "RELEASE_STATE" in text
    # Healthy process/storage must not silently rewrite release readiness.
    health_tail = text.split("def health_check", 1)[-1]
    assert "RELEASE_STATE =" not in health_tail
