"""Release identity must be exact, sanitized and fail closed."""
from __future__ import annotations

from types import SimpleNamespace

from utils import release_identity


SHA = "2a21a6fbcb0771be746766dad3c6a511a7c3ec5e"


def test_git_revision_accepts_only_a_full_sha():
    assert release_identity.normalize_git_revision(SHA.upper()) == SHA
    for invalid in ("", "2a21a6f", "g" * 40, SHA + "x", "$(private)"):
        assert release_identity.normalize_git_revision(invalid) == ""


def test_deployment_revision_uses_validated_host_variable_only():
    env = {
        "RAILWAY_GIT_COMMIT_SHA": "not-a-sha",
        "SOURCE_VERSION": SHA.upper(),
    }
    assert release_identity.deployment_revision(env) == SHA
    assert release_identity.deployment_revision({"SOURCE_VERSION": "secret"}) == ""


def test_repository_identity_reports_clean_checkout_without_command_output(
    monkeypatch, tmp_path,
):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if "rev-parse" in command:
            return SimpleNamespace(returncode=0, stdout=SHA + "\n")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(release_identity.subprocess, "run", fake_run)
    result = release_identity.repository_identity(tmp_path)
    assert result == {"available": True, "revision": SHA, "clean": True}
    assert len(calls) == 2


def test_repository_identity_marks_dirty_or_git_failure_without_leaking_details(
    monkeypatch, tmp_path,
):
    responses = iter([
        SimpleNamespace(returncode=0, stdout=SHA + "\n"),
        SimpleNamespace(returncode=0, stdout=" M private.env\n"),
    ])
    monkeypatch.setattr(
        release_identity.subprocess, "run", lambda *_args, **_kwargs: next(responses),
    )
    assert release_identity.repository_identity(tmp_path) == {
        "available": True, "revision": SHA, "clean": False,
    }

    monkeypatch.setattr(
        release_identity.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout="private raw error must not escape",
        ),
    )
    assert release_identity.repository_identity(tmp_path) == {
        "available": False, "revision": "", "clean": False,
    }

