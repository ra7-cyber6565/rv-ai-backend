import json

import pytest

from research_engine.scientific_memory import ScientificMemory


def _memory(tmp_path):
    return ScientificMemory("project-1", directory=str(tmp_path))


def test_temporal_fact_is_queryable_and_id_is_immutable(tmp_path):
    memory = _memory(tmp_path)
    first = memory.record_temporal_fact(
        "fact-ceo-v1",
        subject="CompanyX",
        predicate="CEO",
        object_value="Person A",
        valid_from="2025-01-01",
        valid_to="2025-12-31",
        context="official filing",
        evidence_ids=["SRC1"],
    )
    assert first["object"] == "Person A"
    assert memory.facts_at("2025-06-01", subject="CompanyX")[0]["fact_id"] == "fact-ceo-v1"
    assert memory.facts_at("2026-01-01", subject="CompanyX") == []

    replay = memory.record_temporal_fact(
        "fact-ceo-v1",
        subject="CompanyX",
        predicate="CEO",
        object_value="Person A",
        valid_from="2025-01-01",
        valid_to="2025-12-31",
        context="official filing",
        evidence_ids=["SRC1"],
    )
    assert replay["fact_id"] == "fact-ceo-v1"

    with pytest.raises(ValueError, match="immutable"):
        memory.record_temporal_fact(
            "fact-ceo-v1",
            subject="CompanyX",
            predicate="CEO",
            object_value="Person B",
            valid_from="2025-01-01",
            valid_to="2025-12-31",
        )


def test_belief_versions_preserve_history_and_supersede_prior_active_version(tmp_path):
    memory = _memory(tmp_path)
    v1 = memory.add_belief_version(
        "H1", statement="effect exists", confidence=0.4, evidence_ids=["E1"], reason="initial evidence"
    )
    v2 = memory.add_belief_version(
        "H1",
        statement="effect exists under condition X",
        confidence=0.7,
        evidence_ids=["E1", "E2"],
        reason="replication narrowed the claim",
    )
    history = memory.belief_history("H1")
    assert v1["version"] == 1
    assert v2["version"] == 2
    assert history[0]["status"] == "SUPERSEDED"
    assert history[1]["status"] == "ACTIVE"
    assert history[0]["content_hash"] != history[1]["content_hash"]


def test_truth_debt_quantifies_unresolved_assumptions_and_disappears_when_resolved(tmp_path):
    memory = _memory(tmp_path)
    memory.register_assumption(
        "A1",
        text="energy density is 400 Wh/kg",
        confidence=0.5,
        severity=2.0,
        downstream_ids=["C1", "C2"],
        evidence_ids=["E1"],
    )
    report = memory.truth_debt_report()
    assert report["unresolved"] == 1
    assert report["total_truth_debt"] == 2.0
    assert report["items"][0]["downstream_count"] == 2
    memory.resolve_assumption("A1", resolution="measured directly", supported=True)
    assert memory.truth_debt_report()["total_truth_debt"] == 0.0


def test_prediction_registry_freezes_protocol_before_outcome_and_calibrates(tmp_path):
    memory = _memory(tmp_path)
    memory.add_belief_version(
        "H1", statement="metric should exceed threshold", confidence=0.8, reason="pre-test estimate"
    )
    registered = memory.preregister_prediction(
        "P1",
        hypothesis_id="H1",
        condition="locked holdout",
        metric="profit_factor",
        direction=">",
        threshold=1.2,
        evaluation_after="2026-09-01",
        protocol_hash="sha256:protocol-v1",
    )
    assert len(registered["registration_hash"]) == 64
    replay = memory.preregister_prediction(
        "P1",
        hypothesis_id="H1",
        condition="locked holdout",
        metric="profit_factor",
        direction=">",
        threshold=1.2,
        evaluation_after="2026-09-01",
        protocol_hash="sha256:protocol-v1",
    )
    assert replay["registration_hash"] == registered["registration_hash"]

    with pytest.raises(ValueError, match="immutable"):
        memory.preregister_prediction(
            "P1",
            hypothesis_id="H1",
            condition="locked holdout",
            metric="profit_factor",
            direction=">",
            threshold=1.1,
            evaluation_after="2026-09-01",
            protocol_hash="sha256:protocol-v1",
        )

    outcome = memory.resolve_prediction("P1", observed_value=1.35, evidence_ids=["HOLDOUT1"])
    assert outcome["passed"] is True
    with pytest.raises(ValueError, match="already resolved"):
        memory.resolve_prediction("P1", observed_value=1.0)

    assert memory.calibration_report() == {
        "count": 1,
        "brier_score": 0.04,
        "mean_confidence": 0.8,
        "observed_rate": 1.0,
    }


