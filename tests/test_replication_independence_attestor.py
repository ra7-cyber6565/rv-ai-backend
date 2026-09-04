import copy
import hashlib
import json
import subprocess

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.maturity_proof import ProofLedger
from research_engine.replication_independence_attestor import (
    ExternalReplicationGroup,
    attest_replication_independence,
    build_replication_independence_execution_receipt,
    validate_replication_independence_receipt,
)


KEY = b"R" * 32
NOW = 80_000.0


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


def _repo(tmp_path, *, verifier="trusted-independent-validator"):
    root = tmp_path / "repo"
    (root / "research_engine").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "research_engine" / "scientist_society.py").write_text(
        "REPLICATION_ENGINE = True\n", encoding="utf-8"
    )
    policy = {
        "schema_version": 1,
        "rules": [
            {
                "capability_id": 39,
                "proof_kind": "independent_validation",
                "subjects": ["capability-39-independent-validation"],
                "verifiers": [verifier],
                "reference_prefixes": ["independent:"],
            }
        ],
    }
    (root / "config" / "maturity_proof_policy.json").write_text(
        json.dumps(policy, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "replication@example.invalid")
    _git(root, "config", "user.name", "Replication Tests")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    return root, _git(root, "rev-parse", "HEAD")


def _protocol():
    return {
        "protocol_id": "P1",
        "dataset_commitment": hashlib.sha256(b"locked-dataset").hexdigest(),
        "procedure": ["load locked sample", "compute metric", "report evidence ids"],
    }


def _groups(seen=None):
    seen = seen if seen is not None else []
    rows = []
    for index in range(3):
        def runner(packet, variant=index):
            seen.append(copy.deepcopy(packet))
            # Deliberate disagreement is allowed: independence is a structural
            # proof, not a consensus/truth proof.
            return {
                "metrics": {"effect": 1.0 + (variant * 0.2)},
                "evidence_ids": [f"E{variant + 1}"],
                "notes": f"external group {variant} completed the frozen protocol",
            }

        rows.append(
            ExternalReplicationGroup(
                group_id=f"group-{index}",
                runner_id=f"runner-{index}",
                model_family=f"family-{index}",
                operator_domain=f"operator-domain-{index}",
                implementation_sha256=hashlib.sha256(
                    f"external-implementation-{index}".encode("utf-8")
                ).hexdigest(),
                runner=runner,
            )
        )
    return tuple(rows)


def _write(tmp_path, payload, name="receipt.json"):
    path = tmp_path / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return path


def _build(tmp_path, root, *, created=int(NOW), groups=None):
    payload = build_replication_independence_execution_receipt(
        repo_root=root,
        frozen_protocol=_protocol(),
        groups=groups or _groups(),
        created_at_epoch=created,
        repetitions=2,
    )
    return payload, _write(tmp_path, payload)


def test_valid_external_campaign_allows_disagreement_and_mints_independence_only(tmp_path):
    root, revision = _repo(tmp_path)
    seen = []
    payload, receipt = _build(tmp_path, root, groups=_groups(seen))
    assert len(payload["runs"]) == 6
    assert payload["independence_structure_satisfied"] is True
    assert payload["agreement_required"] is False
    assert payload["replication_success_proven"] is False
    assert payload["truth_proven"] is False
    assert len({row["metrics"]["effect"] for row in payload["runs"]}) == 3
    assert seen
    forbidden = {"author", "expected", "expected_result", "champion", "ground_truth"}
    assert all(not (set(packet) & forbidden) for packet in seen)

    ledger_path = tmp_path / "ledger.jsonl"
    result = attest_replication_independence(
        repo_root=root,
        execution_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="campaign-1",
        now=NOW,
    )
    assert result.revision == revision
    assert result.receipts_added == 1
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.external_implementation_bytes_verified is False
    assert result.hidden_provider_dependencies_ruled_out is False
    assert result.replication_success_proven is False
    assert result.truth_proven is False

    capability = result.audit.maturity_report.results[38]
    assert ProofKind.INDEPENDENT not in capability.missing_proofs
    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
    ]
    assert len(rows) == 1
    assert rows[0]["capability_id"] == 39
    assert rows[0]["proof_kind"] == ProofKind.INDEPENDENT.value
    assert rows[0]["verifier"] == "trusted-independent-validator"
    assert ProofKind.EXECUTION.value not in {row["proof_kind"] for row in rows}
    assert ProofKind.REPRODUCIBILITY.value not in {row["proof_kind"] for row in rows}


@pytest.mark.parametrize(
    "field",
    ["group_id", "runner_id", "model_family", "operator_domain", "implementation_sha256"],
)
def test_duplicate_independence_dimensions_fail_closed(tmp_path, field):
    root, _ = _repo(tmp_path)
    groups = list(_groups())
    first = groups[0]
    second = groups[1]
    values = {
        "group_id": second.group_id,
        "runner_id": second.runner_id,
        "model_family": second.model_family,
        "operator_domain": second.operator_domain,
        "implementation_sha256": second.implementation_sha256,
        "runner": second.runner,
    }
    values[field] = getattr(first, field)
    groups[1] = ExternalReplicationGroup(**values)
    with pytest.raises(ValueError, match=f"distinct {field}"):
        build_replication_independence_execution_receipt(
            repo_root=root,
            frozen_protocol=_protocol(),
            groups=groups,
            created_at_epoch=int(NOW),
            repetitions=2,
        )


