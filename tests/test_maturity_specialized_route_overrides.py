import json
from pathlib import Path

import pytest

from research_engine.maturity_policy_extensions import merge_policy_route_extensions


_PRIMARY = "config/maturity_proof_route_extensions.json"
_SPECIAL = "config/maturity_specialized_route_overrides.json"


def _base():
    return json.dumps({"schema_version": 1, "rules": []}).encode("utf-8")


def _write_json(root: Path, relative: str, payload) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _primary(*, include_code=False):
    bindings = []
    if include_code:
        bindings.append({
            "capability_ids": [1],
            "code_subjects": ["research_engine/facets.py"],
            "test_subjects": ["tests/test_question_facets.py"],
        })
    return {
        "schema_version": 1,
        "code_test_bindings": bindings,
        "wiring_bindings": [],
        "external_routes": [{
            "proof_kind": "execution",
            "capability_ids": [127],
            "subject_suffix": "execution-run",
            "verifier": "trusted-execution-attestor",
            "reference_namespace": "execution",
        }],
    }


def _override(*, capability_id=127, proof_kind="execution"):
    return {
        "schema_version": 1,
        "routes": [{
            "capability_id": capability_id,
            "proof_kind": proof_kind,
            "subject": "sim-to-reality-hardware-validation",
            "verifier": "trusted-hardware-observer",
            "reference_prefix": "sim-to-reality:",
        }],
    }


def _tracked(*, special=True):
    rows = {_PRIMARY: "100644"}
    if special:
        rows[_SPECIAL] = "100644"
    return rows


def test_specialized_override_narrows_existing_generated_external_route(tmp_path):
    _write_json(tmp_path, _PRIMARY, _primary())
    _write_json(tmp_path, _SPECIAL, _override())
    merged = json.loads(merge_policy_route_extensions(
        root=tmp_path,
        tracked=_tracked(),
        base_policy_bytes=_base(),
    ))
    assert len(merged["rules"]) == 1
    route = merged["rules"][0]
    assert route == {
        "capability_id": 127,
        "proof_kind": "execution",
        "subjects": ["sim-to-reality-hardware-validation"],
        "verifiers": ["trusted-hardware-observer"],
        "reference_prefixes": ["sim-to-reality:"],
    }
    assert "evidence" not in merged
    assert "verified" not in merged


def test_untracked_specialized_file_cannot_change_policy(tmp_path):
    _write_json(tmp_path, _PRIMARY, _primary())
    _write_json(tmp_path, _SPECIAL, _override())
    merged = json.loads(merge_policy_route_extensions(
        root=tmp_path,
        tracked=_tracked(special=False),
        base_policy_bytes=_base(),
    ))
    route = merged["rules"][0]
    assert route["subjects"] == ["capability-127-execution-run"]
    assert route["verifiers"] == ["trusted-execution-attestor"]
    assert route["reference_prefixes"] == ["execution:c127:"]


def test_override_cannot_create_route_that_primary_manifest_did_not_generate(tmp_path):
    _write_json(tmp_path, _PRIMARY, {
        "schema_version": 1,
        "code_test_bindings": [],
        "wiring_bindings": [],
        "external_routes": [],
    })
    _write_json(tmp_path, _SPECIAL, _override())
    with pytest.raises(ValueError, match="only narrow an existing generated external route"):
        merge_policy_route_extensions(
            root=tmp_path,
            tracked=_tracked(),
            base_policy_bytes=_base(),
        )


def test_override_cannot_target_code_or_test_route(tmp_path):
    _write_json(tmp_path, _PRIMARY, _primary(include_code=True))
    _write_json(tmp_path, _SPECIAL, _override(capability_id=1, proof_kind="code"))
    with pytest.raises(ValueError, match="cannot target CODE/TEST/WIRING"):
        merge_policy_route_extensions(
            root=tmp_path,
            tracked=_tracked(),
            base_policy_bytes=_base(),
        )


def test_duplicate_specialized_route_fails_closed(tmp_path):
    _write_json(tmp_path, _PRIMARY, _primary())
    payload = _override()
    payload["routes"].append(dict(payload["routes"][0]))
    _write_json(tmp_path, _SPECIAL, payload)
    with pytest.raises(ValueError, match="duplicate route"):
        merge_policy_route_extensions(
            root=tmp_path,
            tracked=_tracked(),
            base_policy_bytes=_base(),
        )


def test_specialized_override_cannot_override_base_policy_route(tmp_path):
    _write_json(tmp_path, _PRIMARY, _primary())
    _write_json(tmp_path, _SPECIAL, _override())
    base = json.dumps({
        "schema_version": 1,
        "rules": [{
            "capability_id": 127,
            "proof_kind": "execution",
            "subjects": ["base-subject"],
            "verifiers": ["base-verifier"],
            "reference_prefixes": ["base:"],
        }],
    }).encode("utf-8")
    with pytest.raises(ValueError, match="override a base policy route"):
        merge_policy_route_extensions(
            root=tmp_path,
            tracked=_tracked(),
            base_policy_bytes=base,
        )


def test_symlink_specialized_manifest_fails_closed(tmp_path):
    _write_json(tmp_path, _PRIMARY, _primary())
    target = tmp_path / "special-target.json"
    target.write_text(json.dumps(_override()), encoding="utf-8")
    link = tmp_path / _SPECIAL
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    tracked = {_PRIMARY: "100644", _SPECIAL: "120000"}
    with pytest.raises(ValueError, match="tracked regular file"):
        merge_policy_route_extensions(
            root=tmp_path,
            tracked=tracked,
            base_policy_bytes=_base(),
        )