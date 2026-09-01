import json
from pathlib import Path
import subprocess

import pytest

from research_engine.capability_registry import CAPABILITIES, ProofKind
from research_engine.maturity_attestation_readiness import (
    _parse_attestor_registry,
    audit_attestation_readiness,
)
from research_engine.maturity_auditor import (
    ProofRule,
    RepositoryProofPolicy,
    _tracked_index,
)


ROOT = Path(__file__).resolve().parents[1]


def _route(report, capability_id, proof_kind):
    capability = next(
        item for item in report.capabilities if item.capability_id == capability_id
    )
    return next(item for item in capability.routes if item.proof_kind is proof_kind)


def _git(root, *args):
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _fixture_repo(tmp_path):
    root = tmp_path / "repo"
    (root / "research_engine").mkdir(parents=True)
    (root / "tests").mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "readiness@example.invalid")
    _git(root, "config", "user.name", "Readiness Tests")
    (root / "research_engine" / "attestor.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (root / "tests" / "test_attestor.py").write_text(
        "def test_attestor():\n    assert True\n", encoding="utf-8"
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    return root


def _policy(*, verifier="trusted-operator"):
    return RepositoryProofPolicy(
        rules=(
            ProofRule(
                capability_id=40,
                proof_kind=ProofKind.EXECUTION,
                subjects=("triple-implementation-run",),
                verifiers=(verifier,),
                reference_prefixes=("triple-implementation:",),
            ),
        ),
        sha256="0" * 64,
    )


def _registry_bytes(
    *,
    verifier="trusted-operator",
    module="research_engine/attestor.py",
    duplicate=False,
):
    entries = [
        {
            "attestor_id": "fixture-attestor",
            "verifier": verifier,
            "module": module,
            "test": "tests/test_attestor.py",
            "external_required": True,
            "routes": [
                {
                    "capability_id": 40,
                    "proof_kind": "execution",
                    "subject": "triple-implementation-run",
                }
            ],
        }
    ]
    if duplicate:
        entries.append(
            {
                "attestor_id": "fixture-attestor-two",
                "verifier": verifier,
                "module": "research_engine/attestor.py",
                "test": "tests/test_attestor.py",
                "external_required": True,
                "routes": [
                    {
                        "capability_id": 40,
                        "proof_kind": "execution",
                        "subject": "triple-implementation-run",
                    }
                ],
            }
        )
    return json.dumps(
        {"schema_version": 1, "attestors": entries},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def test_actual_repo_readiness_covers_every_required_route_without_minting_claims():
    before = _git(ROOT, "status", "--porcelain=v1", "--untracked-files=all")
    report = audit_attestation_readiness(ROOT)
    after = _git(ROOT, "status", "--porcelain=v1", "--untracked-files=all")

    assert before == after == ""
    assert report.total_capabilities == 142
    assert report.total_capabilities == len(CAPABILITIES)
    assert report.total_required_routes == sum(
        len(capability.required_proofs) for capability in CAPABILITIES
    )
    assert report.status_counts.get("ROUTE_MISSING", 0) == 0
    assert report.status_counts.get("TRACKED_CI", 0) == 284
    assert "verified" not in " ".join(report.status_counts).lower()


def test_current_specialized_attestors_are_explicit_and_external_boundaries_remain_visible():
    report = audit_attestation_readiness(ROOT)

    triple = _route(report, 40, ProofKind.EXECUTION)
    assert triple.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
    assert triple.attestor_id == "triple-implementation"
    assert triple.external_required is True

    debate = _route(report, 103, ProofKind.INDEPENDENT)
    assert debate.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
    assert debate.attestor_id == "literature-debate-independent"

    oracle = _route(report, 41, ProofKind.LIVE)
    assert oracle.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
    assert oracle.attestor_id == "reality-oracle-live"
    assert oracle.external_required is True

    manufacturing = {
        ProofKind.EXECUTION: (
            "manufacturing-reality-execution",
            "trusted-execution-attestor",
            "capability-71-execution-run",
        ),
        ProofKind.REPRODUCIBILITY: (
            "manufacturing-reality-reproducibility",
            "trusted-reproducibility-attestor",
            "capability-71-reproducibility-run",
        ),
    }
    for kind, (attestor_id, verifier, subject) in manufacturing.items():
        route = _route(report, 71, kind)
        assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
        assert route.attestor_id == attestor_id
        assert route.external_required is True
        assert route.verifiers == (verifier,)
        assert route.subjects == (subject,)

    for capability_id, kinds in {
        87: (ProofKind.PERSISTENCE, ProofKind.RUNTIME, ProofKind.LIVE),
        88: (
            ProofKind.EXECUTION,
            ProofKind.REPRODUCIBILITY,
            ProofKind.PERSISTENCE,
            ProofKind.RUNTIME,
            ProofKind.LIVE,
        ),
    }.items():
        for kind in kinds:
            route = _route(report, capability_id, kind)
            assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
            assert route.attestor_id == "post-deployment-live"
            assert route.external_required is True
            assert route.verifiers == ("trusted-deployment-observer",)
            assert route.subjects == ("post-deployment-live-validation",)

    for kind in (
        ProofKind.EXECUTION,
        ProofKind.REPRODUCIBILITY,
        ProofKind.HARDWARE,
        ProofKind.SAFETY,
    ):
        route = _route(report, 127, kind)
        assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
        assert route.attestor_id == "sim-to-reality-hardware"
        assert route.external_required is True
        assert route.verifiers == ("trusted-hardware-observer",)
        assert route.subjects == ("sim-to-reality-hardware-validation",)

    physical_roles = {
        ProofKind.EXECUTION: ("physical-lab-execution", "trusted-execution-attestor", "execution-run"),
        ProofKind.REPRODUCIBILITY: (
            "physical-lab-reproducibility",
            "trusted-reproducibility-attestor",
            "reproducibility-run",
        ),
        ProofKind.RUNTIME: ("physical-lab-runtime", "trusted-runtime-attestor", "runtime-observation"),
        ProofKind.LIVE: ("physical-lab-live", "trusted-live-observer", "live-observation"),
        ProofKind.HARDWARE: ("physical-lab-hardware", "trusted-hardware-lab", "hardware-observation"),
        ProofKind.SAFETY: ("physical-lab-safety", "trusted-safety-officer", "safety-gate"),
    }
    for capability_id in (125, 126):
        for kind, (attestor_id, verifier, suffix) in physical_roles.items():
            route = _route(report, capability_id, kind)
            assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
            assert route.attestor_id == attestor_id
            assert route.external_required is True
            assert route.verifiers == (verifier,)
            assert route.subjects == (f"capability-{capability_id}-{suffix}",)

    for kind in (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY):
        route = _route(report, 97, kind)
        assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
        assert route.attestor_id == "holdout-vault-benchmark"
        assert route.external_required is True
        assert route.verifiers == ("trusted-operator",)
        assert route.subjects == ("holdout-vault-benchmark",)

    for capability_id in (107, 108):
        for kind in (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY):
            route = _route(report, capability_id, kind)
            assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
            assert route.attestor_id == "visual-science-benchmark"
            assert route.external_required is True
            assert route.verifiers == ("trusted-operator",)
            assert route.subjects == ("visual-science-benchmark",)

    for kind in (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY):
        route = _route(report, 109, kind)
        assert route.status == "SPECIALIZED_EXTERNAL_ATTESTOR"
        assert route.attestor_id == "data-forensics-benchmark"
        assert route.external_required is True
        assert route.verifiers == ("trusted-operator",)
        assert route.subjects == ("data-forensics-benchmark",)


def test_production_wiring_is_repo_backed_but_not_execution_evidence():
    report = audit_attestation_readiness(ROOT)
    for capability_id in (14, 105, 112):
        route = _route(report, capability_id, ProofKind.WIRING)
        assert route.status == "SPECIALIZED_ATTESTOR"
        assert route.attestor_id == "production-wiring"
        assert route.external_required is False
        assert route.verifiers == ("github-actions",)


def test_generic_trusted_routes_are_not_misrepresented_as_specialized_attestors():
    report = audit_attestation_readiness(ROOT)

    # Real hardware evidence remains external even after the software execution
    # benchmark for Manufacturing Reality is specialized.
    hardware = _route(report, 71, ProofKind.HARDWARE)
    assert hardware.status == "HARDWARE_REQUIRED"
    assert hardware.attestor_id == ""
    assert hardware.external_required is True

    runtime = _route(report, 91, ProofKind.RUNTIME)
    assert runtime.status == "RUNTIME_EXTERNAL_REQUIRED"
    assert runtime.attestor_id == ""
    assert runtime.external_required is True

    # Keep this regression on a genuinely still-unspecialized software route.
    execution = _route(report, 72, ProofKind.EXECUTION)
    assert execution.status == "GENERIC_EXTERNAL_ROUTE"
    assert execution.attestor_id == ""
    assert execution.external_required is True


def test_code_and_test_routes_are_tracked_ci_not_maturity_evidence():
    report = audit_attestation_readiness(ROOT)
    for capability_id in (1, 40, 106, 142):
        for kind in (ProofKind.CODE, ProofKind.TEST):
            route = _route(report, capability_id, kind)
            assert route.status == "TRACKED_CI"
            assert route.attestor_id == "foundation-code-test"
            assert route.external_required is False
            assert route.subjects


def test_report_hash_is_deterministic_for_same_clean_revision():
    first = audit_attestation_readiness(ROOT)
    second = audit_attestation_readiness(ROOT)
    assert first.revision == second.revision
    assert first.report_hash == second.report_hash
    assert first.to_dict() == second.to_dict()


def test_registry_parser_accepts_exact_policy_bound_tracked_attestor(tmp_path):
    root = _fixture_repo(tmp_path)
    tracked = _tracked_index(root)
    registry = _parse_attestor_registry(
        _registry_bytes(),
        root=root,
        tracked=tracked,
        policy=_policy(),
    )
    assert len(registry.bindings) == 1
    binding = registry.bindings[0]
    assert binding.capability_id == 40
    assert binding.proof_kind is ProofKind.EXECUTION
    assert binding.subject == "triple-implementation-run"


def test_registry_parser_rejects_verifier_not_allowed_by_policy(tmp_path):
    root = _fixture_repo(tmp_path)
    tracked = _tracked_index(root)
    with pytest.raises(ValueError, match="verifier is not allowed"):
        _parse_attestor_registry(
            _registry_bytes(verifier="different-verifier"),
            root=root,
            tracked=tracked,
            policy=_policy(),
        )


def test_registry_parser_rejects_untracked_attestor_module(tmp_path):
    root = _fixture_repo(tmp_path)
    untracked = root / "research_engine" / "untracked.py"
    untracked.write_text("VALUE = 2\n", encoding="utf-8")
    tracked = _tracked_index(root)
    with pytest.raises(ValueError, match="not tracked"):
        _parse_attestor_registry(
            _registry_bytes(module="research_engine/untracked.py"),
            root=root,
            tracked=tracked,
            policy=_policy(),
        )


def test_registry_parser_rejects_duplicate_specialized_route(tmp_path):
    root = _fixture_repo(tmp_path)
    tracked = _tracked_index(root)
    with pytest.raises(ValueError, match="duplicate capability/proof binding"):
        _parse_attestor_registry(
            _registry_bytes(duplicate=True),
            root=root,
            tracked=tracked,
            policy=_policy(),
        )


def test_registry_parser_rejects_tracked_symlink_as_attestor_module(tmp_path):
    root = _fixture_repo(tmp_path)
    link = root / "research_engine" / "linked.py"
    try:
        link.symlink_to("attestor.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    _git(root, "add", "research_engine/linked.py")
    _git(root, "commit", "-qm", "track symlink")
    tracked = _tracked_index(root)
    with pytest.raises(ValueError, match="tracked regular"):
        _parse_attestor_registry(
            _registry_bytes(module="research_engine/linked.py"),
            root=root,
            tracked=tracked,
            policy=_policy(),
        )
