from pathlib import Path

import pytest

import research_engine.statistical_validation_attestor as attestor_mod
from research_engine.capability_registry import ProofKind
from research_engine.maturity_attestation_readiness import audit_attestation_readiness
from research_engine.maturity_proof import ProofLedger
from research_engine.statistical_validation_attestor import (
    attest_statistical_validation_execution,
    run_statistical_validation_benchmark,
)


KEY = b"S" * 32
NOW = 90_000.0
CAPABILITY_IDS = (29, 30, 31, 32, 33, 34, 35, 99)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _route(report, capability_id, proof_kind):
    capability = next(
        item for item in report.capabilities if item.capability_id == capability_id
    )
    return next(item for item in capability.routes if item.proof_kind is proof_kind)


def test_locked_statistical_benchmark_executes_all_eight_capabilities():
    result = run_statistical_validation_benchmark()
    assert result["benchmark_passed"] is True
    assert all(result["checks"].values())
    assert result["multiple_testing"]["benjamini_hochberg"]["rejected"] == (
        True, True, False, False
    )
    assert result["multiple_testing"]["holm_bonferroni"]["rejected"] == (
        True, True, False, False
    )
    assert result["placebo"]["p_value"] < 0.05
    assert result["sensitivity"]["best_parameter"] == pytest.approx(3.0)
    assert set(result["ablation"]["critical_components"]) == {
        "core_signal", "risk_filter"
    }
    assert result["overfit"]["suspicious"] is True
    assert result["overfit"]["overfitting_proven"] is False
    assert result["ood"]["psi_same"] == pytest.approx(0.0)
    assert result["ood"]["psi_shifted"] > 0.10
    assert result["real_world_dataset_observed"] is False
    assert result["future_distribution_guaranteed"] is False
    assert result["causality_proven"] is False
    assert result["truth_proven"] is False
    assert len(result["benchmark_sha256"]) == 64


def test_benchmark_is_byte_deterministic_for_fixed_seed_and_fixtures():
    first = run_statistical_validation_benchmark()
    second = run_statistical_validation_benchmark()
    assert attestor_mod._canonical(first) == attestor_mod._canonical(second)  # noqa: SLF001
    assert first["benchmark_sha256"] == second["benchmark_sha256"]


def test_trusted_attestor_mints_only_execution_and_reproducibility(tmp_path):
    ledger_path = tmp_path / "statistical-validation-proof.jsonl"
    result = attest_statistical_validation_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="statistical-validation:ci-fixture-1",
        now=NOW,
    )
    assert result.receipts_added == 16
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.real_world_dataset_observed is False
    assert result.future_distribution_guaranteed is False
    assert result.causality_proven is False
    assert result.truth_proven is False

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
    ]
    assert len(rows) == 16
    assert {row["capability_id"] for row in rows} == set(CAPABILITY_IDS)
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
    }
    assert {row["verifier"] for row in rows} == {"trusted-operator"}
    assert {row["subject"] for row in rows} == {"statistical-validation-benchmark"}

    for capability_id in CAPABILITY_IDS:
        capability = result.audit.maturity_report.results[capability_id - 1]
        assert ProofKind.EXECUTION not in capability.missing_proofs
        assert ProofKind.REPRODUCIBILITY not in capability.missing_proofs
        # This attestor deliberately does not mint Foundation CODE/TEST receipts.
        assert ProofKind.CODE in capability.missing_proofs
        assert ProofKind.TEST in capability.missing_proofs


def test_specialized_readiness_replaces_generic_execution_routes():
    report = audit_attestation_readiness(_root())
    for capability_id in CAPABILITY_IDS:
        for kind in (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY):
            route = _route(report, capability_id, kind)
            assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
            assert route.attestor_id == "statistical-validation-benchmark"
            assert route.external_required is True
            assert route.verifiers == ("trusted-operator",)
            assert route.subjects == ("statistical-validation-benchmark",)


def test_existing_ledger_requires_prior_anchor_and_same_run_is_idempotent(tmp_path):
    ledger_path = tmp_path / "statistical-validation-proof.jsonl"
    first = attest_statistical_validation_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="statistical-validation:ci-fixture-2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_statistical_validation_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="statistical-validation:ci-fixture-2",
            now=NOW + 1,
        )
    second = attest_statistical_validation_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="statistical-validation:ci-fixture-2",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 16


def test_wrong_reference_prefix_fails_before_ledger_creation(tmp_path):
    ledger_path = tmp_path / "statistical-validation-proof.jsonl"
    with pytest.raises(ValueError, match="run_reference is not allowed"):
        attest_statistical_validation_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="self-asserted:fake",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_ledger_inside_repo_is_rejected():
    target = _root() / ".statistical-validation-proof-test.jsonl"
    try:
        with pytest.raises(ValueError, match="outside"):
            attest_statistical_validation_execution(
                repo_root=_root(),
                ledger_path=target,
                integrity_key=KEY,
                run_reference="statistical-validation:inside-repo",
                now=NOW,
            )
    finally:
        target.unlink(missing_ok=True)


def test_failed_benchmark_cannot_mint_receipts(monkeypatch, tmp_path):
    original = attestor_mod.run_statistical_validation_benchmark

    def failed():
        payload = dict(original())
        payload["benchmark_passed"] = False
        return payload

    monkeypatch.setattr(attestor_mod, "run_statistical_validation_benchmark", failed)
    ledger_path = tmp_path / "statistical-validation-proof.jsonl"
    with pytest.raises(ValueError, match="benchmark failed"):
        attest_statistical_validation_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="statistical-validation:failed",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_nondeterministic_repeated_execution_cannot_mint_reproducibility(
    monkeypatch, tmp_path
):
    original = attestor_mod.run_statistical_validation_benchmark
    counter = {"n": 0}

    def changing():
        payload = dict(original())
        counter["n"] += 1
        payload["nonce"] = counter["n"]
        return payload

    monkeypatch.setattr(attestor_mod, "run_statistical_validation_benchmark", changing)
    ledger_path = tmp_path / "statistical-validation-proof.jsonl"
    with pytest.raises(ValueError, match="not deterministic"):
        attest_statistical_validation_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="statistical-validation:nondeterministic",
            now=NOW,
        )
    assert not ledger_path.exists()
