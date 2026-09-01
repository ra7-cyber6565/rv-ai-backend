from pathlib import Path

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.maturity_attestation_readiness import audit_attestation_readiness
from research_engine.maturity_proof import ProofLedger
from research_engine.data_forensics_execution_attestor import (
    attest_data_forensics_execution,
    run_data_forensics_benchmark,
)


ROOT = Path(__file__).resolve().parents[1]
KEY = b"D" * 32
NOW = 50_000.0


def _route(report, capability_id, proof_kind):
    capability = next(
        item for item in report.capabilities if item.capability_id == capability_id
    )
    return next(item for item in capability.routes if item.proof_kind is proof_kind)


def test_locked_data_forensics_benchmark_passes_and_is_deterministic():
    first = run_data_forensics_benchmark()
    second = run_data_forensics_benchmark()
    assert first == second
    assert first["benchmark_passed"] is True
    assert len(first["benchmark_sha256"]) == 64
    assert all(first["checks"].values())


def test_benchmark_preserves_anomaly_vs_fraud_boundary():
    result = run_data_forensics_benchmark()
    assert result["locked_structured_tabular_corpus"] is True
    assert result["external_dataset_provenance_verified"] is False
    assert result["malicious_intent_inferred"] is False
    assert result["fraud_proven"] is False
    assert result["truth_proven"] is False
    assert result["reports"]["conflicting_primary_key"]["passed"] is False
    assert result["reports"]["warning_only_outlier"]["passed"] is True
    assert result["reports"]["warning_only_outlier"]["fraud_proven"] is False


def test_readiness_has_specialized_data_forensics_execution_and_repro_routes():
    report = audit_attestation_readiness(ROOT)
    for kind in (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY):
        route = _route(report, 109, kind)
        assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
        assert route.attestor_id == "data-forensics-benchmark"
        assert route.external_required is True
        assert route.verifiers == ("trusted-operator",)
        assert route.subjects == ("data-forensics-benchmark",)


def test_attestor_mints_only_execution_and_repro_for_109(tmp_path):
    ledger_path = tmp_path / "proofs.jsonl"
    result = attest_data_forensics_execution(
        repo_root=ROOT,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="data-forensics:ci:1",
        now=NOW,
    )
    assert result.receipts_added == 2
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.external_dataset_provenance_verified is False
    assert result.malicious_intent_inferred is False
    assert result.fraud_proven is False
    assert result.truth_proven is False

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD" and row.get("capability_id") == 109
    ]
    assert len(rows) == 2
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
    }
    assert {row["subject"] for row in rows} == {"data-forensics-benchmark"}
    assert {row["verifier"] for row in rows} == {"trusted-operator"}


def test_wrong_reference_prefix_fails_before_ledger_mutation(tmp_path):
    ledger_path = tmp_path / "proofs.jsonl"
    with pytest.raises(ValueError, match="run_reference is not allowed"):
        attest_data_forensics_execution(
            repo_root=ROOT,
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="self-asserted:1",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_existing_ledger_requires_anchor_and_reuses_exact_receipts(tmp_path):
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_data_forensics_execution(
        repo_root=ROOT,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="data-forensics:ci:2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_data_forensics_execution(
            repo_root=ROOT,
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="data-forensics:ci:2",
            now=NOW + 1,
        )
    second = attest_data_forensics_execution(
        repo_root=ROOT,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="data-forensics:ci:2",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 2


def test_wrong_prior_anchor_key_fails_closed(tmp_path):
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_data_forensics_execution(
        repo_root=ROOT,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="data-forensics:ci:3",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior anchor continuity"):
        attest_data_forensics_execution(
            repo_root=ROOT,
            ledger_path=ledger_path,
            integrity_key=b"Z" * 32,
            run_reference="data-forensics:ci:3",
            now=NOW + 1,
            prior_anchor_token=first.anchor_token,
            prior_revision=first.revision,
        )


def test_failed_locked_benchmark_mints_nothing(tmp_path, monkeypatch):
    import research_engine.data_forensics_execution_attestor as module

    original = module.run_data_forensics_benchmark
    bad = dict(original())
    bad["benchmark_passed"] = False
    monkeypatch.setattr(module, "run_data_forensics_benchmark", lambda: bad)
    ledger_path = tmp_path / "proofs.jsonl"
    with pytest.raises(ValueError, match="benchmark failed"):
        module.attest_data_forensics_execution(
            repo_root=ROOT,
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="data-forensics:ci:4",
            now=NOW,
        )
    assert not ledger_path.exists()
