from pathlib import Path

import pytest

import research_engine.neural_symbolic_execution_attestor as attestor_mod
from research_engine.capability_registry import ProofKind
from research_engine.maturity_attestation_readiness import audit_attestation_readiness
from research_engine.maturity_proof import ProofLedger
from research_engine.neural_symbolic_execution_attestor import (
    attest_neural_symbolic_execution,
    run_neural_symbolic_execution_benchmark,
)


KEY = b"N" * 32
NOW = 140_000.0
CAPABILITY_ID = 67


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _route(report, proof_kind):
    capability = next(
        item for item in report.capabilities if item.capability_id == CAPABILITY_ID
    )
    return next(item for item in capability.routes if item.proof_kind is proof_kind)


def _runner(counter=None, *, confidence=0.83, mutate_contract=False):
    def run(task):
        if counter is not None:
            counter["calls"] = counter.get("calls", 0) + 1
        contract = task["formal_logic"]
        if mutate_contract:
            contract = {
                "atoms": ["A", "B"],
                "premises": [{"atom": "A"}],
                "conclusion": {"atom": "B"},
            }
        return {
            "formal_logic": contract,
            "model_confidence": confidence,
            "self_reported_proved": True,
        }
    return run


def test_benchmark_actually_calls_runner_and_independently_verifies_logic():
    counter = {"calls": 0}
    result = run_neural_symbolic_execution_benchmark(
        runner=_runner(counter),
        runner_id="model-A",
        runner_revision="rev-1",
    )
    assert counter["calls"] == 1
    assert result["benchmark_passed"] is True
    assert all(result["checks"].values())
    assert result["external_neural_runner_executed"] is True
    assert result["external_independence_proven"] is False
    assert result["truth_proven"] is False
    audit = result["hybrid_report"]["audits"][0]
    assert audit["symbolic_status"] == "PROVED"
    assert audit["symbolic_entailed"] is True
    assert audit["hybrid_gate_passed"] is True
    assert audit["neural_self_report_can_override_symbolic_gate"] is False
    assert len(result["runner_response_sha256"]) == 64
    assert len(result["benchmark_sha256"]) == 64


def test_attestor_calls_external_runner_twice_and_mints_only_exec_repro(tmp_path):
    counter = {"calls": 0}
    ledger_path = tmp_path / "neural-symbolic-proof.jsonl"
    result = attest_neural_symbolic_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="ci-neural-symbolic-1",
        runner=_runner(counter),
        runner_id="model-A",
        runner_revision="rev-1",
        now=NOW,
    )
    assert counter["calls"] == 2
    assert result.receipts_added == 2
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.external_neural_runner_executed is True
    assert result.external_independence_proven is False
    assert result.truth_proven is False

    capability = result.audit.maturity_report.results[CAPABILITY_ID - 1]
    assert ProofKind.EXECUTION not in capability.missing_proofs
    assert ProofKind.REPRODUCIBILITY not in capability.missing_proofs
    assert ProofKind.WIRING in capability.missing_proofs
    assert ProofKind.CODE in capability.missing_proofs
    assert ProofKind.TEST in capability.missing_proofs

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
    ]
    assert len(rows) == 2
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
    }
    assert {row["verifier"] for row in rows} == {
        "trusted-execution-attestor",
        "trusted-reproducibility-attestor",
    }
    assert all(row["proof_kind"] != ProofKind.INDEPENDENT.value for row in rows)


def test_specialized_readiness_routes_are_repo_backed_but_external():
    report = audit_attestation_readiness(_root())
    execution = _route(report, ProofKind.EXECUTION)
    reproducibility = _route(report, ProofKind.REPRODUCIBILITY)
    assert execution.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
    assert execution.attestor_id == "neural-symbolic-execution"
    assert execution.external_required is True
    assert execution.verifiers == ("trusted-execution-attestor",)
    assert execution.subjects == ("capability-67-execution-run",)
    assert reproducibility.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
    assert reproducibility.attestor_id == "neural-symbolic-reproducibility"
    assert reproducibility.external_required is True
    assert reproducibility.verifiers == ("trusted-reproducibility-attestor",)
    assert reproducibility.subjects == ("capability-67-reproducibility-run",)


def test_runner_cannot_change_frozen_contract():
    with pytest.raises(ValueError, match="changed the frozen formal_logic contract"):
        run_neural_symbolic_execution_benchmark(
            runner=_runner(mutate_contract=True),
            runner_id="model-A",
            runner_revision="rev-1",
        )


def test_nondeterministic_runner_cannot_mint_reproducibility(tmp_path):
    state = {"calls": 0}

    def changing(task):
        state["calls"] += 1
        return {
            "formal_logic": task["formal_logic"],
            "model_confidence": 0.8 if state["calls"] == 1 else 0.81,
            "self_reported_proved": True,
        }

    ledger_path = tmp_path / "neural-symbolic-proof.jsonl"
    with pytest.raises(ValueError, match="not reproducible"):
        attest_neural_symbolic_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="nondeterministic",
            runner=changing,
            runner_id="model-A",
            runner_revision="rev-1",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_invalid_runner_identity_fails_before_ledger_creation(tmp_path):
    ledger_path = tmp_path / "neural-symbolic-proof.jsonl"
    with pytest.raises(ValueError, match="runner_id"):
        attest_neural_symbolic_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="invalid-runner",
            runner=_runner(),
            runner_id="bad runner id",
            runner_revision="rev-1",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_existing_ledger_requires_anchor_and_same_run_is_idempotent(tmp_path):
    ledger_path = tmp_path / "neural-symbolic-proof.jsonl"
    first = attest_neural_symbolic_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="ci-neural-symbolic-2",
        runner=_runner(),
        runner_id="model-A",
        runner_revision="rev-1",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_neural_symbolic_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="ci-neural-symbolic-2",
            runner=_runner(),
            runner_id="model-A",
            runner_revision="rev-1",
            now=NOW + 1,
        )
    second = attest_neural_symbolic_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="ci-neural-symbolic-2",
        runner=_runner(),
        runner_id="model-A",
        runner_revision="rev-1",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 2


def test_attestor_rejects_dishonest_truth_relabel(monkeypatch, tmp_path):
    original = attestor_mod.run_neural_symbolic_execution_benchmark

    def dishonest(**kwargs):
        payload = dict(original(**kwargs))
        payload["truth_proven"] = True
        return payload

    monkeypatch.setattr(attestor_mod, "run_neural_symbolic_execution_benchmark", dishonest)
    ledger_path = tmp_path / "neural-symbolic-proof.jsonl"
    with pytest.raises(ValueError, match="must not claim scientific truth"):
        attest_neural_symbolic_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="dishonest",
            runner=_runner(),
            runner_id="model-A",
            runner_revision="rev-1",
            now=NOW,
        )
    assert not ledger_path.exists()
