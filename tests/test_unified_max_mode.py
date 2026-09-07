from pathlib import Path

from research_engine.depth import get_depth_config
from research_engine.research_company import ROLES


def test_maximum_is_unified_strongest_bounded_preset():
    maximum = get_depth_config("MAXIMUM")
    marathon = get_depth_config("MARATHON")
    company_plus = get_depth_config("COMPANY_PLUS")

    assert maximum.name == "MAXIMUM"
    assert maximum.max_rounds == marathon.max_rounds == 5
    assert maximum.max_sources == marathon.max_sources == 40
    assert maximum.max_fulltext == marathon.max_fulltext == 16
    assert maximum.discovery_seconds == marathon.discovery_seconds == 360
    assert maximum.require_all_rounds is True
    assert maximum.research_process_target_percent == 90
    assert maximum.company_agents == 6
    assert maximum.gemini_calls == company_plus.gemini_calls == 10
    assert maximum.use_papers is True
    assert maximum.use_books is True
    assert maximum.use_datasets is True
    assert maximum.use_patents is True
    assert maximum.use_red_team is True


def test_six_worker_max_contains_original_company_four_plus_two_extensions():
    roles = [name for name, _instruction in ROLES]
    assert roles[:4] == ["evidence", "validation", "mechanism", "red_team"]
    assert roles[4:6] == ["data_quality", "implementation"]


def test_public_ui_contract_is_chat_and_max_only():
    source = Path("main.py").read_text(encoding="utf-8")
    replacement = (
        '<button class="on" data-mode="QUICK">Chat</button>'
        '\n'
        '        \'    <button data-mode="MAXIMUM">Max</button>'
    )
    # The response transformer must expose the two public choices and must use
    # the whole mode container as its replacement boundary.
    assert 'r\'<div class="modes">.*?</div>\'' in source
    assert 'data-mode="QUICK">Chat</button>' in source
    assert 'data-mode="MAXIMUM">Max</button>' in source
    assert 'count=1' in source


def test_unified_max_contract_is_durable_for_future_agents():
    text = Path("MAX_MODE_CONTRACT.md").read_text(encoding="utf-8")
    assert "exactly two research choices" in text
    assert "ROLES[:6] already contains `ROLES[:4]`" in text
    assert "capability inclusion, not duplicate execution" in text
