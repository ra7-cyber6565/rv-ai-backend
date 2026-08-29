import hashlib
import importlib.util
import json
import subprocess

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.maturity_proof import ProofLedger
from research_engine.triple_implementation import (
    TripleImplementationEngine,
    TripleImplementationSpec,
)
from research_engine.triple_implementation_attestor import (
    attest_triple_implementation_proofs,
    validate_triple_execution_receipt,
)


KEY = b"T" * 32
NOW = 20_000.0


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


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_runner(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module.run


def _proof_rule(kind):
    return {
        "capability_id": 40,
        "proof_kind": kind.value,
        "subjects": ["triple-implementation-run"],
        "verifiers": ["trusted-operator"],
        "reference_prefixes": ["triple-implementation:"],
    }


def _repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    (root / "implementations").mkdir()
    (root / "config").mkdir()

    workers = [
        ("I1", "r1", "manual", "a.py", 0.50),
        ("I2", "r2", "stdlib", "b.py", 0.51),
        ("I3", "r3", "exact", "c.py", 0.49),
    ]
    manifest = []
    specs = []
    for implementation_id, runner_id, family, filename, value in workers:
        path = root / "implementations" / filename
        path.write_text(
            "def run(protocol):\n"
            f"    return {{'metrics': {{'effect': {value!r}, 'n': 100}}}}\n",
            encoding="utf-8",
        )
        subject = f"implementations/{filename}"
        digest = _sha(path)
        manifest.append({
            "implementation_id": implementation_id,
            "runner_id": runner_id,
            "implementation_family": family,
            "subject": subject,
            "code_digest": digest,
        })
        specs.append(
            TripleImplementationSpec(
                implementation_id=implementation_id,
                runner_id=runner_id,
                implementation_family=family,
                code_digest=digest,
                runner=_load_runner(path, f"worker_{implementation_id}"),
            )
        )

    policy = {
        "schema_version": 1,
        "rules": [
            _proof_rule(ProofKind.EXECUTION),
            _proof_rule(ProofKind.INDEPENDENT),
            _proof_rule(ProofKind.REPRODUCIBILITY),
        ],
    }
    (root / "config" / "maturity_proof_policy.json").write_text(
        json.dumps(policy, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    revision = _git(root, "rev-parse", "HEAD")

    report = TripleImplementationEngine(specs).run(
        {"protocol_id": "P1", "dataset_commitment": "locked"},
        metric_tolerances={"effect": 0.02, "n": 0.0},
    )
    assert report.triple_confirmed is True
    return root, revision, manifest, report.to_dict()


def _write_receipt(
    tmp_path,
    revision,
    manifest,
    report,
    *,
    created=19_900,
    **changes,
):
    value = {
        "schema_version": 1,
        "created_at_epoch": created,
        "implementation_revision": revision,
        "implementations": manifest,
        "report": report,
    }
    value.update(changes)
    path = tmp_path / f"triple-{len(list(tmp_path.glob('triple-*.json')))}.json"
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def test_valid_triple_receipt_mints_only_execution_independent_and_reproducibility(
    tmp_path,
):
    root, revision, manifest, report = _repo(tmp_path)
    receipt = _write_receipt(tmp_path, revision, manifest, report)
    ledger_path = tmp_path / "proofs.jsonl"

    result = attest_triple_implementation_proofs(
        repo_root=root,
        execution_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        now=NOW,
    )

    assert result.revision == revision
    assert result.receipts_added == 3
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    c40 = result.audit.maturity_report.results[39]
    assert c40.status == "INCOMPLETE"
    assert set(c40.missing_proofs) == {ProofKind.CODE, ProofKind.TEST}

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row
        for row in ledger._events()  # noqa: SLF001 - adversarial inspection
        if row.get("event_type") == "ADD"
    ]
    assert {row["proof_kind"] for row in rows} == {
        "execution",
        "independent_validation",
        "reproducibility",
    }
    assert all(row["verifier"] == "trusted-operator" for row in rows)
    assert all(row["implementation_revision"] == revision for row in rows)
    assert all(
        row["reference"].startswith("triple-implementation:") for row in rows
    )


def test_receipt_is_idempotent_only_with_prior_anchor_continuity(tmp_path):
    root, revision, manifest, report = _repo(tmp_path)
    receipt = _write_receipt(tmp_path, revision, manifest, report)
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_triple_implementation_proofs(
        repo_root=root,
        execution_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_triple_implementation_proofs(
            repo_root=root,
            execution_receipt_path=receipt,
            ledger_path=ledger_path,
            integrity_key=KEY,
            now=NOW + 1,
        )
    second = attest_triple_implementation_proofs(
        repo_root=root,
        execution_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 3


def test_tampered_tracked_implementation_digest_is_rejected(tmp_path):
    root, revision, manifest, report = _repo(tmp_path)
    forged = [dict(row) for row in manifest]
    forged[0]["code_digest"] = "0" * 64
    receipt = _write_receipt(tmp_path, revision, forged, report)
    with pytest.raises(ValueError, match="does not match tracked file"):
        validate_triple_execution_receipt(
            receipt,
            repo_root=root,
            expected_revision=revision,
            now=NOW,
        )


def test_unconfirmed_or_truth_claiming_report_is_rejected(tmp_path):
    root, revision, manifest, report = _repo(tmp_path)
    unconfirmed = dict(report)
    unconfirmed["triple_confirmed"] = False
    receipt = _write_receipt(tmp_path, revision, manifest, unconfirmed)
    with pytest.raises(ValueError, match="not confirmed"):
        validate_triple_execution_receipt(
            receipt,
            repo_root=root,
            expected_revision=revision,
            now=NOW,
        )

    truth_claim = dict(report)
    truth_claim["truth_proven"] = True
    receipt2 = _write_receipt(tmp_path, revision, manifest, truth_claim)
    with pytest.raises(ValueError, match="must not claim truth_proven"):
        validate_triple_execution_receipt(
            receipt2,
            repo_root=root,
            expected_revision=revision,
            now=NOW,
        )


def test_missing_pairwise_comparison_and_result_hash_tamper_are_rejected(tmp_path):
    root, revision, manifest, report = _repo(tmp_path)
    missing_pair = dict(report)
    missing_pair["comparisons"] = list(report["comparisons"][:-1])
    receipt = _write_receipt(tmp_path, revision, manifest, missing_pair)
    with pytest.raises(ValueError, match="every all-pairs"):
        validate_triple_execution_receipt(
            receipt,
            repo_root=root,
            expected_revision=revision,
            now=NOW,
        )

    bad_result = json.loads(json.dumps(report))
    bad_result["results"][0]["result_hash"] = "f" * 64
    receipt2 = _write_receipt(tmp_path, revision, manifest, bad_result)
    with pytest.raises(ValueError, match="result_hash verification failed"):
        validate_triple_execution_receipt(
            receipt2,
            repo_root=root,
            expected_revision=revision,
            now=NOW,
        )


def test_wrong_revision_stale_and_dirty_repo_fail_closed(tmp_path):
    root, revision, manifest, report = _repo(tmp_path)
    wrong = _write_receipt(
        tmp_path,
        revision,
        manifest,
        report,
        implementation_revision="a" * 40,
    )
    with pytest.raises(ValueError, match="revision does not match"):
        validate_triple_execution_receipt(
            wrong,
            repo_root=root,
            expected_revision=revision,
            now=NOW,
        )

    stale = _write_receipt(tmp_path, revision, manifest, report, created=1)
    with pytest.raises(ValueError, match="stale"):
        validate_triple_execution_receipt(
            stale,
            repo_root=root,
            expected_revision=revision,
            now=NOW,
        )

    good = _write_receipt(tmp_path, revision, manifest, report)
    (root / "dirty.txt").write_text("untracked\n", encoding="utf-8")
    with pytest.raises(ValueError, match="clean Git checkout"):
        attest_triple_implementation_proofs(
            repo_root=root,
            execution_receipt_path=good,
            ledger_path=tmp_path / "proofs.jsonl",
            integrity_key=KEY,
            now=NOW,
        )


def test_committed_policy_must_authorize_all_three_strong_proof_classes(tmp_path):
    root, revision, manifest, report = _repo(tmp_path)
    policy_path = root / "config" / "maturity_proof_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["rules"] = [
        rule
        for rule in policy["rules"]
        if rule["proof_kind"] != ProofKind.INDEPENDENT.value
    ]
    policy_path.write_text(
        json.dumps(policy, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    _git(root, "add", "config/maturity_proof_policy.json")
    _git(root, "commit", "-qm", "remove independent rule")
    revision2 = _git(root, "rev-parse", "HEAD")
    receipt = _write_receipt(tmp_path, revision2, manifest, report)
    with pytest.raises(ValueError, match="independent_validation attestation"):
        attest_triple_implementation_proofs(
            repo_root=root,
            execution_receipt_path=receipt,
            ledger_path=tmp_path / "proofs.jsonl",
            integrity_key=KEY,
            now=NOW,
        )
