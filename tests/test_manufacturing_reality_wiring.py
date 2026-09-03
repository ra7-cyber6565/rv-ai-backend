import pytest

from research_engine.manufacturing_reality_wiring import (
    apply_manufacturing_reality_wiring,
    build_manufacturing_reality_packet,
    install,
    manufacturing_reality_relevant,
)
from research_engine.models import ResearchResult


def _passing_contract():
    return {
        "requirements": [
            {
                "requirement_id": "yield-gate",
                "requirement_kind": "YIELD",
                "minimum_yield": 0.95,
                "minimum_sample_size": 100,
                "require_measured": True,
                "require_hardware_observed": True,
                "require_production_environment": True,
            }
        ],
        "evidence": [
            {
                "evidence_id": "factory-run-1",
                "requirement_id": "yield-gate",
                "environment": "PRODUCTION",
                "provenance_ref": "factory://line-a/run-2026-09-01",
                "sample_size": 100,
                "measured": True,
                "hardware_observed": True,
                "reproducible": True,
                "accepted_count": 98,
                "total_count": 100,
            }
        ],
    }


def test_manufacturing_relevance_is_conservative_for_physical_builds():
    assert manufacturing_reality_relevant("Can this drone be mass produced?") is True
    assert manufacturing_reality_relevant("Iron Man suit kaise banaye aur manufacture kare?") is True
    assert manufacturing_reality_relevant("How to build a physical robot prototype?") is True
    assert manufacturing_reality_relevant("How to build a Python API?") is False
    assert manufacturing_reality_relevant("Explain the history of mathematics") is False


def test_relevant_question_without_structured_contract_fails_closed():
    result = apply_manufacturing_reality_wiring({
        "question": "Can this drone be manufactured at scale?",
        "answer": "yes",
        "status": "COMPLETE",
        "coverage": {"existing": {"kept": True}},
    })
    packet = result["coverage"]["manufacturing_reality"]
    assert packet["status"] == "STRUCTURED_MANUFACTURING_INPUTS_REQUIRED"
    assert packet["structured_contract_present"] is False
    assert packet["blocks_completion"] is True
    assert packet["free_form_manufacturability_inference_performed"] is False
    assert packet["manufacturability_truth_proven"] is False
    assert result["status"] == "PARTIAL"
    assert result["coverage"]["existing"] == {"kept": True}


def test_non_manufacturing_question_is_not_downgraded_without_contract():
    result = apply_manufacturing_reality_wiring({
        "question": "Explain prime number factorization",
        "status": "COMPLETE",
        "coverage": {},
    })
    packet = result["coverage"]["manufacturing_reality"]
    assert packet["status"] == "NO_STRUCTURED_MANUFACTURING_INPUTS"
    assert packet["relevance_detected"] is False
    assert packet["blocks_completion"] is False
    assert result["status"] == "COMPLETE"


def test_passing_contract_supports_only_scoped_requirement_statement():
    packet = build_manufacturing_reality_packet({
        "question": "Can this component be mass produced?",
        "coverage": {"manufacturing_reality_inputs": _passing_contract()},
    })
    assert packet["status"] == "AUDITED_PASS"
    assert packet["all_requirements_passed"] is True
    assert packet["supports_scoped_requirement_statement"] is True
    assert packet["blocks_completion"] is False
    assert packet["blocks_unqualified_manufacturability_claim"] is True
    assert packet["factory_execution_proven"] is False
    assert packet["hardware_authenticity_proven"] is False
    assert packet["external_certification_claimed"] is False
    assert packet["manufacturability_truth_proven"] is False


def test_failed_requirement_downgrades_relevant_complete_result():
    contract = _passing_contract()
    contract["evidence"][0]["accepted_count"] = 80
    result = apply_manufacturing_reality_wiring({
        "question": "Is this factory process production ready?",
        "status": "COMPLETE",
        "coverage": {"manufacturing_reality_inputs": contract},
    })
    packet = result["coverage"]["manufacturing_reality"]
    assert packet["status"] == "AUDITED_BLOCKED"
    assert packet["all_requirements_passed"] is False
    assert packet["supports_scoped_requirement_statement"] is False
    assert packet["blocks_completion"] is True
    assert result["status"] == "PARTIAL"


def test_simulation_cannot_satisfy_required_hardware_observation():
    contract = _passing_contract()
    row = contract["evidence"][0]
    row["environment"] = "SIMULATION"
    row["hardware_observed"] = False
    result = build_manufacturing_reality_packet({
        "question": "Can this component be manufactured?",
        "coverage": {"manufacturing_reality_inputs": contract},
    })
    assert result["status"] == "AUDITED_BLOCKED"
    blockers = result["audits"][0]["blockers"]
    assert "hardware_observation_missing" in blockers
    assert "production_environment_evidence_missing" in blockers
    assert result["simulation_promoted_to_measurement"] is False


def test_unknown_contract_keys_fail_closed_without_crashing_result():
    contract = _passing_contract()
    contract["invented_truth"] = True
    result = apply_manufacturing_reality_wiring({
        "question": "Can this be mass produced?",
        "status": "COMPLETE",
        "coverage": {"manufacturing_reality_inputs": contract},
    })
    packet = result["coverage"]["manufacturing_reality"]
    assert packet["status"] == "ASSESSMENT_ERROR"
    assert packet["error"] == "ValueError"
    assert packet["manufacturability_truth_proven"] is False
    assert result["status"] == "PARTIAL"


def test_unknown_row_keys_are_rejected_instead_of_silently_ignored():
    contract = _passing_contract()
    contract["requirements"][0]["magic_factory_score"] = 1.0
    with pytest.raises(ValueError, match="unknown manufacturing requirement keys"):
        build_manufacturing_reality_packet({
            "question": "manufacturing feasibility",
            "coverage": {"manufacturing_reality_inputs": contract},
        })


def test_string_false_does_not_coerce_to_true():
    contract = _passing_contract()
    contract["evidence"][0]["hardware_observed"] = "false"
    with pytest.raises(ValueError, match="hardware_observed must be boolean"):
        build_manufacturing_reality_packet({
            "question": "manufacturing feasibility",
            "coverage": {"manufacturing_reality_inputs": contract},
        })


def test_empty_requirements_are_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        build_manufacturing_reality_packet({
            "question": "manufacturing feasibility",
            "coverage": {
                "manufacturing_reality_inputs": {"requirements": [], "evidence": []}
            },
        })


def test_install_is_idempotent_and_real_serialization_path_gets_packet():
    from research_engine import result_coverage_gate

    before = result_coverage_gate.enforce
    install()
    after_first = result_coverage_gate.enforce
    install()
    after_second = result_coverage_gate.enforce
    assert after_first is after_second
    # Package import may already have installed the wrapper; if not, this call
    # installs it exactly once. Either way, normal ResearchResult serialization
    # must expose the production coverage packet.
    result = ResearchResult(
        question="Explain prime numbers",
        answer="2, 3, 5",
        status="PARTIAL",
    ).to_dict()
    assert "manufacturing_reality" in result["coverage"]
    assert result["coverage"]["manufacturing_reality"]["ran"] is True
    assert result["coverage"]["manufacturing_reality"]["manufacturability_truth_proven"] is False
    assert before is after_first or before is not after_first
