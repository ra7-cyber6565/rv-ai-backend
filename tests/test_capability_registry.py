from research_engine.capability_registry import (
    CAPABILITIES,
    CAPABILITY_BY_ID,
    CapabilityEvidence,
    ProofKind,
    assess_capabilities,
    evidence_item,
)


def test_registry_is_exactly_142_contiguous_unique_capabilities():
    assert len(CAPABILITIES) == 142
    assert [item.id for item in CAPABILITIES] == list(range(1, 143))
    assert len({item.name for item in CAPABILITIES}) == 142
    assert CAPABILITY_BY_ID[97].name == "Holdout Vault"
    assert CAPABILITY_BY_ID[142].name == "Final Evidence Packet"


def test_registry_fails_closed_without_proof():
    report = assess_capabilities({})
    assert report.verified == 0
    assert report.total == 142
    assert report.proof_completion_score == 0.0
    assert report.all_verified is False
    assert report.blocking_capability_ids == tuple(range(1, 143))


def test_max_level_requires_more_than_code_and_test_for_real_world_capabilities():
    hardware = CAPABILITY_BY_ID[125]
    assert ProofKind.CODE in hardware.required_proofs
    assert ProofKind.TEST in hardware.required_proofs
    assert ProofKind.EXECUTION in hardware.required_proofs
    assert ProofKind.HARDWARE in hardware.required_proofs
    assert ProofKind.SAFETY in hardware.required_proofs
    assert ProofKind.REPRODUCIBILITY in hardware.required_proofs

    continuous = CAPABILITY_BY_ID[135]
    assert ProofKind.PERSISTENCE in continuous.required_proofs
    assert ProofKind.RUNTIME in continuous.required_proofs
    assert ProofKind.LIVE in continuous.required_proofs


def test_a_filename_or_code_only_can_never_fake_verified():
    evidence = {
        16: CapabilityEvidence(
            capability_id=16,
            proofs={
                ProofKind.CODE: ("research_engine/agent_manager.py",),
                ProofKind.TEST: ("tests/test_agent_manager.py",),
            },
        )
    }
    result = assess_capabilities(evidence).results[15]
    assert result.status == "INCOMPLETE"
    assert ProofKind.INDEPENDENT in result.missing_proofs


def test_100_score_only_when_every_required_proof_exists():
    evidence = {}
    for spec in CAPABILITIES:
        evidence[spec.id] = CapabilityEvidence(
            capability_id=spec.id,
            proofs={proof: (f"verified:{spec.id}:{proof.value}",) for proof in spec.required_proofs},
        )
    report = assess_capabilities(evidence)
    assert report.verified == 142
    assert report.proof_completion_score == 100.0
    assert report.all_verified is True
    assert report.blocking_capability_ids == ()


def test_evidence_item_rejects_unknown_ids_and_proof_names():
    item = evidence_item(1, code=["a.py"], test=["test_a.py"])
    assert item.has(ProofKind.CODE)
    assert item.has(ProofKind.TEST)

    import pytest

    with pytest.raises(ValueError):
        evidence_item(999, code=["x"])
    with pytest.raises(ValueError):
        evidence_item(1, nonsense=["x"])
