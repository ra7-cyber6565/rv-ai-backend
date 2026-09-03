import pytest

from research_engine.reality_oracle import make_observation_receipt
from research_engine.reality_oracle_memory import (
    contract_from_scientific_memory,
    evaluate_memory_prediction,
)
from research_engine.scientific_memory import ScientificMemory


PROTO = "c" * 64
DIGEST = "d" * 64


def _memory(tmp_path):
    memory = ScientificMemory("oracle", directory=str(tmp_path))
    memory.preregister_prediction(
        "pred-1",
        hypothesis_id="H1",
        condition="locked holdout after timestamp",
        metric="accuracy",
        direction=">=",
        threshold=0.80,
        evaluation_after="2099-01-01T01:00:00+00:00",
        protocol_hash=PROTO,
    )
    return memory


def _observation(**overrides):
    data = {
        "observation_id": "obs-1",
        "metric": "accuracy",
        "unit": "fraction",
        "observed_value": 0.82,
        "observed_at": "2099-01-01T02:00:00+00:00",
        "source_id": "sensor-1",
        "source_kind": "sensor",
        "source_digest": DIGEST,
        "raw_reference": "lab://run/1/accuracy",
    }
    data.update(overrides)
    return make_observation_receipt(**data)


def test_bridge_uses_existing_immutable_prediction_registry(tmp_path):
    memory = _memory(tmp_path)
    contract = contract_from_scientific_memory(memory, "pred-1", unit="fraction")
    assert contract.prediction_id == "pred-1"
    assert contract.hypothesis_id == "H1"
    assert contract.rule == "directional"
    assert contract.direction == ">="
    assert contract.target == 0.80
    assert contract.protocol_hash == PROTO


def test_default_evaluation_is_read_only_and_mints_no_live_proof(tmp_path):
    memory = _memory(tmp_path)
    result = evaluate_memory_prediction(
        memory, "pred-1", _observation(), unit="fraction"
    )
    assert result.evaluation.status == "MATCH"
    assert result.committed_to_memory is False
    assert result.memory_outcome is None
    assert result.live_proof_minted is False
    assert result.truth_proven is False
    assert memory.load()["predictions"]["pred-1"]["resolved"] is False


def test_explicit_commit_records_outcome_but_not_live_or_truth_proof(tmp_path):
    memory = _memory(tmp_path)
    result = evaluate_memory_prediction(
        memory,
        "pred-1",
        _observation(),
        unit="fraction",
        commit=True,
        evidence_ids=("evidence-1",),
    )
    assert result.committed_to_memory is True
    assert result.memory_outcome["passed"] is True
    assert result.memory_outcome["evidence_ids"] == ["evidence-1"]
    assert result.live_proof_minted is False
    assert result.truth_proven is False
    assert memory.load()["predictions"]["pred-1"]["resolved"] is True
    assert memory.audit_integrity()["valid"] is True


def test_inconclusive_observation_cannot_mutate_prediction_memory(tmp_path):
    memory = _memory(tmp_path)
    with pytest.raises(ValueError, match="inconclusive"):
        evaluate_memory_prediction(
            memory,
            "pred-1",
            _observation(metric="loss"),
            unit="fraction",
            commit=True,
        )
    assert memory.load()["predictions"]["pred-1"]["resolved"] is False


def test_resolved_prediction_cannot_be_reused_for_new_oracle_contract(tmp_path):
    memory = _memory(tmp_path)
    evaluate_memory_prediction(
        memory, "pred-1", _observation(), unit="fraction", commit=True
    )
    with pytest.raises(ValueError, match="already resolved"):
        contract_from_scientific_memory(memory, "pred-1", unit="fraction")


def test_memory_protocol_hash_must_be_real_sha256(tmp_path):
    memory = ScientificMemory("oracle-bad", directory=str(tmp_path))
    memory.preregister_prediction(
        "pred-1",
        hypothesis_id="H1",
        condition="condition",
        metric="accuracy",
        direction=">=",
        threshold=0.8,
        evaluation_after="2099-01-01T01:00:00+00:00",
        protocol_hash="not-a-digest",
    )
    with pytest.raises(ValueError, match="SHA-256"):
        contract_from_scientific_memory(memory, "pred-1", unit="fraction")


def test_observation_before_memory_evaluation_window_stays_unresolved(tmp_path):
    memory = _memory(tmp_path)
    result = evaluate_memory_prediction(
        memory,
        "pred-1",
        _observation(observed_at="2099-01-01T00:30:00+00:00"),
        unit="fraction",
    )
    assert result.evaluation.status == "INCONCLUSIVE"
    assert memory.load()["predictions"]["pred-1"]["resolved"] is False
