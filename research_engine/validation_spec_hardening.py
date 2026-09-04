"""Line-by-line runtime hardening for the AI-2 Validation Director.

This layer is deliberately additive.  The merged AI-2 core remains the source of
its 17-section packet; this module performs a second fail-closed audit at the
application integration boundary and strengthens requirements that are easy to
state but dangerous to over-claim in execution (generalization, one-metric
success, regime failures, second-pass handoffs, and explicit status reasons).

It never creates empirical results.  Missing data remains UNKNOWN / NOT TESTED /
TO BE ESTIMATED and positive verdicts may only be downgraded by this layer.
"""
from __future__ import annotations

from copy import deepcopy
import math
import random
from statistics import mean
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence

from .validation_advanced import evaluate_decision_rule
from .validation_contracts import (
    CONDITIONAL_PASS,
    FAIL,
    INCONCLUSIVE,
    NOT_TESTED,
    PASS,
    RESULT_OBSERVED,
    TEST_PERFORMED,
    TEST_POSSIBLE,
    TEST_PROPOSED,
    TO_BE_ESTIMATED,
    UNKNOWN,
    meaningful,
)

_DECISIVE = {PASS, CONDITIONAL_PASS, FAIL}
_POSITIVE = {PASS, CONDITIONAL_PASS}
_UNTOUCHED_ROLES = {"untouched_test", "out_of_sample", "oos", "external_test"}
_PROVENANCE_KEYS = {
    "test_id", "run_id", "dataset_id", "source", "source_id", "timestamp",
    "artifact", "report", "observed_metrics",
}
_CORE_ROBUSTNESS_DIMENSIONS = (
    "nearby parameter values",
    "different time periods",
    "alternative definitions",
    "reasonable noise",
    "reduced data",
    "changed assumptions",
    "different regimes",
)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _numbers(value: Any) -> List[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    out: List[float] = []
    for item in value:
        number = _number(item)
        if number is None:
            return []
        out.append(number)
    return out


def _provenance_bearing(value: Any) -> bool:
    if not isinstance(value, Mapping) or not value:
        return False
    return any(meaningful(value.get(key)) for key in _PROVENANCE_KEYS)


def _find_mapping(result: Mapping[str, Any], keys: Sequence[str]) -> Optional[Dict[str, Any]]:
    for key in keys:
        value = result.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    coverage = result.get("coverage")
    if isinstance(coverage, Mapping):
        for key in keys:
            value = coverage.get(key)
            if isinstance(value, Mapping):
                return dict(value)
    return None


def _find_hypothesis_receipt(result: Mapping[str, Any], hypothesis_id: str) -> Optional[Dict[str, Any]]:
    candidates: List[Any] = []
    for key in ("validation_receipts", "experiment_results", "test_results"):
        value = result.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            candidates.extend(value)
    coverage = result.get("coverage")
    if isinstance(coverage, Mapping):
        for key in ("validation_receipts", "experiment_results", "test_results"):
            value = coverage.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                candidates.extend(value)
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        item_id = str(item.get("hypothesis_id") or item.get("id") or "")
        if item_id == str(hypothesis_id):
            return dict(item)
    return None


def _sections(packet: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    value = packet.get("sections")
    return value if isinstance(value, MutableMapping) else {}


def _experiments(packet: MutableMapping[str, Any]) -> List[MutableMapping[str, Any]]:
    sections = _sections(packet)
    section = sections.get("6. Exact Experiments / Backtests / Simulations Required")
    if not isinstance(section, Mapping):
        return []
    rows = section.get("domain_hypothesis_experiments")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, MutableMapping)]


def _harden_goal_interpretation(packet: MutableMapping[str, Any]) -> None:
    sections = _sections(packet)
    goal = sections.get("1. Interpretation of User Goal")
    if not isinstance(goal, MutableMapping):
        return
    experiments = _experiments(packet)
    required_evidence = []
    for row in experiments:
        required_evidence.append({
            "hypothesis_id": row.get("hypothesis_id", UNKNOWN),
            "dataset_or_sample": row.get("Dataset/sample", UNKNOWN),
            "primary_metric": row.get("Metric", UNKNOWN),
            "baseline": row.get("Baseline", UNKNOWN),
            "prediction": row.get("Prediction", UNKNOWN),
            "falsification_condition": row.get("Falsification condition", UNKNOWN),
            "result_provenance_required": True,
        })
    goal["eventual_outcome_required"] = (
        "For each material claim: an auditable test result whose scope matches the claim, "
        "with uncertainty, baseline comparison, falsification logic and provenance; broader "
        "usefulness/robustness requires separate robustness, friction and failure evidence."
    )
    goal["quantitative_evidence_required"] = required_evidence or [{
        "status": UNKNOWN,
        "reason": "No structured domain hypothesis reached AI-2, so exact evidence requirements cannot yet be instantiated.",
    }]
    goal["what_can_realistically_be_measured"] = (
        "Explicit observables, datasets/samples, outcomes, costs, timings, errors and supplied proxy measures."
    )
    goal["what_cannot_be_claimed_measured_without_extra_evidence"] = (
        "Latent constructs, causal mechanisms, real-world deployment performance, external generalization "
        "or unavailable physical quantities merely because a proxy/model output exists."
    )


