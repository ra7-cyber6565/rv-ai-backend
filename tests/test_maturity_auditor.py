import hashlib
import json
import os
import subprocess

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.maturity_auditor import audit_repository_maturity
from research_engine.maturity_proof import ProofLedger


KEY = b"T" * 32


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _policy(*rules):
    return {"schema_version": 1, "rules": list(rules)}


def _rule(capability_id, proof_kind, subjects, *, verifiers=("ci",), prefixes=()):
    return {
        "capability_id": capability_id,
        "proof_kind": proof_kind.value,
        "subjects": list(subjects),
        "verifiers": list(verifiers),
        "reference_prefixes": list(prefixes),
    }


def _repo(tmp_path, *, policy):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")

    (root / "research_engine").mkdir()
    (root / "tests").mkdir()
    (root / "config").mkdir()
    code = b"VALUE = 1\n"
    test = b"def test_value():\n    assert 1 == 1\n"
    (root / "research_engine" / "question.py").write_bytes(code)
    (root / "tests" / "test_question.py").write_bytes(test)
    (root / "config" / "maturity_proof_policy.json").write_text(
        json.dumps(policy, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    revision = _git(root, "rev-parse", "HEAD")
    return root, revision, code, test


def _cap1_policy():
    return _policy(
        _rule(1, ProofKind.CODE, ("research_engine/question.py",)),
        _rule(1, ProofKind.TEST, ("tests/test_question.py",)),
    )


def _ledger_with_cap1(
    tmp_path,
    revision,
    code,
    test,
    *,
    code_subject="research_engine/question.py",
):
    path = tmp_path / "proofs.jsonl"
    ledger = ProofLedger(str(path), integrity_key=KEY)
    ledger.add(
        receipt_id="cap1-code",
        capability_id=1,
        proof_kind=ProofKind.CODE,
        subject=code_subject,
        subject_sha256=_sha(code),
        verifier="ci",
        observed_at=100.0,
    )
    ledger.add(
        receipt_id="cap1-test",
        capability_id=1,
        proof_kind=ProofKind.TEST,
        subject="tests/test_question.py",
        subject_sha256=_sha(test),
        verifier="ci",
        observed_at=100.0,
    )
    anchor = ledger.create_anchor(current_revision=revision, issued_at=101.0)
    return path, ledger, anchor


def test_auditor_derives_clean_git_head_and_hashes_tracked_files(tmp_path):
    root, revision, code, test = _repo(tmp_path, policy=_cap1_policy())
    ledger_path, _ledger, anchor = _ledger_with_cap1(
        tmp_path, revision, code, test
    )

    audit = audit_repository_maturity(
        repo_root=root,
        ledger_path=ledger_path,
        integrity_key=KEY,
        anchor_token=anchor,
        now=102.0,
    )

    assert audit.revision == revision
    assert audit.repository_clean is True
    assert audit.cryptographic_integrity is True
    assert audit.audit_valid is True
    assert audit.accepted_receipts == 2
    assert audit.rejected_receipts == ()
    assert audit.maturity_report.verified == 1
    assert audit.maturity_report.results[0].status == "VERIFIED"
    assert len(audit.audit_sha256) == 64
    assert 1 not in {item.capability_id for item in audit.blockers}


def test_dirty_repository_is_rejected_before_scoring(tmp_path):
    root, revision, code, test = _repo(tmp_path, policy=_cap1_policy())
    ledger_path, _ledger, anchor = _ledger_with_cap1(
        tmp_path, revision, code, test
    )
    (root / "research_engine" / "question.py").write_text(
        "VALUE = 2\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="clean Git checkout"):
        audit_repository_maturity(
            repo_root=root,
            ledger_path=ledger_path,
            integrity_key=KEY,
            anchor_token=anchor,
            now=102.0,
        )


def test_untracked_file_receipt_is_rejected_and_cannot_score(tmp_path):
    policy = _policy(
        _rule(1, ProofKind.CODE, ("research_engine/untracked.py",)),
        _rule(1, ProofKind.TEST, ("tests/test_question.py",)),
    )
    root, revision, _code, test = _repo(tmp_path, policy=policy)
    fake_code = b"VALUE = 999\n"
    ledger_path, _ledger, anchor = _ledger_with_cap1(
        tmp_path,
        revision,
        fake_code,
        test,
        code_subject="research_engine/untracked.py",
    )

    audit = audit_repository_maturity(
        repo_root=root,
        ledger_path=ledger_path,
        integrity_key=KEY,
        anchor_token=anchor,
        now=102.0,
    )
    assert audit.audit_valid is False
    assert audit.accepted_receipts == 1
    assert any("not tracked" in item.reason for item in audit.rejected_receipts)
    assert audit.maturity_report.results[0].status == "INCOMPLETE"


def test_policy_is_committed_and_blocks_self_asserted_verifier(tmp_path):
    root, revision, code, test = _repo(tmp_path, policy=_cap1_policy())
    path = tmp_path / "proofs.jsonl"
    ledger = ProofLedger(str(path), integrity_key=KEY)
    ledger.add(
        receipt_id="cap1-code",
        capability_id=1,
        proof_kind=ProofKind.CODE,
        subject="research_engine/question.py",
        subject_sha256=_sha(code),
        verifier="self",
        observed_at=100.0,
    )
    ledger.add(
        receipt_id="cap1-test",
        capability_id=1,
        proof_kind=ProofKind.TEST,
        subject="tests/test_question.py",
        subject_sha256=_sha(test),
        verifier="ci",
        observed_at=100.0,
    )
    anchor = ledger.create_anchor(current_revision=revision, issued_at=101.0)

    audit = audit_repository_maturity(
        repo_root=root,
        ledger_path=path,
        integrity_key=KEY,
        anchor_token=anchor,
        now=102.0,
    )
    assert audit.audit_valid is False
    assert audit.accepted_receipts == 1
    assert any(
        item.receipt_id == "cap1-code"
        and item.reason == "active_receipt_not_allowed_by_policy"
        for item in audit.rejected_receipts
    )
    assert audit.maturity_report.results[0].status == "INCOMPLETE"


def test_no_manual_revision_parameter_can_revive_old_execution_proof(tmp_path):
    policy = _policy(
        _rule(20, ProofKind.CODE, ("research_engine/question.py",)),
        _rule(20, ProofKind.TEST, ("tests/test_question.py",)),
        _rule(
            20,
            ProofKind.EXECUTION,
            ("ci:hypothesis-evolution",),
            prefixes=("run:",),
        ),
        _rule(
            20,
            ProofKind.REPRODUCIBILITY,
            ("ci:hypothesis-evolution",),
            prefixes=("run:",),
        ),
    )
    root, revision, code, test = _repo(tmp_path, policy=policy)
    old_revision = "a" * 40
    assert old_revision != revision
    path = tmp_path / "proofs.jsonl"
    ledger = ProofLedger(str(path), integrity_key=KEY)
    ledger.add(
        receipt_id="c20-code",
        capability_id=20,
        proof_kind=ProofKind.CODE,
        subject="research_engine/question.py",
        subject_sha256=_sha(code),
        verifier="ci",
        observed_at=100.0,
    )
    ledger.add(
        receipt_id="c20-test",
        capability_id=20,
        proof_kind=ProofKind.TEST,
        subject="tests/test_question.py",
        subject_sha256=_sha(test),
        verifier="ci",
        observed_at=100.0,
    )
    for suffix, kind in (
        ("exec", ProofKind.EXECUTION),
        ("repro", ProofKind.REPRODUCIBILITY),
    ):
        ledger.add(
            receipt_id=f"c20-{suffix}",
            capability_id=20,
            proof_kind=kind,
            subject="ci:hypothesis-evolution",
            subject_sha256=_sha(suffix.encode()),
            verifier="ci",
            observed_at=100.0,
            reference="run:old",
            implementation_revision=old_revision,
        )
    anchor = ledger.create_anchor(current_revision=revision, issued_at=101.0)

    audit = audit_repository_maturity(
        repo_root=root,
        ledger_path=path,
        integrity_key=KEY,
        anchor_token=anchor,
        now=102.0,
    )
    c20 = audit.maturity_report.results[19]
    assert c20.status == "INCOMPLETE"
    assert ProofKind.EXECUTION in c20.missing_proofs
    assert ProofKind.REPRODUCIBILITY in c20.missing_proofs
    assert audit.ledger_status.stale_revision_receipts == 2


def test_missing_or_wrong_anchor_fails_before_maturity_report(tmp_path):
    root, revision, code, test = _repo(tmp_path, policy=_cap1_policy())
    ledger_path, _ledger, anchor = _ledger_with_cap1(
        tmp_path, revision, code, test
    )
    with pytest.raises(ValueError, match="trusted external anchor"):
        audit_repository_maturity(
            repo_root=root,
            ledger_path=ledger_path,
            integrity_key=KEY,
            anchor_token="",
            now=102.0,
        )
    with pytest.raises(ValueError, match="anchor verification failed"):
        audit_repository_maturity(
            repo_root=root,
            ledger_path=ledger_path,
            integrity_key=b"W" * 32,
            anchor_token=anchor,
            now=102.0,
        )


def test_policy_rejects_revision_bound_rule_without_reference_namespace(tmp_path):
    bad_policy = _policy(
        _rule(
            20,
            ProofKind.EXECUTION,
            ("ci:hypothesis-evolution",),
            prefixes=(),
        )
    )
    root, revision, _code, _test = _repo(tmp_path, policy=bad_policy)
    path = tmp_path / "proofs.jsonl"
    ledger = ProofLedger(str(path), integrity_key=KEY)
    ledger.add(
        receipt_id="execution",
        capability_id=20,
        proof_kind=ProofKind.EXECUTION,
        subject="ci:hypothesis-evolution",
        subject_sha256=_sha(b"execution"),
        verifier="ci",
        observed_at=100.0,
        reference="run:1",
        implementation_revision=revision,
    )
    anchor = ledger.create_anchor(current_revision=revision, issued_at=101.0)

    with pytest.raises(ValueError, match="must constrain reference_prefixes"):
        audit_repository_maturity(
            repo_root=root,
            ledger_path=path,
            integrity_key=KEY,
            anchor_token=anchor,
            now=102.0,
        )


@pytest.mark.skipif(os.name == "nt", reason="symlink fixture requires POSIX semantics")
def test_tracked_symlink_cannot_be_used_as_code_evidence(tmp_path):
    policy = _policy(
        _rule(1, ProofKind.CODE, ("research_engine/link.py",)),
        _rule(1, ProofKind.TEST, ("tests/test_question.py",)),
    )
    root, _revision, _code, _test = _repo(tmp_path, policy=policy)
    target = root / "research_engine" / "target.py"
    target.write_text("VALUE = 7\n", encoding="utf-8")
    link = root / "research_engine" / "link.py"
    link.symlink_to("target.py")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "add symlink")
    revision = _git(root, "rev-parse", "HEAD")

    path = tmp_path / "proofs.jsonl"
    ledger = ProofLedger(str(path), integrity_key=KEY)
    ledger.add(
        receipt_id="link-code",
        capability_id=1,
        proof_kind=ProofKind.CODE,
        subject="research_engine/link.py",
        subject_sha256=_sha(target.read_bytes()),
        verifier="ci",
        observed_at=100.0,
    )
    anchor = ledger.create_anchor(current_revision=revision, issued_at=101.0)

    audit = audit_repository_maturity(
        repo_root=root,
        ledger_path=path,
        integrity_key=KEY,
        anchor_token=anchor,
        now=102.0,
    )
    assert audit.audit_valid is False
    assert any("tracked regular file" in item.reason for item in audit.rejected_receipts)
