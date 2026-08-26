from __future__ import annotations

from types import SimpleNamespace

from research_engine.final_stress_hardening import (
    _advanced_source_lane,
    _augment_for_final_gate,
    _enrich_lane_report,
)


def _source(*, source_type="paper", title="", snippet="", url="https://example.org/item"):
    return SimpleNamespace(
        source_type=source_type,
        title=title,
        snippet=snippet,
        url=url,
        venue="",
        publisher="",
        full_text="",
        source_id="S1",
    )


def test_multidomain_profile_does_not_turn_every_paper_empirical():
    source = _source(
        title="Jung and individuation: a conceptual review",
        snippet="A philosophical interpretation of the historical literature.",
    )
    lane = _advanced_source_lane(source, ["mind_cognition", "jung_depth_psychology"])
    assert lane == "scholarly_interpretation"


def test_empirical_paper_is_classified_from_its_own_content():
    source = _source(
        title="Attention after digital abstinence",
        snippet="We measured 420 participants in a longitudinal experiment and report statistical results.",
    )
    lane = _advanced_source_lane(source, ["mind_cognition", "jung_depth_psychology"])
    assert lane == "empirical_science"


def test_official_archive_source_stays_official_even_in_multidomain_question():
    source = _source(
        source_type="document",
        title="Declassified memorandum",
        url="https://www.cia.gov/readingroom/document/example",
    )
    assert _advanced_source_lane(source, ["mind_cognition", "declassified_intelligence"]) == "official_document_record"


def test_occult_profile_does_not_make_unrelated_book_traditional():
    unrelated = _source(source_type="book", title="Game Theory", snippet="Strategic interaction and incentives")
    traditional = _source(source_type="book", title="Hermetic writings", snippet="A historical occult and esoteric tradition")
    keys = ["esotericism_occult_history", "mind_cognition"]
    assert _advanced_source_lane(unrelated, keys) == "primary_historical_text"
    assert _advanced_source_lane(traditional, keys) == "traditional_belief_text"


def test_secret_society_allegation_uses_canonical_lane_key():
    from research_engine import specialist_domains as sd

    source = _source(
        source_type="web",
        title="New World Order allegation",
        snippet="The source claimed that a secret plot controls institutions.",
    )
    lane = _advanced_source_lane(source, ["secret_societies_history"])
    assert lane == "allegation_or_conspiracy_claim"
    assert lane in sd.LANES


def test_conspiracy_profile_allegation_uses_canonical_lane_key():
    from research_engine import specialist_domains as sd

    source = _source(
        source_type="web",
        title="Cover-up claim",
        snippet="An allegation of a hidden agenda is repeated without independent corroboration.",
    )
    lane = _advanced_source_lane(source, ["conspiracy_claims"])
    assert lane == "allegation_or_conspiracy_claim"
    assert lane in sd.LANES


def test_philosophy_metaphysics_key_can_classify_traditional_text_from_source_content():
    source = _source(
        source_type="book",
        title="Mystical metaphysics",
        snippet="A spiritual and mystical historical tradition.",
    )
    assert _advanced_source_lane(source, ["philosophy_metaphysics"]) == "traditional_belief_text"


def test_representative_advanced_lane_outputs_are_defined_lane_keys():
    from research_engine import specialist_domains as sd

    cases = [
        (_source(source_type="dataset", title="Measured dataset"), ["mind_cognition"]),
        (_source(source_type="paper", title="Conceptual review"), ["jung_depth_psychology"]),
        (_source(source_type="book", title="Historical monograph"), ["jung_depth_psychology"]),
        (_source(source_type="document", title="Historical letter"), ["jung_depth_psychology"]),
        (_source(source_type="web", title="Conspiracy allegation"), ["conspiracy_claims"]),
    ]
    for source, profiles in cases:
        assert _advanced_source_lane(source, profiles) in sd.LANES


def test_required_specialist_lanes_are_machine_auditable():
    report = {
        "active": True,
        "lanes": [
            {"key": "official_document_record", "source_count": 2},
            {"key": "scholarly_interpretation", "source_count": 1},
            {"key": "primary_historical_text", "source_count": 0},
        ],
    }
    specialist = {
        "expected_lanes": [
            "official_document_record",
            "primary_historical_text",
            "scholarly_interpretation",
        ]
    }
    out = _enrich_lane_report(report, specialist)
    assert out["covered_required_lanes"] == ["official_document_record", "scholarly_interpretation"]
    assert out["missing_required_lanes"] == ["primary_historical_text"]
    assert out["required_lane_coverage_complete"] is False


