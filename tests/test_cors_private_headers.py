"""Static CORS regression for private async-job polling."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_main_allows_job_capability_header_for_explicit_origins_only():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '"X-Research-Job-Token"' in text
    assert '"X-Infinity-Admin-Token"' in text
    assert 'allow_origins=CORS_ORIGINS' in text
    assert 'allow_origins=["*"]' not in text
    assert "allow_origins=['*']" not in text


def test_official_web_client_uses_header_not_authorization_query_param():
    text = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert '"X-Research-Job-Token":jobToken' in text
    assert "job_access_token=" not in text
