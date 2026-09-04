import copy
import hashlib
import json
import subprocess

import pytest

from research_engine.adversarial_independence_attestor import (
    ExternalValidatorSpec,
    IndependenceChallenge,
    attest_adversarial_independence,
    build_adversarial_independence_execution_receipt,
    validate_adversarial_independence_receipt,
)
from research_engine.capability_registry import ProofKind
from research_engine.maturity_proof import ProofLedger


KEY = b"I" * 32
NOW = 50_000.0


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


def _repo(tmp_path, *, verifier="trusted-independent-validator", prefix="independent:"):
    root = tmp_path / "repo"
    (root / "research_engine").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "research_engine" / "adversarial_science.py").write_text(
        "ENGINE = 'red-team'\n", encoding="utf-8"
    )
    (root / "research_engine" / "scientist_society.py").write_text(
        "ENGINE = 'devils-advocate'\n", encoding="utf-8"
    )
    policy = {
        "schema_version": 1,
        "rules": [
            {
                "capability_id": capability_id,
                "proof_kind": "independent_validation",
                "subjects": [f"capability-{capability_id}-independent-validation"],
                "verifiers": [verifier],
                "reference_prefixes": [prefix],
            }
            for capability_id in (36, 37)
        ],
    }
    (root / "config" / "maturity_proof_policy.json").write_text(
        json.dumps(policy, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "independence@example.invalid")
    _git(root, "config", "user.name", "Independence Tests")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    return root, _git(root, "rev-parse", "HEAD")


def _challenges():
    return (
        IndependenceChallenge(
            capability_id=36,
            challenge_id="RT1",
            statement="The registered mechanism explains the locked observation.",
            evidence_ids=("E1", "E2"),
            dimensions=("COUNTEREXAMPLE", "ASSUMPTION_BREAK", "CONFOUNDER"),
        ),
        IndependenceChallenge(
            capability_id=37,
            challenge_id="DA1",
            statement="The candidate interpretation is the best available explanation.",
            evidence_ids=("E1", "E2"),
            dimensions=("ALTERNATIVE_MECHANISM", "MEASUREMENT_STRESS", "OOD_STRESS"),
        ),
    )


def _result(packet, *, variant=0):
    capability_id = int(packet["capability_id"])
    tested = list(packet["dimensions"][:2])
    if capability_id == 36:
        status = "FALSIFIED" if variant != 2 else "NOT_FALSIFIED"
    else:
        status = "MATERIAL_OBJECTION" if variant != 2 else "NO_MATERIAL_OBJECTION"
    return {
        "status": status,
        "tested_dimensions": tested,
        "findings": [
            {
                "finding_id": f"F{variant + 1}",
                "dimension": tested[0],
                "statement": "Independent validator completed the frozen adversarial check.",
                "evidence_ids": [packet["evidence_ids"][0]],
            }
        ],
    }


def _validators(seen=None):
    seen = seen if seen is not None else []
    rows = []
    for index in range(3):
        def validator(packet, variant=index):
            seen.append(copy.deepcopy(packet))
            return _result(packet, variant=variant)

        rows.append(
            ExternalValidatorSpec(
                validator_id=f"validator-{index}",
                runner_id=f"runner-{index}",
                model_family=f"family-{index}",
                independence_domain=f"domain-{index}",
                implementation_sha256=hashlib.sha256(
                    f"implementation-{index}".encode("utf-8")
                ).hexdigest(),
                validator=validator,
            )
        )
    return tuple(rows)


def _write_receipt(tmp_path, payload, name="receipt.json"):
    path = tmp_path / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return path


def _build(tmp_path, root, *, created=int(NOW), validators=None):
    payload = build_adversarial_independence_execution_receipt(
        repo_root=root,
        challenges=_challenges(),
        validators=validators or _validators(),
        created_at_epoch=created,
        repetitions=2,
    )
    return payload, _write_receipt(tmp_path, payload)


def test_valid_external_receipt_allows_disagreement_and_mints_independence_only(tmp_path):
    root, revision = _repo(tmp_path)
    seen = []
    payload, receipt = _build(tmp_path, root, validators=_validators(seen))

    # Three validators x two challenges x two repetitions.
    assert len(payload["runs"]) == 12
    red_statuses = {
        row["result"]["status"] for row in payload["runs"]
        if row["capability_id"] == 36
    }
    devil_statuses = {
        row["result"]["status"] for row in payload["runs"]
        if row["capability_id"] == 37
    }
    assert red_statuses == {"FALSIFIED", "NOT_FALSIFIED"}
    assert devil_statuses == {"MATERIAL_OBJECTION", "NO_MATERIAL_OBJECTION"}
    assert payload["validator_agreement_required"] is False
    assert payload["truth_proven"] is False

    forbidden = {
        "author", "author_id", "author_agent_id", "author_commitment",
        "expected", "expected_result", "expected_outcome", "champion",
        "champion_id", "ground_truth", "correct_answer",
    }
    assert seen
    for packet in seen:
        assert not (set(packet) & forbidden)

    ledger_path = tmp_path / "ledger.jsonl"
    result = attest_adversarial_independence(
        repo_root=root,
        execution_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="campaign-1",
        now=NOW,
    )
    assert result.revision == revision
    assert result.receipts_added == 2
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.hidden_provider_dependencies_ruled_out is False
    assert result.external_implementation_bytes_verified is False
    assert result.truth_proven is False

    for capability_id in (36, 37):
        capability = result.audit.maturity_report.results[capability_id - 1]
        assert ProofKind.INDEPENDENT not in capability.missing_proofs

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
    ]
    assert len(rows) == 2
    assert {row["capability_id"] for row in rows} == {36, 37}
    assert {row["proof_kind"] for row in rows} == {ProofKind.INDEPENDENT.value}
    assert ProofKind.EXECUTION.value not in {row["proof_kind"] for row in rows}
    assert ProofKind.REPRODUCIBILITY.value not in {row["proof_kind"] for row in rows}
    assert ProofKind.SAFETY.value not in {row["proof_kind"] for row in rows}
    assert ProofKind.LIVE.value not in {row["proof_kind"] for row in rows}
    assert ProofKind.HARDWARE.value not in {row["proof_kind"] for row in rows}


