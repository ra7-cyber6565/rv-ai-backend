from pathlib import Path

import pytest

import research_engine.manufacturing_reality_attestor as attestor_mod
from research_engine.capability_registry import ProofKind
from research_engine.manufacturing_reality_attestor import (
    attest_manufacturing_reality_execution,
    run_manufacturing_reality_benchmark,
)
from research_engine.maturity_proof import ProofLedger


KEY = b"M" * 32
NOW = 60_000.0


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _attest(tmp_path, *, ledger_name="manufacturing-proof.jsonl", now=NOW, **kwargs):
    return attest_manufacturing_reality_execution(
        repo_root=_root(),
        ledger_path=tmp_path / ledger_name,
        integrity_key=KEY,
        execution_reference="execution:manufacturing-ci",
        reproducibility_reference="reproducibility:manufacturing-ci",
        now=now,
        **kwargs,
    )


def test_closed_form_benchmark_passes_and_keeps_factory_truth_boundary():
    result = run_manufacturing_reality_benchmark()
    assert result["benchmark_passed"] is True
    assert all(result["checks"].values())
    report = result["report"]
    assert report["all_requirements_passed"] is True
    assert report["factory_execution_proven"] is False
    assert report["hardware_authenticity_proven"] is False
    assert report["external_certification_claimed"] is False
    assert report["manufacturability_truth_proven"] is False
    assert len(result["benchmark_sha256"]) == 64


def test_attestor_mints_execution_and_reproducibility_but_not_hardware_or_safety(tmp_path):
    ledger_path = tmp_path / "manufacturing-proof.jsonl"
    result = _attest(tmp_path)
    assert result.receipts_added == 2
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.factory_execution_proven is False
    assert result.hardware_authenticity_proven is False
    assert result.safety_proven is False
    assert result.manufacturability_truth_proven is False

    capability = result.audit.maturity_report.results[70]
    assert ProofKind.EXECUTION not in capability.missing_proofs
    assert ProofKind.REPRODUCIBILITY not in capability.missing_proofs
    assert ProofKind.HARDWARE in capability.missing_proofs
    assert ProofKind.SAFETY in capability.missing_proofs

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [row for row in ledger._events() if row.get("event_type") == "ADD"]  # noqa: SLF001
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
    }
    assert {row["subject"] for row in rows} == {
        "capability-71-execution-run",
        "capability-71-reproducibility-run",
    }
    assert {row["verifier"] for row in rows} == {
        "trusted-execution-attestor",
        "trusted-reproducibility-attestor",
    }
    assert ProofKind.HARDWARE.value not in {row["proof_kind"] for row in rows}
    assert ProofKind.SAFETY.value not in {row["proof_kind"] for row in rows}


def test_existing_ledger_requires_anchor_and_repeat_is_idempotent(tmp_path):
    first = _attest(tmp_path)
    with pytest.raises(ValueError, match="prior trusted anchor"):
        _attest(tmp_path, now=NOW + 1)
    second = _attest(
        tmp_path,
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 2


def test_wrong_execution_reference_fails_before_ledger_creation(tmp_path):
    ledger_path = tmp_path / "manufacturing-proof.jsonl"
    with pytest.raises(ValueError, match="execution reference is not allowed"):
        attest_manufacturing_reality_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            execution_reference="self-asserted:execution",
            reproducibility_reference="reproducibility:manufacturing-ci",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_wrong_reproducibility_reference_fails_before_ledger_creation(tmp_path):
    ledger_path = tmp_path / "manufacturing-proof.jsonl"
    with pytest.raises(ValueError, match="reproducibility reference is not allowed"):
        attest_manufacturing_reality_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            execution_reference="execution:manufacturing-ci",
            reproducibility_reference="self-asserted:repro",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_ledger_inside_repo_is_rejected():
    target = _root() / ".manufacturing-proof-test.jsonl"
    try:
        with pytest.raises(ValueError, match="outside"):
            attest_manufacturing_reality_execution(
                repo_root=_root(),
                ledger_path=target,
                integrity_key=KEY,
                execution_reference="execution:manufacturing-ci",
                reproducibility_reference="reproducibility:manufacturing-ci",
                now=NOW,
            )
    finally:
        target.unlink(missing_ok=True)


def test_failed_benchmark_cannot_mint_receipts(monkeypatch, tmp_path):
    original = attestor_mod.run_manufacturing_reality_benchmark

    def failed():
        payload = dict(original())
        payload["benchmark_passed"] = False
        return payload

    monkeypatch.setattr(attestor_mod, "run_manufacturing_reality_benchmark", failed)
    ledger_path = tmp_path / "manufacturing-proof.jsonl"
    with pytest.raises(ValueError, match="benchmark failed"):
        _attest(tmp_path)
    assert not ledger_path.exists()


def test_nondeterministic_benchmark_cannot_mint_reproducibility(monkeypatch, tmp_path):
    original = attestor_mod.run_manufacturing_reality_benchmark
    counter = {"n": 0}

    def changing():
        payload = dict(original())
        counter["n"] += 1
        payload["nonce"] = counter["n"]
        return payload

    monkeypatch.setattr(attestor_mod, "run_manufacturing_reality_benchmark", changing)
    ledger_path = tmp_path / "manufacturing-proof.jsonl"
    with pytest.raises(ValueError, match="not deterministic"):
        _attest(tmp_path)
    assert not ledger_path.exists()
