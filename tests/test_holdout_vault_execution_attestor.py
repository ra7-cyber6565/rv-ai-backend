from pathlib import Path

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.holdout_vault_execution_attestor import (
    attest_holdout_vault_execution,
    run_holdout_vault_benchmark,
)
from research_engine.maturity_attestation_readiness import audit_attestation_readiness
from research_engine.maturity_proof import ProofLedger


ROOT = Path(__file__).resolve().parents[1]
KEY = b"H" * 32
NOW = 30_000.0


def _route(report, capability_id, proof_kind):
    capability = next(
        item for item in report.capabilities if item.capability_id == capability_id
    )
    return next(item for item in capability.routes if item.proof_kind is proof_kind)


def test_locked_holdout_benchmark_passes_and_is_deterministic():
    first = run_holdout_vault_benchmark()
    second = run_holdout_vault_benchmark()
    assert first == second
    assert first["benchmark_passed"] is True
    assert len(first["benchmark_sha256"]) == 64
    assert all(first["checks"].values())
    assert first["wrong_token_error"] == "PermissionError"
    assert first["refreeze_error"] == "ValueError"
    assert first["token_reuse_error"] == "ValueError"
    assert first["second_eval_error"] == "ValueError"
    assert first["dataset_tamper_error"] == "ValueError"


def test_benchmark_does_not_overclaim_platform_confidentiality():
    result = run_holdout_vault_benchmark()
    assert result["application_level_boundary"] is True
    assert result["os_process_isolation_observed"] is False
    assert result["kms_backed_secret_observed"] is False
    assert result["filesystem_admin_resistance_observed"] is False
    assert result["truth_proven"] is False


def test_readiness_now_has_specialized_holdout_execution_and_repro_routes():
    report = audit_attestation_readiness(ROOT)
    for kind in (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY):
        route = _route(report, 97, kind)
        assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
        assert route.attestor_id == "holdout-vault-benchmark"
        assert route.external_required is True
        assert route.verifiers == ("trusted-operator",)
        assert route.subjects == ("holdout-vault-benchmark",)


def test_attestor_mints_only_execution_and_reproducibility(tmp_path):
    ledger_path = tmp_path / "proofs.jsonl"
    result = attest_holdout_vault_execution(
        repo_root=ROOT,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="holdout-vault:ci:1",
        now=NOW,
    )
    assert result.receipts_added == 2
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.os_process_isolation_observed is False
    assert result.kms_backed_secret_observed is False
    assert result.filesystem_admin_resistance_observed is False
    assert result.truth_proven is False

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD" and row.get("capability_id") == 97
    ]
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
    }
    assert {row["subject"] for row in rows} == {"holdout-vault-benchmark"}
    assert {row["verifier"] for row in rows} == {"trusted-operator"}


def test_wrong_reference_prefix_fails_before_ledger_mutation(tmp_path):
    ledger_path = tmp_path / "proofs.jsonl"
    with pytest.raises(ValueError, match="run_reference is not allowed"):
        attest_holdout_vault_execution(
            repo_root=ROOT,
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="self-asserted:1",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_existing_ledger_requires_prior_anchor_and_reuses_exact_receipts(tmp_path):
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_holdout_vault_execution(
        repo_root=ROOT,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="holdout-vault:ci:2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_holdout_vault_execution(
            repo_root=ROOT,
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="holdout-vault:ci:2",
            now=NOW + 1,
        )
    second = attest_holdout_vault_execution(
        repo_root=ROOT,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="holdout-vault:ci:2",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 2


def test_wrong_prior_anchor_key_fails_closed(tmp_path):
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_holdout_vault_execution(
        repo_root=ROOT,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="holdout-vault:ci:3",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior anchor continuity"):
        attest_holdout_vault_execution(
            repo_root=ROOT,
            ledger_path=ledger_path,
            integrity_key=b"Z" * 32,
            run_reference="holdout-vault:ci:3",
            now=NOW + 1,
            prior_anchor_token=first.anchor_token,
            prior_revision=first.revision,
        )