@pytest.mark.parametrize(
    "field",
    ["runner_id", "model_family", "independence_domain", "implementation_sha256"],
)
def test_duplicate_validator_independence_dimensions_fail_closed(tmp_path, field):
    root, _revision = _repo(tmp_path)
    validators = list(_validators())
    first = validators[0]
    second = validators[1]
    values = {
        "validator_id": second.validator_id,
        "runner_id": second.runner_id,
        "model_family": second.model_family,
        "independence_domain": second.independence_domain,
        "implementation_sha256": second.implementation_sha256,
        "validator": second.validator,
    }
    values[field] = getattr(first, field)
    validators[1] = ExternalValidatorSpec(**values)
    with pytest.raises(ValueError, match=f"distinct {field}"):
        build_adversarial_independence_execution_receipt(
            repo_root=root,
            challenges=_challenges(),
            validators=validators,
            created_at_epoch=int(NOW),
            repetitions=2,
        )


def test_duplicate_validator_id_fails_closed(tmp_path):
    root, _revision = _repo(tmp_path)
    validators = list(_validators())
    second = validators[1]
    validators[1] = ExternalValidatorSpec(
        validator_id=validators[0].validator_id,
        runner_id=second.runner_id,
        model_family=second.model_family,
        independence_domain=second.independence_domain,
        implementation_sha256=second.implementation_sha256,
        validator=second.validator,
    )
    with pytest.raises(ValueError, match="distinct validator_id"):
        build_adversarial_independence_execution_receipt(
            repo_root=root,
            challenges=_challenges(),
            validators=validators,
            created_at_epoch=int(NOW),
            repetitions=2,
        )


