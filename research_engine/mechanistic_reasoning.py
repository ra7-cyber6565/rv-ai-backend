"""Explicit causal-mechanism contracts and bounded mechanistic simulation (#101/#102).

The module is deliberately narrower than a generic code simulator.  A mechanism
must declare variables, structural rate equations, observables, falsifiers and
provenance references before it can run.  The simulator then computes only the
consequences of that declared model under baseline and do-style interventions.

Important epistemic boundary: a successful simulation proves neither that the
mechanism exists in nature nor that the structural equations are empirically
correct.  Calibration and external experiments are separate evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, replace
from typing import Any, Dict, Mapping, Sequence, Tuple


_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,119}$")
_ROLES = {"STATE", "EXOGENOUS"}
_TRANSFORMS = {"identity", "tanh", "sigmoid", "relu"}
_MAX_VARIABLES = 128
_MAX_EQUATIONS = 128
_MAX_TERMS_PER_EQUATION = 64
_MAX_TOTAL_TERMS = 512
_MAX_STEPS = 5_000
_MAX_TEXT = 4_000
_MAX_REFS = 64


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("mechanistic payload must be finite JSON-compatible data") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _identifier(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _text(value: object, field: str, *, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field} is required")
    if len(text) > _MAX_TEXT:
        raise ValueError(f"{field} exceeds bounded length")
    return text


def _sequence(value: object, field: str, maximum: int) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be a bounded sequence")
    if len(value) > maximum:
        raise ValueError(f"{field} exceeds bounded size")
    return value


@dataclass(frozen=True)
class MechanismVariable:
    variable_id: str
    initial_value: float
    lower_bound: float
    upper_bound: float
    unit: str
    role: str = "STATE"
    observable_ref: str = ""


@dataclass(frozen=True)
class MechanismTerm:
    variable_id: str
    coefficient: float
    transform: str = "identity"


@dataclass(frozen=True)
class MechanismEquation:
    target: str
    terms: Tuple[MechanismTerm, ...]
    bias: float = 0.0
    decay: float = 0.0
    mechanism: str = ""
    observable: str = ""
    falsifier: str = ""
    evidence_refs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class MechanismModel:
    model_id: str
    variables: Tuple[MechanismVariable, ...]
    equations: Tuple[MechanismEquation, ...]
    dt: float
    steps: int


@dataclass(frozen=True)
class MechanismAudit:
    model_id: str
    complete: bool
    state_variables: Tuple[str, ...]
    exogenous_variables: Tuple[str, ...]
    missing_equations: Tuple[str, ...]
    incomplete_equations: Tuple[str, ...]
    edge_count: int
    evidence_reference_count: int
    audit_hash: str
    causal_mechanism_proven: bool = False
    empirical_validation_proven: bool = False
    truth_proven: bool = False


@dataclass(frozen=True)
class MechanisticSimulationReport:
    model_id: str
    model_hash: str
    status: str
    dt: float
    steps_completed: int
    intervention: Tuple[Tuple[str, float], ...]
    trace: Tuple[Tuple[Tuple[str, float], ...], ...]
    final_state: Tuple[Tuple[str, float], ...]
    report_hash: str
    model_consequence_only: bool = True
    empirically_calibrated: bool = False
    causal_mechanism_proven: bool = False
    real_world_effect_proven: bool = False
    truth_proven: bool = False


@dataclass(frozen=True)
class MechanisticComparison:
    model_id: str
    baseline_report_hash: str
    intervention_report_hash: str
    final_delta: Tuple[Tuple[str, float], ...]
    comparison_hash: str
    counterfactual_is_model_prediction: bool = True
    intervention_observed_in_reality: bool = False
    causal_effect_proven: bool = False
    truth_proven: bool = False


@dataclass(frozen=True)
class CalibrationCheck:
    model_id: str
    observed_variables: Tuple[str, ...]
    normalized_rmse: float
    calibration_hash: str
    observations_supplied: bool = True
    causal_mechanism_proven: bool = False
    truth_proven: bool = False


def _normalize_variable(item: MechanismVariable) -> MechanismVariable:
    variable_id = _identifier(item.variable_id, "variable_id")
    initial = _finite(item.initial_value, f"{variable_id}.initial_value")
    lower = _finite(item.lower_bound, f"{variable_id}.lower_bound")
    upper = _finite(item.upper_bound, f"{variable_id}.upper_bound")
    if not lower < upper:
        raise ValueError(f"{variable_id} bounds must satisfy lower < upper")
    if not lower <= initial <= upper:
        raise ValueError(f"{variable_id} initial_value is outside declared bounds")
    role = str(item.role or "").strip().upper()
    if role not in _ROLES:
        raise ValueError("variable role must be STATE or EXOGENOUS")
    unit = _text(item.unit, f"{variable_id}.unit", required=True)
    observable_ref = _text(item.observable_ref, f"{variable_id}.observable_ref")
    return MechanismVariable(
        variable_id=variable_id,
        initial_value=initial,
        lower_bound=lower,
        upper_bound=upper,
        unit=unit,
        role=role,
        observable_ref=observable_ref,
    )


def _normalize_term(item: MechanismTerm, known: set[str], target: str) -> MechanismTerm:
    variable_id = _identifier(item.variable_id, f"{target}.term.variable_id")
    if variable_id not in known:
        raise ValueError(f"{target} equation references unknown variable {variable_id}")
    transform = str(item.transform or "identity").strip().lower()
    if transform not in _TRANSFORMS:
        raise ValueError(f"unsupported transform: {transform}")
    return MechanismTerm(
        variable_id=variable_id,
        coefficient=_finite(item.coefficient, f"{target}.{variable_id}.coefficient"),
        transform=transform,
    )


def normalize_model(model: MechanismModel) -> MechanismModel:
    model_id = _identifier(model.model_id, "model_id")
    if not 1 <= len(model.variables) <= _MAX_VARIABLES:
        raise ValueError("variables must contain a bounded non-empty set")
    if len(model.equations) > _MAX_EQUATIONS:
        raise ValueError("equations exceed bounded size")
    variables = tuple(_normalize_variable(item) for item in model.variables)
    ids = [item.variable_id for item in variables]
    if len(set(ids)) != len(ids):
        raise ValueError("variable IDs must be unique")
    known = set(ids)

    equations = []
    targets = set()
    total_terms = 0
    for raw in model.equations:
        target = _identifier(raw.target, "equation.target")
        if target not in known:
            raise ValueError(f"equation target is unknown: {target}")
        if target in targets:
            raise ValueError(f"duplicate structural equation for {target}")
        targets.add(target)
        if len(raw.terms) > _MAX_TERMS_PER_EQUATION:
            raise ValueError("equation terms exceed bounded size")
        terms = tuple(_normalize_term(item, known, target) for item in raw.terms)
        term_ids = [item.variable_id for item in terms]
        if len(set(term_ids)) != len(term_ids):
            raise ValueError(f"duplicate input variable in equation for {target}")
        total_terms += len(terms)
        if total_terms > _MAX_TOTAL_TERMS:
            raise ValueError("model terms exceed bounded size")
        refs = tuple(_text(ref, f"{target}.evidence_ref", required=True)
                     for ref in raw.evidence_refs)
        if len(refs) > _MAX_REFS or len(set(refs)) != len(refs):
            raise ValueError("evidence_refs must be unique and bounded")
        equations.append(MechanismEquation(
            target=target,
            terms=terms,
            bias=_finite(raw.bias, f"{target}.bias"),
            decay=_finite(raw.decay, f"{target}.decay"),
            mechanism=_text(raw.mechanism, f"{target}.mechanism"),
            observable=_text(raw.observable, f"{target}.observable"),
            falsifier=_text(raw.falsifier, f"{target}.falsifier"),
            evidence_refs=refs,
        ))

    dt = _finite(model.dt, "dt")
    if not 0.0 < dt <= 1_000.0:
        raise ValueError("dt must be > 0 and bounded")
    if isinstance(model.steps, bool) or not isinstance(model.steps, int):
        raise ValueError("steps must be an integer")
    if not 1 <= model.steps <= _MAX_STEPS:
        raise ValueError(f"steps must be 1..{_MAX_STEPS}")
    return MechanismModel(
        model_id=model_id,
        variables=variables,
        equations=tuple(equations),
        dt=dt,
        steps=model.steps,
    )


def audit_mechanism(model: MechanismModel) -> MechanismAudit:
    normalized = normalize_model(model)
    state_ids = tuple(sorted(item.variable_id for item in normalized.variables if item.role == "STATE"))
    exogenous = tuple(sorted(item.variable_id for item in normalized.variables if item.role == "EXOGENOUS"))
    targets = {item.target for item in normalized.equations}
    missing = tuple(sorted(set(state_ids) - targets))
    incomplete = []
    refs = set()
    edge_count = 0
    for equation in normalized.equations:
        edge_count += len(equation.terms)
        refs.update(equation.evidence_refs)
        if (
            not equation.terms
            or not equation.mechanism
            or not equation.observable
            or not equation.falsifier
            or not equation.evidence_refs
        ):
            incomplete.append(equation.target)
    observable_missing = any(
        item.role == "STATE" and not item.observable_ref for item in normalized.variables
    )
    complete = bool(state_ids) and not missing and not incomplete and not observable_missing
    payload = {
        "model_id": normalized.model_id,
        "state_variables": state_ids,
        "exogenous_variables": exogenous,
        "missing_equations": missing,
        "incomplete_equations": sorted(incomplete),
        "observable_missing": observable_missing,
        "edge_count": edge_count,
        "evidence_refs": sorted(refs),
        "complete": complete,
    }
    return MechanismAudit(
        model_id=normalized.model_id,
        complete=complete,
        state_variables=state_ids,
        exogenous_variables=exogenous,
        missing_equations=missing,
        incomplete_equations=tuple(sorted(incomplete)),
        edge_count=edge_count,
        evidence_reference_count=len(refs),
        audit_hash=_hash(payload),
    )


def _transform(name: str, value: float) -> float:
    if name == "identity":
        return value
    if name == "tanh":
        return math.tanh(value)
    if name == "relu":
        return max(0.0, value)
    if name == "sigmoid":
        if value >= 0:
            z = math.exp(-value)
            return 1.0 / (1.0 + z)
        z = math.exp(value)
        return z / (1.0 + z)
    raise ValueError("unknown transform")


def _state_tuple(state: Mapping[str, float]) -> Tuple[Tuple[str, float], ...]:
    return tuple((key, float(state[key])) for key in sorted(state))


def _normalized_intervention(
    model: MechanismModel,
    intervention: Mapping[str, float] | None,
) -> Dict[str, float]:
    if intervention is None:
        return {}
    if not isinstance(intervention, Mapping):
        raise ValueError("intervention must be a mapping")
    variables = {item.variable_id: item for item in model.variables}
    output: Dict[str, float] = {}
    for raw_key, raw_value in intervention.items():
        key = _identifier(raw_key, "intervention variable")
        if key not in variables:
            raise ValueError(f"intervention references unknown variable {key}")
        value = _finite(raw_value, f"intervention.{key}")
        spec = variables[key]
        if not spec.lower_bound <= value <= spec.upper_bound:
            raise ValueError(f"intervention for {key} is outside declared bounds")
        output[key] = value
    return output


def simulate_mechanism(
    model: MechanismModel,
    *,
    intervention: Mapping[str, float] | None = None,
) -> MechanisticSimulationReport:
    normalized = normalize_model(model)
    audit = audit_mechanism(normalized)
    if not audit.complete:
        raise ValueError("mechanism contract is incomplete; simulation is blocked")
    variables = {item.variable_id: item for item in normalized.variables}
    equations = {item.target: item for item in normalized.equations}
    fixed = _normalized_intervention(normalized, intervention)
    state = {item.variable_id: item.initial_value for item in normalized.variables}
    for key, value in fixed.items():
        state[key] = value
    trace = [_state_tuple(state)]

    for _step in range(1, normalized.steps + 1):
        current = dict(state)
        for key, value in fixed.items():
            current[key] = value
        next_state = dict(current)
        for target, equation in equations.items():
            if target in fixed:
                next_state[target] = fixed[target]
                continue
            rate = equation.bias - equation.decay * current[target]
            for term in equation.terms:
                rate += term.coefficient * _transform(term.transform, current[term.variable_id])
            proposed = current[target] + normalized.dt * rate
            if not math.isfinite(proposed):
                raise ValueError(f"simulation became non-finite at {target}")
            spec = variables[target]
            if not spec.lower_bound <= proposed <= spec.upper_bound:
                raise ValueError(f"simulation boundary violation at {target}")
            next_state[target] = proposed
        for key, value in fixed.items():
            next_state[key] = value
        state = next_state
        trace.append(_state_tuple(state))

    model_payload = asdict(normalized)
    model_hash = _hash(model_payload)
    trace_tuple = tuple(trace)
    final_state = trace_tuple[-1]
    intervention_tuple = tuple(sorted((key, value) for key, value in fixed.items()))
    payload = {
        "model_hash": model_hash,
        "dt": normalized.dt,
        "steps": normalized.steps,
        "intervention": intervention_tuple,
        "trace": trace_tuple,
        "status": "SIMULATED_MODEL_CONSEQUENCE",
    }
    return MechanisticSimulationReport(
        model_id=normalized.model_id,
        model_hash=model_hash,
        status="SIMULATED_MODEL_CONSEQUENCE",
        dt=normalized.dt,
        steps_completed=normalized.steps,
        intervention=intervention_tuple,
        trace=trace_tuple,
        final_state=final_state,
        report_hash=_hash(payload),
    )


def compare_intervention(
    model: MechanismModel,
    intervention: Mapping[str, float],
) -> MechanisticComparison:
    baseline = simulate_mechanism(model)
    treated = simulate_mechanism(model, intervention=intervention)
    base = dict(baseline.final_state)
    alt = dict(treated.final_state)
    delta = tuple((key, alt[key] - base[key]) for key in sorted(base))
    payload = {
        "model_id": baseline.model_id,
        "baseline": baseline.report_hash,
        "intervention": treated.report_hash,
        "final_delta": delta,
    }
    return MechanisticComparison(
        model_id=baseline.model_id,
        baseline_report_hash=baseline.report_hash,
        intervention_report_hash=treated.report_hash,
        final_delta=delta,
        comparison_hash=_hash(payload),
    )


def check_final_state_calibration(
    model: MechanismModel,
    report: MechanisticSimulationReport,
    observed_final_state: Mapping[str, float],
) -> CalibrationCheck:
    normalized = normalize_model(model)
    if report.model_hash != _hash(asdict(normalized)):
        raise ValueError("simulation report does not belong to this model")
    if not isinstance(observed_final_state, Mapping) or not observed_final_state:
        raise ValueError("observed_final_state must contain measurements")
    specs = {item.variable_id: item for item in normalized.variables}
    predicted = dict(report.final_state)
    squared = []
    observed_ids = []
    for raw_key, raw_value in observed_final_state.items():
        key = _identifier(raw_key, "observed variable")
        if key not in specs:
            raise ValueError(f"observation references unknown variable {key}")
        observed = _finite(raw_value, f"observed.{key}")
        spec = specs[key]
        span = spec.upper_bound - spec.lower_bound
        squared.append(((predicted[key] - observed) / span) ** 2)
        observed_ids.append(key)
    nrmse = math.sqrt(sum(squared) / len(squared))
    payload = {
        "model_hash": report.model_hash,
        "report_hash": report.report_hash,
        "observed": sorted((key, float(observed_final_state[key])) for key in observed_ids),
        "normalized_rmse": nrmse,
    }
    return CalibrationCheck(
        model_id=normalized.model_id,
        observed_variables=tuple(sorted(observed_ids)),
        normalized_rmse=nrmse,
        calibration_hash=_hash(payload),
    )


def coefficient_sensitivity(
    model: MechanismModel,
    *,
    fraction: float = 0.05,
) -> Mapping[str, Any]:
    normalized = normalize_model(model)
    fraction = _finite(fraction, "fraction")
    if not 0.0 < fraction <= 0.5:
        raise ValueError("fraction must be in (0, 0.5]")
    baseline = simulate_mechanism(normalized)
    base_state = dict(baseline.final_state)
    rows = []
    for equation_index, equation in enumerate(normalized.equations):
        for term_index, term in enumerate(equation.terms):
            if term.coefficient == 0.0:
                continue
            variants = []
            for direction in (-1.0, 1.0):
                changed_term = replace(
                    term,
                    coefficient=term.coefficient * (1.0 + direction * fraction),
                )
                changed_terms = list(equation.terms)
                changed_terms[term_index] = changed_term
                changed_equation = replace(equation, terms=tuple(changed_terms))
                changed_equations = list(normalized.equations)
                changed_equations[equation_index] = changed_equation
                changed_model = replace(normalized, equations=tuple(changed_equations))
                simulation = simulate_mechanism(changed_model)
                final = dict(simulation.final_state)
                max_abs_delta = max(abs(final[key] - base_state[key]) for key in base_state)
                variants.append({
                    "direction": "down" if direction < 0 else "up",
                    "simulation_hash": simulation.report_hash,
                    "max_abs_final_delta": max_abs_delta,
                })
            rows.append({
                "target": equation.target,
                "input": term.variable_id,
                "base_coefficient": term.coefficient,
                "fraction": fraction,
                "variants": variants,
            })
    payload = {
        "model_hash": baseline.model_hash,
        "baseline_report_hash": baseline.report_hash,
        "fraction": fraction,
        "rows": rows,
    }
    return {
        **payload,
        "sensitivity_hash": _hash(payload),
        "model_consequence_only": True,
        "causal_mechanism_proven": False,
        "truth_proven": False,
    }


def mechanism_model_from_mapping(value: Mapping[str, Any]) -> MechanismModel:
    if not isinstance(value, Mapping):
        raise ValueError("mechanistic_model must be a mapping")
    if set(value) != {"model_id", "variables", "equations", "dt", "steps"}:
        raise ValueError("mechanistic_model schema is invalid")
    variables_raw = _sequence(value["variables"], "variables", _MAX_VARIABLES)
    equations_raw = _sequence(value["equations"], "equations", _MAX_EQUATIONS)
    variables = []
    for index, row in enumerate(variables_raw):
        if not isinstance(row, Mapping) or set(row) != {
            "id", "initial", "min", "max", "unit", "role", "observable_ref"
        }:
            raise ValueError(f"variable {index} schema is invalid")
        variables.append(MechanismVariable(
            variable_id=row["id"],
            initial_value=row["initial"],
            lower_bound=row["min"],
            upper_bound=row["max"],
            unit=row["unit"],
            role=row["role"],
            observable_ref=row["observable_ref"],
        ))
    equations = []
    for index, row in enumerate(equations_raw):
        if not isinstance(row, Mapping) or set(row) != {
            "target", "terms", "bias", "decay", "mechanism", "observable",
            "falsifier", "evidence_refs"
        }:
            raise ValueError(f"equation {index} schema is invalid")
        terms_raw = _sequence(row["terms"], f"equation {index} terms", _MAX_TERMS_PER_EQUATION)
        terms = []
        for term_index, term in enumerate(terms_raw):
            if not isinstance(term, Mapping) or set(term) != {"variable", "coefficient", "transform"}:
                raise ValueError(f"equation {index} term {term_index} schema is invalid")
            terms.append(MechanismTerm(
                variable_id=term["variable"],
                coefficient=term["coefficient"],
                transform=term["transform"],
            ))
        refs = _sequence(row["evidence_refs"], f"equation {index} evidence_refs", _MAX_REFS)
        equations.append(MechanismEquation(
            target=row["target"],
            terms=tuple(terms),
            bias=row["bias"],
            decay=row["decay"],
            mechanism=row["mechanism"],
            observable=row["observable"],
            falsifier=row["falsifier"],
            evidence_refs=tuple(refs),
        ))
    return normalize_model(MechanismModel(
        model_id=value["model_id"],
        variables=tuple(variables),
        equations=tuple(equations),
        dt=value["dt"],
        steps=value["steps"],
    ))
