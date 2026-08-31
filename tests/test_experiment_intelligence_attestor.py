from pathlib import Path

import pytest

import research_engine.experiment_intelligence_attestor as attestor_mod
from research_engine.capability_registry import ProofKind
from research_engine.experiment_intelligence_attestor import (
    attest_experiment_intelligence_execution,
    run_experiment_intelligence_benchmark,
)
from research_engine.maturity_attestation_readiness import audit_attestation_readiness
from research_engine.maturity_proof import ProofLedger


KEY = b"I" * 32
NOW = 70_000.0
CAPABILITY_IDS = (22, 122, 123, 124)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _route(report, capability_id, proof_kind):
    capability = next(
        item for item in report.capabilities if item.capability_id == capability_id
    )
    return next(item for item in capability.routes if item.proof_kind is proof_kind)


def test_analytic_benchmark_passes_all_four_planning_contracts():
    result = run_experiment_intelligence_benchmark()
    assert result["benchmark_passed"] is True
    assert all(result["checks"].values())
    assert result["discriminating"]["experiment_id"] == "diagnostic"
    assert result["minimum_cost"]["experiment_id"] == "medium"
    assert result["active_learning"]["experiment_id"] == "medium"
    assert result["posterior_update"]["posterior"]["H1"] == pytest.approx(0.9)
    assert result["posterior_update"]["posterior"]["H2"] == pytest.approx(0.1)
    assert result["physical_experiment_executed"] is False
    assert result["real_world_approval_implied"] is False
    assert result["truth_proven"] is False
    assert len(result["benchmark_sha256"]) == 64


def test_trusted_attestor_mints_only_execution_and_reproducibility(tmp_path):
    ledger_path = tmp_path / "experiment-intelligence-proof.jsonl"
    result = attest_experiment_intelligence_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="experiment-intelligence:ci-fixture-1",
        now=NOW,
    )
    assert result.receipts_added == 8
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.physical_experiment_executed is False
    assert result.real_world_approval_implied is False
    assert result.truth_proven is False

    for capability_id in CAPABILITY_IDS:
        capability = result.audit.maturity_report.results[capability_id - 1]
        assert ProofKind.EXECUTION not in capability.missing_proofs
        assert ProofKind.REPRODUCIBILITY not in capability.missing_proofs
        assert ProofKind.CODE in capability.missing_proofs
        assert ProofKind.TEST in capability.missing_proofs

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
    ]
    assert len(rows) == 8
    assert {row["capability_id"] for row in rows} == set(CAPABILITY_IDS)
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
    }
    assert {row["verifier"] for row in rows} == {"trusted-operator"}
    assert {row["subject"] for row in rows} == {"experiment-intelligence-benchmark"}


def test_specialized_readiness_routes_are_repo_backed_but_external():
    report = audit_attestation_readiness(_root())
    for capability_id in CAPABILITY_IDS:
        for kind in (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY):
            route = _route(report, capability_id, kind)
            assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
            assert route.attestor_id == "experiment-intelligence-benchmark"
            assert route.external_required is True
            assert route.verifiers == ("trusted-operator",)
            assert route.subjects == ("experiment-intelligence-benchmark",)


def test_existing_ledger_requires_anchor_and_same_run_is_idempotent(tmp_path):
    ledger_path = tmp_path / "experiment-intelligence-proof.jsonl"
    first = attest_experiment_intelligence_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="experiment-intelligence:ci-fixture-2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_experiment_intelligence_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="experiment-intelligence:ci-fixture-2",
            now=NOW + 1,
        )
    second = attest_experiment_intelligence_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="experiment-intelligence:ci-fixture-2",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 8


def test_wrong_reference_prefix_fails_before_ledger_creation(tmp_path):
    ledger_path = tmp_path / "experiment-intelligence-proof.jsonl"
    with pytest.raises(ValueError, match="run_reference is not allowed"):
        attest_experiment_intelligence_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="self-asserted:fake",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_ledger_inside_repo_is_rejected():
    target = _root() / ".experiment-intelligence-proof-test.jsonl"
    try:
        with pytest.raises(ValueError, match="outside"):
            attest_experiment_intelligence_execution(
                repo_root=_root(),
                ledger_path=target,
                integrity_key=KEY,
                run_reference="experiment-intelligence:inside-repo",
                now=NOW,
            )
    finally:
        target.unlink(missing_ok=True)


def test_failed_benchmark_cannot_mint_receipts(monkeypatch, tmp_path):
    original = attestor_mod.run_experiment_intelligence_benchmark

    def failed():
        payload = dict(original())
        payload["benchmark_passed"] = False
        return payload

    monkeypatch.setattr(attestor_mod, "run_experiment_intelligence_benchmark", failed)
    ledger_path = tmp_path / "experiment-intelligence-proof.jsonl"
    with pytest.raises(ValueError, match="benchmark failed"):
        attest_experiment_intelligence_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="experiment-intelligence:failed",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_nondeterministic_repeated_execution_cannot_mint_reproducibility(
    monkeypatch, tmp_path
):
    original = attestor_mod.run_experiment_intelligence_benchmark
    counter = {"n": 0}

    def changing():
        payload = dict(original())
        counter["n"] += 1
        payload["nonce"] = counter["n"]
        return payload

    monkeypatch.setattr(attestor_mod, "run_experiment_intelligence_benchmark", changing)
    ledger_path = tmp_path / "experiment-intelligence-proof.jsonl"
    with pytest.raises(ValueError, match="not deterministic"):
        attest_experiment_intelligence_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="experiment-intelligence:nondeterministic",
            now=NOW,
        )
    assert not ledger_path.exists()
