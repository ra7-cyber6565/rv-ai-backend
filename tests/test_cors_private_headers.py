"""Static CORS regression for private project/job capability headers."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_main_allows_private_capability_headers_for_explicit_origins_only():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '"X-Project-Token"' in text
    assert '"X-Research-Job-Token"' in text
    assert '"X-Infinity-Admin-Token"' in text
    assert 'allow_origins=CORS_ORIGINS' in text
    assert 'allow_origins=["*"]' not in text
    assert "allow_origins=['*']" not in text


def test_official_web_client_uses_headers_not_capability_query_params():
    text = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    low = text.lower()
    assert '"X-Project-Token":PROJECT.token' in text
    assert '"X-Research-Job-Token":jobToken' in text
    assert "job_access_token=" not in low
    assert "project_access_token=" not in low
    assert "project_token=" not in low
