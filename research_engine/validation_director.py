"""AI-2 Quantitative Science, Experiment, Testing & Validation Director.

The layer is additive and fail-closed. Plans never become results; missing values
stay explicit; decisive statuses require provenance plus a supplied decision rule.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Mapping, Optional, Sequence

from .validation_advanced import (
    analyze_ablation_receipt, analyze_failure_receipt, analyze_predictive_receipt,
    analyze_robustness_receipt, apply_bias_guard, collect_second_pass_outputs,
    find_ablation_receipt, find_failure_receipt, find_predictive_receipt,
    find_robustness_receipt, variable_role_audit,
)
from .validation_contracts import (
    AGENT_ID, CONDITIONAL_PASS, EXPERIMENT_FIELDS, FAIL, HYPOTHESIS_STATUSES,
    INCONCLUSIVE, NOT_TESTED, PASS, REQUIRED_SECTIONS, RESULT_OBSERVED,
    SCHEMA_VERSION, TEST_PERFORMED, TEST_POSSIBLE, TEST_PROPOSED, TEST_STATES,
    TO_BE_ESTIMATED, UNKNOWN, existing_experiment_intelligence,
    extract_hypotheses, is_trading, meaningful, second_pass_summary,
    source_count, text,
)
from .validation_experiments import confidence_score, extract_math_models, normalize_experiment
from .validation_inference import inference_controls
from .validation_risk import (
    ablation_plan, bias_audit, cross_agent_alerts, failure_plan, friction_plan,
    meta_hypotheses, robustness_plan, second_pass_tasks,
)
from .validation_statistics import analyze_two_group_receipt, find_result_receipt
from .validation_trading import trading_standard


def _requested_pass_status(receipt: Mapping[str, Any]) -> str:
    rule = receipt.get("decision_rule")
    if not isinstance(rule, Mapping):
        return PASS
    status = str(rule.get("status_if_pass") or PASS).strip().upper().replace("_", " ")
    return status if status in {PASS, CONDITIONAL_PASS} else PASS


def _apply_result_receipts(experiments: Sequence[Dict[str, Any]], result: Mapping[str, Any]) -> None:
    for row in experiments:
        receipt = find_result_receipt(result, str(row.get("hypothesis_id") or ""))
        if not receipt:
            continue
        analysis = analyze_two_group_receipt(receipt)
        if analysis.get("observed") and analysis.get("status") == PASS:
            requested = _requested_pass_status(receipt)
            if requested == CONDITIONAL_PASS:
                analysis = deepcopy(dict(analysis))
                analysis["status"] = CONDITIONAL_PASS
                decision = analysis.get("decision")
                if isinstance(decision, dict) and decision.get("rule_source") == "SUPPLIED_IN_RESULT_RECEIPT":
                    decision["status"] = CONDITIONAL_PASS
                    decision["status_if_pass_source"] = "SUPPLIED_IN_RESULT_RECEIPT"
        controls = inference_controls(receipt, observed_provenance=bool(analysis.get("observed")))
        row["quantitative_result_analysis"] = analysis
        row["inference_controls"] = controls
        stat = row.get("statistical_validation")
        if isinstance(stat, dict):
            stat["power_analysis"] = controls.get("power_analysis", NOT_TESTED)
            stat["bayesian_evidence"] = controls.get("bayesian_evidence", NOT_TESTED)
            stat["multiple_testing_correction"] = controls.get("multiple_testing_correction", NOT_TESTED)
        if not analysis.get("observed"):
            continue
        metrics = analysis.get("metrics") if isinstance(analysis.get("metrics"), Mapping) else {}
        row["test_state"] = RESULT_OBSERVED
        row["hypothesis_status"] = analysis.get("status", INCONCLUSIVE)
        row["result"] = deepcopy(analysis)
        row["result_provenance"] = deepcopy(analysis.get("provenance") or {})
        row["decision_basis"] = deepcopy(analysis.get("decision") or {})
        if isinstance(stat, dict):
            stat["effect_size"] = metrics.get("standardized_effect", NOT_TESTED)
            stat["uncertainty_interval"] = analysis.get("confidence_interval", NOT_TESTED)
            stat["confidence_interval"] = analysis.get("confidence_interval", NOT_TESTED)
            stat["bootstrap"] = analysis.get("bootstrap", NOT_TESTED)
            stat["permutation_test"] = analysis.get("permutation_test", NOT_TESTED)


def _enforce_decisive_bias_guard(
    experiments: Sequence[Dict[str, Any]], bias_guard: Mapping[str, Any]
) -> None:
    if not bias_guard.get("verified_findings"):
        return
    downgraded = False
    for row in experiments:
        status = row.get("hypothesis_status")
        if status not in {PASS, CONDITIONAL_PASS, FAIL}:
            continue
        row.setdefault("pre_bias_guard_status", status)
        row["hypothesis_status"] = INCONCLUSIVE
        row["bias_guard"] = (
            "DOWNGRADED — verified leakage/bias invalidates a decisive verdict "
            "until the affected test is repeated on a clean design/data path."
        )
        downgraded = True
    if isinstance(bias_guard, dict):
        bias_guard["decisive_verdicts_downgraded"] = downgraded
        bias_guard["rule"] = (
            "Verified leakage/bias downgrades any affected decisive PASS, CONDITIONAL PASS, "
            "or FAIL to INCONCLUSIVE until a clean re-test. Narrow raw observations remain recorded."
        )


def _compact_handoffs(handoffs: Mapping[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    for agent, payload in handoffs.items():
        row: Dict[str, Any] = {
            "present": True,
            "full_payload_embedded": False,
            "payload_type": type(payload).__name__,
        }
        if isinstance(payload, Mapping):
            keys = sorted(str(key) for key in payload.keys())
            row["top_level_keys"] = keys[:20]
            row["top_level_key_count"] = len(keys)
            validation = payload.get("validation")
            integrity = payload.get("packet_integrity")
            if isinstance(validation, Mapping) and "valid" in validation:
                row["packet_valid"] = bool(validation.get("valid"))
            elif isinstance(integrity, Mapping) and "valid" in integrity:
                row["packet_valid"] = bool(integrity.get("valid"))
            else:
                row["packet_valid"] = UNKNOWN
        compact[str(agent)] = row
    return compact


def _result_missing(value: Any) -> bool:
    return value is None or value == NOT_TESTED or value == UNKNOWN


def _analysis_state(analysis: Any) -> str:
    if isinstance(analysis, Mapping) and analysis.get("observed"):
        return RESULT_OBSERVED
    return NOT_TESTED


def _blockers(
    experiments: Sequence[Mapping[str, Any]], confidence: Mapping[str, Any], trading: bool,
    models: Sequence[Mapping[str, Any]], advanced: Mapping[str, Any], bias_guard: Mapping[str, Any],
) -> list:
    blockers = []
    if not experiments:
        blockers.append("No structured domain hypothesis supplied to AI-2.")
    for row in experiments:
        blockers.extend(
            f"{row.get('hypothesis_id', 'hypothesis')}: missing {field}."
            for field in row.get("missing_required_fields", [])
        )
        if row.get("variable_symbol_contract_complete") is False:
            blockers.append(
                f"{row.get('hypothesis_id', 'hypothesis')}: one or more explicit variable symbols "
                "lack definition/unit/interpretation."
            )
    if models and any(model.get("model_contract_complete") is not True for model in models):
        blockers.append(
            "At least one mathematical model lacks a complete "
            "type/expression/objective/constraints/assumptions/symbol/estimation/"
            "identifiability/data-linked-prediction contract."
        )
    if not any(e.get("test_state") in {TEST_PERFORMED, RESULT_OBSERVED} for e in experiments):
        blockers.append("No actual domain test execution evidenced; proposed tests cannot be reported as results.")
    if not any(e.get("test_state") == RESULT_OBSERVED for e in experiments):
        blockers.append("No domain-hypothesis observed result with explicit provenance available.")
    for label, analysis in advanced.items():
        if not (isinstance(analysis, Mapping) and analysis.get("observed")):
            blockers.append(f"{label} remains NOT TESTED because no valid provenance-bearing receipt was supplied.")
    if bias_guard.get("unverified_findings"):
        blockers.append(
            "One or more bias/leakage findings are asserted without sufficient evidence/provenance and require investigation."
        )
    if bias_guard.get("verified_findings"):
        blockers.append("Verified bias/leakage finding(s) invalidate affected decisive verdicts until a clean re-test.")
    if trading:
        blockers.append(
            "Trading deployment conclusions require provenance-bearing friction-net per-trade data, "
            "OOS validation, stability evidence and explicit ruin-model inputs where risk of ruin is claimed."
        )
    if float(confidence.get("score", 0) or 0) < 100:
        blockers.append("Evidence-readiness checklist is not fully satisfied; inspect Confidence /100 checks.")
    return list(dict.fromkeys(blockers))


def _can_test(experiments: Sequence[Mapping[str, Any]], trading: bool) -> list:
    rows = [
        "Audit experiment-contract completeness, baseline adequacy, falsifiability, measurability and leakage exposure now.",
        "Pre-register robustness, ablation, statistical and predictive-validation protocols now; numeric outcomes require data/execution.",
        "Evaluate supplied provenance-bearing numeric result receipts now; no receipt means no observed result.",
        "Calculate Bayesian update, multiplicity correction and power only when their required priors/likelihoods/p-values/alpha/effect inputs are explicitly supplied.",
        "Evaluate supplied predictive, robustness, ablation and failure-distribution receipts without inventing thresholds.",
    ]
    if experiments:
        rows.append("Convert structured hypotheses into exact test contracts; missing fields stay UNKNOWN/TO BE ESTIMATED.")
    if trading:
        rows.append(
            "Calculate provenance-bearing per-trade receipts and risk-of-ruin only when all "
            "bankroll/horizon/dependence inputs are explicit."
        )
    return rows


def _cannot_test(experiments: Sequence[Mapping[str, Any]]) -> list:
    rows = []
    if not experiments:
        rows.append("Domain hypotheses cannot be validated because no structured hypothesis reached AI-2.")
    if not any(e.get("Dataset/sample") != UNKNOWN for e in experiments):
        rows.append(
            "Effect size/CI/power/bootstrap/permutation/replication require a concrete "
            "dataset/sample or explicit design inputs."
        )
    if not any(e.get("test_state") in {TEST_PERFORMED, RESULT_OBSERVED} for e in experiments):
        rows.append("No claim can be promoted to PASS/FAIL from a proposed protocol alone.")
    if not any(e.get("test_state") == RESULT_OBSERVED for e in experiments):
        rows.append("Observed performance/effect cannot be asserted without result provenance and recorded outputs.")
    return rows or ["Conclusions beyond exact observed tests remain untested; external generalization still needs replication."]


def validate_ai2_packet(packet: Mapping[str, Any]) -> Dict[str, Any]:
    sections = packet.get("sections") if isinstance(packet, Mapping) else {}
    sections = sections if isinstance(sections, Mapping) else {}
    missing = [name for name in REQUIRED_SECTIONS if name not in sections]
    errors = ["missing_required_sections"] if missing else []
    exp_section = sections.get("6. Exact Experiments / Backtests / Simulations Required", {})
    rows = exp_section.get("domain_hypothesis_experiments", []) if isinstance(exp_section, Mapping) else []
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        errors.append("experiment_rows_not_sequence")
        rows = []
    for row in rows:
        if not isinstance(row, Mapping):
            errors.append("experiment_row_not_mapping")
            continue
        if row.get("test_state") not in TEST_STATES:
            errors.append("invalid_test_state")
        if row.get("hypothesis_status") not in HYPOTHESIS_STATUSES:
            errors.append("invalid_hypothesis_status")
        for field in EXPERIMENT_FIELDS:
            if field not in row:
                errors.append(f"missing_experiment_field:{field}")
        if row.get("test_state") == RESULT_OBSERVED:
            if not meaningful(row.get("result_provenance")) or _result_missing(row.get("result")):
                errors.append("observed_result_without_provenance")
            if row.get("hypothesis_status") in {PASS, CONDITIONAL_PASS, FAIL}:
                decision = row.get("decision_basis")
                if not isinstance(decision, Mapping) or decision.get("rule_source") != "SUPPLIED_IN_RESULT_RECEIPT":
                    errors.append("decisive_status_without_explicit_decision_rule")
        elif row.get("hypothesis_status") in {PASS, CONDITIONAL_PASS, FAIL}:
            errors.append("decisive_status_without_observed_result")

    advanced = packet.get("advanced_receipt_analyses") if isinstance(packet, Mapping) else {}
    if isinstance(advanced, Mapping):
        predictive = advanced.get("predictive_validation")
        if isinstance(predictive, Mapping) and predictive.get("status") in {PASS, CONDITIONAL_PASS, FAIL}:
            if predictive.get("final_test_valid") is not True:
                errors.append("predictive_decision_without_valid_untouched_test")
            decision = predictive.get("decision")
            if not isinstance(decision, Mapping) or decision.get("rule_source") != "SUPPLIED_IN_RESULT_RECEIPT":
                errors.append("predictive_decision_without_explicit_rule")
    return {
        "valid": not errors,
        "errors": sorted(set(errors)),
        "missing_sections": missing,
        "required_section_count": len(REQUIRED_SECTIONS),
        "truth_invariant": (
            "Plans/targets/narratives are never observed results; decisive status requires "
            "explicit provenance and supplied decision rule."
        ),
    }


class AI2ValidationDirector:
    def build_packet(
        self, question: str, research_result: Optional[Mapping[str, Any]],
        second_pass_outputs: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        result = research_result if isinstance(research_result, Mapping) else {}
        handoffs = collect_second_pass_outputs(result, second_pass_outputs)
        hypotheses = extract_hypotheses(result)
        experiments = [normalize_experiment(h, i) for i, h in enumerate(hypotheses, 1)]
        _apply_result_receipts(experiments, result)
        trading = is_trading(question)
        models = extract_math_models(hypotheses, result)

        predictive_receipt = find_predictive_receipt(result)
        robustness_receipt = find_robustness_receipt(result)
        ablation_receipt = find_ablation_receipt(result)
        failure_receipt = find_failure_receipt(result)
        advanced = {
            "predictive_validation": (
                analyze_predictive_receipt(predictive_receipt)
                if predictive_receipt
                else {"observed": False, "status": INCONCLUSIVE, "reason": "No predictive validation receipt supplied."}
            ),
            "robustness": (
                analyze_robustness_receipt(robustness_receipt)
                if robustness_receipt
                else {"observed": False, "status": INCONCLUSIVE, "reason": "No robustness receipt supplied."}
            ),
            "ablation": (
                analyze_ablation_receipt(ablation_receipt)
                if ablation_receipt
                else {"observed": False, "status": INCONCLUSIVE, "reason": "No ablation receipt supplied."}
            ),
            "failure_distribution": (
                analyze_failure_receipt(failure_receipt)
                if failure_receipt
                else {"observed": False, "status": INCONCLUSIVE, "reason": "No failure-distribution receipt supplied."}
            ),
        }

        bias_rows = bias_audit(result)
        bias_guard = apply_bias_guard(bias_rows, experiments)
        _enforce_decisive_bias_guard(experiments, bias_guard)
        confidence = confidence_score(experiments, result)
        confidence["advanced_validation_states"] = {
            name: _analysis_state(value) for name, value in advanced.items()
        }
        confidence["bias_guard_active"] = bool(bias_guard.get("verified_findings"))
        upstream_ei = existing_experiment_intelligence(result)
        second = second_pass_summary(handoffs)

        experiment_section: Dict[str, Any] = {
            "domain_hypothesis_experiments": experiments,
            "required_contract_fields": list(EXPERIMENT_FIELDS),
            "predictive_validation_standard": {
                "training": "Discovery only.",
                "validation": "Model/parameter selection only.",
                "untouched_test": "Final evaluation; lock before tuning and never optimize on it.",
                "additional": ["rolling", "walk-forward", "external replication", "cross-dataset", "temporal", "regime"],
            },
            "executed_predictive_validation": advanced["predictive_validation"],
            "statistical_validation_standard": [
                "effect size", "uncertainty interval", "confidence interval when justified",
                "Bayesian evidence with explicit priors/likelihoods", "bootstrap", "permutation test",
                "Monte Carlo", "multiple-testing correction", "power analysis",
            ],
            "result_receipt_contract": {
                "provenance_required": True,
                "numeric_observations_required_for_calculation": True,
                "pass_fail_rule_required": True,
                "conditional_pass_supported_by_explicit_rule": True,
                "no_default_confidence_level": True,
                "no_default_bootstrap_or_permutation_iterations": True,
                "no_default_alpha_power_prior_or_likelihood": True,
            },
            "result_provenance_rule": (
                "TEST PROPOSED / TEST POSSIBLE / TEST PERFORMED / RESULT OBSERVED are distinct; "
                "RESULT OBSERVED requires explicit provenance."
            ),
            "existing_experiment_intelligence": upstream_ei,
            "reuse_rule": (
                "Reuse upstream Bayesian/information-gain planning when present; "
                "AI-2 adds controls rather than replacing it."
            ),
        }
        if trading:
            experiment_section["trading_validation_standard"] = trading_standard(hypotheses, result)

        robustness_section = robustness_plan()
        robustness_section.append({
            "dimension": "EXECUTED ROBUSTNESS RECEIPT",
            "state": _analysis_state(advanced["robustness"]),
            "observed_result": advanced["robustness"],
        })
        ablation_section = ablation_plan(hypotheses)
        ablation_section["executed_analysis"] = advanced["ablation"]
        failure_section = failure_plan()
        failure_section.append({
            "dimension": "EXECUTED FAILURE DISTRIBUTION RECEIPT",
            "state": _analysis_state(advanced["failure_distribution"]),
            "observed_result": advanced["failure_distribution"],
        })

        sections: Dict[str, Any] = {
            "1. Interpretation of User Goal": {
                "original_question": text(question, ""),
                "goal": (
                    "Determine whether the proposed explanation/model/strategy is true, false, useful, "
                    "robust or merely attractive storytelling using discriminating observations."
                ),
                "deliverable": "Auditable quantitative validation plan plus honest status of what was actually tested.",
                "do_not_change_task_rule": "Measurement convenience must not silently redefine the requested outcome.",
                "measurement_limits": (
                    "Separate directly measurable outcomes, defensible proxies, unobservable constructs "
                    "and unavailable measurements."
                ),
            },
            "2. Quantifiable Components": {
                "variables_by_hypothesis": [
                    {"hypothesis_id": e["hypothesis_id"], "variables": e["Variables"]} for e in experiments
                ],
                "variable_role_audit": variable_role_audit(experiments),
                "required_variable_roles": [
                    "independent", "dependent", "control", "mediator", "confounder", "state", "uncertainty"
                ],
                "symbol_rule": (
                    "Every explicit mathematical symbol needs definition, unit and interpretation; "
                    "missing metadata remains UNKNOWN and blocks a complete symbol contract."
                ),
                "measurement_rule": "Do not replace the target with an easier proxy without separate proxy-validity evidence.",
                "uncertainty_policy": "Unknown values are UNKNOWN or TO BE ESTIMATED, never convenient defaults.",
            },
            "3. Mathematical Model": {
                "domain_models_found": models,
                "status": (
                    TEST_POSSIBLE
                    if models and all(m.get("model_contract_complete") is True for m in models)
                    else INCONCLUSIVE
                ),
                "if_absent": "UNKNOWN — no mathematical model is invented for decoration.",
                "model_families_when_justified": [
                    "equations", "objective functions", "constraints", "probabilistic",
                    "causal", "optimization", "dynamical",
                ],
                "model_requirements": [
                    "model type", "objective/target", "defined symbols+units+interpretation",
                    "assumptions", "constraints or explicit none", "estimable parameters",
                    "identifiability/estimation or explicit not-applicable", "data-linked prediction",
                ],
                "unknown_value_policy": "Unmeasured parameters: TO BE ESTIMATED; unavailable quantities: UNKNOWN.",
            },
            "4. Baselines": {
                "policy": (
                    "Every complex candidate must beat the simplest valid baseline under the same data, "
                    "metric and friction assumptions."
                ),
                "domain_baselines": [
                    {"hypothesis_id": e["hypothesis_id"], "baseline": e["Baseline"]} for e in experiments
                ],
                "candidates": [
                    "naive/persistence when valid", "simple heuristic", "basic statistical model",
                    "standard existing method", "random only when meaningful",
                ],
                "selection_status": (
                    "PARTIALLY_EXPLICIT" if any(e["Baseline"] != UNKNOWN for e in experiments)
                    else TO_BE_ESTIMATED
                ),
            },
            "5. Independent Testable Hypotheses": meta_hypotheses(trading),
            "6. Exact Experiments / Backtests / Simulations Required": experiment_section,
            "7. Bias & Leakage Risks": bias_rows,
            "8. Robustness Plan": robustness_section,
            "9. Ablation Plan": ablation_section,
            "10. Real-World Friction": friction_plan(trading, result),
            "11. Failure Modes": failure_section,
            "12. What Can Be Tested Now": _can_test(experiments, trading),
            "13. What Cannot Yet Be Tested": _cannot_test(experiments),
            "14. Cross-Agent Alerts": cross_agent_alerts(experiments, trading),
            "15. Highest-Value Second-Pass Validation Tasks": second_pass_tasks(experiments, trading, handoffs),
            "16. Confidence /100": confidence,
            "17. Exactly What Prevents a Higher Score": _blockers(
                experiments, confidence, trading, models, advanced, bias_guard
            ),
        }
        packet: Dict[str, Any] = {
            "title": "AI-2 VALIDATION PACKET",
            "agent_id": AGENT_ID,
            "schema_version": SCHEMA_VERSION,
            "mode": "PARALLEL MULTI-AGENT RESEARCH COMPANY",
            "role": "Quantitative Science, Experiment, Testing & Validation Director",
            "truth_policy": {
                "never_invent_results": True,
                "unknown_labels": [UNKNOWN, TO_BE_ESTIMATED, NOT_TESTED],
                "test_states": [TEST_PROPOSED, TEST_POSSIBLE, TEST_PERFORMED, RESULT_OBSERVED],
                "hypothesis_statuses": [PASS, CONDITIONAL_PASS, INCONCLUSIVE, FAIL],
                "narrow_rejection_rule": (
                    "A failed test rejects only the claim actually tested; "
                    "never a whole theory family by invalid generalization."
                ),
            },
            "input_summary": {
                "structured_hypotheses_seen": len(hypotheses),
                "sources_seen": source_count(result),
                "trading_specific_standard_enabled": trading,
                "second_pass_inputs_present": bool(handoffs),
                "upstream_experiment_intelligence_present": upstream_ei["present"],
                "ai1_research_packet_present": isinstance(result.get("ai1_research_packet"), Mapping),
            },
            "advanced_receipt_analyses": advanced,
            "decision_guards": {"bias_leakage_guard": bias_guard},
            "sections": sections,
            "second_pass_context": second,
        }
        if handoffs:
            packet["second_pass_context"]["agent_outputs"] = _compact_handoffs(handoffs)
            packet["second_pass_context"]["full_payloads_used_internally"] = True
            packet["second_pass_context"]["full_payloads_embedded_in_ai2_packet"] = False
        packet["packet_integrity"] = validate_ai2_packet(packet)
        return packet


def attach_ai2_validation(
    question: str, research_result: Mapping[str, Any],
    director: Optional[AI2ValidationDirector] = None,
) -> Dict[str, Any]:
    """Add AI-2 without mutating/replacing existing output; AI-2 failure never crashes research."""
    enriched = dict(research_result or {})
    try:
        enriched["ai2_validation"] = (director or AI2ValidationDirector()).build_packet(question, enriched)
    except Exception:
        enriched["ai2_validation"] = {
            "title": "AI-2 VALIDATION PACKET",
            "agent_id": AGENT_ID,
            "schema_version": SCHEMA_VERSION,
            "status": INCONCLUSIVE,
            "error": "validation_packet_unavailable",
            "truth_policy": {"never_invent_results": True},
            "packet_integrity": {"valid": False, "errors": ["packet_build_failed"]},
        }
    return enriched
