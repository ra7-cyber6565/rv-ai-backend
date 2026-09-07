"""Preserve proposed mechanisms and complete-test-plan fields without inventing results."""
from __future__ import annotations

PLAN_FIELDS = ("test_type", "setup", "target_system_sample", "inputs_data_source", "prerequisites",
    "controls", "confounders", "baseline", "primary_outcome", "decision_threshold", "falsification",
    "power_sample_assumptions", "expected_results_by_hypothesis", "analysis_method", "uncertainty_method",
    "stopping_rule", "failure_modes", "replication_method", "random_seed_environment")
_UNKNOWN = {"", "UNKNOWN", "TO BE ESTIMATED", "NOT TESTED", "N/A", "NOT_APPLICABLE"}
_ROLES = {"independent", "dependent", "control", "confounder", "mediator", "state", "uncertainty"}


def text(value, limit=1200):
    return value.strip()[:limit] if isinstance(value, str) else "UNKNOWN"


def known(value):
    return isinstance(value, str) and value.strip().upper() not in _UNKNOWN


def complete_proposal(row, source_ids):
    allowed = set(source_ids)
    plan = row.get("test_plan") if isinstance(row.get("test_plan"), dict) else {}
    normalized, missing, truncated = {}, [], []
    for field in PLAN_FIELDS:
        value = plan.get(field)
        # Inapplicability is explicit and requires a reason; no made-up power or threshold.
        if isinstance(value, dict) and value.get("state") == "NOT_APPLICABLE" and known(value.get("reason")):
            normalized[field] = {"state": "NOT_APPLICABLE", "reason": text(value["reason"], 500)}
        else:
            normalized[field] = text(value)
            if not known(normalized[field]):
                missing.append(field)
            if isinstance(value, str) and len(value.strip()) > 1200:
                truncated.append(field)
    variables = []
    raw_variables = plan.get("variables") if isinstance(plan.get("variables"), list) else []
    if len(raw_variables) > 12:
        truncated.append("variables")
    for v in raw_variables[:12]:
        if not isinstance(v, dict):
            continue
        variable = {key: text(v.get(key), 300) for key in ("symbol", "definition", "unit", "role")}
        if all(known(value) for value in variable.values()) and variable["role"] in _ROLES:
            variables.append(variable)
            if any(isinstance(v.get(key), str) and len(v[key].strip()) > 300 for key in variable):
                truncated.append("variable_definition")
    if len(variables) != len(raw_variables[:12]):
        missing.append("invalid_variable_definitions")
    variable_applicability = plan.get("variables_applicability")
    if not variables and not (isinstance(variable_applicability, dict) and
        variable_applicability.get("state") == "NOT_APPLICABLE" and known(variable_applicability.get("reason"))):
        missing.append("variables_with_units_and_roles")
    normalized["variables"] = variables
    if not variables and isinstance(variable_applicability, dict) and variable_applicability.get("state") == "NOT_APPLICABLE" and known(variable_applicability.get("reason")):
        normalized["variables_applicability"] = {"state": "NOT_APPLICABLE", "reason": text(variable_applicability.get("reason"), 500)}
    mechanism = text(row.get("mechanism"))
    assumptions = [text(v, 500) for v in row.get("assumptions", [])[:8] if known(v)] if isinstance(row.get("assumptions"), list) else []
    if not known(mechanism):
        missing.append("mechanism")
    if not assumptions:
        missing.append("assumptions")
    boundaries = text(row.get("applicability_boundaries"))
    if not known(boundaries):
        missing.append("applicability_boundaries")
    for field in ("mechanism", "applicability_boundaries"):
        if isinstance(row.get(field), str) and len(row[field].strip()) > 1200:
            truncated.append(field)
    support = {key: sorted({v for v in row.get(key, []) if isinstance(v, str)} & allowed)
               if isinstance(row.get(key), list) else []
               for key in ("supporting_source_ids", "opposing_source_ids")}
    unknown_ids = sorted({v for key in support for v in (row.get(key) if isinstance(row.get(key), list) else []) if isinstance(v, str)} - allowed)
    return {"mechanism": mechanism, "assumptions": assumptions, **support,
            "applicability_boundaries": boundaries, "unknown_source_ids": unknown_ids[:12],
            "novelty": {"assessment": "NOT_ESTABLISHED", "search_scope_note": text(row.get("novelty_search_scope"))},
            "test_plan": normalized, "plan_completeness": "INCOMPLETE" if missing or truncated else "STRUCTURALLY_COMPLETE",
            "missing_plan_fields": missing, "truncated_plan_fields": truncated, "semantic_plan_validation": "NOT_ASSESSED",
            "execution": "TEST_PROPOSED", "status": "INCONCLUSIVE",
            "preregistration": "NOT_REGISTERED", "actual_results": None}


def prompt_schema():
    return ("Also give each hypothesis mechanism, assumptions (strings), supporting_source_ids, opposing_source_ids, "
        "applicability_boundaries, novelty_search_scope, and test_plan with " + ", ".join(PLAN_FIELDS) +
        ". test_plan.variables is an array of {symbol, definition, unit, role}; roles: "+", ".join(sorted(_ROLES))+
        ". Missing values must stay UNKNOWN/TO BE ESTIMATED. Inapplicable fields may be "
        "{state: NOT_APPLICABLE, reason: precise reason}. Do not invent execution results or registration. ")