def test_installed_specialist_report_exposes_missing_required_lanes():
    from research_engine import specialist_domains as sd

    question = "Compare CIA declassified consciousness documents with Jung and scholarly criticism."
    specialist = sd.build_specialist_plan(question, question)
    plan = {"specialist": specialist}
    report = sd.build_evidence_lane_report(question, plan, SimpleNamespace(sources=[]))
    assert report["active"] is True
    assert report["required_lanes"]
    assert report["missing_required_lanes"] == report["required_lanes"]
    assert report["required_lane_coverage_complete"] is False


def test_missing_specialist_lane_blocks_evidence_first_completion():
    result = {
        "answer": "A sourced answer [S1].",
        "quality_contract": {"evidence_first_required": True},
        "requested_ledger": {"unmet": []},
        "specialist_research": {
            "active": True,
            "missing_required_lanes": ["official_document_record", "primary_historical_text"],
        },
    }
    out = _augment_for_final_gate(result)
    unmet = out["requested_ledger"]["unmet"]
    item = next(x for x in unmet if x["key"] == "specialist_source_family_coverage")
    assert "official_document_record" in item["got"]
    assert item["mandatory"] is True
    # Evaluation works on a copy: caller's ledger remains untouched.
    assert result["requested_ledger"]["unmet"] == []


def test_installed_final_gate_reports_specialist_lane_failure():
    from research_engine.final_quality_gate import FinalQualityGate

    result = {
        "answer": "A sourced answer [S1].",
        "status": "COMPLETE",
        "quality_contract": {"evidence_first_required": True},
        "requested_ledger": {"unmet": []},
        "specialist_research": {
            "active": True,
            "missing_required_lanes": ["official_document_record"],
        },
    }
    report = FinalQualityGate().evaluate(result).to_dict()
    requested = [issue for issue in report["issues"] if issue["code"] == "REQUESTED_DELIVERABLE_MISSING"]
    assert requested
    assert any(
        item.get("key") == "specialist_source_family_coverage"
        for issue in requested
        for item in issue.get("details", {}).get("unmet", [])
    )
    assert report["answer_complete"] is False


def test_missing_specialist_lane_does_not_gate_non_evidence_first_answer():
    result = {
        "answer": "Short answer.",
        "quality_contract": {"evidence_first_required": False},
        "requested_ledger": {"unmet": []},
        "specialist_research": {"active": True, "missing_required_lanes": ["scholarly_interpretation"]},
    }
    assert _augment_for_final_gate(result)["requested_ledger"]["unmet"] == []


def test_explicit_math_model_requires_sensitivity_not_just_one_parameter_set():
    result = {
        "answer": "Objective function: U = benefit - cost\nExpected value = p * gain - (1-p) * loss",
        "quality_contract": {"math_model_required": True},
        "requested_ledger": {"unmet": []},
    }
    out = _augment_for_final_gate(result)
    keys = {x["key"] for x in out["requested_ledger"]["unmet"]}
    assert "model_sensitivity_analysis" in keys


def test_model_with_sensitivity_passes_extra_model_grade_requirement():
    result = {
        "answer": (
            "Objective function: U = benefit - cost\n"
            "Expected value = p * gain - (1-p) * loss\n"
            "Sensitivity analysis: vary p from 0.2 to 0.8 and report how the decision changes."
        ),
        "quality_contract": {"math_model_required": True},
        "requested_ledger": {"unmet": []},
    }
    out = _augment_for_final_gate(result)
    assert not any(x["key"] == "model_sensitivity_analysis" for x in out["requested_ledger"]["unmet"])


def test_ordinary_calculation_does_not_require_model_sensitivity():
    result = {
        "answer": "speed = distance / time",
        "quality_contract": {"calculations_required": True, "math_model_required": False},
        "requested_ledger": {"unmet": []},
    }
    out = _augment_for_final_gate(result)
    assert out["requested_ledger"]["unmet"] == []


def test_shipped_ui_distinguishes_worker_finished_from_answer_complete():
    import main

    html = main._website_html()
    assert '"COMPLETE":"Research run finished"' in html
    assert '"COMPLETE":"Research complete"' not in html
    assert 'COMPLETE:"Research complete"' not in html
