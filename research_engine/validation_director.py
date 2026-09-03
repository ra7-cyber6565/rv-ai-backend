"""AI-2 Quantitative Science, Experiment, Testing & Validation Director.

The layer is additive and fail-closed. Plans never become results; missing values
stay explicit; decisive statuses require provenance plus a supplied decision rule.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Mapping, Optional, Sequence

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


def _apply_result_receipts(experiments: Sequence[Dict[str, Any]], result: Mapping[str, Any]) -> None:
    for row in experiments:
        receipt = find_result_receipt(result, str(row.get("hypothesis_id") or ""))
        if not receipt:
            continue
        analysis = analyze_two_group_receipt(receipt)
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


def _result_missing(value: Any) -> bool:
    return value is None or value == NOT_TESTED or value == UNKNOWN


def _blockers(experiments: Sequence[Mapping[str, Any]], confidence: Mapping[str, Any], trading: bool) -> list:
    blockers = []
    if not experiments:
        blockers.append("No structured domain hypothesis supplied to AI-2.")
    for row in experiments:
        blockers.extend(f"{row.get('hypothesis_id', 'hypothesis')}: missing {field}." for field in row.get("missing_required_fields", []))
    if not any(e.get("test_state") in {TEST_PERFORMED, RESULT_OBSERVED} for e in experiments):
        blockers.append("No actual test execution evidenced; proposed tests cannot be reported as results.")
    if not any(e.get("test_state") == RESULT_OBSERVED for e in experiments):
        blockers.append("No observed result with explicit provenance available.")
    if trading:
        blockers.append("Trading performance is NOT TESTED unless a provenance-bearing per-trade result receipt exists; a deployment PASS also requires friction-net returns.")
    if float(confidence.get("score", 0) or 0) < 100:
        blockers.append("Evidence-readiness checklist is not fully satisfied; inspect Confidence /100 checks.")
    return list(dict.fromkeys(blockers))


def _can_test(experiments: Sequence[Mapping[str, Any]], trading: bool) -> list:
    rows = [
        "Audit experiment-contract completeness, baseline adequacy, falsifiability, measurability and leakage exposure now.",
        "Pre-register robustness, ablation, statistical and predictive-validation protocols now; numeric outcomes require data/execution.",
        "Evaluate supplied provenance-bearing numeric result receipts now; no receipt means no observed result.",
        "Calculate Bayesian update, multiplicity correction and power only when their required priors/likelihoods/p-values/alpha/effect inputs are explicitly supplied.",
    ]
    if experiments:
        rows.append("Convert structured hypotheses into exact test contracts; missing fields stay UNKNOWN/TO BE ESTIMATED.")
    if trading:
        rows.append("Calculate provenance-bearing per-trade receipts; never import claimed summary metrics as validated performance.")
    return rows


def _cannot_test(experiments: Sequence[Mapping[str, Any]]) -> list:
    rows = []
    if not experiments:
        rows.append("Domain hypotheses cannot be validated because no structured hypothesis reached AI-2.")
    if not any(e.get("Dataset/sample") != UNKNOWN for e in experiments):
        rows.append("Effect size/CI/power/bootstrap/permutation/replication require a concrete dataset/sample or explicit design inputs.")
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
        errors.append("experiment_rows_not_sequence"); rows = []
    for row in rows:
        if not isinstance(row, Mapping):
            errors.append("experiment_row_not_mapping"); continue
        if row.get("test_state") not in TEST_STATES: errors.append("invalid_test_state")
        if row.get("hypothesis_status") not in HYPOTHESIS_STATUSES: errors.append("invalid_hypothesis_status")
        for field in EXPERIMENT_FIELDS:
            if field not in row: errors.append(f"missing_experiment_field:{field}")
        if row.get("test_state") == RESULT_OBSERVED:
            if not meaningful(row.get("result_provenance")) or _result_missing(row.get("result")):
                errors.append("observed_result_without_provenance")
            if row.get("hypothesis_status") in {PASS, CONDITIONAL_PASS, FAIL}:
                decision = row.get("decision_basis")
                if not isinstance(decision, Mapping) or decision.get("rule_source") != "SUPPLIED_IN_RESULT_RECEIPT":
                    errors.append("decisive_status_without_explicit_decision_rule")
        elif row.get("hypothesis_status") in {PASS, CONDITIONAL_PASS, FAIL}:
            errors.append("decisive_status_without_observed_result")
    return {"valid": not errors, "errors": sorted(set(errors)), "missing_sections": missing,
            "required_section_count": len(REQUIRED_SECTIONS),
            "truth_invariant": "Plans/targets/narratives are never observed results; decisive status requires explicit provenance and supplied decision rule."}


class AI2ValidationDirector:
    def build_packet(self, question: str, research_result: Optional[Mapping[str, Any]],
                     second_pass_outputs: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        result = research_result if isinstance(research_result, Mapping) else {}
        hypotheses = extract_hypotheses(result)
        experiments = [normalize_experiment(h, i) for i, h in enumerate(hypotheses, 1)]
        _apply_result_receipts(experiments, result)
        trading = is_trading(question); models = extract_math_models(hypotheses, result)
        confidence = confidence_score(experiments, result)
        upstream_ei = existing_experiment_intelligence(result); second = second_pass_summary(second_pass_outputs)

        experiment_section: Dict[str, Any] = {
            "domain_hypothesis_experiments": experiments,
            "required_contract_fields": list(EXPERIMENT_FIELDS),
            "predictive_validation_standard": {"training": "Discovery only.", "validation": "Model/parameter selection only.",
                "untouched_test": "Final evaluation; lock before tuning and never optimize on it.",
                "additional": ["rolling", "walk-forward", "external replication", "cross-dataset", "temporal", "regime"]},
            "statistical_validation_standard": ["effect size", "uncertainty interval", "confidence interval when justified",
                "Bayesian evidence with explicit priors/likelihoods", "bootstrap", "permutation test", "Monte Carlo",
                "multiple-testing correction", "power analysis"],
            "result_receipt_contract": {"provenance_required": True, "numeric_observations_required_for_calculation": True,
                "pass_fail_rule_required": True, "no_default_confidence_level": True,
                "no_default_bootstrap_or_permutation_iterations": True,
                "no_default_alpha_power_prior_or_likelihood": True},
            "result_provenance_rule": "TEST PROPOSED / TEST POSSIBLE / TEST PERFORMED / RESULT OBSERVED are distinct; RESULT OBSERVED requires explicit provenance.",
            "existing_experiment_intelligence": upstream_ei,
            "reuse_rule": "Reuse upstream Bayesian/information-gain planning when present; AI-2 adds controls rather than replacing it."}
        if trading:
            experiment_section["trading_validation_standard"] = trading_standard(hypotheses, result)

        sections: Dict[str, Any] = {
            "1. Interpretation of User Goal": {"original_question": text(question, ""),
                "goal": "Determine whether the proposed explanation/model/strategy is true, false, useful, robust or merely attractive storytelling using discriminating observations.",
                "deliverable": "Auditable quantitative validation plan plus honest status of what was actually tested.",
                "do_not_change_task_rule": "Measurement convenience must not silently redefine the requested outcome.",
                "measurement_limits": "Separate directly measurable outcomes, defensible proxies, unobservable constructs and unavailable measurements."},
            "2. Quantifiable Components": {"variables_by_hypothesis": [{"hypothesis_id": e["hypothesis_id"], "variables": e["Variables"]} for e in experiments],
                "required_variable_roles": ["independent", "dependent", "control", "mediator", "confounder", "state", "uncertainty"],
                "symbol_rule": "Every mathematical symbol needs definition, unit and interpretation; missing metadata remains UNKNOWN.",
                "measurement_rule": "Do not replace the target with an easier proxy without separate proxy-validity evidence.",
                "uncertainty_policy": "Unknown values are UNKNOWN or TO BE ESTIMATED, never convenient defaults."},
            "3. Mathematical Model": {"domain_models_found": models,
                "status": TEST_POSSIBLE if models and all(m["symbol_contract_complete"] for m in models) else INCONCLUSIVE,
                "if_absent": "UNKNOWN — no mathematical model is invented for decoration.",
                "model_families_when_justified": ["equations", "objective functions", "constraints", "probabilistic", "causal", "optimization", "dynamical"],
                "model_requirements": ["objective/target", "defined symbols+units+interpretation", "assumptions", "constraints", "estimable parameters", "identifiability/estimation", "data-linked prediction"],
                "unknown_value_policy": "Unmeasured parameters: TO BE ESTIMATED; unavailable quantities: UNKNOWN."},
            "4. Baselines": {"policy": "Every complex candidate must beat the simplest valid baseline under the same data, metric and friction assumptions.",
                "domain_baselines": [{"hypothesis_id": e["hypothesis_id"], "baseline": e["Baseline"]} for e in experiments],
                "candidates": ["naive/persistence when valid", "simple heuristic", "basic statistical model", "standard existing method", "random only when meaningful"],
                "selection_status": "PARTIALLY_EXPLICIT" if any(e["Baseline"] != UNKNOWN for e in experiments) else TO_BE_ESTIMATED},
            "5. Independent Testable Hypotheses": meta_hypotheses(trading),
            "6. Exact Experiments / Backtests / Simulations Required": experiment_section,
            "7. Bias & Leakage Risks": bias_audit(result), "8. Robustness Plan": robustness_plan(),
            "9. Ablation Plan": ablation_plan(hypotheses), "10. Real-World Friction": friction_plan(trading),
            "11. Failure Modes": failure_plan(), "12. What Can Be Tested Now": _can_test(experiments, trading),
            "13. What Cannot Yet Be Tested": _cannot_test(experiments), "14. Cross-Agent Alerts": cross_agent_alerts(experiments, trading),
            "15. Highest-Value Second-Pass Validation Tasks": second_pass_tasks(experiments, trading, second_pass_outputs),
            "16. Confidence /100": confidence, "17. Exactly What Prevents a Higher Score": _blockers(experiments, confidence, trading)}
        packet: Dict[str, Any] = {"title": "AI-2 VALIDATION PACKET", "agent_id": AGENT_ID, "schema_version": SCHEMA_VERSION,
            "mode": "PARALLEL MULTI-AGENT RESEARCH COMPANY", "role": "Quantitative Science, Experiment, Testing & Validation Director",
            "truth_policy": {"never_invent_results": True, "unknown_labels": [UNKNOWN, TO_BE_ESTIMATED, NOT_TESTED],
                "test_states": [TEST_PROPOSED, TEST_POSSIBLE, TEST_PERFORMED, RESULT_OBSERVED],
                "hypothesis_statuses": [PASS, CONDITIONAL_PASS, INCONCLUSIVE, FAIL],
                "narrow_rejection_rule": "A failed test rejects only the claim actually tested; never a whole theory family by invalid generalization."},
            "input_summary": {"structured_hypotheses_seen": len(hypotheses), "sources_seen": source_count(result),
                "trading_specific_standard_enabled": trading, "second_pass_inputs_present": bool(second_pass_outputs),
                "upstream_experiment_intelligence_present": upstream_ei["present"]},
            "sections": sections, "second_pass_context": second}
        if second_pass_outputs:
            packet["second_pass_context"]["agent_outputs"] = deepcopy(dict(second_pass_outputs))
        packet["packet_integrity"] = validate_ai2_packet(packet)
        return packet


def attach_ai2_validation(question: str, research_result: Mapping[str, Any],
                          director: Optional[AI2ValidationDirector] = None) -> Dict[str, Any]:
    """Add AI-2 without mutating/replacing existing output; AI-2 failure never crashes research."""
    enriched = dict(research_result or {})
    try:
        enriched["ai2_validation"] = (director or AI2ValidationDirector()).build_packet(question, enriched)
    except Exception:
        enriched["ai2_validation"] = {"title": "AI-2 VALIDATION PACKET", "agent_id": AGENT_ID,
            "schema_version": SCHEMA_VERSION, "status": INCONCLUSIVE, "error": "validation_packet_unavailable",
            "truth_policy": {"never_invent_results": True},
            "packet_integrity": {"valid": False, "errors": ["packet_build_failed"]}}
    return enriched
