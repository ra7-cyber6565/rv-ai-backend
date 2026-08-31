import hashlib
import hmac
import json
import subprocess

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.maturity_proof import ProofLedger
from research_engine.physical_lab_attestor import (
    attest_physical_lab_proofs,
    validate_physical_lab_attestation,
)


HARDWARE_KEY = b"H" * 32
LEDGER_KEY = b"L" * 32
NOW = 10_000.0
SUBJECT = "physical-lab-live-validation"
VERIFIER = "trusted-hardware-observer"
PREFIX = "physical-lab:"
REQUIRED = (
    ProofKind.EXECUTION,
    ProofKind.REPRODUCIBILITY,
    ProofKind.RUNTIME,
    ProofKind.LIVE,
    ProofKind.HARDWARE,
    ProofKind.SAFETY,
)


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


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "config").mkdir()
    (root / "research_engine").mkdir()
    boundary = root / "research_engine" / "physical_lab_boundary.py"
    boundary.write_text("BOUNDARY_VERSION = 'fixture-v1'\n", encoding="utf-8")
    rules = []
    for capability_id in (125, 126):
        for kind in REQUIRED:
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
    return root, _git(root, "rev-parse", "HEAD"), _sha(boundary.read_bytes())


def _receipt(tmp_path, revision, boundary_sha, **overrides):
    value = {
        "schema_version": 1,
        "created_at_epoch": 9950,
        "live_observed_at_epoch": 9940,
        "implementation_revision": revision,
        "boundary_sha256": boundary_sha,
        "observer_id": "observer-1",
        "hardware_system_id": "rig-1",
        "session_ids": ["session-a", "session-b"],
        "session_sensor_chain_heads": {
            "session-a": "a" * 64,
            "session-b": "b" * 64,
        },
        "session_action_hashes": {
            "session-a": ["c" * 64],
            "session-b": ["d" * 64],
        },
        "calibration_references": ["cal-2026-08"],
        "safety_review_hash": "e" * 64,
        "emergency_stop_test_hash": "f" * 64,
        "lab_interface_exercised": True,
        "sensor_loop_exercised": True,
        "execution_observed": True,
        "reproduction_passed": True,
        "runtime_observation_complete": True,
        "live_observation_complete": True,
        "hardware_observation_complete": True,
        "safety_gate_passed": True,
        "software_boundary_preserved": True,
        "truth_proven": False,
    }
    value.update(overrides)
    value["signature"] = hmac.new(HARDWARE_KEY, _canonical(value), hashlib.sha256).hexdigest()
    path = tmp_path / f"physical-{len(list(tmp_path.glob('physical-*.json')))}.json"
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def test_valid_live_hardware_receipt_mints_exact_twelve_external_proofs(tmp_path):
    root, revision, boundary_sha = _repo(tmp_path)
    receipt = _receipt(tmp_path, revision, boundary_sha)
    ledger_path = tmp_path / "ledger.jsonl"
    result = attest_physical_lab_proofs(
        repo_root=root,
        hardware_receipt_path=receipt,
        hardware_attestation_key=HARDWARE_KEY,
        ledger_path=ledger_path,
        integrity_key=LEDGER_KEY,
        now=NOW,
    )
    assert result.revision == revision
    assert result.receipts_added == 12
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True

    ledger = ProofLedger(str(ledger_path), integrity_key=LEDGER_KEY)
    rows = [row for row in ledger._events() if row.get("event_type") == "ADD"]  # noqa: SLF001
    assert len(rows) == 12
    assert {row["capability_id"] for row in rows} == {125, 126}
    assert {row["proof_kind"] for row in rows} == {kind.value for kind in REQUIRED}
    assert all(row["subject"] == SUBJECT for row in rows)
    assert all(row["verifier"] == VERIFIER for row in rows)
    assert ProofKind.CODE.value not in {row["proof_kind"] for row in rows}
    assert ProofKind.TEST.value not in {row["proof_kind"] for row in rows}
    assert ProofKind.WIRING.value not in {row["proof_kind"] for row in rows}


def test_receipt_inside_repo_is_never_accepted_as_real_hardware_evidence(tmp_path):
    root, revision, boundary_sha = _repo(tmp_path)
    external = _receipt(tmp_path, revision, boundary_sha)
    inside = root / "hardware.json"
    inside.write_bytes(external.read_bytes())
    with pytest.raises(ValueError, match="must live outside"):
        validate_physical_lab_attestation(
            repo_root=root,
            hardware_receipt_path=inside,
            hardware_attestation_key=HARDWARE_KEY,
            expected_revision=revision,
            now=NOW,
        )


def test_wrong_hardware_key_fails_before_ledger_mutation(tmp_path):
    root, revision, boundary_sha = _repo(tmp_path)
    receipt = _receipt(tmp_path, revision, boundary_sha)
    ledger_path = tmp_path / "ledger.jsonl"
    with pytest.raises(ValueError, match="signature verification failed"):
        attest_physical_lab_proofs(
            repo_root=root,
            hardware_receipt_path=receipt,
            hardware_attestation_key=b"X" * 32,
            ledger_path=ledger_path,
            integrity_key=LEDGER_KEY,
            now=NOW,
        )
    assert not ledger_path.exists()