def _variable_unit_ok(variable: Mapping[str, Any]) -> bool:
    unit = variable.get("unit")
    return meaningful(unit) and str(unit).strip().upper() != UNKNOWN


def _construct_validation_model_skeletons(packet: MutableMapping[str, Any]) -> None:
    """Construct only a non-parametric validation skeleton when symbols can be defined safely.

    This is not a fitted model and never upgrades the mathematical-model section.  It exists so
    AI-2 can independently formalize a measurable relationship instead of merely saying "no model"
    while still refusing to invent a functional form, coefficient, threshold or causal assumption.
    """
    sections = _sections(packet)
    math_section = sections.get("3. Mathematical Model")
    if not isinstance(math_section, MutableMapping):
        return
    existing = math_section.get("domain_models_found")
    if isinstance(existing, Sequence) and not isinstance(existing, (str, bytes, bytearray)) and existing:
        math_section.setdefault("ai2_constructed_validation_models", [])
        return

    constructed: List[Dict[str, Any]] = []
    for row in _experiments(packet):
        variables = row.get("Variables")
        if not isinstance(variables, Sequence) or isinstance(variables, (str, bytes, bytearray)):
            continue
        independent = []
        dependent = []
        controls = []
        for variable in variables:
            if not isinstance(variable, Mapping):
                continue
            role = str(variable.get("role") or "").strip().lower()
            if not _variable_unit_ok(variable) or not meaningful(variable.get("name")):
                continue
            if role == "independent":
                independent.append(variable)
            elif role == "dependent":
                dependent.append(variable)
            elif role in {"control", "confounder", "mediator", "state"}:
                controls.append(variable)
        if not independent or not dependent:
            continue

        y = dependent[0]
        x_rows = independent
        c_rows = controls
        symbol_metadata = []
        y_symbol = "Y1"
        symbol_metadata.append({
            "symbol": y_symbol,
            "definition": str(y.get("definition") or y.get("name")),
            "unit": str(y.get("unit")),
            "interpretation": str(y.get("interpretation") or f"dependent outcome: {y.get('name')}"),
            "value": TO_BE_ESTIMATED,
        })
        x_symbols = []
        for index, variable in enumerate(x_rows, 1):
            symbol = f"X{index}"
            x_symbols.append(symbol)
            symbol_metadata.append({
                "symbol": symbol,
                "definition": str(variable.get("definition") or variable.get("name")),
                "unit": str(variable.get("unit")),
                "interpretation": str(variable.get("interpretation") or f"independent variable: {variable.get('name')}"),
                "value": TO_BE_ESTIMATED,
            })
        c_symbols = []
        for index, variable in enumerate(c_rows, 1):
            symbol = f"C{index}"
            c_symbols.append(symbol)
            symbol_metadata.append({
                "symbol": symbol,
                "definition": str(variable.get("definition") or variable.get("name")),
                "unit": str(variable.get("unit")),
                "interpretation": str(variable.get("interpretation") or f"adjustment/state variable: {variable.get('name')}"),
                "value": TO_BE_ESTIMATED,
            })
        args = x_symbols + c_symbols
        symbol_metadata.append({
            "symbol": "f",
            "definition": "Unknown relationship from explicitly defined inputs to the dependent outcome; functional form is not assumed.",
            "unit": f"operator mapping input units to {y.get('unit')}",
            "interpretation": "relationship TO BE ESTIMATED or replaced by a justified domain model",
            "value": TO_BE_ESTIMATED,
        })
        constructed.append({
            "model_id": f"AI2-SKELETON-{row.get('hypothesis_id', len(constructed) + 1)}",
            "model_type": "non-parametric validation relationship skeleton",
            "expression": f"{y_symbol} = f({', '.join(args)})",
            "objective": "Estimate/test the locked prediction using the stated metric and baseline without assuming an unsupported functional form.",
            "constraints": UNKNOWN,
            "assumptions": [UNKNOWN],
            "symbol_metadata": symbol_metadata,
            "estimation_method": TO_BE_ESTIMATED,
            "identifiability": UNKNOWN,
            "data_linked_prediction": row.get("Prediction", UNKNOWN),
            "model_contract_complete": False,
            "status": INCONCLUSIVE,
            "truth_warning": "Formalization only; not fitted, not causal proof, and not an observed result.",
        })
    math_section["ai2_constructed_validation_models"] = constructed
    if constructed:
        math_section["construction_rule"] = (
            "AI-2 may construct a symbol-complete non-parametric validation skeleton from explicit variables, "
            "but leaves form/parameters/constraints/identifiability UNKNOWN or TO BE ESTIMATED until justified."
        )


