"""Regression tests for the independent 100-point final quality gate."""
from __future__ import annotations

from dataclasses import dataclass

from research_engine.final_quality_gate import (
    CATEGORY_WEIGHTS,
    FinalQualityGate,
    QualityContract,
    evaluate_final_quality,
)


def _answer(*, hypotheses: bool = True, calculations: bool = True, verified: bool = False) -> str:
    blocks = [
        "## Seedha jawab\n\nRelevant evidence ke basis par seedha result.",
        "## Research se kya pata chala?\n\nEstablished knowledge [S1].",
        "## Evidence kya kehta hai?\n\nSupporting evidence [S1], [S2].",
        "## Iske against kya mila?\n\nCounter evidence [S3].",
    ]
    if calculations:
        blocks.append("## Calculations\n\nFormula, units aur assumptions structured audit mein hain.")
    blocks.extend([
        "## Kya abhi unknown hai?\n\nRemaining uncertainty.",
        "## Final conclusion\n\nBounded evidence-based conclusion.",
    ])
    if hypotheses:
        blocks.append(
            "## APP ORIGINAL RESEARCH LAB\n\n"
            "Neeche app-generated possibilities hain; cited sources ke direct conclusions nahi.\n\n"
            "### RV-HYP-2026-001\n\nPossibly novel candidate, global novelty verified nahi."
        )
    blocks.append("## Sources\n\n[S1], [S2], [S3].")
    if verified:
        blocks.append("Evidence ka level: ✅ VERIFIED")
    return "\n\n".join(blocks)


def _source(source_id: str, relevance: float = 0.9) -> dict:
    return {
        "source_id": source_id,
        "title": f"Primary study {source_id}",
        "url": f"https://example.org/{source_id}",
        "relevance_score": relevance,
        "read_level": "full_text",
        "is_primary": True,
        "retracted": False,
    }


def _experiment() -> dict:
    return {
        "dataset_or_sample": "Pre-registered sample of 120 independent observations",
        "control_or_baseline": "Matched baseline under the existing model",
        "measured_variables": ["observable_x", "observable_y"],
        "parameter_range": "x from 0.1 to 1.0 in ten fixed steps",
        "statistical_metric": "Out-of-sample log likelihood and calibrated error",
        "success_threshold": "At least 10 percent pre-registered improvement",
        "failure_threshold": "Less than 2 percent improvement at 95 percent power",
        "falsification_condition": "Reject if the effect is absent across the full tested range",
    }


def _hypothesis() -> dict:
    return {
        "hypothesis_id": "RV-HYP-2026-001",
        "statement": "A bounded and measurable mechanism changes observable_x.",
        "provenance": {
            "facts_used": ["S1 result", "S2 constraint"],
            "gap": "Neither source tests their combined boundary condition",
        },
        "mechanism": "The combined boundary condition changes the intermediate state and output.",
        "source_claim_disclaimer": "No cited source reports this exact conclusion; it is app-generated synthesis.",
        "closest_prior_work": [
            {"source_id": "S2", "similarity": 0.61, "difference": "Different parameter regime"}
        ],
        "novelty_search": {
            "queries": ["exact mechanism", "synonym mechanism", "negative prior-art query"],
            "databases": ["OpenAlex", "arXiv", "Crossref"],
            "close_match_found": False,
        },
        "novelty_status": "POSSIBLY NOVEL — NO CLOSE MATCH FOUND",
        "assumptions": ["Measurements are unbiased", "Boundary conditions are stable"],
        "prediction": {
            "variables": ["observable_x", "observable_y"],
            "expected_outcome": "A monotonic 10–20 percent change",
            "measurement_method": "Pre-registered blinded measurement",
            "falsification_condition": "No change across the bounded parameter range",
        },
        "experiment": _experiment(),
        "confidence": {"level": "LOW", "reason_codes": ["untested mechanism"]},
        "validation_status": "Concept only",
    }


def _calculation() -> dict:
    return {
        "formula": "M = v^2 r / G",
        "inputs": {"v": 220, "r": 8.2, "G": 6.6743e-11},
        "units": {"v": "km/s", "r": "kpc", "result": "solar masses"},
        "assumptions": ["circular orbit", "spherical enclosed-mass approximation"],
        "result": "9.2e10 solar masses",
        "uncertainty": "Illustrative only; disk geometry and input errors excluded",
        "unit_check_passed": True,
        "recalculation_passed": True,
        "sanity_check_passed": True,
        "invented_input": False,
    }


