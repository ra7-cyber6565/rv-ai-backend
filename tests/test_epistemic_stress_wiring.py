from research_engine.epistemic_stress_wiring import (
    apply_epistemic_stress_wiring,
    build_epistemic_stress_packet,
)


def _contracts():
    return {
        "unknown_unknown": {
            "coverage_dimensions": [
                {
                    "dimension_id": "regime",
                    "expected_states": ["normal", "stress"],
                    "observed_states": ["normal"],
                }
            ],
            "assumptions": [],
            "anomalies": [],
        },
        "claim_insurance": [
            {
                "claim_id": "C1",
                "statement": "A bounded high-impact claim has an explicit downside contract.",
                "impact_if_wrong": 0.9,
                "supporting_evidence_ids": ["E1", "E2", "E3"],
                "independent_groups": ["G1", "G2"],
                "uncertainty_upper_bound": 0.2,
                "falsifier": "reject if frozen endpoint reverses",
                "revalidation_trigger": "revalidate after model revision",
                "monitoring_signal": "monitor endpoint drift continuously",
                "rollback_plan": "revert dependent recommendation",
            }
        ],
        "synthetic_data": {
            "artifacts": [
                {
                    "artifact_id": "raw",
                    "declared_lineage": "REAL",
                    "role": "REFERENCE",
                    "source_ref": "dataset://raw",
                },
                {
                    "artifact_id": "holdout",
                    "declared_lineage": "REAL",
                    "role": "HOLDOUT",
                    "parent_ids": ["raw"],
                },
            ]
        },
        "belief_sandbox": [
            {
                "belief_id": "B1",
                "statement": "Candidate belief predicts a measurable outcome.",
                "evidence_ids": ["E1", "E2"],
                "independent_groups": ["G1", "G2"],
                "falsifier": "reject if preregistered endpoint is absent",
                "preregistered_predictions": ["endpoint exceeds frozen threshold"],
                "resolved_predictions": 1,
                "falsification_attempts": 1,
            }
        ],
        "conspiracy_hypotheses": [
            {
                "hypothesis_id": "H1",
                "statement": "Specified coordinated mechanism predicts a measurable effect.",
                "mechanism": "Specified actors alter a variable through a measurable channel.",
                "falsifier": "reject if locked discriminator is absent",
                "preregistered_predictions": ["observable Z precedes outcome Y"],
                "evidence": [
                    {
                        "evidence_id": "CE1",
                        "source_id": "S1",
                        "independence_group": "CG1",
                        "supports": True,
                    },
                    {
                        "evidence_id": "CE2",
                        "source_id": "S2",
                        "independence_group": "CG2",
                        "supports": True,
                    },
                ],
                "disconfirming_search_performed": True,
                "alternative_explanations_considered": [
                    "ordinary incentives explain the same observation"
                ],
            }
        ],
    }


def test_no_structured_contract_never_infers_from_prose():
    packet = build_epistemic_stress_packet({
        "question": "Could hidden coordination explain this?",
        "answer": "Maybe.",
    })
    assert packet["status"] == "NO_STRUCTURED_CONTRACT"
    assert packet["natural_language_inference_performed"] is False
    assert packet["result_status_upgraded"] is False
    assert packet["truth_proven"] is False


def test_all_five_explicit_contracts_are_audited_without_status_upgrade():
    original = {
        "status": "PARTIAL",
        "answer": "bounded answer",
        "coverage": {"existing": {"kept": True}},
        "epistemic_stress_contracts": _contracts(),
    }
    result = apply_epistemic_stress_wiring(original)
    packet = result["coverage"]["epistemic_stress"]
    assert result["status"] == "PARTIAL"
    assert result["answer"] == "bounded answer"
    assert result["coverage"]["existing"] == {"kept": True}
    assert packet["status"] == "AUDITED"
    assert set(packet["contracts_present"]) == {
        "unknown_unknown",
        "claim_insurance",
        "synthetic_data",
        "belief_sandbox",
        "conspiracy_hypotheses",
    }
    assert packet["unknown_unknown"]["unknown_unknown_proven"] is False
    assert packet["claim_insurance"]["all_operational_reliance_eligible"] is True
    assert packet["synthetic_data"]["real_world_validation_eligible"] is True
    assert packet["belief_sandbox"]["canonical_state_mutated"] is False
    assert packet["conspiracy_hypotheses"]["absence_of_evidence_treated_as_proof"] is False
    assert packet["truth_proven"] is False


def test_bad_explicit_contract_fails_closed_inside_coverage_packet():
    result = apply_epistemic_stress_wiring({
        "status": "PARTIAL",
        "epistemic_stress_contracts": {
            "synthetic_data": {"artifacts": []},
        },
    })
    packet = result["coverage"]["epistemic_stress"]
    assert packet["ran"] is False
    assert packet["status"] == "ASSESSMENT_ERROR"
    assert packet["truth_proven"] is False
    assert result["status"] == "PARTIAL"


def test_unknown_contract_key_fails_closed_not_silently_ignored():
    result = apply_epistemic_stress_wiring({
        "epistemic_stress_contracts": {"invented_magic_gate": {}},
    })
    packet = result["coverage"]["epistemic_stress"]
    assert packet["ran"] is False
    assert packet["status"] == "ASSESSMENT_ERROR"
    assert packet["natural_language_inference_performed"] is False
