from pathlib import Path

import pytest

import research_engine.human_factors_attestor as attestor_mod
from research_engine.capability_registry import ProofKind
from research_engine.human_factors import HumanFactorsRequirement, HumanStudyEvidence
from research_engine.human_factors_attestor import (
    HumanFactorsExternalObservation,
    attest_human_factors_external,
    attest_human_factors_software,
    run_human_factors_benchmark,
)
from research_engine.maturity_proof import ProofLedger


KEY = b"H" * 32
NOW = 80_000.0


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _requirement():
    return HumanFactorsRequirement(
        requirement_id="hf-field-task",
        task_id="critical-task",
        minimum_participants=4,
        minimum_task_success=0.75,
        maximum_critical_error_rate=0.25,
        maximum_adverse_event_rate=0.05,
        maximum_p95_completion_seconds=20.0,
        maximum_p95_workload_score=70.0,
        require_real_humans=True,
        require_field_or_operational=True,
        require_independent=False,
        require_ethics_review=True,
        require_consent=True,
        require_safety_review=True,
    )


def _study(*, real=True, environment="FIELD", safety=True):
    return HumanStudyEvidence(
        study_id="field-study-1",
        requirement_id="hf-field-task",
        task_id="critical-task",
        environment=environment,
        provenance_ref="external-study:study-1",
        participant_count=4,
        successful_tasks=4,
        attempted_tasks=4,
        critical_errors=0,
        adverse_events=0,
        completion_seconds=(8.0, 9.0, 10.0, 11.0),
        workload_scores=(20.0, 30.0, 40.0, 50.0),
        real_humans_observed=real,
        independent=True,
        ethics_reviewed=True,
        consent_documented=True,
        safety_reviewed=safety,
        representative_sample_proven=False,
    )


def _observation(*, real=True, environment="FIELD", safety=True, hardware=True, officer=True):
    return HumanFactorsExternalObservation(
        requirement=_requirement(),
        studies=(_study(real=real, environment=environment, safety=safety),),
        hardware_observed=hardware,
        hardware_provenance_ref="hardware-lab:fixture-42" if hardware else "",
        safety_officer_reviewed=officer,
        safety_review_ref="safety-board:review-42" if officer else "",
    )


def test_software_benchmark_is_deterministic_and_does_not_invent_human_truth():
    first = run_human_factors_benchmark()
    second = run_human_factors_benchmark()
    assert first == second
    assert first["benchmark_passed"] is True
    assert all(first["checks"].values())
    report = first["report"]
    assert report["agent_simulation_promoted_to_human_evidence"] is False
    assert report["population_generalization_proven"] is False
    assert report["human_safety_truth_proven"] is False
    assert report["external_certification_claimed"] is False


def test_software_execution_and_reproducibility_are_separate_receipts(tmp_path):
    ledger_path = tmp_path / "human-factors.jsonl"
    first = attest_human_factors_software(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        proof_kind=ProofKind.EXECUTION,
        run_reference="execution:c72:ci",
        now=NOW,
    )
    assert first.receipts_added == 1
    assert first.proof_kind == ProofKind.EXECUTION.value
    second = attest_human_factors_software(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        proof_kind=ProofKind.REPRODUCIBILITY,
        run_reference="reproducibility:c72:ci",
        now=NOW + 1,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 1
    assert second.proof_kind == ProofKind.REPRODUCIBILITY.value
    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [row for row in ledger._events() if row.get("event_type") == "ADD"]  # noqa: SLF001
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.EXECUTION.value,
        ProofKind.REPRODUCIBILITY.value,
    }
    assert ProofKind.HARDWARE.value not in {row["proof_kind"] for row in rows}
    assert ProofKind.SAFETY.value not in {row["proof_kind"] for row in rows}


def test_software_attestor_cannot_mint_hardware_or_safety(tmp_path):
    for kind in (ProofKind.HARDWARE, ProofKind.SAFETY):
        with pytest.raises(ValueError, match="only accepts execution/reproducibility"):
            attest_human_factors_software(
                repo_root=_root(),
                ledger_path=tmp_path / f"{kind.value}.jsonl",
                integrity_key=KEY,
                proof_kind=kind,
                run_reference=f"{kind.value}:c72:ci",
                now=NOW,
            )


def test_hardware_route_requires_hash_bound_real_field_observation(tmp_path):
    observation = _observation()
    ledger_path = tmp_path / "hardware.jsonl"
    result = attest_human_factors_external(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        proof_kind=ProofKind.HARDWARE,
        observation=observation,
        expected_bundle_sha256=observation.sha256(),
        run_reference="hardware:c72:lab-42",
        now=NOW,
    )
    assert result.receipts_added == 1
    assert result.proof_kind == ProofKind.HARDWARE.value
    assert result.population_generalization_proven is False
    assert result.universal_human_safety_proven is False
    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [row for row in ledger._events() if row.get("event_type") == "ADD"]  # noqa: SLF001
    assert len(rows) == 1
    assert rows[0]["subject"] == "capability-72-hardware-observation"
    assert rows[0]["verifier"] == "trusted-hardware-lab"


