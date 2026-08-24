"""Offline adversarial checks for Marathon multilingual specialist research."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.answer_order import LAB_HEADING, section_start  # noqa: E402
from research_engine.depth import get_depth_config  # noqa: E402
from research_engine.models import EvidencePack, SourceRecord  # noqa: E402
from research_engine.models import SourceType  # noqa: E402
from research_engine.multilingual_research import (  # noqa: E402
    build_multilingual_plan)
from research_engine.planner import ResearchPlanner  # noqa: E402
from research_engine.source_discovery import SourceDiscovery  # noqa: E402
from research_engine.specialist_domains import (  # noqa: E402
    build_evidence_lane_report,
    build_specialist_plan,
    prompt_block,
    render_evidence_lane_report,
    specialist_classification,
)
from research_engine.synthesizer import FinalSynthesizer  # noqa: E402


def _source(source_id: str, *, kind: SourceType, url: str, title: str) -> SourceRecord:
    source = SourceRecord(
        source_id=source_id,
        source_type=kind,
        url=url,
        title=title,
        snippet="Relevant source text for the requested specialist topic.",
        read_level="abstract" if kind == SourceType.PAPER else "snippet",
        relevance_score=0.85,
        quality_score=0.75,
    )
    return source


def test_metaphysics_does_not_trigger_physics_by_substring():
    cls = ResearchPlanner().classify("Metaphysics aur consciousness kya hai?")
    assert "philosophical" in cls["all_detected_types"]
    assert "philosophy_metaphysics" in cls["specialist_profile_keys"]
    assert "Physics" not in cls["relevant_fields"]


def test_occult_sciences_does_not_become_ordinary_science():
    cls = ResearchPlanner().classify("Occult sciences aur Hermeticism ka history batao")
    assert cls["is_scientific"] is False
    assert "scientific" not in cls["all_detected_types"]
    assert cls["specialist_profile_keys"] == ["esotericism_occult_history"]
    assert "Western Esotericism" in cls["relevant_fields"]


def test_jung_shadow_work_gets_primary_history_and_modern_evidence_boundary():
    plan = build_specialist_plan(
        "Carl Jung shadow work aur individuation",
        "Carl Jung shadow work individuation",
    )
    assert "jung_depth_psychology" in plan["profile_keys"]
    assert "primary_historical_text" in plan["expected_lanes"]
    assert "empirical_science" in plan["expected_lanes"]
    assert any("social-media" in caution for caution in plan["cautions"])


def test_cia_question_has_bounded_official_archive_queries_and_truth_warning():
    plan = build_specialist_plan(
        "CIA documents remote viewing ki sachchai",
        "CIA documents remote viewing",
    )
    queries = plan["official_archive_queries"]
    assert 1 <= len(queries) <= 3
    assert queries[0].startswith("site:cia.gov/readingroom")
    assert any("site:archives.gov" in query for query in queries)
    assert "official_document_record" in plan["expected_lanes"]
    assert any("not proof" in rule.lower() for rule in plan["claim_boundary_rules"])


def test_source_discovery_builds_archive_tasks_without_replacing_normal_web():
    planner = ResearchPlanner()
    cls = planner.classify("CIA declassified documents Project Stargate")
    connectors = planner.connector_plan(cls, get_depth_config("MARATHON"),
                                        "CIA declassified documents Project Stargate")
    tasks = SourceDiscovery()._tasks(
        ["CIA Project Stargate"], connectors, max_per_connector=2, max_web=6,
    )
    labels = [label for label, _ in tasks]
    assert labels.count("web_chain") == 1
    assert 1 <= labels.count("official_archive_web") <= 3


def test_dimag_tej_routes_to_cognitive_research_and_relevant_datasets_only():
    planner = ResearchPlanner()
    plan = planner.plan("dimag tej kaise kare", get_depth_config("MARATHON"))
    assert plan["specialist"]["profile_keys"] == ["mind_cognition"]
    assert any("cognitive performance" in query for query in plan["queries"])
    assert set(plan["connectors"]["datasets"]) <= {"zenodo", "data_gov", "who_gho"}
    assert "world_bank" not in plan["connectors"]["datasets"]
    assert plan["specialist"]["multilingual"]["translation_status"] == \
        "glossary_assisted_search_only"


def test_hindi_and_original_language_are_preserved_without_fake_translation():
    plan = build_multilingual_plan(
        "दिमाग तेज कैसे करें और अवचेतन मन क्या है",
        "brain cognitive performance subconscious mind",
        ["memory attention learning"],
    )
    assert plan["primary"] == "hindi_or_related_devanagari"
    assert plan["original_preserved"] is True
    assert plan["translation_status"] == "glossary_assisted_search_only"
    assert "cognitive performance" in plan["english_search_terms"]
    assert "subconscious mind" in plan["english_search_terms"]
    assert "not full-text translation" in plan["full_text_language_policy"]
    assert plan["paywall_or_copyright_bypass"] is False


def test_unmapped_non_english_language_is_marked_translation_required():
    plan = build_multilingual_plan("未知の精神研究", "精神 research", [])
    assert plan["original_preserved"] is True
    assert plan["translation_status"] == \
        "translation_required_for_semantic_full_text_review"
    assert not plan["matched_glossary_terms"]


def test_frequency_hertz_and_spiritual_vibration_are_not_same_claim_type():
    measured = specialist_classification("528 Hz binaural healing frequency claim")
    symbolic = specialist_classification("spiritual frequency aur vibration")
    assert "scientific" in measured["question_types"]
    assert "scientific" not in symbolic["question_types"]
    assert "frequency_claims" in measured["profile_keys"]
    assert "frequency_claims" in symbolic["profile_keys"]


def test_engineering_vibration_does_not_activate_spiritual_frequency_profile():
    cls = specialist_classification(
        "Induction motor bearing failure vibration monitoring signal analysis"
    )
    assert "frequency_claims" not in cls["profile_keys"]


def test_conspiracy_and_secret_society_profiles_require_allegation_lane():
    cls = specialist_classification(
        "Freemasonry secret societies New World Order conspiracy theory"
    )
    assert "secret_societies_history" in cls["profile_keys"]
    assert "conspiracy_claims" in cls["profile_keys"]
    assert "allegation_or_conspiracy_claim" in cls["expected_lanes"]
    assert "sociological" in cls["question_types"]


def test_ambiguous_pix_etma_is_not_given_an_invented_mapping():
    plan = build_specialist_plan(
        "spirituality aur pix etma ka relation",
        "spirituality pix etma relation",
    )
    assert plan["active"] is True
    assert plan["unknown_terms"] == ["pix etma"]
    block = prompt_block({"specialist": plan})
    assert "meaning invent mat karo" in block
    assert "pix etma" in block


def test_marathon_preset_is_bounded_deep():
    config = get_depth_config("MARATHON")
    assert config.name == "MARATHON"
    assert config.gemini_calls == 4
    assert config.max_sources == 40
    assert config.max_rounds == 5
    assert config.max_fulltext == 16
    assert config.discovery_seconds == 360
    assert config.require_all_rounds is True
    assert config.research_process_target_percent == 90
    assert config.use_books is True


def test_evidence_lane_report_separates_official_paper_book_and_hypothesis():
    question = "CIA documents, Hermeticism aur consciousness"
    planner = ResearchPlanner()
    plan = planner.plan(question, get_depth_config("MARATHON"))
    pack = EvidencePack(
        question=question,
        sources=[
            _source("S1", kind=SourceType.WEB,
                    url="https://www.cia.gov/readingroom/document/abc",
                    title="Declassified record"),
            _source("S2", kind=SourceType.PAPER,
                    url="https://doi.org/10.0000/example",
                    title="Consciousness experiment"),
            _source("S3", kind=SourceType.BOOK,
                    url="https://archive.org/details/hermetic-text",
                    title="Historical Hermetic text"),
        ],
        reasoning_planned=1,
        reasoning_done=1,
    )
    report = build_evidence_lane_report(question, plan, pack)
    lanes = {row["key"]: row for row in report["lanes"]}
    assert lanes["official_document_record"]["source_ids"] == ["S1"]
    assert lanes["empirical_science"]["source_ids"] == ["S2"]
    assert lanes["traditional_belief_text"]["source_ids"] == ["S3"]
    assert lanes["app_original_hypothesis"]["source_count"] == 0
    rendered = render_evidence_lane_report(report)
    assert "document contents are not automatically true" in rendered
    # §12 (2026-08-22) — lane report user ko app ki apni soch ka SAHI section
    # naam batata hai. Pehle yahan "Humari Hypotheses" tha, jo report mein ab
    # exist hi nahi karta — reader ko galat naam pakadaya jaa raha tha.
    assert LAB_HEADING in rendered
    assert "Humari Hypotheses" not in rendered
    assert "UNTESTED" in rendered


def test_synthesizer_visibly_inserts_lane_section_before_app_hypotheses():
    question = "CIA documents aur Hermeticism"
    planner = ResearchPlanner()
    plan = planner.plan(question, get_depth_config("MARATHON"))
    pack = EvidencePack(
        question=question,
        sources=[_source("S1", kind=SourceType.WEB,
                         url="https://www.cia.gov/readingroom/document/abc",
                         title="Official record")],
        reasoning_planned=1,
        reasoning_done=1,
    )
    specialist = build_evidence_lane_report(question, plan, pack)
    report = FinalSynthesizer().assemble(
        gemini_answer=(
            "## Seedha jawab\nEvidence limited hai; official record aur historical "
            "tradition ko alag samajhna zaroori hai. Research, evidence, source, "
            "inference aur hypothesis ek hi proof level nahi hain.\n\n"
            "## Research se kya pata chala?\n### Fact\nDocument archive mein hai.\n"
            "### Inference\nContent ki sachchai alag check hogi.\n\n"
            "## Evidence kya kehta hai?\nOfficial provenance signal mila.\n\n"
            "## Iske against kya mila?\nIndependent confirmation limited hai.\n\n"
            "## Kya abhi unknown hai?\nDocument ke claims ka outcome unknown hai.\n\n"
            "## Final conclusion\nProvenance aur truth ko alag rakho."
        ),
        pack=pack,
        evidence_level="WEAK",
        confidence_note="Sirf ek source hai.",
        contradictions=[],
        hypotheses=[],
        verification={},
        coverage=pack.coverage_report(),
        honesty={},
        consensus={},
        specialist_report=specialist,
    )
    # §12 (2026-08-22) — section ki jagah ab canonical key se dekhi jaati hai.
    #
    # Pehle yahan literal `report.find("## Humari Hypotheses")` tha. App ki apni
    # soch ki heading `## APP ORIGINAL RESEARCH LAB` ho jaane ke baad wo find()
    # hamesha -1 deta tha, isliye `0 < lane_pos < -1` fail hona chahiye tha —
    # par ye file pytest-style thi aur sandbox mein chalti hi nahi thi, to
    # failure chhupa raha. Aakhir ka kram bhi §12 ke hisaab se badla gaya hai:
    # pehle audit, PHIR Sources (pehle ulta tha).
    lane_pos = report.find("## Evidence ki alag-alag lanes")
    lab_pos = section_start(report, "original_lab")
    audit_pos = section_start(report, "audit")
    source_pos = section_start(report, "sources")
    assert 0 < lane_pos < lab_pos, (lane_pos, lab_pos)
    assert lab_pos < audit_pos < source_pos, (lab_pos, audit_pos, source_pos)
    # Sources aakhri section rehna chahiye
    assert source_pos == max(section_start(report, key) for key in
                             ("direct_answer", "established_knowledge",
                              "supporting_evidence", "counterevidence",
                              "calculations", "unknowns", "conclusion",
                              "original_lab", "audit", "sources"))


def main() -> int:
    """
    Direct runner (2026-08-22).

    Ye file pytest-style thi aur sandbox mein pytest nahi hai, isliye
    `python3 tests/test_specialist_research.py` chup-chaap exit 0 deta tha —
    ek asli failure (purani `## Humari Hypotheses` heading) is chuppi mein
    chhupa hua tha. Ab direct chalane par bhi sach dikhta hai.
    """
    failed = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        try:
            func()
        except AssertionError as exc:                  # noqa: PERF203
            failed += 1
            print(f"  [FAIL] {name} -> {exc}")
        except Exception as exc:                       # noqa: BLE001
            failed += 1
            print(f"  [ERROR] {name} -> {type(exc).__name__}: {exc}")
        else:
            print(f"  [PASS] {name}")
    print(f"\n{'FAIL' if failed else 'ok'} — {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