def _status_reason(row: Mapping[str, Any]) -> str:
    status = str(row.get("hypothesis_status") or INCONCLUSIVE)
    state = str(row.get("test_state") or TEST_PROPOSED)
    if status in _DECISIVE:
        decision = row.get("decision_basis")
        if isinstance(decision, Mapping) and meaningful(decision.get("reason")):
            return str(decision.get("reason"))
        if isinstance(decision, Mapping) and decision.get("rule_source") == "SUPPLIED_IN_RESULT_RECEIPT":
            return "Decisive only for the explicitly supplied provenance-bearing decision rule and the exact tested claim/scope."
        return "Decisive status is limited to the exact observed test; broader theory-family conclusions are not implied."
    missing = row.get("missing_required_fields")
    if isinstance(missing, Sequence) and not isinstance(missing, (str, bytes, bytearray)) and missing:
        return "INCONCLUSIVE because required experiment fields remain missing: " + ", ".join(str(x) for x in missing) + "."
    analysis = row.get("quantitative_result_analysis")
    if isinstance(analysis, Mapping) and meaningful(analysis.get("reason")):
        return str(analysis.get("reason"))
    if state == RESULT_OBSERVED:
        return "RESULT OBSERVED, but no explicit valid decision basis justifies PASS/CONDITIONAL PASS/FAIL."
    if state == TEST_PERFORMED:
        return "A test is reported as performed, but result provenance/output is insufficient for an observed decisive verdict."
    if state == TEST_POSSIBLE:
        return "Experiment contract is sufficiently specified to run, but no provenance-bearing observed result is available."
    return "TEST PROPOSED only; no observed result is available."


def _add_status_reasons(packet: MutableMapping[str, Any]) -> None:
    for row in _experiments(packet):
        row["status_reason"] = _status_reason(row)
    sections = _sections(packet)
    independent = sections.get("5. Independent Testable Hypotheses")
    if isinstance(independent, list):
        for row in independent:
            if isinstance(row, MutableMapping):
                row.setdefault(
                    "status_reason",
                    "INCONCLUSIVE because this independently formulated AI-2 hypothesis has no linked provenance-bearing executed result yet.",
                )


def _harden_multi_metric_decisions(packet: MutableMapping[str, Any], result: Mapping[str, Any]) -> None:
    """Support explicit multi-metric decision bundles without inventing thresholds.

    A single pre-registered primary metric may still decide the narrow claim, but the packet explicitly
    marks that broader usefulness/robustness is not established by that single number.
    """
    for row in _experiments(packet):
        hypothesis_id = str(row.get("hypothesis_id") or "")
        receipt = _find_hypothesis_receipt(result, hypothesis_id)
        if not receipt:
            continue
        analysis = row.get("quantitative_result_analysis")
        metrics = analysis.get("metrics") if isinstance(analysis, Mapping) and isinstance(analysis.get("metrics"), Mapping) else {}
        rules = receipt.get("decision_rules")
        if isinstance(rules, Sequence) and not isinstance(rules, (str, bytes, bytearray)) and rules:
            rule_results = [evaluate_decision_rule(metrics, rule) for rule in rules if isinstance(rule, Mapping)]
            logic = str(receipt.get("decision_logic") or "all").strip().lower()
            if not rule_results or logic not in {"all", "any"}:
                combined = INCONCLUSIVE
            else:
                statuses = [item.get("status", INCONCLUSIVE) for item in rule_results]
                if logic == "all":
                    if any(status == FAIL for status in statuses):
                        combined = FAIL
                    elif any(status == INCONCLUSIVE for status in statuses):
                        combined = INCONCLUSIVE
                    elif any(status == CONDITIONAL_PASS for status in statuses):
                        combined = CONDITIONAL_PASS
                    else:
                        combined = PASS
                else:
                    positive = [status for status in statuses if status in _POSITIVE]
                    if positive:
                        combined = CONDITIONAL_PASS if all(status == CONDITIONAL_PASS for status in positive) else PASS
                    elif all(status == FAIL for status in statuses):
                        combined = FAIL
                    else:
                        combined = INCONCLUSIVE
            if row.get("test_state") == RESULT_OBSERVED:
                row["hypothesis_status"] = combined
                row["decision_basis"] = {
                    "status": combined,
                    "rule_source": "SUPPLIED_IN_RESULT_RECEIPT",
                    "multi_metric": True,
                    "decision_logic": logic,
                    "rule_count": len(rule_results),
                    "rule_results": rule_results,
                    "reason": "Combined only caller-supplied metric/operator/threshold rules; no threshold or weighting was invented.",
                }
                if isinstance(analysis, MutableMapping):
                    analysis["status"] = combined
                    analysis["decision"] = deepcopy(row["decision_basis"])
        else:
            row["decision_scope"] = (
                "A single locked primary-metric rule can decide only the narrow tested claim. "
                "Overall usefulness/robustness is separately gated by uncertainty, replication, robustness, friction and failure analyses."
            )
            row["broader_validation_status"] = INCONCLUSIVE


