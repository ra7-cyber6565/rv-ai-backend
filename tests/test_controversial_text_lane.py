"""Regression tests for the relevance-driven controversial/banned-text lane."""
from research_engine.controversial_texts import POLICY_PROMPT, build_lane
from research_engine.depth import get_depth_config
from research_engine.planner import ResearchPlanner
from research_engine.specialist_domains import prompt_block


def _connector_plan(question: str, mode: str = "MARATHON"):
    planner = ResearchPlanner()
    cls = planner.classify(question)
    return planner.connector_plan(cls, get_depth_config(mode), question)


def test_explicit_banned_books_always_open_lane_and_book_search():
    q = "Power aur propaganda ko samajhne ke liye banned books aur controversial texts bhi compare karo"
    plan = _connector_plan(q, "DEEP")
    lane = plan["controversial_text_lane"]

    assert lane["active"] is True
    assert lane["explicit"] is True
    assert lane["mode"] == "explicit"
    assert lane["verified"] is False
    assert lane["banned_status_is_truth_signal"] is False
    assert lane["legal_access_only"] is True
    assert lane["no_paywall_drm_password_bypass"] is True
    assert "internet_archive" in plan["books"]
    assert "open_library" in plan["books"]
    assert plan["book_queries"]
    assert plan["summary_queries"]
    assert "scholarly criticism" in plan["summary_queries"][0].lower()


def test_roman_hindi_ban_book_wording_is_understood():
    lane = build_lane("ban book bhi dekhna jo censorship aur power par ho", "censorship power")
    assert lane["active"] is True
    assert lane["explicit"] is True


def test_high_depth_humanities_can_auto_discover_without_user_saying_book():
    q = "Political power, propaganda, censorship aur ideology ka historical analysis karo"
    plan = _connector_plan(q, "MARATHON")
    lane = plan["controversial_text_lane"]

    assert lane["active"] is True
    assert lane["automatic_relevance"] is True
    assert lane["explicit"] is False
    assert len(lane["context_signals"]) >= 2
    assert plan["book_queries"]
    assert plan["summary_queries"]


def test_ordinary_medical_question_does_not_auto_open_sensational_text_lane():
    q = "cancer treatment resistance mechanisms aur clinical evidence kya kehte hain"
    plan = _connector_plan(q, "MARATHON")
    lane = plan["controversial_text_lane"]

    assert lane["active"] is False
    assert lane["automatic_relevance"] is False
    assert lane["explicit"] is False


def test_ordinary_science_question_stays_inactive_even_at_marathon_depth():
    lane = build_lane(
        "photosynthesis ke light reactions ka mechanism samjhao",
        "photosynthesis light reactions",
        question_types=["scientific"],
        high_depth=True,
    )
    assert lane["active"] is False
    assert lane["catalog_queries"] == []
    assert lane["review_queries"] == []


def test_lane_is_search_plan_not_evidence_and_never_uses_ban_as_truth_signal():
    lane = build_lane(
        "controversial books on censorship and propaganda compare karo",
        "censorship propaganda",
        question_types=["sociological"],
        high_depth=True,
    )
    assert lane["verified"] is False
    assert "search_plan_only" in lane["evidence_status"]
    assert lane["same_evidence_standard"] is True
    assert lane["original_unavailable_must_say_not_read"] is True
    assert lane["banned_status_is_truth_signal"] is False


def test_synthesis_policy_is_injected_when_lane_active():
    plan = {"connectors": {"controversial_text_lane": {"active": True}}}
    text = prompt_block(plan)
    assert "BANNED STATUS ≠ TRUTH SIGNAL" in text
    assert "legally accessible" in text
    assert "book/text was not actually accessed" in text
    assert "SAME citation, relevance, contradiction" in text


def test_synthesis_policy_is_not_injected_when_lane_inactive():
    plan = {"connectors": {"controversial_text_lane": {"active": False}}}
    assert POLICY_PROMPT not in prompt_block(plan)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
