"""Offline regression for fail-closed admin/history endpoint protection."""
from __future__ import annotations

from fastapi import HTTPException

from utils import admin_guard


def test_admin_guard_disabled_when_backend_token_missing():
    env = {}
    assert admin_guard.admin_configured(env) is False
    assert admin_guard.admin_token_valid("anything", env) is False
    assert admin_guard.public_admin_status(env) == {"admin_endpoints_configured": False}


def test_short_backend_token_is_rejected_even_when_candidate_matches():
    env = {"INFINITY_ADMIN_TOKEN": "too-short"}
    assert admin_guard.admin_configured(env) is False
    assert admin_guard.admin_token_valid("too-short", env) is False


def test_strong_matching_token_is_accepted_without_disclosing_length_or_value():
    token = "A-strong-random-admin-token-1234567890"
    env = {"INFINITY_ADMIN_TOKEN": token}
    assert admin_guard.admin_configured(env) is True
    assert admin_guard.admin_token_valid(token, env) is True
    assert admin_guard.admin_token_valid(token + "x", env) is False
    public = admin_guard.public_admin_status(env)
    assert public == {"admin_endpoints_configured": True}
    assert token not in repr(public)
    assert "length" not in repr(public).lower()


def test_require_admin_returns_404_for_missing_or_bad_token(monkeypatch):
    token = "A-strong-random-admin-token-1234567890"
    monkeypatch.setenv("INFINITY_ADMIN_TOKEN", token)
    for candidate in (None, "wrong"):
        try:
            admin_guard.require_admin(candidate)
        except HTTPException as exc:
            assert exc.status_code == 404
            assert exc.detail == "Not found"
        else:
            raise AssertionError("invalid admin token must fail closed")


def test_require_admin_accepts_matching_token(monkeypatch):
    token = "A-strong-random-admin-token-1234567890"
    monkeypatch.setenv("INFINITY_ADMIN_TOKEN", token)
    assert admin_guard.require_admin(token) is None


def test_sensitive_server_metadata_routes_are_guarded_in_source_tree():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    agent = (root / "api" / "agent_routes.py").read_text(encoding="utf-8")
    jobs = (root / "api" / "job_routes.py").read_text(encoding="utf-8")
    projects = (root / "knowledge" / "routes.py").read_text(encoding="utf-8")

    assert "Depends(require_admin)" in agent
    assert "def get_history" in agent and "def clear_history" in agent
    assert "Depends(require_admin)" in jobs
    assert "def list_research_jobs" in jobs
    assert projects.count("Depends(require_admin)") >= 4
