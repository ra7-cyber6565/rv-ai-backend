from research_engine.validation_contracts import INCONCLUSIVE, RESULT_OBSERVED
from research_engine.validation_director import AI2ValidationDirector


def _row(packet):
    return packet["sections"]["6. Exact Experiments / Backtests / Simulations Required"]["domain_hypothesis_experiments"][0]


def test_upstream_observed_pass_is_only_a_claim_without_ai2_decision_rule():
    result = {"hypotheses": [{
        "id": "H1", "statement": "A changes B", "status": "PASS",
        "test_state": RESULT_OBSERVED, "observed_result": "reported success",
        "result_provenance": {"test_id": "upstream-T", "dataset_id": "upstream-D"},
    }]}
    packet = AI2ValidationDirector().build_packet("test", result)
    row = _row(packet)
    assert row["upstream_claimed_status"] == "PASS"
    assert row["hypothesis_status"] == INCONCLUSIVE
    assert packet["packet_integrity"]["valid"] is True


def test_experiment_mapping_is_not_mistaken_for_explicit_setup():
    result = {"hypotheses": [{"id": "H1", "statement": "A changes B", "experiment": {"metric": "B"}}]}
    row = _row(AI2ValidationDirector().build_packet("test", result))
    assert row["Experimental setup"] == "UNKNOWN"
    assert "Experimental setup" in row["missing_required_fields"]
    assert row["contract_complete"] is False


def test_missing_variables_and_confounders_keep_contract_incomplete():
    result = {"hypotheses": [{
        "id": "H1", "statement": "A changes B",
        "experiment": {"dataset_or_sample": "D", "experimental_setup": "S", "statistical_metric": "M",
                       "control_or_baseline": "C", "null_hypothesis": "N",
                       "falsification_condition": "F", "replication_method": "R"},
        "prediction": "P",
    }]}
    row = _row(AI2ValidationDirector().build_packet("test", result))
    assert "Variables" in row["missing_required_fields"]
    assert "Confounders" in row["missing_required_fields"]
    assert row["contract_complete"] is False


def test_math_model_needs_objective_not_only_symbol_metadata():
    result = {"mathematical_model": {
        "equation": "y = beta*x",
        "parameters": {"beta": {"definition": "slope", "unit": "y/x", "interpretation": "change in y per x"}},
    }}
    model = AI2ValidationDirector().build_packet("predict", result)["sections"]["3. Mathematical Model"]["domain_models_found"][0]
    assert model["symbol_contract_complete"] is True
    assert model["model_contract_complete"] is False
    assert model["status"] == INCONCLUSIVE
