"""Paired, task-clustered evaluation of independently graded run receipts.

This module cannot grade nuanced scientific validity. Grading provenance and
execution kind are mandatory; fixtures cannot become a live superiority claim.
"""
from __future__ import annotations
import math
import random
import statistics
from .research_runtime import digest


def evaluate(manifest, baseline, candidate, *, expected_manifest_hash, seed=0, draws=2000):
    if digest(manifest) != expected_manifest_hash:
        raise ValueError("frozen manifest changed")
    task_ids = manifest.get("task_ids", [])
    if not task_ids or len(task_ids) != len(set(task_ids)):
        raise ValueError("nonempty unique task manifest required")
    if manifest.get("split") not in {"development", "untouched_holdout"}:
        raise ValueError("evaluation split must be declared")
    if manifest.get("split") == "untouched_holdout" and manifest.get("used_for_tuning") is not False:
        raise ValueError("holdout may not have been used for tuning")
    if type(draws) is not int or not 100 <= draws <= 10000:
        raise ValueError("bootstrap draws outside bounded range")

    def index(rows):
        result = {}
        for row in rows:
            key = (row.get("task_id"), row.get("trial"))
            if key in result or key[0] not in task_ids or type(key[1]) is not int:
                raise ValueError("duplicate or unknown task/trial")
            if row.get("execution_kind") not in {"FIXTURE", "RECORDED_REPLAY", "LIVE"}:
                raise ValueError("execution provenance missing")
            if row.get("grader") not in {"DETERMINISTIC", "HUMAN", "MODEL_ASSISTED_UNCALIBRATED"}:
                raise ValueError("grading provenance missing")
            for key_name in ("task_success", "coverage", "citation_support", "abstention_appropriate"):
                value = row.get(key_name)
                if value is not None and (type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1):
                    raise ValueError("invalid metric")
            for key_name in ("http_budget", "seconds_budget", "latency_seconds"):
                value = row.get(key_name)
                if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
                    raise ValueError("resource conditions missing")
            result[key] = row
        return result

    left, right = index(baseline), index(candidate)
    if set(left) != set(right) or {k[0] for k in left} != set(task_ids):
        raise ValueError("paired task/trial coverage is incomplete")
    if any(left[k][f] != right[k][f] for k in left for f in ("http_budget", "seconds_budget")):
        raise ValueError("matched-budget comparison has unequal allocations")
    rng = random.Random(seed)
    metrics = {}
    for name in ("task_success", "coverage", "citation_support", "abstention_appropriate", "latency_seconds"):
        grouped = {}
        for key in sorted(left):
            a, b = left[key].get(name), right[key].get(name)
            if a is not None and b is not None:
                grouped.setdefault(key[0], []).append(b-a)
        deltas = [statistics.mean(values) for values in grouped.values()]
        n = len(deltas)
        if not n:
            metrics[name] = {"eligible_tasks": 0, "status": "NOT_ASSESSED", "delta": None}
            continue
        # Cluster by task so repeated trials are not counted as independent tasks.
        interval = None
        if n >= 2:
            boots = sorted(statistics.mean(rng.choices(deltas, k=n)) for _ in range(draws))
            interval = [boots[int(draws*.025)], boots[min(draws-1, int(draws*.975))]]
        metrics[name] = {"eligible_tasks": n, "delta_candidate_minus_baseline": statistics.mean(deltas),
                         "task_cluster_bootstrap_95_interval": interval,
                         "worst_task_delta": min(deltas), "tasks_worse": sum(d < 0 for d in deltas)}
    kinds = sorted({r["execution_kind"] for r in baseline + candidate})
    return {"manifest_sha256": expected_manifest_hash, "tasks": len(task_ids), "paired_trials": len(left),
            "metrics": metrics, "execution_kinds": kinds, "split": manifest["split"],
            "decision": "INCONCLUSIVE: practical effect threshold and applicable independent grading required",
            "bootstrap_seed": seed, "bootstrap_draws": draws,
            "limitations": ["small task sets give unstable intervals", "no multiple-endpoint success claim",
                            "fixture/replay results do not establish current live performance",
                            "this evaluator validates receipts, not the honesty or calibration of an external grader"]}