def _contract(*, hypotheses: int = 1, calculations: bool = True) -> QualityContract:
    return QualityContract(
        hypotheses_requested=hypotheses,
        original_hypotheses_required=hypotheses > 0,
        calculations_required=calculations,
        counter_search_required=True,
        minimum_directly_relevant_sources=2,
        minimum_average_relevance=0.65,
    )


def _perfect_result(*, hypotheses: bool = True, calculations: bool = True) -> dict:
    sources = [_source("S1"), _source("S2", 0.85), _source("S3", 0.8)]
    return {
        "status": "COMPLETE",
        "answer": _answer(hypotheses=hypotheses, calculations=calculations),
        "evidence_level": "STRONG EVIDENCE",
        "sources": sources,
        "missing_passes": [],
        "requested_ledger": {"items": [], "unmet": []},
        "verification": {"invalid_citations": [], "fabricated_citations": 0},
        "label_report": {"a_e_failed": 0, "entailment_blocked": 0},
        "contradictions": [],
        "hypotheses": [_hypothesis()] if hypotheses else [],
        "coverage": {
            "avg_relevance": 0.85,
            "on_topic_sources": 3,
            "directly_relevant_sources": 3,
            "sources_retrieved": 3,
            "sources_cited": 3,
            "sources_supporting_critical_claims": 2,
            "retracted_sources": 0,
        },
        "quality_context": {
            "counter_search_performed": True,
            "critical_claim_spans_complete": True,
            "critical_claim_evidence_spans": [
                {"claim_id": "C1", "source_id": "S1", "passage": "Exact support"}
            ],
            "directly_relevant_sources": 3,
            "sources_retrieved": 3,
            "sources_cited": 3,
            "sources_supporting_critical_claims": 2,
            "unsupported_critical_claims": 0,
            "critical_no_source_claims": 0,
            "access_depth_mismatches": 0,
            "hypothesis_fact_mix_count": 0,
            "numeric_confidence_calibrated": False,
            "recovery_used": False,
            "calculations": [_calculation()] if calculations else [],
        },
    }


def _codes(report) -> set[str]:
    return {issue.code for issue in report.issues}


def test_weights_are_exactly_100_and_complete_result_can_score_100():
    assert sum(CATEGORY_WEIGHTS.values()) == 100
    report = FinalQualityGate().evaluate(_perfect_result(), _contract())
    assert report.score == 100
    assert report.status == "PASS_100"
    assert report.release_ready is True
    assert report.verified_allowed is True
    assert report.answer_complete is True
    assert report.issues == ()
    assert all(report.checks.values())


def test_optional_hypotheses_and_calculations_do_not_create_fake_failures():
    result = _perfect_result(hypotheses=False, calculations=False)
    report = FinalQualityGate().evaluate(result, _contract(hypotheses=0, calculations=False))
    assert report.score == 100
    assert report.release_ready is True


def test_dark_matter_style_failure_is_capped_at_30_when_called_verified():
    result = _perfect_result()
    result["answer"] = """## Seedha jawab
Core evidence nahi mila [NO-SOURCE], phir bhi result final hai.

## Research se kya pata chala?
TESS aur telescope calibration background [S1][S2].

## Evidence kya kehta hai?
Main requested evidence available nahi tha.

## Final conclusion
Evidence ka level: ✅ VERIFIED

## Sources
Unrelated sources.

### Technical details (developer ke liye)
ResourceExhausted: quota_id raw line
"""
    result["status"] = "COMPLETE"
    result["sources"] = [_source("S1", 0.30), _source("S2", 0.20)]
    result["coverage"].update({
        "avg_relevance": 0.25,
        "on_topic_sources": 1,
        "directly_relevant_sources": 0,
        "sources_retrieved": 2,
    })
    result["quality_context"].update({
        "directly_relevant_sources": 0,
        "sources_retrieved": 2,
        "counter_search_performed": False,
        "critical_no_source_claims": 1,
        "unsupported_critical_claims": 1,
        "access_depth_mismatches": 1,
    })
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 30
    assert report.verified_allowed is False
    assert report.release_ready is False
    assert {
        "MANDATORY_SECTION_MISSING",
        "IRRELEVANT_EVIDENCE_PACK",
        "CRITICAL_CLAIM_UNSUPPORTED",
        "CRITICAL_NO_SOURCE_CLAIM",
        "COUNTER_SEARCH_MISSING",
        "RAW_DEVELOPER_LOG_LEAK",
        "FALSE_VERIFIED_BADGE",
    }.issubset(_codes(report))


def test_fabricated_citation_caps_score_at_20():
    result = _perfect_result()
    result["verification"]["fabricated_citations"] = 1
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 20
    assert "FABRICATED_CITATION" in _codes(report)