def test_validator_cannot_cite_evidence_outside_frozen_packet(tmp_path):
    root, _revision = _repo(tmp_path)
    validators = list(_validators())

    def bad(packet):
        raw = _result(packet)
        raw["findings"][0]["evidence_ids"] = ["UNSEEN"]
        return raw

    first = validators[0]
    validators[0] = ExternalValidatorSpec(
        validator_id=first.validator_id,
        runner_id=first.runner_id,
        model_family=first.model_family,
        independence_domain=first.independence_domain,
        implementation_sha256=first.implementation_sha256,
        validator=bad,
    )
    with pytest.raises(ValueError, match="outside the frozen challenge"):
        build_adversarial_independence_execution_receipt(
            repo_root=root,
            challenges=_challenges(),
            validators=validators,
            created_at_epoch=int(NOW),
            repetitions=2,
        )


def test_stale_receipt_is_rejected(tmp_path):
    root, _revision = _repo(tmp_path)
    _payload, receipt = _build(tmp_path, root, created=int(NOW - 3 * 60 * 60))
    with pytest.raises(ValueError, match="stale"):
        validate_adversarial_independence_receipt(receipt, repo_root=root, now=NOW)


def test_tampered_report_is_rejected(tmp_path):
    root, _revision = _repo(tmp_path)
    payload, _receipt = _build(tmp_path, root)
    payload["runs"][0]["result"]["findings"][0]["statement"] = "tampered finding"
    tampered = _write_receipt(tmp_path, payload, "tampered.json")
    with pytest.raises(ValueError, match="hash|run_sha256|report_hash"):
        validate_adversarial_independence_receipt(tampered, repo_root=root, now=NOW)


def test_wrong_git_revision_invalidates_old_receipt(tmp_path):
    root, revision_a = _repo(tmp_path)
    _payload, receipt = _build(tmp_path, root)
    (root / "research_engine" / "adversarial_science.py").write_text(
        "ENGINE = 'red-team-v2'\n", encoding="utf-8"
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "revision B")
    assert _git(root, "rev-parse", "HEAD") != revision_a
    with pytest.raises(ValueError, match="revision mismatch"):
        validate_adversarial_independence_receipt(receipt, repo_root=root, now=NOW)


def test_wrong_policy_verifier_fails_before_ledger_mutation(tmp_path):
    root, _revision = _repo(tmp_path, verifier="wrong-validator")
    _payload, receipt = _build(tmp_path, root)
    ledger_path = tmp_path / "ledger.jsonl"
    with pytest.raises(ValueError, match="no trusted c36 independent route"):
        attest_adversarial_independence(
            repo_root=root,
            execution_receipt_path=receipt,
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="campaign-2",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_wrong_policy_reference_prefix_fails_before_ledger_mutation(tmp_path):
    root, _revision = _repo(tmp_path, prefix="different:")
    _payload, receipt = _build(tmp_path, root)
    ledger_path = tmp_path / "ledger.jsonl"
    with pytest.raises(ValueError, match="reference is not allowed"):
        attest_adversarial_independence(
            repo_root=root,
            execution_receipt_path=receipt,
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="campaign-3",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_existing_ledger_requires_prior_anchor_and_reuses_same_receipts(tmp_path):
    root, revision = _repo(tmp_path)
    _payload, receipt = _build(tmp_path, root)
    ledger_path = tmp_path / "ledger.jsonl"
    first = attest_adversarial_independence(
        repo_root=root,
        execution_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="campaign-4",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_adversarial_independence(
            repo_root=root,
            execution_receipt_path=receipt,
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="campaign-4",
            now=NOW + 1,
        )
    second = attest_adversarial_independence(
        repo_root=root,
        execution_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="campaign-4",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 2
    assert second.audit.audit_valid is True


def test_receipt_refuses_truth_and_hidden_dependency_upgrades(tmp_path):
    root, _revision = _repo(tmp_path)
    payload, _receipt = _build(tmp_path, root)
    for field in (
        "truth_proven",
        "hidden_provider_dependencies_ruled_out",
        "external_implementation_bytes_verified",
        "agreement_proves_truth",
    ):
        modified = copy.deepcopy(payload)
        modified[field] = True
        body = {key: value for key, value in modified.items() if key != "report_hash"}
        modified["report_hash"] = hashlib.sha256(
            json.dumps(
                body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        path = _write_receipt(tmp_path, modified, f"{field}.json")
        with pytest.raises(ValueError):
            validate_adversarial_independence_receipt(path, repo_root=root, now=NOW)
