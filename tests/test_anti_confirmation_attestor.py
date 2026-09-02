import hashlib
import json
import subprocess

import pytest

from research_engine.anti_confirmation_attestor import (
    attest_anti_confirmation_independence,
    validate_anti_confirmation_campaign,
)
from research_engine.capability_registry import ProofKind
from research_engine.maturity_proof import ProofLedger


KEY = b"A" * 32
NOW = 50_000.0


def _sha(value):
    if not isinstance(value, (bytes, bytearray)):
        value = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    return hashlib.sha256(bytes(value)).hexdigest()


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
                "capability_id": 140,
                "proof_kind": ProofKind.INDEPENDENT.value,
                "subjects": ["anti-confirmation-campaign"],
                "verifiers": ["anti-confirmation-independent-validator"],
                "reference_prefixes": ["anti-confirmation:"],
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


def _identity(prefix):
    return {
        "team_id": f"{prefix}-team",
        "runner_id": f"{prefix}-runner",
        "model_id": f"{prefix}-model",
        "implementation_digest": _sha(f"{prefix}-implementation".encode()),
    }


def _campaign(revision, *, created=49_900):
    validator = _identity("validator")
    payload = {
        "schema_version": 1,
        "created_at_epoch": created,
        "implementation_revision": revision,
        "campaign_id": "campaign-001",
        "hypothesis_id": "H1",
        "hypothesis_hash": _sha(b"hypothesis"),
        "protocol_hash": _sha(b"protocol"),
        "search_space_hash": _sha(b"search-space"),
        "stopping_rule_hash": _sha(b"stopping-rule"),
        "originator": _identity("originator"),
        "independent_validator": validator,
        "falsification_criteria": [
            {"criterion_id": "C1", "description_hash": _sha(b"criterion-1")},
            {"criterion_id": "C2", "description_hash": _sha(b"criterion-2")},
        ],
        "tests": [
            {
                "test_id": "T1",
                "criterion_id": "C1",
                "method_hash": _sha(b"method-1"),
                "evidence_hash": _sha(b"evidence-1"),
                "targets_falsification": True,
                "outcome": "supporting",
                "performed_by_team_id": validator["team_id"],
                "performed_by_runner_id": validator["runner_id"],
            },
            {
                "test_id": "T2",
                "criterion_id": "C2",
                "method_hash": _sha(b"method-2"),
                "evidence_hash": _sha(b"evidence-2"),
                "targets_falsification": True,
                "outcome": "inconclusive",
                "performed_by_team_id": validator["team_id"],
                "performed_by_runner_id": validator["runner_id"],
            },
            {
                "test_id": "T3",
                "criterion_id": "C1",
                "method_hash": _sha(b"method-3"),
                "evidence_hash": _sha(b"evidence-3"),
                "targets_falsification": True,
                "outcome": "null",
                "performed_by_team_id": validator["team_id"],
                "performed_by_runner_id": validator["runner_id"],
            },
        ],
        "negative_evidence_search_completed": True,
        "null_results_recorded": True,
        "conclusion": "survived",
        "truth_proven": False,
    }
    payload["campaign_hash"] = _sha(payload)
    return payload


def _write(tmp_path, value, name="campaign.json"):
    path = tmp_path / name
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def _rehash(value):
    value = dict(value)
    value.pop("campaign_hash", None)
    value["campaign_hash"] = _sha(value)
    return value


def test_valid_independent_falsification_campaign_mints_only_independent(tmp_path):
    root, revision = _repo(tmp_path)
    campaign = _write(tmp_path, _campaign(revision))
    ledger_path = tmp_path / "proofs.jsonl"
    result = attest_anti_confirmation_independence(
        repo_root=root,
        campaign_path=campaign,
        ledger_path=ledger_path,
        integrity_key=KEY,
        now=NOW,
    )
    assert result.revision == revision
    assert result.receipts_added == 1
    assert result.receipts_reused == 0
    assert result.truth_proven is False
    assert result.audit.audit_valid is True

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
    ]
    assert len(rows) == 1
    assert rows[0]["capability_id"] == 140
    assert rows[0]["proof_kind"] == ProofKind.INDEPENDENT.value
    assert rows[0]["subject"] == "anti-confirmation-campaign"
    assert rows[0]["verifier"] == "anti-confirmation-independent-validator"
    assert rows[0]["reference"].startswith("anti-confirmation:")


def test_all_supporting_outcomes_are_allowed_when_tests_genuinely_target_falsification(tmp_path):
    root, revision = _repo(tmp_path)
    value = _campaign(revision)
    for row in value["tests"]:
        row["outcome"] = "supporting"
    value = _rehash(value)
    receipt = validate_anti_confirmation_campaign(
        _write(tmp_path, value), expected_revision=revision, now=NOW
    )
    assert receipt.conclusion == "survived"
    assert receipt.test_count == 3


