"""Fail-closed held-out release policy on top of the paired evaluator.

The paired evaluator measures independently graded receipts and keeps uncertainty
visible. This module adds the *predeclared policy* needed for one narrow release
decision. It does not grade answers, inspect gold labels, or turn fixture/replay
data into a live superiority claim.

Anything ambiguous is INCONCLUSIVE and therefore release-blocking.
"""
from __future__ import annotations

import math
import re
from typing import Any

from .paired_evaluation import evaluate
from .research_runtime import digest

_HIGHER_IS_BETTER = {
    "task_success", "coverage", "citation_support", "abstention_appropriate",
}
_ALL_METRICS = _HIGHER_IS_BETTER | {"latency_seconds"}
_GRADERS = {"DETERMINISTIC", "HUMAN", "MODEL_ASSISTED_UNCALIBRATED"}
_EXECUTION_KINDS = {"FIXTURE", "RECORDED_REPLAY", "LIVE"}
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_MANIFEST_KEYS = {
    "answer", "answers", "gold", "gold_answer", "gold_answers", "ground_truth",
    "ground_truths", "label", "labels", "reference_answer", "reference_answers",
    "rubric", "solution", "solutions",
}


class HeldoutGateError(ValueError):
    """Malformed or non-auditable campaign input."""


def _number(value: Any, *, minimum: float | None = None,
            maximum: float | None = None, label: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(value):
        raise HeldoutGateError(f"{label} must be a finite number")
    value = float(value)
    if minimum is not None and value < minimum:
        raise HeldoutGateError(f"{label} is below its allowed minimum")
    if maximum is not None and value > maximum:
        raise HeldoutGateError(f"{label} is above its allowed maximum")
    return value


def _sha40(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA40.fullmatch(text):
        raise HeldoutGateError(f"{label} must be a full 40-character Git SHA")
    return text


def _sha256(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256.fullmatch(text):
        raise HeldoutGateError(f"{label} must be a 64-character SHA-256")
    return text


def _assert_blind_manifest(value: Any, path: str = "manifest") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
            if normalized in _FORBIDDEN_MANIFEST_KEYS:
                raise HeldoutGateError(
                    f"{path} contains grading-target field {key!r}; generation manifest must stay blind"
                )
            _assert_blind_manifest(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_blind_manifest(item, f"{path}[{index}]")


def _campaign(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise HeldoutGateError("campaign receipt schema_version must be 1")
    baseline = _sha40(value.get("baseline_revision"), "baseline_revision")
    candidate = _sha40(value.get("candidate_revision"), "candidate_revision")
    if baseline == candidate:
        raise HeldoutGateError("baseline and candidate revisions must differ")
    attestations = (
        "outputs_frozen_before_grading",
        "holdout_targets_hidden_during_generation",
        "grader_frozen_before_candidate_scoring",
    )
    for name in attestations:
        if value.get(name) is not True:
            raise HeldoutGateError(f"campaign attestation {name} must be explicitly true")
    return {
        "campaign_id": str(value.get("campaign_id") or "").strip(),
        "baseline_revision": baseline,
        "candidate_revision": candidate,
        "grader_spec_sha256": _sha256(value.get("grader_spec_sha256"), "grader_spec_sha256"),
    }


def _policy(value: Any, expected_hash: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise HeldoutGateError("release policy schema_version must be 1")
    expected_hash = _sha256(expected_hash, "expected_policy_hash")
    if digest(value) != expected_hash:
        raise HeldoutGateError("frozen release policy changed")
    primary = str(value.get("primary_metric") or "")
    if primary not in _HIGHER_IS_BETTER:
        raise HeldoutGateError("primary_metric must be a supported quality metric")
    min_tasks = value.get("min_tasks")
    if type(min_tasks) is not int or min_tasks < 2:
        raise HeldoutGateError("min_tasks must be an integer >= 2")
    kind = str(value.get("required_execution_kind") or "")
    if kind not in _EXECUTION_KINDS:
        raise HeldoutGateError("required_execution_kind is invalid")
    graders = value.get("allowed_graders")
    if not isinstance(graders, list) or not graders:
        raise HeldoutGateError("allowed_graders must be a nonempty list")
    graders = sorted({str(item) for item in graders})
    if set(graders) - _GRADERS:
        raise HeldoutGateError("allowed_graders contains an unsupported grader")
    nonreg_raw = value.get("non_regression")
    if not isinstance(nonreg_raw, dict) or not nonreg_raw:
        raise HeldoutGateError("non_regression must declare at least one metric")
    nonreg: dict[str, dict[str, float]] = {}
    for metric, rule in nonreg_raw.items():
        metric = str(metric)
        if metric not in _ALL_METRICS or metric == primary or not isinstance(rule, dict):
            raise HeldoutGateError("invalid non_regression metric/rule")
        worse = _number(rule.get("max_tasks_worse_fraction"), minimum=0, maximum=1,
                        label=f"non_regression.{metric}.max_tasks_worse_fraction")
        if metric == "latency_seconds":
            nonreg[metric] = {
                "max_increase": _number(rule.get("max_increase"), minimum=0,
                                        label=f"non_regression.{metric}.max_increase"),
                "max_tasks_worse_fraction": worse,
            }
        else:
            item = {
                "max_drop": _number(rule.get("max_drop"), minimum=0, maximum=1,
                                    label=f"non_regression.{metric}.max_drop"),
                "max_tasks_worse_fraction": worse,
            }
            if "candidate_min" in rule:
                item["candidate_min"] = _number(rule.get("candidate_min"), minimum=0, maximum=1,
                                                label=f"non_regression.{metric}.candidate_min")
            nonreg[metric] = item
    return {
        "primary_metric": primary,
        "min_tasks": min_tasks,
        "primary_min_effect": _number(value.get("primary_min_effect"), minimum=0, maximum=1,
                                      label="primary_min_effect"),
        "primary_candidate_min": _number(value.get("primary_candidate_min"), minimum=0, maximum=1,
                                         label="primary_candidate_min"),
        "primary_max_tasks_worse_fraction": _number(
            value.get("primary_max_tasks_worse_fraction"), minimum=0, maximum=1,
            label="primary_max_tasks_worse_fraction"),
        "required_execution_kind": kind,
        "allowed_graders": graders,
        "non_regression": nonreg,
    }


def _rows(rows: Any, *, revision: str, label: str) -> tuple[set[str], list[str]]:
    if not isinstance(rows, list) or not rows:
        raise HeldoutGateError(f"{label} receipts must be a nonempty list")
    graders: set[str] = set()
    outputs: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise HeldoutGateError(f"{label}[{index}] must be an object")
        if _sha40(row.get("revision"), f"{label}[{index}].revision") != revision:
            raise HeldoutGateError(f"{label}[{index}] is not bound to the declared revision")
        outputs.append(_sha256(row.get("output_sha256"), f"{label}[{index}].output_sha256"))
        _sha256(row.get("grade_sha256"), f"{label}[{index}].grade_sha256")
        grader = str(row.get("grader") or "")
        if grader not in _GRADERS:
            raise HeldoutGateError(f"{label}[{index}] has unsupported grader provenance")
        graders.add(grader)
    return graders, outputs


def _complete(metric: Any, tasks: int) -> bool:
    return (
        isinstance(metric, dict)
        and metric.get("eligible_tasks") == tasks
        and metric.get("missing_pairs") == 0
        and isinstance(metric.get("task_cluster_bootstrap_95_interval"), list)
        and len(metric["task_cluster_bootstrap_95_interval"]) == 2
    )


def assess_release(manifest: Any, baseline: Any, candidate: Any, policy: Any,
                   campaign: Any, *, expected_manifest_hash: str,
                   expected_policy_hash: str, seed: int = 0,
                   draws: int = 2000) -> dict[str, Any]:
    """Return a sanitized PASS/FAIL/INCONCLUSIVE held-out release receipt."""
    if not isinstance(manifest, dict):
        raise HeldoutGateError("manifest must be an object")
    _assert_blind_manifest(manifest)
    if manifest.get("split") != "untouched_holdout" or manifest.get("used_for_tuning") is not False:
        raise HeldoutGateError("release gate requires an untouched holdout with used_for_tuning=false")
    expected_manifest_hash = _sha256(expected_manifest_hash, "expected_manifest_hash")
    if digest(manifest) != expected_manifest_hash:
        raise HeldoutGateError("frozen holdout manifest changed")

    campaign = _campaign(campaign)
    policy = _policy(policy, expected_policy_hash)
    base_graders, base_outputs = _rows(
        baseline, revision=campaign["baseline_revision"], label="baseline")
    cand_graders, cand_outputs = _rows(
        candidate, revision=campaign["candidate_revision"], label="candidate")
    graders = base_graders | cand_graders

    report = evaluate(manifest, baseline, candidate,
                      expected_manifest_hash=expected_manifest_hash,
                      seed=seed, draws=draws)
    tasks = int(report.get("tasks") or 0)
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    failures: list[str] = []
    uncertain: list[str] = []

    if tasks < policy["min_tasks"]:
        uncertain.append(f"only {tasks} held-out tasks; policy requires {policy['min_tasks']}")
    kinds = report.get("execution_kinds") if isinstance(report.get("execution_kinds"), list) else []
    if kinds != [policy["required_execution_kind"]]:
        uncertain.append("execution provenance does not match the predeclared release policy")
    if not graders.issubset(set(policy["allowed_graders"])):
        uncertain.append("one or more graders are outside the predeclared allowed set")
    if "MODEL_ASSISTED_UNCALIBRATED" in graders:
        uncertain.append("uncalibrated model-assisted grading cannot authorize release")

    primary_name = policy["primary_metric"]
    primary = metrics.get(primary_name) if isinstance(metrics.get(primary_name), dict) else {}
    primary_summary: dict[str, Any] = {"metric": primary_name}
    if not _complete(primary, tasks):
        uncertain.append(f"primary metric {primary_name} lacks complete task-cluster uncertainty")
    else:
        low, high = [float(v) for v in primary["task_cluster_bootstrap_95_interval"]]
        candidate_mean = float(primary["candidate_task_mean"])
        worse_fraction = float(primary["tasks_worse"]) / max(1, int(primary["eligible_tasks"]))
        primary_summary.update({
            "baseline_task_mean": primary["baseline_task_mean"],
            "candidate_task_mean": candidate_mean,
            "delta_candidate_minus_baseline": primary["delta_candidate_minus_baseline"],
            "bootstrap_95_interval": [low, high],
            "tasks_worse": primary["tasks_worse"],
            "tasks_worse_fraction": worse_fraction,
            "required_min_effect": policy["primary_min_effect"],
            "required_candidate_min": policy["primary_candidate_min"],
            "allowed_tasks_worse_fraction": policy["primary_max_tasks_worse_fraction"],
        })
        if candidate_mean < policy["primary_candidate_min"]:
            failures.append(f"primary metric {primary_name} candidate floor was missed")
        if worse_fraction > policy["primary_max_tasks_worse_fraction"]:
            failures.append(f"primary metric {primary_name} regressed on too many task clusters")
        threshold = policy["primary_min_effect"]
        if high <= threshold:
            failures.append(f"primary metric {primary_name} is below the practical-effect requirement")
        elif low <= threshold:
            uncertain.append(f"primary metric {primary_name} uncertainty crosses the practical-effect requirement")

    nonreg_summaries: dict[str, Any] = {}
    for metric_name, rule in policy["non_regression"].items():
        metric = metrics.get(metric_name) if isinstance(metrics.get(metric_name), dict) else {}
        summary: dict[str, Any] = {"metric": metric_name, **rule}
        nonreg_summaries[metric_name] = summary
        if not _complete(metric, tasks):
            uncertain.append(f"non-regression metric {metric_name} lacks complete task-cluster uncertainty")
            continue
        low, high = [float(v) for v in metric["task_cluster_bootstrap_95_interval"]]
        candidate_mean = float(metric["candidate_task_mean"])
        worse_fraction = float(metric["tasks_worse"]) / max(1, int(metric["eligible_tasks"]))
        summary.update({
            "baseline_task_mean": metric["baseline_task_mean"],
            "candidate_task_mean": candidate_mean,
            "delta_candidate_minus_baseline": metric["delta_candidate_minus_baseline"],
            "bootstrap_95_interval": [low, high],
            "tasks_worse": metric["tasks_worse"],
            "tasks_worse_fraction": worse_fraction,
        })
        if worse_fraction > rule["max_tasks_worse_fraction"]:
            failures.append(f"non-regression metric {metric_name} worsened on too many task clusters")
        if metric_name == "latency_seconds":
            tolerance = rule["max_increase"]
            if low > tolerance:
                failures.append("latency regression exceeds the allowed increase")
            elif high > tolerance:
                uncertain.append("latency uncertainty crosses the allowed increase")
        else:
            tolerance = rule["max_drop"]
            if "candidate_min" in rule and candidate_mean < rule["candidate_min"]:
                failures.append(f"non-regression metric {metric_name} candidate floor was missed")
            if high < -tolerance:
                failures.append(f"non-regression metric {metric_name} exceeds the allowed drop")
            elif low < -tolerance:
                uncertain.append(f"non-regression metric {metric_name} uncertainty crosses the allowed drop")

    decision = "FAIL" if failures else "INCONCLUSIVE" if uncertain else "PASS"
    receipt = {
        "schema_version": 1,
        "decision": decision,
        "release_allowed": decision == "PASS",
        "manifest_sha256": expected_manifest_hash,
        "policy_sha256": _sha256(expected_policy_hash, "expected_policy_hash"),
        "campaign_id": campaign["campaign_id"],
        "baseline_revision": campaign["baseline_revision"],
        "candidate_revision": campaign["candidate_revision"],
        "baseline_output_set_sha256": digest(sorted(base_outputs)),
        "candidate_output_set_sha256": digest(sorted(cand_outputs)),
        "grader_spec_sha256": campaign["grader_spec_sha256"],
        "operator_attestations": {
            "outputs_frozen_before_grading": True,
            "holdout_targets_hidden_during_generation": True,
            "grader_frozen_before_candidate_scoring": True,
        },
        "tasks": tasks,
        "paired_trials": report.get("paired_trials"),
        "execution_kinds": kinds,
        "graders": sorted(graders),
        "primary": primary_summary,
        "non_regression": nonreg_summaries,
        "failures": failures,
        "inconclusive_reasons": uncertain,
        "bootstrap_seed": report.get("bootstrap_seed"),
        "bootstrap_draws": report.get("bootstrap_draws"),
        "limitations": list(report.get("limitations") or []) + [
            "operator attestations are recorded provenance claims, not independently witnessed facts",
            "PASS applies only to the frozen benchmark, policy, revisions, execution kind and grader receipts named here",
            "benchmark PASS is comparative release evidence, not proof that every answer is true or independently replicated",
        ],
    }
    receipt["receipt_sha256"] = digest(receipt)
    return receipt


__all__ = ["HeldoutGateError", "assess_release"]
