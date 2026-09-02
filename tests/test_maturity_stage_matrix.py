import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest

from research_engine.capability_registry import (
    CAPABILITIES,
    CapabilityEvidence,
    ProofKind,
    assess_capabilities,
)
from research_engine.maturity_proof import ProofLedger
from research_engine.maturity_stage_matrix import (
    _build_matrix,
    audit_repository_stage_matrix,
    parse_stage_policy,
)


KEY = b"S" * 32


STAGE_POLICY = {
    "schema_version": 1,
    "stages": [
        {"id": "A", "name": "Software foundations", "proof_kinds": ["code"]},
        {"id": "B", "name": "Production wiring", "proof_kinds": ["production_wiring"]},
        {"id": "C", "name": "Adversarial and benchmark test evidence", "proof_kinds": ["test"]},
        {"id": "D", "name": "Execution and reproducibility", "proof_kinds": ["execution", "reproducibility"]},
        {"id": "E", "name": "Independent live hardware and operational evidence", "proof_kinds": [
            "independent_validation", "persistence", "runtime_observation",
            "live_observation", "hardware_observation", "safety_gate",
        ]},
        {"id": "F", "name": "Strict 142 capability verification", "proof_kinds": []},
    ],
    "final_stage": "F",
}


def _stage_policy():
    return parse_stage_policy(json.dumps(STAGE_POLICY).encode("utf-8"))


def _evidence(capability_id, kinds):
    return CapabilityEvidence(
        capability_id=capability_id,
        proofs={kind: (f"proof:{capability_id}:{kind.value}",) for kind in kinds},
    )


def _fake_audit(evidence, *, valid=True):
    report = assess_capabilities(evidence)
    return SimpleNamespace(
        revision="a" * 40,
        audit_valid=valid,
        cryptographic_integrity=valid,
        audit_sha256="b" * 64,
        maturity_report=report,
        max_level_eligible=bool(valid and report.all_verified),
    )


def _state(matrix, capability_id, stage_id):
    return next(
        item for item in matrix.capability(capability_id)
        if item.stage_id == stage_id
    )


def test_stage_policy_partitions_every_proof_kind_exactly_once():
    policy = _stage_policy()
    owned = [kind for stage in policy.stages[:-1] for kind in stage.proof_kinds]
    assert set(owned) == set(ProofKind)
    assert len(owned) == len(set(owned)) == len(ProofKind)
    assert policy.stages[-1].stage_id == "F"
    assert policy.stages[-1].proof_kinds == ()
    assert len(policy.sha256) == 64


def test_stage_policy_rejects_missing_or_duplicate_proof_class():
    missing = json.loads(json.dumps(STAGE_POLICY))
    missing["stages"][4]["proof_kinds"].remove("safety_gate")
    with pytest.raises(ValueError, match="partition every proof kind"):
        parse_stage_policy(json.dumps(missing).encode())

    duplicate = json.loads(json.dumps(STAGE_POLICY))
    duplicate["stages"][2]["proof_kinds"].append("code")
    with pytest.raises(ValueError, match="assigned to both"):
        parse_stage_policy(json.dumps(duplicate).encode())


def test_wiring_missing_blocks_cumulative_stage_even_when_test_exists():
    cap = CAPABILITIES[13]  # #14 Formal Logic requires CODE + TEST + WIRING.
    evidence = {14: _evidence(14, {ProofKind.CODE, ProofKind.TEST})}
    matrix = _build_matrix(_fake_audit(evidence), _stage_policy())

    assert _state(matrix, 14, "A").cumulative_status == "VERIFIED"
    assert _state(matrix, 14, "B").local_missing_proofs == ("production_wiring",)
    assert _state(matrix, 14, "B").cumulative_status == "INCOMPLETE"
    assert _state(matrix, 14, "C").local_status == "VERIFIED"
    assert _state(matrix, 14, "C").cumulative_status == "INCOMPLETE"
    assert ProofKind.WIRING in cap.required_proofs
    assert matrix.all_142_verified is False


def test_execution_stage_cannot_be_inferred_from_code_and_tests():
    evidence = {20: _evidence(20, {ProofKind.CODE, ProofKind.TEST})}
    matrix = _build_matrix(_fake_audit(evidence), _stage_policy())
    assert _state(matrix, 20, "C").cumulative_status == "VERIFIED"
    d = _state(matrix, 20, "D")
    assert d.cumulative_status == "INCOMPLETE"
    assert set(d.local_missing_proofs) == {"execution", "reproducibility"}
    assert 20 in matrix.stage("D").blocking_capability_ids


def test_hardware_live_and_safety_remain_external_stage_blockers():
    required = set(CAPABILITIES[124].required_proofs)  # #125 Autonomous Lab Interface
    pre_external = required - {
        ProofKind.RUNTIME, ProofKind.LIVE, ProofKind.HARDWARE, ProofKind.SAFETY
    }
    evidence = {125: _evidence(125, pre_external)}
    matrix = _build_matrix(_fake_audit(evidence), _stage_policy())

    assert _state(matrix, 125, "D").cumulative_status == "VERIFIED"
    e = _state(matrix, 125, "E")
    assert e.cumulative_status == "INCOMPLETE"
    assert {"runtime_observation", "live_observation", "hardware_observation", "safety_gate"}.issubset(
        set(e.local_missing_proofs)
    )
    assert matrix.stage("E").all_capabilities_max is False