def test_self_validation_is_rejected(tmp_path):
    root, revision = _repo(tmp_path)
    value = _campaign(revision)
    value["independent_validator"]["team_id"] = value["originator"]["team_id"]
    value = _rehash(value)
    with pytest.raises(ValueError, match="distinct team_id"):
        validate_anti_confirmation_campaign(
            _write(tmp_path, value), expected_revision=revision, now=NOW
        )


def test_non_falsifying_attempt_is_rejected(tmp_path):
    root, revision = _repo(tmp_path)
    value = _campaign(revision)
    value["tests"][0]["targets_falsification"] = False
    value = _rehash(value)
    with pytest.raises(ValueError, match="target falsification"):
        validate_anti_confirmation_campaign(
            _write(tmp_path, value), expected_revision=revision, now=NOW
        )


def test_insufficient_criterion_coverage_is_rejected(tmp_path):
    root, revision = _repo(tmp_path)
    value = _campaign(revision)
    for row in value["tests"]:
        row["criterion_id"] = "C1"
    value = _rehash(value)
    with pytest.raises(ValueError, match="cover at least two"):
        validate_anti_confirmation_campaign(
            _write(tmp_path, value), expected_revision=revision, now=NOW
        )


def test_duplicate_evidence_cannot_be_counted_as_multiple_attempts(tmp_path):
    root, revision = _repo(tmp_path)
    value = _campaign(revision)
    value["tests"][1]["evidence_hash"] = value["tests"][0]["evidence_hash"]
    value = _rehash(value)
    with pytest.raises(ValueError, match="evidence_hash must be unique"):
        validate_anti_confirmation_campaign(
            _write(tmp_path, value), expected_revision=revision, now=NOW
        )


def test_truth_proven_claim_is_rejected(tmp_path):
    root, revision = _repo(tmp_path)
    value = _campaign(revision)
    value["truth_proven"] = True
    value = _rehash(value)
    with pytest.raises(ValueError, match="must not claim truth_proven"):
        validate_anti_confirmation_campaign(
            _write(tmp_path, value), expected_revision=revision, now=NOW
        )


def test_wrong_revision_and_stale_campaign_fail_closed(tmp_path):
    root, revision = _repo(tmp_path)
    wrong = _campaign("f" * 40)
    with pytest.raises(ValueError, match="revision does not match"):
        validate_anti_confirmation_campaign(
            _write(tmp_path, wrong, "wrong.json"), expected_revision=revision, now=NOW
        )
    stale = _campaign(revision, created=1)
    with pytest.raises(ValueError, match="stale"):
        validate_anti_confirmation_campaign(
            _write(tmp_path, stale, "stale.json"), expected_revision=revision, now=NOW
        )


def test_campaign_hash_tamper_is_rejected(tmp_path):
    root, revision = _repo(tmp_path)
    value = _campaign(revision)
    value["conclusion"] = "falsified"
    with pytest.raises(ValueError, match="campaign_hash verification failed"):
        validate_anti_confirmation_campaign(
            _write(tmp_path, value), expected_revision=revision, now=NOW
        )


def test_existing_ledger_requires_retained_anchor_and_is_idempotent(tmp_path):
    root, revision = _repo(tmp_path)
    campaign = _write(tmp_path, _campaign(revision))
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_anti_confirmation_independence(
        repo_root=root,
        campaign_path=campaign,
        ledger_path=ledger_path,
        integrity_key=KEY,
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_anti_confirmation_independence(
            repo_root=root,
            campaign_path=campaign,
            ledger_path=ledger_path,
            integrity_key=KEY,
            now=NOW + 1,
        )
    second = attest_anti_confirmation_independence(
        repo_root=root,
        campaign_path=campaign,
        ledger_path=ledger_path,
        integrity_key=KEY,
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 1


def test_dirty_repo_and_in_repo_ledger_are_rejected(tmp_path):
    root, revision = _repo(tmp_path)
    campaign = _write(tmp_path, _campaign(revision))
    with pytest.raises(ValueError, match="ledger must live outside"):
        attest_anti_confirmation_independence(
            repo_root=root,
            campaign_path=campaign,
            ledger_path=root / "ledger.jsonl",
            integrity_key=KEY,
            now=NOW,
        )

    (root / "dirty.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(ValueError, match="clean Git checkout"):
        attest_anti_confirmation_independence(
            repo_root=root,
            campaign_path=campaign,
            ledger_path=tmp_path / "outside.jsonl",
            integrity_key=KEY,
            now=NOW,
        )
