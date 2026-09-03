from research_engine.models import ResearchResult
from research_engine.validation_director import PACKET_HEADINGS
from research_engine.validation_director_integrated import IntegratedQuantitativeValidationDirector
from research_engine.validation_guard import audit_holdout, seal_holdout


def _director():
    return IntegratedQuantitativeValidationDirector()


def _single_hypothesis_proposal(domain="general", metric="score"):
    return {
        "domain": domain,
        "goal": "Test the candidate rigorously",
        "dataset_sample": "predeclared sample",
        "primary_metric": metric,
        "hypotheses": [{
            "hypothesis_id": "H1",
            "statement": "Candidate beats the baseline.",
            "mechanism": "A measurable mechanism.",
            "prediction": "The primary metric improves.",
            "null_hypothesis": "No improvement versus baseline.",
            "variables": ["X", "Y"],
            "baseline_id": "B1",
            "test": "Frozen protocol comparison.",
            "falsification_condition": "Predeclared decision rule fails.",
        }],
    }


def test_plan_without_execution_never_claims_pass_or_observed_result():
    packet = _director().analyze(
        "Does this model work?",
        _single_hypothesis_proposal(),
        execution_packets={},
    )
    assert packet["hypotheses"][0]["status"] == "INCONCLUSIVE"
    assert packet["experiments"][0]["state"] in {"TEST PROPOSED", "TEST POSSIBLE"}
    assert packet["results"][0]["state"] != "RESULT OBSERVED"
    assert packet["validation_integrity"]["self_reported_metrics_can_unconditionally_pass"] is False


def test_render_packet_contains_exact_17_required_sections():
    director = _director()
    packet = director.analyze("Test this explanation", _single_hypothesis_proposal())
    rendered = director.render_packet(packet)
    assert rendered.startswith("# AI-2 VALIDATION PACKET")
    for heading in PACKET_HEADINGS:
        assert f"## {heading}" in rendered


def test_default_variables_are_not_decorative_and_have_units_and_interpretations():
    packet = _director().analyze("Test this explanation", {"goal": "causal test"})
    assert packet["variables"]
    for variable in packet["variables"]:
        assert variable["symbol"]
        assert variable["definition"]
        assert variable["unit"]
        assert variable["interpretation"]
        assert variable["role"]


def test_observed_numbers_without_decision_rule_remain_inconclusive():
    proposal = _single_hypothesis_proposal()
    packet = _director().analyze(
        "Does this model work?",
        proposal,
        execution_packets={"H1": {"metrics": {"score": 999999}}},
    )
    assert packet["results"][0]["state"] == "RESULT OBSERVED"
    assert packet["results"][0]["decision"]["status"] == "INCONCLUSIVE"
    assert "decision" in packet["results"][0]["decision"]["reason"].lower()


def test_fatal_leakage_invalidates_evaluation_but_does_not_disprove_hypothesis():
    proposal = _single_hypothesis_proposal()
    packet = _director().analyze(
        "Does this model work?",
        proposal,
        execution_packets={
            "H1": {
                "metrics": {"score": 0.0},
                "metrics_verified": True,
                "decision_rule": {"metric": "score", "operator": ">=", "threshold": 1.0},
                "bias_audit": {"look_ahead": True},
            }
        },
    )
    decision = packet["results"][0]["decision"]
    assert decision["status"] == "INCONCLUSIVE"
    assert "INVALID_EVALUATION_FATAL_LEAKAGE" in decision["integrity_codes"]
    assert packet["hypotheses"][0]["status"] == "INCONCLUSIVE"


def test_self_reported_aggregate_metrics_cannot_unconditionally_pass():
    proposal = _single_hypothesis_proposal()
    packet = _director().analyze(
        "Does this model work?",
        proposal,
        execution_packets={
            "H1": {
                "metrics": {"baseline_difference": 2.0},
                "decision_rule": {"metric": "baseline_difference", "operator": ">", "threshold": 0.0},
            }
        },
    )
    decision = packet["results"][0]["decision"]
    assert decision["status"] == "CONDITIONAL PASS"
    assert "SELF_REPORTED_METRICS" in decision["integrity_codes"]
    assert packet["results"][0]["epistemic_evidence_origin"] == "CALLER_SUPPLIED_AGGREGATE_METRICS"


def test_bare_baseline_beaten_boolean_is_not_quantitative_proof():
    proposal = _single_hypothesis_proposal(metric="score")
    packet = _director().analyze(
        "Does this model work?",
        proposal,
        execution_packets={
            "H1": {
                "metrics": {"score": 2.0},
                "metrics_verified": True,
                "decision_rule": {"metric": "score", "operator": ">", "threshold": 1.0},
                "baseline_beaten": True,
            }
        },
    )
    decision = packet["results"][0]["decision"]
    assert decision["status"] == "CONDITIONAL PASS"
    assert "BASELINE_ATTESTATION_ONLY" in decision["integrity_codes"]


