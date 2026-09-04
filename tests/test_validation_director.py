from research_engine.validation_contracts import (
    FAIL, INCONCLUSIVE, NOT_TESTED, PASS, REQUIRED_SECTIONS, RESULT_OBSERVED, TEST_PERFORMED,
)
from research_engine.validation_director import AI2ValidationDirector, attach_ai2_validation, validate_ai2_packet


def hypothesis():
    return {"id": "H1", "status": "UNTESTED HYPOTHESIS", "statement": "Treatment X reduces outcome Y vs standard care.",
        "prediction": {"variables": [{"name": "treatment", "role": "independent", "unit": "category"},
                                     {"name": "outcome Y", "role": "dependent", "unit": "score"}],
                       "expected_outcome": "Outcome Y is lower under X.", "falsification_condition": "No reproducible reduction vs control."},
        "experiment": {"dataset_or_sample": "Pre-registered eligible sample", "control_or_baseline": "Standard care",
            "measured_variables": ["treatment", "outcome Y"], "experimental_setup": "Randomized blinded comparison where feasible",
            "statistical_metric": "Pre-specified effect size", "null_hypothesis": "No difference between groups.",
            "confounders": ["baseline severity"], "falsification_condition": "No reproducible reduction vs control.",
            "replication_method": "Independent site repeats locked protocol."}}


def result():
    return {"question": "Does Treatment X reduce outcome Y?", "answer": "Research answer remains separate.",
            "sources": [{"id": "S1"}, {"id": "S2"}], "hypotheses": [hypothesis()],
            "verification": {"status": "VERIFIED", "claim_checks": {"gate_passed": True}}}


def experiment(packet):
    return packet["sections"]["6. Exact Experiments / Backtests / Simulations Required"]["domain_hypothesis_experiments"][0]


def trading(packet):
    return packet["sections"]["6. Exact Experiments / Backtests / Simulations Required"]["trading_validation_standard"]


def test_packet_has_exact_required_sections_and_integrity():
    p = AI2ValidationDirector().build_packet("Does Treatment X work?", result())
    assert p["title"] == "AI-2 VALIDATION PACKET"
    assert tuple(p["sections"].keys()) == REQUIRED_SECTIONS
    assert p["packet_integrity"]["valid"] is True


def test_exact_experiment_contract_and_no_fake_results():
    e = experiment(AI2ValidationDirector().build_packet("Does Treatment X work?", result()))
    for field in ("Hypothesis", "Variables", "Dataset/sample", "Experimental setup", "Prediction", "Null hypothesis",
                  "Metric", "Baseline", "Confounders", "Falsification condition", "Replication method"): assert field in e
    assert e["hypothesis_status"] == INCONCLUSIVE and e["result"] == NOT_TESTED
    assert e["statistical_validation"]["effect_size"] == NOT_TESTED


def test_unknown_inputs_stay_unknown():
    e = experiment(AI2ValidationDirector().build_packet("Does A affect B?", {"hypotheses": [{"id": "H1", "statement": "A may affect B."}]}))
    assert e["Dataset/sample"] == "UNKNOWN" and e["Metric"] == "UNKNOWN" and e["Baseline"] == "UNKNOWN"
    assert e["success_threshold"] == "TO BE ESTIMATED" and e["result"] == NOT_TESTED


def test_observed_requires_provenance():
    h = hypothesis(); h.update({"test_state": RESULT_OBSERVED, "observed_result": "Candidate beat baseline."})
    e = experiment(AI2ValidationDirector().build_packet("test", {"hypotheses": [h]}))
    assert e["test_state"] == TEST_PERFORMED and e["result"] == NOT_TESTED


def test_provenanced_narrative_result_is_observed_but_not_decisive():
    h = hypothesis(); h.update({"test_state": RESULT_OBSERVED, "observed_result": "Candidate beat baseline.",
                                "result_provenance": {"test_id": "T1", "dataset_id": "locked"}})
    p = AI2ValidationDirector().build_packet("test", {"hypotheses": [h]}); e = experiment(p)
    assert e["test_state"] == RESULT_OBSERVED and e["hypothesis_status"] == INCONCLUSIVE
    assert validate_ai2_packet(p)["valid"] is True


def test_upstream_pass_without_observed_result_is_downgraded():
    h = hypothesis(); h["status"] = "PASS"
    e = experiment(AI2ValidationDirector().build_packet("test", {"hypotheses": [h]}))
    assert e["upstream_claimed_status"] == "PASS" and e["hypothesis_status"] == INCONCLUSIVE


