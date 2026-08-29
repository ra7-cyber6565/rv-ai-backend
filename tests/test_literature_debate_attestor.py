import hashlib
import json
import subprocess

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.literature_debate_attestor import (
    attest_literature_debate_independent_validation,
    validate_literature_debate_validation_receipt,
)
from research_engine.maturity_proof import ProofLedger


KEY = b"L" * 32
NOW = 50_000.0
SUBJECT = "literature-debate-independent-validation"
ENGINE = "research_engine/literature_debate.py"
WIRING = "research_engine/literature_debate_wiring.py"


def _canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha(value):
    if isinstance(value, bytes):
        data = value
    else:
        data = _canonical(value)
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


def _repo(tmp_path):
    root = tmp_path / "repo"
    (root / "research_engine").mkdir(parents=True)
    (root / "config").mkdir()
    (root / ENGINE).write_text("ENGINE = 'debate-v1'\n", encoding="utf-8")
    (root / WIRING).write_text("WIRING = 'debate-v1'\n", encoding="utf-8")
    policy = {
        "schema_version": 1,
        "rules": [
            {
                "capability_id": 103,
                "proof_kind": ProofKind.INDEPENDENT.value,
                "subjects": [SUBJECT],
                "verifiers": ["trusted-operator"],
                "reference_prefixes": ["literature-debate:"],
            }
        ],
    }
    (root / "config" / "maturity_proof_policy.json").write_text(
        json.dumps(policy, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    return root, _git(root, "rev-parse", "HEAD")


def _file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validator(validator_id, family, artifact, case_manifest, total):
    payload = {
        "validator_id": validator_id,
        "validator_family": family,
        "validator_artifact_sha256": artifact,
        "case_manifest_sha256": case_manifest,
        "passed_cases": total,
        "total_cases": total,
        "decision": "PASS",
    }
    return {**payload, "result_sha256": _sha(payload)}


def _receipt_value(root, revision, *, created=49_900, total=17):
    case_manifest = _sha({"suite": "lit-debate-independent-v1", "cases": total})
    validators = [
        _validator("validator-a", "symbolic-python", "a" * 64, case_manifest, total),
        _validator("validator-b", "rules-rust", "b" * 64, case_manifest, total),
    ]
    payload = {
        "schema_version": 1,
        "created_at_epoch": created,
        "implementation_revision": revision,
        "implementation_subjects": {
            ENGINE: _file_sha(root / ENGINE),
            WIRING: _file_sha(root / WIRING),
        },
        "case_manifest_sha256": case_manifest,
        "total_cases": total,
        "validators": validators,
        "independent_validation_passed": True,
        "truth_proven": False,
        "consensus_proves_truth": False,
    }
    return {**payload, "validation_sha256": _sha(payload)}


def _recompute_validator(row):
    payload = {key: value for key, value in row.items() if key != "result_sha256"}
    row["result_sha256"] = _sha(payload)


def _recompute_receipt(value):
    payload = {key: val for key, val in value.items() if key != "validation_sha256"}
    value["validation_sha256"] = _sha(payload)


def _write(tmp_path, value, name="validation.json"):
    path = tmp_path / name
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def test_two_distinct_external_validators_mint_only_independent_proof(tmp_path):
    root, revision = _repo(tmp_path)
    receipt = _write(tmp_path, _receipt_value(root, revision))
    ledger_path = tmp_path / "proofs.jsonl"

    result = attest_literature_debate_independent_validation(
        repo_root=root,
        validation_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="literature-debate:validation:100",
        now=NOW,
    )

    assert result.revision == revision
    assert result.validator_count == 2
    assert result.total_cases == 17
    assert result.receipts_added == 1
    assert result.audit.audit_valid is True
    assert result.truth_proven is False
    assert result.consensus_proves_truth is False

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [row for row in ledger._events() if row.get("event_type") == "ADD"]  # noqa: SLF001
    assert len(rows) == 1
    assert rows[0]["capability_id"] == 103
    assert rows[0]["proof_kind"] == ProofKind.INDEPENDENT.value
    assert rows[0]["subject"] == SUBJECT
    assert rows[0]["verifier"] == "trusted-operator"
    assert rows[0]["implementation_revision"] == revision


def test_duplicate_validator_family_fails_closed(tmp_path):
    root, revision = _repo(tmp_path)
    value = _receipt_value(root, revision)
    value["validators"][1]["validator_family"] = value["validators"][0]["validator_family"]
    _recompute_validator(value["validators"][1])
    _recompute_receipt(value)
    path = _write(tmp_path, value)
    with pytest.raises(ValueError, match="identities, families, and artifacts"):
        validate_literature_debate_validation_receipt(
            path, repo_root=root, expected_revision=revision, now=NOW
        )


def test_same_validator_artifact_under_different_name_fails_closed(tmp_path):
    root, revision = _repo(tmp_path)
    value = _receipt_value(root, revision)
    value["validators"][1]["validator_artifact_sha256"] = value["validators"][0]["validator_artifact_sha256"]
    _recompute_validator(value["validators"][1])
    _recompute_receipt(value)
    path = _write(tmp_path, value)
    with pytest.raises(ValueError, match="identities, families, and artifacts"):
        validate_literature_debate_validation_receipt(
            path, repo_root=root, expected_revision=revision, now=NOW
        )


def test_partial_case_pass_cannot_claim_independent_validation(tmp_path):
    root, revision = _repo(tmp_path)
    value = _receipt_value(root, revision)
    value["validators"][1]["passed_cases"] -= 1
    _recompute_validator(value["validators"][1])
    _recompute_receipt(value)
    path = _write(tmp_path, value)
    with pytest.raises(ValueError, match="pass every frozen case"):
        validate_literature_debate_validation_receipt(
            path, repo_root=root, expected_revision=revision, now=NOW
        )


def test_mismatched_frozen_case_manifest_fails_closed(tmp_path):
    root, revision = _repo(tmp_path)
    value = _receipt_value(root, revision)
    value["validators"][1]["case_manifest_sha256"] = "c" * 64
    _recompute_validator(value["validators"][1])
    _recompute_receipt(value)
    path = _write(tmp_path, value)
    with pytest.raises(ValueError, match="same frozen case manifest"):
        validate_literature_debate_validation_receipt(
            path, repo_root=root, expected_revision=revision, now=NOW
        )


def test_tracked_engine_digest_is_derived_not_trusted(tmp_path):
    root, revision = _repo(tmp_path)
    value = _receipt_value(root, revision)
    value["implementation_subjects"][ENGINE] = "d" * 64
    _recompute_receipt(value)
    path = _write(tmp_path, value)
    with pytest.raises(ValueError, match="tracked digest mismatch"):
        validate_literature_debate_validation_receipt(
            path, repo_root=root, expected_revision=revision, now=NOW
        )


def test_stale_wrong_revision_and_truth_injection_fail_closed(tmp_path):
    root, revision = _repo(tmp_path)

    stale = _receipt_value(root, revision, created=1)
    with pytest.raises(ValueError, match="stale"):
        validate_literature_debate_validation_receipt(
            _write(tmp_path, stale, "stale.json"),
            repo_root=root,
            expected_revision=revision,
            now=NOW,
        )

    wrong = _receipt_value(root, "1" * 40)
    with pytest.raises(ValueError, match="revision mismatch"):
        validate_literature_debate_validation_receipt(
            _write(tmp_path, wrong, "wrong.json"),
            repo_root=root,
            expected_revision=revision,
            now=NOW,
        )

    truth = _receipt_value(root, revision)
    truth["truth_proven"] = True
    _recompute_receipt(truth)
    with pytest.raises(ValueError, match="must not claim truth_proven"):
        validate_literature_debate_validation_receipt(
            _write(tmp_path, truth, "truth.json"),
            repo_root=root,
            expected_revision=revision,
            now=NOW,
        )


def test_existing_ledger_requires_retained_anchor_and_reuses_exact_receipt(tmp_path):
    root, revision = _repo(tmp_path)
    receipt = _write(tmp_path, _receipt_value(root, revision))
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_literature_debate_independent_validation(
        repo_root=root,
        validation_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="literature-debate:validation:200",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_literature_debate_independent_validation(
            repo_root=root,
            validation_receipt_path=receipt,
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="literature-debate:validation:200",
            now=NOW + 1,
        )
    second = attest_literature_debate_independent_validation(
        repo_root=root,
        validation_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="literature-debate:validation:200",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 1


def test_wrong_reference_prefix_fails_before_ledger_mutation(tmp_path):
    root, revision = _repo(tmp_path)
    receipt = _write(tmp_path, _receipt_value(root, revision))
    ledger_path = tmp_path / "proofs.jsonl"
    with pytest.raises(ValueError, match="not a literature-debate trusted reference"):
        attest_literature_debate_independent_validation(
            repo_root=root,
            validation_receipt_path=receipt,
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="self-asserted:validation:1",
            now=NOW,
        )
    assert not ledger_path.exists()
