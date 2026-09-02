from pathlib import Path

import pytest

import research_engine.scientist_society_execution_attestor as attestor_mod
from research_engine.capability_registry import ProofKind
from research_engine.maturity_attestation_readiness import audit_attestation_readiness
from research_engine.maturity_proof import ProofLedger
from research_engine.scientist_society_execution_attestor import (
    attest_scientist_society_execution,
    run_scientist_society_benchmark,
)


KEY = b"S" * 32
NOW = 90_000.0
CAPABILITY_IDS = (19, 37, 39)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _route(report, capability_id, proof_kind):
    capability = next(
        item for item in report.capabilities if item.capability_id == capability_id
    )
    return next(item for item in capability.routes if item.proof_kind is proof_kind)


def test_benchmark_exercises_debate_devil_advocate_and_replication():
    result = run_scientist_society_benchmark()
    assert result["benchmark_passed"] is True
    assert all(result["checks"].values())
    assert result["society"]["successful_agents"] == 3
    assert result["society"]["distinct_runner_ids"] == 3
    assert result["society"]["distinct_model_families"] == 3
    assert result["society"]["distinct_perspectives"] == 3
    assert result["tournament"]["status"] == "WINNER_SELECTED"
    assert result["tournament"]["winner_id"] == "H1"
    assert result["replication"]["independently_replicated"] is True
    assert result["software_execution_only"] is True
    assert result["external_independence_proven"] is False
    assert result["truth_proven"] is False
    assert len(result["benchmark_sha256"]) == 64


def test_attestor_mints_only_execution_and_reproducibility(tmp_path):
    ledger_path = tmp_path / "scientist-society-proof.jsonl"
    result = attest_scientist_society_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="ci-fixture-1",
        now=NOW,
    )
    assert result.receipts_added == 6
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.external_independence_proven is False
    assert result.truth_proven is False

    for capability_id in CAPABILITY_IDS:
        capability = result.audit.maturity_report.results[capability_id - 1]
        assert ProofKind.EXECUTION not in capability.missing_proofs
        assert ProofKind.REPRODUCIBILITY not in capability.missing_proofs
        assert ProofKind.INDEPENDENT in capability.missing_proofs
        assert ProofKind.CODE in capability.missing_proofs
        assert ProofKind.TEST in capability.missing_proofs

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
    assert {row["verifier"] for row in rows} == {
        "trusted-execution-attestor",
        "trusted-reproducibility-attestor",
    }
    assert all(row["proof_kind"] != ProofKind.INDEPENDENT.value for row in rows)
    assert all(row["proof_kind"] != ProofKind.LIVE.value for row in rows)
    assert all(row["proof_kind"] != ProofKind.HARDWARE.value for row in rows)


def test_specialized_readiness_routes_are_repo_backed_but_external():
    report = audit_attestation_readiness(_root())
    for capability_id in CAPABILITY_IDS:
        execution = _route(report, capability_id, ProofKind.EXECUTION)
        reproducibility = _route(report, capability_id, ProofKind.REPRODUCIBILITY)
        assert execution.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
        assert execution.attestor_id == "scientist-society-execution"
        assert execution.external_required is True
        assert execution.verifiers == ("trusted-execution-attestor",)
        assert execution.subjects == (f"capability-{capability_id}-execution-run",)
        assert reproducibility.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
        assert reproducibility.attestor_id == "scientist-society-reproducibility"
        assert reproducibility.external_required is True
        assert reproducibility.verifiers == ("trusted-reproducibility-attestor",)
        assert reproducibility.subjects == (
            f"capability-{capability_id}-reproducibility-run",
        )


def test_existing_ledger_requires_anchor_and_same_run_is_idempotent(tmp_path):
    ledger_path = tmp_path / "scientist-society-proof.jsonl"
    first = attest_scientist_society_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="ci-fixture-2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_scientist_society_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="ci-fixture-2",
            now=NOW + 1,
        )
    second = attest_scientist_society_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="ci-fixture-2",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 6


def test_invalid_observation_id_fails_before_ledger_creation(tmp_path):
    ledger_path = tmp_path / "scientist-society-proof.jsonl"
    with pytest.raises(ValueError, match="observation_id"):
        attest_scientist_society_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="bad id with spaces",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_ledger_inside_repo_is_rejected():
    target = _root() / ".scientist-society-proof-test.jsonl"
    try:
        with pytest.raises(ValueError, match="outside"):
            attest_scientist_society_execution(
                repo_root=_root(),
                ledger_path=target,
                integrity_key=KEY,
                observation_id="inside-repo",
                now=NOW,
            )
    finally:
        target.unlink(missing_ok=True)


def test_failed_benchmark_cannot_mint_receipts(monkeypatch, tmp_path):
    original = attestor_mod.run_scientist_society_benchmark

    def failed():
        payload = dict(original())
        payload["benchmark_passed"] = False
        return payload

    monkeypatch.setattr(attestor_mod, "run_scientist_society_benchmark", failed)
    ledger_path = tmp_path / "scientist-society-proof.jsonl"
    with pytest.raises(ValueError, match="benchmark failed"):
        attest_scientist_society_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="failed",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_nondeterministic_repeated_execution_cannot_mint_reproducibility(
    monkeypatch, tmp_path
):
    original = attestor_mod.run_scientist_society_benchmark
    counter = {"n": 0}

    def changing():
        payload = dict(original())
        counter["n"] += 1
        payload["nonce"] = counter["n"]
        return payload

    monkeypatch.setattr(attestor_mod, "run_scientist_society_benchmark", changing)
    ledger_path = tmp_path / "scientist-society-proof.jsonl"
    with pytest.raises(ValueError, match="not deterministic"):
        attest_scientist_society_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="nondeterministic",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_software_benchmark_can_never_be_relabelled_as_external_independence(
    monkeypatch, tmp_path
):
    original = attestor_mod.run_scientist_society_benchmark

    def dishonest():
        payload = dict(original())
        payload["external_independence_proven"] = True
        return payload

    monkeypatch.setattr(attestor_mod, "run_scientist_society_benchmark", dishonest)
    ledger_path = tmp_path / "scientist-society-proof.jsonl"
    with pytest.raises(ValueError, match="must not claim external independence"):
        attest_scientist_society_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="dishonest",
            now=NOW,
        )
    assert not ledger_path.exists()
