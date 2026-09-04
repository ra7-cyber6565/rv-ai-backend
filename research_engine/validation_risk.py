"""Robustness, bias, friction and second-pass logic for AI-2."""
from __future__ import annotations
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Sequence
from .validation_contracts import (
    BIAS_RISKS, FAILURE_DIMENSIONS, FRICTION_FACTORS, INCONCLUSIVE, NOT_TESTED,
    ROBUSTNESS_DIMENSIONS, TEST_POSSIBLE, TEST_PROPOSED, TO_BE_ESTIMATED,
    UNKNOWN, as_list, first, meaningful, second_pass_summary, text,
)


def meta_hypotheses(trading: bool) -> List[Dict[str, Any]]:
    rows = [
        {"hypothesis_id": "AI2-H1-BASELINE-EDGE", "hypothesis_status": INCONCLUSIVE, "test_state": TEST_PROPOSED,
         "mechanism": "Useful complexity must add reproducible out-of-sample value beyond the simplest valid baseline.",
         "variables": [
             {"name": "candidate performance", "symbol": UNKNOWN, "role": "dependent", "unit": "domain metric",
              "definition": "Locked primary outcome achieved by the candidate method.", "interpretation": "candidate primary outcome"},
             {"name": "baseline performance", "symbol": UNKNOWN, "role": "control", "unit": "same domain metric",
              "definition": "Same locked primary outcome achieved by the simplest valid baseline.", "interpretation": "baseline primary outcome"}],
         "prediction": "Candidate materially outperforms baseline on untouched data.",
         "test": "Lock metric, baseline, data split and analysis; compare on untouched data with uncertainty.",
         "falsification": "No credible incremental value or advantage reverses on untouched/external data.",
         "baseline": "Simplest valid domain baseline; exact choice TO BE ESTIMATED from task semantics."},
        {"hypothesis_id": "AI2-H2-STABILITY", "hypothesis_status": INCONCLUSIVE, "test_state": TEST_PROPOSED,
         "mechanism": "A real effect should occupy a stable neighborhood, not one finely tuned parameter/time/definition point.",
         "variables": [
             {"name": "performance across perturbations", "symbol": UNKNOWN, "role": "dependent", "unit": "domain metric",
              "definition": "Locked outcome measured under pre-specified parameter/time/definition/noise/regime changes.",
              "interpretation": "robustness surface"}],
         "prediction": "Direction and practical magnitude survive reasonable pre-specified perturbations.",
         "test": "Evaluate parameter, temporal, definition, noise, reduced-data, assumption and regime perturbations without final-set retuning.",
         "falsification": "Effect exists only at a sharp optimum or collapses/reverses under reasonable perturbations.",
         "baseline": "Locked nominal candidate and same simple baseline across perturbations."},
        {"hypothesis_id": "AI2-H3-REAL-WORLD-SURVIVAL", "hypothesis_status": INCONCLUSIVE, "test_state": TEST_PROPOSED,
         "mechanism": "Laboratory or simulation value must survive deployment friction and failure tails.",
         "variables": [
             {"name": "net deployment outcome", "symbol": UNKNOWN, "role": "dependent", "unit": "domain outcome",
              "definition": "Outcome after materially relevant costs, implementation errors and deployment constraints.",
              "interpretation": "net real-world utility"},
             {"name": "failure severity", "symbol": UNKNOWN, "role": "uncertainty", "unit": "domain loss/harm",
              "definition": "Magnitude of adverse outcomes including tail events.", "interpretation": "failure-tail severity"}],
         "prediction": "Net value remains useful under realistic friction/stress with acceptable failure severity.",
         "test": "Evaluate costs/errors, tails, clustered failures and worst credible scenarios; replicate in a deployment-like environment.",
         "falsification": "Realistic friction erases value or plausible tail failure becomes unacceptable.",
         "baseline": "Current standard practice under same friction/stress assumptions."},
    ]
    if trading:
        rows[2]["mechanism"] = "A gross market-model edge is not deployable unless net expectancy and tails survive realistic execution friction."
        rows[2]["prediction"] = "Net out-of-sample expectancy stays positive without unacceptable drawdown or ruin risk after realistic friction."
    return rows


