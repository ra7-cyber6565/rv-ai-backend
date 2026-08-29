import json
import subprocess

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.maturity_proof import ProofLedger
from research_engine.wiring_attestor import attest_foundation_wiring_proofs


KEY = b"W" * 32
NOW = 20_000.0
_BASELINE_TEST = "tests/test_baseline.py"


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


def _rule(capability_id, subject, *, prefix="github-actions:"):
    return {
        "capability_id": capability_id,
        "proof_kind": ProofKind.WIRING.value,
        "subjects": [subject],
        "verifiers": ["github-actions"],
        "reference_prefixes": [prefix],
    }


def _repo(tmp_path, *, include_wiring=True, subject="tests/test_runtime_wiring.py"):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    (root / "tests").mkdir()
    (root / "config").mkdir()
    (root / "scripts").mkdir()
    (root / subject).write_text(
        "def test_production_wiring():\n    assert True\n", encoding="utf-8"
    )
    (root / _BASELINE_TEST).write_text(
        "def test_baseline():\n    assert True\n", encoding="utf-8"
    )
    policy = {"schema_version": 1, "rules": []}
    if include_wiring:
        policy["rules"].append(_rule(14, subject))
    # Keep one ordinary CODE rule so a no-WIRING fixture is still a valid policy.
    if not include_wiring:
        code = root / "subject.py"
        code.write_text("VALUE = 1\n", encoding="utf-8")
        policy["rules"].append({
            "capability_id": 1,
            "proof_kind": ProofKind.CODE.value,
            "subjects": ["subject.py"],
            "verifiers": ["github-actions"],
            "reference_prefixes": [],
        })
    (root / "config" / "maturity_proof_policy.json").write_text(
        json.dumps(policy, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    return root, _git(root, "rev-parse", "HEAD"), subject


def _stage(name, command):
    return {
        "name": name,
        "command": command,
        "returncode": 0,
        "duration_seconds": 0.01,
        "status": "passed",
        "output_tail": [],
    }


def _receipt_value(root, revision, *, focused_tests, created=19_900):
    py = "python"
    tests = list(focused_tests)
    if _BASELINE_TEST not in tests:
        tests.append(_BASELINE_TEST)
    return {
        "schema_version": 2,
        "created_at_epoch": created,
        "python": "3.11.0",
        "repo_root": str(root),
        "code_revision": revision,
        "repository_clean": True,
        "code_identity_verified": True,
        "offline_zero_cost": True,
        "passed": True,
        "failed_stages": [],
        "stages": [
            _stage("compileall", [py, "-m", "compileall", "-q", "."]),
            _stage("focused_pytest", [py, "-m", "pytest", "-q", *tests]),
            _stage("all_pytest", [py, "-m", "pytest", "-q", "tests"]),
            _stage("offline_api_smoke", [py, "scripts/run_offline_api_smoke.py"]),
            _stage("core_regression", [py, "test_research_engine.py"]),
            _stage("provider_bypass_audit", [py, "scripts/audit_provider_bypass.py"]),
            _stage("architecture_audit", [py, "scripts/audit_architecture.py"]),
            _stage("benchmark_cross_domain", [py, "tests/benchmark_cross_domain.py"]),
            _stage("benchmark_superconductivity_v2", [py, "tests/benchmark_superconductivity.py"]),
            _stage("benchmark_dark_matter_acceptance", [py, "tests/benchmark_dark_matter_acceptance.py"]),
        ],
    }


def _write_receipt(tmp_path, root, revision, *, focused_tests, created=19_900):
    path = tmp_path / f"foundation-{len(list(tmp_path.glob('foundation-*.json')))}.json"
    path.write_text(
        json.dumps(
            _receipt_value(
                root, revision, focused_tests=focused_tests, created=created
            ),
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def test_green_focused_integration_test_mints_revision_bound_wiring_only(tmp_path):
    root, revision, subject = _repo(tmp_path)
    receipt = _write_receipt(tmp_path, root, revision, focused_tests=[subject])
    ledger_path = tmp_path / "proofs.jsonl"
    result = attest_foundation_wiring_proofs(
        repo_root=root,
        foundation_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="github-actions:run:100",
        now=NOW,
    )
    assert result.revision == revision
    assert result.receipts_added == 1
    assert result.receipts_reused == 0
    assert subject in result.focused_tests
    assert _BASELINE_TEST in result.focused_tests
    assert result.audit.audit_valid is True

    capability = result.audit.maturity_report.results[13]
    assert capability.status == "INCOMPLETE"
    assert ProofKind.CODE in capability.missing_proofs
    assert ProofKind.TEST in capability.missing_proofs
    assert ProofKind.WIRING not in capability.missing_proofs

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [row for row in ledger._events() if row.get("event_type") == "ADD"]  # noqa: SLF001
    assert len(rows) == 1
    assert rows[0]["proof_kind"] == ProofKind.WIRING.value
    assert rows[0]["implementation_revision"] == revision
    assert rows[0]["verifier"] == "github-actions"


def test_wiring_subject_not_in_focused_pytest_fails_before_ledger_mutation(tmp_path):
    root, revision, subject = _repo(tmp_path)
    other = root / "tests" / "test_other.py"
    other.write_text("def test_other():\n    assert True\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "other test")
    revision = _git(root, "rev-parse", "HEAD")
    receipt = _write_receipt(
        tmp_path, root, revision, focused_tests=["tests/test_other.py"]
    )
    ledger_path = tmp_path / "proofs.jsonl"
    with pytest.raises(ValueError, match="was not executed by focused_pytest"):
        attest_foundation_wiring_proofs(
            repo_root=root,
            foundation_receipt_path=receipt,
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="github-actions:run:101",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_wrong_reference_prefix_fails_before_ledger_mutation(tmp_path):
    root, revision, subject = _repo(tmp_path)
    receipt = _write_receipt(tmp_path, root, revision, focused_tests=[subject])
    ledger_path = tmp_path / "proofs.jsonl"
    with pytest.raises(ValueError, match="run_reference is not allowed"):
        attest_foundation_wiring_proofs(
            repo_root=root,
            foundation_receipt_path=receipt,
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="self-asserted:run:1",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_no_committed_wiring_rule_fails_closed(tmp_path):
    root, revision, subject = _repo(tmp_path, include_wiring=False)
    receipt = _write_receipt(tmp_path, root, revision, focused_tests=[subject])
    ledger_path = tmp_path / "proofs.jsonl"
    with pytest.raises(ValueError, match="no github-actions WIRING rules"):
        attest_foundation_wiring_proofs(
            repo_root=root,
            foundation_receipt_path=receipt,
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="github-actions:run:102",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_existing_wiring_ledger_requires_prior_anchor_and_is_idempotent(tmp_path):
    root, revision, subject = _repo(tmp_path)
    receipt = _write_receipt(tmp_path, root, revision, focused_tests=[subject])
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_foundation_wiring_proofs(
        repo_root=root,
        foundation_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="github-actions:run:103",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_foundation_wiring_proofs(
            repo_root=root,
            foundation_receipt_path=receipt,
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="github-actions:run:103",
            now=NOW + 1,
        )
    second = attest_foundation_wiring_proofs(
        repo_root=root,
        foundation_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="github-actions:run:103",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 1


def test_previous_wiring_proof_goes_stale_after_revision_change(tmp_path):
    root, revision_a, subject = _repo(tmp_path)
    receipt_a = _write_receipt(tmp_path, root, revision_a, focused_tests=[subject])
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_foundation_wiring_proofs(
        repo_root=root,
        foundation_receipt_path=receipt_a,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="github-actions:run:A",
        now=NOW,
    )

    (root / subject).write_text(
        "def test_production_wiring():\n    assert 2 == 2\n", encoding="utf-8"
    )
    _git(root, "add", subject)
    _git(root, "commit", "-qm", "revision B")
    revision_b = _git(root, "rev-parse", "HEAD")
    receipt_b = _write_receipt(
        tmp_path,
        root,
        revision_b,
        focused_tests=[subject],
        created=int(NOW + 2),
    )
    second = attest_foundation_wiring_proofs(
        repo_root=root,
        foundation_receipt_path=receipt_b,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="github-actions:run:B",
        now=NOW + 3,
        prior_anchor_token=first.anchor_token,
        prior_revision=revision_a,
    )
    assert second.audit.audit_valid is True
    assert second.audit.ledger_status.stale_revision_receipts >= 1
    capability = second.audit.maturity_report.results[13]
    assert ProofKind.WIRING not in capability.missing_proofs


def test_wiring_attestor_never_mints_execution_or_safety(tmp_path):
    root, revision, subject = _repo(tmp_path)
    receipt = _write_receipt(tmp_path, root, revision, focused_tests=[subject])
    ledger_path = tmp_path / "proofs.jsonl"
    attest_foundation_wiring_proofs(
        repo_root=root,
        foundation_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="github-actions:run:104",
        now=NOW,
    )
    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    kinds = {
        row["proof_kind"]
        for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
    }
    assert kinds == {ProofKind.WIRING.value}
    assert ProofKind.EXECUTION.value not in kinds
    assert ProofKind.SAFETY.value not in kinds
    assert ProofKind.LIVE.value not in kinds
    assert ProofKind.HARDWARE.value not in kinds