def test_unsupported_critical_claim_caps_score_at_40():
    result = _perfect_result()
    result["quality_context"]["unsupported_critical_claims"] = 1
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 40
    assert "CRITICAL_CLAIM_UNSUPPORTED" in _codes(report)


def test_missing_mandatory_section_with_complete_status_caps_score_at_40():
    result = _perfect_result()
    result["answer"] = result["answer"].replace("## Kya abhi unknown hai?", "### Limit note")
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 40
    assert report.answer_complete is False
    assert "MANDATORY_SECTION_MISSING" in _codes(report)
    assert "INCOMPLETE_STATUS_MISMATCH" in _codes(report)


def test_unmet_requested_ledger_blocks_complete_even_if_text_looks_good():
    result = _perfect_result()
    missing = {"what": "Evidence graph", "got": "nahi mila", "ok": False}
    result["requested_ledger"] = {"items": [missing], "unmet": [missing]}
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.answer_complete is False
    assert report.score <= 40
    assert "REQUESTED_DELIVERABLE_MISSING" in _codes(report)


def test_counter_search_is_a_hard_release_gate():
    result = _perfect_result()
    result["quality_context"]["counter_search_performed"] = False
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 70
    assert report.verified_allowed is False
    assert "COUNTER_SEARCH_MISSING" in _codes(report)


def test_source_accounting_requires_retrieved_cited_relevant_and_support_counts():
    result = _perfect_result()
    del result["coverage"]["sources_cited"]
    del result["quality_context"]["sources_cited"]
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 90
    assert "SOURCE_ACCOUNTING_INCOMPLETE" in _codes(report)


def test_low_relevance_is_not_rescued_by_source_quantity():
    result = _perfect_result()
    result["sources"] = [_source(f"S{i}", 0.20) for i in range(1, 19)]
    result["coverage"].update({
        "avg_relevance": 0.20,
        "on_topic_sources": 0,
        "directly_relevant_sources": 0,
        "sources_retrieved": 18,
    })
    result["quality_context"].update({
        "directly_relevant_sources": 0,
        "sources_retrieved": 18,
        "sources_cited": 9,
    })
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 40
    assert "IRRELEVANT_EVIDENCE_PACK" in _codes(report)


def test_access_depth_mismatch_blocks_full_text_overclaim():
    result = _perfect_result()
    result["quality_context"]["access_depth_mismatches"] = 1
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 40
    assert "ACCESS_DEPTH_MISMATCH" in _codes(report)


def test_evidence_spans_are_required_for_critical_claims():
    result = _perfect_result()
    result["quality_context"]["critical_claim_spans_complete"] = False
    result["quality_context"]["critical_claim_evidence_spans"] = []
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 90
    assert "EVIDENCE_SPANS_MISSING" in _codes(report)


def test_year_only_or_unstructured_contradiction_fails():
    result = _perfect_result()
    result["contradictions"] = [{"summary": "2010 aur 2025 alag confidence dikhate hain"}]
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 80
    assert "FALSE_CONTRADICTION_RECORD" in _codes(report)


def test_proposition_based_contradiction_passes():
    result = _perfect_result()
    result["contradictions"] = [{
        "normalized_proposition": "Intervention X changes outcome Y",
        "source_a_claim": "X increased Y in population P",
        "source_b_claim": "X did not increase Y in population P",
        "opposing_direction": True,
        "evidence_spans": ["S1 page 4", "S2 page 7"],
        "method_difference": "Different measurement precision",
    }]
    report = FinalQualityGate().evaluate(result, _contract())
    assert "FALSE_CONTRADICTION_RECORD" not in _codes(report)
    assert report.score == 100


def test_calculation_requires_formula_units_assumptions_and_three_checks():
    result = _perfect_result()
    broken = _calculation()
    broken["units"] = {}
    broken["recalculation_passed"] = False
    result["quality_context"]["calculations"] = [broken]
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 50
    assert "CALCULATION_VALIDATION_MISSING" in _codes(report)


def test_invented_numeric_input_caps_score_at_50():
    result = _perfect_result()
    result["quality_context"]["calculations"][0]["invented_input"] = True
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 50
    assert "UNSUPPORTED_NUMERIC_INPUT" in _codes(report)


def test_hypotheses_must_be_in_a_separate_original_research_section():
    result = _perfect_result()
    result["answer"] = result["answer"].replace("## APP ORIGINAL RESEARCH LAB", "## Humari Hypotheses")
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 60
    assert "HYPOTHESIS_NOT_SEPARATED" in _codes(report)


