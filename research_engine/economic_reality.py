"""Capability #100 — deterministic Economic Reality Test.

This engine asks a deliberately narrower question than "will this business or
technology succeed?": given an explicit, provenance-labelled set of economic
assumptions, what cash-flow, NPV, IRR, payback, break-even, liquidity and stress
results follow mathematically?

It never invents prices, demand, costs, taxes, inflation, financing or market
share from prose.  It never promotes a positive model output into proof of
profitability or real-world viability.  Future demand, manufacturing reality,
technology readiness, human factors and market evidence remain separate gates.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


_MAX_SCENARIOS = 1_000
_MAX_PERIODS = 600
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_CURRENCY = re.compile(r"^[A-Z]{3,8}$")
_ALLOWED_BASIS = {"MEASURED", "CONTRACTED", "ESTIMATED", "ASSUMED"}
_REQUIRED_BASIS = {"initial_capex", "revenues", "operating_costs", "discount_rate"}
_OPTIONAL_BASIS = {"other_cash_flows", "starting_cash", "unit_economics"}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _nonnegative(value: object, field: str) -> float:
    number = _finite(value, field)
    if number < 0:
        raise ValueError(f"{field} must be non-negative")
    return number


def _bounded_series(
    values: object,
    field: str,
    *,
    nonnegative: bool,
    required_length: Optional[int] = None,
) -> Tuple[float, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise ValueError(f"{field} must be a bounded sequence")
    if not 1 <= len(values) <= _MAX_PERIODS:
        raise ValueError(f"{field} length is outside 1..{_MAX_PERIODS}")
    if required_length is not None and len(values) != required_length:
        raise ValueError(f"{field} must match the scenario horizon")
    result = tuple(_finite(value, f"{field}[{index}]") for index, value in enumerate(values))
    if nonnegative and any(value < 0 for value in result):
        raise ValueError(f"{field} values must be non-negative")
    return result


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_ID.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _basis_map(value: object) -> Tuple[Tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        raise ValueError("input_basis must be a mapping")
    normalized: Dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
        basis = str(raw_value or "").strip().upper()
        if key not in _REQUIRED_BASIS | _OPTIONAL_BASIS:
            raise ValueError(f"input_basis contains unsupported field: {key}")
        if basis not in _ALLOWED_BASIS:
            raise ValueError(f"input_basis[{key}] is invalid")
        normalized[key] = basis
    missing = sorted(_REQUIRED_BASIS - set(normalized))
    if missing:
        raise ValueError("input_basis is missing: " + ", ".join(missing))
    return tuple(sorted(normalized.items()))


@dataclass(frozen=True)
class EconomicScenario:
    scenario_id: str
    probability: float
    currency: str
    discount_rate: float
    initial_capex: float
    revenues: Tuple[float, ...]
    operating_costs: Tuple[float, ...]
    provenance_ref: str
    input_basis: Mapping[str, str]
    other_cash_flows: Tuple[float, ...] = ()
    starting_cash: Optional[float] = None
    unit_price: Optional[float] = None
    unit_variable_cost: Optional[float] = None
    fixed_cost_per_period: Optional[float] = None

    def normalized(self) -> "EconomicScenario":
        scenario_id = _safe_id(self.scenario_id, "scenario_id")
        probability = _finite(self.probability, "probability")
        if not 0 <= probability <= 1:
            raise ValueError("probability must be in [0,1]")
        currency = str(self.currency or "").strip().upper()
        if not _CURRENCY.fullmatch(currency):
            raise ValueError("currency must be an explicit uppercase currency/unit code")
        discount_rate = _finite(self.discount_rate, "discount_rate")
        if not -0.95 < discount_rate <= 5.0:
            raise ValueError("discount_rate must be in (-0.95, 5.0]")
        capex = _nonnegative(self.initial_capex, "initial_capex")
        revenues = _bounded_series(self.revenues, "revenues", nonnegative=True)
        costs = _bounded_series(
            self.operating_costs,
            "operating_costs",
            nonnegative=True,
            required_length=len(revenues),
        )
        if self.other_cash_flows:
            other = _bounded_series(
                self.other_cash_flows,
                "other_cash_flows",
                nonnegative=False,
                required_length=len(revenues),
            )
        else:
            other = tuple(0.0 for _ in revenues)
        provenance = str(self.provenance_ref or "").strip()
        if len(provenance) < 3 or len(provenance) > 20_000:
            raise ValueError("provenance_ref is missing or too long")
        basis_pairs = _basis_map(self.input_basis)
        basis = dict(basis_pairs)
        if self.other_cash_flows and "other_cash_flows" not in basis:
            raise ValueError("other_cash_flows requires an input_basis label")

        starting_cash = None
        if self.starting_cash is not None:
            starting_cash = _nonnegative(self.starting_cash, "starting_cash")
            if "starting_cash" not in basis:
                raise ValueError("starting_cash requires an input_basis label")

        unit_values = (self.unit_price, self.unit_variable_cost, self.fixed_cost_per_period)
        any_unit = any(value is not None for value in unit_values)
        all_unit = all(value is not None for value in unit_values)
        if any_unit and not all_unit:
            raise ValueError(
                "unit_price, unit_variable_cost and fixed_cost_per_period must be supplied together"
            )
        unit_price = unit_variable_cost = fixed_cost = None
        if all_unit:
            unit_price = _nonnegative(self.unit_price, "unit_price")
            unit_variable_cost = _nonnegative(self.unit_variable_cost, "unit_variable_cost")
            fixed_cost = _nonnegative(self.fixed_cost_per_period, "fixed_cost_per_period")
            if "unit_economics" not in basis:
                raise ValueError("unit economics require an input_basis label")

        return EconomicScenario(
            scenario_id=scenario_id,
            probability=probability,
            currency=currency,
            discount_rate=discount_rate,
            initial_capex=capex,
            revenues=revenues,
            operating_costs=costs,
            provenance_ref=provenance,
            input_basis=basis_pairs,
            other_cash_flows=other,
            starting_cash=starting_cash,
            unit_price=unit_price,
            unit_variable_cost=unit_variable_cost,
            fixed_cost_per_period=fixed_cost,
        )


@dataclass(frozen=True)
class SensitivityResult:
    shock: str
    expected_npv: float
    delta_from_base: float


@dataclass(frozen=True)
class EconomicScenarioAudit:
    scenario_id: str
    probability: float
    currency: str
    horizon_periods: int
    net_cash_flows: Tuple[float, ...]
    npv: float
    irr: Optional[float]
    irr_status: str
    payback_period: Optional[float]
    discounted_payback_period: Optional[float]
    contribution_margin_per_unit: Optional[float]
    break_even_units_per_period: Optional[float]
    break_even_status: str
    minimum_cash_balance: Optional[float]
    liquidity_breach: Optional[bool]
    uncertain_input_fields: Tuple[str, ...]
    assumptions_sha256: str


@dataclass(frozen=True)
class EconomicRealityReport:
    currency: str
    scenario_count: int
    expected_npv: float
    worst_case_npv: float
    best_case_npv: float
    probability_of_positive_npv: float
    scenario_audits: Tuple[EconomicScenarioAudit, ...]
    sensitivities: Tuple[SensitivityResult, ...]
    economic_signal: str
    economically_promising_under_assumptions: bool
    high_uncertainty_inputs_present: bool
    assumptions_sha256: str
    report_sha256: str
    model_version: str = "economic-reality-v1"
    deterministic_execution: bool = True
    taxes_or_inflation_inferred: bool = False
    currency_conversion_performed: bool = False
    market_demand_proven: bool = False
    profitability_proven: bool = False
    real_world_viability_proven: bool = False
    truth_proven: bool = False


def _npv(initial_capex: float, cash_flows: Sequence[float], discount_rate: float) -> float:
    value = -initial_capex
    for period, cash_flow in enumerate(cash_flows, start=1):
        value += cash_flow / ((1.0 + discount_rate) ** period)
    return value


def _sign_changes(values: Sequence[float]) -> int:
    nonzero = [value for value in values if abs(value) > 1e-12]
    return sum(1 for left, right in zip(nonzero, nonzero[1:]) if left * right < 0)


def _irr(initial_capex: float, cash_flows: Sequence[float]) -> Tuple[Optional[float], str]:
    sequence = (-initial_capex, *cash_flows)
    changes = _sign_changes(sequence)
    if changes != 1:
        return None, "undefined_or_non_unique_sign_pattern"

    def value(rate: float) -> float:
        total = 0.0
        for period, cash_flow in enumerate(sequence):
            total += cash_flow / ((1.0 + rate) ** period)
        return total

    low, high = -0.949999, 1.0
    f_low, f_high = value(low), value(high)
    while f_low * f_high > 0 and high < 100.0:
        high *= 2.0
        f_high = value(high)
    if f_low * f_high > 0:
        return None, "root_outside_bounded_search"
    for _ in range(160):
        mid = (low + high) / 2.0
        f_mid = value(mid)
        if abs(f_mid) <= 1e-10:
            return mid, "unique_bounded_root"
        if f_low * f_mid <= 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2.0, "unique_bounded_root"


def _payback(initial_capex: float, cash_flows: Sequence[float], rate: float = 0.0) -> Optional[float]:
    balance = -initial_capex
    if balance >= 0:
        return 0.0
    for period, raw in enumerate(cash_flows, start=1):
        cash_flow = raw / ((1.0 + rate) ** period) if rate else raw
        previous = balance
        balance += cash_flow
        if balance >= 0:
            if cash_flow <= 0:
                return float(period)
            fraction = max(0.0, min(1.0, -previous / cash_flow))
            return (period - 1) + fraction
    return None


def _audit_scenario(row: EconomicScenario) -> EconomicScenarioAudit:
    cash_flows = tuple(
        revenue - cost + other
        for revenue, cost, other in zip(row.revenues, row.operating_costs, row.other_cash_flows)
    )
    npv = _npv(row.initial_capex, cash_flows, row.discount_rate)
    irr, irr_status = _irr(row.initial_capex, cash_flows)
    payback = _payback(row.initial_capex, cash_flows)
    discounted_payback = _payback(row.initial_capex, cash_flows, row.discount_rate)

    contribution = break_even = None
    break_even_status = "unit_economics_not_supplied"
    if row.unit_price is not None:
        contribution = row.unit_price - row.unit_variable_cost
        if contribution <= 0:
            break_even_status = "non_positive_contribution_margin"
        else:
            break_even = row.fixed_cost_per_period / contribution
            break_even_status = "computed_from_supplied_unit_economics"

    minimum_cash = None
    liquidity_breach = None
    if row.starting_cash is not None:
        cash = row.starting_cash - row.initial_capex
        minimum_cash = cash
        for cash_flow in cash_flows:
            cash += cash_flow
            minimum_cash = min(minimum_cash, cash)
        liquidity_breach = minimum_cash < 0

    basis = dict(row.input_basis)
    uncertain = tuple(sorted(key for key, value in basis.items() if value in {"ESTIMATED", "ASSUMED"}))
    assumptions = {
        "scenario_id": row.scenario_id,
        "probability": row.probability,
        "currency": row.currency,
        "discount_rate": row.discount_rate,
        "initial_capex": row.initial_capex,
        "revenues": row.revenues,
        "operating_costs": row.operating_costs,
        "other_cash_flows": row.other_cash_flows,
        "starting_cash": row.starting_cash,
        "unit_price": row.unit_price,
        "unit_variable_cost": row.unit_variable_cost,
        "fixed_cost_per_period": row.fixed_cost_per_period,
        "provenance_ref": row.provenance_ref,
        "input_basis": row.input_basis,
    }
    return EconomicScenarioAudit(
        scenario_id=row.scenario_id,
        probability=row.probability,
        currency=row.currency,
        horizon_periods=len(row.revenues),
        net_cash_flows=cash_flows,
        npv=npv,
        irr=irr,
        irr_status=irr_status,
        payback_period=payback,
        discounted_payback_period=discounted_payback,
        contribution_margin_per_unit=contribution,
        break_even_units_per_period=break_even,
        break_even_status=break_even_status,
        minimum_cash_balance=minimum_cash,
        liquidity_breach=liquidity_breach,
        uncertain_input_fields=uncertain,
        assumptions_sha256=_sha(assumptions),
    )


def _expected_npv(rows: Sequence[EconomicScenario], *, revenue_factor: float = 1.0,
                  cost_factor: float = 1.0, capex_factor: float = 1.0,
                  discount_shift: float = 0.0) -> float:
    total = 0.0
    for row in rows:
        rate = min(5.0, max(-0.949, row.discount_rate + discount_shift))
        flows = tuple(
            revenue * revenue_factor - cost * cost_factor + other
            for revenue, cost, other in zip(row.revenues, row.operating_costs, row.other_cash_flows)
        )
        total += row.probability * _npv(row.initial_capex * capex_factor, flows, rate)
    return total


def _sensitivity(rows: Sequence[EconomicScenario], base: float) -> Tuple[SensitivityResult, ...]:
    shocks = (
        ("revenue_-10pct", dict(revenue_factor=0.90)),
        ("revenue_+10pct", dict(revenue_factor=1.10)),
        ("opex_+10pct", dict(cost_factor=1.10)),
        ("opex_-10pct", dict(cost_factor=0.90)),
        ("capex_+10pct", dict(capex_factor=1.10)),
        ("capex_-10pct", dict(capex_factor=0.90)),
        ("discount_rate_+2pp", dict(discount_shift=0.02)),
        ("discount_rate_-2pp", dict(discount_shift=-0.02)),
    )
    results = []
    for name, kwargs in shocks:
        value = _expected_npv(rows, **kwargs)
        results.append(SensitivityResult(name, value, value - base))
    return tuple(sorted(results, key=lambda item: (-abs(item.delta_from_base), item.shock)))


def assess_economic_reality(scenarios: Sequence[EconomicScenario]) -> EconomicRealityReport:
    """Evaluate explicit scenarios without inventing missing economics."""
    if isinstance(scenarios, (str, bytes, bytearray)) or not isinstance(scenarios, Sequence):
        raise ValueError("scenarios must be a bounded sequence")
    if not 1 <= len(scenarios) <= _MAX_SCENARIOS:
        raise ValueError(f"scenario count must be in 1..{_MAX_SCENARIOS}")
    rows = tuple(item.normalized() for item in scenarios)
    ids = [row.scenario_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("scenario_id values must be unique")
    currencies = {row.currency for row in rows}
    if len(currencies) != 1:
        raise ValueError("all scenarios must use the same currency; conversion is never inferred")
    horizons = {len(row.revenues) for row in rows}
    if len(horizons) != 1:
        raise ValueError("all scenarios must use the same period horizon")
    probability_total = math.fsum(row.probability for row in rows)
    if not math.isclose(probability_total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("scenario probabilities must sum to exactly 1 within 1e-9")

    audits = tuple(_audit_scenario(row) for row in rows)
    expected = math.fsum(row.probability * audit.npv for row, audit in zip(rows, audits))
    worst = min(audit.npv for audit in audits)
    best = max(audit.npv for audit in audits)
    probability_positive = math.fsum(
        row.probability for row, audit in zip(rows, audits) if audit.npv > 0
    )
    sensitivity = _sensitivity(rows, expected)
    high_uncertainty = any(audit.uncertain_input_fields for audit in audits)
    promising = expected > 0
    if expected <= 0:
        signal = "NOT_PROMISING_UNDER_STATED_ASSUMPTIONS"
    elif worst < 0:
        signal = "MIXED_SCENARIO_ECONOMICS"
    else:
        signal = "POSITIVE_ACROSS_SUPPLIED_SCENARIOS"

    assumptions_payload = [
        {
            "scenario_id": row.scenario_id,
            "probability": row.probability,
            "currency": row.currency,
            "discount_rate": row.discount_rate,
            "initial_capex": row.initial_capex,
            "revenues": row.revenues,
            "operating_costs": row.operating_costs,
            "other_cash_flows": row.other_cash_flows,
            "starting_cash": row.starting_cash,
            "unit_price": row.unit_price,
            "unit_variable_cost": row.unit_variable_cost,
            "fixed_cost_per_period": row.fixed_cost_per_period,
            "provenance_ref": row.provenance_ref,
            "input_basis": row.input_basis,
        }
        for row in rows
    ]
    assumptions_hash = _sha(assumptions_payload)
    report_payload = {
        "currency": next(iter(currencies)),
        "expected_npv": expected,
        "worst_case_npv": worst,
        "best_case_npv": best,
        "probability_of_positive_npv": probability_positive,
        "scenario_audits": [asdict(audit) for audit in audits],
        "sensitivities": [asdict(item) for item in sensitivity],
        "economic_signal": signal,
        "economically_promising_under_assumptions": promising,
        "high_uncertainty_inputs_present": high_uncertainty,
        "assumptions_sha256": assumptions_hash,
        "model_version": "economic-reality-v1",
    }
    return EconomicRealityReport(
        currency=next(iter(currencies)),
        scenario_count=len(rows),
        expected_npv=expected,
        worst_case_npv=worst,
        best_case_npv=best,
        probability_of_positive_npv=probability_positive,
        scenario_audits=audits,
        sensitivities=sensitivity,
        economic_signal=signal,
        economically_promising_under_assumptions=promising,
        high_uncertainty_inputs_present=high_uncertainty,
        assumptions_sha256=assumptions_hash,
        report_sha256=_sha(report_payload),
    )
