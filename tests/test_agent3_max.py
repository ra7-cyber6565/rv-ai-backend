"""Max-level Agent 3 facade tests — no network/model calls."""
from __future__ import annotations

from research_engine.agent3 import Agent3ValidationEngine, classification_metrics
from research_engine.validation_agent3 import seal_holdout


CLEAR = {
    "look_ahead": False,
    "hindsight": False,
    "survivorship": False,
    "data_snooping": False,
    "cherry_picking": False,
    "publication_bias": False,
    "selection_bias": False,
    "p_hacking": False,
    "hidden_leakage": False,
    "future_known_variables": False,
    "revised_data": False,
}


def _hypothesis(domain="general"):
    row = {
        "id": "H1",
        "domain": domain,
        "statement": "Candidate produces a reproducible advantage.",
        "dataset": "Frozen v1",
        "timeframe": "2020-2025",
        "unit_of_analysis": "independent observation",
        "how_to_test": "Pre-registered confirmatory test",
        "falsification_rule": "Reject if untouched-test primary metric <= baseline.",
    }
    if domain == "trading":
        row.update({
            "instrument_feed": "US100 broker tick feed",
            "regime": "London/NY liquid sessions",
            "session": "NY AM",
            "long_setup": "long rule supplied by Agent 2",
            "short_setup": "short rule supplied by Agent 2",
            "entry": "market/limit rule supplied by Agent 2",
            "stop_loss": "fixed hypothesis stop rule",
            "take_profit": "fixed hypothesis TP rule",
            "position_sizing": "fixed fractional risk",
            "no_trade": "skip excluded conditions",
            "news_rule": "skip pre-specified high-impact window",
        })
    return row


def _clean():
    seal = seal_holdout([1, 2, 3])
    return {
        "split": {
            "train": "A",
            "validation": "B",
            "test": "C",
            "test_touched_for_tuning": False,
            "holdout_seal_before": seal,
            "holdout_seal_after": seal,
        },
        "test_touched_for_tuning": False,
        "bias_flags": dict(CLEAR),
    }


def test_classification_metrics_include_majority_baseline_and_no_fake_probability_metrics():
    out = classification_metrics([0, 0, 1, 1], [0, 0, 1, 0])
    assert out["status"] == "TESTED"
    assert out["accuracy"] == 0.75
    assert out["majority_baseline_accuracy"] == 0.5
    assert out["candidate_beats_majority_baseline"] is True
    assert "brier_score" not in out
    assert "log_loss" not in out


def test_binary_probabilities_add_brier_and_log_loss_only_when_supplied():
    out = classification_metrics([0, 1, 1, 0], [0, 1, 1, 0], [0.1, 0.9, 0.8, 0.2])
    assert out["status"] == "TESTED"
    assert out["brier_score"] >= 0
    assert out["log_loss"] >= 0


def test_classification_execution_is_converted_to_real_executed_packet():
    execution = {
        **_clean(),
        "kind": "classification",
        "y_true": [0, 0, 1, 1, 1, 0],
        "y_pred": [0, 0, 1, 1, 0, 0],
        "friction": {"status": "TESTED"},
        "falsified": False,
        "primary_metric": "accuracy",
        "pass_threshold": 0.5,
        "parameter_runs": [{"accuracy": .80}, {"accuracy": .82}, {"accuracy": .78}],
    }
    packet = Agent3ValidationEngine().validate("classification test", {}, {"hypotheses": [_hypothesis("predictive_modeling")]}, {"H1": execution})
    result = packet["14. FINAL VALIDATION PACKET FOR AGENT 4"]["validations"][0]
    assert result["result"]["executed"] is True
    assert result["result"]["metrics"]["accuracy"] > 0
    assert result["result"]["statistical_tests"]["classification_detail"]["status"] == "TESTED"


def test_insufficient_sample_forces_inconclusive_even_if_metrics_look_good():
    execution = {
        **_clean(),
        "executed": True,
        "sample_size": 20,
        "minimum_sample_size": 100,
        "metrics": {"score": 0.99},
        "baseline_results": {"candidate_beats_baseline": True},
        "friction": {"status": "TESTED"},
        "falsified": False,
        "primary_metric": "score",
        "pass_threshold": 0.8,
        "parameter_runs": [{"score": .95}, {"score": .96}],
    }
    packet = Agent3ValidationEngine().validate("q", {}, {"hypotheses": [_hypothesis()]}, {"H1": execution})
    row = packet["5. Hypothesis results"]["H1"]
    assert row["status"] == "INCONCLUSIVE"
    assert "Sample requirement not met" in row["reason"]
    assert packet["11. Surviving final candidates"] == []


