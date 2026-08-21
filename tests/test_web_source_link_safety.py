"""Static regression for source-link scheme safety in the shipped web client."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "index.html"


def test_web_has_explicit_http_https_source_url_allowlist():
    text = WEB.read_text(encoding="utf-8")
    assert "function safeHttpUrl" in text
    assert 'u.protocol==="http:"||u.protocol==="https:"' in text
    assert "href=safeHttpUrl(s.url)" in text


def test_source_url_is_escaped_only_after_scheme_validation():
    text = WEB.read_text(encoding="utf-8")
    render = text[text.index("function renderResearch"):text.index("async function submit")]
    assert "href=safeHttpUrl(s.url)" in render
    assert "url=href?esc(href):\"\"" in render
    assert "rel=\"noopener noreferrer\"" in render
    # Regression target: escaping alone does not neutralize javascript: URLs.
    assert 'url=s.url?esc(s.url):""' not in render


def test_model_answer_is_html_escaped_before_innerhtml_rendering():
    text = WEB.read_text(encoding="utf-8")
    assert "function htmlText(s){return esc(s)" in text
    assert "function answer(el,text){el.innerHTML=htmlText(text)" in text
