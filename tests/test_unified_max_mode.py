from pathlib import Path
import importlib

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


def test_maximum_activates_full_company_plus_when_model_layer_is_usable(monkeypatch):
    _set_model_ready(monkeypatch, True)
    maximum = get_depth_config("MAXIMUM")
    marathon = get_depth_config("MARATHON")
    company_plus = get_depth_config("COMPANY_PLUS")

    _assert_marathon_strength(maximum, marathon)
    assert maximum.company_optional is True
    assert maximum.company_agents_configured == 6
    assert maximum.company_agents == 6
    assert maximum.gemini_calls == company_plus.gemini_calls == 10


def test_maximum_keeps_marathon_core_when_company_models_are_unavailable(monkeypatch):
    _set_model_ready(monkeypatch, False)
    maximum = get_depth_config("MAXIMUM")
    marathon = get_depth_config("MARATHON")

    _assert_marathon_strength(maximum, marathon)
    assert maximum.company_optional is True
    assert maximum.company_agents_configured == 6
    assert maximum.company_agents == 0
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


def test_unified_max_contract_is_durable_for_future_agents():
    text = Path("MAX_MODE_CONTRACT.md").read_text(encoding="utf-8")
    assert "exactly two research choices" in text
    assert "`ROLES[:6]` already contains `ROLES[:4]`" in text
    assert "capability inclusion, not duplicate execution" in text
    assert "Company+ availability must never disable the Marathon-strength core" in text
