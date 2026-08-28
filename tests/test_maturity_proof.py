import hashlib
import json

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.maturity_proof import ProofLedger


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _add_basic_code_and_test(ledger, *, now=100.0):
    code_sha = _sha(b"code-v1")
    test_sha = _sha(b"test-v1")
    ledger.add(
        receipt_id="cap1-code",
        capability_id=1,
        proof_kind=ProofKind.CODE,
        subject="research_engine/question.py",
        subject_sha256=code_sha,
        verifier="ci",
        observed_at=now,
        reference="run:1",
    )
    ledger.add(
        receipt_id="cap1-test",
        capability_id=1,
        proof_kind=ProofKind.TEST,
        subject="tests/test_question.py",
        subject_sha256=test_sha,
        verifier="ci",
        observed_at=now,
        reference="run:1",
    )
    return code_sha, test_sha


def test_active_code_and_test_receipts_can_verify_software_capability(tmp_path):
    ledger = ProofLedger(str(tmp_path / "proofs.jsonl"))
    code_sha, test_sha = _add_basic_code_and_test(ledger)
    current = {
        "research_engine/question.py": code_sha,
        "tests/test_question.py": test_sha,
    }

    report, status = ledger.maturity_report(current_hashes=current, now=110.0)
    cap1 = report.results[0]
    assert cap1.capability_id == 1
    assert cap1.status == "VERIFIED"
    assert report.verified == 1
    assert status.integrity_valid is True
    assert status.active_receipts == 2
    assert status.ledger_head_hash != "GENESIS"
    assert ledger.verify_chain() is True

    reloaded = ProofLedger(str(tmp_path / "proofs.jsonl"))
    report2, status2 = reloaded.maturity_report(current_hashes=current, now=110.0)
    assert report2.results[0].status == "VERIFIED"
    assert status2.ledger_head_hash == status.ledger_head_hash


def test_changed_code_hash_invalidates_stale_code_proof(tmp_path):
    ledger = ProofLedger(str(tmp_path / "proofs.jsonl"))
    _code_sha, test_sha = _add_basic_code_and_test(ledger)
    current = {
        "research_engine/question.py": _sha(b"code-v2"),
        "tests/test_question.py": test_sha,
    }

    report, status = ledger.maturity_report(current_hashes=current, now=110.0)
    cap1 = report.results[0]
    assert cap1.status == "INCOMPLETE"
    assert ProofKind.CODE in cap1.missing_proofs
    assert status.stale_file_receipts == 1
    assert status.active_receipts == 1


def test_missing_current_file_hash_also_makes_code_test_proof_stale(tmp_path):
    ledger = ProofLedger(str(tmp_path / "proofs.jsonl"))
    _add_basic_code_and_test(ledger)
    report, status = ledger.maturity_report(current_hashes={}, now=110.0)
    assert report.results[0].status == "INCOMPLETE"
    assert status.stale_file_receipts == 2
    assert status.active_receipts == 0


def test_runtime_and_live_proofs_require_expiry_and_expire(tmp_path):
    ledger = ProofLedger(str(tmp_path / "proofs.jsonl"))
    digest = _sha(b"runtime-receipt")

    with pytest.raises(ValueError, match="valid_until"):
        ledger.add(
            receipt_id="runtime-no-expiry",
            capability_id=135,
            proof_kind=ProofKind.RUNTIME,
            subject="runtime:knowledge-watch",
            subject_sha256=digest,
            verifier="ci",
            observed_at=100.0,
        )

    ledger.add(
        receipt_id="runtime-valid",
        capability_id=135,
        proof_kind=ProofKind.RUNTIME,
        subject="runtime:knowledge-watch",
        subject_sha256=digest,
        verifier="ci",
        observed_at=100.0,
        valid_until=120.0,
    )
    evidence_before, status_before = ledger.evidence(current_hashes={}, now=110.0)
    assert evidence_before[135].has(ProofKind.RUNTIME)
    assert status_before.expired_receipts == 0

    evidence_after, status_after = ledger.evidence(current_hashes={}, now=120.0)
    assert 135 not in evidence_after
    assert status_after.expired_receipts == 1
    assert status_after.active_receipts == 0


