from research_engine.capability_registry import (
    CAPABILITY_BY_ID,
    CapabilityEvidence,
    ProofKind,
    assess_capabilities,
)


def test_manufacturing_reality_requires_wiring_execution_repro_hardware_and_safety():
    capability = CAPABILITY_BY_ID[71]
    for proof in (
        ProofKind.CODE,
        ProofKind.TEST,
        ProofKind.WIRING,
        ProofKind.EXECUTION,
        ProofKind.REPRODUCIBILITY,
        ProofKind.HARDWARE,
        ProofKind.SAFETY,
    ):
        assert proof in capability.required_proofs


def test_software_and_wiring_proofs_cannot_fake_real_factory_validation():
    evidence = {
        71: CapabilityEvidence(
            capability_id=71,
            proofs={
                ProofKind.CODE: ("research_engine/manufacturing_reality.py",),
                ProofKind.TEST: ("tests/test_manufacturing_reality.py",),
                ProofKind.WIRING: ("tests/test_manufacturing_reality_wiring.py",),
                ProofKind.EXECUTION: ("capability-71-execution-run",),
                ProofKind.REPRODUCIBILITY: ("capability-71-reproducibility-run",),
            },
        )
    }
    result = assess_capabilities(evidence).results[70]
    assert result.status == "INCOMPLETE"
    assert result.missing_proofs == (ProofKind.HARDWARE, ProofKind.SAFETY)


def test_even_hardware_without_safety_cannot_verify_manufacturing_reality():
    proofs = {
        ProofKind.CODE: ("code",),
        ProofKind.TEST: ("test",),
        ProofKind.WIRING: ("wiring",),
        ProofKind.EXECUTION: ("execution",),
        ProofKind.REPRODUCIBILITY: ("repro",),
        ProofKind.HARDWARE: ("hardware",),
    }
    result = assess_capabilities({
        71: CapabilityEvidence(capability_id=71, proofs=proofs)
    }).results[70]
    assert result.status == "INCOMPLETE"
    assert result.missing_proofs == (ProofKind.SAFETY,)