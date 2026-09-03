from pathlib import Path

import pytest

import research_engine.sandbox_execution_attestor as attestor_mod
from research_engine.capability_registry import ProofKind
from research_engine.maturity_attestation_readiness import audit_attestation_readiness
from research_engine.maturity_proof import ProofLedger
from research_engine.sandbox_execution_attestor import (
    attest_sandbox_execution,
    run_sandbox_benchmark,
)


KEY = b"B" * 32
NOW = 130_000.0


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _route(report, capability_id, proof_kind):
    capability = next(
        item for item in report.capabilities if item.capability_id == capability_id
    )
    return next(item for item in capability.routes if item.proof_kind is proof_kind)


def test_locked_sandbox_benchmark_executes_valid_program_and_rejects_attack_corpus():
    result = run_sandbox_benchmark()
    assert result["benchmark_passed"] is True
    assert all(result["checks"].values())
    assert result["valid_result"]["outputs"]["total"] == 2470
    assert result["valid_result"]["stdout"] == "2470\n123.5"
    assert result["valid_result"]["deterministic"] is True
    assert result["valid_result"]["network_allowed"] is False
    assert result["valid_result"]["filesystem_allowed"] is False
    assert result["valid_result"]["subprocess_allowed"] is False
    assert all(value != "ACCEPTED" for value in result["attack_results"].values())
    assert all(value.startswith("LIMIT:") for value in result["budget_results"].values())
    assert result["in_process_ast_interpreter"] is True
    assert result["os_container_isolation_observed"] is False
    assert result["native_code_isolation_observed"] is False
    assert result["safety_certified"] is False
    assert result["truth_proven"] is False
    assert len(result["benchmark_sha256"]) == 64


def test_sandbox_benchmark_is_byte_deterministic():
    first = run_sandbox_benchmark()
    second = run_sandbox_benchmark()
    assert attestor_mod._canonical(first) == attestor_mod._canonical(second)  # noqa: SLF001
    assert first["benchmark_sha256"] == second["benchmark_sha256"]


def test_trusted_attestor_mints_only_execution_and_reproducibility(tmp_path):
    ledger_path = tmp_path / "sandbox-proof.jsonl"
    result = attest_sandbox_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="numeric-sandbox:ci-fixture-1",
        now=NOW,
    )
    assert result.receipts_added == 2
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.os_container_isolation_observed is False
    assert result.native_code_isolation_observed is False
    assert result.safety_certified is False
    assert result.truth_proven is False

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
    ]
    assert len(rows) == 2
    assert {row["capability_id"] for row in rows} == {23}
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
    }
    assert {row["subject"] for row in rows} == {"numeric-sandbox-benchmark"}
    assert {row["verifier"] for row in rows} == {"trusted-operator"}
    assert ProofKind.SAFETY.value not in {row["proof_kind"] for row in rows}

    capability = result.audit.maturity_report.results[22]
    assert ProofKind.EXECUTION not in capability.missing_proofs
    assert ProofKind.REPRODUCIBILITY not in capability.missing_proofs
    assert ProofKind.SAFETY in capability.missing_proofs
    # This specialized attestor must not borrow Foundation CODE/TEST receipts.
    assert ProofKind.CODE in capability.missing_proofs
    assert ProofKind.TEST in capability.missing_proofs


def test_specialized_readiness_replaces_generic_sandbox_execution_routes_only():
    report = audit_attestation_readiness(_root())
    for kind in (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY):
        route = _route(report, 23, kind)
        assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
        assert route.attestor_id == "numeric-sandbox-benchmark"
        assert route.external_required is True
        assert route.verifiers == ("trusted-operator",)
        assert route.subjects == ("numeric-sandbox-benchmark",)

    safety = _route(report, 23, ProofKind.SAFETY)
    assert safety.status == "SAFETY_EXTERNAL_REQUIRED"
    assert safety.attestor_id == ""
    assert safety.external_required is True


def test_existing_ledger_requires_prior_anchor_and_same_run_is_idempotent(tmp_path):
    ledger_path = tmp_path / "sandbox-proof.jsonl"
    first = attest_sandbox_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="numeric-sandbox:ci-fixture-2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_sandbox_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="numeric-sandbox:ci-fixture-2",
            now=NOW + 1,
        )
    second = attest_sandbox_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="numeric-sandbox:ci-fixture-2",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 2


def test_wrong_reference_prefix_fails_before_ledger_creation(tmp_path):
    ledger_path = tmp_path / "sandbox-proof.jsonl"
    with pytest.raises(ValueError, match="run_reference is not allowed"):
        attest_sandbox_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="self-asserted:fake",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_ledger_inside_repo_is_rejected():
    target = _root() / ".sandbox-proof-test.jsonl"
    try:
        with pytest.raises(ValueError, match="outside"):
            attest_sandbox_execution(
                repo_root=_root(),
                ledger_path=target,
                integrity_key=KEY,
                run_reference="numeric-sandbox:inside-repo",
                now=NOW,
            )
    finally:
        target.unlink(missing_ok=True)


def test_failed_benchmark_cannot_mint_receipts(monkeypatch, tmp_path):
    original = attestor_mod.run_sandbox_benchmark

    def failed():
        payload = dict(original())
        payload["benchmark_passed"] = False
        return payload

    monkeypatch.setattr(attestor_mod, "run_sandbox_benchmark", failed)
    ledger_path = tmp_path / "sandbox-proof.jsonl"
    with pytest.raises(ValueError, match="benchmark failed"):
        attest_sandbox_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="numeric-sandbox:failed",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_nondeterministic_repeat_cannot_mint_reproducibility(monkeypatch, tmp_path):
    original = attestor_mod.run_sandbox_benchmark
    counter = {"n": 0}

    def changing():
        payload = dict(original())
        counter["n"] += 1
        payload["nonce"] = counter["n"]
        return payload

    monkeypatch.setattr(attestor_mod, "run_sandbox_benchmark", changing)
    ledger_path = tmp_path / "sandbox-proof.jsonl"
    with pytest.raises(ValueError, match="not deterministic"):
        attest_sandbox_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="numeric-sandbox:nondeterministic",
            now=NOW,
        )
    assert not ledger_path.exists()
