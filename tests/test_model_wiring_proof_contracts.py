import json
from pathlib import Path

from research_engine.capability_registry import (
    CAPABILITY_BY_ID,
    CapabilityEvidence,
    ProofKind,
    assess_capabilities,
)


def _policy_rules():
    path = Path(__file__).resolve().parents[1] / "config" / "maturity_proof_policy.json"
    return json.loads(path.read_text(encoding="utf-8"))["rules"]


def _matching(capability_id, proof_kind):
    return [
        rule for rule in _policy_rules()
        if rule["capability_id"] == capability_id
        and rule["proof_kind"] == proof_kind.value
    ]


def test_neural_symbolic_and_world_model_require_wiring_execution_and_reproducibility():
    for capability_id in (67, 68):
        capability = CAPABILITY_BY_ID[capability_id]
        for proof in (
            ProofKind.CODE,
            ProofKind.TEST,
            ProofKind.WIRING,
            ProofKind.EXECUTION,
            ProofKind.REPRODUCIBILITY,
        ):
            assert proof in capability.required_proofs

        evidence = {
            capability_id: CapabilityEvidence(
                capability_id=capability_id,
                proofs={
                    ProofKind.CODE: ("code",),
                    ProofKind.TEST: ("test",),
                    ProofKind.WIRING: ("wiring",),
                },
            )
        }
        result = assess_capabilities(evidence).results[capability_id - 1]
        assert result.status == "INCOMPLETE"
        assert ProofKind.EXECUTION in result.missing_proofs
        assert ProofKind.REPRODUCIBILITY in result.missing_proofs


def test_readiness_requires_real_production_wiring_but_not_fake_external_execution():
    capability = CAPABILITY_BY_ID[70]
    assert ProofKind.WIRING in capability.required_proofs
    assert ProofKind.EXECUTION not in capability.required_proofs
    assert ProofKind.HARDWARE not in capability.required_proofs


def test_committed_policy_maps_code_test_and_wiring_for_all_three_capabilities():
    expected = {
        67: {
            ProofKind.CODE: {"research_engine/neural_symbolic_hybrid.py", "research_engine/neural_symbolic_wiring.py"},
            ProofKind.TEST: {"tests/test_neural_symbolic_hybrid.py", "tests/test_neural_symbolic_wiring.py"},
            ProofKind.WIRING: {"tests/test_neural_symbolic_wiring.py"},
        },
        68: {
            ProofKind.CODE: {"research_engine/world_model.py", "research_engine/world_model_wiring.py"},
            ProofKind.TEST: {"tests/test_world_model.py", "tests/test_world_model_wiring.py"},
            ProofKind.WIRING: {"tests/test_world_model_wiring.py"},
        },
        70: {
            ProofKind.CODE: {"research_engine/technology_readiness.py", "research_engine/technology_readiness_wiring.py"},
            ProofKind.TEST: {"tests/test_technology_readiness.py", "tests/test_technology_readiness_wiring.py"},
            ProofKind.WIRING: {"tests/test_technology_readiness_wiring.py"},
        },
    }
    for capability_id, proof_map in expected.items():
        for proof_kind, subjects in proof_map.items():
            rules = _matching(capability_id, proof_kind)
            assert len(rules) == 1
            assert set(rules[0]["subjects"]) == subjects
            assert rules[0]["verifiers"] == ["github-actions"]
            if proof_kind is ProofKind.WIRING:
                assert rules[0]["reference_prefixes"] == ["github-actions:"]


def test_green_ci_policy_does_not_mint_execution_for_neural_or_world_model():
    for capability_id in (67, 68):
        execution_rules = _matching(capability_id, ProofKind.EXECUTION)
        assert not any("github-actions" in rule["verifiers"] for rule in execution_rules)
        repro_rules = _matching(capability_id, ProofKind.REPRODUCIBILITY)
        assert not any("github-actions" in rule["verifiers"] for rule in repro_rules)
