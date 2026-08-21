"""Static integration audit for project namespace privacy wiring."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_main_exposes_session_router_and_project_readiness_without_static_client_secret():
    main = _read("main.py")
    assert "from api.session_routes import router as session_router" in main
    assert "include_router(session_router" in main
    assert '"X-Project-Token"' in main
    assert '"project_isolation": project_access.status()' in main
    assert "project_capability_tokens_ready" in main


def test_project_capability_is_server_issued_hmac_not_a_client_shared_secret():
    access = _read("utils/project_access.py")
    assert "hmac.new" in access
    assert "secrets.token_urlsafe" in access
    assert "secrets.token_bytes" in access
    assert "X-Project-Token" in access
    assert "ExclusiveProcessFileLock" in access
    assert "_PATH_LOCKS" in access


def test_public_project_scoped_entrypoints_require_project_guard():
    agent = _read("api/agent_routes.py")
    jobs = _read("api/job_routes.py")
    rag = _read("api/routes.py")

    assert agent.count("require_project_access(") >= 2
    assert "def chat(" in agent
    assert "def deep_research(" in agent
    assert "require_project_access(request.project_id, x_project_token)" in agent

    assert "def start_research_job(" in jobs
    assert "require_project_access(request.project_id, x_project_token)" in jobs

    # Six project-scoped RAG/media entrypoints currently use the guard.
    assert rag.count("require_project_access(") >= 6


def test_web_session_token_is_server_issued_header_only_and_memory_only():
    web = _read("web/index.html")
    low = web.lower()
    assert 'API+"/api/v1/session"' in web
    assert "data.project_id" in web
    assert "data.project_access_token" in web
    assert '"X-Project-Token":PROJECT.token' in web
    assert "localstorage" not in low
    assert "sessionstorage" not in low
    assert "project_access_token=" not in low
    assert "project_token=" not in low


def test_rate_guard_limits_session_minting_and_env_documents_it():
    guard = _read("utils/request_guard.py")
    env = _read(".env.example")
    assert '"/api/v1/session"' in guard
    assert "RATE_SESSION_PER_HOUR" in guard
    assert "RATE_SESSION_PER_HOUR=20" in env
    assert "RATE_JOB_POLL_PER_MINUTE=180" in env
