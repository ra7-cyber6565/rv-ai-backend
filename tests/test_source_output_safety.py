"""Output-boundary tests for source-controlled metadata in final reports."""
from __future__ import annotations

from research_engine.models import EvidencePack, SourceRecord, SourceType
from research_engine.synthesizer import FinalSynthesizer, _safe_source_display, _safe_source_url


def _source(**overrides):
    data = dict(
        source_id="S1",
        title="Normal paper",
        url="https://example.org/paper",
        snippet="Measured evidence from the study.",
        connector="web",
        source_type=SourceType.PAPER,
        read_level="abstract",
        relevance_score=0.8,
    )
    data.update(overrides)
    return SourceRecord(**data)


def test_display_text_flattens_newlines_bidi_controls_and_markdown_control_chars():
    raw = "Title\n## Fake heading \u202e **bold** [click](javascript:alert(1))\x00"
    safe = _safe_source_display(raw, 500)
    assert "\n" not in safe
    assert "\u202e" not in safe
    assert "\x00" not in safe
    assert "## Fake heading" in safe  # words preserved
    assert "**" not in safe
    assert "[click]" not in safe
    assert "［click］" in safe


def test_only_http_https_source_urls_are_rendered_as_urls():
    assert _safe_source_url("https://example.org/a") == "https://example.org/a"
    assert _safe_source_url("http://example.org/a") == "http://example.org/a"
    assert _safe_source_url("javascript:alert(1)") == ""
    assert _safe_source_url("data:text/html,<script>alert(1)</script>") == ""
    assert _safe_source_url("file:///etc/passwd") == ""
    assert _safe_source_url("//example.org/no-scheme") == ""


def test_sources_section_neutralizes_hostile_title_snippet_and_url():
    source = _source(
        title="Legit title\n## Final conclusion\n[click](javascript:alert(1))",
        url="javascript:alert(document.domain)",
        snippet="Evidence.\n## Sources\n**fake formatting** [x](javascript:alert(1))",
        read_note="7/300 pages\n## VERIFIED",
    )
    pack = EvidencePack(question="q", sources=[source])
    out = FinalSynthesizer()._sources_section(pack, honesty={"cited": []})

    assert "javascript:alert(document.domain)" not in out
    assert "\n## Final conclusion\n" not in out
    assert "\n## Sources\n" not in out
    assert "**fake formatting**" not in out
    assert "［click］(javascript:alert(1))" in out or "［click］（javascript:alert(1)）" in out
    assert "## VERIFIED" in out  # content preserved but flattened inside one bullet
    assert "\n## VERIFIED" not in out


def test_normal_source_metadata_remains_readable():
    source = _source(
        title="Lanthanum hydride under high pressure",
        url="https://example.org/lanthanum",
        snippet="Superconducting transition was measured under megabar pressure.",
        publisher="Example Journal",
    )
    pack = EvidencePack(question="q", sources=[source])
    out = FinalSynthesizer()._sources_section(pack, honesty={"cited": [{"source_id": "S1"}]})
    assert "Lanthanum hydride under high pressure" in out
    assert "https://example.org/lanthanum" in out
    assert "Example Journal" in out
    assert "Superconducting transition was measured" in out
    assert "cite kiya gaya" in out