def test_wrong_revision_or_boundary_hash_is_rejected(tmp_path):
    root, revision, boundary_sha = _repo(tmp_path)
    wrong_revision = _receipt(tmp_path, "1" * 40, boundary_sha)
    with pytest.raises(ValueError, match="revision does not match"):
        validate_physical_lab_attestation(
            repo_root=root,
            hardware_receipt_path=wrong_revision,
            hardware_attestation_key=HARDWARE_KEY,
            expected_revision=revision,
            now=NOW,
        )
    wrong_boundary = _receipt(tmp_path, revision, "2" * 64)
    with pytest.raises(ValueError, match="does not bind exact physical lab boundary"):
        validate_physical_lab_attestation(
            repo_root=root,
            hardware_receipt_path=wrong_boundary,
            hardware_attestation_key=HARDWARE_KEY,
            expected_revision=revision,
            now=NOW,
        )


@pytest.mark.parametrize(
    "field",
    [
        "lab_interface_exercised",
        "sensor_loop_exercised",
        "execution_observed",
        "reproduction_passed",
        "runtime_observation_complete",
        "live_observation_complete",
        "hardware_observation_complete",
        "safety_gate_passed",
        "software_boundary_preserved",
    ],
)
def test_every_external_gate_is_mandatory(tmp_path, field):
    root, revision, boundary_sha = _repo(tmp_path)
    receipt = _receipt(tmp_path, revision, boundary_sha, **{field: False})
    with pytest.raises(ValueError, match="did not pass every required external gate"):
        validate_physical_lab_attestation(
            repo_root=root,
            hardware_receipt_path=receipt,
            hardware_attestation_key=HARDWARE_KEY,
            expected_revision=revision,
            now=NOW,
        )


def test_reproducibility_needs_two_distinct_sessions_and_distinct_chain_heads(tmp_path):
    root, revision, boundary_sha = _repo(tmp_path)
    one = _receipt(
        tmp_path,
        revision,
        boundary_sha,
        session_ids=["session-a"],
        session_sensor_chain_heads={"session-a": "a" * 64},
        session_action_hashes={"session-a": ["c" * 64]},
    )
    with pytest.raises(ValueError, match="session_ids must be a bounded list"):
        validate_physical_lab_attestation(
            repo_root=root,
            hardware_receipt_path=one,
            hardware_attestation_key=HARDWARE_KEY,
            expected_revision=revision,
            now=NOW,
        )

    duplicate_heads = _receipt(
        tmp_path,
        revision,
        boundary_sha,
        session_sensor_chain_heads={"session-a": "a" * 64, "session-b": "a" * 64},
    )
    with pytest.raises(ValueError, match="distinct per-session commitments"):
        validate_physical_lab_attestation(
            repo_root=root,
            hardware_receipt_path=duplicate_heads,
            hardware_attestation_key=HARDWARE_KEY,
            expected_revision=revision,
            now=NOW,
        )


def test_stale_future_and_post_receipt_live_timestamps_fail_closed(tmp_path):
    root, revision, boundary_sha = _repo(tmp_path)
    stale = _receipt(tmp_path, revision, boundary_sha, created_at_epoch=1, live_observed_at_epoch=1)
    with pytest.raises(ValueError, match="stale"):
        validate_physical_lab_attestation(
            repo_root=root,
            hardware_receipt_path=stale,
            hardware_attestation_key=HARDWARE_KEY,
            expected_revision=revision,
            now=NOW,
        )
    future = _receipt(tmp_path, revision, boundary_sha, created_at_epoch=20_000, live_observed_at_epoch=19_999)
    with pytest.raises(ValueError, match="from the future"):
        validate_physical_lab_attestation(
            repo_root=root,
            hardware_receipt_path=future,
            hardware_attestation_key=HARDWARE_KEY,
            expected_revision=revision,
            now=NOW,
        )
    impossible = _receipt(tmp_path, revision, boundary_sha, created_at_epoch=9950, live_observed_at_epoch=9960)
    with pytest.raises(ValueError, match="cannot occur after receipt creation"):
        validate_physical_lab_attestation(
            repo_root=root,
            hardware_receipt_path=impossible,
            hardware_attestation_key=HARDWARE_KEY,
            expected_revision=revision,
            now=NOW,
        )


def test_truth_proven_must_remain_false(tmp_path):
    root, revision, boundary_sha = _repo(tmp_path)
    receipt = _receipt(tmp_path, revision, boundary_sha, truth_proven=True)
    with pytest.raises(ValueError, match="must not claim truth_proven"):
        validate_physical_lab_attestation(
            repo_root=root,
            hardware_receipt_path=receipt,
            hardware_attestation_key=HARDWARE_KEY,
            expected_revision=revision,
            now=NOW,
        )


def test_existing_ledger_requires_prior_trusted_anchor_and_reuses_exact_receipt(tmp_path):
    root, revision, boundary_sha = _repo(tmp_path)
    receipt = _receipt(tmp_path, revision, boundary_sha)
    ledger_path = tmp_path / "ledger.jsonl"
    first = attest_physical_lab_proofs(
        repo_root=root,
        hardware_receipt_path=receipt,
        hardware_attestation_key=HARDWARE_KEY,
        ledger_path=ledger_path,
        integrity_key=LEDGER_KEY,
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_physical_lab_proofs(
            repo_root=root,
            hardware_receipt_path=receipt,
            hardware_attestation_key=HARDWARE_KEY,
            ledger_path=ledger_path,
            integrity_key=LEDGER_KEY,
            now=NOW + 1,
        )
    second = attest_physical_lab_proofs(
        repo_root=root,
        hardware_receipt_path=receipt,
        hardware_attestation_key=HARDWARE_KEY,
        ledger_path=ledger_path,
        integrity_key=LEDGER_KEY,
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 12
