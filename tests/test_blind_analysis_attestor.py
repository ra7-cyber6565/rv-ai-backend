import copy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from research_engine.blind_analysis_attestor import (
    attest_blind_analysis_proofs,
    build_blind_analysis_execution_receipt,
    validate_blind_analysis_execution_receipt,
)
from research_engine.capability_registry import ProofKind
from research_engine.maturity_attestation_readiness import audit_attestation_readiness
from research_engine.maturity_proof import ProofLedger
from research_engine.scientist_society import AgentSpec, ResearchTask


ROOT = Path(__file__).resolve().parents[1]
KEY = b"B" * 32
NOW = 20_000
TARGET = "SECRET_EXPECTED_RESULT_7F6F0B"


def _git(*args):
    proc = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _sha(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _task():
    return ResearchTask(
        question="Does blinded evidence support H1?",
        evidence=(
            {"id": "E1", "value": 1.0},
            {"id": "E2", "value": 0.9},
        ),
        hypothesis="H1",
        expected_result=TARGET,
        constraints={"metric": "bounded-score", "threshold": 0.5},
    )


def _runner(label):
    def run(task):
        # This assertion executes inside the dependency-injected runner.  If the
        # society accidentally leaks expected_result, receipt generation fails.
        assert task.expected_result is None
        return {
            "answer": f"{label}: evidence-only conclusion",
            "evidence_ids": ["E1", "E2"],
            "confidence": 0.7,
        }

    return run


def _agents():
    return [
        (
            AgentSpec(
                agent_id="agent-a",
                role="analyst",
                runner_id="runner-a",
                model_family="family-a",
                perspective="mechanistic",
                blind_to_expected_result=True,
            ),
            _runner("A"),
        ),
        (
            AgentSpec(
                agent_id="agent-b",
                role="replicator",
                runner_id="runner-b",
                model_family="family-b",
                perspective="statistical",
                blind_to_expected_result=True,
            ),
            _runner("B"),
        ),
    ]


def _receipt():
    return build_blind_analysis_execution_receipt(
        repo_root=ROOT,
        task=_task(),
        agents=_agents(),
        created_at_epoch=NOW - 10,
        repetitions=2,
    )


def _write(tmp_path, value, name="blind.json"):
    path = tmp_path / name
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return path


def _rehash(value):
    result = copy.deepcopy(value)
    for run in result["runs"]:
        run["run_hash"] = _sha(
            {
                "run_id": run["run_id"],
                "protocol_hash": run["protocol_hash"],
                "agents": sorted(run["agents"], key=lambda row: row["agent_id"]),
            }
        )
    payload = {key: item for key, item in result.items() if key != "report_hash"}
    result["report_hash"] = _sha(payload)
    return result


def test_builder_executes_only_blinded_packets_and_never_serializes_hidden_target(tmp_path):
    receipt = _receipt()
    serialized = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
    assert TARGET not in serialized
    assert receipt["protocol"]["task"]["expected_result"] is None
    assert receipt["execution_complete"] is True
    assert receipt["blindness_structure_satisfied"] is True
    assert receipt["independence_structure_satisfied"] is True
    assert receipt["reproducibility_structure_satisfied"] is True
    assert receipt["truth_proven"] is False
    assert receipt["blindness_does_not_prove_truth"] is True
    assert len(receipt["runs"]) == 2

    path = _write(tmp_path, receipt)
    validated = validate_blind_analysis_execution_receipt(
        path,
        repo_root=ROOT,
        expected_revision=_git("rev-parse", "HEAD"),
        now=NOW,
    )
    assert validated.run_count == 2
    assert validated.report_hash == receipt["report_hash"]


def test_builder_rejects_unblinded_agent():
    agents = _agents()
    spec, runner = agents[0]
    agents[0] = (
        AgentSpec(
            agent_id=spec.agent_id,
            role=spec.role,
            runner_id=spec.runner_id,
            model_family=spec.model_family,
            perspective=spec.perspective,
            blind_to_expected_result=False,
        ),
        runner,
    )
    with pytest.raises(ValueError, match="blind_to_expected_result"):
        build_blind_analysis_execution_receipt(
            repo_root=ROOT,
            task=_task(),
            agents=agents,
            created_at_epoch=NOW,
        )


def test_builder_rejects_fake_independence_same_model_family():
    agents = _agents()
    spec, runner = agents[1]
    agents[1] = (
        AgentSpec(
            agent_id=spec.agent_id,
            role=spec.role,
            runner_id=spec.runner_id,
            model_family="family-a",
            perspective=spec.perspective,
            blind_to_expected_result=True,
        ),
        runner,
    )
    with pytest.raises(ValueError, match="model families"):
        build_blind_analysis_execution_receipt(
            repo_root=ROOT,
            task=_task(),
            agents=agents,
            created_at_epoch=NOW,
        )


def test_builder_rejects_failed_blind_runner():
    agents = _agents()

    def failed(_task):
        raise RuntimeError("runner failed")

    agents[1] = (agents[1][0], failed)
    with pytest.raises(ValueError, match="failed agents"):
        build_blind_analysis_execution_receipt(
            repo_root=ROOT,
            task=_task(),
            agents=agents,
            created_at_epoch=NOW,
        )


def test_validator_rejects_expected_result_in_receipt_even_if_outer_hash_recomputed(tmp_path):
    receipt = _receipt()
    receipt["protocol"]["task"]["expected_result"] = TARGET
    receipt = _rehash(receipt)
    path = _write(tmp_path, receipt)
    with pytest.raises(ValueError, match="must not contain expected_result"):
        validate_blind_analysis_execution_receipt(
            path,
            repo_root=ROOT,
            expected_revision=_git("rev-parse", "HEAD"),
            now=NOW,
        )


def test_validator_rejects_runner_packet_hash_tamper_even_with_recomputed_outer_hashes(tmp_path):
    receipt = _receipt()
    receipt["runs"][0]["agents"][0]["task_packet_hash"] = "0" * 64
    receipt = _rehash(receipt)
    path = _write(tmp_path, receipt)
    with pytest.raises(ValueError, match="different task packet"):
        validate_blind_analysis_execution_receipt(
            path,
            repo_root=ROOT,
            expected_revision=_git("rev-parse", "HEAD"),
            now=NOW,
        )


def test_validator_rejects_stale_and_wrong_revision_receipts(tmp_path):
    receipt = _receipt()
    path = _write(tmp_path, receipt, "stale.json")
    with pytest.raises(ValueError, match="stale"):
        validate_blind_analysis_execution_receipt(
            path,
            repo_root=ROOT,
            expected_revision=_git("rev-parse", "HEAD"),
            now=NOW + 3 * 60 * 60,
        )

    wrong = _receipt()
    wrong["implementation_revision"] = "0" * 40
    wrong = _rehash(wrong)
    path = _write(tmp_path, wrong, "wrong-revision.json")
    with pytest.raises(ValueError, match="revision does not match"):
        validate_blind_analysis_execution_receipt(
            path,
            repo_root=ROOT,
            expected_revision=_git("rev-parse", "HEAD"),
            now=NOW,
        )


def test_attestor_mints_only_three_strong_blind_process_proofs(tmp_path):
    receipt_path = _write(tmp_path, _receipt())
    ledger_path = tmp_path / "proofs.jsonl"
    result = attest_blind_analysis_proofs(
        repo_root=ROOT,
        execution_receipt_path=receipt_path,
        ledger_path=ledger_path,
        integrity_key=KEY,
        now=NOW,
    )
    assert result.receipts_added == 3
    assert result.receipts_reused == 0
    capability = result.audit.maturity_report.results[17]
    assert ProofKind.EXECUTION not in capability.missing_proofs
    assert ProofKind.INDEPENDENT not in capability.missing_proofs
    assert ProofKind.REPRODUCIBILITY not in capability.missing_proofs

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row
        for row in ledger._events()  # noqa: SLF001 - test of trusted ledger output
        if row.get("event_type") == "ADD"
    ]
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.INDEPENDENT.value,
        ProofKind.REPRODUCIBILITY.value,
    }
    assert {row["verifier"] for row in rows} == {"trusted-blind-analysis-observer"}
    assert {row["subject"] for row in rows} == {"blind-analysis-run"}


