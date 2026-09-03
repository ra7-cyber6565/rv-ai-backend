import hashlib
import hmac
import json
import subprocess

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.maturity_proof import ProofLedger
from research_engine.post_deployment_attestor import (
    attest_post_deployment_proofs,
    validate_deployment_attestation,
)
from research_engine.post_deployment_integrity import verify_post_deployment_state
from research_engine.post_deployment_validation import (
    DriftPolicy,
    MetricRule,
    PostDeploymentValidator,
)


DEPLOYMENT_KEY = b"D" * 32
LEDGER_KEY = b"L" * 32
NOW = 10_000.0
SUBJECT = "post-deployment-live-validation"
VERIFIER = "trusted-deployment-observer"
PREFIX = "post-deployment:"


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


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _repo(tmp_path, *, omit=None):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "config").mkdir()
    route_map = {
        87: (ProofKind.PERSISTENCE, ProofKind.RUNTIME, ProofKind.LIVE),
        88: (
            ProofKind.EXECUTION,
            ProofKind.REPRODUCIBILITY,
            ProofKind.PERSISTENCE,
            ProofKind.RUNTIME,
            ProofKind.LIVE,
        ),
    }
    rules = []
    for capability_id, kinds in route_map.items():
        for kind in kinds:
            if omit == (capability_id, kind):
                continue
            rules.append({
                "capability_id": capability_id,
                "proof_kind": kind.value,
                "subjects": [SUBJECT],
                "verifiers": [VERIFIER],
                "reference_prefixes": [PREFIX],
            })
    (root / "config" / "maturity_proof_policy.json").write_text(
        json.dumps({"schema_version": 1, "rules": rules}, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    return root, _git(root, "rev-parse", "HEAD")


def _state(tmp_path, *, batches=3, outcomes=True):
    directory = tmp_path / "runtime-state"
    validator = PostDeploymentValidator(str(directory), project_id="live-project")
    validator.register_baseline(
        "model-v1",
        feature_kinds={"score": "numeric"},
        feature_samples={"score": [float(index) for index in range(40)]},
        observed_at_epoch=6000,
        policy=DriftPolicy(min_batch_samples=30, confirmation_windows=2, numeric_bins=5),
        metric_rules={
            "accuracy": MetricRule(
                baseline=0.80,
                direction="max",
                max_relative_degradation=0.10,
            )
        },
        implementation_hash="impl-v1",
        dataset_hash="dataset-v1",
    )
    for index in range(batches):
        validator.observe_batch(
            "model-v1",
            f"batch-{index + 1}",
            feature_samples={"score": [float(value) + index * 0.05 for value in range(40)]},
            observed_at_epoch=7000 + index * 500,
            observed_metrics={"accuracy": 0.80 + index * 0.001} if outcomes else None,
        )
    validator.save()
    return validator.path


def _receipt(tmp_path, revision, state_path, **overrides):
    verified = verify_post_deployment_state(state_path, expected_project_id="live-project")
    state = json.loads(open(state_path, "r", encoding="utf-8").read())
    rows = [
        row for row in state["batches"].values()
        if row["model_id"] == "model-v1"
    ]
    rows.sort(key=lambda row: (float(row["observed_at_epoch"]), str(row["batch_id"])))
    value = {
        "schema_version": 1,
        "created_at_epoch": 9900,
        "implementation_revision": revision,
        "project_id": "live-project",
        "model_id": "model-v1",
        "deployment_id": "prod-deployment-1",
        "runtime_instance_id": "runtime-1",
        "observer_id": "observer-1",
        "state_sha256": verified.state_sha256,
        "event_head_hash": verified.event_head_hash,
        "baseline_hash": state["baselines"]["model-v1"]["baseline_hash"],
        "batch_ids": [row["batch_id"] for row in rows],
        "batch_analysis_hashes": [row["analysis_hash"] for row in rows],
        "live_data_source_ids": ["production-stream-1"],
        "observation_window_start_epoch": 6900,
        "observation_window_end_epoch": 9000,
        "monitor_execution_observed": True,
        "persistent_state_reloaded": True,
        "runtime_observation_complete": True,
        "live_observation_complete": True,
        "replay_reproducibility_passed": True,
        "replay_run_ids": ["replay-a", "replay-b"],
        "replay_analysis_hashes": [row["analysis_hash"] for row in rows],
        "truth_proven": False,
    }
    value.update(overrides)
    signature = hmac.new(DEPLOYMENT_KEY, _canonical(value), hashlib.sha256).hexdigest()
    value["signature"] = signature
    path = tmp_path / f"deployment-{len(list(tmp_path.glob('deployment-*.json')))}.json"
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def test_valid_live_receipt_mints_only_exact_87_88_external_proofs(tmp_path):
    root, revision = _repo(tmp_path)
    state_path = _state(tmp_path)
    receipt_path = _receipt(tmp_path, revision, state_path)
    ledger_path = tmp_path / "ledger.jsonl"
    result = attest_post_deployment_proofs(
        repo_root=root,
        state_path=state_path,
        deployment_receipt_path=receipt_path,
        deployment_attestation_key=DEPLOYMENT_KEY,
        ledger_path=ledger_path,
        integrity_key=LEDGER_KEY,
        now=NOW,
    )
    assert result.revision == revision
    assert result.receipts_added == 8
    ledger = ProofLedger(str(ledger_path), integrity_key=LEDGER_KEY)
    rows = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
    ]
    by_capability = {}
    for row in rows:
        by_capability.setdefault(row["capability_id"], set()).add(row["proof_kind"])
        assert row["verifier"] == VERIFIER
        assert row["subject"] == SUBJECT
        assert row["implementation_revision"] == revision
    assert by_capability[87] == {
        ProofKind.PERSISTENCE.value,
        ProofKind.RUNTIME.value,
        ProofKind.LIVE.value,
    }
    assert by_capability[88] == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
        ProofKind.PERSISTENCE.value,
        ProofKind.RUNTIME.value,
        ProofKind.LIVE.value,
    }
    assert ProofKind.INDEPENDENT.value not in {row["proof_kind"] for row in rows}
    assert ProofKind.HARDWARE.value not in {row["proof_kind"] for row in rows}


