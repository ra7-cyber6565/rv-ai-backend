"""AI-2 — Quantitative Science, Experiment & Validation Director.

This is the canonical fail-closed director for the parallel research company.
It turns explanations, theories, strategies and models into measurable variables,
mathematical structures, baselines, falsifiable tests, validation receipts and
second-round discriminators. It performs no network/model/API calls.
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .validation_guard import (
    ablation_analysis, audit_holdout, evaluate_decision_rule,
    failure_cluster_analysis, failure_distribution, leakage_bias_audit,
    parameter_stability, regime_summary, seal_holdout, walk_forward_summary,
)
from .validation_stats import (
    benjamini_hochberg, beta_binomial_posterior, bootstrap_difference_ci,
    bootstrap_mean_ci, classification_metrics, mean_difference_effect,
    permutation_mean_difference, regression_metrics, statistical_validation,
    two_sample_power_n,
)
from .validation_trading import (
    edge_decay_analysis, monte_carlo_trade_paths, trade_pnl_series,
    trading_friction_stress, trading_metrics, trading_regime_metrics,
)
from .validation_types import (
    UNKNOWN, TO_ESTIMATE, BaselineSpec, ExperimentSpec, HypothesisSpec,
    HypothesisStatus, TestState, VariableRole, VariableSpec, known, listify,
    mapping, number, text,
)

_DOMAIN_TERMS = {
    "trading": ("trade", "trading", "strategy", "nas100", "us100", "xauusd", "forex", "entry", "stop loss", "profit factor"),
    "prediction": ("predict", "classifier", "classification", "regression", "machine learning", "forecast", "model accuracy"),
    "medicine": ("patient", "treatment", "drug", "clinical", "disease", "therapy", "medical"),
    "engineering": ("engine", "motor", "material", "device", "manufactur", "hardware", "thermal", "battery", "efficiency"),
    "causal": ("cause", "causal", "effect of", "why does", "mechanism", "intervention"),
}

PACKET_HEADINGS = (
    "1. Interpretation of User Goal", "2. Quantifiable Components", "3. Mathematical Model",
    "4. Baselines", "5. Independent Testable Hypotheses",
    "6. Exact Experiments / Backtests / Simulations Required", "7. Bias & Leakage Risks",
    "8. Robustness Plan", "9. Ablation Plan", "10. Real-World Friction", "11. Failure Modes",
    "12. What Can Be Tested Now", "13. What Cannot Yet Be Tested", "14. Cross-Agent Alerts",
    "15. Highest-Value Second-Pass Validation Tasks", "16. Confidence /100",
    "17. Exactly What Prevents a Higher Score",
)


def detect_domain(question: str, proposal: Mapping[str, Any]) -> str:
    explicit = text(proposal.get("domain")).lower()
    if explicit:
        return explicit
    low = text(question).lower()
    scores = {name: sum(term in low for term in terms) for name, terms in _DOMAIN_TERMS.items()}
    best, score = max(scores.items(), key=lambda kv: kv[1])
    return best if score else "general"


def _variables(domain: str, proposal: Mapping[str, Any]) -> List[VariableSpec]:
    supplied = []
    for row in listify(proposal.get("variables")):
        if isinstance(row, Mapping):
            supplied.append(VariableSpec(
                symbol=text(row.get("symbol"), "?"), definition=text(row.get("definition"), UNKNOWN),
                unit=text(row.get("unit"), UNKNOWN), interpretation=text(row.get("interpretation"), UNKNOWN),
                role=text(row.get("role"), "unspecified"), value_status=text(row.get("value_status"), UNKNOWN)))
    if supplied:
        return supplied
    if domain == "trading":
        return [
            VariableSpec("r_t", "net P&L/return of trade t after explicitly modelled friction", UNKNOWN, "realized strategy outcome", VariableRole.DEPENDENT.value),
            VariableSpec("x_t", "information/features available at decision time t", "feature-specific", "entry/filter state with no future data", VariableRole.INDEPENDENT.value),
            VariableSpec("c_t", "commission + spread + slippage + financing + supplied taxes for trade t", "same unit as r_t", "real-world friction", VariableRole.CONTROL.value, TO_ESTIMATE),
            VariableSpec("q_t", "position size/exposure", "contracts/lots or currency risk", "risk taken on trade t", VariableRole.STATE.value, TO_ESTIMATE),
            VariableSpec("R_t", "market regime/session state", "categorical", "condition under which edge may change", VariableRole.CONFOUNDER.value),
            VariableSpec("epsilon_t", "unmodelled execution/market noise", "same outcome scale", "residual uncertainty", VariableRole.UNCERTAINTY.value),
        ]
    if domain == "prediction":
        return [
            VariableSpec("X", "predictor matrix using only information available before target time", "feature-specific", "candidate inputs", VariableRole.INDEPENDENT.value),
            VariableSpec("Y", "target outcome", UNKNOWN, "quantity/class to predict", VariableRole.DEPENDENT.value),
            VariableSpec("theta", "model parameters selected without touching final test set", "model-specific", "learned degrees of freedom", VariableRole.PARAMETER.value, TO_ESTIMATE),
            VariableSpec("L", "predeclared loss/metric", "metric-specific", "model selection/evaluation criterion", VariableRole.DEPENDENT.value),
            VariableSpec("epsilon", "irreducible/residual prediction error", "target-specific", "uncertainty", VariableRole.UNCERTAINTY.value),
        ]
    return [
        VariableSpec("X", "intervention/exposure or proposed causal input", UNKNOWN, "quantity intentionally varied or compared", VariableRole.INDEPENDENT.value),
        VariableSpec("Y", "primary measured outcome", UNKNOWN, "result the claim predicts", VariableRole.DEPENDENT.value),
        VariableSpec("C", "measured control/confounder set", "variable-specific", "alternative causes requiring control", VariableRole.CONFOUNDER.value),
        VariableSpec("M", "candidate mediator(s)", "variable-specific", "mechanistic pathway between X and Y", VariableRole.MEDIATOR.value),
        VariableSpec("theta", "unknown model parameters", "model-specific", "strength/shape of relationships", VariableRole.PARAMETER.value, TO_ESTIMATE),
        VariableSpec("epsilon", "measurement/process noise", "same unit as Y where additive", "unexplained uncertainty", VariableRole.UNCERTAINTY.value),
    ]


def _mathematical_model(domain: str, variables: List[VariableSpec], proposal: Mapping[str, Any]) -> Dict[str, Any]:
    supplied = text(proposal.get("mathematical_model"))
    if supplied:
        equation, note = supplied, "Caller-supplied model; parameters still require estimation/validation."
    elif domain == "trading":
        equation = "r_t = gross_t - commission_t - spread_t - slippage_t - financing_t - tax_t; E[r_t | rule, regime] estimated out-of-sample"
        note = "No friction term is silently set to zero; absent costs remain TO BE ESTIMATED."
    elif domain == "prediction":
        equation = "theta* = argmin_theta L_validation(f_theta(X),Y); final score = L_test(f_theta*(X_test),Y_test) evaluated once on untouched test"
        note = "Training fits, validation selects, untouched test estimates final generalization."
    elif domain == "medicine":
        equation = "Y_i = beta_0 + beta_T T_i + beta_C^T C_i + epsilon_i; causal estimand ATE = E[Y_i(1)-Y_i(0)]"
        note = "beta_T is not causal unless randomization or a defensible identification strategy controls treatment-selection confounding."
    elif domain == "engineering":
        equation = "y = f(x,theta,d) + epsilon, subject to g_j(x,theta,d) <= L_j; theta and L_j are TO BE ESTIMATED/SUPPLIED"
        note = "Validate tolerances, measurement uncertainty, operating envelope and replication across builds/batches."
    else:
        equation = "Y = f(X,C;theta) + epsilon; causal target Delta = E[Y|do(X=x1)] - E[Y|do(X=x0)]"
        note = "Observational association alone does not identify the do(.) causal target."

    if domain == "trading":
        objective = "Estimate/optimize the prespecified net objective only on train/validation data; evaluate once out-of-sample after all friction."
        constraints = ["Risk/drawdown/ruin limits are UNKNOWN until supplied.", "No future information, fake fills or unmodelled cost may enter the decision path."]
    elif domain == "prediction":
        objective = "Minimize prespecified validation loss during selection; report untouched-test generalization without retuning."
        constraints = ["Final test is used once.", "Features must exist at prediction time.", "Complex model must beat a simple baseline."]
    elif domain == "engineering":
        objective = "Estimate performance/reliability across the operating envelope while satisfying supplied physical/safety constraints."
        constraints = ["Engineering limits/tolerances must be supplied, not invented.", "Replicate across builds/batches and measurement systems."]
    elif domain == "medicine":
        objective = "Estimate the prespecified effect with uncertainty and an explicit decision rule."
        constraints = ["Identification/randomization assumptions must be defensible.", "Safety, missingness and generalizability must be audited when relevant."]
    else:
        objective = "Estimate the prespecified effect/predictive contrast versus baseline with uncertainty under a falsifiable design."
        constraints = ["Unknown thresholds remain UNKNOWN.", "Association is not promoted to causation without identification."]
    return {"equation": equation, "objective": objective, "constraints": constraints,
            "symbols": [v.to_dict() for v in variables], "note": note,
            "unknown_parameters": [v.symbol for v in variables if v.value_status in (UNKNOWN, TO_ESTIMATE)]}


def _baselines(domain: str, proposal: Mapping[str, Any]) -> List[BaselineSpec]:
    supplied = []
    for i, row in enumerate(listify(proposal.get("baselines")), 1):
        if isinstance(row, Mapping):
            supplied.append(BaselineSpec(
                baseline_id=text(row.get("baseline_id"), f"B{i}"), name=text(row.get("name"), f"Baseline {i}"),
                reason=text(row.get("reason"), "Caller supplied baseline."), metric=text(row.get("metric"), UNKNOWN),
                result=row.get("result", UNKNOWN), status=text(row.get("status"), "TO BE MEASURED")))
    if supplied:
        return supplied
    if domain == "trading":
        return [BaselineSpec("B1", "No-trade / zero-exposure", "Strategy must create positive net value after friction."),
                BaselineSpec("B2", "Simple time/session-matched rule", "Complex rules must beat a simpler rule exposed to comparable conditions.")]
    if domain == "prediction":
        return [BaselineSpec("B1", "Naive majority/mean/persistence", "Complex prediction must beat a trivial data-appropriate predictor."),
                BaselineSpec("B2", "Simple regularized/statistical model", "Complexity must add out-of-sample value beyond a simpler fitted model.")]
    return [BaselineSpec("B1", "Null/no-effect or current standard", "The proposal must outperform the simplest defensible comparator."),
            BaselineSpec("B2", "Simple heuristic/statistical model", "Extra mechanisms/components must earn measurable incremental value.")]


def _hypothesis_from_row(row: Mapping[str, Any], i: int, baseline_id: str) -> HypothesisSpec:
    return HypothesisSpec(
        hypothesis_id=text(row.get("hypothesis_id") or row.get("id"), f"H{i}"),
        statement=text(row.get("statement") or row.get("hypothesis"), f"Candidate hypothesis {i}"),
        mechanism=text(row.get("mechanism"), UNKNOWN),
        prediction=text(row.get("prediction"), "A predeclared measurable difference/predictive improvement must occur."),
        null_hypothesis=text(row.get("null_hypothesis"), "Observed performance/effect is no better than the stated baseline."),
        variables=[text(v) for v in listify(row.get("variables")) if text(v)] or ["X", "Y"],
        baseline_id=text(row.get("baseline_id"), baseline_id),
        test=text(row.get("test"), "Prospective/held-out comparison against baseline using predeclared metric and decision rule."),
        falsification_condition=text(row.get("falsification_condition"), "Prespecified prediction fails on valid independent/untouched evaluation."),
        scope=text(row.get("scope"), "Only the explicitly tested population/time/regime."))


def _default_hypotheses(domain: str, baseline_id: str) -> List[HypothesisSpec]:
    rows = [
        HypothesisSpec("H1", "The proposed method/explanation provides measurable value beyond the simplest valid baseline.",
                       "Real structure should improve the prespecified outcome relative to baseline.",
                       "Primary metric improves versus baseline on valid evaluation data after relevant friction.",
                       "There is no out-of-sample advantage over baseline.", ["X", "Y"], baseline_id,
                       "Baseline-controlled prospective or held-out comparison.",
                       "Candidate fails the prespecified baseline decision rule."),
        HypothesisSpec("H2", "The apparent effect generalizes beyond discovery/tuning data.",
                       "A real effect should survive untouched/temporal/external replication.",
                       "Direction and practically relevant magnitude persist on untouched/external data.",
                       "Discovery result does not replicate out of sample.", ["Y", "theta"], baseline_id,
                       "Train/discovery -> validation -> one-time untouched test plus external/temporal replication.",
                       "Untouched/external evaluation fails the prespecified replication criterion."),
        HypothesisSpec("H3", "Performance is robust in a reasonable neighborhood, not a single sharp optimum.",
                       "Real structure should survive small defensible perturbations unless a mechanism predicts a threshold.",
                       "Nearby parameter/definition/regime tests stay within caller-supplied tolerance.",
                       "Performance is unstable under nearby defensible perturbations.", ["theta", "Y"], baseline_id,
                       "Parameter/noise/definition/regime sensitivity grid without final-holdout retuning.",
                       "Stability region fails the predeclared tolerance or collapses across key regimes."),
        HypothesisSpec("H4", "Each major component provides incremental value.",
                       "Necessary components should measurably improve validated performance.",
                       "Full system beats each ablated variant by the caller-supplied incremental-value criterion.",
                       "One or more components add no measurable incremental value.", ["component", "Y"], baseline_id,
                       "Ablation with identical data/splits/friction and predeclared metric.",
                       "Removing a component does not materially weaken performance under the supplied criterion."),
        HypothesisSpec("H5", "Failure severity remains acceptable under stressed but plausible conditions.",
                       "Useful systems must survive tail events/implementation friction, not merely average well.",
                       "Failure distribution stays within explicit risk/catastrophic limits.",
                       "Tail/catastrophic frequency breaches the supplied limit.", ["Y", "epsilon"], baseline_id,
                       "Stress, scenario, tail-risk and Monte-Carlo/failure-clustering analysis.",
                       "Explicit catastrophic/risk limit is breached."),
    ]
    if domain == "trading":
        rows[0].statement = "The exact trading rules have positive net expectancy versus a simple/no-trade baseline after spread, commission, slippage, latency and other supplied friction."
        rows[0].prediction = "Net out-of-sample expectancy is positive and beats the declared baseline under the supplied rule."
    return rows


def _experiment(h: HypothesisSpec, proposal: Mapping[str, Any], domain: str) -> ExperimentSpec:
    setup = h.test
    if domain == "trading":
        setup += " Freeze exact instrument/feed, timestamp convention, session, long/short entry, stop, target, sizing, no-trade/news rules and all cost assumptions before untouched evaluation."
    return ExperimentSpec(
        test_id=f"T-{h.hypothesis_id}", hypothesis_id=h.hypothesis_id, hypothesis=h.statement,
        variables=h.variables,
        dataset_sample=text(proposal.get("dataset_sample"), "TO BE SPECIFIED — representative sample with provenance, inclusion/exclusion and scope fixed before final testing."),
        experimental_setup=setup, prediction=h.prediction, null_hypothesis=h.null_hypothesis,
        metric=text(proposal.get("primary_metric"), UNKNOWN), baseline=h.baseline_id,
        confounders=[text(x) for x in listify(proposal.get("confounders")) if text(x)] or ["TO BE IDENTIFIED from the data-generating process"],
        falsification_condition=h.falsification_condition,
        replication_method=text(proposal.get("replication_method"), "Independent rerun on a new time/site/dataset/instrument/feed/lab batch as domain permits."),
        state=TestState.POSSIBLE if proposal.get("data_available") else TestState.PROPOSED,
        decision_rule=dict(mapping(proposal.get("decision_rule"))))


def _execution_state(execution: Mapping[str, Any]) -> TestState:
    explicit = text(execution.get("state")).upper()
    for state in TestState:
        if explicit == state.value:
            return state
    if (execution.get("result_observed") or execution.get("metrics")
            or (execution.get("y_true") is not None and execution.get("y_pred") is not None)
            or execution.get("trades") or execution.get("group_a") or execution.get("group_b")):
        return TestState.OBSERVED
    if execution.get("executed"):
        return TestState.PERFORMED
    if execution.get("possible"):
        return TestState.POSSIBLE
    return TestState.PROPOSED


def _metrics(execution: Mapping[str, Any]) -> Dict[str, Any]:
    kind = text(execution.get("kind")).lower()
    if kind in ("classification", "classifier"):
        return classification_metrics(execution.get("y_true") or [], execution.get("y_pred") or [], execution.get("probabilities"))
    if kind in ("regression", "forecast"):
        return regression_metrics(execution.get("y_true") or [], execution.get("y_pred") or [])
    if kind in ("two_group", "two-sample", "experiment"):
        a, b = execution.get("group_a") or [], execution.get("group_b") or []
        return {**mean_difference_effect(a, b),
                "permutation": permutation_mean_difference(a, b, permutations=int(number(execution.get("permutations")) or 5000)),
                "bootstrap_difference_ci": bootstrap_difference_ci(a, b, confidence=float(number(execution.get("confidence")) or .95),
                                                                   resamples=int(number(execution.get("bootstrap_resamples")) or 4000))}
    if kind in ("trading", "backtest"):
        return trading_metrics(execution.get("trades") or [], unit=text(execution.get("unit"), UNKNOWN))
    supplied = dict(mapping(execution.get("metrics")))
    return {"status": "RESULT OBSERVED", **supplied} if supplied else {"status": UNKNOWN, "reason": "No evaluable observations supplied."}


def _baseline_gate(metrics: Mapping[str, Any], decision: Mapping[str, Any],
                   execution: Mapping[str, Any], domain: str) -> Dict[str, Any]:
    if decision.get("status") != HypothesisStatus.PASS.value:
        return dict(decision)
    if execution.get("baseline_beaten") is True:
        return dict(decision)
    if execution.get("baseline_beaten") is False:
        return {"status": HypothesisStatus.FAIL.value, "reason": "Caller reports the candidate did not beat the declared baseline."}
    metric = text(mapping(execution.get("decision_rule")).get("metric"))
    if any(word in metric.lower() for word in ("baseline", "difference", "delta")):
        return dict(decision)
    if "majority_baseline_accuracy" in metrics and number(metrics.get("accuracy")) is not None:
        return dict(decision) if float(metrics["accuracy"]) > float(metrics["majority_baseline_accuracy"]) else {
            "status": HypothesisStatus.FAIL.value, "reason": "Candidate accuracy did not beat the computed majority baseline."}
    if domain == "trading" and metric == "expectancy" and number(metrics.get("expectancy")) is not None:
        return dict(decision) if float(metrics["expectancy"]) > 0 else {
            "status": HypothesisStatus.FAIL.value, "reason": "Net expectancy did not beat no-trade zero-exposure P&L."}
    candidate, baseline = number(execution.get("candidate_result")), number(execution.get("baseline_result"))
    if candidate is not None and baseline is not None:
        beaten = candidate > baseline if bool(execution.get("maximize_metric", True)) else candidate < baseline
        return dict(decision) if beaten else {"status": HypothesisStatus.FAIL.value, "reason": "Candidate did not beat supplied baseline result."}
    return {"status": HypothesisStatus.INCONCLUSIVE.value,
            "reason": str(decision.get("reason") or "") + " Baseline gate remains untested; complex candidate cannot be promoted yet."}


def _integrity_gate(decision: Mapping[str, Any], holdout: Mapping[str, Any],
                    bias: Mapping[str, Any], execution: Mapping[str, Any]) -> Dict[str, Any]:
    if bias.get("fatal"):
        return {"status": HypothesisStatus.FAIL.value,
                "reason": "Evaluation invalidated by confirmed fatal data leakage/bias: " + ", ".join(bias["fatal"])}
    if holdout.get("status") == "TEST PERFORMED" and not holdout.get("integrity_pass", True):
        return {"status": HypothesisStatus.FAIL.value, "reason": holdout.get("fatal_reason") or "Untouched test integrity failed."}
    if decision.get("status") == HypothesisStatus.PASS.value:
        missing = []
        if execution.get("require_external_replication") and not execution.get("external_replication_observed"):
            missing.append("external replication")
        if execution.get("require_friction_test") and not execution.get("friction_observed"):
            missing.append("real-world friction")
        if missing:
            return {"status": HypothesisStatus.CONDITIONAL_PASS.value,
                    "reason": str(decision.get("reason") or "") + " Still missing: " + ", ".join(missing) + "."}
    return dict(decision)


def _predictive_plan(domain: str) -> Dict[str, str]:
    return {
        "training_set": "Discovery/parameter fitting only; no final performance claim.",
        "validation_set": "Model/feature/parameter/threshold selection only.",
        "completely_untouched_test_set": "Seal/hash; one-time final evaluation; never optimize on it.",
        "rolling_walk_forward": "Required where time order matters." if domain in ("trading", "prediction") else "Use when temporal drift/order matters.",
        "external_replication": "New site/dataset/instrument/feed/lab batch/population where feasible.",
        "cross_dataset_testing": "Use independent data definitions/sources to test transportability.",
        "temporal_replication": "Repeat on a later non-overlapping period where the process can drift.",
        "regime_testing": "Predeclare regimes/conditions; do not define regimes after seeing failures.",
    }


def _statistical_plan() -> List[str]:
    return [
        "Report effect size, not only p-values.",
        "Report confidence/credible intervals with level/mass stated.",
        "Use bootstrap when analytic assumptions are weak and resampling is defensible.",
        "Use permutation/randomization tests when exchangeability/design permits.",
        "Bayesian evidence requires an explicit defensible prior; never invent one.",
        "Correct multiple comparisons (for example BH-FDR) when many tests are run.",
        "Power/sample-size planning only after effect size, alpha and target power are supplied/justified.",
        "Monte Carlo/scenario results must disclose assumptions, seed and simulation count.",
    ]


def _friction(domain: str, proposal: Mapping[str, Any]) -> List[str]:
    supplied = [text(x) for x in listify(proposal.get("real_world_friction")) if text(x)]
    if supplied:
        return supplied
    if domain == "trading":
        return ["spread", "commission", "slippage", "latency", "liquidity/partial fills", "financing", "tax/regulatory constraints", "feed/CFD-vs-futures mismatch"]
    if domain == "engineering":
        return ["measurement error", "manufacturing tolerances", "hardware/thermal limits", "compute/latency", "maintenance", "human implementation error", "regulation/certification", "opportunity cost"]
    if domain == "medicine":
        return ["adherence", "measurement error", "site/operator effects", "eligibility/generalizability", "adverse events", "regulation", "cost/access", "dropout/missingness"]
    return ["measurement error", "implementation difficulty", "compute/hardware", "human error", "maintenance", "regulation", "opportunity cost"]


def _trading_standard(proposal: Mapping[str, Any], execution: Mapping[str, Any]) -> Dict[str, Any]:
    def value(name: str, *aliases: str):
        for key in (name,) + aliases:
            if key in execution and execution.get(key) not in (None, ""):
                return execution.get(key)
            if key in proposal and proposal.get(key) not in (None, ""):
                return proposal.get(key)
        return UNKNOWN
    return {
        "exact_instrument": value("instrument"), "feed_assumptions": value("feed_assumptions", "feed"),
        "futures_vs_cfd_relationship": value("futures_vs_cfd_relationship"), "timeframe": value("timeframe"),
        "regime": value("regime"), "session": value("session"), "long_rules": value("long_rules", "long_setup"),
        "short_rules": value("short_rules", "short_setup"), "entry": value("entry", "entry_rule"),
        "stop": value("stop", "stop_loss", "sl"), "target": value("target", "take_profit", "tp"),
        "position_sizing": value("position_sizing"), "no_trade_rules": value("no_trade_rules", "no_trade"),
        "news_filtering": value("news_filtering", "news_rule"), "spread": value("spread"),
        "commission": value("commission"), "slippage": value("slippage"), "latency": value("latency"),
        "sample_size": value("sample_size"), "win_rate": value("win_rate"), "average_win": value("average_win"),
        "average_loss": value("average_loss"), "expectancy": value("expectancy"), "profit_factor": value("profit_factor"),
        "maximum_drawdown": value("maximum_drawdown"), "losing_streak_distribution": value("losing_streak_distribution"),
        "risk_of_ruin": value("risk_of_ruin"), "MAE": value("mae", "MAE"), "MFE": value("mfe", "MFE"),
        "out_of_sample": value("out_of_sample"), "walk_forward": value("walk_forward"),
        "monte_carlo": value("monte_carlo"), "parameter_stability": value("parameter_stability"),
        "regime_stability": value("regime_stability"), "edge_decay": value("edge_decay"),
    }


def _second_pass_tasks(prior: Mapping[str, Any], agents: Mapping[str, Any]) -> List[Dict[str, Any]]:
    tasks = [{"priority": 1, "task": "Re-audit untouched-test integrity and fatal leakage before performance tuning.", "why": "A leak can invalidate the entire result."}]
    disputes = listify(agents.get("disputed_claims")) + listify(agents.get("red_team_objections"))
    if disputes:
        tasks.append({"priority": 2, "task": "Run the minimum discriminator that gives rival explanations different quantitative predictions.", "targets": disputes[:8], "why": "Highest information gain between competing explanations."})
    survivors = listify(prior.get("surviving_hypotheses")) or listify(prior.get("hypotheses"))
    if survivors:
        tasks.append({"priority": 3, "task": "One-time untouched/external replication of strongest surviving hypotheses.", "targets": survivors[:5], "why": "Separates discovery fit from generalization."})
    tasks += [
        {"priority": 4, "task": "Robustness surface: nearby parameters, definitions, periods, noise and regimes without final-holdout tuning.", "why": "Tests stable region vs sharp optimum."},
        {"priority": 5, "task": "Ablation with identical splits/friction to quantify component incremental value.", "why": "Removes decorative complexity."},
        {"priority": 6, "task": "Stress, tail-risk and real-world-friction evaluation using explicit risk limits.", "why": "Average performance can hide unacceptable failure."},
    ]
    return tasks


class QuantitativeValidationDirector:
    agent_id = "AI-2 / VALIDATION-DIRECTOR"

    def analyze(self, question: str, proposal: Optional[Mapping[str, Any]] = None,
                execution_packets: Optional[Mapping[str, Mapping[str, Any]]] = None,
                agent_outputs: Optional[Mapping[str, Any]] = None,
                phase: str = "first") -> Dict[str, Any]:
        proposal, executions, agents = dict(mapping(proposal)), dict(mapping(execution_packets)), dict(mapping(agent_outputs))
        question = text(question)
        domain = detect_domain(question, proposal)
        variables = _variables(domain, proposal)
        model, baselines = _mathematical_model(domain, variables, proposal), _baselines(domain, proposal)
        supplied_h = [r for r in listify(proposal.get("hypotheses")) if isinstance(r, Mapping)]
        hypotheses = ([_hypothesis_from_row(row, i, baselines[0].baseline_id) for i, row in enumerate(supplied_h, 1)]
                      if supplied_h else _default_hypotheses(domain, baselines[0].baseline_id))
        experiments = [_experiment(h, proposal, domain) for h in hypotheses]
        bias_global = leakage_bias_audit(mapping(proposal.get("bias_audit")))
        results = []

        for h, exp in zip(hypotheses, experiments):
            execution = dict(mapping(executions.get(h.hypothesis_id) or executions.get(exp.test_id)))
            state = _execution_state(execution); exp.state = state
            if execution.get("decision_rule"):
                exp.decision_rule = dict(mapping(execution.get("decision_rule")))
            metrics = _metrics(execution) if state in (TestState.PERFORMED, TestState.OBSERVED) else {"status": UNKNOWN}
            local_bias = leakage_bias_audit({**dict(mapping(proposal.get("bias_audit"))), **dict(mapping(execution.get("bias_audit")))})
            holdout = audit_holdout(execution) if execution else {"status": UNKNOWN, "reason": "No execution packet."}
            decision = (evaluate_decision_rule(metrics, exp.decision_rule) if state == TestState.OBSERVED
                        else {"status": HypothesisStatus.INCONCLUSIVE.value,
                              "reason": f"{state.value}; no observed result may be treated as pass/fail."})
            final = _integrity_gate(_baseline_gate(metrics, decision, execution, domain), holdout, local_bias, execution)
            h.status, h.status_reason = HypothesisStatus(final["status"]), final["reason"]
            metric_name = text(execution.get("primary_metric"), text(proposal.get("primary_metric"), "score"))
            robustness = {
                "walk_forward": walk_forward_summary(execution.get("walk_forward_runs"), metric_name) if execution else {"status": UNKNOWN},
                "regimes": regime_summary(execution.get("regime_runs"), metric_name) if execution else {"status": UNKNOWN},
                "parameter_stability": parameter_stability(execution.get("parameter_grid"), metric=metric_name,
                                                           tolerance=execution.get("stability_tolerance"),
                                                           maximize=bool(execution.get("maximize_metric", True))) if execution.get("parameter_grid") else {"status": UNKNOWN},
            }
            if domain == "trading" and execution.get("trades"):
                trades = execution.get("trades") or []
                robustness.update({
                    "monte_carlo": monte_carlo_trade_paths(trades, simulations=int(number(execution.get("monte_carlo_simulations")) or 5000),
                                                           starting_capital=execution.get("starting_capital"), ruin_floor=execution.get("ruin_floor")),
                    "trade_regimes": trading_regime_metrics(trades, unit=text(execution.get("unit"), UNKNOWN)),
                    "friction_stress": trading_friction_stress(trades, execution.get("friction_multipliers") or [], unit=text(execution.get("unit"), UNKNOWN)),
                })
                if execution.get("edge_decay_window"):
                    robustness["edge_decay"] = edge_decay_analysis(
                        trade_pnl_series(trades)["net"], window=int(number(execution.get("edge_decay_window")) or 0),
                        maximum_allowed_decay=execution.get("maximum_allowed_decay"))
            statistical = statistical_validation(execution) if execution else {}
            failure_values = execution.get("failure_values") if execution else None
            results.append({
                "hypothesis_id": h.hypothesis_id, "state": state.value, "metrics": metrics,
                "decision": final, "untouched_test_integrity": holdout, "bias_audit": local_bias,
                "statistical_validation": statistical, "robustness": robustness,
                "failure_distribution": failure_distribution(failure_values or [], catastrophic_threshold=execution.get("catastrophic_threshold"), worse_is_lower=bool(execution.get("worse_is_lower", True))) if failure_values is not None else {"status": UNKNOWN},
                "failure_clusters": failure_cluster_analysis(failure_values or [], failure_threshold=execution.get("failure_threshold"), worse_is_lower=bool(execution.get("worse_is_lower", True))) if failure_values is not None else {"status": UNKNOWN},
                "scope": h.scope,
                "scope_rule": "Failure/pass applies only to this exact tested claim and scope; no theory-wide generalization.",
            })

        first_execution = mapping(executions.get(hypotheses[0].hypothesis_id)) if hypotheses else {}
        trading = _trading_standard(proposal, first_execution) if domain == "trading" else {}
        ablation = (ablation_analysis(proposal.get("ablation_results"), metric=text(proposal.get("primary_metric"), "score"),
                                     full_name=text(proposal.get("full_model_name"), "full"),
                                     minimum_increment=proposal.get("minimum_ablation_increment"),
                                     maximize=bool(proposal.get("maximize_metric", True)))
                    if proposal.get("ablation_results") else {"status": UNKNOWN, "reason": "No ablation results supplied."})

        can_now = (["Recompute metrics, leakage checks, holdout receipts and supplied experiment/backtest statistics from existing observations."]
                   if proposal.get("data_available") or executions else
                   ["Finalize variables, baselines, falsification rules, sampling plan and analysis protocol before data collection."])
        if executions:
            can_now.append("Evaluate only TEST PERFORMED / RESULT OBSERVED packets; leave the rest untested.")
        cannot = []
        if not known(proposal.get("primary_metric")):
            cannot.append("Final quantitative promotion: primary metric is UNKNOWN / NOT TESTED.")
        if not proposal.get("decision_rule") and not any(mapping(e).get("decision_rule") for e in executions.values()):
            cannot.append("PASS/FAIL thresholding beyond validity failures: no caller-supplied decision rule exists.")
        if not executions:
            cannot.append("No real result is observed; performance/effect size/robustness cannot be claimed.")
        if domain == "trading" and not any(mapping(e).get("trades") for e in executions.values()):
            cannot.append("Trading metrics are UNKNOWN until a real trade ledger/backtest is supplied.")

        alerts = {
            "AI-1": ["Supply exact dataset/source provenance, measurement definitions, sample frame and external replication data needed for each claim."],
            "AI-3": ["For every mechanism, provide a prediction that differs from rival mechanisms; reformulate unclear causal arrows/parameters."],
            "AI-4": ["Stress-test leakage, repeated holdout use, sharp optima, catastrophic tails and any conclusion broader than tested scope."],
        }
        alerts["AI-1"] += [text(x) for x in listify(agents.get("evidence_needed")) if text(x)]
        alerts["AI-3"] += [text(x) for x in listify(agents.get("mechanism_ambiguities")) if text(x)]
        alerts["AI-4"] += [text(x) for x in listify(agents.get("red_team_objections")) if text(x)]

        completeness = [bool(question), bool(variables), bool(model), bool(baselines), bool(hypotheses), bool(experiments),
                        known(proposal.get("primary_metric")), known(proposal.get("dataset_sample")),
                        bool(executions), not bool(bias_global.get("fatal"))]
        confidence = min(round(100 * sum(completeness) / len(completeness)), 95)
        blockers = []
        if not known(proposal.get("primary_metric")): blockers.append("Primary metric not supplied.")
        if not known(proposal.get("dataset_sample")): blockers.append("Exact dataset/sample and sampling frame not supplied.")
        if not executions: blockers.append("No execution/results packet supplied; tests are plans, not observed evidence.")
        if bias_global.get("fatal"): blockers.append("Confirmed fatal leakage/bias invalidates dependent performance claims.")
        if not blockers and any(r["decision"]["status"] in ("INCONCLUSIVE", "CONDITIONAL PASS") for r in results):
            blockers.append("At least one important hypothesis is not fully decided/replicated.")
        if not blockers and results and all(r["decision"]["status"] == "PASS" for r in results):
            confidence = 95
            blockers.append("Independent external replication/real-world deployment evidence is still required before truth certainty.")

        return {
            "agent_id": self.agent_id, "phase": phase, "domain": domain, "question": question,
            "goal": text(proposal.get("goal"), question or UNKNOWN),
            "required_outcome": text(proposal.get("required_outcome"), "Determine whether the proposed claim/model is true/useful/robust under explicit measurable tests."),
            "measurability_limits": listify(proposal.get("measurability_limits")) or ["Unobserved constructs require operational definitions before testing."],
            "variables": [v.to_dict() for v in variables], "mathematical_model": model,
            "baselines": [b.to_dict() for b in baselines], "hypotheses": [h.to_dict() for h in hypotheses],
            "experiments": [e.to_dict() for e in experiments], "results": results,
            "predictive_validation_plan": _predictive_plan(domain), "statistical_validation_plan": _statistical_plan(),
            "bias_leakage": bias_global,
            "robustness_plan": [
                "Nearby parameter values with caller-supplied tolerance; report full surface, not only best point.",
                "Different time periods/sites/datasets and temporal/external replication.",
                "Alternative defensible variable/label definitions.",
                "Noise/measurement perturbation and reduced-data/subsample checks.",
                "Regime/stratum-specific results and interaction checks.",
                "No retuning on the untouched final test set.",
            ],
            "ablation": ablation,
            "ablation_plan": ["Compare full system with each component-removed variant on identical splits/metric/friction.",
                              "Use caller-supplied incremental-value/equivalence criterion; otherwise report increments without verdict.",
                              "Recommend REMOVAL only when the component fails the prespecified incremental-value requirement."],
            "real_world_friction": _friction(domain, proposal),
            "failure_modes": ["Average metric hides clustered/tail failures.", "Regime/distribution shift.",
                              "Measurement/implementation error overwhelms effect.", "Sharp one-point optimum/overfitting.",
                              "Unfairly weak baseline.", "Leakage/repeated final-set tuning invalidates evaluation.",
                              "Catastrophic limit unspecified, making average success insufficient for deployment."],
            "trading_specific_standard": trading,
            "what_can_be_tested_now": can_now, "what_cannot_yet_be_tested": cannot,
            "cross_agent_alerts": alerts,
            "second_pass_tasks": _second_pass_tasks({"hypotheses": [h.to_dict() for h in hypotheses]}, agents),
            "confidence": confidence,
            "confidence_meaning": "Confidence that the VALIDATION PLAN/PACKET is complete enough to guide testing; not probability the theory is true.",
            "higher_score_blockers": blockers,
        }

    def second_pass(self, question: str, prior_packet: Mapping[str, Any],
                    agent_outputs: Mapping[str, Any],
                    execution_packets: Optional[Mapping[str, Mapping[str, Any]]] = None) -> Dict[str, Any]:
        prior = dict(mapping(prior_packet))
        first_exp = mapping((prior.get("experiments") or [{}])[0])
        proposal = {"domain": prior.get("domain"), "goal": prior.get("goal"),
                    "required_outcome": prior.get("required_outcome"), "variables": prior.get("variables"),
                    "baselines": prior.get("baselines"), "hypotheses": prior.get("hypotheses"),
                    "primary_metric": first_exp.get("metric"), "data_available": bool(execution_packets)}
        packet = self.analyze(question, proposal, execution_packets, agent_outputs, phase="second")
        packet["second_pass_continuity"] = {"restarted_from_zero": False,
                                             "prior_agent_id": prior.get("agent_id", UNKNOWN),
                                             "priority_rule": "Fatal validity threats -> rival discriminator -> untouched/external replication -> robustness -> ablation -> friction/tails."}
        packet["second_pass_tasks"] = _second_pass_tasks(prior, mapping(agent_outputs))
        return packet

    def render_packet(self, packet: Mapping[str, Any]) -> str:
        p, lines = mapping(packet), ["# AI-2 VALIDATION PACKET"]

        def section(title: str, rows: Iterable[str]):
            lines.append(f"\n## {title}")
            clean = [str(x) for x in rows if str(x).strip()]
            lines.extend(clean or [UNKNOWN])

        section(PACKET_HEADINGS[0], [f"Goal: {p.get('goal', UNKNOWN)}", f"Required outcome: {p.get('required_outcome', UNKNOWN)}",
                                     "Measurability limits: " + "; ".join(map(str, p.get("measurability_limits") or [UNKNOWN]))])
        section(PACKET_HEADINGS[1], [f"- {v.get('symbol')}: {v.get('definition')} | unit={v.get('unit')} | role={v.get('role')} | interpretation={v.get('interpretation')} | value={v.get('value_status')}" for v in p.get("variables") or []])
        mm = mapping(p.get("mathematical_model"))
        section(PACKET_HEADINGS[2], [str(mm.get("equation", UNKNOWN)), "Objective: " + str(mm.get("objective", UNKNOWN)),
                                     *["Constraint: " + str(x) for x in mm.get("constraints") or []], str(mm.get("note", "")),
                                     "Unknown/to-estimate parameters: " + ", ".join(map(str, mm.get("unknown_parameters") or []))])
        section(PACKET_HEADINGS[3], [f"- {b.get('baseline_id')} {b.get('name')}: {b.get('reason')} | metric={b.get('metric')} | result={b.get('result')}" for b in p.get("baselines") or []])
        section(PACKET_HEADINGS[4], [f"- {h.get('hypothesis_id')} [{h.get('status')}]: {h.get('statement')} | mechanism={h.get('mechanism')} | prediction={h.get('prediction')} | falsification={h.get('falsification_condition')} | reason={h.get('status_reason')}" for h in p.get("hypotheses") or []])
        experiment_rows = []
        for e in p.get("experiments") or []:
            experiment_rows.append(
                f"### {e.get('test_id')} — {e.get('state')}\nHypothesis: {e.get('hypothesis')}\nVariables: {', '.join(e.get('variables') or [])}\nDataset/sample: {e.get('dataset_sample')}\nExperimental setup: {e.get('experimental_setup')}\nPrediction: {e.get('prediction')}\nNull hypothesis: {e.get('null_hypothesis')}\nMetric: {e.get('metric')}\nBaseline: {e.get('baseline')}\nConfounders: {'; '.join(e.get('confounders') or [])}\nFalsification condition: {e.get('falsification_condition')}\nReplication: {e.get('replication_method')}")
        experiment_rows += ["Predictive validation — " + k + ": " + str(v) for k, v in mapping(p.get("predictive_validation_plan")).items()]
        experiment_rows += ["Statistical validation — " + str(x) for x in p.get("statistical_validation_plan") or []]
        section(PACKET_HEADINGS[5], experiment_rows)
        bias = mapping(p.get("bias_leakage"))
        section(PACKET_HEADINGS[6], [f"Audit status: {bias.get('status', UNKNOWN)}",
                                     *[f"- {r.get('severity')}: {r.get('risk')} — {r.get('detail')}" for r in bias.get("findings") or []],
                                     "Not yet assessed: " + ", ".join(bias.get("not_assessed") or [])])
        section(PACKET_HEADINGS[7], [f"- {x}" for x in p.get("robustness_plan") or []])
        section(PACKET_HEADINGS[8], [*[f"- {x}" for x in p.get("ablation_plan") or []], f"Current ablation result: {mapping(p.get('ablation')).get('status', UNKNOWN)}"])
        section(PACKET_HEADINGS[9], [f"- {x}" for x in p.get("real_world_friction") or []])
        section(PACKET_HEADINGS[10], [f"- {x}" for x in p.get("failure_modes") or []])
        section(PACKET_HEADINGS[11], [f"- {x}" for x in p.get("what_can_be_tested_now") or []])
        section(PACKET_HEADINGS[12], [f"- {x}" for x in p.get("what_cannot_yet_be_tested") or []])
        alerts = mapping(p.get("cross_agent_alerts"))
        section(PACKET_HEADINGS[13], ["## CROSS-AGENT ALERT — AI-1", *[f"- {x}" for x in alerts.get("AI-1") or []],
                                      "## CROSS-AGENT ALERT — AI-3", *[f"- {x}" for x in alerts.get("AI-3") or []],
                                      "## CROSS-AGENT ALERT — AI-4", *[f"- {x}" for x in alerts.get("AI-4") or []]])
        section(PACKET_HEADINGS[14], [f"- P{t.get('priority')}: {t.get('task')} Why: {t.get('why')}" for t in p.get("second_pass_tasks") or []])
        section(PACKET_HEADINGS[15], [f"{p.get('confidence', 0)}/100", str(p.get("confidence_meaning", ""))])
        section(PACKET_HEADINGS[16], [f"- {x}" for x in p.get("higher_score_blockers") or []])
        return "\n".join(lines).strip() + "\n"


VALIDATION_DIRECTOR_CONTRACT = """
AI-2 / VALIDATION-DIRECTOR converts claims into measurable variables,
mathematical models, baselines, falsifiable experiments, train/validation/
untouched-test discipline, statistics, robustness, ablation, leakage/bias audits,
real-world friction and failure distributions. Trading metrics are reported only
when actually tested. Hypothesis status is PASS / CONDITIONAL PASS / INCONCLUSIVE
/ FAIL. TEST PROPOSED / TEST POSSIBLE / TEST PERFORMED / RESULT OBSERVED are never
blurred. Unknowns remain UNKNOWN / NOT TESTED or TO BE ESTIMATED. One failed test
rejects only the exact tested claim. Second-pass validation continues from prior
packets and prioritizes highest-information-gain tests.
""".strip()


__all__ = [
    "UNKNOWN", "TO_ESTIMATE", "HypothesisStatus", "TestState", "VariableRole",
    "VariableSpec", "BaselineSpec", "HypothesisSpec", "ExperimentSpec",
    "bootstrap_mean_ci", "bootstrap_difference_ci", "mean_difference_effect",
    "permutation_mean_difference", "benjamini_hochberg", "two_sample_power_n",
    "beta_binomial_posterior", "classification_metrics", "regression_metrics",
    "seal_holdout", "audit_holdout", "walk_forward_summary", "regime_summary",
    "trade_pnl_series", "trading_metrics", "trading_regime_metrics",
    "trading_friction_stress", "edge_decay_analysis", "monte_carlo_trade_paths",
    "parameter_stability", "ablation_analysis", "failure_distribution",
    "failure_cluster_analysis", "leakage_bias_audit", "evaluate_decision_rule",
    "QuantitativeValidationDirector", "VALIDATION_DIRECTOR_CONTRACT", "PACKET_HEADINGS",
]
