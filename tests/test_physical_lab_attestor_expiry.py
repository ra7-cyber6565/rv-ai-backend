from research_engine.capability_registry import ProofKind
from research_engine.physical_lab_attestor import (
    ValidatedPhysicalLabReceipt,
    _MAX_AGE_SECONDS,
    _proof_valid_until,
)


def _receipt(created_at=9_950):
    return ValidatedPhysicalLabReceipt(
        revision="a" * 40,
        created_at_epoch=created_at,
        live_observed_at_epoch=created_at - 10,
        boundary_sha256="b" * 64,
        observer_id="observer-1",
        hardware_system_id="rig-1",
        session_ids=("session-a", "session-b"),
        receipt_sha256="c" * 64,
    )


def test_runtime_and_live_expire_from_signed_receipt_creation_time():
    receipt = _receipt()
    expected = float(receipt.created_at_epoch + _MAX_AGE_SECONDS)
    assert _proof_valid_until(ProofKind.RUNTIME, receipt) == expected
    assert _proof_valid_until(ProofKind.LIVE, receipt) == expected


def test_re_attestation_time_cannot_refresh_runtime_or_live_expiry():
    receipt = _receipt(created_at=12_345)
    first = _proof_valid_until(ProofKind.RUNTIME, receipt)
    later = _proof_valid_until(ProofKind.RUNTIME, receipt)
    assert first == later == float(12_345 + _MAX_AGE_SECONDS)


def test_non_live_physical_proofs_are_not_given_fake_time_expiry():
    receipt = _receipt()
    for kind in (
        ProofKind.EXECUTION,
        ProofKind.REPRODUCIBILITY,
        ProofKind.HARDWARE,
        ProofKind.SAFETY,
    ):
        assert _proof_valid_until(kind, receipt) is None
