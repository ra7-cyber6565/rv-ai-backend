from pathlib import Path

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.maturity_attestation_readiness import audit_attestation_readiness
from research_engine.maturity_proof import ProofLedger
from research_engine.visual_science_execution_attestor import (
    attest_visual_science_execution,
    run_visual_science_benchmark,
)


ROOT = Path(__file__).resolve().parents[1]
KEY = b"V" * 32
NOW = 40_000.0


def _route(report, capability_id, proof_kind):
    capability = next(
        item for item in report.capabilities if item.capability_id == capability_id
    )
    return next(item for item in capability.routes if item.proof_kind is proof_kind)


def test_locked_visual_benchmark_passes_and_is_deterministic():
    first = run_visual_science_benchmark()
    second = run_visual_science_benchmark()
    assert first == second
    assert first["benchmark_passed"] is True
    assert len(first["benchmark_sha256"]) == 64
    assert all(first["checks"].values())


def test_visual_benchmark_keeps_scope_and_intent_boundaries_explicit():
    result = run_visual_science_benchmark()
    assert result["normalized_structured_specs_only"] is True
    assert result["computer_vision_executed"] is False
    assert result["ocr_executed"] is False
    assert result["author_fraud_inferred"] is False
    assert result["truth_proven"] is False
    assert result["reports"]["low_extraction"]["strong_claim_allowed"] is False
    assert result["reports"]["truncated"]["intent_inference_allowed"] is False


def test_readiness_has_specialized_visual_execution_and_repro_routes():
    report = audit_attestation_readiness(ROOT)
    for capability_id in (107, 108):
        for kind in (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY):
            route = _route(report, capability_id, kind)
            assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
            assert route.attestor_id == "visual-science-benchmark"
            assert route.external_required is True
            assert route.verifiers == ("trusted-operator",)
            assert route.subjects == ("visual-science-benchmark",)


def test_attestor_mints_only_execution_and_repro_for_both_capabilities(tmp_path):
    ledger_path = tmp_path / "proofs.jsonl"
    result = attest_visual_science_execution(
        repo_root=ROOT,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="visual-science:ci:1",
        now=NOW,
    )
    assert result.receipts_added == 4
    assert result.receipts_reused == 0
    assert result.audit.audit_valid is True
    assert result.normalized_structured_specs_only is True
    assert result.computer_vision_executed is False
    assert result.ocr_executed is False
    assert result.author_fraud_inferred is False
    assert result.truth_proven is False

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [
        row for row in ledger._events()  # noqa: SLF001
        if row.get("event_type") == "ADD" and row.get("capability_id") in {107, 108}
    ]
    assert len(rows) == 4
    assert {row["capability_id"] for row in rows} == {107, 108}
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
    }
    assert {row["subject"] for row in rows} == {"visual-science-benchmark"}
    assert {row["verifier"] for row in rows} == {"trusted-operator"}


def test_wrong_reference_prefix_fails_before_ledger_mutation(tmp_path):
    ledger_path = tmp_path / "proofs.jsonl"
    with pytest.raises(ValueError, match="run_reference is not allowed"):
        attest_visual_science_execution(
            repo_root=ROOT,
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="self-asserted:1",
            now=NOW,
        )
    assert not ledger_path.exists()


def test_existing_ledger_requires_anchor_and_reuses_exact_receipts(tmp_path):
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_visual_science_execution(
        repo_root=ROOT,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="visual-science:ci:2",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_visual_science_execution(
            repo_root=ROOT,
            ledger_path=ledger_path,
            integrity_key=KEY,
            run_reference="visual-science:ci:2",
            now=NOW + 1,
        )
    second = attest_visual_science_execution(
        repo_root=ROOT,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="visual-science:ci:2",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 4


def test_wrong_prior_anchor_key_fails_closed(tmp_path):
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_visual_science_execution(
        repo_root=ROOT,
        ledger_path=ledger_path,
        integrity_key=KEY,
        run_reference="visual-science:ci:3",
        now=NOW,
    )
    with pytest.raises(ValueError, match="prior anchor continuity"):
        attest_visual_science_execution(
            repo_root=ROOT,
            ledger_path=ledger_path,
            integrity_key=b"Z" * 32,
            run_reference="visual-science:ci:3",
            now=NOW + 1,
            prior_anchor_token=first.anchor_token,
            prior_revision=first.revision,
        )
