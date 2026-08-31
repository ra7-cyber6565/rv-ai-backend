from pathlib import Path

import pytest

import research_engine.hypothesis_evolution_attestor as attestor_mod
from research_engine.capability_registry import ProofKind
from research_engine.hypothesis_evolution_attestor import (
    attest_hypothesis_evolution_execution,
    run_hypothesis_evolution_benchmark,
)
from research_engine.maturity_attestation_readiness import audit_attestation_readiness
from research_engine.maturity_proof import ProofLedger


KEY = b"E" * 32
NOW = 95_000.0
CAPABILITY_IDS = (20, 66)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _route(report, capability_id, proof_kind):
    capability = next(item for item in report.capabilities if item.capability_id == capability_id)
    return next(item for item in capability.routes if item.proof_kind is proof_kind)


def test_locked_evolution_benchmark_exercises_lineage_diversity_and_budgets():
    result = run_hypothesis_evolution_benchmark()
    assert result["benchmark_passed"] is True
    assert all(result["checks"].values())
    assert len(result["generations"]) == 2
    assert all(len(row["population_hash"]) == 64 for row in result["generations"])
    assert any(
        "near_duplicate_of:" in item["reason"]
        for generation in result["generations"]
        for item in generation["eliminated"]
    )
    assert result["global_novelty_proven"] is False
    assert result["scientific_truth_proven"] is False
    assert result["real_world_experiment_executed"] is False
    assert len(result["benchmark_sha256"]) == 64


def test_benchmark_is_byte_deterministic():
    first = run_hypothesis_evolution_benchmark()
    second = run_hypothesis_evolution_benchmark()
    assert attestor_mod._canonical(first) == attestor_mod._canonical(second)  # noqa: SLF001
    assert first["benchmark_sha256"] == second["benchmark_sha256"]


def test_trusted_attestor_mints_only_execution_and_reproducibility(tmp_path):
    ledger_path = tmp_path / "hypothesis-evolution-proof.jsonl"
    result = attest_hypothesis_evolution_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="hypothesis-evolution:ci-fixture-1",
        now=NOW,
    )
    assert result.receipts_added == 4
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.global_novelty_proven is False
    assert result.scientific_truth_proven is False
    assert result.real_world_experiment_executed is False

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [row for row in ledger._events() if row.get("event_type") == "ADD"]  # noqa: SLF001
    assert len(rows) == 4
    assert {row["capability_id"] for row in rows} == set(CAPABILITY_IDS)
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
    }
    assert {row["verifier"] for row in rows} == {"trusted-operator"}
    assert {row["subject"] for row in rows} == {"hypothesis-evolution-benchmark"}


def test_specialized_readiness_routes_are_repo_backed_but_external():
    report = audit_attestation_readiness(_root())
    for capability_id in CAPABILITY_IDS:
        for kind in (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY):
            route = _route(report, capability_id, kind)
            assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
            assert route.attestor_id == "hypothesis-evolution-benchmark"
            assert route.external_required is True
            assert route.verifiers == ("trusted-operator",)
            assert route.subjects == ("hypothesis-evolution-benchmark",)


def test_existing_ledger_requires_anchor_and_same_run_is_idempotent(tmp_path):
    ledger_path = tmp_path / "hypothesis-evolution-proof.jsonl"
    first = attest_hypothesis_evolution_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="hypothesis-evolution:ci-fixture-2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_hypothesis_evolution_execution(
            repo_root=_root(), ledger_path=ledger_path, integrity_key=KEY,
            run_reference="hypothesis-evolution:ci-fixture-2", now=NOW + 1,
        )
    second = attest_hypothesis_evolution_execution(
        repo_root=_root(), ledger_path=ledger_path, integrity_key=KEY,
        run_reference="hypothesis-evolution:ci-fixture-2", now=NOW + 1,
        prior_anchor_token=first.anchor_token, prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 4


def test_wrong_reference_prefix_fails_before_ledger_creation(tmp_path):
    ledger_path = tmp_path / "hypothesis-evolution-proof.jsonl"
    with pytest.raises(ValueError, match="run_reference is not allowed"):
        attest_hypothesis_evolution_execution(
            repo_root=_root(), ledger_path=ledger_path, integrity_key=KEY,
            run_reference="self-asserted:fake", now=NOW,
        )
    assert not ledger_path.exists()


def test_ledger_inside_repo_is_rejected():
    target = _root() / ".hypothesis-evolution-proof-test.jsonl"
    try:
        with pytest.raises(ValueError, match="outside"):
            attest_hypothesis_evolution_execution(
                repo_root=_root(), ledger_path=target, integrity_key=KEY,
                run_reference="hypothesis-evolution:inside-repo", now=NOW,
            )
    finally:
        target.unlink(missing_ok=True)


def test_failed_benchmark_cannot_mint_receipts(monkeypatch, tmp_path):
    original = attestor_mod.run_hypothesis_evolution_benchmark

    def failed():
        payload = dict(original())
        payload["benchmark_passed"] = False
        return payload

    monkeypatch.setattr(attestor_mod, "run_hypothesis_evolution_benchmark", failed)
    ledger_path = tmp_path / "hypothesis-evolution-proof.jsonl"
    with pytest.raises(ValueError, match="benchmark failed"):
        attest_hypothesis_evolution_execution(
            repo_root=_root(), ledger_path=ledger_path, integrity_key=KEY,
            run_reference="hypothesis-evolution:failed", now=NOW,
        )
    assert not ledger_path.exists()


def test_nondeterministic_repeated_execution_cannot_mint_reproducibility(monkeypatch, tmp_path):
    original = attestor_mod.run_hypothesis_evolution_benchmark
    counter = {"n": 0}

    def changing():
        payload = dict(original())
        counter["n"] += 1
        payload["nonce"] = counter["n"]
        return payload

    monkeypatch.setattr(attestor_mod, "run_hypothesis_evolution_benchmark", changing)
    ledger_path = tmp_path / "hypothesis-evolution-proof.jsonl"
    with pytest.raises(ValueError, match="not deterministic"):
        attest_hypothesis_evolution_execution(
            repo_root=_root(), ledger_path=ledger_path, integrity_key=KEY,
            run_reference="hypothesis-evolution:nondeterministic", now=NOW,
        )
    assert not ledger_path.exists()