def test_numeric_receipt_computes_effect_uncertainty_and_explicit_pass():
    r = result()
    r["validation_receipts"] = [{
        "hypothesis_id": "H1",
        "provenance": {"test_id": "T1", "dataset_id": "D1"},
        "observations": {"candidate": [4, 5, 6, 7], "baseline": [1, 2, 3, 4]},
        "confidence_level": 0.95, "bootstrap_iterations": 40, "permutation_iterations": 40,
        "random_seed": 17,
        "decision_rule": {"metric": "mean_difference", "operator": ">", "threshold": 0},
    }]
    p = AI2ValidationDirector().build_packet("Does Treatment X work?", r); e = experiment(p)
    assert e["test_state"] == RESULT_OBSERVED and e["hypothesis_status"] == PASS
    assert e["quantitative_result_analysis"]["metrics"]["mean_difference"] == 3.0
    assert isinstance(e["statistical_validation"]["confidence_interval"], dict)
    assert isinstance(e["statistical_validation"]["bootstrap"], dict)
    assert isinstance(e["statistical_validation"]["permutation_test"], dict)
    assert p["packet_integrity"]["valid"] is True


def test_numeric_receipt_without_decision_rule_stays_inconclusive():
    r = result(); r["validation_receipts"] = [{
        "hypothesis_id": "H1", "provenance": {"test_id": "T2", "dataset_id": "D2"},
        "observations": {"candidate": [3, 4, 5], "baseline": [1, 2, 3]},
    }]
    e = experiment(AI2ValidationDirector().build_packet("test", r))
    assert e["test_state"] == RESULT_OBSERVED and e["hypothesis_status"] == INCONCLUSIVE
    assert e["decision_basis"]["status"] == INCONCLUSIVE


def test_numeric_receipt_without_provenance_cannot_be_observed():
    r = result(); r["validation_receipts"] = [{
        "hypothesis_id": "H1", "observations": {"candidate": [3, 4], "baseline": [1, 2]},
        "decision_rule": {"metric": "mean_difference", "operator": ">", "threshold": 0},
    }]
    e = experiment(AI2ValidationDirector().build_packet("test", r))
    assert e["test_state"] != RESULT_OBSERVED and e["result"] == NOT_TESTED


def test_trading_standard_complete_and_claimed_metrics_not_invented():
    r = {"trade_contract": {"instrument": "MARKET CFD", "timeframe": "5m", "session": "session A",
                            "entry_rule": "locked", "stop_loss": "locked stop", "take_profit": "locked target",
                            "spread": "historical series required", "win_rate": .99, "profit_factor": 99},
         "hypotheses": [{"id": "H1", "statement": "Rule may have positive net expectancy."}]}
    t = trading(AI2ValidationDirector().build_packet("Backtest MARKET CFD 5m strategy", r))
    assert t["exact_instrument"] == "MARKET CFD" and t["timeframe"] == "5m" and t["entry"] == "locked"
    for m in ("win_rate", "expectancy", "profit_factor", "maximum_drawdown", "risk_of_ruin", "MAE", "MFE",
              "out_of_sample", "walk_forward", "monte_carlo", "parameter_stability", "regime_stability", "edge_decay"):
        assert t[m] == NOT_TESTED


def test_trading_receipt_calculates_metrics_but_friction_gate_controls_decision():
    base = {"trade_contract": {"instrument": "MARKET CFD", "timeframe": "5m"},
            "hypotheses": [{"id": "H1", "statement": "Rule may have positive net expectancy."}],
            "trade_result_receipt": {
                "provenance": {"test_id": "BT1", "dataset_id": "OOS1"},
                "trade_returns": [1.0, -0.5, 2.0, -1.0], "dataset_role": "untouched_test", "unit": "R",
                "decision_rule": {"metric": "expectancy", "operator": ">", "threshold": 0},
                "monte_carlo_iterations": 20, "random_seed": 3,
                "walk_forward_folds": [[1.0, -0.5], [2.0, -1.0]],
                "parameter_scenarios": {"near": [0.5, -0.1, 0.7]},
                "regime_returns": {"A": [1.0, -0.5], "B": [2.0, -1.0]},
                "temporal_returns": {"early": [1.0, 0.5], "late": [0.3, -0.1]},
            }}
    t = trading(AI2ValidationDirector().build_packet("Backtest MARKET CFD strategy", base))
    assert t["sample_size"] == 4 and t["win_rate"] == 0.5 and t["expectancy"] == 0.375
    assert t["observed_result_status"] == INCONCLUSIVE
    assert isinstance(t["out_of_sample"], dict) and isinstance(t["walk_forward"], dict)
    assert isinstance(t["monte_carlo"], dict) and isinstance(t["parameter_stability"], dict)

    base["trade_result_receipt"]["returns_are_net_of_friction"] = True
    t2 = trading(AI2ValidationDirector().build_packet("Backtest MARKET CFD strategy", base))
    assert t2["observed_result_status"] == PASS and t2["result_decision"]["rule_source"] == "SUPPLIED_IN_RESULT_RECEIPT"


