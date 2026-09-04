from pathlib import Path

import pytest

import research_engine.adversarial_science_attestor as attestor_mod
from research_engine.adversarial_science_attestor import (
    attest_adversarial_science_execution,
    run_adversarial_science_benchmark,
)
from research_engine.capability_registry import ProofKind
from research_engine.maturity_attestation_readiness import audit_attestation_readiness
from research_engine.maturity_proof import ProofLedger


KEY = b"A" * 32
NOW = 110_000.0
CAPABILITY_IDS = (36, 38)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _route(report, capability_id, proof_kind):
    capability = next(
        item for item in report.capabilities if item.capability_id == capability_id
    )
    return next(item for item in capability.routes if item.proof_kind is proof_kind)


def test_benchmark_executes_budgeted_red_team_without_truth_upgrade():
    result = run_adversarial_science_benchmark()
    assert result["benchmark_passed"] is True
    assert all(result["checks"].values())
    assert result["plan"]["status"] == "READY"
    assert result["coverage"]["target_coverage"] == 1.0
    assert result["coverage"]["champion_reserve_met"] is True
    assert result["execution"]["execution_complete"] is True
    assert "H1" in result["execution"]["falsified_target_ids"]
    assert "H2" in result["execution"]["survived_target_ids"]
    assert result["software_execution_only"] is True
    assert result["external_independence_proven"] is False
    assert result["truth_proven"] is False
    assert result["execution"]["survival_is_truth"] is False
    assert len(result["benchmark_sha256"]) == 64


def test_attestor_mints_only_execution_and_reproducibility(tmp_path):
    ledger_path = tmp_path / "adversarial-science-proof.jsonl"
    result = attest_adversarial_science_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="ci-fixture-1",
        now=NOW,
    )
    assert result.receipts_added == 4
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.external_independence_proven is False
    assert result.truth_proven is False

    red_team = result.audit.maturity_report.results[35]
    assert ProofKind.EXECUTION not in red_team.missing_proofs
    assert ProofKind.REPRODUCIBILITY not in red_team.missing_proofs
    assert ProofKind.INDEPENDENT in red_team.missing_proofs
    assert ProofKind.CODE in red_team.missing_proofs
    assert ProofKind.TEST in red_team.missing_proofs

    falsification = result.audit.maturity_report.results[37]
    assert ProofKind.EXECUTION not in falsification.missing_proofs
    assert ProofKind.REPRODUCIBILITY not in falsification.missing_proofs
    assert ProofKind.CODE in falsification.missing_proofs
    assert ProofKind.TEST in falsification.missing_proofs

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
    ]
    assert len(rows) == 4
    assert {row["capability_id"] for row in rows} == set(CAPABILITY_IDS)
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
    }
    assert all(row["proof_kind"] != ProofKind.INDEPENDENT.value for row in rows)
    assert all(row["proof_kind"] != ProofKind.LIVE.value for row in rows)
    assert all(row["proof_kind"] != ProofKind.HARDWARE.value for row in rows)


def test_specialized_readiness_routes_are_repo_backed_and_independence_stays_external():
    report = audit_attestation_readiness(_root())
    for capability_id in CAPABILITY_IDS:
        execution = _route(report, capability_id, ProofKind.EXECUTION)
        reproducibility = _route(report, capability_id, ProofKind.REPRODUCIBILITY)
        assert execution.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
        assert execution.attestor_id == "adversarial-science-execution"
        assert execution.verifiers == ("trusted-execution-attestor",)
        assert execution.subjects == (f"capability-{capability_id}-execution-run",)
        assert reproducibility.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
        assert reproducibility.attestor_id == "adversarial-science-reproducibility"
        assert reproducibility.verifiers == ("trusted-reproducibility-attestor",)
        assert reproducibility.subjects == (
            f"capability-{capability_id}-reproducibility-run",
        )

    independent = _route(report, 36, ProofKind.INDEPENDENT)
    assert independent.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
    assert independent.attestor_id == "adversarial-independent"
    assert independent.verifiers == ("trusted-independent-validator",)
    assert independent.subjects == ("capability-36-independent-validation",)
    assert independent.external_required is True


def test_existing_ledger_requires_anchor_and_same_run_is_idempotent(tmp_path):
    ledger_path = tmp_path / "adversarial-science-proof.jsonl"
    first = attest_adversarial_science_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="ci-fixture-2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_adversarial_science_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="ci-fixture-2",
            now=NOW + 1,
        )
    second = attest_adversarial_science_execution(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="ci-fixture-2",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 4


def test_invalid_observation_id_and_inside_repo_ledger_fail_closed(tmp_path):
    ledger_path = tmp_path / "adversarial-science-proof.jsonl"
    with pytest.raises(ValueError, match="observation_id"):
        attest_adversarial_science_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="invalid id with spaces",
            now=NOW,
        )
    assert not ledger_path.exists()

    inside = _root() / ".adversarial-science-proof-test.jsonl"
    try:
        with pytest.raises(ValueError, match="outside"):
            attest_adversarial_science_execution(
                repo_root=_root(),
                ledger_path=inside,
                integrity_key=KEY,
                observation_id="inside-repo",
                now=NOW,
            )
    finally:
        inside.unlink(missing_ok=True)


def test_failed_or_nondeterministic_benchmark_cannot_mint_receipts(monkeypatch, tmp_path):
    original = attestor_mod.run_adversarial_science_benchmark

    def failed():
        payload = dict(original())
        payload["benchmark_passed"] = False
        return payload

    monkeypatch.setattr(attestor_mod, "run_adversarial_science_benchmark", failed)
    ledger_path = tmp_path / "failed.jsonl"
    with pytest.raises(ValueError, match="benchmark failed"):
        attest_adversarial_science_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="failed",
            now=NOW,
        )
    assert not ledger_path.exists()

    monkeypatch.setattr(attestor_mod, "run_adversarial_science_benchmark", original)
    counter = {"n": 0}

    def changing():
        payload = dict(original())
        counter["n"] += 1
        payload["nonce"] = counter["n"]
        return payload

    monkeypatch.setattr(attestor_mod, "run_adversarial_science_benchmark", changing)
    ledger_path = tmp_path / "nondeterministic.jsonl"
    with pytest.raises(ValueError, match="not deterministic"):
        attest_adversarial_science_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="nondeterministic",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_software_benchmark_cannot_self_assert_independence_or_truth(monkeypatch, tmp_path):
    original = attestor_mod.run_adversarial_science_benchmark

    def dishonest_independence():
        payload = dict(original())
        payload["external_independence_proven"] = True
        return payload

    monkeypatch.setattr(
        attestor_mod, "run_adversarial_science_benchmark", dishonest_independence
    )
    ledger_path = tmp_path / "dishonest-independent.jsonl"
    with pytest.raises(ValueError, match="must not claim external independence"):
        attest_adversarial_science_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="dishonest-independent",
            now=NOW,
        )
    assert not ledger_path.exists()

    def dishonest_truth():
        payload = dict(original())
        payload["truth_proven"] = True
        return payload

    monkeypatch.setattr(attestor_mod, "run_adversarial_science_benchmark", dishonest_truth)
    ledger_path = tmp_path / "dishonest-truth.jsonl"
    with pytest.raises(ValueError, match="must not claim scientific truth"):
        attest_adversarial_science_execution(
            repo_root=_root(),
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="dishonest-truth",
            now=NOW,
        )
    assert not ledger_path.exists()
