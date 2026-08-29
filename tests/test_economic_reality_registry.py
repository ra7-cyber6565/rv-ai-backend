from research_engine.capability_registry import (
    CAPABILITY_BY_ID,
    CapabilityEvidence,
    ProofKind,
    assess_capabilities,
)


def test_economic_reality_requires_wiring_execution_and_reproducibility():
    capability = CAPABILITY_BY_ID[100]
    for proof in (
        ProofKind.CODE,
        ProofKind.TEST,
        ProofKind.WIRING,
        ProofKind.EXECUTION,
        ProofKind.REPRODUCIBILITY,
    ):
        assert proof in capability.required_proofs

    evidence = {
        100: CapabilityEvidence(
            capability_id=100,
            proofs={
                ProofKind.CODE: ("research_engine/economic_reality.py",),
                ProofKind.TEST: ("tests/test_economic_reality.py",),
                ProofKind.WIRING: ("tests/test_economic_reality.py",),
            },
        )
    }
    result = assess_capabilities(evidence).results[99]
    assert result.status == "INCOMPLETE"
    assert result.missing_proofs == (
        ProofKind.EXECUTION,
        ProofKind.REPRODUCIBILITY,
    )
