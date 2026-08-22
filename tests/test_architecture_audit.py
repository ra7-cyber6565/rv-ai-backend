"""Regression tests for scripts/audit_architecture.py.

These tests are offline and mostly exercise the audit helpers against temporary
files, so the audit cannot become a rubber stamp that always says PASS.
"""
from __future__ import annotations

from pathlib import Path

from scripts import audit_architecture as audit


def test_real_repository_audit_has_all_expected_check_names():
    report = audit.run_audit()
    names = {row["name"] for row in report.checks}
    assert "required-production-and-test-files" in names
    assert "honesty:release-state-not-faked" in names
    assert "safety:zero-cost-provider-chain" in names
    assert "resilience:quota-does-not-blank-answer" in names
    assert "resilience:cross-request-provider-cooldown" in names
    assert "security:project-namespace-capability" in names
    assert "security:async-job-capability" in names
    assert "storage:bounded-and-verified" in names
    assert "security:no-wildcard-cors" in names
    assert "security:no-obvious-credential-literals" in names
    assert any(name.startswith("pipeline-order:") for name in names)


def test_architecture_audit_wires_cross_domain_and_network_safety_into_release_gate():
    report = audit.run_audit()
    required = next(
        row for row in report.checks
        if row["name"] == "required-production-and-test-files"
    )
    gate = next(
        row for row in report.checks
        if row["name"] == "wiring:scripts/run_foundation_gate.py"
    )
    assert required["passed"] is True, required["detail"]
    assert gate["passed"] is True, gate["detail"]