def test_champion_challenger_requires_objective_improvement_and_independent_validation(tmp_path):
    memory = _memory(tmp_path)
    memory.register_model(
        "M1",
        metrics={"profit_factor": 1.3, "max_drawdown": 0.18},
        holdout_id="HOLDOUT-A",
        implementation_hash="code-m1",
        independent_validation_ids=["REP-A"],
        status="champion",
    )
    memory.register_model(
        "M2",
        metrics={"profit_factor": 1.5, "max_drawdown": 0.14},
        holdout_id="HOLDOUT-B",
        implementation_hash="code-m2",
        independent_validation_ids=["REP-B"],
        status="challenger",
    )
    decision = memory.promote_challenger(
        "M1",
        "M2",
        objectives={"profit_factor": "max", "max_drawdown": "min"},
        require_distinct_holdout=True,
    )
    assert decision.promoted is True
    assert memory.load()["models"]["M1"]["status"] == "retired"
    assert memory.load()["models"]["M2"]["status"] == "champion"

    memory.register_model(
        "M3",
        metrics={"profit_factor": 2.0, "max_drawdown": 0.10},
        holdout_id="HOLDOUT-C",
        implementation_hash="code-m3",
        independent_validation_ids=[],
        status="challenger",
    )
    failed = memory.promote_challenger(
        "M2", "M3", objectives={"profit_factor": "max", "max_drawdown": "min"}
    )
    assert failed.promoted is False
    assert "challenger has no independent validation" in failed.reasons


def test_model_graveyard_preserves_rejection_reasons(tmp_path):
    memory = _memory(tmp_path)
    memory.register_model("BAD1", metrics={"score": 0.9}, holdout_id="H1", implementation_hash="bad-code")
    memory.reject_model("BAD1", reasons=["look-ahead leakage", "parameter instability"])
    graveyard = memory.model_graveyard()
    assert len(graveyard) == 1
    assert graveyard[0]["model_id"] == "BAD1"
    assert graveyard[0]["rejection_reasons"] == ["look-ahead leakage", "parameter instability"]


def test_dependency_shock_propagates_to_downstream_conclusions(tmp_path):
    memory = _memory(tmp_path)
    memory.set_node_reliability("SOURCE", 1.0)
    memory.set_node_reliability("CLAIM", 0.9)
    memory.set_node_reliability("CONCLUSION", 0.8)
    memory.add_dependency("CLAIM", "SOURCE", weight=0.5)
    memory.add_dependency("CONCLUSION", "CLAIM", weight=0.5)
    shock = memory.propagate_dependency_shock("SOURCE", new_reliability=0.2)
    assert shock["impacted"]["CLAIM"]["new_reliability"] == 0.5
    assert shock["impacted"]["CONCLUSION"]["new_reliability"] == 0.6


def test_atomic_save_reload_and_hash_chain_tamper_detection(tmp_path):
    memory = _memory(tmp_path)
    memory.add_belief_version("H1", statement="test belief", confidence=0.6, reason="evidence")
    memory.save()
    reloaded = _memory(tmp_path)
    assert reloaded.belief_history("H1")[0]["statement"] == "test belief"
    assert reloaded.audit_integrity()["valid"] is True

    with open(reloaded.path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["audit_chain"][0]["event_hash"] = "0" * 64
    with open(reloaded.path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    corrupted = _memory(tmp_path)
    with pytest.raises(ValueError, match="hash mismatch"):
        corrupted.load()


@pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan"), float("inf")])
def test_probabilities_fail_closed(tmp_path, bad):
    memory = _memory(tmp_path)
    with pytest.raises(ValueError):
        memory.add_belief_version("H1", statement="x", confidence=bad, reason="test")
