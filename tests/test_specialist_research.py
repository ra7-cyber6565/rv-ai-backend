"""Offline adversarial checks for Marathon multilingual specialist research."""
from __future__ import annotations

from research_engine.depth import get_depth_config
from research_engine.models import EvidencePack, SourceRecord, SourceType
from research_engine.multilingual_research import build_multilingual_plan
from research_engine.planner import ResearchPlanner
from research_engine.source_discovery import SourceDiscovery
from research_engine.specialist_domains import (
    build_evidence_lane_report,
    build_specialist_plan,
    prompt_block,
    render_evidence_lane_report,
    specialist_classification,
)
from research_engine.synthesizer import FinalSynthesizer


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
    assert config.max_sources == 32
    assert config.max_rounds == 4
    assert config.max_fulltext == 12
    assert config.discovery_seconds == 300
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
    assert "Humari Hypotheses" in rendered
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
    lane_pos = report.find("## Evidence ki alag-alag lanes")
    hypothesis_pos = report.find("## Humari Hypotheses")
    source_pos = report.find("## Sources")
    assert 0 < lane_pos < hypothesis_pos < source_pos
    assert report.rfind("## Research quality / technical audit") > source_pos