def _harden_predictive_generalization(packet: MutableMapping[str, Any], result: Mapping[str, Any]) -> None:
    receipt = _find_mapping(result, ("predictive_validation_receipt", "predictive_result_receipt", "model_validation_receipt"))
    if not receipt:
        return
    advanced = packet.get("advanced_receipt_analyses")
    predictive = advanced.get("predictive_validation") if isinstance(advanced, Mapping) else None
    if not isinstance(predictive, MutableMapping) or not predictive.get("observed"):
        return
    metrics = predictive.get("metrics") if isinstance(predictive.get("metrics"), Mapping) else {}
    train_ok = _number(metrics.get("training_metric")) is not None
    validation_ok = _number(metrics.get("validation_metric")) is not None
    untouched_ok = _number(metrics.get("untouched_test_metric")) is not None
    na_reason = receipt.get("train_validation_not_applicable_reason")
    explicit_na = meaningful(na_reason)
    split_contract_complete = untouched_ok and ((train_ok and validation_ok) or explicit_na)
    predictive["split_contract_complete"] = split_contract_complete
    predictive["train_validation_not_applicable_reason"] = na_reason if explicit_na else NOT_TESTED
    predictive["generalization_scope"] = (
        "Positive final predictive status requires an untouched test plus either explicit train+validation metrics "
        "or an explicit reason those stages are not applicable to an already-locked external model."
    )
    if predictive.get("status") in _POSITIVE and not split_contract_complete:
        predictive["pre_split_guard_status"] = predictive.get("status")
        predictive["status"] = INCONCLUSIVE
        decision = predictive.get("decision")
        if isinstance(decision, MutableMapping):
            decision["pre_split_guard_status"] = decision.get("status")
            decision["status"] = INCONCLUSIVE
            decision["reason"] = (
                "Positive predictive generalization blocked: train/validation/untouched split contract is incomplete "
                "and no explicit not-applicable rationale was supplied."
            )


def _harden_robustness_scope(packet: MutableMapping[str, Any], result: Mapping[str, Any]) -> None:
    receipt = _find_mapping(result, ("robustness_result_receipt", "robustness_receipt"))
    if not receipt:
        return
    advanced = packet.get("advanced_receipt_analyses")
    robustness = advanced.get("robustness") if isinstance(advanced, Mapping) else None
    if not isinstance(robustness, MutableMapping):
        return
    raw_dimensions = receipt.get("scenario_dimensions")
    covered = set()
    if isinstance(raw_dimensions, Mapping):
        for value in raw_dimensions.values():
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                covered.update(str(item).strip().lower() for item in value if meaningful(item))
            elif meaningful(value):
                covered.add(str(value).strip().lower())
    required_raw = receipt.get("required_dimensions")
    if isinstance(required_raw, Sequence) and not isinstance(required_raw, (str, bytes, bytearray)) and required_raw:
        required = [str(item).strip().lower() for item in required_raw if meaningful(item)]
        source = "SUPPLIED_IN_RECEIPT"
    else:
        required = list(_CORE_ROBUSTNESS_DIMENSIONS)
        source = "REFERENCE_DIMENSIONS_NOT_ASSUMED_MANDATORY"
    missing = [item for item in required if item not in covered]
    robustness["dimension_coverage_audit"] = {
        "covered_dimensions": sorted(covered),
        "reference_or_required_dimensions": required,
        "missing_dimensions": missing,
        "requirements_source": source,
        "coverage_complete": (not missing) if source == "SUPPLIED_IN_RECEIPT" else NOT_TESTED,
        "rule": "Do not call a few scenarios universal robustness; report exactly which perturbation dimensions were tested.",
    }


