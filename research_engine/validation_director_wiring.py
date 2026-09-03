"""Production wiring for AI-2 quantitative validation.

Every normal ``ResearchResult.to_dict()`` path receives a deterministic AI-2
validation *plan/audit* derived from the structured question/hypothesis objects
already present in the result.  This stage intentionally does not pretend that
research text, a hypothesis, or an internal lab calculation is a real-world
experiment.

No network/model/API call occurs.  No result status or evidence grade is
upgraded.  Absent execution observations remain TEST PROPOSED / INCONCLUSIVE.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

from .validation_director_integrated import IntegratedQuantitativeValidationDirector
from .validation_types import UNKNOWN, mapping, text

_INSTALLED = False
_MAX_HYPOTHESES = 32


def _bounded_hypotheses(values: Any) -> List[Mapping[str, Any]]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        return []
    out: List[Mapping[str, Any]] = []
    for value in list(values)[:_MAX_HYPOTHESES]:
        if isinstance(value, Mapping):
            out.append(value)
    return out


def _first_experiment(hypotheses: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    for hypothesis in hypotheses:
        experiment = hypothesis.get("experiment")
        if isinstance(experiment, Mapping):
            return experiment
    return {}


def _proposal_hypotheses(hypotheses: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(hypotheses, 1):
        experiment = mapping(item.get("experiment"))
        statement = text(
            item.get("statement")
            or item.get("hypothesis")
            or item.get("title")
            or item.get("claim"),
            f"Candidate hypothesis {index}",
        )
        variables = experiment.get("measured_variables") or item.get("variables") or []
        if isinstance(variables, str):
            variables = [variables]
        rows.append({
            "hypothesis_id": text(item.get("id") or item.get("hypothesis_id"), f"H{index}"),
            "statement": statement,
            "mechanism": text(item.get("mechanism"), UNKNOWN),
            "prediction": text(
                item.get("prediction") or experiment.get("prediction"),
                "A predeclared measurable result must distinguish this hypothesis from its baseline/rivals.",
            ),
            "null_hypothesis": text(
                experiment.get("null_hypothesis"),
                "The observed result is no better/different than the declared baseline or rival explanation.",
            ),
            "variables": list(variables) if isinstance(variables, Sequence) else [],
            "baseline_id": text(experiment.get("control_or_baseline"), "B1"),
            "test": text(
                experiment.get("setup") or experiment.get("experimental_setup") or item.get("test"),
                "Prospective or held-out comparison under a frozen protocol.",
            ),
            "falsification_condition": text(
                experiment.get("falsification_condition") or item.get("falsification_condition"),
                "The predeclared prediction fails under a valid independent evaluation.",
            ),
            "scope": text(item.get("scope"), "Only the explicitly tested population/time/regime."),
        })
    return rows


def build_runtime_ai2_validation_packet(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Build a plan-only AI-2 packet from one structured research result."""
    data = dict(result or {})
    question = text(data.get("question"), UNKNOWN)
    hypotheses = _bounded_hypotheses(data.get("hypotheses") or [])
    experiment = _first_experiment(hypotheses)

    primary_metric = text(experiment.get("statistical_metric"), UNKNOWN)
    dataset_sample = text(experiment.get("dataset_or_sample"), UNKNOWN)
    proposal: Dict[str, Any] = {
        "goal": question,
        "required_outcome": (
            "Determine which proposed explanation/model survives explicit quantitative, "
            "falsifiable, baseline-controlled validation."
        ),
        "hypotheses": _proposal_hypotheses(hypotheses),
        "primary_metric": primary_metric,
        "dataset_sample": dataset_sample,
        "data_available": False,
        "measurability_limits": [
            "This runtime adapter receives research/hypothesis structures, not a verified real-world execution ledger.",
            "Internal calculations/simulations are not silently promoted to real-world experimental evidence.",
        ],
    }

    director = IntegratedQuantitativeValidationDirector()
    packet = director.analyze(
        question,
        proposal=proposal,
        execution_packets={},
        agent_outputs={
            "red_team_objections": [
                text(row.get("summary") or row.get("claim") or row.get("text"))
                for row in _bounded_hypotheses(data.get("contradictions") or [])
                if text(row.get("summary") or row.get("claim") or row.get("text"))
            ][:8]
        },
        phase="first",
    )
    packet["runtime_wiring"] = {
        "ran": True,
        "mode": "PLAN_ONLY_FROM_STRUCTURED_RESEARCH_RESULT",
        "execution_packets_supplied": False,
        "real_world_experiment_executed": False,
        "internal_lab_counts_as_real_world_validation": False,
        "truth_proven": False,
        "result_status_upgraded": False,
        "hypotheses_seen": len(hypotheses),
        "hypotheses_truncated": max(0, len(data.get("hypotheses") or []) - len(hypotheses))
        if isinstance(data.get("hypotheses"), Sequence) and not isinstance(data.get("hypotheses"), (str, bytes, bytearray))
        else 0,
    }
    return packet


def apply_runtime_ai2_validation(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    coverage = dict(data.get("coverage") or {})
    try:
        packet = build_runtime_ai2_validation_packet(data)
    except Exception as exc:
        packet = {
            "agent_id": "AI-2 / VALIDATION-DIRECTOR",
            "status": "ASSESSMENT_ERROR",
            "results": [],
            "hypotheses": [],
            "runtime_wiring": {
                "ran": False,
                "mode": "PLAN_ONLY_FROM_STRUCTURED_RESEARCH_RESULT",
                "execution_packets_supplied": False,
                "real_world_experiment_executed": False,
                "truth_proven": False,
                "result_status_upgraded": False,
                "error": type(exc).__name__,
            },
            "confidence": 0,
            "higher_score_blockers": ["AI-2 runtime validation packet could not be constructed."],
        }
    coverage["ai2_validation"] = packet
    data["coverage"] = coverage
    return data


def install() -> None:
    """Install after existing result gates; wrapping is idempotent."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from . import result_coverage_gate as result_mod

    original_enforce = result_mod.enforce

    def enforce_with_ai2_validation(result: Dict[str, Any]) -> Dict[str, Any]:
        return apply_runtime_ai2_validation(original_enforce(result))

    result_mod.enforce = enforce_with_ai2_validation


__all__ = [
    "build_runtime_ai2_validation_packet",
    "apply_runtime_ai2_validation",
    "install",
]
