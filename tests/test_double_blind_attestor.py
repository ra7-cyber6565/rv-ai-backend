import hashlib
import json
import subprocess

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.double_blind_attestor import (
    attest_double_blind_proofs,
    issue_double_blind_protocol_commitment,
)
from research_engine.double_blind_evaluation import DoubleBlindStudy
from research_engine.maturity_proof import ProofLedger


PROOF_KEY = b"P" * 32
ASSIGNMENT_KEY = b"A" * 32
NOW = 50_000.0


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(root, *args):
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "config").mkdir()
    policy = {
        "schema_version": 1,
        "rules": [
            {
                "capability_id": 98,
                "proof_kind": kind,
                "subjects": ["double-blind-evaluation-run"],
                "verifiers": ["trusted-operator"],
                "reference_prefixes": ["double-blind:"],
            }
            for kind in (
                "execution",
                "independent_validation",
                "reproducibility",
            )
        ],
    }
    (root / "config" / "maturity_proof_policy.json").write_text(
        json.dumps(policy, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    (root / "marker.txt").write_text("fixture\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    return root


def _study(*, tolerance=0.1):
    study = DoubleBlindStudy(
        study_id="blind-study",
        protocol_hash=_sha("protocol"),
        assignment_key=ASSIGNMENT_KEY,
        metric_tolerances={"score": tolerance},
        evaluator_instructions={"task": "score blinded artifacts"},
    )
    arms = [
        study.register_candidate(
            candidate_id="candidate-a",
            artifact_digest=_sha("artifact-a"),
            builder_theory="theory A",
        ),
        study.register_candidate(
            candidate_id="candidate-b",
            artifact_digest=_sha("artifact-b"),
            builder_theory="theory B",
        ),
    ]
    study.register_evaluator(
        evaluator_id="eval-1",
        evaluator_family="family-a",
        evaluator_implementation_hash=_sha("impl-a"),
    )
    study.register_evaluator(
        evaluator_id="eval-2",
        evaluator_family="family-b",
        evaluator_implementation_hash=_sha("impl-b"),
    )
    study.seal()
    return study, arms


def _finish(study, arms, *, disagreement=False):
    second_b = 2.5 if disagreement else 2.05
    values = {
        "eval-1": [1.0, 2.0],
        "eval-2": [1.05, second_b],
    }
    for evaluator, scores in values.items():
        for arm, score in zip(arms, scores):
            study.record_result(
                evaluator_id=evaluator,
                arm_id=arm,
                metrics={"score": score},
            )
    return study.reveal()


def _commit(root, study, now=NOW):
    return issue_double_blind_protocol_commitment(
        study=study,
        repo_root=root,
        integrity_key=PROOF_KEY,
        now=now,
    )


def _attest(root, report, token, tmp_path, **kwargs):
    return attest_double_blind_proofs(
        report=report,
        preregistration_token=token,
        assignment_key=kwargs.pop("assignment_key", ASSIGNMENT_KEY),
        repo_root=root,
        ledger_path=kwargs.pop("ledger_path", tmp_path / "proofs.jsonl"),
        integrity_key=PROOF_KEY,
        now=kwargs.pop("now", NOW + 10),
        **kwargs,
    )


def test_preregister_before_results_then_mint_all_three_when_reproducible(tmp_path):
    root = _repo(tmp_path)
    study, arms = _study()
    commitment = _commit(root, study)
    report = _finish(study, arms)
    result = _attest(root, report, commitment.token, tmp_path)
    assert result.reproducibility_satisfied is True
    assert result.proofs_minted == (
        ProofKind.EXECUTION,
        ProofKind.INDEPENDENT,
        ProofKind.REPRODUCIBILITY,
    )
    assert result.receipts_added == 3
    assert result.audit.audit_valid is True
    assert report.truth_proven is False
    assert report.profitability_proven is False


def test_disagreement_mints_execution_and_independence_but_not_reproducibility(tmp_path):
    root = _repo(tmp_path)
    study, arms = _study()
    commitment = _commit(root, study)
    report = _finish(study, arms, disagreement=True)
    result = _attest(root, report, commitment.token, tmp_path)
    assert result.reproducibility_satisfied is False
    assert result.proofs_minted == (
        ProofKind.EXECUTION,
        ProofKind.INDEPENDENT,
    )
    assert ProofKind.REPRODUCIBILITY not in result.proofs_minted
    capability = result.audit.maturity_report.results[97]
    assert ProofKind.REPRODUCIBILITY in capability.missing_proofs


def test_preregistration_after_first_result_is_rejected(tmp_path):
    root = _repo(tmp_path)
    study, arms = _study()
    study.record_result(
        evaluator_id="eval-1",
        arm_id=arms[0],
        metrics={"score": 1.0},
    )
    with pytest.raises(ValueError, match="before any evaluator result"):
        _commit(root, study)


def test_wrong_assignment_key_cannot_open_preregistration(tmp_path):
    root = _repo(tmp_path)
    study, arms = _study()
    commitment = _commit(root, study)
    report = _finish(study, arms)
    with pytest.raises(ValueError, match="assignment_key does not match"):
        _attest(
            root,
            report,
            commitment.token,
            tmp_path,
            assignment_key=b"B" * 32,
        )


def test_forged_report_boolean_is_rejected_even_with_recomputed_outer_hash(tmp_path):
    root = _repo(tmp_path)
    study, arms = _study()
    commitment = _commit(root, study)
    report = _finish(study, arms).to_dict()
    report["truth_proven"] = True
    payload = {key: value for key, value in report.items() if key != "report_hash"}
    report["report_hash"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="must not claim truth_proven"):
        _attest(root, report, commitment.token, tmp_path)


def test_tampered_metric_with_recomputed_report_hash_still_fails_result_hash(tmp_path):
    root = _repo(tmp_path)
    study, arms = _study()
    commitment = _commit(root, study)
    report = _finish(study, arms).to_dict()
    report["results"][0]["metrics"]["score"] += 100.0
    payload = {key: value for key, value in report.items() if key != "report_hash"}
    report["report_hash"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="result_hash verification failed"):
        _attest(root, report, commitment.token, tmp_path)


def test_old_revision_preregistration_cannot_attest_new_git_head(tmp_path):
    root = _repo(tmp_path)
    study, arms = _study()
    commitment = _commit(root, study)
    report = _finish(study, arms)
    (root / "marker.txt").write_text("revision two\n", encoding="utf-8")
    _git(root, "add", "marker.txt")
    _git(root, "commit", "-qm", "revision two")
    with pytest.raises(ValueError, match="revision does not match current Git HEAD"):
        _attest(root, report, commitment.token, tmp_path)


def test_stale_preregistration_token_fails_closed(tmp_path):
    root = _repo(tmp_path)
    study, arms = _study()
    commitment = _commit(root, study, now=100.0)
    report = _finish(study, arms)
    with pytest.raises(ValueError, match="token is stale"):
        _attest(root, report, commitment.token, tmp_path, now=100.0 + 24 * 60 * 60 + 1)


def test_existing_ledger_requires_previous_trusted_anchor_and_is_idempotent(tmp_path):
    root = _repo(tmp_path)
    study, arms = _study()
    commitment = _commit(root, study)
    report = _finish(study, arms)
    ledger_path = tmp_path / "proofs.jsonl"
    first = _attest(
        root, report, commitment.token, tmp_path, ledger_path=ledger_path
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        _attest(
            root,
            report,
            commitment.token,
            tmp_path,
            ledger_path=ledger_path,
            now=NOW + 11,
        )
    second = _attest(
        root,
        report,
        commitment.token,
        tmp_path,
        ledger_path=ledger_path,
        now=NOW + 11,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 3


def test_proof_ledger_contains_only_capability_98_required_strong_kinds(tmp_path):
    root = _repo(tmp_path)
    study, arms = _study()
    commitment = _commit(root, study)
    report = _finish(study, arms)
    ledger_path = tmp_path / "proofs.jsonl"
    _attest(root, report, commitment.token, tmp_path, ledger_path=ledger_path)
    ledger = ProofLedger(str(ledger_path), integrity_key=PROOF_KEY)
    rows = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
    ]
    assert {row["capability_id"] for row in rows} == {98}
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.INDEPENDENT.value,
        ProofKind.REPRODUCIBILITY.value,
    }
    assert all(row["verifier"] == "trusted-operator" for row in rows)
    assert all(row["reference"].startswith("double-blind:") for row in rows)
