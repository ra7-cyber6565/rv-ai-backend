"""Offline regression for scripts/audit_provider_bypass.py."""
from __future__ import annotations

from pathlib import Path

from scripts import audit_provider_bypass as audit


def test_real_repo_has_no_unapproved_direct_provider_surface():
    report = audit.scan(audit.ROOT)
    assert report.passed, report.hits


def test_direct_gemini_call_outside_allowlist_fails(tmp_path):
    (tmp_path / "api").mkdir()
    bad = tmp_path / "api" / "bad_route.py"
    bad.write_text(
        "import google.generativeai as genai\n"
        "answer = genai.GenerativeModel('x').generate_content('hello')\n",
        encoding="utf-8",
    )
    report = audit.scan(tmp_path)
    assert report.passed is False
    markers = {row["marker"] for row in report.hits}
    assert "google_sdk_import" in markers
    assert "gemini_generate" in markers


def test_allowed_provider_adapter_is_not_flagged(tmp_path):
    base = tmp_path / "research_engine"
    base.mkdir()
    allowed = base / "gemini_reasoning.py"
    allowed.write_text(
        "import google.generativeai as genai\n"
        "x = genai.GenerativeModel('x').generate_content('hello')\n",
        encoding="utf-8",
    )
    report = audit.scan(tmp_path)
    assert report.passed is True


def test_direct_openrouter_url_outside_router_fails(tmp_path):
    (tmp_path / "rag").mkdir()
    bad = tmp_path / "rag" / "old.py"
    bad.write_text(
        'URL = "https://openrouter.ai/api/v1/chat/completions"\n',
        encoding="utf-8",
    )
    report = audit.scan(tmp_path)
    assert report.passed is False
    assert any(row["marker"] == "openrouter_endpoint" for row in report.hits)


def test_comments_do_not_create_false_positive(tmp_path):
    (tmp_path / "api").mkdir()
    path = tmp_path / "api" / "comment.py"
    path.write_text(
        "# legacy example: google.generativeai and .generate_content(\n"
        "VALUE = 1\n",
        encoding="utf-8",
    )
    assert audit.scan(tmp_path).passed is True


def test_json_write_is_atomic(tmp_path):
    report = audit.BypassReport(
        schema_version=1,
        passed=False,
        scanned_files=1,
        allowlist=[],
        hits=[{"path": "api/x.py", "marker": "gemini_generate", "line": 2}],
    )
    target = tmp_path / "audit" / "provider_bypass.json"
    audit.write_report(target, report)
    assert target.is_file()
    assert not Path(str(target) + ".tmp").exists()
