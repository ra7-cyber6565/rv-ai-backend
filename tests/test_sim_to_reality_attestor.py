import hashlib
import hmac
import json
import subprocess

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.maturity_proof import ProofLedger
from research_engine.sim_to_reality import (
    PhysicalComparisonSample,
    SimToRealityProtocol,
    VariableTolerance,
    evaluate_sim_to_reality_gap,
)
from research_engine.sim_to_reality_attestor import (
    attest_sim_to_reality_proofs,
    validate_hardware_attestation,
)


HARDWARE_KEY = b"H" * 32
LEDGER_KEY = b"L" * 32
NOW = 10_000.0


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


def _repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "config").mkdir()
    policy = {
        "schema_version": 1,
        "rules": [
            {
                "capability_id": 127,
                "proof_kind": kind.value,
                "subjects": ["sim-to-reality-hardware-validation"],
                "verifiers": ["trusted-hardware-observer"],
                "reference_prefixes": ["sim-to-reality:"],
            }
            for kind in (
                ProofKind.EXECUTION,
                ProofKind.REPRODUCIBILITY,
                ProofKind.HARDWARE,
                ProofKind.SAFETY,
            )
        ],
    }
    (root / "config" / "maturity_proof_policy.json").write_text(
        json.dumps(policy, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    return root, _git(root, "rev-parse", "HEAD")


def _report(tmp_path):
    protocol = SimToRealityProtocol(
        protocol_id="rig-v1",
        model_hash="a" * 64,
        variables=(VariableTolerance(
            name="temperature",
            scale=100.0,
            max_nrmse=0.10,
            max_abs_normalized_bias=0.05,
            max_p95_normalized_error=0.15,
            min_uncertainty_coverage=0.8,
        ),),
        min_holdout_samples=6,
        min_regimes=2,
        min_samples_per_regime=3,
        min_distinct_sessions=2,
    )
    rows = []
    for index in range(6):
        observed = 20.0 + index * 5.0
        rows.append(PhysicalComparisonSample(
            sample_id=f"p{index}",
            regime="cold" if index < 3 else "hot",
            session_id="session-a" if index % 2 == 0 else "session-b",
            timestamp_epoch=1000 + index,
            predicted={"temperature": observed + 1.0},
            observed={"temperature": observed},
            prediction_uncertainty={"temperature": 2.0},
            measurement_uncertainty={"temperature": 2.0},
            hardware_receipt_hash=(f"{index + 1:x}" * 64)[:64],
        ))
    report = evaluate_sim_to_reality_gap(protocol, rows)
    assert report.software_fit_passed is True
    assert report.threshold_sensitive is False
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return path, report


def _hardware_receipt(tmp_path, revision, report, **overrides):
    value = {
        "schema_version": 1,
        "created_at_epoch": 9900,
        "implementation_revision": revision,
        "report_hash": report.report_hash,
        "observer_id": "observer-1",
        "hardware_system_id": "rig-1",
        "session_ids": list(report.sessions),
        "calibration_references": ["cal-2026-08"],
        "safety_review_hash": "c" * 64,
        "emergency_stop_test_hash": "d" * 64,
        "execution_observed": True,
        "reproduction_passed": True,
        "hardware_observation_complete": True,
        "safety_gate_passed": True,
        "truth_proven": False,
    }
    value.update(overrides)
    unsigned = dict(value)
    signature = hmac.new(HARDWARE_KEY, _canonical(unsigned), hashlib.sha256).hexdigest()
    value["signature"] = signature
    path = tmp_path / f"hardware-{len(list(tmp_path.glob('hardware-*.json')))}.json"
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def test_valid_signed_hardware_receipt_mints_only_required_external_proofs(tmp_path):
    root, revision = _repo(tmp_path)
    report_path, report = _report(tmp_path)
    receipt_path = _hardware_receipt(tmp_path, revision, report)
    ledger_path = tmp_path / "ledger.jsonl"

    result = attest_sim_to_reality_proofs(
        repo_root=root,
        report_path=report_path,
        hardware_receipt_path=receipt_path,
        hardware_attestation_key=HARDWARE_KEY,
        ledger_path=ledger_path,
        integrity_key=LEDGER_KEY,
        now=NOW,
    )
    assert result.revision == revision
    assert result.report_hash == report.report_hash
    assert result.receipts_added == 4

    ledger = ProofLedger(str(ledger_path), integrity_key=LEDGER_KEY)
    rows = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
    ]
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
        ProofKind.HARDWARE.value,
        ProofKind.SAFETY.value,
    }
    assert all(row["capability_id"] == 127 for row in rows)
    assert all(row["verifier"] == "trusted-hardware-observer" for row in rows)
    assert ProofKind.INDEPENDENT.value not in {row["proof_kind"] for row in rows}
    assert ProofKind.LIVE.value not in {row["proof_kind"] for row in rows}