def test_order_check_fails_when_verification_moves_before_discovery(monkeypatch, tmp_path):
    target = tmp_path / "pipeline.py"
    target.write_text("verify()\ndiscover()\nsynthesize()\n", encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    result = audit._ordered(
        "pipeline.py",
        (("discover", "discover()"), ("verify", "verify()"), ("synth", "synthesize()")),
    )
    assert result.passed is False


def test_required_files_check_fails_closed(monkeypatch, tmp_path):
    (tmp_path / "exists.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    result = audit._required_files(("exists.py", "missing.py"))
    assert result.passed is False
    assert "missing.py" in result.detail


def test_release_honesty_rejects_production_ready_claim(monkeypatch, tmp_path):
    (tmp_path / "main.py").write_text(
        'RELEASE_STATE="foundation_verification_pending"\n'
        'data={"release_state": RELEASE_STATE}\n'
        'status={"status": "degraded" if degraded else "healthy"}\n'
        'message="RV AI Backend - Production Ready"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    result = audit._release_honesty()
    assert result.passed is False
    assert "production_ready_claim=True" in result.detail


def test_release_honesty_accepts_separate_health_and_release_state(monkeypatch, tmp_path):
    (tmp_path / "main.py").write_text(
        'RELEASE_STATE="foundation_verification_pending"\n'
        'data={"release_state": RELEASE_STATE}\n'
        'health={"status": "degraded" if degraded else "healthy"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    result = audit._release_honesty()
    assert result.passed is True


def test_provider_cooldown_audit_fails_when_facade_is_not_wired(monkeypatch, tmp_path):
    (tmp_path / "utils").mkdir()
    (tmp_path / "research_engine").mkdir()
    (tmp_path / ".env.example").write_text("PROVIDER_HEALTH_RATE_LIMIT_SECONDS=180\n", encoding="utf-8")
    (tmp_path / "utils" / "provider_health.py").write_text(
        "class ProviderHealthRegistry: pass\ndef record_failure(): pass\ndef record_success(): pass\n",
        encoding="utf-8",
    )
    (tmp_path / "utils" / "reasoning_status.py").write_text("temporarily_skipped=True\n", encoding="utf-8")
    (tmp_path / "research_engine" / "reasoning_router_integrated.py").write_text(
        "# missing health wrapper on purpose\n", encoding="utf-8"
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    result = audit._provider_cooldown_wired()
    assert result.passed is False
    assert "fallback-provider wrapper" in result.detail


def test_project_isolation_audit_fails_when_web_forgets_project_header(monkeypatch, tmp_path):
    for folder in ("api", "utils", "web"):
        (tmp_path / folder).mkdir()
    (tmp_path / "main.py").write_text(
        'include_router(session_router)\n"X-Project-Token"\n'
        'status={"project_isolation": project_access.status()}\n',
        encoding="utf-8",
    )
    (tmp_path / "api" / "session_routes.py").write_text(
        "project_access.create()\nproject_capability_tokens_ready\n",
        encoding="utf-8",
    )
    (tmp_path / "utils" / "project_access.py").write_text(
        "hmac.new\nsecrets.token_urlsafe\nproject_capability.key\nExclusiveProcessFileLock\n",
        encoding="utf-8",
    )
    (tmp_path / "utils" / "project_guard.py").write_text(
        "project_access.verify\nstatus_code=404\n", encoding="utf-8"
    )
    (tmp_path / "api" / "agent_routes.py").write_text(
        "require_project_access(request.project_id, x_project_token)\n", encoding="utf-8"
    )
    (tmp_path / "api" / "job_routes.py").write_text(
        "require_project_access(request.project_id, x_project_token)\n", encoding="utf-8"
    )
    (tmp_path / "api" / "routes.py").write_text(
        "require_project_access(project_id, x_project_token)\n", encoding="utf-8"
    )
    # Session exists, but the private bearer header is deliberately missing.
    (tmp_path / "web" / "index.html").write_text(
        'API+"/api/v1/session"\nasync function projectPost(){}\nattempt<2\n', encoding="utf-8"
    )
    (tmp_path / "utils" / "request_guard.py").write_text(
        '"/api/v1/session"\nRATE_SESSION_PER_HOUR\n', encoding="utf-8"
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    result = audit._project_isolation()
    assert result.passed is False
    assert "web project bearer header" in result.detail


def test_async_job_privacy_audit_fails_without_capability_verification(monkeypatch, tmp_path):
    (tmp_path / "api").mkdir()
    (tmp_path / "utils").mkdir()
    (tmp_path / "api" / "job_routes.py").write_text(
        "X-Research-Job-Token\n_authorized_job\nDepends(require_admin)\n",
        encoding="utf-8",
    )
    (tmp_path / "utils" / "job_access.py").write_text(
        "hmac.new\nsecrets.token_bytes\nresearch_job_capability.key\nExclusiveProcessFileLock\ncompare_digest\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    result = audit._async_job_privacy()
    assert result.passed is False
    assert "capability verification" in result.detail


def test_secret_scan_detects_obvious_literal_in_production(monkeypatch, tmp_path):
    (tmp_path / "research_engine").mkdir()
    bad = tmp_path / "research_engine" / "bad.py"
    bad.write_text('TOKEN = "AIza' + ('A' * 30) + '"\n', encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    result = audit._obvious_secret_scan()
    assert result.passed is False
    assert "bad.py" in result.detail


def test_secret_scan_does_not_treat_variable_name_as_secret(monkeypatch, tmp_path):
    (tmp_path / "utils").mkdir()
    good = tmp_path / "utils" / "config.py"
    good.write_text('name = "GEMINI_API_KEY"\nvalue = os.getenv(name, "")\n', encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    result = audit._obvious_secret_scan()
    assert result.passed is True


def test_wildcard_cors_is_rejected(monkeypatch, tmp_path):
    (tmp_path / "utils").mkdir()
    (tmp_path / "main.py").write_text('allow_origins=["*"]\n', encoding="utf-8")
    (tmp_path / "utils" / "security_config.py").write_text(
        "def allowed_cors_origins(): return []\n", encoding="utf-8"
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    result = audit._no_wildcard_cors()
    assert result.passed is False


def test_json_report_write_is_atomic_shape(monkeypatch, tmp_path):
    path = tmp_path / "audit" / "architecture.json"
    report = audit.AuditReport(
        schema_version=1,
        passed=False,
        checks=[{"name": "x", "passed": False, "detail": "broken"}],
        failed=["x"],
    )
    audit._write_json(path, report)
    assert path.is_file()
    assert not Path(str(path) + ".tmp").exists()
    text = path.read_text(encoding="utf-8")
    assert '"passed": false' in text.lower()
