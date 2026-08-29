import math

import pytest

from research_engine.causal_counterfactual import (
    CausalCounterfactualEngine,
    CausalModel,
    evaluate_causal_contract,
)


def _model(*, hidden=False):
    return {
        "nodes": [
            {"name": "X", "parents": {}, "intercept": 0.0},
            {"name": "M", "parents": {"X": 2.0}, "intercept": 1.0},
            {"name": "Y", "parents": {"X": 1.0, "M": 3.0}, "intercept": -1.0},
        ],
        "hidden_confounding_addressed": hidden,
        "identification_basis": "explicit test SCM",
    }


def _engine(**kwargs):
    return CausalCounterfactualEngine(CausalModel.from_mapping(_model(**kwargs)))


def test_topological_evaluation_and_do_intervention_severs_incoming_equation():
    engine = _engine()
    baseline = engine.evaluate(exogenous={"X": 2.0})
    assert baseline == {"X": 2.0, "M": 5.0, "Y": 16.0}
    changed = engine.evaluate(exogenous={"X": 2.0}, intervention={"M": 10.0})
    assert changed == {"X": 2.0, "M": 10.0, "Y": 31.0}


def test_counterfactual_uses_abduction_action_prediction_same_unit_disturbances():
    engine = _engine()
    factual = {"X": 2.0, "M": 6.0, "Y": 20.0}
    disturbances = engine.abduce(factual)
    assert disturbances == {"X": 2.0, "M": 1.0, "Y": 1.0}

    result = engine.counterfactual(
        factual=factual,
        intervention={"X": 4.0},
        targets=["M", "Y"],
    )
    assert result.predicted_values == {"M": 10.0, "Y": 35.0}
    assert result.deltas == {"M": 4.0, "Y": 15.0}
    assert result.exogenous_disturbances == disturbances
    assert result.causal_graph_empirically_proven is False
    assert result.real_world_effect_proven is False
    assert "hidden confounding" in " ".join(result.warnings)


def test_interventional_contrast_is_b_minus_a_and_not_measured_effect():
    result = _engine(hidden=True).interventional_contrast(
        intervention_a={"X": 1.0},
        intervention_b={"X": 3.0},
        targets=["Y"],
    )
    # Y = -1 + X + 3*(1 + 2X) = 2 + 7X, so delta is 14.
    assert result.factual_values["Y"] == 9.0
    assert result.predicted_values["Y"] == 23.0
    assert result.deltas["Y"] == 14.0
    assert result.real_world_effect_proven is False


def test_cycle_unknown_parent_duplicate_and_self_parent_fail_closed():
    with pytest.raises(ValueError, match="acyclic"):
        CausalModel.from_mapping({
            "nodes": [
                {"name": "A", "parents": {"B": 1}},
                {"name": "B", "parents": {"A": 1}},
            ]
        })
    with pytest.raises(ValueError, match="unknown parent"):
        CausalModel.from_mapping({"nodes": [{"name": "A", "parents": {"Z": 1}}]})
    with pytest.raises(ValueError, match="unique"):
        CausalModel.from_mapping({"nodes": [{"name": "A"}, {"name": "A"}]})
    with pytest.raises(ValueError, match="own parent"):
        CausalModel.from_mapping({"nodes": [{"name": "A", "parents": {"A": 1}}]})


def test_nonfinite_values_and_unknown_interventions_fail_closed():
    engine = _engine()
    with pytest.raises(ValueError, match="finite"):
        engine.evaluate(exogenous={"X": float("nan")})
    with pytest.raises(ValueError, match="unknown node"):
        engine.evaluate(intervention={"Z": 1.0})
    with pytest.raises(ValueError, match="every model node"):
        engine.counterfactual(
            factual={"X": 1.0, "M": 3.0},
            intervention={"X": 2.0},
        )


def test_counterfactual_requires_explicit_intervention_and_unique_known_targets():
    engine = _engine()
    factual = {"X": 1.0, "M": 3.0, "Y": 9.0}
    with pytest.raises(ValueError, match="must not be empty"):
        engine.counterfactual(factual=factual, intervention={})
    with pytest.raises(ValueError, match="unique"):
        engine.counterfactual(
            factual=factual, intervention={"X": 2.0}, targets=["Y", "Y"]
        )
    with pytest.raises(ValueError, match="unknown"):
        engine.counterfactual(
            factual=factual, intervention={"X": 2.0}, targets=["Z"]
        )


def test_deterministic_model_and_result_hashes():
    engine_a = _engine()
    engine_b = _engine()
    factual = {"X": 1.0, "M": 3.25, "Y": 9.5}
    a = engine_a.counterfactual(
        factual=factual, intervention={"X": 2.0}, targets=["Y"]
    )
    b = engine_b.counterfactual(
        factual=factual, intervention={"X": 2.0}, targets=["Y"]
    )
    assert engine_a.model.model_hash == engine_b.model.model_hash
    assert a.result_hash == b.result_hash


def test_coefficient_sensitivity_is_bounded_and_reports_model_uncertainty_not_truth():
    rows = _engine().coefficient_sensitivity(
        factual={"X": 2.0, "M": 5.0, "Y": 16.0},
        intervention={"X": 4.0},
        target="Y",
        relative_perturbation=0.1,
    )
    assert len(rows) == 6  # three directed coefficients x +/- perturbation
    assert all(row["causal_truth_proven"] is False for row in rows)
    assert any(abs(row["delta_from_base"]) > 0 for row in rows)
    with pytest.raises(ValueError, match="\(0, 0.5\]"):
        _engine().coefficient_sensitivity(
            factual={"X": 2.0, "M": 5.0, "Y": 16.0},
            intervention={"X": 4.0},
            target="Y",
            relative_perturbation=0.75,
        )


def test_public_contract_never_claims_causal_discovery_or_real_world_truth():
    payload = evaluate_causal_contract({
        "model": _model(),
        "factual": {"X": 1.0, "M": 3.0, "Y": 9.0},
        "intervention": {"X": 2.0},
        "targets": ["Y"],
    })
    assert payload["status"] == "MODELED_COUNTERFACTUAL"
    assert payload["natural_language_causal_discovery_performed"] is False
    assert payload["causal_graph_empirically_proven"] is False
    assert payload["real_world_effect_proven"] is False
    assert payload["truth_proven"] is False
    assert payload["identification_basis"] == "explicit test SCM"


def test_public_contract_rejects_schema_smuggling():
    with pytest.raises(ValueError, match="schema"):
        evaluate_causal_contract({
            "model": _model(),
            "factual": {"X": 1, "M": 3, "Y": 9},
            "intervention": {"X": 2},
            "targets": ["Y"],
            "trust_me": True,
        })
