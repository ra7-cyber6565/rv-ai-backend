from research_engine.validation_contracts import NOT_TESTED, PASS
from research_engine.validation_director import AI2ValidationDirector
from research_engine.validation_inference import bayesian_update, multiple_testing, power_analysis


def _hypothesis():
    return {"id": "H1", "statement": "Candidate improves outcome vs baseline.",
            "experiment": {"dataset_or_sample": "locked sample", "experimental_setup": "comparison",
                           "statistical_metric": "mean difference", "control_or_baseline": "baseline",
                           "null_hypothesis": "no difference", "confounders": ["none known"],
                           "falsification_condition": "mean difference fails locked rule",
                           "replication_method": "independent locked repeat"},
            "prediction": {"variables": ["candidate outcome", "baseline outcome"],
                           "expected_outcome": "candidate higher"}}


def test_explicit_inference_controls_flow_into_hypothesis_packet():
    result = {"hypotheses": [_hypothesis()], "sources": [{"id": "S1"}],
              "validation_receipts": [{
                  "hypothesis_id": "H1", "provenance": {"test_id": "T1", "dataset_id": "D1"},
                  "observations": {"candidate": [4, 5, 6, 7], "baseline": [1, 2, 3, 4]},
                  "decision_rule": {"metric": "mean_difference", "operator": ">", "threshold": 0},
                  "bayesian_evidence": {"prior_h1": 0.5, "likelihood_e_given_h1": 0.8, "likelihood_e_given_h0": 0.2},
                  "multiple_testing": {"p_values": [0.01, 0.04], "method": "holm", "alpha": 0.05},
                  "power_analysis": {"standardized_effect": 0.5, "alpha": 0.05, "target_power": 0.8, "sided": 2},
              }]}
    packet = AI2ValidationDirector().build_packet("test candidate", result)
    row = packet["sections"]["6. Exact Experiments / Backtests / Simulations Required"]["domain_hypothesis_experiments"][0]
    stat = row["statistical_validation"]
    assert row["hypothesis_status"] == PASS
    assert stat["bayesian_evidence"]["posterior_h1"] == 0.8
    assert stat["bayesian_evidence"]["bayes_factor_h1_h0"] == 4.0
    assert stat["multiple_testing_correction"]["adjusted_p_values"] == [0.02, 0.04]
    assert stat["multiple_testing_correction"]["reject_flags"] == [True, True]
    assert stat["power_analysis"]["required_n_per_group"] > 0
    assert packet["packet_integrity"]["valid"] is True


def test_inference_does_not_invent_alpha_or_power_target():
    mt = multiple_testing({"p_values": [0.01, 0.02], "method": "bonferroni"}, observed_provenance=True)
    assert mt["adjusted_p_values"] == [0.02, 0.04]
    assert mt["reject_flags"] == NOT_TESTED

    power = power_analysis({"standardized_effect": 0.5, "alpha": 0.05, "sided": 2})
    assert power["required_n_per_group"] == NOT_TESTED


def test_bayesian_result_update_requires_observed_provenance():
    config = {"prior_h1": 0.5, "likelihood_e_given_h1": 0.8, "likelihood_e_given_h0": 0.2}
    blocked = bayesian_update(config, observed_provenance=False)
    assert blocked["status"] == NOT_TESTED
