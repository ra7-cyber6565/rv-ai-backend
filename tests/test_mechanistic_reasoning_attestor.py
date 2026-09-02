from pathlib import Path

import pytest

import research_engine.mechanistic_reasoning_attestor as attestor_mod
from research_engine.capability_registry import ProofKind
from research_engine.mechanistic_reasoning_attestor import (
    attest_mechanistic_simulation_execution,
    run_mechanistic_simulation_benchmark,
)
from research_engine.maturity_proof import ProofLedger


KEY = b"M" * 32
NOW = 70_000.0


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_closed_form_benchmark_passes_and_preserves_causal_truth_boundary():
    result = run_mechanistic_simulation_benchmark()
    assert result["benchmark_passed"] is True
    assert all(result["checks"].values())
    assert result["baseline"]["causal_mechanism_proven"] is False
    assert result["baseline"]["real_world_effect_proven"] is False
    assert result["comparison"]["causal_effect_proven"] is False
    assert result["audit"]["empirical_validation_proven"] is False
    assert len(result["benchmark_sha256"]) == 64


def test_trusted_attestor_mints_only_execution_and_reproducibility(tmp_path):
    ledger_path = tmp_path / "mechanistic-proof.jsonl"
    result = attest_mechanistic_simulation_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="mechanistic-simulation:ci-fixture-1",
        now=NOW,
    )
    assert result.receipts_added == 2
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.causal_mechanism_proven is False
    assert result.real_world_effect_proven is False
    assert result.truth_proven is False

    capability = result.audit.maturity_report.results[101]
    assert ProofKind.EXECUTION not in capability.missing_proofs
    assert ProofKind.REPRODUCIBILITY not in capability.missing_proofs
    assert ProofKind.CODE in capability.missing_proofs
    assert ProofKind.TEST in capability.missing_proofs
    assert ProofKind.WIRING in capability.missing_proofs

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [row for row in ledger._events() if row.get("event_type") == "ADD"]  # noqa: SLF001
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
    }
    assert {row["verifier"] for row in rows} == {"trusted-operator"}
    assert {row["subject"] for row in rows} == {"mechanistic-simulation-benchmark"}


def test_existing_ledger_requires_anchor_and_same_run_is_idempotent(tmp_path):
    ledger_path = tmp_path / "mechanistic-proof.jsonl"
    first = attest_mechanistic_simulation_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="mechanistic-simulation:ci-fixture-2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_mechanistic_simulation_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="mechanistic-simulation:ci-fixture-2",
            now=NOW + 1,
        )
    second = attest_mechanistic_simulation_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="mechanistic-simulation:ci-fixture-2",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 2


def test_wrong_reference_prefix_fails_before_ledger_creation(tmp_path):
    ledger_path = tmp_path / "mechanistic-proof.jsonl"
    with pytest.raises(ValueError, match="run_reference is not allowed"):
        attest_mechanistic_simulation_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="self-asserted:fake",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_ledger_inside_repo_is_rejected():
    target = _root() / ".mechanistic-proof-test.jsonl"
    try:
        with pytest.raises(ValueError, match="outside"):
            attest_mechanistic_simulation_execution(
                repo_root=_root(),
                ledger_path=target,
                integrity_key=KEY,
                run_reference="mechanistic-simulation:inside-repo",
                now=NOW,
            )
    finally:
        target.unlink(missing_ok=True)


def test_failed_benchmark_cannot_mint_receipts(monkeypatch, tmp_path):
    original = attestor_mod.run_mechanistic_simulation_benchmark

    def failed():
        payload = dict(original())
        payload["benchmark_passed"] = False
        return payload

    monkeypatch.setattr(attestor_mod, "run_mechanistic_simulation_benchmark", failed)
    ledger_path = tmp_path / "mechanistic-proof.jsonl"
    with pytest.raises(ValueError, match="benchmark failed"):
        attest_mechanistic_simulation_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="mechanistic-simulation:failed",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_nondeterministic_repeated_execution_cannot_mint_reproducibility(monkeypatch, tmp_path):
    original = attestor_mod.run_mechanistic_simulation_benchmark
    counter = {"n": 0}

    def changing():
        payload = dict(original())
        counter["n"] += 1
        payload["nonce"] = counter["n"]
        return payload

    monkeypatch.setattr(attestor_mod, "run_mechanistic_simulation_benchmark", changing)
    ledger_path = tmp_path / "mechanistic-proof.jsonl"
    with pytest.raises(ValueError, match="not deterministic"):
        attest_mechanistic_simulation_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="mechanistic-simulation:nondeterministic",
            now=NOW,
        )
    assert not ledger_path.exists()
