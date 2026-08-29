"""Production wiring for capability #100 Economic Reality Test.

Only explicit ``economic_reality_inputs`` contracts are evaluated.  The wiring
never extracts or invents revenue, demand, costs, capex, discount rates or
scenario probabilities from free-form prose and never upgrades the parent
research result's status, answer or scientific truth labels.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Mapping, Sequence

from .economic_reality import EconomicScenario, assess_economic_reality


_INSTALLED = False
_MAX_RUNTIME_SCENARIOS = 1_000


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping")
    return value


def _sequence(value: object, field: str) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > _MAX_RUNTIME_SCENARIOS:
            raise ValueError(f"{field} exceeds runtime budget")
        return value
    raise ValueError(f"{field} must be a bounded sequence")


def _inputs(result: Mapping[str, Any]):
    if "economic_reality_inputs" in result:
        return result.get("economic_reality_inputs")
    coverage = result.get("coverage") if isinstance(result.get("coverage"), Mapping) else {}
    return coverage.get("economic_reality_inputs")


def _scenario(raw: object) -> EconomicScenario:
    row = _mapping(raw, "economic scenario")
    allowed = {
        "scenario_id",
        "probability",
        "currency",
        "discount_rate",
        "initial_capex",
        "revenues",
        "operating_costs",
        "provenance_ref",
        "input_basis",
        "other_cash_flows",
        "starting_cash",
        "unit_price",
        "unit_variable_cost",
        "fixed_cost_per_period",
    }
    unknown = set(row) - allowed
    if unknown:
        raise ValueError("unknown economic scenario keys: " + ", ".join(sorted(unknown)))
    required = {
        "scenario_id",
        "probability",
        "currency",
        "discount_rate",
        "initial_capex",
        "revenues",
        "operating_costs",
        "provenance_ref",
        "input_basis",
    }
    missing = sorted(required - set(row))
    if missing:
        raise ValueError("economic scenario missing: " + ", ".join(missing))
    return EconomicScenario(
        scenario_id=str(row.get("scenario_id") or ""),
        probability=row.get("probability"),
        currency=str(row.get("currency") or ""),
        discount_rate=row.get("discount_rate"),
        initial_capex=row.get("initial_capex"),
        revenues=tuple(row.get("revenues") or ()),
        operating_costs=tuple(row.get("operating_costs") or ()),
        provenance_ref=str(row.get("provenance_ref") or ""),
        input_basis=dict(_mapping(row.get("input_basis"), "input_basis")),
        other_cash_flows=tuple(row.get("other_cash_flows") or ()),
        starting_cash=row.get("starting_cash"),
        unit_price=row.get("unit_price"),
        unit_variable_cost=row.get("unit_variable_cost"),
        fixed_cost_per_period=row.get("fixed_cost_per_period"),
    )


def build_economic_reality_packet(result: Mapping[str, Any]) -> Dict[str, Any]:
    raw = _inputs(result)
    if raw is None:
        return {
            "ran": True,
            "status": "NO_STRUCTURED_ECONOMIC_INPUTS",
            "free_form_economics_inference_performed": False,
            "result_status_upgraded": False,
            "profitability_proven": False,
            "real_world_viability_proven": False,
            "truth_proven": False,
        }
    contract = _mapping(raw, "economic_reality_inputs")
    if set(contract) != {"scenarios"}:
        raise ValueError("economic_reality_inputs must contain exactly scenarios")
    scenarios = tuple(_scenario(row) for row in _sequence(contract["scenarios"], "scenarios"))
    report = asdict(assess_economic_reality(scenarios))
    report.update({
        "ran": True,
        "status": "AUDITED",
        "free_form_economics_inference_performed": False,
        "result_status_upgraded": False,
    })
    return report


def apply_economic_reality_wiring(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    coverage = dict(data.get("coverage") or {})
    try:
        packet = build_economic_reality_packet(data)
    except Exception as exc:
        packet = {
            "ran": False,
            "status": "ASSESSMENT_ERROR",
            "free_form_economics_inference_performed": False,
            "result_status_upgraded": False,
            "profitability_proven": False,
            "real_world_viability_proven": False,
            "truth_proven": False,
            "error": type(exc).__name__,
        }
    coverage["economic_reality"] = packet
    data["coverage"] = coverage
    return data


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from . import result_coverage_gate as result_mod
    original_enforce = result_mod.enforce

    def enforce_with_economic_reality(result: Dict[str, Any]) -> Dict[str, Any]:
        return apply_economic_reality_wiring(original_enforce(result))

    result_mod.enforce = enforce_with_economic_reality
