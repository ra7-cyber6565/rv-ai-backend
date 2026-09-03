from pathlib import Path

from research_engine.capability_registry import CAPABILITY_BY_ID, ProofKind
from research_engine.maturity_policy_coverage import audit_repository_policy_coverage


def test_causal_mechanism_requires_production_wiring_but_not_software_execution():
    required = set(CAPABILITY_BY_ID[101].required_proofs)
    assert required == {ProofKind.CODE, ProofKind.TEST, ProofKind.WIRING}


def test_mechanistic_simulation_requires_wiring_execution_and_reproducibility():
    required = set(CAPABILITY_BY_ID[102].required_proofs)
    assert required == {
        ProofKind.CODE,
        ProofKind.TEST,
        ProofKind.WIRING,
        ProofKind.EXECUTION,
        ProofKind.REPRODUCIBILITY,
    }
    assert ProofKind.INDEPENDENT not in required
    assert ProofKind.HARDWARE not in required
    assert ProofKind.LIVE not in required


def test_committed_policy_maps_every_required_route_for_101_and_102():
    root = Path(__file__).resolve().parents[1]
    report = audit_repository_policy_coverage(root, capability_ids=[101, 102])
    assert report.gaps == ()
    assert report.invalid_file_subjects == ()
    assert report.required_routes == 8
    assert report.mapped_routes == 8
