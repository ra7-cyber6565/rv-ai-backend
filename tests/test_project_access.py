"""Offline tests for anonymous project/session capability isolation."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from utils.project_access import ProjectCapabilitySigner


def _project_id(ch: str = "a") -> str:
    return "p_" + ch * 24


def test_create_returns_random_private_project_and_matching_token(tmp_path):
    signer = ProjectCapabilitySigner(str(tmp_path / "project.key"))
    first = signer.create()
    second = signer.create()

    assert first["project_id"].startswith("p_")
    assert second["project_id"].startswith("p_")
    assert first["project_id"] != second["project_id"]
    assert first["project_access_header"] == "X-Project-Token"
    assert signer.verify(first["project_id"], first["project_access_token"]) is True
    assert signer.verify(second["project_id"], second["project_access_token"]) is True
    assert signer.verify(first["project_id"], second["project_access_token"]) is False


def test_secret_survives_new_signer_instance_and_tokens_stay_valid(tmp_path):
    path = str(tmp_path / "project.key")
    first = ProjectCapabilitySigner(path)
    project = _project_id("b")
    token = first.issue(project)

    second = ProjectCapabilitySigner(path)
    assert second.verify(project, token) is True
    assert second.issue(project) == token
    assert Path(path).read_bytes()


def test_invalid_or_predictable_project_ids_fail_closed(tmp_path):
    signer = ProjectCapabilitySigner(str(tmp_path / "project.key"))
    for project in ("", "default", "p1", "p_short", "../other", "p_" + "x" * 100):
        with pytest.raises(ValueError):
            signer.issue(project)
        assert signer.verify(project, "anything") is False


def test_missing_wrong_and_oversized_tokens_are_rejected(tmp_path):
    signer = ProjectCapabilitySigner(str(tmp_path / "project.key"))
    project = _project_id("c")
    good = signer.issue(project)

    assert signer.verify(project, None) is False
    assert signer.verify(project, "wrong") is False
    assert signer.verify(project, good + "x") is False
    assert signer.verify(project, "x" * 129) is False


def test_status_is_aggregate_only_and_does_not_leak_secret_or_token(tmp_path):
    path = str(tmp_path / "project.key")
    signer = ProjectCapabilitySigner(path)
    session = signer.create()
    raw_secret = Path(path).read_bytes().hex()

    status = signer.status()
    dumped = repr(status)
    assert status == {"project_capability_tokens_ready": True}
    assert session["project_id"] not in dumped
    assert session["project_access_token"] not in dumped
    assert raw_secret not in dumped
    assert path not in dumped


def test_corrupt_persisted_secret_fails_closed_instead_of_rotating_silently(tmp_path):
    path = tmp_path / "project.key"
    path.write_bytes(b"too-short")
    signer = ProjectCapabilitySigner(str(path))

    assert signer.status() == {"project_capability_tokens_ready": False}
    assert signer.verify(_project_id("d"), "anything") is False
    # Existing corrupt bytes are not silently replaced, which would invalidate
    # every previously issued capability without operator awareness.
    assert path.read_bytes() == b"too-short"


def test_parallel_signer_instances_share_one_secret_and_issue_same_token(tmp_path):
    path = str(tmp_path / "project.key")
    project = _project_id("e")

    def issue_once(_index: int) -> str:
        return ProjectCapabilitySigner(path).issue(project)

    with ThreadPoolExecutor(max_workers=12) as pool:
        tokens = list(pool.map(issue_once, range(48)))

    assert len(set(tokens)) == 1
    assert len(Path(path).read_bytes()) == 32
    verifier = ProjectCapabilitySigner(path)
    assert verifier.verify(project, tokens[0]) is True
