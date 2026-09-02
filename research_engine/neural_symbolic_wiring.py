"""Production audit wiring for capability #67.

Only explicit structured neural proposal contracts are consumed.  Model output
identity/digest/confidence and formal logic must be supplied; no prose is
translated into symbolic logic by this layer.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Mapping, Sequence

from .neural_symbolic_hybrid import NeuralProposal, audit_neural_symbolic

_INSTALLED = False
_MAX = 1000


def _sequence(value: object) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > _MAX:
            raise ValueError("neural symbolic proposal budget exceeded")
        return value
    raise ValueError("neural_symbolic_inputs must be a bounded sequence")


def _inputs(result: Mapping[str, Any]):
    if "neural_symbolic_inputs" in result:
        return result.get("neural_symbolic_inputs")
    coverage = result.get("coverage") if isinstance(result.get("coverage"), Mapping) else {}
    return coverage.get("neural_symbolic_inputs")


def build_neural_symbolic_packet(result: Mapping[str, Any]) -> Dict[str, Any]:
    raw = _inputs(result)
    if raw is None:
        return {
            "ran": True,
            "status": "NO_STRUCTURED_NEURAL_SYMBOLIC_INPUTS",
            "audits": [],
            "natural_language_formalization_performed": False,
            "result_status_upgraded": False,
            "truth_proven": False,
        }
    proposals = []
    for item in _sequence(raw):
        if not isinstance(item, Mapping):
            raise ValueError("each neural symbolic proposal must be a mapping")
        proposals.append(NeuralProposal(
            proposal_id=str(item.get("proposal_id") or ""),
            model_id=str(item.get("model_id") or ""),
            model_revision=str(item.get("model_revision") or ""),
            model_output_sha256=str(item.get("model_output_sha256") or ""),
            model_confidence=item.get("model_confidence", 0.0),
            formal_logic=item.get("formal_logic") or {},
            self_reported_proved=bool(item.get("self_reported_proved")),
        ))
    report = asdict(audit_neural_symbolic(proposals))
    report.update({
        "ran": True,
        "status": "AUDITED",
        "natural_language_formalization_performed": False,
        "result_status_upgraded": False,
    })
    return report


def apply_neural_symbolic_wiring(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    coverage = dict(data.get("coverage") or {})
    try:
        packet = build_neural_symbolic_packet(data)
    except Exception as exc:
        packet = {
            "ran": False,
            "status": "ASSESSMENT_ERROR",
            "audits": [],
            "natural_language_formalization_performed": False,
            "result_status_upgraded": False,
            "truth_proven": False,
            "error": type(exc).__name__,
        }
    coverage["neural_symbolic"] = packet
    data["coverage"] = coverage
    return data


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from . import result_coverage_gate as result_mod
    original_enforce = result_mod.enforce

    def enforce_with_neural_symbolic(result: Dict[str, Any]) -> Dict[str, Any]:
        return apply_neural_symbolic_wiring(original_enforce(result))

    result_mod.enforce = enforce_with_neural_symbolic