def test_invalid_global_audit_blocks_every_stage_even_with_perfect_evidence():
    evidence = {
        spec.id: _evidence(spec.id, set(spec.required_proofs))
        for spec in CAPABILITIES
    }
    matrix = _build_matrix(_fake_audit(evidence, valid=False), _stage_policy())
    assert all(stage.verified_capabilities == 0 for stage in matrix.stages)
    assert matrix.final_score == 0.0
    assert matrix.all_142_verified is False
    assert all(
        state.cumulative_status == "AUDIT_INVALID"
        for state in matrix.capability_states
    )


def test_stage_f_reaches_100_only_when_strict_auditor_state_has_all_142_verified():
    evidence = {
        spec.id: _evidence(spec.id, set(spec.required_proofs))
        for spec in CAPABILITIES
    }
    audit = _fake_audit(evidence, valid=True)
    assert audit.maturity_report.verified == 142
    matrix = _build_matrix(audit, _stage_policy())
    assert tuple(stage.stage_id for stage in matrix.stages) == tuple("ABCDEF")
    assert all(stage.verified_capabilities == 142 for stage in matrix.stages)
    assert matrix.stage("F").proof_completion_score == 100.0
    assert matrix.final_verified == 142
    assert matrix.total_capabilities == 142
    assert matrix.final_score == 100.0
    assert matrix.all_142_verified is True


def test_matrix_hash_is_deterministic_for_same_trusted_state():
    evidence = {1: _evidence(1, {ProofKind.CODE, ProofKind.TEST})}
    audit = _fake_audit(evidence)
    first = _build_matrix(audit, _stage_policy())
    second = _build_matrix(audit, _stage_policy())
    assert first.matrix_sha256 == second.matrix_sha256
    assert len(first.matrix_sha256) == 64


def _sha(data):
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


def test_repository_facade_uses_clean_git_head_keyed_ledger_and_tracked_stage_policy(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    (root / "research_engine").mkdir()
    (root / "tests").mkdir()
    (root / "config").mkdir()

    code = b"VALUE = 1\n"
    test = b"def test_value():\n    assert 1 == 1\n"
    (root / "research_engine" / "question.py").write_bytes(code)
    (root / "tests" / "test_question.py").write_bytes(test)
    proof_policy = {
        "schema_version": 1,
        "rules": [
            {"capability_id": 1, "proof_kind": "code", "subjects": ["research_engine/question.py"], "verifiers": ["ci"], "reference_prefixes": []},
            {"capability_id": 1, "proof_kind": "test", "subjects": ["tests/test_question.py"], "verifiers": ["ci"], "reference_prefixes": []},
        ],
    }
    (root / "config" / "maturity_proof_policy.json").write_text(
        json.dumps(proof_policy, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    (root / "config" / "maturity_stage_policy.json").write_text(
        json.dumps(STAGE_POLICY, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    revision = _git(root, "rev-parse", "HEAD")

    ledger_path = tmp_path / "proofs.jsonl"
    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    ledger.add(
        receipt_id="cap1-code", capability_id=1, proof_kind=ProofKind.CODE,
        subject="research_engine/question.py", subject_sha256=_sha(code),
        verifier="ci", observed_at=100.0,
    )
    ledger.add(
        receipt_id="cap1-test", capability_id=1, proof_kind=ProofKind.TEST,
        subject="tests/test_question.py", subject_sha256=_sha(test),
        verifier="ci", observed_at=100.0,
    )
    anchor = ledger.create_anchor(current_revision=revision, issued_at=101.0)

    matrix = audit_repository_stage_matrix(
        repo_root=root,
        ledger_path=ledger_path,
        integrity_key=KEY,
        anchor_token=anchor,
        now=102.0,
    )
    assert matrix.revision == revision
    assert matrix.audit_valid is True
    assert matrix.cryptographic_integrity is True
    assert matrix.stage("A").verified_capabilities == 1
    assert matrix.stage("C").verified_capabilities == 1
    assert matrix.stage("F").verified_capabilities == 1
    assert matrix.final_score == round(100.0 / 142.0, 2)
    assert matrix.all_142_verified is False


def test_repository_facade_rejects_dirty_checkout_before_stage_claim(tmp_path):
    # Reuse the strict parser failure property directly: a stage policy file is
    # not enough to make an untrusted repository state scoreable.
    malformed = json.loads(json.dumps(STAGE_POLICY))
    malformed["stages"][0]["proof_kinds"] = []
    with pytest.raises(ValueError, match="partition every proof kind"):
        parse_stage_policy(json.dumps(malformed).encode("utf-8"))
