"""Canonical Agent 3 facade: practical + quantitative validation.

This wraps ``validation_agent3`` without weakening its fail-closed rules and
adds the domain-specific contract the handoff requires, especially trading.
It also adds classification evaluation, sample-adequacy, regime/walk-forward
receipts, and hard rejection when real-world friction explicitly fails.

All calculations use caller-supplied observations only. Missing values remain
``NOT TESTED / UNKNOWN``.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .validation_agent3 import (
    Agent3ValidationEngine as _CoreAgent3,
    FinalStatus,
    UNKNOWN,
)


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> List[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else list(value) if isinstance(value, tuple) else [value]


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _first(*values: Any, default: str = "") -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return default


def _number(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _hypotheses(packet: Any) -> List[Mapping[str, Any]]:
    if isinstance(packet, list):
        return [row for row in packet if isinstance(row, Mapping)]
    packet = _map(packet)
    for key in ("hypotheses", "surviving_hypotheses", "candidates", "items"):
        rows = packet.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, Mapping)]
    return [packet] if packet else []


def _hid(h: Mapping[str, Any], index: int) -> str:
    # Agent-2 packets should provide a stable id. When absent, core will create
    # one; this local name is only used to match explicit execution packets.
    return _first(h.get("hypothesis_id"), h.get("id"), h.get("stable_id"), default=f"H{index}")


def classification_metrics(y_true: Sequence[Any], y_pred: Sequence[Any], probabilities: Optional[Sequence[Any]] = None) -> Dict[str, Any]:
    """Actual classification metrics; no synthetic predictions or labels."""
    truth, pred = list(y_true or []), list(y_pred or [])
    if not truth or len(truth) != len(pred):
        return {"status": UNKNOWN, "reason": "y_true/y_pred missing ya unequal"}
    labels = sorted(set(truth) | set(pred), key=lambda x: str(x))
    correct = sum(a == b for a, b in zip(truth, pred))
    per_label: Dict[str, Dict[str, float]] = {}
    recalls: List[float] = []
    f1s: List[float] = []
    for label in labels:
        tp = sum(a == label and b == label for a, b in zip(truth, pred))
        fp = sum(a != label and b == label for a, b in zip(truth, pred))
        fn = sum(a == label and b != label for a, b in zip(truth, pred))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        recalls.append(recall)
        f1s.append(f1)
        per_label[str(label)] = {"precision": precision, "recall": recall, "f1": f1, "support": sum(a == label for a in truth)}
    counts = {label: sum(x == label for x in truth) for label in labels}
    majority = max(counts.values()) / len(truth)
    out: Dict[str, Any] = {
        "status": "TESTED",
        "n": len(truth),
        "accuracy": correct / len(truth),
        "balanced_accuracy": sum(recalls) / len(recalls),
        "macro_f1": sum(f1s) / len(f1s),
        "majority_baseline_accuracy": majority,
        "candidate_beats_majority_baseline": correct / len(truth) > majority,
        "per_label": per_label,
    }
    probs = [_number(x) for x in (probabilities or [])]
    # Binary probability diagnostics only when all probabilities are supplied
    # and truth has exactly two labels. Positive class = sorted last label.
    if len(labels) == 2 and len(probs) == len(truth) and all(x is not None and 0 <= x <= 1 for x in probs):
        positive = labels[-1]
        target = [1.0 if y == positive else 0.0 for y in truth]
        p = [float(x) for x in probs]
        eps = 1e-15
        out["brier_score"] = sum((pi - yi) ** 2 for pi, yi in zip(p, target)) / len(p)
        out["log_loss"] = -sum(yi * math.log(max(eps, min(1-eps, pi))) + (1-yi) * math.log(max(eps, min(1-eps, 1-pi))) for pi, yi in zip(p, target)) / len(p)
    return out


def _domain_contract(domain: str, h: Mapping[str, Any], execution: Mapping[str, Any]) -> Dict[str, Any]:
    plan = _map(h.get("test_plan"))
    if domain == "trading":
        def get(name: str, *aliases: str) -> str:
            values = [execution.get(name), h.get(name), plan.get(name)]
            for alias in aliases:
                values += [execution.get(alias), h.get(alias), plan.get(alias)]
            return _first(*values, default=UNKNOWN)
        return {
            "instrument/feed": get("instrument_feed", "instrument", "feed"),
            "regime": get("regime"),
            "session": get("session"),
            "exact long setup": get("long_setup", "exact_long_setup"),
            "exact short setup": get("short_setup", "exact_short_setup"),
            "entry": get("entry", "entry_rule"),
            "stop": get("stop", "stop_loss", "sl"),
            "TP": get("take_profit", "tp"),
            "position sizing": get("position_sizing", "risk_rule"),
            "no-trade": get("no_trade", "avoid_rules"),
            "news": get("news", "news_rule"),
            "transaction costs": get("transaction_cost_model", "cost_model"),
            "sample size requirement": get("minimum_sample_size", "sample_size_requirement"),
            "out-of-sample": get("out_of_sample"),
            "walk-forward": get("walk_forward"),
            "Monte Carlo": get("monte_carlo"),
            "parameter robustness": get("parameter_robustness"),
            "edge decay": get("edge_decay"),
        }
    if domain == "engineering":
        return {
            "tolerances": _first(execution.get("tolerances"), h.get("tolerances"), default=UNKNOWN),
            "heat/thermal": _first(execution.get("thermal_limits"), h.get("thermal_limits"), default=UNKNOWN),
            "failure rate": _first(execution.get("failure_rate_target"), h.get("failure_rate_target"), default=UNKNOWN),
            "hardware limits": _first(execution.get("hardware_limits"), h.get("hardware_limits"), default=UNKNOWN),
            "manufacturing cost": _first(execution.get("manufacturing_cost"), h.get("manufacturing_cost"), default=UNKNOWN),
        }
    if domain == "business":
        return {
            "taxes": _first(execution.get("taxes"), h.get("taxes"), default=UNKNOWN),
            "acquisition costs": _first(execution.get("acquisition_costs"), h.get("acquisition_costs"), default=UNKNOWN),
            "churn": _first(execution.get("churn"), h.get("churn"), default=UNKNOWN),
            "operational friction": _first(execution.get("operational_friction"), h.get("operational_friction"), default=UNKNOWN),
        }
    return {
        "domain-specific implementation constraints": _list(h.get("implementation_constraints")) or [UNKNOWN],
    }


def _prepare_executions(executions: Optional[Mapping[str, Mapping[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    prepared: Dict[str, Dict[str, Any]] = copy.deepcopy(dict(_map(executions)))
    for hid, raw in list(prepared.items()):
        if not isinstance(raw, Mapping):
            prepared[hid] = {}
            continue
        row = dict(raw)
        kind = _first(row.get("kind"), row.get("test_kind")).lower()
        if kind in ("classification", "classifier"):
            metrics = classification_metrics(row.get("y_true") or [], row.get("y_pred") or [], row.get("probabilities"))
            if metrics.get("status") == "TESTED":
                row["kind"] = "precomputed"
                row["executed"] = True
                row["sample_size"] = metrics["n"]
                row["metrics"] = {k: v for k, v in metrics.items() if k not in ("status", "per_label", "candidate_beats_majority_baseline", "n")}
                row["classification_detail"] = metrics
                row["baseline_results"] = {
                    "majority_baseline_accuracy": metrics["majority_baseline_accuracy"],
                    "candidate_beats_baseline": metrics["candidate_beats_majority_baseline"],
                }
        prepared[hid] = row
    return prepared


def _regime_receipt(execution: Mapping[str, Any]) -> Dict[str, Any]:
    rows = [row for row in _list(execution.get("regime_runs")) if isinstance(row, Mapping)]
    if not rows:
        return {"status": UNKNOWN, "reason": "regime-specific runs not supplied"}
    metric = _first(execution.get("primary_metric"), default="score")
    output = []
    for row in rows:
        value = _number(row.get(metric))
        output.append({"regime": _first(row.get("regime"), row.get("name"), default="unknown"), metric: value if value is not None else UNKNOWN, "failed": bool(row.get("failed")) if "failed" in row else UNKNOWN})
    return {"status": "TESTED", "metric": metric, "rows": output, "any_explicit_failure": any(x.get("failed") is True for x in output)}


def _walk_forward_receipt(execution: Mapping[str, Any]) -> Dict[str, Any]:
    rows = [row for row in _list(execution.get("walk_forward_runs")) if isinstance(row, Mapping)]
    if not rows:
        return {"status": UNKNOWN, "reason": "walk-forward folds not supplied"}
    metric = _first(execution.get("primary_metric"), default="score")
    values = [_number(row.get(metric)) for row in rows]
    values = [x for x in values if x is not None]
    if not values:
        return {"status": UNKNOWN, "reason": f"walk-forward {metric} missing"}
    return {"status": "TESTED", "metric": metric, "folds": len(values), "values": values, "mean": sum(values)/len(values), "min": min(values), "max": max(values)}


def _recompute(packet: Dict[str, Any]) -> None:
    final = packet["14. FINAL VALIDATION PACKET FOR AGENT 4"]
    validations = final.get("validations") or []
    final["pass"] = sum(x.get("status") == FinalStatus.PASS.value for x in validations)
    final["conditional_pass"] = sum(x.get("status") == FinalStatus.CONDITIONAL_PASS.value for x in validations)
    final["inconclusive"] = sum(x.get("status") == FinalStatus.INCONCLUSIVE.value for x in validations)
    final["fail"] = sum(x.get("status") == FinalStatus.FAIL.value for x in validations)
    survivors = [
        {"hypothesis_id": x.get("hypothesis_id"), "status": x.get("status"), "statement": x.get("statement"), "scope_warning": "Do not generalize beyond tested population/time/regime."}
        for x in validations if x.get("status") in (FinalStatus.PASS.value, FinalStatus.CONDITIONAL_PASS.value)
    ]
    final["survivors"] = survivors
    packet["11. Surviving final candidates"] = survivors
    # Keep the original practical candidate only if it still survived post-audit.
    practical = packet.get("12. Practical implementation candidate") or {}
    if practical.get("hypothesis_id") not in {x["hypothesis_id"] for x in survivors}:
        packet["12. Practical implementation candidate"] = {"status": "NONE", "reason": "Post-validation hard gates removed the previous candidate.", "steps": []}


class Agent3ValidationEngine(_CoreAgent3):
    """Max-level Agent 3 facade used by the multi-agent pipeline."""

    def validate(self, question: str, research_packet: Mapping[str, Any], hypothesis_packet: Any, execution_packets: Optional[Mapping[str, Mapping[str, Any]]] = None) -> Dict[str, Any]:
        prepared = _prepare_executions(execution_packets)
        packet = super().validate(question, research_packet, hypothesis_packet, prepared)
        final = packet["14. FINAL VALIDATION PACKET FOR AGENT 4"]
        hypotheses = _hypotheses(hypothesis_packet)
        by_id = {_hid(h, i): h for i, h in enumerate(hypotheses, 1)}

        for validation in final.get("validations") or []:
            hid = _text(validation.get("hypothesis_id"))
            h = by_id.get(hid, {})
            execution = _map(prepared.get(hid))
            matrix = validation.get("test_matrix") or {}
            domain = _first(matrix.get("domain"), h.get("domain"), default="general").lower()
            matrix["domain_specific"] = _domain_contract(domain, h, execution)
            validation["test_matrix"] = matrix

            result = validation.get("result") or {}
            robustness = result.setdefault("robustness", {})
            robustness["regime_testing"] = _regime_receipt(execution)
            robustness["walk_forward"] = _walk_forward_receipt(execution)
            if execution.get("classification_detail"):
                result.setdefault("statistical_tests", {})["classification_detail"] = execution["classification_detail"]

            # Sample adequacy: a small experiment cannot become FAIL/PASS merely
            # because the point estimate looked good; it remains INCONCLUSIVE.
            minimum = _number(execution.get("minimum_sample_size"))
            sample = _number(result.get("sample_size")) or 0.0
            if minimum is not None:
                result["sample_adequacy"] = {"required": int(minimum), "observed": int(sample), "adequate": sample >= minimum}
                if sample < minimum:
                    validation["status"] = FinalStatus.INCONCLUSIVE.value
                    validation["surviving_candidate"] = False
                    validation["reason"] = f"Sample requirement not met: observed {int(sample)} < required {int(minimum)}."

            # User's hard rule: a theoretical edge that explicitly FAILS after
            # real-world friction is rejected, not merely downgraded.
            friction_status = _first((result.get("friction") or {}).get("status")).upper()
            if friction_status == "FAIL":
                validation["status"] = FinalStatus.FAIL.value
                validation["surviving_candidate"] = False
                validation["reason"] = "Real-world friction test failed; theoretical advantage did not survive implementation costs/constraints."

            regime = robustness["regime_testing"]
            if execution.get("regime_failure") is True or regime.get("any_explicit_failure") is True and execution.get("regime_failure_is_fatal") is True:
                validation["status"] = FinalStatus.FAIL.value
                validation["surviving_candidate"] = False
                validation["reason"] = "Pre-specified fatal regime failure triggered. Rejection is limited to the tested model/scope."

            if execution.get("edge_decay_failed") is True:
                validation["status"] = FinalStatus.FAIL.value
                validation["surviving_candidate"] = False
                validation["reason"] = "Pre-specified edge-decay failure triggered on later/rolling data."

            result["hard_rule_note"] = "Metrics not supplied by actual execution remain NOT TESTED / UNKNOWN."
            validation["result"] = result

            # Mirror post-audit status into the top-level section 5.
            if hid in packet["5. Hypothesis results"]:
                packet["5. Hypothesis results"][hid]["status"] = validation["status"]
                packet["5. Hypothesis results"][hid]["reason"] = validation["reason"]
            packet["6. Robustness tests"][hid] = robustness
            packet["9. Real-world friction results"][hid] = result.get("friction") or {"status": UNKNOWN}

        _recompute(packet)
        final["agent3_max_rules"] = [
            "Baseline first; complexity must beat the declared simple baseline.",
            "Untouched test cannot be used for tuning.",
            "Critical leakage invalidates the result.",
            "Insufficient sample => INCONCLUSIVE.",
            "Explicit real-world friction failure => FAIL.",
            "Fatal regime/edge-decay failure => FAIL only for tested scope.",
            "Ablations that do not materially hurt performance should be removed.",
            "No actual data => NOT TESTED / UNKNOWN, never fake metrics.",
        ]
        return packet


__all__ = ["Agent3ValidationEngine", "classification_metrics"]