def test_real_world_friction_failure_is_hard_fail():
    execution = {
        **_clean(),
        "executed": True,
        "sample_size": 500,
        "metrics": {"score": 1.0},
        "baseline_results": {"candidate_beats_baseline": True},
        "friction": {"status": "FAIL", "reason": "costs erase edge"},
        "falsified": False,
        "primary_metric": "score",
        "pass_threshold": 0.8,
        "parameter_runs": [{"score": .9}, {"score": .91}],
    }
    packet = Agent3ValidationEngine().validate("q", {}, {"hypotheses": [_hypothesis()]}, {"H1": execution})
    row = packet["5. Hypothesis results"]["H1"]
    assert row["status"] == "FAIL"
    assert "friction" in row["reason"].lower()
    assert packet["11. Surviving final candidates"] == []


def test_trading_domain_contract_contains_all_requested_operational_fields():
    packet = Agent3ValidationEngine().validate("US100 trading", {}, {"hypotheses": [_hypothesis("trading")]})
    validation = packet["14. FINAL VALIDATION PACKET FOR AGENT 4"]["validations"][0]
    contract = validation["test_matrix"]["domain_specific"]
    for key in (
        "instrument/feed", "regime", "session", "exact long setup", "exact short setup",
        "entry", "stop", "TP", "position sizing", "no-trade", "news",
        "transaction costs", "sample size requirement", "out-of-sample",
        "walk-forward", "Monte Carlo", "parameter robustness", "edge decay",
    ):
        assert key in contract


def test_trading_missing_operational_fields_stay_unknown_not_invented():
    h = _hypothesis("trading")
    h.pop("entry")
    h.pop("take_profit")
    packet = Agent3ValidationEngine().validate("US100 trading", {}, {"hypotheses": [h]})
    contract = packet["14. FINAL VALIDATION PACKET FOR AGENT 4"]["validations"][0]["test_matrix"]["domain_specific"]
    assert contract["entry"] == "NOT TESTED / UNKNOWN"
    assert contract["TP"] == "NOT TESTED / UNKNOWN"


def test_regime_and_walk_forward_receipts_are_kept_separate():
    execution = {
        **_clean(),
        "executed": True,
        "sample_size": 300,
        "metrics": {"score": .8},
        "baseline_results": {"candidate_beats_baseline": True},
        "friction": {"status": "TESTED"},
        "falsified": False,
        "primary_metric": "score",
        "pass_threshold": .6,
        "parameter_runs": [{"score": .72}, {"score": .75}],
        "regime_runs": [{"regime": "A", "score": .8}, {"regime": "B", "score": .65}],
        "walk_forward_runs": [{"fold": 1, "score": .7}, {"fold": 2, "score": .68}],
    }
    packet = Agent3ValidationEngine().validate("q", {}, {"hypotheses": [_hypothesis()]}, {"H1": execution})
    robust = packet["6. Robustness tests"]["H1"]
    assert robust["regime_testing"]["status"] == "TESTED"
    assert robust["walk_forward"]["status"] == "TESTED"
    assert robust["walk_forward"]["folds"] == 2


def test_fatal_regime_failure_rejects_only_tested_candidate():
    execution = {
        **_clean(),
        "executed": True,
        "sample_size": 300,
        "metrics": {"score": .8},
        "baseline_results": {"candidate_beats_baseline": True},
        "friction": {"status": "TESTED"},
        "falsified": False,
        "primary_metric": "score",
        "pass_threshold": .6,
        "parameter_runs": [{"score": .72}, {"score": .75}],
        "regime_failure_is_fatal": True,
        "regime_runs": [{"regime": "normal", "score": .8}, {"regime": "stress", "score": -.2, "failed": True}],
    }
    packet = Agent3ValidationEngine().validate("q", {}, {"hypotheses": [_hypothesis()]}, {"H1": execution})
    row = packet["5. Hypothesis results"]["H1"]
    assert row["status"] == "FAIL"
    assert "tested model/scope" in row["reason"]


def test_edge_decay_pre_specified_failure_is_fail():
    execution = {
        **_clean(),
        "executed": True,
        "sample_size": 300,
        "metrics": {"score": .8},
        "baseline_results": {"candidate_beats_baseline": True},
        "friction": {"status": "TESTED"},
        "falsified": False,
        "primary_metric": "score",
        "pass_threshold": .6,
        "parameter_runs": [{"score": .72}, {"score": .75}],
        "edge_decay_failed": True,
    }
    packet = Agent3ValidationEngine().validate("q", {}, {"hypotheses": [_hypothesis()]}, {"H1": execution})
    assert packet["5. Hypothesis results"]["H1"]["status"] == "FAIL"


def test_agent4_packet_contains_max_hard_rules():
    packet = Agent3ValidationEngine().validate("q", {}, {"hypotheses": [_hypothesis()]})
    final = packet["14. FINAL VALIDATION PACKET FOR AGENT 4"]
    rules = " ".join(final["agent3_max_rules"]).lower()
    assert "baseline" in rules
    assert "untouched test" in rules
    assert "leakage" in rules
    assert "friction" in rules
    assert "unknown" in rules