def test_existing_ledger_requires_anchor_and_same_receipt_is_idempotent(tmp_path):
    receipt_path = _write(tmp_path, _receipt())
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_blind_analysis_proofs(
        repo_root=ROOT,
        execution_receipt_path=receipt_path,
        ledger_path=ledger_path,
        integrity_key=KEY,
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_blind_analysis_proofs(
            repo_root=ROOT,
            execution_receipt_path=receipt_path,
            ledger_path=ledger_path,
            integrity_key=KEY,
            now=NOW + 1,
        )
    second = attest_blind_analysis_proofs(
        repo_root=ROOT,
        execution_receipt_path=receipt_path,
        ledger_path=ledger_path,
        integrity_key=KEY,
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 3


def test_readiness_exposes_specialized_external_route_without_calling_it_verified():
    report = audit_attestation_readiness(ROOT)
    capability = next(item for item in report.capabilities if item.capability_id == 18)
    routes = {route.proof_kind: route for route in capability.routes}
    for kind in (
        ProofKind.EXECUTION,
        ProofKind.INDEPENDENT,
        ProofKind.REPRODUCIBILITY,
    ):
        route = routes[kind]
        assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
        assert route.attestor_id == "blind-analysis"
        assert route.external_required is True
        assert route.verifiers == ("trusted-blind-analysis-observer",)
        assert route.subjects == ("blind-analysis-run",)
    assert "verified" not in " ".join(report.status_counts).lower()
