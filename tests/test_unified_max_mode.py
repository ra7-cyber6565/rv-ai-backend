from pathlib import Path
import importlib
import os
import subprocess
import sys

from research_engine.depth import get_depth_config
from research_engine.research_company import ROLES


def _set_model_ready(monkeypatch, ready: bool):
    status_module = importlib.import_module("utils.reasoning_status")
    monkeypatch.setattr(
        status_module,
        "reasoning_status",
        lambda: {"has_model_layer_usable_now": ready},
    )


def _assert_marathon_strength(maximum, marathon):
    assert maximum.name == "MAXIMUM"
    assert maximum.max_rounds == marathon.max_rounds == 5
    assert maximum.max_sources == marathon.max_sources == 40
    assert maximum.max_fulltext == marathon.max_fulltext == 16
    assert maximum.discovery_seconds == marathon.discovery_seconds == 360
    assert maximum.require_all_rounds is True
    assert maximum.research_process_target_percent == 90
    assert maximum.use_papers is True
    assert maximum.use_books is True
    assert maximum.use_datasets is True
    assert maximum.use_patents is True
    assert maximum.use_red_team is True


def test_maximum_activates_full_company_plus_and_round2_when_model_layer_is_usable(monkeypatch):
    _set_model_ready(monkeypatch, True)
    maximum = get_depth_config("MAXIMUM")
    marathon = get_depth_config("MARATHON")
    company_plus = get_depth_config("COMPANY_PLUS")

    _assert_marathon_strength(maximum, marathon)
    assert maximum.company_optional is True
    assert maximum.company_agents_configured == 6
    assert maximum.company_agents == 6
    assert maximum.company_cross_review_agents == 6
    assert company_plus.gemini_calls == 10
    assert maximum.gemini_calls == 16
    assert maximum.to_dict()["company_cross_review_agents"] == 6


def test_maximum_keeps_marathon_core_when_company_models_are_unavailable(monkeypatch):
    _set_model_ready(monkeypatch, False)
    maximum = get_depth_config("MAXIMUM")
    marathon = get_depth_config("MARATHON")

    _assert_marathon_strength(maximum, marathon)
    assert maximum.company_optional is True
    assert maximum.company_agents_configured == 6
    assert maximum.company_agents == 0
    assert maximum.company_cross_review_agents == 0
    # Six impossible worker calls are removed, but the four-call Marathon/chief
    # reasoning share survives. Missing Company must never erase core Max power.
    assert maximum.gemini_calls == marathon.gemini_calls == 4


def test_six_worker_max_contains_original_company_four_plus_two_extensions():
    roles = [name for name, _instruction in ROLES]
    assert roles[:4] == ["evidence", "validation", "mechanism", "red_team"]
    assert roles[4:6] == ["data_quality", "implementation"]


def test_public_ui_contract_is_chat_and_max_only():
    source = Path("main.py").read_text(encoding="utf-8")
    # The response transformer replaces the whole mode selector with exactly
    # the two public choices. Legacy backend names can still exist elsewhere.
    assert '<div class="modes">.*?</div>' in source
    assert 'data-mode="QUICK">Chat</button>' in source
    assert 'data-mode="MAXIMUM">Max</button>' in source
    assert "Public users intentionally see only two choices: Chat and Max." in source


def test_actual_served_html_exposes_exactly_chat_and_max(tmp_path):
    """Execute the real server-side HTML transform in an isolated process."""
    env = os.environ.copy()
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GEMINI_API_KEYS",
        "GEMINI_API_KEY_BACKUP",
        "GEMINI_API_KEY_FALLBACK",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        env.pop(name, None)
    env["ZERO_COST_ONLY"] = "true"
    env["INFINITY_DURABLE_ROOT"] = str(tmp_path / "durable")
    env["INFINITY_EPHEMERAL_ROOT"] = str(tmp_path / "ephemeral")
    code = r'''
import re
import main
html = main._website_html()
block = re.search(r'<div class="modes">(.*?)</div>', html, re.S)
assert block, "served mode selector missing"
modes = re.findall(r'data-mode="([^"]+)"', block.group(1))
assert modes == ["QUICK", "MAXIMUM"], modes
for legacy in ("DEEP", "MARATHON", "COMPANY", "COMPANY_PLUS", "CUSTOM"):
    assert f'data-mode="{legacy}"' not in block.group(1)
'''
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path.cwd()),
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_unified_max_contract_is_durable_for_future_agents():
    text = Path("MAX_MODE_CONTRACT.md").read_text(encoding="utf-8")
    assert "exactly two research choices" in text
    assert "`ROLES[:6]` already contains `ROLES[:4]`" in text
    assert "capability inclusion, not duplicate execution" in text
    assert "Company+ availability must never disable the Marathon-strength core" in text
