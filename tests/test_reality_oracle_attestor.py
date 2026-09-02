import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.maturity_proof import ProofLedger
from research_engine.reality_oracle import (
    evaluate_reality,
    freeze_prediction_contract,
    make_observation_receipt,
)
from research_engine.reality_oracle_attestor import (
    attest_reality_oracle_live,
    observation_signature,
    validate_live_oracle_receipt,
)
from utils.release_identity import repository_identity


KEY = b"R" * 32
OBSERVER_KEY = b"O" * 32
OBSERVER_ID = "lab-observer-1"
NOW = 2_000_000_000
LIVE_VALID_UNTIL = NOW - 60 + (2 * 60 * 60)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _iso(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="seconds")


def _revision():
    return str(repository_identity(_root())["revision"])


def _payload(*, revision=None, now=NOW, source_kind="sensor"):
    revision = revision or _revision()
    prediction = freeze_prediction_contract(
        prediction_id="pred-live-1",
        hypothesis_id="H-live",
        metric="temperature",
        unit="C",
        rule="interval",
        lower=19.0,
        upper=21.0,
        tolerance=0.0,
        preregistered_at=_iso(now - 3600),
        evaluation_after=_iso(now - 1800),
        protocol_hash="a" * 64,
    )
    observation = make_observation_receipt(
        observation_id="obs-live-1",
        metric="temperature",
        unit="C",
        observed_value=20.2,
        observed_at=_iso(now - 60),
        source_id="sensor-A",
        source_kind=source_kind,
        source_digest="b" * 64,
        raw_reference="lab://sensor-A/run/42",
    )
    evaluation = evaluate_reality(prediction, observation)
    signature = observation_signature(
        observer_key=OBSERVER_KEY,
        revision=revision,
        prediction_contract_hash=prediction.contract_hash,
        observation=observation.to_dict(),
    )
    return {
        "schema_version": 1,
        "created_at_epoch": now - 30,
        "implementation_revision": revision,
        "prediction": prediction.to_dict(),
        "observation": observation.to_dict(),
        "evaluation": evaluation.to_dict(),
        "observer": {"observer_id": OBSERVER_ID, "signature": signature},
    }


def _write(tmp_path, payload, name="oracle.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
    return path


def test_valid_signed_live_receipt_recomputes_everything(tmp_path):
    path = _write(tmp_path, _payload())
    receipt = validate_live_oracle_receipt(
        path,
        expected_revision=_revision(),
        observer_keys={OBSERVER_ID: OBSERVER_KEY},
        now=NOW,
    )
    assert receipt.observer_id == OBSERVER_ID
    assert receipt.observation_id == "obs-live-1"
    assert len(receipt.evaluation_hash) == 64
    assert len(receipt.sha256) == 64
    assert receipt.live_valid_until_epoch == LIVE_VALID_UNTIL
    assert receipt.live_valid_until_epoch > NOW


def test_wrong_key_or_tampered_observation_fails_signature(tmp_path):
    payload = _payload()
    path = _write(tmp_path, payload)
    with pytest.raises(ValueError, match="signature"):
        validate_live_oracle_receipt(
            path,
            expected_revision=_revision(),
            observer_keys={OBSERVER_ID: b"X" * 32},
            now=NOW,
        )

    payload = _payload()
    payload["observation"]["observed_value"] = 99.0
    tampered = _write(tmp_path, payload, "tampered.json")
    with pytest.raises(ValueError):
        validate_live_oracle_receipt(
            tampered,
            expected_revision=_revision(),
            observer_keys={OBSERVER_ID: OBSERVER_KEY},
            now=NOW,
        )


def test_static_dataset_cannot_mint_live_proof_even_with_valid_signature(tmp_path):
    payload = _payload(source_kind="dataset")
    path = _write(tmp_path, payload)
    with pytest.raises(ValueError, match="static dataset"):
        validate_live_oracle_receipt(
            path,
            expected_revision=_revision(),
            observer_keys={OBSERVER_ID: OBSERVER_KEY},
            now=NOW,
        )


def test_stale_and_future_receipts_fail_closed(tmp_path):
    stale = _payload(now=NOW - 10_000)
    stale_path = _write(tmp_path, stale, "stale.json")
    with pytest.raises(ValueError, match="stale"):
        validate_live_oracle_receipt(
            stale_path,
            expected_revision=_revision(),
            observer_keys={OBSERVER_ID: OBSERVER_KEY},
            now=NOW,
        )

    future = _payload(now=NOW + 10_000)
    future_path = _write(tmp_path, future, "future.json")
    with pytest.raises(ValueError, match="future"):
        validate_live_oracle_receipt(
            future_path,
            expected_revision=_revision(),
            observer_keys={OBSERVER_ID: OBSERVER_KEY},
            now=NOW,
        )


def test_wrong_revision_fails_before_any_proof(tmp_path):
    payload = _payload(revision="f" * 40)
    path = _write(tmp_path, payload)
    with pytest.raises(ValueError, match="revision mismatch"):
        validate_live_oracle_receipt(
            path,
            expected_revision=_revision(),
            observer_keys={OBSERVER_ID: OBSERVER_KEY},
            now=NOW,
        )


def test_tampered_evaluation_cannot_be_self_asserted(tmp_path):
    payload = _payload()
    payload["evaluation"]["status"] = (
        "MATCH" if payload["evaluation"]["status"] == "MISS" else "MISS"
    )
    path = _write(tmp_path, payload)
    with pytest.raises(ValueError, match="evaluation"):
        validate_live_oracle_receipt(
            path,
            expected_revision=_revision(),
            observer_keys={OBSERVER_ID: OBSERVER_KEY},
            now=NOW,
        )


def test_trusted_attestor_mints_only_required_reality_oracle_proofs(tmp_path):
    receipt_path = _write(tmp_path, _payload())
    ledger_path = tmp_path / "reality-proof.jsonl"
    result = attest_reality_oracle_live(
        repo_root=_root(),
        receipt_path=receipt_path,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observer_keys={OBSERVER_ID: OBSERVER_KEY},
        run_reference="reality-oracle:ci-fixture-1",
        now=NOW,
    )
    assert result.audit.audit_valid is True
    assert result.receipts_added == 4
    assert result.truth_proven is False
    assert result.observation_authenticity_verified is True
    assert result.live_observation_verified is True

    capability = result.audit.maturity_report.results[40]
    for kind in (
        ProofKind.EXECUTION,
        ProofKind.REPRODUCIBILITY,
        ProofKind.RUNTIME,
        ProofKind.LIVE,
    ):
        assert kind not in capability.missing_proofs
    assert ProofKind.CODE in capability.missing_proofs
    assert ProofKind.TEST in capability.missing_proofs

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row
        for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
    ]
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
        ProofKind.RUNTIME.value,
        ProofKind.LIVE.value,
    }
    assert {row["verifier"] for row in rows} == {"trusted-live-observer"}
    by_kind = {row["proof_kind"]: row for row in rows}
    assert by_kind[ProofKind.EXECUTION.value]["valid_until"] is None
    assert by_kind[ProofKind.REPRODUCIBILITY.value]["valid_until"] is None
    assert by_kind[ProofKind.RUNTIME.value]["valid_until"] == LIVE_VALID_UNTIL
    assert by_kind[ProofKind.LIVE.value]["valid_until"] == LIVE_VALID_UNTIL
    assert ProofKind.HARDWARE.value not in by_kind
    assert ProofKind.INDEPENDENT.value not in by_kind

    evidence, status = ledger.evidence(
        current_hashes={},
        now=LIVE_VALID_UNTIL,
        current_revision=result.revision,
        anchor_token=result.anchor_token,
        require_cryptographic_integrity=True,
    )
    assert status.expired_receipts == 2
    proofs = evidence[41].proofs
    assert ProofKind.EXECUTION in proofs
    assert ProofKind.REPRODUCIBILITY in proofs
    assert ProofKind.RUNTIME not in proofs
    assert ProofKind.LIVE not in proofs


