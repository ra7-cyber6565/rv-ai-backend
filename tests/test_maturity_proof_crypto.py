import hashlib
import json

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.maturity_proof import ProofLedger


KEY = b"K" * 32
WRONG_KEY = b"W" * 32


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _recompute_plain_event_hash(row):
    payload = dict(row)
    payload.pop("event_hash", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_keyed_chain_rejects_wrong_or_missing_key(tmp_path):
    path = tmp_path / "proofs.jsonl"
    ledger = ProofLedger(str(path), integrity_key=KEY)
    receipt = ledger.add(
        receipt_id="code-keyed",
        capability_id=1,
        proof_kind=ProofKind.CODE,
        subject="research_engine/question.py",
        subject_sha256=_sha(b"code"),
        verifier="ci",
        observed_at=100.0,
    )
    assert receipt.integrity_mode == "hmac-sha256"
    assert ledger.verify_chain() is True
    assert ProofLedger(str(path), integrity_key=WRONG_KEY).verify_chain() is False
    assert ProofLedger(str(path)).verify_chain() is False

    with pytest.raises(ValueError, match="integrity_key"):
        ProofLedger(str(tmp_path / "weak.jsonl"), integrity_key=b"too-short")


def test_anchor_is_required_before_keyed_chain_counts_as_crypto_integrity(tmp_path):
    path = tmp_path / "proofs.jsonl"
    ledger = ProofLedger(str(path), integrity_key=KEY)
    code_sha = _sha(b"code")
    ledger.add(
        receipt_id="code",
        capability_id=1,
        proof_kind=ProofKind.CODE,
        subject="research_engine/question.py",
        subject_sha256=code_sha,
        verifier="ci",
        observed_at=100.0,
    )

    evidence, status = ledger.evidence(
        current_hashes={"research_engine/question.py": code_sha},
        now=101.0,
        current_revision="rev-A",
    )
    assert evidence[1].has(ProofKind.CODE)
    assert status.keyed_events == 1
    assert status.unkeyed_events == 0
    assert status.anchor_verified is False
    assert status.cryptographic_integrity is False

    with pytest.raises(ValueError, match="trusted external anchor"):
        ledger.evidence(
            current_hashes={"research_engine/question.py": code_sha},
            now=101.0,
            current_revision="rev-A",
            require_cryptographic_integrity=True,
        )

    token = ledger.create_anchor(current_revision="rev-A", issued_at=101.0)
    evidence2, status2 = ledger.evidence(
        current_hashes={"research_engine/question.py": code_sha},
        now=101.0,
        current_revision="rev-A",
        anchor_token=token,
        require_cryptographic_integrity=True,
    )
    assert evidence2[1].has(ProofKind.CODE)
    assert status2.anchor_verified is True
    assert status2.cryptographic_integrity is True
    assert ledger.verify_chain(anchor_token=token, current_revision="rev-A") is True
    assert ledger.verify_chain(anchor_token=token, current_revision="rev-B") is False


def test_signed_anchor_detects_valid_prefix_truncation_rollback(tmp_path):
    path = tmp_path / "proofs.jsonl"
    ledger = ProofLedger(str(path), integrity_key=KEY)
    ledger.add(
        receipt_id="one",
        capability_id=1,
        proof_kind=ProofKind.CODE,
        subject="a.py",
        subject_sha256=_sha(b"a"),
        verifier="ci",
        observed_at=100.0,
    )
    ledger.add(
        receipt_id="two",
        capability_id=1,
        proof_kind=ProofKind.TEST,
        subject="test_a.py",
        subject_sha256=_sha(b"test-a"),
        verifier="ci",
        observed_at=101.0,
    )
    anchor = ledger.create_anchor(current_revision="rev-A", issued_at=102.0)
    assert ledger.verify_anchor(anchor, current_revision="rev-A") is True

    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(lines[0] + "\n", encoding="utf-8")

    # A valid HMAC prefix is internally consistent, so raw chain verification
    # alone cannot prove it is the latest state. The externally retained anchor
    # is what detects rollback/truncation.
    assert ledger.verify_chain() is True
    assert ledger.verify_anchor(anchor, current_revision="rev-A") is False
    assert ledger.verify_chain(anchor_token=anchor, current_revision="rev-A") is False


def test_mixed_legacy_sha_prefix_is_sealed_by_first_hmac_event_and_anchor(tmp_path):
    path = tmp_path / "proofs.jsonl"
    plain = ProofLedger(str(path))
    code_sha = _sha(b"code-v1")
    plain.add(
        receipt_id="legacy-code",
        capability_id=1,
        proof_kind=ProofKind.CODE,
        subject="research_engine/question.py",
        subject_sha256=code_sha,
        verifier="ci",
        observed_at=90.0,
    )

    keyed = ProofLedger(str(path), integrity_key=KEY)
    test_sha = _sha(b"test-v1")
    keyed.add(
        receipt_id="keyed-test",
        capability_id=1,
        proof_kind=ProofKind.TEST,
        subject="tests/test_question.py",
        subject_sha256=test_sha,
        verifier="ci",
        observed_at=100.0,
    )
    anchor = keyed.create_anchor(current_revision="rev-A", issued_at=101.0)
    evidence, status = keyed.evidence(
        current_hashes={
            "research_engine/question.py": code_sha,
            "tests/test_question.py": test_sha,
        },
        now=101.0,
        current_revision="rev-A",
        anchor_token=anchor,
        require_cryptographic_integrity=True,
    )
    assert evidence[1].has(ProofKind.CODE)
    assert evidence[1].has(ProofKind.TEST)
    assert status.unkeyed_events == 1
    assert status.keyed_events == 1
    assert status.cryptographic_integrity is True

    # Attacker rewrites the old SHA event and recomputes its plain hash. The
    # first HMAC event still commits to the original prefix hash, so the chain
    # fails and cannot be repaired without the external key.
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["subject"] = "research_engine/forged.py"
    rows[0]["event_hash"] = _recompute_plain_event_hash(rows[0])
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows)
        + "\n",
        encoding="utf-8",
    )
    assert keyed.verify_chain() is False
    with pytest.raises(ValueError, match="integrity failure"):
        keyed.evidence(
            current_hashes={},
            now=102.0,
            current_revision="rev-A",
            anchor_token=anchor,
            require_cryptographic_integrity=True,
        )