def _regime_failure_analysis(receipt: Mapping[str, Any]) -> Any:
    regimes_raw = receipt.get("failure_regimes")
    if not isinstance(regimes_raw, Sequence) or isinstance(regimes_raw, (str, bytes, bytearray)) or not regimes_raw:
        return NOT_TESTED
    regimes = [str(item) for item in regimes_raw]
    flags_raw = receipt.get("failure_flags")
    flags = list(flags_raw) if isinstance(flags_raw, Sequence) and not isinstance(flags_raw, (str, bytes, bytearray)) and all(isinstance(x, bool) for x in flags_raw) else []
    severities = _numbers(receipt.get("failure_severities"))
    labels = sorted(set(regimes))
    rows = []
    for label in labels:
        row: Dict[str, Any] = {"regime": label}
        if flags and len(flags) == len(regimes):
            subset = [flag for flag, regime in zip(flags, regimes) if regime == label]
            row["n_failure_flags"] = len(subset)
            row["failure_frequency"] = (sum(subset) / len(subset)) if subset else NOT_TESTED
        else:
            row["failure_frequency"] = NOT_TESTED
        if severities and len(severities) == len(regimes):
            subset_s = [severity for severity, regime in zip(severities, regimes) if regime == label]
            row["severity_n"] = len(subset_s)
            row["mean_failure_severity"] = mean(subset_s) if subset_s else NOT_TESTED
            row["worst_failure_severity"] = max(subset_s) if subset_s else NOT_TESTED
        else:
            row["mean_failure_severity"] = NOT_TESTED
            row["worst_failure_severity"] = NOT_TESTED
        rows.append(row)
    return {
        "state": RESULT_OBSERVED,
        "regimes": rows,
        "alignment_rule": "Regime labels are used only when their length exactly matches the corresponding flags/severity observations.",
    }


def _stress_scenario_analysis(receipt: Mapping[str, Any]) -> Any:
    raw = receipt.get("stress_scenarios")
    if not isinstance(raw, Mapping) or not raw:
        return NOT_TESTED
    numeric = {str(name): _number(value) for name, value in raw.items()}
    numeric = {name: value for name, value in numeric.items() if value is not None}
    if not numeric:
        return NOT_TESTED
    values = list(numeric.values())
    higher_is_worse = receipt.get("stress_higher_is_worse")
    worst: Any = NOT_TESTED
    if isinstance(higher_is_worse, bool):
        worst = max(numeric, key=numeric.get) if higher_is_worse else min(numeric, key=numeric.get)
    return {
        "scenarios": numeric,
        "minimum": min(values),
        "maximum": max(values),
        "mean": mean(values),
        "worst_scenario": worst,
        "worst_direction_source": "SUPPLIED_IN_RECEIPT" if isinstance(higher_is_worse, bool) else NOT_TESTED,
    }


def _block_failure_monte_carlo(receipt: Mapping[str, Any]) -> Any:
    severities = _numbers(receipt.get("failure_severities"))
    model = str(receipt.get("failure_dependence_model") or "").strip().lower()
    iterations = receipt.get("monte_carlo_iterations")
    seed = receipt.get("random_seed")
    block_length = receipt.get("failure_block_length")
    if model != "block_bootstrap":
        return NOT_TESTED
    if not severities or not isinstance(iterations, int) or iterations <= 0 or not isinstance(seed, int):
        return {"status": NOT_TESTED, "reason": "Block failure Monte Carlo needs severities, positive iterations and integer seed."}
    if not isinstance(block_length, int) or isinstance(block_length, bool) or not (1 <= block_length <= len(severities)):
        return {"status": NOT_TESTED, "reason": "Explicit valid failure_block_length is required for block_bootstrap."}
    rng = random.Random(seed)
    maxima = []
    for _ in range(iterations):
        sample: List[float] = []
        while len(sample) < len(severities):
            start = 0 if block_length == len(severities) else rng.randrange(0, len(severities) - block_length + 1)
            sample.extend(severities[start:start + block_length])
        maxima.append(max(sample[:len(severities)]))
    ordered = sorted(maxima)
    p95 = ordered[min(len(ordered) - 1, int(math.floor(0.95 * (len(ordered) - 1))))]
    return {
        "status": "CALCULATED",
        "method": "block_bootstrap_failure_severity",
        "iterations": iterations,
        "random_seed": seed,
        "block_length": block_length,
        "p95_path_max": p95,
        "worst_path_max": max(ordered),
        "assumption_warning": "Block bootstrap preserves only dependence represented by the supplied block design; structural breaks still require regime/stress tests.",
    }


def _harden_failure_distribution(packet: MutableMapping[str, Any], result: Mapping[str, Any]) -> None:
    receipt = _find_mapping(result, ("failure_result_receipt", "failure_distribution_receipt", "stress_result_receipt"))
    if not receipt:
        return
    advanced = packet.get("advanced_receipt_analyses")
    failure = advanced.get("failure_distribution") if isinstance(advanced, Mapping) else None
    if not isinstance(failure, MutableMapping):
        return
    failure["regime_analysis"] = _regime_failure_analysis(receipt)
    failure["scenario_analysis"] = _stress_scenario_analysis(receipt)
    failure["dependence_aware_monte_carlo"] = _block_failure_monte_carlo(receipt)


def _bias_provenance_audit(packet: MutableMapping[str, Any]) -> None:
    sections = _sections(packet)
    rows = sections.get("7. Bias & Leakage Risks")
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, MutableMapping):
            continue
        evidence = row.get("evidence")
        provenance = row.get("provenance")
        if meaningful(evidence) and str(evidence).strip().upper() != UNKNOWN:
            row["verification_level"] = "PROVENANCE_BEARING" if _provenance_bearing(provenance) else "ASSERTED_EVIDENCE_WITHOUT_PROVENANCE"
        else:
            row["verification_level"] = NOT_TESTED
        row["scope_rule"] = "Invalidate/downgrade only the affected claim/test when scope is known; otherwise use a conservative investigation hold, not a theory-family rejection."