def test_revocation_removes_proof_and_is_persistent(tmp_path):
    ledger = ProofLedger(str(tmp_path / "proofs.jsonl"))
    code_sha, test_sha = _add_basic_code_and_test(ledger)
    current = {
        "research_engine/question.py": code_sha,
        "tests/test_question.py": test_sha,
    }
    ledger.revoke("cap1-code", reason="implementation changed after verification")

    report, status = ledger.maturity_report(current_hashes=current, now=110.0)
    assert report.results[0].status == "INCOMPLETE"
    assert ProofKind.CODE in report.results[0].missing_proofs
    assert status.revoked_receipts == 1
    assert status.active_receipts == 1

    reloaded = ProofLedger(str(tmp_path / "proofs.jsonl"))
    report2, status2 = reloaded.maturity_report(current_hashes=current, now=110.0)
    assert report2.results[0].status == "INCOMPLETE"
    assert status2.revoked_receipts == 1


def test_duplicate_receipt_and_double_revocation_are_rejected(tmp_path):
    ledger = ProofLedger(str(tmp_path / "proofs.jsonl"))
    digest = _sha(b"code")
    kwargs = dict(
        receipt_id="same",
        capability_id=1,
        proof_kind=ProofKind.CODE,
        subject="a.py",
        subject_sha256=digest,
        verifier="ci",
        observed_at=100.0,
    )
    ledger.add(**kwargs)
    with pytest.raises(ValueError, match="already exists"):
        ledger.add(**kwargs)
    ledger.revoke("same", reason="bad receipt")
    with pytest.raises(ValueError, match="already revoked"):
        ledger.revoke("same", reason="again")


def test_invalid_capability_sha_and_expiry_fail_closed(tmp_path):
    ledger = ProofLedger(str(tmp_path / "proofs.jsonl"))
    with pytest.raises(ValueError, match="unknown capability"):
        ledger.add(
            receipt_id="bad-cap",
            capability_id=999,
            proof_kind=ProofKind.CODE,
            subject="a.py",
            subject_sha256=_sha(b"x"),
            verifier="ci",
            observed_at=100.0,
        )
    with pytest.raises(ValueError, match="64-character"):
        ledger.add(
            receipt_id="bad-sha",
            capability_id=1,
            proof_kind=ProofKind.CODE,
            subject="a.py",
            subject_sha256="not-a-sha",
            verifier="ci",
            observed_at=100.0,
        )
    with pytest.raises(ValueError, match="after observed_at"):
        ledger.add(
            receipt_id="bad-expiry",
            capability_id=135,
            proof_kind=ProofKind.RUNTIME,
            subject="runtime:x",
            subject_sha256=_sha(b"x"),
            verifier="ci",
            observed_at=100.0,
            valid_until=100.0,
        )


def test_tampering_breaks_chain_and_blocks_maturity_report(tmp_path):
    path = tmp_path / "proofs.jsonl"
    ledger = ProofLedger(str(path))
    code_sha, test_sha = _add_basic_code_and_test(ledger)
    current = {
        "research_engine/question.py": code_sha,
        "tests/test_question.py": test_sha,
    }
    assert ledger.verify_chain() is True

    lines = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["subject"] = "research_engine/tampered.py"
    lines[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert ledger.verify_chain() is False
    with pytest.raises(ValueError, match="integrity failure"):
        ledger.maturity_report(current_hashes=current, now=110.0)


def test_malformed_json_is_fail_closed(tmp_path):
    path = tmp_path / "proofs.jsonl"
    ledger = ProofLedger(str(path))
    _add_basic_code_and_test(ledger)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not-json}\n")
    assert ledger.verify_chain() is False
    with pytest.raises(ValueError, match="invalid JSON"):
        ledger.maturity_report(current_hashes={}, now=110.0)
