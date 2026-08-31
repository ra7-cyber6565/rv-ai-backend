from pathlib import Path

import pytest

import research_engine.simulation_execution_attestor as attestor_mod
from research_engine.capability_registry import ProofKind
from research_engine.maturity_attestation_readiness import audit_attestation_readiness
from research_engine.maturity_proof import ProofLedger
from research_engine.simulation_execution_attestor import (
    attest_simulation_execution,
    run_simulation_benchmark,
)


KEY = b"M" * 32
NOW = 120_000.0
CAPABILITY_IDS = (25, 26, 27, 28, 73, 74, 86)
PHYSICAL_IDS = (25, 26, 73, 74)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _route(report, capability_id, proof_kind):
    capability = next(
        item for item in report.capabilities if item.capability_id == capability_id
    )
    return next(item for item in capability.routes if item.proof_kind is proof_kind)


def test_locked_simulation_benchmark_exercises_all_declared_lanes():
    result = run_simulation_benchmark()
    assert result["benchmark_passed"] is True
    assert all(result["checks"].values())
    assert result["software_only"] is True
    assert result["hardware_observed"] is False
    assert result["safety_certified"] is False
    assert result["live_world_observed"] is False
    assert result["sim_to_reality_closed"] is False
    assert result["future_guaranteed"] is False
    assert result["truth_proven"] is False
    assert result["digital_twin"]["calibration"]["sim_to_reality_gap_open"] is True
    assert result["multiphysics"]["result"]["hardware_validated"] is False
    assert result["fault_campaign"]["safety_review_required"] is True
    assert result["black_swan"]["future_guarantee"] is False
    assert len(result["benchmark_sha256"]) == 64


def test_simulation_benchmark_is_byte_deterministic():
    first = run_simulation_benchmark()
    second = run_simulation_benchmark()
    assert attestor_mod._canonical(first) == attestor_mod._canonical(second)  # noqa: SLF001
    assert first["benchmark_sha256"] == second["benchmark_sha256"]


def test_trusted_attestor_mints_only_execution_and_reproducibility(tmp_path):
    ledger_path = tmp_path / "simulation-proof.jsonl"
    result = attest_simulation_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="simulation-lab:ci-fixture-1",
        now=NOW,
    )
    assert result.receipts_added == 14
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.hardware_observed is False
    assert result.safety_certified is False
    assert result.live_world_observed is False
    assert result.sim_to_reality_closed is False
    assert result.truth_proven is False

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
    ]
    assert len(rows) == 14
    assert {row["capability_id"] for row in rows} == set(CAPABILITY_IDS)
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
    }
    assert {row["subject"] for row in rows} == {"simulation-lab-benchmark"}
    assert {row["verifier"] for row in rows} == {"trusted-operator"}
    assert ProofKind.HARDWARE.value not in {row["proof_kind"] for row in rows}
    assert ProofKind.SAFETY.value not in {row["proof_kind"] for row in rows}

    for capability_id in CAPABILITY_IDS:
        capability = result.audit.maturity_report.results[capability_id - 1]
        assert ProofKind.EXECUTION not in capability.missing_proofs
        assert ProofKind.REPRODUCIBILITY not in capability.missing_proofs
        # This attestor cannot borrow Foundation CODE/TEST receipts.
        assert ProofKind.CODE in capability.missing_proofs
        assert ProofKind.TEST in capability.missing_proofs
    for capability_id in PHYSICAL_IDS:
        capability = result.audit.maturity_report.results[capability_id - 1]
        assert ProofKind.HARDWARE in capability.missing_proofs
        assert ProofKind.SAFETY in capability.missing_proofs


def test_specialized_readiness_replaces_generic_simulation_execution_routes():
    report = audit_attestation_readiness(_root())
    for capability_id in CAPABILITY_IDS:
        for kind in (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY):
            route = _route(report, capability_id, kind)
            assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
            assert route.attestor_id == "simulation-lab-benchmark"
            assert route.external_required is True
            assert route.verifiers == ("trusted-operator",)
            assert route.subjects == ("simulation-lab-benchmark",)


def test_existing_ledger_requires_prior_anchor_and_same_run_is_idempotent(tmp_path):
    ledger_path = tmp_path / "simulation-proof.jsonl"
    first = attest_simulation_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="simulation-lab:ci-fixture-2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_simulation_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="simulation-lab:ci-fixture-2",
            now=NOW + 1,
        )
    second = attest_simulation_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="simulation-lab:ci-fixture-2",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 14


def test_wrong_reference_prefix_fails_before_ledger_creation(tmp_path):
    ledger_path = tmp_path / "simulation-proof.jsonl"
    with pytest.raises(ValueError, match="run_reference is not allowed"):
        attest_simulation_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="self-asserted:fake",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_ledger_inside_repo_is_rejected():
    target = _root() / ".simulation-proof-test.jsonl"
    try:
        with pytest.raises(ValueError, match="outside"):
            attest_simulation_execution(
                repo_root=_root(),
                ledger_path=target,
                integrity_key=KEY,
                run_reference="simulation-lab:inside-repo",
                now=NOW,
            )
    finally:
        target.unlink(missing_ok=True)


def test_failed_benchmark_cannot_mint_receipts(monkeypatch, tmp_path):
    original = attestor_mod.run_simulation_benchmark

    def failed():
        payload = dict(original())
        payload["benchmark_passed"] = False
        return payload

    monkeypatch.setattr(attestor_mod, "run_simulation_benchmark", failed)
    ledger_path = tmp_path / "simulation-proof.jsonl"
    with pytest.raises(ValueError, match="benchmark failed"):
        attest_simulation_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="simulation-lab:failed",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_nondeterministic_repeat_cannot_mint_reproducibility(monkeypatch, tmp_path):
    original = attestor_mod.run_simulation_benchmark
    counter = {"n": 0}

    def changing():
        payload = dict(original())
        counter["n"] += 1
        payload["nonce"] = counter["n"]
        return payload

    monkeypatch.setattr(attestor_mod, "run_simulation_benchmark", changing)
    ledger_path = tmp_path / "simulation-proof.jsonl"
    with pytest.raises(ValueError, match="not deterministic"):
        attest_simulation_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="simulation-lab:nondeterministic",
            now=NOW,
        )
    assert not ledger_path.exists()
