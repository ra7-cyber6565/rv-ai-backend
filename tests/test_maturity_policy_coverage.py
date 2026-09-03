import json
from pathlib import Path

from research_engine.capability_registry import ProofKind
from research_engine.maturity_policy_coverage import (
    audit_repository_policy_coverage,
    load_policy_coverage,
)


def _rule(capability_id, proof_kind, subject, *, prefix=()):
    return {
        "capability_id": capability_id,
        "proof_kind": proof_kind.value,
        "subjects": [subject],
        "verifiers": ["github-actions"],
        "reference_prefixes": list(prefix),
    }


def _policy(*rules):
    return json.dumps(
        {"schema_version": 1, "rules": list(rules)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def test_complete_file_route_for_capability_one_has_no_gap():
    report = load_policy_coverage(
        _policy(
            _rule(1, ProofKind.CODE, "research_engine/question.py"),
            _rule(1, ProofKind.TEST, "tests/test_question.py"),
        ),
        capability_ids=[1],
    )
    assert report.complete is True
    assert report.required_routes == 2
    assert report.mapped_routes == 2
    assert report.gaps == ()


def test_missing_test_route_is_explicit_file_proof_gap():
    report = load_policy_coverage(
        _policy(_rule(1, ProofKind.CODE, "research_engine/question.py")),
        capability_ids=[1],
    )
    assert report.complete is False
    assert len(report.file_proof_gaps) == 1
    gap = report.file_proof_gaps[0]
    assert gap.capability_id == 1
    assert gap.proof_kind is ProofKind.TEST
    assert gap.category == "file_proof_route_missing"


def test_missing_wiring_route_is_distinct_from_missing_external_attestation():
    report = load_policy_coverage(
        _policy(
            _rule(14, ProofKind.CODE, "research_engine/formal_logic.py"),
            _rule(14, ProofKind.TEST, "tests/test_formal_logic.py"),
        ),
        capability_ids=[14],
    )
    assert [gap.proof_kind for gap in report.wiring_gaps] == [ProofKind.WIRING]
    assert report.external_route_gaps == ()


def test_execution_independence_and_repro_routes_are_reported_separately():
    report = load_policy_coverage(
        _policy(
            _rule(40, ProofKind.CODE, "research_engine/triple_implementation.py"),
            _rule(40, ProofKind.TEST, "tests/test_triple_implementation.py"),
        ),
        capability_ids=[40],
    )
    assert {gap.proof_kind for gap in report.external_route_gaps} == {
        ProofKind.EXECUTION,
        ProofKind.INDEPENDENT,
        ProofKind.REPRODUCIBILITY,
    }


def test_committed_policy_maps_every_registry_required_production_wiring_route():
    root = Path(__file__).resolve().parents[1]
    report = audit_repository_policy_coverage(root)
    assert report.wiring_gaps == ()
    assert report.invalid_file_subjects == ()


def test_capability_98_committed_policy_maps_every_required_route():
    root = Path(__file__).resolve().parents[1]
    report = audit_repository_policy_coverage(root, capability_ids=[98])
    assert report.gaps == ()
    assert report.invalid_file_subjects == ()
    assert report.required_routes == 5
    assert report.mapped_routes == 5


def test_committed_policy_maps_every_registry_required_proof_route():
    """Every required proof class needs a committed acceptance route.

    This is deliberately stricter than the wiring-only regression above.  A
    mapped route is *not* evidence and never makes a capability verified; it
    only guarantees that legitimate future CODE/TEST/execution/independence/
    persistence/runtime/live/hardware/safety/reproducibility evidence has a
    fail-closed policy path through the trusted maturity auditor.
    """
    root = Path(__file__).resolve().parents[1]
    report = audit_repository_policy_coverage(root)
    assert report.complete is True, report.to_dict()
    assert report.required_routes == report.mapped_routes
    assert report.gaps == ()
    assert report.invalid_file_subjects == ()


def test_report_is_machine_readable_and_never_equates_route_with_evidence():
    report = load_policy_coverage(
        _policy(_rule(1, ProofKind.CODE, "research_engine/question.py")),
        capability_ids=[1],
    )
    payload = report.to_dict()
    assert payload["complete"] is False
    assert payload["blocking_capability_ids"] == [1]
    assert payload["gaps"][0]["proof_kind"] == ProofKind.TEST.value
    assert "verified" not in payload
    assert "truth" not in payload
