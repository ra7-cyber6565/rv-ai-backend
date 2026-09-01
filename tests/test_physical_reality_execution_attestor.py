from pathlib import Path

import pytest

import research_engine.physical_reality_execution_attestor as attestor_mod
from research_engine.capability_registry import ProofKind
from research_engine.maturity_attestation_readiness import audit_attestation_readiness
from research_engine.maturity_proof import ProofLedger
from research_engine.physical_reality_execution_attestor import (
    attest_physical_reality_execution,
    run_physical_reality_benchmark,
)


KEY = b"P" * 32
NOW = 130_000.0
CAPABILITY_ID = 69


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _route(report, proof_kind):
    capability = next(
        item for item in report.capabilities if item.capability_id == CAPABILITY_ID
    )
    return next(item for item in capability.routes if item.proof_kind is proof_kind)


def test_benchmark_checks_real_measurements_and_blocks_simulation_promotion():
    result = run_physical_reality_benchmark()
    assert result["benchmark_passed"] is True
    assert all(result["checks"].values())
    assert result["positive"]["all_constraints_verified"] is True
    negative = result["negative_control"]["audits"][0]
    assert negative["calculation_passed"] is True
    assert negative["evidence_sufficient"] is False
    assert negative["verified_constraint"] is False
    assert "real_measurement_missing" in negative["blockers"]
    assert result["hardware_authenticity_proven"] is False
    assert result["physical_truth_proven"] is False
    assert len(result["benchmark_sha256"]) == 64


def test_attestor_mints_only_execution_and_reproducibility(tmp_path):
    ledger_path = tmp_path / "physical-reality-proof.jsonl"
    result = attest_physical_reality_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="ci-physical-reality-1",
        now=NOW,
    )
    assert result.receipts_added == 2
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.hardware_authenticity_proven is False
    assert result.physical_truth_proven is False

    capability = result.audit.maturity_report.results[CAPABILITY_ID - 1]
    assert ProofKind.EXECUTION not in capability.missing_proofs
    assert ProofKind.REPRODUCIBILITY not in capability.missing_proofs
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
    assert all(row["proof_kind"] != ProofKind.HARDWARE.value for row in rows)
    assert all(row["proof_kind"] != ProofKind.SAFETY.value for row in rows)


def test_specialized_readiness_routes_are_repo_backed_but_external():
    report = audit_attestation_readiness(_root())
    execution = _route(report, ProofKind.EXECUTION)
    reproducibility = _route(report, ProofKind.REPRODUCIBILITY)
    assert execution.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
    assert execution.attestor_id == "physical-reality-execution"
    assert execution.external_required is True
    assert execution.verifiers == ("trusted-execution-attestor",)
    assert execution.subjects == ("capability-69-execution-run",)
    assert reproducibility.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
    assert reproducibility.attestor_id == "physical-reality-reproducibility"
    assert reproducibility.external_required is True
    assert reproducibility.verifiers == ("trusted-reproducibility-attestor",)
    assert reproducibility.subjects == ("capability-69-reproducibility-run",)


def test_existing_ledger_requires_anchor_and_same_run_is_idempotent(tmp_path):
    ledger_path = tmp_path / "physical-reality-proof.jsonl"
    first = attest_physical_reality_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="ci-physical-reality-2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_physical_reality_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="ci-physical-reality-2",
            now=NOW + 1,
        )
    second = attest_physical_reality_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="ci-physical-reality-2",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 2


def test_failed_benchmark_cannot_mint_receipts(monkeypatch, tmp_path):
    original = attestor_mod.run_physical_reality_benchmark

    def failed():
        payload = dict(original())
        payload["benchmark_passed"] = False
        return payload

    monkeypatch.setattr(attestor_mod, "run_physical_reality_benchmark", failed)
    ledger_path = tmp_path / "physical-reality-proof.jsonl"
    with pytest.raises(ValueError, match="benchmark failed"):
        attest_physical_reality_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="failed",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_nondeterministic_benchmark_cannot_mint_reproducibility(monkeypatch, tmp_path):
    original = attestor_mod.run_physical_reality_benchmark
    counter = {"n": 0}

    def changing():
        payload = dict(original())
        counter["n"] += 1
        payload["nonce"] = counter["n"]
        return payload

    monkeypatch.setattr(attestor_mod, "run_physical_reality_benchmark", changing)
    ledger_path = tmp_path / "physical-reality-proof.jsonl"
    with pytest.raises(ValueError, match="not deterministic"):
        attest_physical_reality_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="nondeterministic",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_software_benchmark_cannot_claim_physical_truth(monkeypatch, tmp_path):
    original = attestor_mod.run_physical_reality_benchmark

    def dishonest():
        payload = dict(original())
        payload["physical_truth_proven"] = True
        return payload

    monkeypatch.setattr(attestor_mod, "run_physical_reality_benchmark", dishonest)
    ledger_path = tmp_path / "physical-reality-proof.jsonl"
    with pytest.raises(ValueError, match="must not claim physical truth"):
        attest_physical_reality_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="dishonest",
            now=NOW,
        )
    assert not ledger_path.exists()