def test_protocol_expected_result_leakage_fails_before_any_runner_call(tmp_path):
    root, _ = _repo(tmp_path)
    seen = []
    protocol = _protocol()
    protocol["expected_result"] = "winning answer"
    with pytest.raises(ValueError, match="leaked blinded metadata"):
        build_replication_independence_execution_receipt(
            repo_root=root,
            frozen_protocol=protocol,
            groups=_groups(seen),
            created_at_epoch=int(NOW),
            repetitions=2,
        )
    assert seen == []


def test_nonfinite_metric_fails_closed(tmp_path):
    root, _ = _repo(tmp_path)
    groups = list(_groups())
    bad = groups[0]

    def runner(_packet):
        return {"metrics": {"effect": float("nan")}, "evidence_ids": ["E1"], "notes": "bad metric"}

    groups[0] = ExternalReplicationGroup(
        group_id=bad.group_id,
        runner_id=bad.runner_id,
        model_family=bad.model_family,
        operator_domain=bad.operator_domain,
        implementation_sha256=bad.implementation_sha256,
        runner=runner,
    )
    with pytest.raises(ValueError, match="must be finite"):
        build_replication_independence_execution_receipt(
            repo_root=root,
            frozen_protocol=_protocol(),
            groups=groups,
            created_at_epoch=int(NOW),
            repetitions=2,
        )


def test_result_tamper_and_boundary_upgrade_are_rejected(tmp_path):
    root, revision = _repo(tmp_path)
    payload, _receipt = _build(tmp_path, root)
    tampered = copy.deepcopy(payload)
    tampered["runs"][0]["metrics"]["effect"] = 999.0
    path = _write(tmp_path, tampered, "tampered.json")
    with pytest.raises(ValueError, match="result_hash mismatch"):
        validate_replication_independence_receipt(
            path, repo_root=root, expected_revision=revision, now=NOW
        )

    dishonest = copy.deepcopy(payload)
    dishonest["truth_proven"] = True
    path = _write(tmp_path, dishonest, "dishonest.json")
    with pytest.raises(ValueError, match="boundary truth_proven"):
        validate_replication_independence_receipt(
            path, repo_root=root, expected_revision=revision, now=NOW
        )


def test_stale_and_wrong_revision_receipts_fail_closed(tmp_path):
    root, revision = _repo(tmp_path)
    stale_payload, stale = _build(tmp_path, root, created=1)
    assert stale_payload["implementation_revision"] == revision
    with pytest.raises(ValueError, match="stale"):
        validate_replication_independence_receipt(
            stale, repo_root=root, expected_revision=revision, now=NOW
        )

    payload, receipt = _build(tmp_path, root)
    assert payload["implementation_revision"] == revision
    with pytest.raises(ValueError, match="revision mismatch"):
        validate_replication_independence_receipt(
            receipt,
            repo_root=root,
            expected_revision="0" * 40,
            now=NOW,
        )


def test_existing_ledger_requires_anchor_and_same_campaign_is_idempotent(tmp_path):
    root, revision = _repo(tmp_path)
    _payload, receipt = _build(tmp_path, root)
    ledger_path = tmp_path / "ledger.jsonl"
    first = attest_replication_independence(
        repo_root=root,
        execution_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="campaign-2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_replication_independence(
            repo_root=root,
            execution_receipt_path=receipt,
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="campaign-2",
            now=NOW + 1,
        )
    second = attest_replication_independence(
        repo_root=root,
        execution_receipt_path=receipt,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="campaign-2",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 1


def test_wrong_policy_verifier_and_inside_repo_ledger_fail_closed(tmp_path):
    root, _ = _repo(tmp_path, verifier="wrong-validator")
    _payload, receipt = _build(tmp_path, root)
    with pytest.raises(ValueError, match="does not match trusted contract"):
        attest_replication_independence(
            repo_root=root,
            execution_receipt_path=receipt,
            ledger_path=tmp_path / "ledger.jsonl",
            integrity_key=KEY,
            observation_id="campaign-3",
            now=NOW,
        )

    root2, _ = _repo(tmp_path / "second")
    _payload2, receipt2 = _build(tmp_path / "second", root2)
    inside = root2 / ".replication-independence-ledger.jsonl"
    with pytest.raises(ValueError, match="outside"):
        attest_replication_independence(
            repo_root=root2,
            execution_receipt_path=receipt2,
            ledger_path=inside,
            integrity_key=KEY,
            observation_id="campaign-4",
            now=NOW,
        )
    assert not inside.exists()
