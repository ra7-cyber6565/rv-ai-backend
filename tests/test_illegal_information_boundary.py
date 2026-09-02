from types import SimpleNamespace

from safety.checks import check_safety, prepend_safety_notice, safety_prompt_appendix
from research_engine.depth import get_depth_config
from research_engine.planner import ResearchPlanner
from research_engine import specialist_domains


def test_illegal_subject_is_warn_and_explain_not_blanket_blocked():
    result = check_safety("Illegal smuggling kya hoti hai aur kanoon ise kyun rokta hai?")
    assert result["safe_to_proceed"] is True
    assert result["response_mode"] == "WARN_AND_EXPLAIN"
    assert result["allow_contextual_explanation"] is True
    assert result["actionable_wrongdoing_allowed"] is False
    categories = {row.get("category") for row in result["flags"]}
    assert "HIGH_RISK" in categories
    assert "LEGAL_RISK" in categories


def test_prompt_keeps_context_but_forbids_operational_wrongdoing():
    boundary = safety_prompt_appendix(check_safety(
        "Ransomware crime ka history, risk aur defensive analysis samjhao"
    ))
    low = boundary.lower()
    assert "do not hide or refuse the whole subject" in low
    assert "historical/social context" in low
    assert "defensive/security analysis" in low
    assert "do not provide operational instructions" in low
    assert "step-by-step execution" in low
    assert "detection-bypass" in low


def test_final_warning_is_deterministic_and_does_not_delete_answer():
    safety = check_safety("Illegal fraud ke legal consequences explain karo")
    original = "## Seedha jawab\nFraud ke legal consequences jurisdiction par depend karte hain."
    rendered = prepend_safety_notice(original, safety)
    assert rendered.startswith("> ⚠️ **Safety / legal warning:**")
    assert original in rendered
    assert "use na karein" in rendered


def test_planner_carries_same_boundary_into_research_plan():
    planner = ResearchPlanner()
    plan = planner.plan(
        "Smuggling illegal kyun ho sakti hai? history aur law explain karo",
        get_depth_config("DEEP"),
    )
    boundary = plan["connectors"]["safety_information_boundary"]
    assert boundary["response_mode"] == "WARN_AND_EXPLAIN"
    assert boundary["actionable_wrongdoing_allowed"] is False
    prompt = specialist_domains.prompt_block(plan)
    assert "SAFETY / LEGAL INFORMATION BOUNDARY" in prompt
    assert "Do NOT hide or refuse the whole subject" in prompt


def test_non_specialist_high_risk_question_still_gets_visible_report_warning():
    planner = ResearchPlanner()
    question = "Illegal smuggling kya hoti hai aur uske legal risks kya hain?"
    plan = planner.plan(question, get_depth_config("DEEP"))
    report = specialist_domains.build_evidence_lane_report(
        question, plan, SimpleNamespace(sources=[])
    )
    assert report.get("safety_information_boundary")
    rendered = specialist_domains.render_evidence_lane_report(report)
    assert "## Safety / legal boundary" in rendered
    assert "Safety / legal warning" in rendered
    assert "execute/optimize" in rendered


def test_normal_research_question_is_unchanged_by_illegal_boundary():
    safety = check_safety("Photosynthesis ka mechanism evidence ke saath explain karo")
    assert safety["response_mode"] == "NORMAL"
    assert safety_prompt_appendix(safety) == ""
    assert prepend_safety_notice("normal answer", safety) == "normal answer"

    planner = ResearchPlanner()
    plan = planner.plan(
        "Photosynthesis ka mechanism evidence ke saath explain karo",
        get_depth_config("DEEP"),
    )
    assert plan["connectors"]["safety_information_boundary"]["response_mode"] == "NORMAL"
    assert "SAFETY / LEGAL INFORMATION BOUNDARY" not in specialist_domains.prompt_block(plan)
