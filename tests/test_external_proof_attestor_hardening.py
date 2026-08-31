import hashlib
import json
from pathlib import Path

import pytest

from utils.release_identity import repository_identity

from research_engine.external_proof_attestor import (
    attest_external_proof,
    sign_external_receipt,
    validate_external_evidence_receipt,
)


LEDGER_KEY = b"L" * 32
VERIFIER_KEY = b"V" * 32
NOW = 100_000.0


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _revision() -> str:
    identity = repository_identity(_root())
    assert identity["available"] is True
    assert identity["clean"] is True
    return str(identity["revision"])


def _canonical(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _execution_receipt(*, reference="execution:c22:canonical-fixture"):
    evidence = {
        "run_id": "canonical-run-1",
        "started_at_epoch": NOW - 30,
        "finished_at_epoch": NOW - 10,
        "result_hash": "a" * 64,
        "exit_code": 0,
        "execution_complete": True,
        "truth_proven": False,
    }
    unsigned = {
        "schema_version": 1,
        "created_at_epoch": NOW,
        "implementation_revision": _revision(),
        "capability_id": 22,
        "proof_kind": "execution",
        "subject": "capability-22-execution-run",
        "verifier": "trusted-execution-attestor",
        "reference": reference,
        "protocol_hash": "b" * 64,
        "evidence": evidence,
        "evidence_hash": hashlib.sha256(_canonical(evidence)).hexdigest(),
    }
    return {
        **unsigned,
        "signature": sign_external_receipt(unsigned, verifier_key=VERIFIER_KEY),
    }


def test_pretty_and_compact_same_signed_receipt_have_same_identity(tmp_path):
    payload = _execution_receipt()
    pretty = tmp_path / "pretty.json"
    compact = tmp_path / "compact.json"
    pretty.write_text(json.dumps(payload, indent=4), encoding="utf-8")
    compact.write_bytes(_canonical(payload))
    assert pretty.read_bytes() != compact.read_bytes()

    first = validate_external_evidence_receipt(
        pretty,
        repo_root=_root(),
        expected_revision=_revision(),
        verifier_key=VERIFIER_KEY,
        now=NOW,
    )
    second = validate_external_evidence_receipt(
        compact,
        repo_root=_root(),
        expected_revision=_revision(),
        verifier_key=VERIFIER_KEY,
        now=NOW,
    )
    expected = hashlib.sha256(_canonical(payload)).hexdigest()
    assert first.receipt_sha256 == expected
    assert second.receipt_sha256 == expected


def test_reformatted_same_receipt_reuses_same_proof_not_second_identity(tmp_path):
    payload = _execution_receipt()
    pretty = tmp_path / "pretty.json"
    compact = tmp_path / "compact.json"
    pretty.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    compact.write_bytes(_canonical(payload))
    ledger = tmp_path / "proofs.jsonl"

    first = attest_external_proof(
        repo_root=_root(),
        evidence_receipt_path=pretty,
        ledger_path=ledger,
        ledger_integrity_key=LEDGER_KEY,
        verifier_key=VERIFIER_KEY,
        now=NOW,
    )
    second = attest_external_proof(
        repo_root=_root(),
        evidence_receipt_path=compact,
        ledger_path=ledger,
        ledger_integrity_key=LEDGER_KEY,
        verifier_key=VERIFIER_KEY,
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert first.receipt_sha256 == second.receipt_sha256
    assert first.receipts_added == 1
    assert second.receipts_added == 0
    assert second.receipts_reused == 1


@pytest.mark.parametrize(
    "bad_reference",
    [
        " execution:c22:leading-space",
        "execution:c22:trailing-space ",
        "execution:c22:contains space",
        "execution:c22:line\nbreak",
        "execution:c22:tab\tbreak",
    ],
)
def test_signed_noncanonical_reference_is_rejected_before_policy_attestation(tmp_path, bad_reference):
    # The receipt is genuinely signed *after* the bad reference is inserted.
    # The strict representation boundary must still reject it.
    payload = _execution_receipt(reference=bad_reference)
    path = tmp_path / "bad-reference.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="reference"):
        validate_external_evidence_receipt(
            path,
            repo_root=_root(),
            expected_revision=_revision(),
            verifier_key=VERIFIER_KEY,
            now=NOW,
        )


def test_external_receipt_inside_audited_repo_is_rejected_even_if_signed():
    target = _root() / ".external-proof-receipt-test.json"
    try:
        target.write_text(json.dumps(_execution_receipt()), encoding="utf-8")
        with pytest.raises(ValueError, match="outside"):
            attest_external_proof(
                repo_root=_root(),
                evidence_receipt_path=target,
                ledger_path=target.with_suffix(".ledger"),
                ledger_integrity_key=LEDGER_KEY,
                verifier_key=VERIFIER_KEY,
                now=NOW,
            )
    finally:
        target.unlink(missing_ok=True)
        target.with_suffix(".ledger").unlink(missing_ok=True)