def _harden_trading_generalization(packet: MutableMapping[str, Any], result: Mapping[str, Any]) -> None:
    sections = _sections(packet)
    experiment_section = sections.get("6. Exact Experiments / Backtests / Simulations Required")
    if not isinstance(experiment_section, MutableMapping):
        return
    trading = experiment_section.get("trading_validation_standard")
    if not isinstance(trading, MutableMapping):
        return
    receipt = _find_mapping(result, ("trading_result_receipt", "trade_result_receipt", "backtest_result_receipt"))
    if not receipt:
        return
    dataset_role = str(receipt.get("dataset_role") or "").strip().lower()
    tuning_flag = receipt.get("test_was_used_for_tuning")
    net_of_friction = bool(
        isinstance(trading.get("result_receipt_analysis"), Mapping)
        and trading.get("result_receipt_analysis", {}).get("returns_are_net_of_friction") is True
    )
    untouched = dataset_role in _UNTOUCHED_ROLES
    gate_passed = net_of_friction and untouched and tuning_flag is False
    trading["generalization_gate"] = {
        "net_of_friction": net_of_friction,
        "dataset_role": dataset_role or UNKNOWN,
        "untouched_or_external_role": untouched,
        "test_was_used_for_tuning": tuning_flag if isinstance(tuning_flag, bool) else UNKNOWN,
        "passed": gate_passed,
        "rule": "A positive trading strategy verdict cannot generalize from in-sample/tuned or gross returns; positive status needs friction-net untouched/external data and test_was_used_for_tuning=false.",
    }
    current = trading.get("observed_result_status")
    decision_rule = receipt.get("decision_rule") if isinstance(receipt.get("decision_rule"), Mapping) else {}
    requested = str(decision_rule.get("status_if_pass") or PASS).strip().upper().replace("_", " ")
    if current == PASS and requested == CONDITIONAL_PASS and gate_passed:
        trading["observed_result_status"] = CONDITIONAL_PASS
        decision = trading.get("result_decision")
        if isinstance(decision, MutableMapping):
            decision["status"] = CONDITIONAL_PASS
            decision["status_if_pass_source"] = "SUPPLIED_IN_RESULT_RECEIPT"
    if trading.get("observed_result_status") in _POSITIVE and not gate_passed:
        trading["pre_generalization_guard_status"] = trading.get("observed_result_status")
        trading["observed_result_status"] = INCONCLUSIVE
        decision = trading.get("result_decision")
        if isinstance(decision, MutableMapping):
            decision["pre_generalization_guard_status"] = decision.get("status")
            decision["status"] = INCONCLUSIVE
            decision["reason"] = "Positive trading verdict blocked until friction-net untouched/external, never-tuned test evidence is supplied."
    if trading.get("observed_result_status") == FAIL:
        trading["failure_scope"] = "FAIL rejects only the exact strategy claim on the tested dataset/regime/rules; it does not reject a broader trading framework."

    contract_fields = (
        "exact_instrument", "feed_assumptions", "futures_vs_cfd_relationship", "timeframe",
        "regime", "session", "long_rules", "short_rules", "entry", "stop", "target",
        "position_sizing", "no_trade_rules", "news_filtering", "spread", "commission",
        "slippage", "latency",
    )
    missing = [field for field in contract_fields if str(trading.get(field, UNKNOWN)).strip().upper() in {UNKNOWN, NOT_TESTED}]
    trading["execution_contract_audit"] = {
        "missing_fields": missing,
        "complete": not missing,
        "deployment_rule": "Missing execution/feed/rule fields block deployment-grade conclusions even when a narrow backtest metric is observed.",
    }


def _structured_second_pass_items(result: Mapping[str, Any]) -> List[Dict[str, Any]]:
    aliases = {
        "AI-1": ("ai1_research_packet", "ai1_output"),
        "AI-3": ("ai3_theory_packet", "ai3_hypotheses", "ai3_output"),
        "AI-4": ("ai4_red_team_packet", "ai4_output", "red_team_packet"),
    }
    tasks: List[Dict[str, Any]] = []
    for agent, keys in aliases.items():
        payload = None
        for key in keys:
            candidate = result.get(key)
            if isinstance(candidate, Mapping) and candidate:
                payload = candidate
                break
        if not isinstance(payload, Mapping):
            continue
        for field, label in (
            ("disputed_claims", "disputed claim"),
            ("merged_models", "merged model"),
            ("objections", "red-team objection"),
            ("hypotheses", "structured hypothesis"),
        ):
            value = payload.get(field)
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
                continue
            for index, item in enumerate(value[:8], 1):
                if isinstance(item, Mapping):
                    identity = item.get("id") or item.get("hypothesis_id") or item.get("statement") or item.get("claim") or f"{field}-{index}"
                else:
                    identity = str(item)
                tasks.append({
                    "source_agent": agent,
                    "structured_input_type": label,
                    "input_identity": str(identity)[:240],
                    "task": "Design the smallest safe discriminating test that most separates this structured input from its strongest alternative/objection.",
                    "expected_information_gain": TO_BE_ESTIMATED,
                    "information_gain_rule": "Calculate/rank numerically only if predictive outcome distributions or explicit priors/likelihoods are supplied; otherwise do not invent a score.",
                    "state": TEST_POSSIBLE,
                })
    return tasks