def test_ledger_can_infer_requested_hypothesis_count():
    result = _perfect_result()
    item = {"what": "3 nayi testable hypotheses", "got": "1", "ok": False}
    result["requested_ledger"] = {"items": [item], "unmet": [item]}
    report = FinalQualityGate().evaluate(result, QualityContract(calculations_required=True))
    assert "HYPOTHESIS_COUNT_SHORTFALL" in _codes(report)
    issue = next(issue for issue in report.issues if issue.code == "HYPOTHESIS_COUNT_SHORTFALL")
    assert issue.details == {"requested": 3, "delivered": 1}


def test_novelty_contract_requires_provenance_prior_work_search_and_status():
    result = _perfect_result()
    result["hypotheses"][0].pop("closest_prior_work")
    result["hypotheses"][0].pop("novelty_search")
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 50
    assert "NOVELTY_AUDIT_MISSING" in _codes(report)


def test_absolute_global_novelty_claim_is_rejected():
    result = _perfect_result()
    result["answer"] = result["answer"].replace(
        "Possibly novel candidate, global novelty verified nahi.",
        "Ye duniya mein pehli hypothesis hai aur 100% new hai.",
    )
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 50
    assert "ABSOLUTE_NOVELTY_OVERCLAIM" in _codes(report)


def test_fact_hypothesis_mixing_caps_score_at_60():
    result = _perfect_result()
    result["quality_context"]["hypothesis_fact_mix_count"] = 1
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 60
    assert "HYPOTHESIS_FACT_MIXING" in _codes(report)


def test_experiment_needs_sample_control_metric_threshold_and_falsifier():
    result = _perfect_result()
    result["hypotheses"][0]["experiment"] = {"dataset_or_sample": "Run a simulation"}
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 70
    assert "EXPERIMENT_OR_FALSIFIER_INCOMPLETE" in _codes(report)


def test_uncalibrated_numeric_confidence_is_blocked():
    result = _perfect_result()
    result["answer"] += "\nConfidence: 95% success chance."
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 50
    assert "UNCALIBRATED_NUMERIC_CONFIDENCE" in _codes(report)


def test_calibrated_numeric_confidence_is_allowed_when_structured_flag_exists():
    result = _perfect_result()
    result["answer"] += "\nConfidence: 95% success chance."
    result["quality_context"]["numeric_confidence_calibrated"] = True
    report = FinalQualityGate().evaluate(result, _contract())
    assert "UNCALIBRATED_NUMERIC_CONFIDENCE" not in _codes(report)


def test_duplicate_recovery_answer_and_footer_are_detected():
    result = _perfect_result()
    result["answer"] += "\n## Seedha jawab\nDuplicate recovered answer.\nEvidence ka level: x\nEvidence ka level: y"
    report = FinalQualityGate().evaluate(result, _contract())
    assert "DUPLICATE_RECOVERY_OUTPUT" in _codes(report)
    assert "DUPLICATE_EVIDENCE_FOOTER" in _codes(report)


def test_raw_provider_error_is_never_user_facing():
    result = _perfect_result()
    result["answer"] += "\nResourceExhausted: quota_metric GenerateRequests"
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 90
    assert "RAW_DEVELOPER_LOG_LEAK" in _codes(report)


def test_recovery_requires_progress_snapshot():
    result = _perfect_result()
    result["quality_context"]["recovery_used"] = True
    result["quality_context"]["progress_snapshot_preserved"] = False
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score <= 90
    assert "RECOVERY_PROGRESS_MISSING" in _codes(report)


def test_recovered_result_with_snapshot_can_still_pass():
    result = _perfect_result()
    result["quality_context"]["recovery_used"] = True
    result["quality_context"]["progress_snapshot_preserved"] = True
    report = FinalQualityGate().evaluate(result, _contract())
    assert report.score == 100
    assert report.release_ready is True


@dataclass
class _ResultObject:
    payload: dict

    def to_dict(self) -> dict:
        return self.payload


def test_public_convenience_api_accepts_model_like_objects_and_returns_dict():
    output = evaluate_final_quality(_ResultObject(_perfect_result()), _contract())
    assert output["contract_version"] == "1.0"
    assert output["score"] == 100
    assert output["release_ready"] is True
    assert output["issues"] == []


def test_quality_report_is_stable_and_json_ready():
    output = FinalQualityGate().evaluate(_perfect_result(), _contract()).to_dict()
    assert set(output) == {
        "contract_version",
        "score",
        "status",
        "release_ready",
        "verified_allowed",
        "answer_complete",
        "hard_cap",
        "category_scores",
        "checks",
        "issues",
    }
    assert sum(output["category_scores"].values()) == 100