def test_wrong_hardware_hmac_fails_before_ledger_mutation(tmp_path):
    root, revision = _repo(tmp_path)
    report_path, report = _report(tmp_path)
    receipt_path = _hardware_receipt(tmp_path, revision, report)
    ledger_path = tmp_path / "ledger.jsonl"
    with pytest.raises(ValueError, match="signature verification failed"):
        attest_sim_to_reality_proofs(
            repo_root=root,
            report_path=report_path,
            hardware_receipt_path=receipt_path,
            hardware_attestation_key=b"X" * 32,
            ledger_path=ledger_path,
            integrity_key=LEDGER_KEY,
            now=NOW,
        )
    assert not ledger_path.exists()


def test_report_tamper_is_rejected_even_with_valid_hardware_signature(tmp_path):
    root, revision = _repo(tmp_path)
    report_path, report = _report(tmp_path)
    receipt_path = _hardware_receipt(tmp_path, revision, report)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["software_fit_passed"] = False
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="report hash verification failed"):
        validate_hardware_attestation(
            report_path=report_path,
            hardware_receipt_path=receipt_path,
            hardware_attestation_key=HARDWARE_KEY,
            expected_revision=revision,
            now=NOW,
        )


@pytest.mark.parametrize(
    "field",
    [
        "execution_observed",
        "reproduction_passed",
        "hardware_observation_complete",
        "safety_gate_passed",
    ],
)
def test_each_required_physical_gate_must_be_true(tmp_path, field):
    root, revision = _repo(tmp_path)
    report_path, report = _report(tmp_path)
    receipt_path = _hardware_receipt(tmp_path, revision, report, **{field: False})
    with pytest.raises(ValueError, match="did not pass all required physical gates"):
        validate_hardware_attestation(
            report_path=report_path,
            hardware_receipt_path=receipt_path,
            hardware_attestation_key=HARDWARE_KEY,
            expected_revision=revision,
            now=NOW,
        )


def test_session_mismatch_cannot_claim_reproduction(tmp_path):
    root, revision = _repo(tmp_path)
    report_path, report = _report(tmp_path)
    receipt_path = _hardware_receipt(
        tmp_path,
        revision,
        report,
        session_ids=["different-a", "different-b"],
    )
    with pytest.raises(ValueError, match="session_ids do not match"):
        validate_hardware_attestation(
            report_path=report_path,
            hardware_receipt_path=receipt_path,
            hardware_attestation_key=HARDWARE_KEY,
            expected_revision=revision,
            now=NOW,
        )


def test_revision_mismatch_is_rejected(tmp_path):
    root, revision = _repo(tmp_path)
    report_path, report = _report(tmp_path)
    receipt_path = _hardware_receipt(tmp_path, "e" * 40, report)
    with pytest.raises(ValueError, match="revision does not match"):
        validate_hardware_attestation(
            report_path=report_path,
            hardware_receipt_path=receipt_path,
            hardware_attestation_key=HARDWARE_KEY,
            expected_revision=revision,
            now=NOW,
        )


def test_stale_receipt_is_rejected(tmp_path):
    root, revision = _repo(tmp_path)
    report_path, report = _report(tmp_path)
    receipt_path = _hardware_receipt(
        tmp_path,
        revision,
        report,
        created_at_epoch=1,
    )
    with pytest.raises(ValueError, match="stale"):
        validate_hardware_attestation(
            report_path=report_path,
            hardware_receipt_path=receipt_path,
            hardware_attestation_key=HARDWARE_KEY,
            expected_revision=revision,
            now=NOW,
        )


def test_truth_proven_must_remain_false(tmp_path):
    root, revision = _repo(tmp_path)
    report_path, report = _report(tmp_path)
    receipt_path = _hardware_receipt(tmp_path, revision, report, truth_proven=True)
    with pytest.raises(ValueError, match="must not claim truth_proven"):
        validate_hardware_attestation(
            report_path=report_path,
            hardware_receipt_path=receipt_path,
            hardware_attestation_key=HARDWARE_KEY,
            expected_revision=revision,
            now=NOW,
        )
