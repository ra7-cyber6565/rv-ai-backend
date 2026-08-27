"""Presentation regression: process coverage must not masquerade as answer quality."""
from __future__ import annotations

import os

# Importing main is safe in Foundation's forced-offline environment and tests the
# exact HTML transform served by GET / rather than merely grepping source code.
os.environ.setdefault("ZERO_COST_ONLY", "true")
os.environ.setdefault("GEMINI_API_KEY", "")
os.environ.setdefault("GEMINI_ZERO_COST_CONFIRMED", "false")
os.environ.setdefault("CLOUD_ARCHIVE_PROVIDER", "none")
os.environ.setdefault("INFINITY_OFFLINE_TEST", "true")

import main  # noqa: E402


def _html() -> str:
    return main._website_html()


def test_terminal_lifecycle_label_does_not_claim_research_complete():
    html = _html()
    assert '"COMPLETE":"Research run finished"' in html
    assert 'COMPLETE:"Research complete"' not in html


def test_audit_ui_names_process_and_semantic_coverage_separately():
    html = _html()
    assert "function qualityMetricLines(data){" in html
    assert "research_process_coverage_percent" in html
    assert "structured_answer_semantic" in html
    assert "semantic_coverage_percent" in html
    assert "Research-process coverage:" in html
    assert "Semantic requested-content coverage:" in html
    assert "process score ko answer-quality/truth score mat maano" in html
    assert "for(const metric of qualityMetricLines(data))bits.push(metric);" in html


def test_metric_copy_explicitly_denies_probability_interpretation():
    html = _html()
    assert "answer ki truth/quality probability nahi" in html
    assert "requested parts ki substantive delivery; truth probability nahi" in html