def test_anchor_token_tampering_wrong_key_and_unkeyed_anchor_creation_fail_closed(tmp_path):
    path = tmp_path / "proofs.jsonl"
    ledger = ProofLedger(str(path), integrity_key=KEY)
    ledger.add(
        receipt_id="one",
        capability_id=1,
        proof_kind=ProofKind.CODE,
        subject="a.py",
        subject_sha256=_sha(b"a"),
        verifier="ci",
        observed_at=100.0,
    )
    anchor = ledger.create_anchor(current_revision="rev-A", issued_at=101.0)
    assert ledger.verify_anchor(anchor, current_revision="rev-A") is True

    replacement = "A" if anchor[-1] != "A" else "B"
    tampered = anchor[:-1] + replacement
    assert ledger.verify_anchor(tampered, current_revision="rev-A") is False
    assert ProofLedger(str(path), integrity_key=WRONG_KEY).verify_anchor(
        anchor, current_revision="rev-A"
    ) is False

    unkeyed_path = tmp_path / "unkeyed.jsonl"
    unkeyed = ProofLedger(str(unkeyed_path))
    unkeyed.add(
        receipt_id="plain",
        capability_id=1,
        proof_kind=ProofKind.CODE,
        subject="a.py",
        subject_sha256=_sha(b"a"),
        verifier="ci",
        observed_at=100.0,
    )
    with pytest.raises(ValueError, match="integrity_key"):
        unkeyed.create_anchor(current_revision="rev-A", issued_at=101.0)


def test_keyed_history_cannot_be_extended_by_writer_without_key(tmp_path):
    path = tmp_path / "proofs.jsonl"
    keyed = ProofLedger(str(path), integrity_key=KEY)
    keyed.add(
        receipt_id="keyed",
        capability_id=1,
        proof_kind=ProofKind.CODE,
        subject="a.py",
        subject_sha256=_sha(b"a"),
        verifier="ci",
        observed_at=100.0,
    )
    no_key = ProofLedger(str(path))
    with pytest.raises(ValueError, match="integrity failure|integrity_key"):
        no_key.add(
            receipt_id="downgrade",
            capability_id=1,
            proof_kind=ProofKind.TEST,
            subject="test_a.py",
            subject_sha256=_sha(b"test"),
            verifier="ci",
            observed_at=101.0,
        )