def test_existing_ledger_requires_prior_anchor_and_is_idempotent(tmp_path):
    receipt_path = _write(tmp_path, _payload())
    ledger_path = tmp_path / "reality-proof.jsonl"
    first = attest_reality_oracle_live(
        repo_root=_root(),
        receipt_path=receipt_path,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observer_keys={OBSERVER_ID: OBSERVER_KEY},
        run_reference="reality-oracle:ci-fixture-2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_reality_oracle_live(
            repo_root=_root(),
            receipt_path=receipt_path,
            ledger_path=ledger_path,
            integrity_key=KEY,
            observer_keys={OBSERVER_ID: OBSERVER_KEY},
            run_reference="reality-oracle:ci-fixture-2",
            now=NOW + 1,
        )
    second = attest_reality_oracle_live(
        repo_root=_root(),
        receipt_path=receipt_path,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observer_keys={OBSERVER_ID: OBSERVER_KEY},
        run_reference="reality-oracle:ci-fixture-2",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 4


def test_replaying_same_observation_cannot_extend_live_validity(tmp_path):
    receipt_path = _write(tmp_path, _payload())
    ledger_path = tmp_path / "reality-proof.jsonl"
    first = attest_reality_oracle_live(
        repo_root=_root(),
        receipt_path=receipt_path,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observer_keys={OBSERVER_ID: OBSERVER_KEY},
        run_reference="reality-oracle:ci-replay",
        now=NOW,
    )
    second = attest_reality_oracle_live(
        repo_root=_root(),
        receipt_path=receipt_path,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observer_keys={OBSERVER_ID: OBSERVER_KEY},
        run_reference="reality-oracle:ci-replay",
        now=NOW + 120,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 4
    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row
        for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD"
        and row.get("proof_kind") in {ProofKind.RUNTIME.value, ProofKind.LIVE.value}
    ]
    assert len(rows) == 2
    assert {row["valid_until"] for row in rows} == {LIVE_VALID_UNTIL}


def test_wrong_reference_prefix_fails_before_ledger_creation(tmp_path):
    receipt_path = _write(tmp_path, _payload())
    ledger_path = tmp_path / "reality-proof.jsonl"
    with pytest.raises(ValueError, match="run_reference"):
        attest_reality_oracle_live(
            repo_root=_root(),
            receipt_path=receipt_path,
            ledger_path=ledger_path,
            integrity_key=KEY,
            observer_keys={OBSERVER_ID: OBSERVER_KEY},
            run_reference="self-asserted:fake",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_ledger_inside_repo_is_rejected(tmp_path):
    receipt_path = _write(tmp_path, _payload())
    target = _root() / ".reality-proof-test.jsonl"
    try:
        with pytest.raises(ValueError, match="outside"):
            attest_reality_oracle_live(
                repo_root=_root(),
                receipt_path=receipt_path,
                ledger_path=target,
                integrity_key=KEY,
                observer_keys={OBSERVER_ID: OBSERVER_KEY},
                run_reference="reality-oracle:inside-repo",
                now=NOW,
            )
    finally:
        target.unlink(missing_ok=True)
