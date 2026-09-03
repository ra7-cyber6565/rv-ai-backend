"""Production audit wiring for #11 Causal Reasoning and #12 Counterfactual.

Only explicit ``hypothesis['causal_contract']`` structures are executed.  The
wrapper never derives a graph, intervention, factual state, or confounder claim
from prose.  It writes an audit packet under ``coverage`` and never upgrades
answer/status/confidence/truth.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence

from .causal_counterfactual import evaluate_causal_contract


_INSTALLED = False
_MAX_HYPOTHESES = 100


def build_causal_counterfactual_packet(hypotheses: Sequence[Any]) -> Dict[str, Any]:
    if isinstance(hypotheses, (str, bytes, bytearray)) or not isinstance(hypotheses, Sequence):
        raise ValueError("hypotheses must be a bounded sequence")
    if len(hypotheses) > _MAX_HYPOTHESES:
        raise ValueError("hypotheses exceed causal audit budget")

    results = []
    explicit = 0
    invalid = 0
    for index, hypothesis in enumerate(hypotheses, 1):
        if not isinstance(hypothesis, Mapping):
            continue
        contract = hypothesis.get("causal_contract")
        if contract is None:
            continue
        explicit += 1
        hypothesis_id = str(
            hypothesis.get("id") or hypothesis.get("hypothesis_id") or f"H{index}"
        )[:240]
        try:
            audit = evaluate_causal_contract(contract)
        except Exception as exc:
            invalid += 1
            audit = {
                "status": "INVALID_CAUSAL_CONTRACT",
                "method": "bounded_linear_structural_causal_model",
                "natural_language_causal_discovery_performed": False,
                "causal_graph_empirically_proven": False,
                "real_world_effect_proven": False,
                "truth_proven": False,
                "error": type(exc).__name__,
            }
        results.append({"hypothesis_id": hypothesis_id, **audit})

    if explicit == 0:
        status = "NO_EXPLICIT_CONTRACTS"
    elif invalid:
        status = "PARTIAL_INVALID_CONTRACTS"
    else:
        status = "AUDITED"
    return {
        "ran": True,
        "status": status,
        "hypotheses_seen": len(hypotheses),
        "explicit_contracts": explicit,
        "invalid_contracts": invalid,
        "results": results,
        "natural_language_causal_discovery_performed": False,
        "causal_graph_empirically_proven": False,
        "real_world_effect_proven": False,
        "truth_proven": False,
    }


def apply_causal_counterfactual_wiring(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    coverage = dict(data.get("coverage") or {})
    try:
        packet = build_causal_counterfactual_packet(data.get("hypotheses") or [])
    except Exception as exc:
        packet = {
            "ran": False,
            "status": "ASSESSMENT_ERROR",
            "hypotheses_seen": 0,
            "explicit_contracts": 0,
            "invalid_contracts": 0,
            "results": [],
            "natural_language_causal_discovery_performed": False,
            "causal_graph_empirically_proven": False,
            "real_world_effect_proven": False,
            "truth_proven": False,
            "error": type(exc).__name__,
        }
    coverage["causal_counterfactual"] = packet
    data["coverage"] = coverage
    return data


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from . import result_coverage_gate as result_mod

    original_enforce = result_mod.enforce

    def enforce_with_causal_counterfactual(result: Dict[str, Any]) -> Dict[str, Any]:
        return apply_causal_counterfactual_wiring(original_enforce(result))

    result_mod.enforce = enforce_with_causal_counterfactual
