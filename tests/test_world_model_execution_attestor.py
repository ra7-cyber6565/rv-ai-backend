from pathlib import Path

import pytest

import research_engine.world_model_execution_attestor as attestor_mod
from research_engine.capability_registry import ProofKind
from research_engine.maturity_attestation_readiness import audit_attestation_readiness
from research_engine.maturity_proof import ProofLedger
from research_engine.world_model_execution_attestor import (
    attest_world_model_execution,
    run_world_model_benchmark,
)


KEY = b"M" * 32
NOW = 120_000.0
CAPABILITY_ID = 68


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _route(report, proof_kind):
    capability = next(
        item for item in report.capabilities if item.capability_id == CAPABILITY_ID
    )
    return next(item for item in capability.routes if item.proof_kind is proof_kind)


def test_benchmark_exercises_rollout_counterfactual_and_calibration():
    result = run_world_model_benchmark()
    assert result["benchmark_passed"] is True
    assert all(result["checks"].values())
    assert result["rollout"]["steps"][-1]["state"]["x"] == 9.0
    assert result["counterfactual"]["final_state_delta"]["x"] == 4.0
    assert result["calibration"]["calibrated"] is True
    assert result["world_model_is_reality"] is False
    assert result["sim_to_reality_gap_open"] is True
    assert result["truth_proven"] is False
    assert len(result["benchmark_sha256"]) == 64


def test_attestor_mints_only_execution_and_reproducibility(tmp_path):
    ledger_path = tmp_path / "world-model-proof.jsonl"
    result = attest_world_model_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="ci-world-model-1",
        now=NOW,
    )
    assert result.receipts_added == 2
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.world_model_is_reality is False
    assert result.sim_to_reality_gap_open is True
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
    assert all(row["proof_kind"] != ProofKind.LIVE.value for row in rows)
    assert all(row["proof_kind"] != ProofKind.HARDWARE.value for row in rows)


def test_specialized_readiness_routes_are_repo_backed_but_external():
    report = audit_attestation_readiness(_root())
    execution = _route(report, ProofKind.EXECUTION)
    reproducibility = _route(report, ProofKind.REPRODUCIBILITY)
    assert execution.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
    assert execution.attestor_id == "world-model-execution"
    assert execution.external_required is True
    assert execution.verifiers == ("trusted-execution-attestor",)
    assert execution.subjects == ("capability-68-execution-run",)
    assert reproducibility.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
    assert reproducibility.attestor_id == "world-model-reproducibility"
    assert reproducibility.external_required is True
    assert reproducibility.verifiers == ("trusted-reproducibility-attestor",)
    assert reproducibility.subjects == ("capability-68-reproducibility-run",)


def test_existing_ledger_requires_anchor_and_same_run_is_idempotent(tmp_path):
    ledger_path = tmp_path / "world-model-proof.jsonl"
    first = attest_world_model_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="ci-world-model-2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_world_model_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="ci-world-model-2",
            now=NOW + 1,
        )
    second = attest_world_model_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="ci-world-model-2",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 2


def test_failed_benchmark_cannot_mint_receipts(monkeypatch, tmp_path):
    original = attestor_mod.run_world_model_benchmark

    def failed():
        payload = dict(original())
        payload["benchmark_passed"] = False
        return payload

    monkeypatch.setattr(attestor_mod, "run_world_model_benchmark", failed)
    ledger_path = tmp_path / "world-model-proof.jsonl"
    with pytest.raises(ValueError, match="benchmark failed"):
        attest_world_model_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="failed",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_nondeterministic_benchmark_cannot_mint_reproducibility(monkeypatch, tmp_path):
    original = attestor_mod.run_world_model_benchmark
    counter = {"n": 0}

    def changing():
        payload = dict(original())
        counter["n"] += 1
        payload["nonce"] = counter["n"]
        return payload

    monkeypatch.setattr(attestor_mod, "run_world_model_benchmark", changing)
    ledger_path = tmp_path / "world-model-proof.jsonl"
    with pytest.raises(ValueError, match="not deterministic"):
        attest_world_model_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="nondeterministic",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_truth_boundary_cannot_be_relabelled(monkeypatch, tmp_path):
    original = attestor_mod.run_world_model_benchmark

    def dishonest():
        payload = dict(original())
        payload["world_model_is_reality"] = True
        return payload

    monkeypatch.setattr(attestor_mod, "run_world_model_benchmark", dishonest)
    ledger_path = tmp_path / "world-model-proof.jsonl"
    with pytest.raises(ValueError, match="must not claim model=reality"):
        attest_world_model_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="dishonest",
            now=NOW,
        )
    assert not ledger_path.exists()