def test_predictive_pass_without_out_of_sample_evidence_is_only_conditional():
    proposal = _single_hypothesis_proposal(domain="prediction", metric="baseline_difference")
    packet = _director().analyze(
        "Will this classifier generalize?",
        proposal,
        execution_packets={
            "H1": {
                "metrics": {"baseline_difference": 0.1},
                "metrics_verified": True,
                "decision_rule": {"metric": "baseline_difference", "operator": ">", "threshold": 0.0},
            }
        },
    )
    decision = packet["results"][0]["decision"]
    assert decision["status"] == "CONDITIONAL PASS"
    assert "OUT_OF_SAMPLE_EVIDENCE_MISSING" in decision["integrity_codes"]


def test_holdout_requires_matching_predeclared_hash_preseal_and_exactly_one_use():
    holdout = [1, 2, 3]
    missing_receipts = audit_holdout({"untouched_test": holdout})
    assert missing_receipts["evaluation_valid_for_final_claim"] is False
    assert "PREDECLARED_HASH_MISSING" in missing_receipts["issues"]
    assert "PRE_EVALUATION_SEALING_NOT_PROVEN" in missing_receipts["issues"]

    valid = audit_holdout({
        "untouched_test": holdout,
        "untouched_test_hash": seal_holdout(holdout),
        "untouched_test_sealed_before_evaluation": True,
        "untouched_test_uses": 1,
        "tuned_on_untouched_test": False,
    })
    assert valid["evaluation_valid_for_final_claim"] is True
    assert valid["issues"] == []

    changed = audit_holdout({
        "untouched_test": [1, 2, 4],
        "untouched_test_hash": seal_holdout(holdout),
        "untouched_test_sealed_before_evaluation": True,
        "untouched_test_uses": 1,
    })
    assert changed["evaluation_valid_for_final_claim"] is False
    assert "HOLDOUT_CHANGED_AFTER_DECLARATION" in changed["issues"]


def test_valid_raw_two_group_observations_can_pass_general_domain_rule():
    proposal = _single_hypothesis_proposal(metric="mean_difference")
    packet = _director().analyze(
        "Does treatment A improve the measured outcome?",
        proposal,
        execution_packets={
            "H1": {
                "kind": "two_group",
                "group_a": [10, 11, 12, 13],
                "group_b": [1, 2, 3, 4],
                "decision_rule": {"metric": "mean_difference", "operator": ">", "threshold": 0.0},
            }
        },
    )
    assert packet["results"][0]["decision"]["status"] == "PASS"
    assert packet["results"][0]["epistemic_evidence_origin"] == "RECOMPUTED_FROM_SUPPLIED_RAW_OBSERVATIONS"


def test_second_pass_continues_instead_of_restarting_from_zero():
    director = _director()
    first = director.analyze("Test this model", _single_hypothesis_proposal())
    second = director.second_pass(
        "Test this model",
        first,
        {"disputed_claims": ["Mechanism A versus mechanism B"]},
        execution_packets={},
    )
    assert second["phase"] == "second"
    assert second["second_pass_continuity"]["restarted_from_zero"] is False
    assert any(task.get("priority") == 2 for task in second["second_pass_tasks"])


def test_normal_research_result_path_gets_plan_only_ai2_packet_without_truth_upgrade():
    result = ResearchResult(
        question="Could this mechanism explain the measured effect?",
        answer="Current evidence is incomplete.",
        hypotheses=[{
            "id": "H1",
            "statement": "Mechanism changes Y.",
            "mechanism": "X alters mediator M.",
            "experiment": {
                "dataset_or_sample": "independent sample",
                "control_or_baseline": "matched control",
                "measured_variables": ["X", "M", "Y"],
                "statistical_metric": "mean_difference",
                "falsification_condition": "No directionally consistent effect on Y.",
            },
        }],
    ).to_dict()
    packet = result["coverage"]["ai2_validation"]
    assert packet["agent_id"] == "AI-2 / VALIDATION-DIRECTOR"
    assert packet["runtime_wiring"]["ran"] is True
    assert packet["runtime_wiring"]["execution_packets_supplied"] is False
    assert packet["runtime_wiring"]["real_world_experiment_executed"] is False
    assert packet["runtime_wiring"]["truth_proven"] is False
    assert all(h["status"] == "INCONCLUSIVE" for h in packet["hypotheses"])
