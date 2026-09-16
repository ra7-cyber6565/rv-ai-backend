from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pytest

from tools import heldout_campaign_capture as capture
from utils.research_runtime import digest


REVISION = "a" * 40


def _pack() -> dict:
    return {
        "schema_version": 1,
        "task_pack_id": "holdout-v1",
        "split": "untouched_holdout",
        "used_for_tuning": False,
        "tasks": [
            {"task_id": "science-01", "question": "Assess claim A using sources and uncertainty."},
            {"task_id": "history-01", "question": "Compare explanations B and C with evidence."},
        ],
    }


def _result(answer: str = "private generated answer") -> dict:
    return {
        "status": "COMPLETE",
        "mode": "MAXIMUM",
        "answer": answer,
        "api_accounting": {
            "accounting_complete": True,
            "counts_are_lower_bounds": False,
            "unknown_worker_usage": 0,
            "actual_http_attempts": 9,
            "logical_reasoning_calls": 8,
        },
    }


def _args(tmp_path: Path, task_pack: Path, expected: str) -> argparse.Namespace:
    return argparse.Namespace(
        base_url="https://example.invalid",
        expected_build_revision=REVISION,
        task_pack=str(task_pack),
        expected_task_pack_sha256=expected,
        private_capture_file=str(tmp_path / "private.json"),
        receipt_file=str(tmp_path / "receipt.json"),
        trials_per_task=1,
        http_budget=24,
        seconds_budget=60.0,
        poll_seconds=1.0,
    )


def _fake_live(monkeypatch: pytest.MonkeyPatch, result: dict | None = None) -> None:
    result = result or _result()
    monkeypatch.setattr(capture.max_live, "_health", lambda base_url: {"status": "ok"})
    monkeypatch.setattr(
        capture.max_live,
        "validate_health",
        lambda health, expected: {
            "service_health": "ok",
            "build_revision": expected,
            "zero_cost_only": True,
            "model_layer_usable_now": True,
            "storage_available": True,
            "split_storage": True,
        },
    )
    monkeypatch.setattr(capture.max_live, "_create_session", lambda base_url: ("project-1", "PRIVATE-PROJECT-TOKEN"))
    monkeypatch.setattr(
        capture.max_live,
        "_start_job",
        lambda base_url, project_id, project_token, question: ("job-1", "PRIVATE-JOB-TOKEN"),
    )
    monkeypatch.setattr(
        capture.max_live,
        "_wait_terminal",
        lambda base_url, job_id, token, timeout, poll: {"status": "completed"},
    )
    monkeypatch.setattr(capture.max_live, "_fetch_result", lambda base_url, job_id, token: result)
    monkeypatch.setattr(
        capture.max_live,
        "validate_maximum_result",
        lambda value: {
            "architecture_pass": True,
            "completed_workers": 6,
            "chief_passes_with_output": 3,
        },
    )


def test_task_pack_is_frozen_blind_unique_and_prompt_only():
    pack = _pack()
    assert capture.validate_task_pack(pack, digest(pack)) == pack["tasks"]

    changed = _pack()
    changed["tasks"][0]["question"] += " changed"
    with pytest.raises(capture.CampaignCaptureError, match="frozen task pack changed"):
        capture.validate_task_pack(changed, digest(pack))

    leaked = _pack()
    leaked["tasks"][0]["gold_answer"] = "target"
    with pytest.raises(capture.CampaignCaptureError, match="grading-target"):
        capture.validate_task_pack(leaked, digest(leaked))

    nested_leak = _pack()
    nested_leak["private"] = {"rubric": ["secret"]}
    with pytest.raises(capture.CampaignCaptureError, match="grading-target"):
        capture.validate_task_pack(nested_leak, digest(nested_leak))

    duplicate = _pack()
    duplicate["tasks"][1]["task_id"] = duplicate["tasks"][0]["task_id"]
    with pytest.raises(capture.CampaignCaptureError, match="unique"):
        capture.validate_task_pack(duplicate, digest(duplicate))


