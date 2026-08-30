from pathlib import Path

import pytest

import research_engine.memory_governance_attestor as attestor_mod
from research_engine.capability_registry import ProofKind
from research_engine.memory_governance_attestor import (
    attest_memory_governance,
    run_memory_governance_benchmark,
)
from research_engine.maturity_proof import ProofLedger


KEY = b"M" * 32
NOW = 60_000.0


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_runtime_benchmark_persists_reloads_and_rejects_tampering(tmp_path):
    result = run_memory_governance_benchmark(tmp_path)
    assert result["benchmark_passed"] is True
    assert all(result["checks"].values())
    assert result["checks"]["tamper_rejected_on_reload"] is True
    assert result["checks"]["decay_only_lowers"] is True
    assert result["checks"]["consolidation_non_destructive"] is True
    assert len(result["benchmark_sha256"]) == 64


def test_trusted_attestor_mints_only_required_memory_proofs(tmp_path):
    storage = tmp_path / "runtime"
    ledger_path = tmp_path / "proofs.jsonl"
    result = attest_memory_governance(
        repo_root=_root(),
        storage_root=storage,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="memory-governance:ci-fixture-1",
        now=NOW,
    )
    assert result.audit.audit_valid is True
    assert result.receipts_added == 5
    assert result.live_proven is False
    assert result.cross_machine_durability_proven is False
    assert result.truth_proven is False

    c49 = result.audit.maturity_report.results[48]
    assert ProofKind.PERSISTENCE not in c49.missing_proofs
    assert ProofKind.RUNTIME not in c49.missing_proofs
    assert ProofKind.CODE in c49.missing_proofs
    assert ProofKind.TEST in c49.missing_proofs
    for capability_id in (53, 55, 56):
        row = result.audit.maturity_report.results[capability_id - 1]
        assert ProofKind.PERSISTENCE not in row.missing_proofs
        assert ProofKind.CODE in row.missing_proofs
        assert ProofKind.TEST in row.missing_proofs

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [row for row in ledger._events() if row.get("event_type") == "ADD"]  # noqa: SLF001
    assert len(rows) == 5
    kinds = {row["proof_kind"] for row in rows}
    assert kinds == {ProofKind.PERSISTENCE.value, ProofKind.RUNTIME.value}
    assert ProofKind.LIVE.value not in kinds
    assert ProofKind.EXECUTION.value not in kinds
    assert ProofKind.HARDWARE.value not in kinds
    assert {row["verifier"] for row in rows} == {"trusted-operator"}


def test_existing_ledger_requires_prior_anchor_and_is_idempotent(tmp_path):
    storage = tmp_path / "runtime"
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_memory_governance(
        repo_root=_root(),
        storage_root=storage,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="memory-governance:ci-fixture-2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_memory_governance(
            repo_root=_root(),
            storage_root=storage,
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="memory-governance:ci-fixture-2",
            now=NOW + 1,
        )
    second = attest_memory_governance(
        repo_root=_root(),
        storage_root=storage,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="memory-governance:ci-fixture-2",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 5


def test_wrong_reference_prefix_fails_before_ledger_creation(tmp_path):
    ledger_path = tmp_path / "proofs.jsonl"
    with pytest.raises(ValueError, match="run_reference"):
        attest_memory_governance(
            repo_root=_root(),
            storage_root=tmp_path / "runtime",
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="self-asserted:fake",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_storage_and_ledger_inside_repo_are_rejected(tmp_path):
    inside_storage = _root() / ".memory-governance-runtime"
    inside_ledger = _root() / ".memory-governance-proof.jsonl"
    try:
        with pytest.raises(ValueError, match="storage_root"):
            attest_memory_governance(
                repo_root=_root(),
                storage_root=inside_storage,
                ledger_path=tmp_path / "outside-ledger.jsonl",
                integrity_key=KEY,
                run_reference="memory-governance:inside-storage",
                now=NOW,
            )
        with pytest.raises(ValueError, match="ledger"):
            attest_memory_governance(
                repo_root=_root(),
                storage_root=tmp_path / "runtime",
                ledger_path=inside_ledger,
                integrity_key=KEY,
                run_reference="memory-governance:inside-ledger",
                now=NOW,
            )
    finally:
        if inside_storage.exists():
            import shutil
            shutil.rmtree(inside_storage, ignore_errors=True)
        inside_ledger.unlink(missing_ok=True)


def test_failed_benchmark_cannot_mint_persistence(monkeypatch, tmp_path):
    original = attestor_mod.run_memory_governance_benchmark

    def failed(storage_root):
        payload = dict(original(storage_root))
        payload["benchmark_passed"] = False
        return payload

    monkeypatch.setattr(attestor_mod, "run_memory_governance_benchmark", failed)
    ledger_path = tmp_path / "proofs.jsonl"
    with pytest.raises(ValueError, match="benchmark failed"):
        attest_memory_governance(
            repo_root=_root(),
            storage_root=tmp_path / "runtime",
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="memory-governance:failed",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_nondeterministic_benchmark_cannot_mint_runtime_proof(monkeypatch, tmp_path):
    original = attestor_mod.run_memory_governance_benchmark
    counter = {"n": 0}

    def changing(storage_root):
        payload = dict(original(storage_root))
        counter["n"] += 1
        payload["nonce"] = counter["n"]
        return payload

    monkeypatch.setattr(attestor_mod, "run_memory_governance_benchmark", changing)
    ledger_path = tmp_path / "proofs.jsonl"
    with pytest.raises(ValueError, match="not deterministic"):
        attest_memory_governance(
            repo_root=_root(),
            storage_root=tmp_path / "runtime",
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="memory-governance:nondeterministic",
            now=NOW,
        )
    assert not ledger_path.exists()