def _harden_second_pass(packet: MutableMapping[str, Any], result: Mapping[str, Any]) -> None:
    sections = _sections(packet)
    tasks = sections.get("15. Highest-Value Second-Pass Validation Tasks")
    if not isinstance(tasks, list):
        return
    specific = _structured_second_pass_items(result)
    if specific:
        merged = specific + [deepcopy(item) for item in tasks if isinstance(item, Mapping)]
        for index, item in enumerate(merged, 1):
            item["priority"] = index
        sections["15. Highest-Value Second-Pass Validation Tasks"] = merged


def _spec_matrix(packet: Mapping[str, Any]) -> List[Dict[str, Any]]:
    sections = packet.get("sections") if isinstance(packet.get("sections"), Mapping) else {}
    has = lambda key: key in sections
    trading_section = sections.get("6. Exact Experiments / Backtests / Simulations Required", {})
    trading_enabled = isinstance(trading_section, Mapping) and "trading_validation_standard" in trading_section
    return [
        {"id": "ROLE", "requirement": "AI-2 Validation Director role + parallel company mode", "implementation_status": "IMPLEMENTED", "evidence": "packet.agent_id / packet.role / packet.mode"},
        {"id": "PRIMARY", "requirement": "Measurable variables, math, predictions, experiments/simulations, quantitative validation, falsification, robustness", "implementation_status": "IMPLEMENTED", "evidence": "sections 2-11 + advanced receipt analyses"},
        {"id": "1", "requirement": "Original deliverable, eventual outcome, quantitative evidence, measurable limits, no task substitution", "implementation_status": "IMPLEMENTED" if has("1. Interpretation of User Goal") else "MISSING", "evidence": "section 1 hardened fields"},
        {"id": "2", "requirement": "Independent/dependent/control/mediator/confounder/state/uncertainty variables; symbol definition/unit/interpretation", "implementation_status": "IMPLEMENTED" if has("2. Quantifiable Components") else "MISSING", "evidence": "section 2 variable role audit + symbol rule"},
        {"id": "3", "requirement": "Useful mathematical models with UNKNOWN/TO BE ESTIMATED and no invented thresholds", "implementation_status": "IMPLEMENTED" if has("3. Mathematical Model") else "MISSING", "evidence": "section 3 domain models + safe AI-2 skeleton fallback"},
        {"id": "4", "requirement": "Baseline first; complexity must earn place", "implementation_status": "IMPLEMENTED" if has("4. Baselines") else "MISSING", "evidence": "section 4 + AI2-H1 baseline edge"},
        {"id": "5", "requirement": "Exact 11-field experiment contract + falsification + replication", "implementation_status": "IMPLEMENTED" if has("6. Exact Experiments / Backtests / Simulations Required") else "MISSING", "evidence": "section 6 domain_hypothesis_experiments"},
        {"id": "6", "requirement": "Train/validation/untouched predictive validation; never tune untouched; rolling/walk-forward/external/cross/temporal/regime", "implementation_status": "IMPLEMENTED", "evidence": "section 6 predictive standard + split/generalization guard"},
        {"id": "7", "requirement": "Effect size, uncertainty/CI, Bayesian, bootstrap, permutation, Monte Carlo, multiplicity, power; no one-metric overclaim", "implementation_status": "IMPLEMENTED", "evidence": "statistical_validation + inference controls + multi-metric bundle hardening"},
        {"id": "8", "requirement": "Robustness over parameters/time/definitions/noise/data/assumptions/regimes; stable region preference", "implementation_status": "IMPLEMENTED" if has("8. Robustness Plan") else "MISSING", "evidence": "section 8 + executed robustness + dimension scope audit"},
        {"id": "9", "requirement": "Ablation and REMOVAL when no material incremental value", "implementation_status": "IMPLEMENTED" if has("9. Ablation Plan") else "MISSING", "evidence": "section 9 + executed ablation receipt"},
        {"id": "10", "requirement": "Full leakage/bias audit and invalidate/downgrade", "implementation_status": "IMPLEMENTED" if has("7. Bias & Leakage Risks") else "MISSING", "evidence": "section 7 + bias decision guard + provenance level"},
        {"id": "11", "requirement": "Real-world friction constraints", "implementation_status": "IMPLEMENTED" if has("10. Real-World Friction") else "MISSING", "evidence": "section 10 friction audit"},
        {"id": "12", "requirement": "Failure frequency/severity/regime/clustering/worst/catastrophe/tails/stress/scenario/Monte Carlo", "implementation_status": "IMPLEMENTED" if has("11. Failure Modes") else "MISSING", "evidence": "section 11 + regime/scenario/dependence-aware receipt analysis"},
        {"id": "13", "requirement": "Trading-specific full standard without fabricated metrics", "implementation_status": "IMPLEMENTED_CONDITIONAL" if not trading_enabled else "IMPLEMENTED_ACTIVE", "evidence": "trading validation standard + OOS/friction/tuning generalization guard"},
        {"id": "14", "requirement": "PASS / CONDITIONAL PASS / INCONCLUSIVE / FAIL with reasons and narrow rejection", "implementation_status": "IMPLEMENTED", "evidence": "truth_policy + status_reason + decision basis"},
        {"id": "15", "requirement": "Exact AI-1 / AI-3 / AI-4 cross-agent alert headers", "implementation_status": "IMPLEMENTED" if has("14. Cross-Agent Alerts") else "MISSING", "evidence": "section 14"},
        {"id": "16", "requirement": "Independent AI-2 hypotheses with mechanism/variables/prediction/test/falsification/baseline", "implementation_status": "IMPLEMENTED" if has("5. Independent Testable Hypotheses") else "MISSING", "evidence": "section 5"},
        {"id": "17", "requirement": "Second round reuses strongest/disputed/merged/red-team inputs and prioritizes information gain", "implementation_status": "IMPLEMENTED" if has("15. Highest-Value Second-Pass Validation Tasks") else "MISSING", "evidence": "section 15 + structured handoff extraction"},
        {"id": "18", "requirement": "Never invent results; TEST PROPOSED/POSSIBLE/PERFORMED/RESULT OBSERVED kept distinct", "implementation_status": "IMPLEMENTED", "evidence": "truth_policy + packet integrity + receipt provenance rules"},
        {"id": "FINAL", "requirement": "Exactly 17 required final AI-2 packet sections", "implementation_status": "IMPLEMENTED" if len(sections) == 17 else "MISSING", "evidence": f"section_count={len(sections)}"},
    ]