def test_no_loss_trading_receipt_does_not_emit_infinity():
    r = {"hypotheses": [{"id": "H1", "statement": "Rule may have edge."}],
         "trade_result_receipt": {"provenance": {"test_id": "BT2", "dataset_id": "D"},
                                  "trade_returns": [1, 2, 3], "returns_are_net_of_friction": True}}
    t = trading(AI2ValidationDirector().build_packet("trading strategy", r))
    assert t["profit_factor"] == NOT_TESTED


def test_full_bias_robustness_friction_failure_coverage():
    s = AI2ValidationDirector().build_packet("test", result())["sections"]
    assert len(s["7. Bias & Leakage Risks"]) >= 13 and len(s["8. Robustness Plan"]) >= 9
    assert len(s["10. Real-World Friction"]) >= 14 and len(s["11. Failure Modes"]) >= 9
    assert all(row["status"] == NOT_TESTED for row in s["7. Bias & Leakage Risks"])


def test_attach_is_additive_and_preserves_original():
    original = result(); enriched = attach_ai2_validation(original["question"], original)
    assert "ai2_validation" not in original and enriched["answer"] == original["answer"] and enriched["sources"] == original["sources"]
    assert enriched["ai2_validation"]["packet_integrity"]["valid"] is True


def test_cross_agent_alerts_are_exact():
    alerts = AI2ValidationDirector().build_packet("test", result())["sections"]["14. Cross-Agent Alerts"]
    assert set(alerts) == {"CROSS-AGENT ALERT — AI-1", "CROSS-AGENT ALERT — AI-3", "CROSS-AGENT ALERT — AI-4"}


def test_existing_experiment_intelligence_is_reused_not_promoted():
    r = result(); r["coverage"] = {"experiment_intelligence": {"status": "ASSESSMENT_READY", "recommended_test": "T2"}}
    p = AI2ValidationDirector().build_packet("test", r); sec = p["sections"]["6. Exact Experiments / Backtests / Simulations Required"]
    assert sec["existing_experiment_intelligence"]["source_path"] == "coverage.experiment_intelligence"
    assert sec["existing_experiment_intelligence"]["packet"]["recommended_test"] == "T2"
    assert experiment(p)["result"] == NOT_TESTED


def test_second_pass_prioritizes_received_red_team_without_restart():
    outputs = {"AI-1": {"hypotheses": [{"id": "E1", "statement": "Mechanism A."}]},
               "AI-4": {"objection": "target leakage and catastrophic tail risk"}}
    p = AI2ValidationDirector().build_packet("test", result(), outputs); tasks = p["sections"]["15. Highest-Value Second-Pass Validation Tasks"]
    assert p["second_pass_context"]["red_team_input_present"] is True and "Triangulate" in tasks[0]["task"]
    assert any("red-team" in t["task"].lower() for t in tasks)
    assert [t["priority"] for t in tasks] == list(range(1, len(tasks) + 1))


def test_math_symbols_require_definition_unit_interpretation():
    r = {"mathematical_model": {"equation": "y = beta*x", "objective": "Predict y", "parameters": {"beta": {"definition": "slope"}}}}
    m = AI2ValidationDirector().build_packet("predict", r)["sections"]["3. Mathematical Model"]["domain_models_found"][0]
    assert m["symbol_contract_complete"] is False and m["status"] == INCONCLUSIVE and m["symbol_metadata"][0]["unit"] == "UNKNOWN"


def test_independent_hypotheses_have_required_mechanism_test_falsification_baseline():
    rows = AI2ValidationDirector().build_packet("test", result())["sections"]["5. Independent Testable Hypotheses"]
    assert len(rows) >= 3
    for row in rows:
        for key in ("mechanism", "variables", "prediction", "test", "falsification", "baseline"): assert row[key]
