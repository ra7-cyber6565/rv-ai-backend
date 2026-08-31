import json
from pathlib import Path

import pytest

from utils.release_identity import repository_identity

from research_engine.capability_registry import ProofKind
from research_engine.external_proof_attestor import (
    attest_external_proof,
    sign_external_receipt,
    validate_external_evidence_receipt,
)
from research_engine.maturity_proof import ProofLedger


LEDGER_KEY = b"L" * 32
VERIFIER_KEY = b"V" * 32
WRONG_KEY = b"X" * 32
NOW = 100_000.0


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _revision() -> str:
    identity = repository_identity(_root())
    assert identity["available"] is True
    assert identity["clean"] is True
    return str(identity["revision"])


def _sha(char: str) -> str:
    return char * 64


def _route(kind: ProofKind, capability_id: int):
    mapping = {
        ProofKind.EXECUTION: ("trusted-execution-attestor", "execution-run", "execution"),
        ProofKind.REPRODUCIBILITY: ("trusted-reproducibility-attestor", "reproducibility-run", "reproducibility"),
        ProofKind.INDEPENDENT: ("trusted-independent-validator", "independent-validation", "independent"),
        ProofKind.PERSISTENCE: ("trusted-persistence-attestor", "persistence-observation", "persistence"),
        ProofKind.RUNTIME: ("trusted-runtime-attestor", "runtime-observation", "runtime"),
        ProofKind.LIVE: ("trusted-live-observer", "live-observation", "live"),
        ProofKind.HARDWARE: ("trusted-hardware-lab", "hardware-observation", "hardware"),
        ProofKind.SAFETY: ("trusted-safety-officer", "safety-gate", "safety"),
    }
    verifier, suffix, namespace = mapping[kind]
    return (
        f"capability-{capability_id}-{suffix}",
        verifier,
        f"{namespace}:c{capability_id}:fixture-1",
    )


def _evidence(kind: ProofKind):
    if kind is ProofKind.EXECUTION:
        return {
            "run_id": "run-1",
            "started_at_epoch": NOW - 30,
            "finished_at_epoch": NOW - 10,
            "result_hash": _sha("a"),
            "exit_code": 0,
            "execution_complete": True,
            "truth_proven": False,
        }
    if kind is ProofKind.REPRODUCIBILITY:
        return {
            "runs": [
                {
                    "run_id": "repeat-1",
                    "started_at_epoch": NOW - 50,
                    "finished_at_epoch": NOW - 40,
                    "result_hash": _sha("a"),
                },
                {
                    "run_id": "repeat-2",
                    "started_at_epoch": NOW - 30,
                    "finished_at_epoch": NOW - 20,
                    "result_hash": _sha("b"),
                },
            ],
            "comparison_hash": _sha("c"),
            "reproducibility_confirmed": True,
            "truth_proven": False,
        }
    if kind is ProofKind.INDEPENDENT:
        return {
            "validation_id": "validation-1",
            "validator_id": "validator-A",
            "implementation_actor_id": "builder-B",
            "validator_environment_id": "env-independent",
            "implementation_environment_id": "env-build",
            "result_hash": _sha("d"),
            "independent_validation_complete": True,
            "truth_proven": False,
        }
    if kind is ProofKind.PERSISTENCE:
        return {
            "checkpoints": [
                {
                    "checkpoint_id": "cp-1",
                    "observed_at_epoch": NOW - 100,
                    "state_hash": _sha("e"),
                    "reload_verified": True,
                },
                {
                    "checkpoint_id": "cp-2",
                    "observed_at_epoch": NOW - 10,
                    "state_hash": _sha("f"),
                    "reload_verified": True,
                },
            ],
            "persistence_confirmed": True,
            "truth_proven": False,
        }
    if kind is ProofKind.RUNTIME:
        return {
            "run_id": "runtime-1",
            "started_at_epoch": NOW - 60,
            "finished_at_epoch": NOW - 30,
            "duration_seconds": 30.0,
            "environment_id": "runtime-env-1",
            "observations_count": 1,
            "result_hash": _sha("1"),
            "valid_until_epoch": NOW + 3600,
            "truth_proven": False,
            "runtime_observed": True,
        }
    if kind is ProofKind.LIVE:
        return {
            "run_id": "live-1",
            "started_at_epoch": NOW - 90,
            "finished_at_epoch": NOW - 30,
            "duration_seconds": 60.0,
            "environment_id": "live-env-1",
            "observations_count": 2,
            "result_hash": _sha("2"),
            "valid_until_epoch": NOW + 3600,
            "truth_proven": False,
            "live_observed": True,
            "external_target_id": "target-1",
            "real_external_observation": True,
        }
    if kind is ProofKind.HARDWARE:
        return {
            "observation_id": "hardware-1",
            "device_id": "device-1",
            "calibration_hash": _sha("3"),
            "safety_approval_hash": _sha("4"),
            "observations_count": 3,
            "result_hash": _sha("5"),
            "hardware_observed": True,
            "truth_proven": False,
        }
    if kind is ProofKind.SAFETY:
        return {
            "safety_case_hash": _sha("6"),
            "hazards_count": 3,
            "tests_executed": 10,
            "tests_passed": 10,
            "unresolved_critical_hazards": 0,
            "result_hash": _sha("7"),
            "safety_gate_passed": True,
            "truth_proven": False,
        }
    raise AssertionError(kind)


