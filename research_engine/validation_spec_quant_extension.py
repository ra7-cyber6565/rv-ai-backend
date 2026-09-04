"""Final quantitative extensions discovered by the AI-2 line-by-line audit.

Adds generic Monte Carlo receipt summaries and enforces caller-declared
robustness-dimension completeness.  The extension is fail-closed: it never
simulates missing data, invents thresholds, or upgrades a hypothesis status.
"""
from __future__ import annotations

from copy import deepcopy
import math
from statistics import mean, stdev
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence

from .validation_contracts import CONDITIONAL_PASS, INCONCLUSIVE, NOT_TESTED, PASS, RESULT_OBSERVED, meaningful

_POSITIVE = {PASS, CONDITIONAL_PASS}
_PROVENANCE_KEYS = (
    "test_id", "run_id", "dataset_id", "source", "source_id", "timestamp",
    "artifact", "report", "observed_metrics",
)


def _numbers(value: Any) -> List[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    out: List[float] = []
    for item in value:
        if isinstance(item, bool):
            return []
        try:
            number = float(item)
        except (TypeError, ValueError):
            return []
        if not math.isfinite(number):
            return []
        out.append(number)
    return out


def _percentile(values: Sequence[float], q: float) -> Any:
    if not values:
        return NOT_TESTED
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    lo = int(math.floor(pos)); hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def _valid_provenance(receipt: Mapping[str, Any]) -> bool:
    raw = receipt.get("provenance") or receipt.get("result_provenance") or receipt.get("test_provenance")
    return isinstance(raw, Mapping) and any(meaningful(raw.get(key)) for key in _PROVENANCE_KEYS)


def _find_receipt(result: Mapping[str, Any], hypothesis_id: str) -> Optional[Dict[str, Any]]:
    candidates: List[Any] = []
    for key in ("validation_receipts", "experiment_results", "test_results"):
        raw = result.get(key)
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            candidates.extend(raw)
    coverage = result.get("coverage")
    if isinstance(coverage, Mapping):
        for key in ("validation_receipts", "experiment_results", "test_results"):
            raw = coverage.get(key)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
                candidates.extend(raw)
    for item in candidates:
        if isinstance(item, Mapping) and str(item.get("hypothesis_id") or item.get("id") or "") == str(hypothesis_id):
            return dict(item)
    return None


def _monte_carlo_summary(receipt: Mapping[str, Any]) -> Any:
    values = _numbers(receipt.get("monte_carlo_samples"))
    if not values:
        return NOT_TESTED
    if not _valid_provenance(receipt):
        return {"status": NOT_TESTED, "reason": "Generic Monte Carlo samples require the same provenance-bearing result receipt."}
    source = str(receipt.get("monte_carlo_sample_source") or "").strip()
    if not source:
        return {"status": NOT_TESTED, "reason": "monte_carlo_sample_source must identify how the supplied simulation draws were generated."}
    summary = {
        "status": "CALCULATED",
        "test_state": RESULT_OBSERVED,
        "sample_source": source,
        "n": len(values),
        "mean": mean(values),
        "standard_deviation": stdev(values) if len(values) > 1 else 0.0,
        "p05": _percentile(values, 0.05),
        "median": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "minimum": min(values),
        "maximum": max(values),
        "interpretation_rule": (
            "Descriptive summary of caller-supplied Monte Carlo draws only; the draws inherit the supplied model/distribution assumptions "
            "and do not become empirical evidence merely because they were simulated."
        ),
    }
    assumptions = receipt.get("monte_carlo_assumptions")
    summary["assumptions"] = deepcopy(assumptions) if meaningful(assumptions) else NOT_TESTED
    return summary


def _extend_generic_monte_carlo(packet: MutableMapping[str, Any], result: Mapping[str, Any]) -> None:
    sections = packet.get("sections")
    experiment_section = sections.get("6. Exact Experiments / Backtests / Simulations Required") if isinstance(sections, Mapping) else None
    rows = experiment_section.get("domain_hypothesis_experiments") if isinstance(experiment_section, Mapping) else None
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, MutableMapping):
            continue
        receipt = _find_receipt(result, str(row.get("hypothesis_id") or ""))
        if not receipt:
            continue
        summary = _monte_carlo_summary(receipt)
        stat = row.get("statistical_validation")
        if isinstance(stat, MutableMapping) and summary != NOT_TESTED:
            stat["monte_carlo"] = summary
        row["monte_carlo_truth_rule"] = (
            "Monte Carlo can quantify consequences under supplied assumptions; it cannot by itself prove the real-world hypothesis."
        )


def _enforce_declared_robustness_dimensions(packet: MutableMapping[str, Any]) -> None:
    advanced = packet.get("advanced_receipt_analyses")
    robustness = advanced.get("robustness") if isinstance(advanced, Mapping) else None
    if not isinstance(robustness, MutableMapping):
        return
    audit = robustness.get("dimension_coverage_audit")
    if not isinstance(audit, Mapping):
        return
    declared = audit.get("requirements_source") == "SUPPLIED_IN_RECEIPT"
    complete = audit.get("coverage_complete") is True
    if declared and not complete and robustness.get("status") in _POSITIVE:
        robustness["pre_dimension_guard_status"] = robustness.get("status")
        robustness["status"] = INCONCLUSIVE
        decision = robustness.get("decision")
        if isinstance(decision, MutableMapping):
            decision["pre_dimension_guard_status"] = decision.get("status")
            decision["status"] = INCONCLUSIVE
            decision["reason"] = (
                "Positive robustness verdict blocked because caller-declared required robustness dimensions are missing."
            )
        robustness["dimension_guard"] = (
            "INCONCLUSIVE until every caller-declared required robustness dimension is actually represented by a tested scenario."
        )


def extend_ai2_quantitative_receipts(research_result: Mapping[str, Any]) -> Dict[str, Any]:
    enriched = dict(research_result or {})
    raw_packet = enriched.get("ai2_validation")
    if not isinstance(raw_packet, Mapping):
        return enriched
    packet: Dict[str, Any] = deepcopy(dict(raw_packet))
    try:
        _extend_generic_monte_carlo(packet, enriched)
        _enforce_declared_robustness_dimensions(packet)
        audit = packet.get("line_by_line_spec_audit")
        if isinstance(audit, MutableMapping):
            audit["generic_monte_carlo_receipts_supported"] = True
            audit["declared_robustness_dimension_guard_supported"] = True
        enriched["ai2_validation"] = packet
    except Exception:
        enriched["ai2_quantitative_extension"] = {
            "valid": False,
            "error": "ai2_quantitative_extension_failed",
            "truth_rule": "Extension failure does not create or upgrade any empirical result.",
        }
    return enriched
