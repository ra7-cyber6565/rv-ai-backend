"""Static honesty regression for API release-state wording."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_api_info_does_not_claim_production_ready_during_foundation_phase():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "RV AI Backend - Production Ready" not in text
    assert 'RELEASE_STATE = "foundation_verification_pending"' in text
    assert '"release_state": RELEASE_STATE' in text


def test_release_state_cannot_be_promoted_by_environment_variable_alone():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    # A public deployment must not become "production_ready" merely because an
    # env var was mistyped/set. Promotion needs a reviewed code/proof change.
    assert 'os.getenv("INFINITY_RELEASE_STATE"' not in text
    assignment = text.split("RELEASE_STATE =", 1)[1].splitlines()[0]
    assert "production_ready" not in assignment


def test_release_state_is_separate_from_runtime_health():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '"status": "degraded" if degraded else "healthy"' in text
    assert "RELEASE_STATE" in text
    # Healthy process/storage must not silently rewrite release readiness.
    health_tail = text.split("def health_check", 1)[-1]
    assert "RELEASE_STATE =" not in health_tail


def test_public_api_uses_sanitized_storage_status_not_internal_mapping():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "public_storage_status" in text
    runtime = text.split("def _runtime_safety_status", 1)[-1].split("@app.get", 1)[0]
    assert '"storage": public_storage_status()' in runtime
    assert '"storage": storage_status()' not in runtime
    assert '"storage": STORAGE_STATUS' not in runtime