def _normalized_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _bias_candidate(evidence: Mapping[str, Any], risk: str) -> Any:
    normalized = {_normalized_key(key): value for key, value in evidence.items()}
    candidates = [risk]
    if risk == "hidden target leakage":
        candidates += ["target leakage", "target_leakage"]
    for candidate in candidates:
        key = _normalized_key(candidate)
        if key in normalized:
            return normalized[key]
    return None


def bias_audit(result: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw = result.get("bias_audit") or result.get("leakage_audit")
    evidence = raw if isinstance(raw, Mapping) else {}
    rows = []
    for risk in BIAS_RISKS:
        candidate = _bias_candidate(evidence, risk)
        provenance: Any = {}
        if isinstance(candidate, Mapping):
            status = text(first(candidate, "status", "state"), NOT_TESTED)
            detail = text(first(candidate, "detail", "evidence", "note"))
            raw_provenance = candidate.get("provenance") or candidate.get("result_provenance")
            provenance = deepcopy(raw_provenance) if isinstance(raw_provenance, Mapping) else {}
        elif meaningful(candidate):
            status = text(candidate); detail = UNKNOWN
        else:
            status = NOT_TESTED; detail = UNKNOWN
        rows.append({"risk": risk, "status": status, "evidence": detail,
                     "provenance": provenance, "action_if_found": "INVALIDATE_OR_DOWNGRADE"})
    return rows


def robustness_plan() -> List[Dict[str, Any]]:
    return [{"dimension": d, "state": TEST_PROPOSED,
             "acceptance_rule": "Pre-specify practical stability criterion before final results; threshold TO BE ESTIMATED.",
             "warning": "Single sharp optimum is suspicious; prefer a stable performance region."} for d in ROBUSTNESS_DIMENSIONS]


def ablation_plan(hypotheses: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    components: List[str] = []
    for h in hypotheses:
        for item in as_list(first(h, "components", "model_components", "features")):
            name = text(item, "")
            if name and name not in components: components.append(name)
    if not components:
        return {"components": [UNKNOWN], "state": TEST_PROPOSED,
                "design": "Identify components, then leave-one-out and pre-specified interaction ablations.",
                "decision_rule": "Recommend REMOVAL when a component adds no reproducible incremental value after uncertainty and complexity cost.",
                "combinatorial_warning": "Do not data-mine every subset on final data; use pre-specification or nested validation."}
    return {"components": components, "state": TEST_PROPOSED,
            "leave_one_out_tests": [f"All locked components except: {c}" for c in components],
            "decision_rule": "Recommend REMOVAL when exclusion does not materially weaken validated performance.",
            "interaction_rule": "Test higher-order combinations only with mechanism or nested-validation justification."}


def friction_plan(trading: bool, result: Mapping[str, Any] | None = None) -> List[Dict[str, Any]]:
    trading_relevant = {"transaction costs", "slippage", "latency", "liquidity", "taxes", "regulation"}
    supplied = {}
    if isinstance(result, Mapping):
        raw = result.get("friction_audit") or result.get("real_world_friction")
        if isinstance(raw, Mapping):
            supplied = raw
    normalized_supplied = {_normalized_key(key): value for key, value in supplied.items()}
    rows: List[Dict[str, Any]] = []
    for factor in FRICTION_FACTORS:
        candidate = normalized_supplied.get(_normalized_key(factor))
        value: Any = TO_BE_ESTIMATED
        tested = False
        provenance: Any = {}
        relevance = "RELEVANT" if trading and factor in trading_relevant else UNKNOWN
        if isinstance(candidate, Mapping):
            if meaningful(candidate.get("value")):
                value = deepcopy(candidate.get("value"))
            tested = candidate.get("tested") is True
            if meaningful(candidate.get("relevance")):
                relevance = text(candidate.get("relevance"))
            raw_provenance = candidate.get("provenance") or candidate.get("source")
            provenance = deepcopy(raw_provenance) if isinstance(raw_provenance, Mapping) else raw_provenance or {}
        elif meaningful(candidate):
            value = deepcopy(candidate)
        rows.append({"factor": factor, "relevance": relevance, "value": value,
                     "tested": tested, "provenance": provenance,
                     "rule": "Measure or source materially applicable values; never assume convenient values."})
    return rows


def failure_plan() -> List[Dict[str, Any]]:
    return [{"dimension": d, "state": TEST_PROPOSED, "observed_result": NOT_TESTED,
             "required_method": "Monte Carlo only with defensible distribution/dependence assumptions." if d == "Monte Carlo failure distribution"
             else "Stress, scenario and tail analysis with uncertainty; preserve event order where clustering matters."} for d in FAILURE_DIMENSIONS]


def cross_agent_alerts(experiments: Sequence[Mapping[str, Any]], trading: bool) -> Dict[str, List[str]]:
    missing = sorted({f for e in experiments for f in e.get("missing_required_fields", [])})
    ai1 = ["Provide primary/independent evidence for measurement validity, dataset provenance, baseline choice and friction values.",
           "Provide external/temporal replication evidence and distinguish raw/real-time from revised data."]
    if missing: ai1.append("Missing quantitative evidence fields: " + ", ".join(missing) + ".")
    if trading: ai1.append("Provide exact instrument/feed mapping, cross-market basis, historical execution costs/latency and session data sources.")
    return {"CROSS-AGENT ALERT — AI-1": ai1,
            "CROSS-AGENT ALERT — AI-3": ["Make causal mechanism explicit enough to identify independent/dependent/control/mediator/confounder/state variables.",
                "Reformulate claims lacking directional prediction, null or precise falsification.", "Use math only when symbols map to measurable quantities."],
            "CROSS-AGENT ALERT — AI-4": ["Attack leakage, multiple testing, researcher degrees of freedom, sharp optima and final-set retuning.",
                "Challenge catastrophic tails and whether deployment friction reverses conclusions.",
                "Ensure a failed narrow experiment rejects only the tested claim, not a whole theory family."]}


def second_pass_tasks(experiments: Sequence[Mapping[str, Any]], trading: bool, outputs: Any = None) -> List[Dict[str, Any]]:
    tasks = []; summary = second_pass_summary(outputs)
    def add(task: str, why: str, state: str = TEST_PROPOSED) -> None:
        tasks.append({"priority": len(tasks) + 1, "task": task, "information_gain_reason": why, "state": state})
    if summary["present"]:
        add("Triangulate strongest structured hypotheses/claims from received agents and select the smallest safe discriminating test.",
            "Second pass should resolve disagreements/merged-model uncertainty rather than repeat first pass.", TEST_POSSIBLE)
        if summary["red_team_input_present"]:
            add("Convert AI-4/red-team objections into explicit falsification, leakage, stress or catastrophic-failure tests; prioritize highest-consequence checks.",
                "A credible red-team objection can invalidate deployment despite attractive average performance.", TEST_POSSIBLE)
    if any(not e.get("contract_complete") for e in experiments):
        add("Close experiment-contract gaps for strongest/disputed hypotheses before expensive testing.",
            "Undefined metric/baseline/sample/falsification prevents clean discrimination.", TEST_POSSIBLE)
    add("Choose the cheapest safe experiment that most separates surviving hypotheses; use Bayesian priors/likelihoods only if actually supplied.",
        "Prefer discriminating over confirmatory evidence; never invent Bayesian inputs.")
    add("Lock analysis, baseline, primary metric and untouched test set; evaluate final out-of-sample performance without tuning it.",
        "Separates discovery/tuning performance from generalization.")
    add("Evaluate parameter neighborhoods, regimes, definitions and realistic friction; map failure distribution and tails.",
        "Distinguishes robust effects from brittle optimized stories.")
    if trading:
        add("Validate market-model performance with cost-aware walk-forward analysis and dependence-aware Monte Carlo where justified.",
            "Tests whether apparent gross edge survives execution friction and temporal instability.")
    return tasks
