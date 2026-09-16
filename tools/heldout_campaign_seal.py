#!/usr/bin/env python3
"""Seal blind captures + independent grades into held-out release-gate inputs.

This tool never generates answers and never grades them itself.  It validates
that baseline/candidate private captures came from the same frozen untouched
holdout, that every grade binds the exact captured output hash, and that the
operator explicitly attests the freeze/blinding order.  It then emits only the
sanitized row schema consumed by ``tools/run_heldout_release_gate.py``.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.heldout_campaign_capture import CampaignCaptureError, validate_task_pack  # noqa: E402
from utils.research_runtime import digest  # noqa: E402

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GRADERS = {"DETERMINISTIC", "HUMAN", "MODEL_ASSISTED_UNCALIBRATED"}
_METRICS = ("task_success", "coverage", "citation_support", "abstention_appropriate")


class CampaignSealError(ValueError):
    pass


def _read(path: str, label: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignSealError(f"{label} JSON is unavailable or invalid") from exc


def _write(path: str, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(target)


def _sha40(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA40.fullmatch(text):
        raise CampaignSealError(f"{label} must be one full 40-character Git SHA")
    return text


def _sha256(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256.fullmatch(text):
        raise CampaignSealError(f"{label} must be one 64-character SHA-256")
    return text


def _metric(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1:
        raise CampaignSealError(f"{label} must be null or a finite number from 0 to 1")
    return float(value)


def _capture(value: Any, *, expected_pack_hash: str, label: str) -> tuple[str, dict[tuple[str, int], dict[str, Any]]]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise CampaignSealError(f"{label} capture schema_version must be 1")
    if value.get("kind") != "HELDOUT_BLIND_GENERATION_CAPTURE_PRIVATE":
        raise CampaignSealError(f"{label} is not a private blind generation capture")
    if value.get("split") != "untouched_holdout" or value.get("used_for_tuning") is not False:
        raise CampaignSealError(f"{label} is not an untouched holdout capture")
    if _sha256(value.get("task_pack_sha256"), f"{label}.task_pack_sha256") != expected_pack_hash:
        raise CampaignSealError(f"{label} task-pack hash mismatch")
    if str(value.get("execution_kind") or "") != "LIVE" or str(value.get("mode") or "") != "MAXIMUM":
        raise CampaignSealError(f"{label} must be a LIVE MAXIMUM capture")
    revision = _sha40(value.get("revision"), f"{label}.revision")
    rows = value.get("rows")
    if not isinstance(rows, list) or not rows:
        raise CampaignSealError(f"{label} rows are missing")
    indexed: dict[tuple[str, int], dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CampaignSealError(f"{label}.rows[{index}] must be an object")
        task_id = str(row.get("task_id") or "").strip()
        trial = row.get("trial")
        key = (task_id, trial)
        if not task_id or type(trial) is not int or trial < 0 or key in indexed:
            raise CampaignSealError(f"{label} has duplicate/invalid task-trial key")
        if _sha40(row.get("revision"), f"{label}.rows[{index}].revision") != revision:
            raise CampaignSealError(f"{label} row revision mismatch")
        if row.get("execution_kind") != "LIVE" or row.get("mode") != "MAXIMUM":
            raise CampaignSealError(f"{label} row execution provenance mismatch")
        if row.get("architecture_pass") is not True:
            raise CampaignSealError(f"{label} row lacks MAXIMUM architecture proof")
        _sha256(row.get("output_sha256"), f"{label}.rows[{index}].output_sha256")
        for budget_name in ("http_budget", "seconds_budget", "latency_seconds"):
            number = row.get(budget_name)
            if type(number) not in {int, float} or not math.isfinite(number) or number < 0:
                raise CampaignSealError(f"{label} row {budget_name} is invalid")
        indexed[key] = row
    return revision, indexed


def _grades(value: Any, *, label: str) -> dict[tuple[str, int], dict[str, Any]]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise CampaignSealError(f"{label} grade file schema_version must be 1")
    rows = value.get("rows")
    if not isinstance(rows, list) or not rows:
        raise CampaignSealError(f"{label} grade rows are missing")
    indexed: dict[tuple[str, int], dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CampaignSealError(f"{label}.rows[{index}] must be an object")
        task_id = str(row.get("task_id") or "").strip()
        trial = row.get("trial")
        key = (task_id, trial)
        if not task_id or type(trial) is not int or trial < 0 or key in indexed:
            raise CampaignSealError(f"{label} has duplicate/invalid task-trial key")
        grader = str(row.get("grader") or "")
        if grader not in _GRADERS:
            raise CampaignSealError(f"{label} has unsupported grader provenance")
        _sha256(row.get("output_sha256"), f"{label}.rows[{index}].output_sha256")
        for metric_name in _METRICS:
            _metric(row.get(metric_name), f"{label}.rows[{index}].{metric_name}")
        indexed[key] = row
    return indexed


def _grade_hash(row: dict[str, Any]) -> str:
    # Hash the complete private grade row, including any private notes/rationale,
    # while emitting only metrics + the hash downstream.
    return digest(row)


def build_release_inputs(
    *,
    task_pack: dict[str, Any],
    expected_task_pack_sha256: str,
    baseline_capture: dict[str, Any],
    candidate_capture: dict[str, Any],
    baseline_grades: dict[str, Any],
    candidate_grades: dict[str, Any],
    grader_spec: dict[str, Any],
    expected_grader_spec_sha256: str,
    campaign_id: str,
    attest_outputs_frozen_before_grading: bool,
    attest_targets_hidden_during_generation: bool,
    attest_grader_frozen_before_candidate_scoring: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    pack_hash = _sha256(expected_task_pack_sha256, "expected_task_pack_sha256")
    tasks = validate_task_pack(task_pack, pack_hash)
    grader_hash = _sha256(expected_grader_spec_sha256, "expected_grader_spec_sha256")
    if digest(grader_spec) != grader_hash:
        raise CampaignSealError("frozen grader spec changed")
    if not all((
        attest_outputs_frozen_before_grading,
        attest_targets_hidden_during_generation,
        attest_grader_frozen_before_candidate_scoring,
    )):
        raise CampaignSealError("all campaign freeze/blinding attestations must be explicit")

    base_revision, base_capture = _capture(baseline_capture, expected_pack_hash=pack_hash, label="baseline")
    cand_revision, cand_capture = _capture(candidate_capture, expected_pack_hash=pack_hash, label="candidate")
    if base_revision == cand_revision:
        raise CampaignSealError("baseline and candidate revisions must differ")
    if set(base_capture) != set(cand_capture):
        raise CampaignSealError("baseline/candidate task-trial capture coverage differs")

    task_ids = [row["task_id"] for row in tasks]
    captured_task_ids = {key[0] for key in base_capture}
    if captured_task_ids != set(task_ids):
        raise CampaignSealError("capture does not cover the exact frozen task pack")

    base_grade_map = _grades(baseline_grades, label="baseline_grades")
    cand_grade_map = _grades(candidate_grades, label="candidate_grades")
    if set(base_grade_map) != set(base_capture) or set(cand_grade_map) != set(cand_capture):
        raise CampaignSealError("grades do not cover the exact captured task/trial set")

    baseline_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    for key in sorted(base_capture):
        base_out, cand_out = base_capture[key], cand_capture[key]
        base_grade, cand_grade = base_grade_map[key], cand_grade_map[key]
        if base_grade["output_sha256"] != base_out["output_sha256"]:
            raise CampaignSealError("baseline grade is not bound to the captured output hash")
        if cand_grade["output_sha256"] != cand_out["output_sha256"]:
            raise CampaignSealError("candidate grade is not bound to the captured output hash")
        if base_grade["grader"] != cand_grade["grader"]:
            raise CampaignSealError("paired baseline/candidate rows must use the same grader provenance")
        for budget_name in ("http_budget", "seconds_budget"):
            if base_out[budget_name] != cand_out[budget_name]:
                raise CampaignSealError("paired baseline/candidate rows do not have matched budgets")

        def sanitized(capture_row: dict[str, Any], grade_row: dict[str, Any], revision: str) -> dict[str, Any]:
            row = {
                "task_id": key[0],
                "trial": key[1],
                "execution_kind": "LIVE",
                "grader": grade_row["grader"],
                "revision": revision,
                "output_sha256": capture_row["output_sha256"],
                "grade_sha256": _grade_hash(grade_row),
                "http_budget": capture_row["http_budget"],
                "seconds_budget": capture_row["seconds_budget"],
                "latency_seconds": capture_row["latency_seconds"],
            }
            for metric_name in _METRICS:
                row[metric_name] = _metric(grade_row.get(metric_name), metric_name)
            return row

        baseline_rows.append(sanitized(base_out, base_grade, base_revision))
        candidate_rows.append(sanitized(cand_out, cand_grade, cand_revision))

    manifest = {
        "schema_version": 1,
        "benchmark_id": str(task_pack.get("task_pack_id") or campaign_id).strip(),
        "task_ids": task_ids,
        "split": "untouched_holdout",
        "used_for_tuning": False,
    }
    campaign = {
        "schema_version": 1,
        "campaign_id": str(campaign_id or "").strip(),
        "baseline_revision": base_revision,
        "candidate_revision": cand_revision,
        "grader_spec_sha256": grader_hash,
        "outputs_frozen_before_grading": True,
        "holdout_targets_hidden_during_generation": True,
        "grader_frozen_before_candidate_scoring": True,
    }
    receipt = {
        "schema_version": 1,
        "kind": "HELDOUT_CAMPAIGN_SEAL_RECEIPT",
        "campaign_id": campaign["campaign_id"],
        "task_pack_sha256": pack_hash,
        "manifest_sha256": digest(manifest),
        "grader_spec_sha256": grader_hash,
        "baseline_revision": base_revision,
        "candidate_revision": cand_revision,
        "paired_rows": len(baseline_rows),
        "baseline_rows_sha256": digest(baseline_rows),
        "candidate_rows_sha256": digest(candidate_rows),
        "raw_outputs_in_receipt": False,
        "raw_grades_in_receipt": False,
        "questions_in_receipt": False,
        "release_decision_performed": False,
        "limitations": [
            "operator freeze/blinding attestations are provenance claims, not independently witnessed facts",
            "this seal validates binding and sanitization; it does not establish grader calibration or answer truth",
            "MODEL_ASSISTED_UNCALIBRATED grades remain release-blocking under the held-out release gate",
        ],
    }
    receipt["receipt_sha256"] = digest(receipt)
    return manifest, baseline_rows, candidate_rows, campaign, receipt


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--task-pack", required=True)
    p.add_argument("--expected-task-pack-sha256", required=True)
    p.add_argument("--baseline-capture", required=True)
    p.add_argument("--candidate-capture", required=True)
    p.add_argument("--baseline-grades", required=True)
    p.add_argument("--candidate-grades", required=True)
    p.add_argument("--grader-spec", required=True)
    p.add_argument("--expected-grader-spec-sha256", required=True)
    p.add_argument("--campaign-id", required=True)
    p.add_argument("--manifest-file", required=True)
    p.add_argument("--baseline-rows-file", required=True)
    p.add_argument("--candidate-rows-file", required=True)
    p.add_argument("--campaign-file", required=True)
    p.add_argument("--receipt-file", required=True)
    p.add_argument("--attest-outputs-frozen-before-grading", action="store_true")
    p.add_argument("--attest-targets-hidden-during-generation", action="store_true")
    p.add_argument("--attest-grader-frozen-before-candidate-scoring", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest, baseline, candidate, campaign, receipt = build_release_inputs(
            task_pack=_read(args.task_pack, "task pack"),
            expected_task_pack_sha256=args.expected_task_pack_sha256,
            baseline_capture=_read(args.baseline_capture, "baseline capture"),
            candidate_capture=_read(args.candidate_capture, "candidate capture"),
            baseline_grades=_read(args.baseline_grades, "baseline grades"),
            candidate_grades=_read(args.candidate_grades, "candidate grades"),
            grader_spec=_read(args.grader_spec, "grader spec"),
            expected_grader_spec_sha256=args.expected_grader_spec_sha256,
            campaign_id=args.campaign_id,
            attest_outputs_frozen_before_grading=args.attest_outputs_frozen_before_grading,
            attest_targets_hidden_during_generation=args.attest_targets_hidden_during_generation,
            attest_grader_frozen_before_candidate_scoring=args.attest_grader_frozen_before_candidate_scoring,
        )
        _write(args.manifest_file, manifest)
        _write(args.baseline_rows_file, baseline)
        _write(args.candidate_rows_file, candidate)
        _write(args.campaign_file, campaign)
        _write(args.receipt_file, receipt)
    except (CampaignSealError, CampaignCaptureError) as exc:
        print(f"HELDOUT_CAMPAIGN_SEAL_FAIL: {exc}", file=sys.stderr)
        return 2
    print(f"HELDOUT_CAMPAIGN_SEAL_PASS: rows={receipt['paired_rows']} receipt={args.receipt_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