def test_wrong_hmac_fails_before_ledger_mutation(tmp_path):
    root, revision = _repo(tmp_path)
    state_path = _state(tmp_path)
    receipt_path = _receipt(tmp_path, revision, state_path)
    ledger_path = tmp_path / "ledger.jsonl"
    with pytest.raises(ValueError, match="signature verification failed"):
        attest_post_deployment_proofs(
            repo_root=root,
            state_path=state_path,
            deployment_receipt_path=receipt_path,
            deployment_attestation_key=b"X" * 32,
            ledger_path=ledger_path,
            integrity_key=LEDGER_KEY,
            now=NOW,
        )
    assert not ledger_path.exists()


def test_persisted_state_tamper_is_rejected_even_with_preexisting_valid_signature(tmp_path):
    root, revision = _repo(tmp_path)
    state_path = _state(tmp_path)
    receipt_path = _receipt(tmp_path, revision, state_path)
    state = json.loads(open(state_path, "r", encoding="utf-8").read())
    state["model_state"]["model-v1"]["last_status"] = "DEGRADED"
    with open(state_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    with pytest.raises(ValueError, match="last_status mismatch"):
        validate_deployment_attestation(
            state_path=state_path,
            deployment_receipt_path=receipt_path,
            deployment_attestation_key=DEPLOYMENT_KEY,
            expected_revision=revision,
            now=NOW,
        )


def test_no_outcome_data_cannot_attest_continuous_validation(tmp_path):
    root, revision = _repo(tmp_path)
    state_path = _state(tmp_path, outcomes=False)
    receipt_path = _receipt(tmp_path, revision, state_path)
    with pytest.raises(ValueError, match="lacks enough outcome-bearing"):
        validate_deployment_attestation(
            state_path=state_path,
            deployment_receipt_path=receipt_path,
            deployment_attestation_key=DEPLOYMENT_KEY,
            expected_revision=revision,
            now=NOW,
        )


def test_less_than_three_live_batches_is_not_continuous_validation(tmp_path):
    root, revision = _repo(tmp_path)
    state_path = _state(tmp_path, batches=2)
    receipt_path = _receipt(tmp_path, revision, state_path)
    with pytest.raises(ValueError, match="batch_ids must be a bounded list"):
        validate_deployment_attestation(
            state_path=state_path,
            deployment_receipt_path=receipt_path,
            deployment_attestation_key=DEPLOYMENT_KEY,
            expected_revision=revision,
            now=NOW,
        )


def test_replay_hash_mismatch_cannot_claim_reproducibility(tmp_path):
    root, revision = _repo(tmp_path)
    state_path = _state(tmp_path)
    receipt_path = _receipt(
        tmp_path,
        revision,
        state_path,
        replay_analysis_hashes=["a" * 64, "b" * 64, "c" * 64],
    )
    with pytest.raises(ValueError, match="replay reproducibility"):
        validate_deployment_attestation(
            state_path=state_path,
            deployment_receipt_path=receipt_path,
            deployment_attestation_key=DEPLOYMENT_KEY,
            expected_revision=revision,
            now=NOW,
        )


@pytest.mark.parametrize(
    "field",
    [
        "monitor_execution_observed",
        "persistent_state_reloaded",
        "runtime_observation_complete",
        "live_observation_complete",
        "replay_reproducibility_passed",
    ],
)
def test_each_required_runtime_gate_must_be_true(tmp_path, field):
    root, revision = _repo(tmp_path)
    state_path = _state(tmp_path)
    receipt_path = _receipt(tmp_path, revision, state_path, **{field: False})
    with pytest.raises(ValueError, match="did not pass all required runtime gates"):
        validate_deployment_attestation(
            state_path=state_path,
            deployment_receipt_path=receipt_path,
            deployment_attestation_key=DEPLOYMENT_KEY,
            expected_revision=revision,
            now=NOW,
        )


def test_wrong_revision_and_stale_receipt_fail_closed(tmp_path):
    root, revision = _repo(tmp_path)
    state_path = _state(tmp_path)
    wrong_revision = _receipt(tmp_path, "e" * 40, state_path)
    with pytest.raises(ValueError, match="revision does not match"):
        validate_deployment_attestation(
            state_path=state_path,
            deployment_receipt_path=wrong_revision,
            deployment_attestation_key=DEPLOYMENT_KEY,
            expected_revision=revision,
            now=NOW,
        )
    stale = _receipt(tmp_path, revision, state_path, created_at_epoch=1)
    with pytest.raises(ValueError, match="stale"):
        validate_deployment_attestation(
            state_path=state_path,
            deployment_receipt_path=stale,
            deployment_attestation_key=DEPLOYMENT_KEY,
            expected_revision=revision,
            now=NOW,
        )


def test_truth_proven_must_remain_false(tmp_path):
    root, revision = _repo(tmp_path)
    state_path = _state(tmp_path)
    receipt_path = _receipt(tmp_path, revision, state_path, truth_proven=True)
    with pytest.raises(ValueError, match="must not claim truth_proven"):
        validate_deployment_attestation(
            state_path=state_path,
            deployment_receipt_path=receipt_path,
            deployment_attestation_key=DEPLOYMENT_KEY,
            expected_revision=revision,
            now=NOW,
        )


def test_missing_policy_route_fails_before_ledger_mutation(tmp_path):
    root, revision = _repo(tmp_path, omit=(88, ProofKind.REPRODUCIBILITY))
    state_path = _state(tmp_path)
    receipt_path = _receipt(tmp_path, revision, state_path)
    ledger_path = tmp_path / "ledger.jsonl"
    with pytest.raises(ValueError, match="does not authorize capability 88 reproducibility"):
        attest_post_deployment_proofs(
            repo_root=root,
            state_path=state_path,
            deployment_receipt_path=receipt_path,
            deployment_attestation_key=DEPLOYMENT_KEY,
            ledger_path=ledger_path,
            integrity_key=LEDGER_KEY,
            now=NOW,
        )
    assert not ledger_path.exists()


def test_state_and_receipt_must_live_outside_audited_repo(tmp_path):
    root, revision = _repo(tmp_path)
    external_state = _state(tmp_path)
    inside_state = root / "inside.post-deployment.json"
    inside_state.write_bytes(open(external_state, "rb").read())
    receipt_path = _receipt(tmp_path, revision, external_state)
    with pytest.raises(ValueError, match="state must live outside"):
        attest_post_deployment_proofs(
            repo_root=root,
            state_path=inside_state,
            deployment_receipt_path=receipt_path,
            deployment_attestation_key=DEPLOYMENT_KEY,
            ledger_path=tmp_path / "ledger.jsonl",
            integrity_key=LEDGER_KEY,
            now=NOW,
        )
