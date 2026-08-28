import hashlib
import json
import subprocess

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.maturity_attestor import (
    attest_foundation_code_test_proofs,
    validate_foundation_receipt,
)
from research_engine.maturity_proof import ProofLedger


KEY = b"A" * 32
NOW = 10_000.0


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


def _rule(capability_id, proof_kind, subjects, *, verifiers=("github-actions",)):
    return {
        "capability_id": capability_id,
        "proof_kind": proof_kind.value,
        "subjects": list(subjects),
        "verifiers": list(verifiers),
        "reference_prefixes": [],
    }


def _repo(tmp_path, *, capability_id=20, verifier="github-actions"):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    (root / "research_engine").mkdir()
    (root / "tests").mkdir()
    (root / "config").mkdir()
    (root / "scripts").mkdir()

    code_path = "research_engine/subject.py"
    test_path = "tests/test_subject.py"
    (root / code_path).write_text("VALUE = 1\n", encoding="utf-8")
    (root / test_path).write_text(
        "def test_value():\n    assert 1 == 1\n", encoding="utf-8"
    )
    policy = {
        "schema_version": 1,
        "rules": [
            _rule(capability_id, ProofKind.CODE, (code_path,), verifiers=(verifier,)),
            _rule(capability_id, ProofKind.TEST, (test_path,), verifiers=(verifier,)),
        ],
    }
    (root / "config" / "maturity_proof_policy.json").write_text(
        json.dumps(policy, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    return root, _git(root, "rev-parse", "HEAD"), code_path, test_path


def _stage(name, command):
    return {
        "name": name,
        "command": command,
        "returncode": 0,
        "duration_seconds": 0.01,
        "status": "passed",
        "output_tail": [],
    }


def _receipt_value(root, revision, *, created=9_900, passed=True):
    py = "python"
    stages = [
        _stage("compileall", [py, "-m", "compileall", "-q", "."]),
        _stage(
            "focused_pytest",
            [py, "-m", "pytest", "-q", "tests/test_alpha.py", "tests/test_beta.py"],
        ),
        _stage("all_pytest", [py, "-m", "pytest", "-q", "tests"]),
        _stage("offline_api_smoke", [py, "scripts/run_offline_api_smoke.py"]),
        _stage("core_regression", [py, "test_research_engine.py"]),
        _stage("provider_bypass_audit", [py, "scripts/audit_provider_bypass.py"]),
        _stage("architecture_audit", [py, "scripts/audit_architecture.py"]),
        _stage("benchmark_cross_domain", [py, "tests/benchmark_cross_domain.py"]),
        _stage(
            "benchmark_superconductivity_v2",
            [py, "tests/benchmark_superconductivity.py"],
        ),
    ]
    return {
        "schema_version": 2,
        "created_at_epoch": created,
        "python": "3.11.0",
        "repo_root": str(root),
        "code_revision": revision,
        "repository_clean": True,
        "code_identity_verified": True,
        "offline_zero_cost": True,
        "passed": passed,
        "failed_stages": [] if passed else ["all_pytest"],
        "stages": stages,
    }


def _write_receipt(tmp_path, root, revision, **changes):
    value = _receipt_value(root, revision)
    value.update(changes)
    path = tmp_path / f"foundation-{len(list(tmp_path.glob('foundation-*.json')))}.json"
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def test_green_foundation_attests_only_code_test_and_keeps_execution_missing(tmp_path):
    root, revision, _code_path, _test_path = _repo(tmp_path, capability_id=20)
    receipt = _write_receipt(tmp_path, root, revision)
    ledger_path = tmp_path / "proofs.jsonl"

    result = attest_foundation_code_test_proofs(
        repo_root=root,
        foundation_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="github-actions:run:536",
        now=NOW,
    )

    assert result.revision == revision
    assert result.receipts_added == 2
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.audit.accepted_receipts == 2
    c20 = result.audit.maturity_report.results[19]
    assert c20.status == "INCOMPLETE"
    assert ProofKind.EXECUTION in c20.missing_proofs
    assert ProofKind.REPRODUCIBILITY in c20.missing_proofs

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    add_rows = [
        row for row in ledger._events()  # noqa: SLF001 - adversarial test inspection
        if row.get("event_type") == "ADD"
    ]
    assert {row["proof_kind"] for row in add_rows} == {"code", "test"}
    assert all(row["verifier"] == "github-actions" for row in add_rows)
    assert all(row.get("implementation_revision") == "" for row in add_rows)


def test_same_receipt_is_idempotent_with_prior_anchor_continuity(tmp_path):
    root, revision, _code_path, _test_path = _repo(tmp_path, capability_id=1)
    receipt = _write_receipt(tmp_path, root, revision)
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_foundation_code_test_proofs(
        repo_root=root,
        foundation_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="github-actions:run:1",
        now=NOW,
    )
    second = attest_foundation_code_test_proofs(
        repo_root=root,
        foundation_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="github-actions:run:1",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 2
    assert second.audit.maturity_report.results[0].status == "VERIFIED"


def test_forged_wrong_revision_failed_and_stale_receipts_fail_closed(tmp_path):
    root, revision, _code_path, _test_path = _repo(tmp_path, capability_id=1)

    wrong_revision = _write_receipt(
        tmp_path, root, revision, code_revision="a" * 40
    )
    with pytest.raises(ValueError, match="code_revision"):
        validate_foundation_receipt(
            wrong_revision, expected_revision=revision, now=NOW
        )

    failed = _write_receipt(
        tmp_path,
        root,
        revision,
        passed=False,
        failed_stages=["all_pytest"],
    )
    with pytest.raises(ValueError, match="did not pass|failed_stages"):
        validate_foundation_receipt(failed, expected_revision=revision, now=NOW)

    stale = _write_receipt(
        tmp_path,
        root,
        revision,
        created_at_epoch=1,
    )
    with pytest.raises(ValueError, match="stale"):
        validate_foundation_receipt(stale, expected_revision=revision, now=NOW)


def test_required_stage_command_spoof_is_rejected(tmp_path):
    root, revision, _code_path, _test_path = _repo(tmp_path, capability_id=1)
    value = _receipt_value(root, revision)
    for stage in value["stages"]:
        if stage["name"] == "all_pytest":
            stage["command"] = ["python", "-m", "pytest", "-q", "tests/test_easy.py"]
    path = tmp_path / "spoof.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="all_pytest command is not canonical"):
        validate_foundation_receipt(path, expected_revision=revision, now=NOW)


def test_existing_ledger_requires_prior_anchor_and_rejects_wrong_anchor(tmp_path):
    root, revision, _code_path, _test_path = _repo(tmp_path, capability_id=1)
    receipt = _write_receipt(tmp_path, root, revision)
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_foundation_code_test_proofs(
        repo_root=root,
        foundation_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="github-actions:run:1",
        now=NOW,
    )

    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_foundation_code_test_proofs(
            repo_root=root,
            foundation_receipt_path=receipt,
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="github-actions:run:1",
            now=NOW + 1,
        )

    tampered = first.anchor_token[:-1] + (
        "A" if first.anchor_token[-1] != "A" else "B"
    )
    with pytest.raises(ValueError, match="continuity check"):
        attest_foundation_code_test_proofs(
            repo_root=root,
            foundation_receipt_path=receipt,
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="github-actions:run:1",
            now=NOW + 1,
            prior_anchor_token=tampered,
            prior_revision=revision,
        )


def test_new_revision_can_extend_only_from_prior_anchored_head(tmp_path):
    root, revision_a, code_path, _test_path = _repo(tmp_path, capability_id=1)
    receipt_a = _write_receipt(tmp_path, root, revision_a)
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_foundation_code_test_proofs(
        repo_root=root,
        foundation_receipt_path=receipt_a,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="github-actions:run:A",
        now=NOW,
    )

    (root / code_path).write_text("VALUE = 2\n", encoding="utf-8")
    _git(root, "add", code_path)
    _git(root, "commit", "-qm", "revision B")
    revision_b = _git(root, "rev-parse", "HEAD")
    receipt_b = _write_receipt(
        tmp_path,
        root,
        revision_b,
        created_at_epoch=int(NOW + 2),
    )

    second = attest_foundation_code_test_proofs(
        repo_root=root,
        foundation_receipt_path=receipt_b,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="github-actions:run:B",
        now=NOW + 3,
        prior_anchor_token=first.anchor_token,
        prior_revision=revision_a,
    )
    assert second.revision == revision_b
    assert second.audit.audit_valid is True
    assert second.audit.maturity_report.results[0].status == "VERIFIED"
    assert second.audit.ledger_status.stale_file_receipts >= 1


def test_policy_cannot_be_runtime_overridden_or_impersonate_github_actions(tmp_path):
    root, revision, _code_path, _test_path = _repo(
        tmp_path, capability_id=1, verifier="self"
    )
    receipt = _write_receipt(tmp_path, root, revision)
    with pytest.raises(ValueError, match="no github-actions CODE/TEST rules"):
        attest_foundation_code_test_proofs(
            repo_root=root,
            foundation_receipt_path=receipt,
            ledger_path=tmp_path / "proofs.jsonl",
            integrity_key=KEY,
            run_reference="github-actions:run:1",
            now=NOW,
        )


def test_attestor_refuses_ledger_inside_audited_repository(tmp_path):
    root, revision, _code_path, _test_path = _repo(tmp_path, capability_id=1)
    receipt = _write_receipt(tmp_path, root, revision)
    with pytest.raises(ValueError, match="must live outside"):
        attest_foundation_code_test_proofs(
            repo_root=root,
            foundation_receipt_path=receipt,
            ledger_path=root / "proofs.jsonl",
            integrity_key=KEY,
            run_reference="github-actions:run:1",
            now=NOW,
        )