def _revalidate_core_packet(packet: MutableMapping[str, Any]) -> None:
    try:
        from .validation_director import validate_ai2_packet
        packet["packet_integrity"] = validate_ai2_packet(packet)
    except Exception:
        packet.setdefault("packet_integrity", {"valid": False, "errors": ["post_hardening_integrity_check_failed"]})


def harden_ai2_runtime_result(question: str, research_result: Mapping[str, Any]) -> Dict[str, Any]:
    """Strengthen an already-attached AI-2 packet without mutating the caller input.

    Any internal hardening failure is sanitized and never crashes the core research result.
    """
    enriched = dict(research_result or {})
    original_packet = enriched.get("ai2_validation")
    if not isinstance(original_packet, Mapping) or not isinstance(original_packet.get("sections"), Mapping):
        return enriched
    packet: Dict[str, Any] = deepcopy(dict(original_packet))
    try:
        _harden_goal_interpretation(packet)
        _construct_validation_model_skeletons(packet)
        _harden_multi_metric_decisions(packet, enriched)
        _harden_predictive_generalization(packet, enriched)
        _harden_robustness_scope(packet, enriched)
        _harden_failure_distribution(packet, enriched)
        _bias_provenance_audit(packet)
        _harden_trading_generalization(packet, enriched)
        _harden_second_pass(packet, enriched)
        _add_status_reasons(packet)
        _revalidate_core_packet(packet)
        matrix = _spec_matrix(packet)
        packet["line_by_line_spec_audit"] = {
            "valid": bool(packet.get("packet_integrity", {}).get("valid")) and all(row["implementation_status"] != "MISSING" for row in matrix),
            "scope": "Implementation/spec compliance audit, NOT probability that a domain hypothesis is true.",
            "matrix": matrix,
            "positive_verdict_rule": "This hardening layer may downgrade or scope a verdict; it never upgrades missing evidence into PASS.",
        }
        enriched["ai2_validation"] = packet
        enriched["ai2_line_by_line_audit"] = {
            "valid": packet["line_by_line_spec_audit"]["valid"],
            "matrix_count": len(matrix),
            "core_packet_valid": bool(packet.get("packet_integrity", {}).get("valid")),
        }
    except Exception:
        enriched["ai2_line_by_line_audit"] = {
            "valid": False,
            "error": "ai2_runtime_spec_hardening_failed",
            "truth_rule": "Failure of the audit layer does not upgrade any research claim and does not crash core research.",
        }
    return enriched
