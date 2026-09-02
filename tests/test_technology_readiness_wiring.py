from research_engine.models import ResearchResult
from research_engine.technology_readiness_wiring import (
    apply_technology_readiness_wiring,
    build_technology_readiness_packet,
    install,
)


def _inputs():
    return {
        "technology_id": "software-1",
        "technology_type": "SOFTWARE",
        "target_level": 3,
        "evidence": [
            {
                "evidence_id": "E1",
                "supports_level": 1,
                "evidence_kind": "PRINCIPLE",
                "environment": "ANALYTICAL",
                "provenance_ref": "receipt://principle",
            },
            {
                "evidence_id": "E2",
                "supports_level": 2,
                "evidence_kind": "CONCEPT",
                "environment": "ANALYTICAL",
                "provenance_ref": "receipt://concept",
            },
            {
                "evidence_id": "E3",
                "supports_level": 3,
                "evidence_kind": "EXPERIMENT",
                "environment": "LAB",
                "provenance_ref": "receipt://experiment",
                "reproducible": True,
            },
        ],
    }


def test_explicit_readiness_receipts_are_audited_without_certification_or_status_upgrade():
    result = apply_technology_readiness_wiring({
        "answer": "partial",
        "status": "PARTIAL",
        "coverage": {"technology_readiness_inputs": _inputs(), "existing": {"kept": True}},
    })
    packet = result["coverage"]["technology_readiness"]
    assert packet["status"] == "AUDITED"
    assert packet["achieved_level"] == 3
    assert packet["target_met"] is True
    assert packet["external_certification_claimed"] is False
    assert packet["truth_proven"] is False
    assert packet["free_form_maturity_inference_performed"] is False
    assert result["status"] == "PARTIAL"
    assert result["coverage"]["existing"] == {"kept": True}


def test_free_form_feature_names_never_manufacture_readiness():
    packet = build_technology_readiness_packet({
        "answer": "This prototype sounds production ready and mature."
    })
    assert packet["status"] == "NO_STRUCTURED_READINESS_INPUTS"
    assert packet["free_form_maturity_inference_performed"] is False
    assert packet["external_certification_claimed"] is False


def test_bad_explicit_readiness_contract_fails_closed():
    bad = _inputs()
    bad["target_level"] = 10
    result = apply_technology_readiness_wiring({
        "status": "PARTIAL",
        "technology_readiness_inputs": bad,
    })
    packet = result["coverage"]["technology_readiness"]
    assert packet["ran"] is False
    assert packet["status"] == "ASSESSMENT_ERROR"
    assert packet["external_certification_claimed"] is False
    assert packet["truth_proven"] is False
    assert result["status"] == "PARTIAL"


def test_physical_readiness_does_not_fake_hardware_evidence():
    physical = _inputs()
    physical["technology_id"] = "physical-1"
    physical["technology_type"] = "PHYSICAL"
    physical["target_level"] = 4
    physical["evidence"].append({
        "evidence_id": "E4",
        "supports_level": 4,
        "evidence_kind": "COMPONENT_TEST",
        "environment": "LAB",
        "provenance_ref": "receipt://simulation-only",
        "independent": True,
        "reproducible": True,
        "hardware_observed": False,
    })
    packet = build_technology_readiness_packet({"technology_readiness_inputs": physical})
    assert packet["achieved_level"] == 3
    assert packet["target_met"] is False
    assert "real_hardware_observation_missing" in packet["levels"][3]["blockers"]
    assert packet["external_certification_claimed"] is False


def test_normal_research_result_serialization_activates_readiness_wiring():
    result = ResearchResult(
        question="technology readiness audit",
        answer="partial",
        status="PARTIAL",
        coverage={"technology_readiness_inputs": _inputs()},
    ).to_dict()
    packet = result["coverage"]["technology_readiness"]
    assert packet["ran"] is True
    assert packet["status"] == "AUDITED"
    assert packet["result_status_upgraded"] is False
    assert packet["external_certification_claimed"] is False
    assert result["status"] != "COMPLETE"


def test_install_is_idempotent():
    from research_engine import result_coverage_gate

    before = result_coverage_gate.enforce
    install()
    after_first = result_coverage_gate.enforce
    install()
    after_second = result_coverage_gate.enforce
    assert before is after_first
    assert after_first is after_second