def test_safety_route_requires_separate_officer_review_and_adverse_event_contract(tmp_path):
    observation = _observation()
    ledger_path = tmp_path / "safety.jsonl"
    result = attest_human_factors_external(
        repo_root=_root(),
        ledger_path=ledger_path,
        integrity_key=KEY,
        proof_kind=ProofKind.SAFETY,
        observation=observation,
        expected_bundle_sha256=observation.sha256(),
        run_reference="safety:c72:review-42",
        now=NOW,
    )
    assert result.receipts_added == 1
    assert result.proof_kind == ProofKind.SAFETY.value
    assert result.universal_human_safety_proven is False
    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [row for row in ledger._events() if row.get("event_type") == "ADD"]  # noqa: SLF001
    assert rows[0]["subject"] == "capability-72-safety-gate"
    assert rows[0]["verifier"] == "trusted-safety-officer"


def test_external_bundle_digest_mismatch_fails_before_ledger_creation(tmp_path):
    observation = _observation()
    target = tmp_path / "bad-digest.jsonl"
    with pytest.raises(ValueError, match="bundle digest mismatch"):
        attest_human_factors_external(
            repo_root=_root(),
            ledger_path=target,
            integrity_key=KEY,
            proof_kind=ProofKind.HARDWARE,
            observation=observation,
            expected_bundle_sha256="0" * 64,
            run_reference="hardware:c72:lab-42",
            now=NOW,
        )
    assert not target.exists()


def test_simulation_or_fake_humans_cannot_be_promoted_to_hardware(tmp_path):
    for observation in (
        _observation(real=False),
        _observation(environment="SIMULATION"),
        _observation(hardware=False),
    ):
        target = tmp_path / f"blocked-{observation.sha256()[:8]}.jsonl"
        with pytest.raises(ValueError):
            attest_human_factors_external(
                repo_root=_root(),
                ledger_path=target,
                integrity_key=KEY,
                proof_kind=ProofKind.HARDWARE,
                observation=observation,
                expected_bundle_sha256=observation.sha256(),
                run_reference="hardware:c72:lab-42",
                now=NOW,
            )
        assert not target.exists()


def test_missing_safety_review_cannot_mint_safety(tmp_path):
    for observation in (
        _observation(safety=False),
        _observation(officer=False),
    ):
        target = tmp_path / f"unsafe-{observation.sha256()[:8]}.jsonl"
        with pytest.raises(ValueError):
            attest_human_factors_external(
                repo_root=_root(),
                ledger_path=target,
                integrity_key=KEY,
                proof_kind=ProofKind.SAFETY,
                observation=observation,
                expected_bundle_sha256=observation.sha256(),
                run_reference="safety:c72:review-42",
                now=NOW,
            )
        assert not target.exists()


def test_cross_capability_reference_is_rejected_before_ledger_creation(tmp_path):
    target = tmp_path / "wrong-ref.jsonl"
    with pytest.raises(ValueError, match="not capability-bound|not allowed"):
        attest_human_factors_software(
            repo_root=_root(),
            ledger_path=target,
            integrity_key=KEY,
            proof_kind=ProofKind.EXECUTION,
            run_reference="execution:c71:ci",
            now=NOW,
        )
    assert not target.exists()


def test_failed_or_nondeterministic_benchmark_cannot_mint(monkeypatch, tmp_path):
    original = attestor_mod.run_human_factors_benchmark
    target = tmp_path / "failed.jsonl"

    def failed():
        payload = dict(original())
        payload["benchmark_passed"] = False
        return payload

    monkeypatch.setattr(attestor_mod, "run_human_factors_benchmark", failed)
    with pytest.raises(ValueError, match="benchmark failed"):
        attest_human_factors_software(
            repo_root=_root(),
            ledger_path=target,
            integrity_key=KEY,
            proof_kind=ProofKind.EXECUTION,
            run_reference="execution:c72:ci",
            now=NOW,
        )
    assert not target.exists()

    counter = {"n": 0}

    def changing():
        payload = dict(original())
        counter["n"] += 1
        payload["nonce"] = counter["n"]
        return payload

    monkeypatch.setattr(attestor_mod, "run_human_factors_benchmark", changing)
    with pytest.raises(ValueError, match="not deterministic"):
        attest_human_factors_software(
            repo_root=_root(),
            ledger_path=target,
            integrity_key=KEY,
            proof_kind=ProofKind.REPRODUCIBILITY,
            run_reference="reproducibility:c72:ci",
            now=NOW,
        )
    assert not target.exists()
