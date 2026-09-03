from research_engine.capability_registry import ProofKind
from research_engine.post_deployment_attestor import (
    ValidatedDeploymentReceipt,
    _MAX_AGE_SECONDS,
    _proof_valid_until,
)


def _receipt(created_at_epoch: int = 9_900) -> ValidatedDeploymentReceipt:
    return ValidatedDeploymentReceipt(
        revision="a" * 40,
        created_at_epoch=created_at_epoch,
        project_id="project",
        model_id="model",
        deployment_id="deployment",
        runtime_instance_id="runtime",
        observer_id="observer",
        state_sha256="b" * 64,
        event_head_hash="c" * 64,
        baseline_hash="d" * 64,
        batch_ids=("b1", "b2", "b3"),
        batch_analysis_hashes=("1" * 64, "2" * 64, "3" * 64),
        receipt_sha256="e" * 64,
    )


def test_runtime_and_live_proofs_expire_from_observer_receipt_time():
    receipt = _receipt()
    expected = float(receipt.created_at_epoch + _MAX_AGE_SECONDS)
    assert _proof_valid_until(ProofKind.RUNTIME, receipt) == expected
    assert _proof_valid_until(ProofKind.LIVE, receipt) == expected


def test_non_live_proofs_do_not_inherit_runtime_expiry():
    receipt = _receipt()
    assert _proof_valid_until(ProofKind.PERSISTENCE, receipt) is None
    assert _proof_valid_until(ProofKind.EXECUTION, receipt) is None
    assert _proof_valid_until(ProofKind.REPRODUCIBILITY, receipt) is None


def test_re_attestation_cannot_slide_the_live_freshness_window():
    receipt = _receipt(created_at_epoch=100)
    first = _proof_valid_until(ProofKind.LIVE, receipt)
    # The helper has no attestation-time input by design: running the attestor
    # later cannot extend evidence beyond the observer receipt's fixed ceiling.
    second = _proof_valid_until(ProofKind.LIVE, receipt)
    assert first == second == float(100 + _MAX_AGE_SECONDS)