def test_capture_keeps_questions_raw_results_and_capabilities_out_of_public_receipt(tmp_path, monkeypatch):
    pack = _pack()
    pack_path = tmp_path / "task-pack.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    args = _args(tmp_path, pack_path, digest(pack))
    _fake_live(monkeypatch)

    receipt = capture.run_capture(args)

    public_text = Path(args.receipt_file).read_text(encoding="utf-8")
    private_text = Path(args.private_capture_file).read_text(encoding="utf-8")
    public = json.loads(public_text)
    private = json.loads(private_text)

    assert receipt["pass"] is True
    assert public["tasks"] == 2
    assert public["paired_trials_ready"] == 2
    assert public["questions_in_receipt"] is False
    assert public["raw_results_in_receipt"] is False
    assert public["capabilities_in_receipt"] is False
    assert public["grading_performed"] is False
    assert public["release_decision_performed"] is False
    assert all(row["architecture_pass"] is True for row in public["rows"])
    assert all(row["actual_http_attempts"] == 9 for row in public["rows"])
    assert all(row["http_budget"] == 24 for row in public["rows"])

    for task in pack["tasks"]:
        assert task["question"] not in public_text
    assert "private generated answer" not in public_text
    assert "PRIVATE-PROJECT-TOKEN" not in public_text
    assert "PRIVATE-JOB-TOKEN" not in public_text
    assert "PRIVATE-PROJECT-TOKEN" not in private_text
    assert "PRIVATE-JOB-TOKEN" not in private_text

    assert private["rows"][0]["raw_result"]["answer"] == "private generated answer"
    assert private["rows"][0]["output_sha256"] == digest(_result())
    assert public["rows"][0]["output_sha256"] == private["rows"][0]["output_sha256"]
    assert private["capture_sha256"] == public["private_capture_sha256"]

    if os.name != "nt":
        assert (Path(args.private_capture_file).stat().st_mode & 0o077) == 0


def test_result_capability_like_fields_are_refused_before_private_persistence(tmp_path, monkeypatch):
    pack = _pack()
    pack_path = tmp_path / "task-pack.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    args = _args(tmp_path, pack_path, digest(pack))
    unsafe = _result()
    unsafe["nested"] = {"job_access_token": "must-not-persist"}
    _fake_live(monkeypatch, unsafe)

    with pytest.raises(capture.CampaignCaptureError, match="capability-like field"):
        capture.run_capture(args)
    assert not Path(args.private_capture_file).exists()
    assert not Path(args.receipt_file).exists()


def test_exact_accounting_and_http_cap_fail_closed():
    good = _result()
    assert capture.extract_accounting(good, http_budget=9) == {
        "actual_http_attempts": 9,
        "logical_reasoning_calls": 8,
    }

    incomplete = _result()
    incomplete["api_accounting"]["accounting_complete"] = False
    with pytest.raises(capture.CampaignCaptureError, match="incomplete"):
        capture.extract_accounting(incomplete, http_budget=24)

    lower_bound = _result()
    lower_bound["api_accounting"]["counts_are_lower_bounds"] = True
    with pytest.raises(capture.CampaignCaptureError, match="lower bound"):
        capture.extract_accounting(lower_bound, http_budget=24)

    unknown = _result()
    unknown["api_accounting"]["unknown_worker_usage"] = 1
    with pytest.raises(capture.CampaignCaptureError, match="unknown worker usage"):
        capture.extract_accounting(unknown, http_budget=24)

    over = _result()
    over["api_accounting"]["actual_http_attempts"] = 25
    with pytest.raises(capture.CampaignCaptureError, match="exceeded"):
        capture.extract_accounting(over, http_budget=24)


def test_cli_failure_surface_does_not_echo_private_prompt_or_result(tmp_path, monkeypatch, capsys):
    pack = _pack()
    secret_prompt = "PRIVATE PROMPT MUST NOT APPEAR"
    pack["tasks"][0]["question"] = secret_prompt
    pack_path = tmp_path / "task-pack.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    args = [
        "--base-url", "https://example.invalid",
        "--expected-build-revision", REVISION,
        "--task-pack", str(pack_path),
        "--expected-task-pack-sha256", digest(pack),
        "--private-capture-file", str(tmp_path / "private.json"),
        "--receipt-file", str(tmp_path / "receipt.json"),
        "--seconds-budget", "60",
    ]
    monkeypatch.setattr(capture.max_live, "_health", lambda base_url: {"status": "ok"})
    monkeypatch.setattr(
        capture.max_live,
        "validate_health",
        lambda health, expected: (_ for _ in ()).throw(capture.max_live.AcceptanceError("deployed build revision does not match")),
    )

    assert capture.main(args) == 2
    out = capsys.readouterr()
    assert secret_prompt not in out.out + out.err
    assert "deployed build revision does not match" in out.err
    assert not (tmp_path / "private.json").exists()


def test_task_pack_disallows_extra_task_fields_even_when_not_named_gold():
    pack = _pack()
    pack["tasks"][0]["notes"] = "could accidentally reveal evaluator hints"
    with pytest.raises(capture.CampaignCaptureError, match="undeclared fields"):
        capture.validate_task_pack(pack, digest(pack))
