import json
from pathlib import Path

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.intellectual_diversity_attestor import (
    attest_intellectual_diversity_proofs,
    build_intellectual_diversity_execution_receipt,
    validate_intellectual_diversity_receipt,
)
from research_engine.maturity_proof import ProofLedger
from research_engine.scientist_society import AgentSpec, ResearchTask


ROOT = Path(__file__).resolve().parents[1]
KEY = b"I" * 32
NOW = 40_000


def _runner(answer, evidence_ids):
    def run(_task):
        return {
            "answer": answer,
            "evidence_ids": list(evidence_ids),
            "confidence": 0.6,
        }
    return run


def _agents(*, same_evidence=False):
    evidence = ("E-common",) if same_evidence else None
    return [
        (
            AgentSpec(
                agent_id="mechanist",
                role="mechanistic_scientist",
                runner_id="runner-a",
                model_family="family-a",
                perspective="mechanistic",
                blind_to_expected_result=False,
            ),
            _runner("mechanistic analysis", evidence or ("E1", "E2")),
        ),
        (
            AgentSpec(
                agent_id="skeptic",
                role="falsification_scientist",
                runner_id="runner-b",
                model_family="family-b",
                perspective="falsification",
                blind_to_expected_result=True,
            ),
            _runner("skeptical analysis", evidence or ("E2", "E3")),
        ),
        (
            AgentSpec(
                agent_id="systems",
                role="systems_scientist",
                runner_id="runner-c",
                model_family="family-c",
                perspective="systems",
                blind_to_expected_result=False,
            ),
            _runner("systems analysis", evidence or ("E4",)),
        ),
    ]


def _domains():
    return {
        "runner-a": "provider-domain-a",
        "runner-b": "provider-domain-b",
        "runner-c": "provider-domain-c",
    }


def _task():
    return ResearchTask(
        question="Which explanation survives independent scrutiny?",
        evidence=({"id": "E1"}, {"id": "E2"}, {"id": "E3"}, {"id": "E4"}),
        hypothesis="H1",
        expected_result=None,
        constraints={"frozen_protocol": "diversity-v1"},
    )


def _write_receipt(tmp_path, value):
    path = tmp_path / "diversity-receipt.json"
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def test_builder_requires_real_structural_diversity_and_never_claims_truth():
    receipt = build_intellectual_diversity_execution_receipt(
        repo_root=ROOT,
        task=_task(),
        agents=_agents(),
        independence_domains=_domains(),
        created_at_epoch=NOW,
        repetitions=2,
    )
    assert receipt["external_independence_structure_satisfied"] is True
    assert receipt["observer_asserted_independence_domains"] is True
    assert receipt["hidden_provider_dependencies_ruled_out"] is False
    assert receipt["agreement_proves_truth"] is False
    assert receipt["truth_proven"] is False
    assert len(receipt["runs"]) == 2
    manifest = receipt["agent_manifest"]
    assert len({row["runner_id"] for row in manifest}) == 3
    assert len({row["model_family"] for row in manifest}) == 3
    assert len({row["perspective"] for row in manifest}) == 3
    assert len({row["independence_domain"] for row in manifest}) == 3


def test_builder_rejects_fake_independence_domains():
    domains = _domains()
    domains["runner-c"] = domains["runner-a"]
    with pytest.raises(ValueError, match="distinct independence_domain"):
        build_intellectual_diversity_execution_receipt(
            repo_root=ROOT,
            task=_task(),
            agents=_agents(),
            independence_domains=domains,
            created_at_epoch=NOW,
        )


def test_builder_rejects_decorative_roles_with_one_evidence_portfolio():
    with pytest.raises(ValueError, match="two evidence portfolios"):
        build_intellectual_diversity_execution_receipt(
            repo_root=ROOT,
            task=_task(),
            agents=_agents(same_evidence=True),
            independence_domains=_domains(),
            created_at_epoch=NOW,
        )


def test_validator_rejects_tampered_manifest_even_if_json_is_parseable(tmp_path):
    receipt = build_intellectual_diversity_execution_receipt(
        repo_root=ROOT,
        task=_task(),
        agents=_agents(),
        independence_domains=_domains(),
        created_at_epoch=NOW,
    )
    receipt["agent_manifest"][0]["perspective"] = "tampered"
    path = _write_receipt(tmp_path, receipt)
    with pytest.raises(ValueError, match="manifest hash mismatch"):
        validate_intellectual_diversity_receipt(path, repo_root=ROOT, now=NOW + 10)


def test_validator_rejects_stale_external_receipt(tmp_path):
    receipt = build_intellectual_diversity_execution_receipt(
        repo_root=ROOT,
        task=_task(),
        agents=_agents(),
        independence_domains=_domains(),
        created_at_epoch=NOW,
    )
    path = _write_receipt(tmp_path, receipt)
    with pytest.raises(ValueError, match="stale"):
        validate_intellectual_diversity_receipt(path, repo_root=ROOT, now=NOW + 7201)


def test_attestor_mints_only_independent_routes_for_16_and_17(tmp_path):
    receipt = build_intellectual_diversity_execution_receipt(
        repo_root=ROOT,
        task=_task(),
        agents=_agents(),
        independence_domains=_domains(),
        created_at_epoch=NOW,
    )
    path = _write_receipt(tmp_path, receipt)
    ledger_path = tmp_path / "maturity.jsonl"
    result = attest_intellectual_diversity_proofs(
        repo_root=ROOT,
        execution_receipt_path=path,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="external-run-1",
        now=NOW + 20,
    )
    assert result.receipts_added == 2
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    adds = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
    ]
    assert {row["capability_id"] for row in adds} == {16, 17}
    assert {row["proof_kind"] for row in adds} == {ProofKind.INDEPENDENT.value}
    assert {row["subject"] for row in adds} == {"scientist-society-independent-validation"}
    assert {row["verifier"] for row in adds} == {"trusted-independent-validator"}
    forbidden = {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
        ProofKind.LIVE.value,
        ProofKind.HARDWARE.value,
        ProofKind.SAFETY.value,
    }
    assert not ({row["proof_kind"] for row in adds} & forbidden)


def test_attestor_requires_previous_anchor_for_existing_ledger(tmp_path):
    receipt = build_intellectual_diversity_execution_receipt(
        repo_root=ROOT,
        task=_task(),
        agents=_agents(),
        independence_domains=_domains(),
        created_at_epoch=NOW,
    )
    path = _write_receipt(tmp_path, receipt)
    ledger_path = tmp_path / "maturity.jsonl"
    first = attest_intellectual_diversity_proofs(
        repo_root=ROOT,
        execution_receipt_path=path,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="external-run-1",
        now=NOW + 20,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_intellectual_diversity_proofs(
            repo_root=ROOT,
            execution_receipt_path=path,
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="external-run-1",
            now=NOW + 30,
        )
    second = attest_intellectual_diversity_proofs(
        repo_root=ROOT,
        execution_receipt_path=path,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="external-run-1",
        now=NOW + 30,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 2
