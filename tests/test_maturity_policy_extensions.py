import json
from pathlib import Path

import pytest

from research_engine.maturity_policy_extensions import merge_policy_route_extensions


def _base(*rules):
    return json.dumps({"schema_version": 1, "rules": list(rules)}).encode()


def _rule(capability_id, proof_kind, subject="subject.py"):
    return {
        "capability_id": capability_id,
        "proof_kind": proof_kind,
        "subjects": [subject],
        "verifiers": ["github-actions"],
        "reference_prefixes": [],
    }


def _payload(*, code_test=None, wiring=None, external=None):
    return {
        "schema_version": 1,
        "code_test_bindings": list(code_test or []),
        "wiring_bindings": list(wiring or []),
        "external_routes": list(external or []),
    }


def _write(tmp_path: Path, payload, *, tracked=True):
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    path = config / "maturity_proof_route_extensions.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    index = {"config/maturity_proof_route_extensions.json": "100644"} if tracked else {}
    return index


def test_absent_extension_preserves_base_bytes_exactly(tmp_path):
    base = _base(_rule(1, "code"))
    assert merge_policy_route_extensions(
        root=tmp_path, tracked={}, base_policy_bytes=base
    ) == base


def test_explicit_code_test_wiring_and_external_routes_compile_without_evidence(tmp_path):
    base = _base()
    tracked = _write(tmp_path, _payload(
        code_test=[{
            "capability_ids": [1],
            "code_subjects": ["research_engine/facets.py"],
            "test_subjects": ["tests/test_question_facets.py"],
        }],
        wiring=[{
            "capability_ids": [71],
            "subjects": ["tests/test_manufacturing_reality_wiring.py"],
        }],
        external=[{
            "proof_kind": "execution",
            "capability_ids": [18],
            "subject_suffix": "execution-run",
            "verifier": "trusted-execution-attestor",
            "reference_namespace": "execution",
        }],
    ))
    merged = json.loads(merge_policy_route_extensions(
        root=tmp_path, tracked=tracked, base_policy_bytes=base
    ))
    assert len(merged["rules"]) == 4
    routes = {(row["capability_id"], row["proof_kind"]): row for row in merged["rules"]}
    assert routes[(1, "code")]["subjects"] == ["research_engine/facets.py"]
    assert routes[(1, "test")]["subjects"] == ["tests/test_question_facets.py"]
    wiring = routes[(71, "production_wiring")]
    assert wiring["subjects"] == ["tests/test_manufacturing_reality_wiring.py"]
    assert wiring["verifiers"] == ["github-actions"]
    assert wiring["reference_prefixes"] == ["github-actions:"]
    external = routes[(18, "execution")]
    assert external["subjects"] == ["capability-18-execution-run"]
    assert external["verifiers"] == ["trusted-execution-attestor"]
    assert external["reference_prefixes"] == ["execution:c18:"]
    assert "evidence" not in merged
    assert "verified" not in merged


def test_extension_cannot_override_existing_route(tmp_path):
    base = _base(_rule(1, "code"))
    tracked = _write(tmp_path, _payload(code_test=[{
        "capability_ids": [1],
        "code_subjects": ["research_engine/facets.py"],
        "test_subjects": ["tests/test_question_facets.py"],
    }]))
    with pytest.raises(ValueError, match="override"):
        merge_policy_route_extensions(root=tmp_path, tracked=tracked, base_policy_bytes=base)


def test_duplicate_generated_route_fails_closed(tmp_path):
    base = _base()
    tracked = _write(tmp_path, _payload(code_test=[
        {"capability_ids": [1], "code_subjects": ["a.py"], "test_subjects": ["ta.py"]},
        {"capability_ids": [1], "code_subjects": ["b.py"], "test_subjects": ["tb.py"]},
    ]))
    with pytest.raises(ValueError, match="duplicate generated route"):
        merge_policy_route_extensions(root=tmp_path, tracked=tracked, base_policy_bytes=base)


def test_wiring_binding_must_target_required_wiring_capability(tmp_path):
    tracked = _write(tmp_path, _payload(wiring=[{
        "capability_ids": [1],
        "subjects": ["tests/test_fake_wiring.py"],
    }]))
    with pytest.raises(ValueError, match="not required"):
        merge_policy_route_extensions(root=tmp_path, tracked=tracked, base_policy_bytes=_base())


def test_wiring_subject_must_be_focused_test_file(tmp_path):
    tracked = _write(tmp_path, _payload(wiring=[{
        "capability_ids": [71],
        "subjects": ["research_engine/manufacturing_reality_wiring.py"],
    }]))
    with pytest.raises(ValueError, match="tests/test_\*\.py"):
        merge_policy_route_extensions(root=tmp_path, tracked=tracked, base_policy_bytes=_base())


def test_wiring_extension_cannot_override_base_wiring_route(tmp_path):
    base = _base({
        "capability_id": 71,
        "proof_kind": "production_wiring",
        "subjects": ["tests/test_existing_wiring.py"],
        "verifiers": ["github-actions"],
        "reference_prefixes": ["github-actions:"],
    })
    tracked = _write(tmp_path, _payload(wiring=[{
        "capability_ids": [71],
        "subjects": ["tests/test_manufacturing_reality_wiring.py"],
    }]))
    with pytest.raises(ValueError, match="override"):
        merge_policy_route_extensions(root=tmp_path, tracked=tracked, base_policy_bytes=base)


def test_external_route_must_be_required_by_capability(tmp_path):
    tracked = _write(tmp_path, _payload(external=[{
        "proof_kind": "hardware_observation",
        "capability_ids": [1],
        "subject_suffix": "hardware-observation",
        "verifier": "trusted-hardware-lab",
        "reference_namespace": "hardware",
    }]))
    with pytest.raises(ValueError, match="not required"):
        merge_policy_route_extensions(root=tmp_path, tracked=tracked, base_policy_bytes=_base())


def test_old_manifest_without_wiring_lane_fails_schema_closed(tmp_path):
    tracked = _write(tmp_path, {
        "schema_version": 1,
        "code_test_bindings": [],
        "external_routes": [],
    })
    with pytest.raises(ValueError, match="schema is invalid"):
        merge_policy_route_extensions(root=tmp_path, tracked=tracked, base_policy_bytes=_base())


def test_untracked_manifest_is_not_silently_consumed(tmp_path):
    _write(tmp_path, _payload(), tracked=False)
    base = _base()
    assert merge_policy_route_extensions(
        root=tmp_path, tracked={}, base_policy_bytes=base
    ) == base


def test_symlink_manifest_fails_closed(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    target = tmp_path / "target.json"
    target.write_text(json.dumps(_payload()), encoding="utf-8")
    link = config / "maturity_proof_route_extensions.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="tracked regular file"):
        merge_policy_route_extensions(
            root=tmp_path,
            tracked={"config/maturity_proof_route_extensions.json": "120000"},
            base_policy_bytes=_base(),
        )