def _receipt(kind: ProofKind, capability_id: int, *, created=NOW, evidence=None):
    subject, verifier, reference = _route(kind, capability_id)
    evidence = dict(_evidence(kind) if evidence is None else evidence)
    import hashlib

    evidence_hash = hashlib.sha256(
        json.dumps(
            evidence,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    unsigned = {
        "schema_version": 1,
        "created_at_epoch": created,
        "implementation_revision": _revision(),
        "capability_id": capability_id,
        "proof_kind": kind.value,
        "subject": subject,
        "verifier": verifier,
        "reference": reference,
        "protocol_hash": _sha("9"),
        "evidence": evidence,
        "evidence_hash": evidence_hash,
    }
    return {**unsigned, "signature": sign_external_receipt(unsigned, verifier_key=VERIFIER_KEY)}


def _write(tmp_path, payload, name="receipt.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "kind,capability_id",
    [
        (ProofKind.EXECUTION, 22),
        (ProofKind.REPRODUCIBILITY, 22),
        (ProofKind.INDEPENDENT, 16),
        (ProofKind.PERSISTENCE, 42),
        (ProofKind.RUNTIME, 91),
        (ProofKind.LIVE, 42),
        (ProofKind.HARDWARE, 125),
        (ProofKind.SAFETY, 23),
    ],
)
def test_all_generic_external_profiles_validate_signed_evidence(tmp_path, kind, capability_id):
    path = _write(tmp_path, _receipt(kind, capability_id))
    parsed = validate_external_evidence_receipt(
        path,
        repo_root=_root(),
        expected_revision=_revision(),
        verifier_key=VERIFIER_KEY,
        now=NOW,
    )
    assert parsed.capability_id == capability_id
    assert parsed.proof_kind is kind
    assert parsed.verifier == _route(kind, capability_id)[1]
    assert len(parsed.receipt_sha256) == 64


def test_execution_receipt_mints_only_exact_policy_proof(tmp_path):
    path = _write(tmp_path, _receipt(ProofKind.EXECUTION, 22))
    ledger_path = tmp_path / "proofs.jsonl"
    result = attest_external_proof(
        repo_root=_root(),
        evidence_receipt_path=path,
        ledger_path=ledger_path,
        ledger_integrity_key=LEDGER_KEY,
        verifier_key=VERIFIER_KEY,
        now=NOW,
    )
    assert result.receipts_added == 1
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    capability = result.audit.maturity_report.results[21]
    assert ProofKind.EXECUTION not in capability.missing_proofs
    assert ProofKind.REPRODUCIBILITY in capability.missing_proofs
    assert ProofKind.CODE in capability.missing_proofs
    assert ProofKind.TEST in capability.missing_proofs

    ledger = ProofLedger(str(ledger_path), integrity_key=LEDGER_KEY)
    rows = [row for row in ledger._events() if row.get("event_type") == "ADD"]  # noqa: SLF001
    assert len(rows) == 1
    assert rows[0]["capability_id"] == 22
    assert rows[0]["proof_kind"] == ProofKind.EXECUTION.value
    assert rows[0]["verifier"] == "trusted-execution-attestor"
    assert rows[0]["subject"] == "capability-22-execution-run"


def test_wrong_verifier_key_and_tampering_fail_before_ledger_creation(tmp_path):
    payload = _receipt(ProofKind.EXECUTION, 22)
    path = _write(tmp_path, payload)
    with pytest.raises(ValueError, match="signature verification failed"):
        validate_external_evidence_receipt(
            path,
            repo_root=_root(),
            expected_revision=_revision(),
            verifier_key=WRONG_KEY,
            now=NOW,
        )

    payload["evidence"]["exit_code"] = 7
    tampered = _write(tmp_path, payload, "tampered.json")
    with pytest.raises(ValueError):
        attest_external_proof(
            repo_root=_root(),
            evidence_receipt_path=tampered,
            ledger_path=tmp_path / "never-created.jsonl",
            ledger_integrity_key=LEDGER_KEY,
            verifier_key=VERIFIER_KEY,
            now=NOW,
        )
    assert not (tmp_path / "never-created.jsonl").exists()


def test_specialized_route_cannot_be_bypassed_by_generic_attestor(tmp_path):
    # #127 execution is narrowed by committed policy to the dedicated
    # sim-to-reality attestor, so the canonical generic subject/verifier must fail.
    path = _write(tmp_path, _receipt(ProofKind.EXECUTION, 127))
    with pytest.raises(ValueError, match="specialized|canonical generic"):
        validate_external_evidence_receipt(
            path,
            repo_root=_root(),
            expected_revision=_revision(),
            verifier_key=VERIFIER_KEY,
            now=NOW,
        )


def test_stale_wrong_revision_and_truth_claims_fail_closed(tmp_path):
    stale = _write(
        tmp_path,
        _receipt(ProofKind.EXECUTION, 22, created=NOW - (6 * 60 * 60) - 1),
        "stale.json",
    )
    with pytest.raises(ValueError, match="stale"):
        validate_external_evidence_receipt(
            stale,
            repo_root=_root(),
            expected_revision=_revision(),
            verifier_key=VERIFIER_KEY,
            now=NOW,
        )

    wrong = _receipt(ProofKind.EXECUTION, 22)
    wrong["implementation_revision"] = "0" * 40
    unsigned = {k: v for k, v in wrong.items() if k != "signature"}
    wrong["signature"] = sign_external_receipt(unsigned, verifier_key=VERIFIER_KEY)
    wrong_path = _write(tmp_path, wrong, "wrong-revision.json")
    with pytest.raises(ValueError, match="revision mismatch"):
        validate_external_evidence_receipt(
            wrong_path,
            repo_root=_root(),
            expected_revision=_revision(),
            verifier_key=VERIFIER_KEY,
            now=NOW,
        )

    evidence = _evidence(ProofKind.EXECUTION)
    evidence["truth_proven"] = True
    truth = _write(tmp_path, _receipt(ProofKind.EXECUTION, 22, evidence=evidence), "truth.json")
    with pytest.raises(ValueError, match="truth_proven"):
        validate_external_evidence_receipt(
            truth,
            repo_root=_root(),
            expected_revision=_revision(),
            verifier_key=VERIFIER_KEY,
            now=NOW,
        )


def test_reproducibility_requires_distinct_repeat_ids(tmp_path):
    evidence = _evidence(ProofKind.REPRODUCIBILITY)
    evidence["runs"][1]["run_id"] = evidence["runs"][0]["run_id"]
    path = _write(tmp_path, _receipt(ProofKind.REPRODUCIBILITY, 22, evidence=evidence))
    with pytest.raises(ValueError, match="distinct"):
        validate_external_evidence_receipt(
            path,
            repo_root=_root(),
            expected_revision=_revision(),
            verifier_key=VERIFIER_KEY,
            now=NOW,
        )


def test_persistence_requires_strict_time_order_and_reload_verification(tmp_path):
    evidence = _evidence(ProofKind.PERSISTENCE)
    evidence["checkpoints"][1]["observed_at_epoch"] = evidence["checkpoints"][0]["observed_at_epoch"]
    path = _write(tmp_path, _receipt(ProofKind.PERSISTENCE, 42, evidence=evidence))
    with pytest.raises(ValueError, match="strictly increase"):
        validate_external_evidence_receipt(
            path,
            repo_root=_root(),
            expected_revision=_revision(),
            verifier_key=VERIFIER_KEY,
            now=NOW,
        )


def test_independence_cannot_self_validate(tmp_path):
    evidence = _evidence(ProofKind.INDEPENDENT)
    evidence["validator_id"] = evidence["implementation_actor_id"]
    path = _write(tmp_path, _receipt(ProofKind.INDEPENDENT, 16, evidence=evidence))
    with pytest.raises(ValueError, match="must differ"):
        validate_external_evidence_receipt(
            path,
            repo_root=_root(),
            expected_revision=_revision(),
            verifier_key=VERIFIER_KEY,
            now=NOW,
        )


def test_runtime_live_expiry_is_bounded_and_safety_blocks_unresolved_critical_hazards(tmp_path):
    runtime = _evidence(ProofKind.RUNTIME)
    runtime["valid_until_epoch"] = NOW + (24 * 60 * 60) + 1
    runtime_path = _write(tmp_path, _receipt(ProofKind.RUNTIME, 91, evidence=runtime), "runtime.json")
    with pytest.raises(ValueError, match="validity window"):
        validate_external_evidence_receipt(
            runtime_path,
            repo_root=_root(),
            expected_revision=_revision(),
            verifier_key=VERIFIER_KEY,
            now=NOW,
        )

    safety = _evidence(ProofKind.SAFETY)
    safety["unresolved_critical_hazards"] = 1
    safety_path = _write(tmp_path, _receipt(ProofKind.SAFETY, 23, evidence=safety), "safety.json")
    with pytest.raises(ValueError, match="critical safety hazards"):
        validate_external_evidence_receipt(
            safety_path,
            repo_root=_root(),
            expected_revision=_revision(),
            verifier_key=VERIFIER_KEY,
            now=NOW,
        )


def test_existing_ledger_requires_anchor_and_same_receipt_is_idempotent(tmp_path):
    path = _write(tmp_path, _receipt(ProofKind.EXECUTION, 22))
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_external_proof(
        repo_root=_root(),
        evidence_receipt_path=path,
        ledger_path=ledger_path,
        ledger_integrity_key=LEDGER_KEY,
        verifier_key=VERIFIER_KEY,
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_external_proof(
            repo_root=_root(),
            evidence_receipt_path=path,
            ledger_path=ledger_path,
            ledger_integrity_key=LEDGER_KEY,
            verifier_key=VERIFIER_KEY,
            now=NOW + 1,
        )
    second = attest_external_proof(
        repo_root=_root(),
        evidence_receipt_path=path,
        ledger_path=ledger_path,
        ledger_integrity_key=LEDGER_KEY,
        verifier_key=VERIFIER_KEY,
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 1
