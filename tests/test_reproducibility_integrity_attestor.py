from pathlib import Path

import pytest

import research_engine.reproducibility_integrity_attestor as attestor_mod
from research_engine.capability_registry import ProofKind
from research_engine.maturity_attestation_readiness import audit_attestation_readiness
from research_engine.maturity_proof import ProofLedger
from research_engine.reproducibility_integrity_attestor import (
    attest_reproducibility_integrity,
    run_reproducibility_integrity_benchmark,
)


KEY = b"I" * 32
NOW = 140_000.0
CAPABILITY_IDS = (24, 79, 80)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _route(report, capability_id, proof_kind):
    capability = next(
        item for item in report.capabilities if item.capability_id == capability_id
    )
    return next(item for item in capability.routes if item.proof_kind is proof_kind)


def test_locked_integrity_benchmark_exercises_capsule_and_crypto_boundaries():
    result = run_reproducibility_integrity_benchmark()
    assert result["benchmark_passed"] is True
    assert all(result["checks"].values())
    assert result["capsule"]["artifact_count"] == 3
    assert len(result["capsule"]["capsule_id"]) == 64
    assert len(result["capsule"]["capsule_sha256"]) == 64
    assert any("hash mismatch" in item for item in result["capsule"]["tamper_errors"])
    assert result["cryptographic_integrity"]["intact_chain_verified"] is True
    assert result["cryptographic_integrity"]["wrong_key_rejected"] is True
    assert result["cryptographic_integrity"]["wrong_revision_rejected"] is True
    assert result["cryptographic_integrity"]["valid_prefix_still_internally_consistent"] is True
    assert result["cryptographic_integrity"]["retained_anchor_detects_truncation"] is True
    assert result["persistent_archive_retention_observed"] is False
    assert result["protected_key_custody_observed"] is False
    assert result["external_anchor_retention_service_observed"] is False
    assert result["safety_certified"] is False
    assert result["truth_proven"] is False


def test_integrity_benchmark_is_byte_deterministic():
    first = run_reproducibility_integrity_benchmark()
    second = run_reproducibility_integrity_benchmark()
    assert attestor_mod._canonical(first) == attestor_mod._canonical(second)  # noqa: SLF001
    assert first["benchmark_sha256"] == second["benchmark_sha256"]


def test_attestor_mints_only_execution_and_reproducibility(tmp_path):
    ledger_path = tmp_path / "integrity-proof.jsonl"
    result = attest_reproducibility_integrity(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="reproducibility-integrity:ci-fixture-1",
        now=NOW,
    )
    assert result.receipts_added == 6
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.persistent_archive_retention_observed is False
    assert result.protected_key_custody_observed is False
    assert result.external_anchor_retention_service_observed is False
    assert result.safety_certified is False
    assert result.truth_proven is False

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
    ]
    assert len(rows) == 6
    assert {row["capability_id"] for row in rows} == set(CAPABILITY_IDS)
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
    }
    assert {row["subject"] for row in rows} == {
        "reproducibility-integrity-benchmark"
    }
    assert {row["verifier"] for row in rows} == {"trusted-operator"}

    c24 = result.audit.maturity_report.results[23]
    assert ProofKind.EXECUTION not in c24.missing_proofs
    assert ProofKind.REPRODUCIBILITY not in c24.missing_proofs
    assert ProofKind.CODE in c24.missing_proofs
    assert ProofKind.TEST in c24.missing_proofs

    c79 = result.audit.maturity_report.results[78]
    assert ProofKind.EXECUTION not in c79.missing_proofs
    assert ProofKind.REPRODUCIBILITY not in c79.missing_proofs
    assert ProofKind.PERSISTENCE in c79.missing_proofs
    assert ProofKind.SAFETY in c79.missing_proofs

    c80 = result.audit.maturity_report.results[79]
    assert ProofKind.EXECUTION not in c80.missing_proofs
    assert ProofKind.REPRODUCIBILITY not in c80.missing_proofs
    assert ProofKind.PERSISTENCE in c80.missing_proofs


def test_specialized_readiness_replaces_only_integrity_exec_repro_routes():
    report = audit_attestation_readiness(_root())
    for capability_id in CAPABILITY_IDS:
        for kind in (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY):
            route = _route(report, capability_id, kind)
            assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
            assert route.attestor_id == "reproducibility-integrity-benchmark"
            assert route.external_required is True
            assert route.verifiers == ("trusted-operator",)
            assert route.subjects == ("reproducibility-integrity-benchmark",)

    assert _route(report, 79, ProofKind.PERSISTENCE).attestor_id == ""
    assert _route(report, 79, ProofKind.SAFETY).attestor_id == ""
    assert _route(report, 80, ProofKind.PERSISTENCE).attestor_id == ""


def test_existing_ledger_requires_prior_anchor_and_same_run_is_idempotent(tmp_path):
    ledger_path = tmp_path / "integrity-proof.jsonl"
    first = attest_reproducibility_integrity(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="reproducibility-integrity:ci-fixture-2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_reproducibility_integrity(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="reproducibility-integrity:ci-fixture-2",
            now=NOW + 1,
        )
    second = attest_reproducibility_integrity(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="reproducibility-integrity:ci-fixture-2",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 6


def test_wrong_reference_prefix_fails_before_ledger_creation(tmp_path):
    ledger_path = tmp_path / "integrity-proof.jsonl"
    with pytest.raises(ValueError, match="run_reference is not allowed"):
        attest_reproducibility_integrity(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="self-asserted:fake",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_ledger_inside_repo_is_rejected():
    target = _root() / ".integrity-proof-test.jsonl"
    try:
        with pytest.raises(ValueError, match="outside"):
            attest_reproducibility_integrity(
                repo_root=_root(),
                ledger_path=target,
                integrity_key=KEY,
                run_reference="reproducibility-integrity:inside-repo",
                now=NOW,
            )
    finally:
        target.unlink(missing_ok=True)


def test_failed_benchmark_cannot_mint_receipts(monkeypatch, tmp_path):
    original = attestor_mod.run_reproducibility_integrity_benchmark

    def failed():
        payload = dict(original())
        payload["benchmark_passed"] = False
        return payload

    monkeypatch.setattr(
        attestor_mod, "run_reproducibility_integrity_benchmark", failed
    )
    ledger_path = tmp_path / "integrity-proof.jsonl"
    with pytest.raises(ValueError, match="benchmark failed"):
        attest_reproducibility_integrity(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="reproducibility-integrity:failed",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_nondeterministic_repeat_cannot_mint_reproducibility(monkeypatch, tmp_path):
    original = attestor_mod.run_reproducibility_integrity_benchmark
    counter = {"n": 0}

    def changing():
        payload = dict(original())
        counter["n"] += 1
        payload["nonce"] = counter["n"]
        return payload

    monkeypatch.setattr(
        attestor_mod, "run_reproducibility_integrity_benchmark", changing
    )
    ledger_path = tmp_path / "integrity-proof.jsonl"
    with pytest.raises(ValueError, match="not deterministic"):
        attest_reproducibility_integrity(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="reproducibility-integrity:nondeterministic",
            now=NOW,
        )
    assert not ledger_path.exists()
