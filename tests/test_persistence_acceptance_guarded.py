from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from tools import persistence_acceptance as core
from tools import persistence_acceptance_guarded as guarded


REVISION = "a" * 40


def _health(**storage_overrides):
    storage = {
        "available": True,
        "split_storage": True,
        "ephemeral_available": True,
        "railway_runtime": True,
        "railway_volume_attached": True,
        "railway_volume_mount_matches_durable_root": True,
        "persistent_volume_ready": True,
        "durable_root": "/data/private",
        "raw_error": "must never escape",
    }
    storage.update(storage_overrides)
    return {
        "status": "ok",
        "build_revision": REVISION,
        "storage": storage,
    }


def test_exact_reviewed_revision_and_real_volume_attestation_pass():
    receipt = guarded.validate_persistent_health(
        _health(), expected_build_revision=REVISION
    )
    assert receipt["build_revision"] == REVISION
    assert receipt["persistent_volume_ready"] is True
    assert receipt["storage"]["railway_runtime"] is True
    assert receipt["storage"]["railway_volume_attached"] is True
    assert receipt["storage"]["railway_volume_mount_matches_durable_root"] is True
    assert receipt["storage"]["persistent_volume_ready"] is True
    text = json.dumps(receipt)
    assert "/data" not in text
    assert "raw_error" not in text


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"available": False}, "split_storage_not_ready"),
        ({"split_storage": False}, "split_storage_not_ready"),
        ({"railway_runtime": False}, "railway_runtime_not_attested"),
        ({"railway_volume_attached": False}, "railway_volume_not_attached"),
        (
            {"railway_volume_mount_matches_durable_root": False},
            "railway_volume_mount_mismatch",
        ),
        ({"persistent_volume_ready": False}, "persistent_volume_not_ready"),
    ],
)
def test_missing_volume_evidence_fails_closed(overrides, code):
    with pytest.raises(guarded.GuardedAcceptanceError, match=code):
        guarded.validate_persistent_health(
            _health(**overrides), expected_build_revision=REVISION
        )


def test_deployed_revision_must_match_exact_reviewed_sha():
    wrong = _health()
    wrong["build_revision"] = "b" * 40
    with pytest.raises(guarded.GuardedAcceptanceError, match="deployed_revision_mismatch"):
        guarded.validate_persistent_health(wrong, expected_build_revision=REVISION)

    with pytest.raises(guarded.GuardedAcceptanceError, match="invalid_reviewed_revision"):
        guarded.validate_persistent_health(_health(), expected_build_revision="short")


def test_after_restart_revision_is_loaded_from_private_state(tmp_path: Path):
    path = tmp_path / "private.json"
    path.write_text(
        json.dumps({"build_revision_before": REVISION, "job_access_token": "SECRET"}),
        encoding="utf-8",
    )
    assert guarded._state_revision(str(path)) == REVISION


def test_guard_wraps_every_core_health_read_and_restores_core(monkeypatch):
    original_health = core._health
    original_receipt = core._storage_receipt
    seen = []

    monkeypatch.setattr(core, "_health", lambda base_url: _health())

    def fake_phase1(args):
        seen.append(core._health(args.base_url))
        return {"pass": True, "storage": core._storage_receipt(_health())}

    monkeypatch.setattr(core, "_phase1", fake_phase1)
    args = argparse.Namespace(phase="before-restart", base_url="https://example.test")
    receipt = guarded._run_with_guard(args, REVISION)
    assert receipt["pass"] is True
    assert seen and seen[0]["build_revision"] == REVISION
    assert receipt["storage"]["persistent_volume_ready"] is True
    # Monkeypatch owns the temporary fake health, but the wrapper must restore
    # whatever functions were present when it entered.
    assert core._storage_receipt is original_receipt
    assert core._health is not original_health


def test_main_failure_surface_never_prints_private_state(tmp_path: Path, capsys):
    state = tmp_path / "state.json"
    secret = "super-secret-job-capability"
    state.write_text(
        json.dumps({"build_revision_before": "invalid", "job_access_token": secret}),
        encoding="utf-8",
    )
    code = guarded.main([
        "after-restart",
        "--state-file", str(state),
        "--receipt-file", str(tmp_path / "receipt.json"),
    ])
    captured = capsys.readouterr()
    assert code == 3
    assert secret not in captured.out + captured.err
    assert "invalid_reviewed_revision" in captured.err
