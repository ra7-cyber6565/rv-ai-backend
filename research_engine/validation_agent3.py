"""
Agent 3 — Quantitative Testing, Validation, Practical Implementation Engine.

Consumes the original question, Agent 1 research packet, Agent 2 hypothesis
packet, and optional *actual* execution packets. Planning is never reported as
execution. Missing data/metrics remain ``NOT TESTED / UNKNOWN``.

The engine is deterministic, network-free and model-free. It builds test
matrices, audits leakage/bias/splits, runs quantitative checks when observations
are supplied, evaluates trading ledgers with friction, checks robustness and
ablations, and emits the exact 14-section handoff packet for Agent 4.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

UNKNOWN = "NOT TESTED / UNKNOWN"
MISSING = "UNSPECIFIED — must be supplied"


class FinalStatus(str, Enum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL PASS"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAIL = "FAIL"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class AuditFinding:
    check: str
    status: str
    severity: Severity
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        row = asdict(self)
        row["severity"] = self.severity.value
        return row


@dataclass
class TestMatrix:
    hypothesis_id: str
    statement: str
    domain: str
    exact_dataset: str
    dataset_source: str
    unit_of_analysis: str
    variables: Dict[str, Any]
    timeframe: str
    exact_test: str
    baseline: List[str]
    null_hypothesis: str
    falsification_rule: str
    metrics: List[str]
    sample_requirements: List[str]
    confounders: List[str]
    leakage_controls: List[str]
    split_plan: Dict[str, Any]
    robustness_plan: List[str]
    ablation_plan: List[str]
    statistical_plan: List[str]
    friction_plan: List[str]
    failure_modes: List[Dict[str, str]]
    implementation_steps: List[str]
    blockers: List[str] = field(default_factory=list)

    @property
    def executable(self) -> bool:
        required = (
            self.exact_dataset, self.timeframe, self.exact_test,
            self.null_hypothesis, self.falsification_rule,
        )
        return not self.blockers and all(
            value and not value.startswith("UNSPECIFIED") for value in required
        )

    def to_dict(self) -> Dict[str, Any]:
        row = asdict(self)
        row["executable"] = self.executable
        return row


@dataclass
class QuantitativeResult:
    executed: bool = False
    dataset: str = ""
    sample_size: int = 0
    metrics: Dict[str, Any] = field(default_factory=dict)
    baseline_results: Dict[str, Any] = field(default_factory=dict)
    statistical_tests: Dict[str, Any] = field(default_factory=dict)
    robustness: Dict[str, Any] = field(default_factory=dict)
    ablations: Dict[str, Any] = field(default_factory=dict)
    friction: Dict[str, Any] = field(default_factory=dict)
    failure_modes: List[Dict[str, Any]] = field(default_factory=list)
    split_audit: List[AuditFinding] = field(default_factory=list)
    bias_audit: List[AuditFinding] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        row = asdict(self)
        row["split_audit"] = [x.to_dict() for x in self.split_audit]
        row["bias_audit"] = [x.to_dict() for x in self.bias_audit]
        return row


@dataclass
class HypothesisValidation:
    hypothesis_id: str
    statement: str
    status: FinalStatus
    reason: str
    test_matrix: TestMatrix
    result: QuantitativeResult
    surviving_candidate: bool
    confidence_note: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "statement": self.statement,
            "status": self.status.value,
            "reason": self.reason,
            "test_matrix": self.test_matrix.to_dict(),
            "result": self.result.to_dict(),
            "surviving_candidate": self.surviving_candidate,
            "confidence_note": self.confidence_note,
        }


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _first(*values: Any, default: str = "") -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return default


def _unique(values: Iterable[Any]) -> List[str]:
    out: List[str] = []
    for value in values:
        text = _text(value)
        if text and text not in out:
            out.append(text)
    return out


def _numbers(values: Iterable[Any]) -> List[float]:
    out: List[float] = []
    for value in values:
        try:
            x = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(x):
            out.append(x)
    return out


def _percentile(values: Sequence[float], q: float) -> Optional[float]:
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * min(1.0, max(0.0, float(q)))
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    weight = pos - lo
    return xs[lo] * (1 - weight) + xs[hi] * weight


def bootstrap_mean_ci(
    values: Sequence[float], *, confidence: float = 0.95,
    iterations: int = 2000, seed: int = 1729,
) -> Dict[str, Any]:
    xs = _numbers(values)
    if len(xs) < 2:
        return {"status": UNKNOWN, "reason": "bootstrap ke liye >=2 observations chahiye"}
    iterations = max(200, min(20000, int(iterations)))
    rng, n = random.Random(seed), len(xs)
    means = [statistics.fmean(xs[rng.randrange(n)] for _ in range(n)) for _ in range(iterations)]
    alpha = 1.0 - min(0.999, max(0.50, confidence))
    return {
        "status": "TESTED", "mean": statistics.fmean(xs), "confidence": confidence,
        "low": _percentile(means, alpha / 2), "high": _percentile(means, 1 - alpha / 2),
        "iterations": iterations, "n": n, "seed": seed,
    }


def permutation_mean_difference(
    treatment: Sequence[float], control: Sequence[float], *,
    iterations: int = 5000, seed: int = 2718,
) -> Dict[str, Any]:
    a, b = _numbers(treatment), _numbers(control)
    if len(a) < 2 or len(b) < 2:
        return {"status": UNKNOWN, "reason": "har group me >=2 observations chahiye"}
    observed, combined, n_a = statistics.fmean(a) - statistics.fmean(b), a + b, len(a)
    iterations, rng, extreme = max(200, min(50000, int(iterations))), random.Random(seed), 0
    for _ in range(iterations):
        sample = combined[:]
        rng.shuffle(sample)
        delta = statistics.fmean(sample[:n_a]) - statistics.fmean(sample[n_a:])
        if abs(delta) >= abs(observed) - 1e-15:
            extreme += 1
    return {
        "status": "TESTED", "mean_difference": observed,
        "p_value_two_sided": (extreme + 1) / (iterations + 1),
        "iterations": iterations, "n_treatment": len(a), "n_control": len(b), "seed": seed,
    }


def benjamini_hochberg(p_values: Sequence[float], alpha: float = 0.05) -> Dict[str, Any]:
    valid: List[Tuple[int, float]] = []
    for index, value in enumerate(p_values):
        try:
            p = float(value)
        except (TypeError, ValueError):
            continue
        if 0.0 <= p <= 1.0 and math.isfinite(p):
            valid.append((index, p))
    if not valid:
        return {"status": UNKNOWN, "reason": "valid p-values nahi mile", "reject": []}
    ordered, m, max_rank = sorted(valid, key=lambda row: row[1]), len(valid), 0
    for rank, (_, p) in enumerate(ordered, 1):
        if p <= alpha * rank / m:
            max_rank = rank
    rejected = sorted(index for index, _ in ordered[:max_rank])
    return {
        "status": "TESTED", "method": "Benjamini-Hochberg FDR", "alpha": alpha,
        "tests": m, "rejected_indexes": rejected,
        "reject": [i in rejected for i in range(len(p_values))],
    }


def seal_holdout(values: Any) -> str:
    payload = json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _extract_hypotheses(packet: Any) -> List[Mapping[str, Any]]:
    if isinstance(packet, list):
        return [x for x in packet if isinstance(x, Mapping)]
    packet = _map(packet)
    for key in ("hypotheses", "surviving_hypotheses", "candidates", "items"):
        if isinstance(packet.get(key), list):
            return [x for x in packet[key] if isinstance(x, Mapping)]
    if packet and any(k in packet for k in ("statement", "hypothesis", "claim")):
        return [packet]
    return []


def _hypothesis_id(h: Mapping[str, Any], index: int) -> str:
    explicit = _first(h.get("hypothesis_id"), h.get("id"), h.get("stable_id"))
    if explicit:
        return explicit
    statement = _first(h.get("statement"), h.get("hypothesis"), h.get("claim"), default=f"hypothesis-{index}")
    return f"AG3-H{index}-{hashlib.sha256(statement.encode('utf-8')).hexdigest()[:10]}"


def _infer_domain(question: str, h: Mapping[str, Any], research: Mapping[str, Any]) -> str:
    explicit = _first(h.get("domain"), research.get("domain"))
    if explicit:
        return explicit.lower()
    text = " ".join((_text(question), _text(h.get("statement")), _text(h.get("reasoning")))).lower()
    groups = (
        ("trading", ("trading", "trade", "xauusd", "us100", "nas100", "forex", "entry", "stop loss", "take profit")),
        ("medicine", ("patient", "clinical", "drug", "treatment", "disease", "therapy")),
        ("engineering", ("engineering", "motor", "circuit", "thermal", "hardware", "manufactur", "tolerance")),
        ("business", ("business", "revenue", "churn", "customer acquisition", "cac", "ltv", "tax")),
        ("predictive_modeling", ("machine learning", "classifier", "regression", "model accuracy", "neural", "prediction")),
    )
    for name, terms in groups:
        if any(term in text for term in terms):
            return name
    return "general"


def _dataset(h: Mapping[str, Any], research: Mapping[str, Any], execution: Mapping[str, Any]) -> Tuple[str, str]:
    plan = _map(h.get("test_plan"))
    name = _first(execution.get("dataset_name"), execution.get("dataset"), h.get("dataset"), plan.get("dataset"))
    source = _first(execution.get("dataset_source"), h.get("dataset_source"), plan.get("dataset_source"))
    datasets = research.get("datasets")
    if not name and isinstance(datasets, list) and len(datasets) == 1:
        item = datasets[0]
        if isinstance(item, Mapping):
            name = _first(item.get("name"), item.get("title"), item.get("dataset"))
            source = _first(source, item.get("url"), item.get("source"))
        else:
            name = _text(item)
    return name or MISSING, source or MISSING


def _prediction(h: Mapping[str, Any]) -> Mapping[str, Any]:
    return _map(h.get("prediction"))


def _baseline(domain: str, h: Mapping[str, Any]) -> List[str]:
    supplied = _unique(_list(h.get("baselines") or h.get("baseline")))
    if supplied:
        return supplied
    if domain == "trading":
        return ["No-trade / zero-return baseline after identical costs", "Random-entry baseline with identical holding/risk rules", "Simplest naive rule using same instrument/feed"]
    if domain == "predictive_modeling":
        return ["Naive constant/majority baseline", "Simple linear/logistic model where appropriate", "Standard benchmark supplied by research packet"]
    if domain == "medicine":
        return ["Control/placebo/usual-care comparator", "Pre-specified standard-of-care benchmark where appropriate"]
    if domain == "engineering":
        return ["Current standard design/process", "Simplest design without proposed component/mechanism"]
    if domain == "business":
        return ["Business-as-usual process", "Simple heuristic with identical cost accounting"]
    return ["Null/no-effect baseline", "Simplest reasonable alternative on same outcome"]


def _metrics(domain: str, h: Mapping[str, Any]) -> List[str]:
    supplied = _unique(_list(h.get("metrics") or _map(h.get("test_plan")).get("metrics")))
    if supplied:
        return supplied
    if domain == "trading":
        return ["net expectancy", "profit factor", "win rate", "average win/loss", "max drawdown", "total net P&L", "out-of-sample performance", "Monte-Carlo drawdown/failure probability"]
    if domain == "predictive_modeling":
        return ["primary pre-specified task metric", "error/effect magnitude", "confidence interval", "untouched-test performance", "baseline delta"]
    return ["pre-specified primary outcome", "effect size", "confidence interval", "baseline/control difference", "robustness across plausible conditions"]


def _frictions(domain: str, h: Mapping[str, Any]) -> List[str]:
    supplied = _unique(_list(h.get("frictions") or h.get("real_world_friction")))
    if supplied:
        return supplied
    return {
        "trading": ["spread", "commission", "slippage", "latency", "news slippage", "feed/execution differences"],
        "engineering": ["manufacturing tolerances", "heat/thermal drift", "failure rate", "hardware limits", "manufacturing cost"],
        "business": ["taxes", "customer acquisition cost", "churn", "operational friction", "capacity constraints"],
        "medicine": ["adherence", "dropout", "site variability", "adverse events", "implementation fidelity"],
    }.get(domain, ["deployment/measurement cost", "missingness", "implementation variability", "real operating constraints"])


def _failure_modes(domain: str) -> List[Dict[str, str]]:
    rows = [
        ("normal failure", "primary metric crosses failure boundary", "continuous metric/quality monitoring", "stop or revert to baseline"),
        ("rare failure", "tail event outside normal envelope", "tail-percentile / rare-event log", "stress-test and add guardrail"),
        ("catastrophic failure", "safety/capital/system-loss threshold breached", "hard safety threshold", "fail closed; immediate shutdown/reversion"),
        ("regime failure", "performance changes materially across regime/time/site", "stratified + rolling evaluation", "regime gate or reject generalization"),
        ("adversarial failure", "input/manipulation targets weakness", "red-team/adversarial cases", "sanitize/constrain/reject vulnerable path"),
        ("implementation failure", "deployed implementation diverges from validated spec", "golden tests + parity telemetry", "rollback and repair implementation"),
        ("assumption failure", "required causal/measurement assumption is false", "assumption-specific diagnostic", "downgrade inference or redesign test"),
    ]
    if domain == "trading":
        rows += [
            ("execution failure", "fill/slippage/latency makes net expectancy non-positive", "signal-vs-fill audit", "tighten filter or reject edge"),
            ("liquidity/news failure", "costs gap during news/thin liquidity", "spread/slippage tail monitor", "news/liquidity exclusion or lower size"),
        ]
    if domain == "engineering":
        rows.append(("tolerance/thermal failure", "performance collapses under tolerance/heat", "corner/thermal sweep", "redesign margin or reject"))
    return [{"mode": m, "failure_signal": s, "detection": d, "mitigation": x} for m, s, d, x in rows]


def _implementation(domain: str) -> List[str]:
    if domain == "trading":
        return [
            "Step 1 — exact instrument/feed aur raw historical data choose karke freeze karo.",
            "Step 2 — train, validation aur untouched chronological test windows lock karo.",
            "Step 3 — spread, commission, slippage, latency/news rules backtest me enter karo.",
            "Step 4 — no-trade/random/naive baselines ko same costs/risk rules par run karo.",
            "Step 5 — candidate long/short rules ko test window dekhe bina fit/select karo.",
            "Step 6 — untouched test par ek final evaluation; wapas us par optimize mat karo.",
            "Step 7 — walk-forward, Monte Carlo, regimes, nearby parameters aur ablations run karo.",
            "Step 8 — net edge/baseline/robustness/drawdown rule fail ho to reject/downgrade karo.",
        ]
    return [
        "Step 1 — exact dataset/sample, inclusion criteria aur measurement protocol freeze karo.",
        "Step 2 — primary outcome, null, baseline aur falsification boundary pre-register karo.",
        "Step 3 — train/validation/test ya control/treatment split contamination se pehle lock karo.",
        "Step 4 — baseline/simplest reasonable model pehle run karo.",
        "Step 5 — candidate test run karke raw observations + all exclusions log karo.",
        "Step 6 — effect size + uncertainty + robustness + sensitivity + ablation run karo.",
        "Step 7 — confounder/leakage/multiple-testing/friction audit complete karo.",
        "Step 8 — failure boundary hit ho to sirf tested scope tak hypothesis/model reject karo.",
    ]


def build_test_matrix(question: str, research_packet: Mapping[str, Any], hypothesis: Mapping[str, Any], execution: Optional[Mapping[str, Any]] = None, *, index: int = 1) -> TestMatrix:
    execution, research_packet = _map(execution), _map(research_packet)
    hid = _hypothesis_id(hypothesis, index)
    statement = _first(hypothesis.get("statement"), hypothesis.get("hypothesis"), hypothesis.get("claim"), default="UNSPECIFIED hypothesis statement")
    domain = _infer_domain(question, hypothesis, research_packet)
    dataset, dataset_source = _dataset(hypothesis, research_packet, execution)
    pred, plan = _prediction(hypothesis), _map(hypothesis.get("test_plan"))
    timeframe = _first(execution.get("timeframe"), hypothesis.get("timeframe"), plan.get("timeframe"), pred.get("timeframe"), research_packet.get("timeframe"), default=MISSING)
    exact_test = _first(execution.get("test_name"), plan.get("test"), hypothesis.get("required_experiment"), hypothesis.get("experimental_plan"), hypothesis.get("how_to_test"), pred.get("measurement_method"), default=MISSING)
    falsification = _first(hypothesis.get("falsification_rule"), hypothesis.get("falsification_test"), pred.get("falsification_condition"), plan.get("falsification_rule"), default=MISSING)
    null = _first(hypothesis.get("null_hypothesis"), plan.get("null"), default=f"No pre-specified effect/advantage for: {statement}")
    variables = execution.get("variables") if isinstance(execution.get("variables"), Mapping) else pred.get("variables")
    if isinstance(variables, Mapping):
        variables = dict(variables)
    elif isinstance(variables, list):
        variables = {"declared_variables": variables}
    else:
        variables = {"independent": _first(hypothesis.get("independent_variable"), pred.get("independent_variable"), default=MISSING), "dependent": _first(hypothesis.get("dependent_variable"), pred.get("dependent_variable"), default=MISSING), "controls": _list(hypothesis.get("control_variables") or pred.get("controls"))}
    sample = _unique(_list(hypothesis.get("sample_requirements") or plan.get("sample_requirements") or research_packet.get("sample_requirements"))) or ["Power/sample-size requirement pre-specify before confirmatory execution.", "Independent units only; repeated observations handled explicitly."]
    confounders = _unique(_list(hypothesis.get("confounders")) + _list(hypothesis.get("assumptions")) + _list(research_packet.get("known_confounders"))) or ["No confounder list supplied — domain expert review required before causal interpretation."]
    leakage = ["No look-ahead/future-known variables", "No tuning on untouched test", "Fit preprocessing on training only", "Deduplicate entities/events across splits", "Use point-in-time/unrevised data where real decision had only point-in-time data", "Log all exclusions/variants for multiple-testing audit"]
    split = {"training": "discovery/model fitting only", "validation": "parameter/model selection only", "untouched_test": "final evaluation only; never optimize on it", "ordering": "chronological" if domain == "trading" else "domain-appropriate independent split", "extra": ["walk-forward", "rolling validation", "different regimes/time periods"] if domain == "trading" else ["replication / independent site or period where appropriate"]}
    if domain == "trading":
        leakage += ["Chronological split only", "Signal timestamp must precede fill timestamp", "No survivorship-biased universe", "Economic/corporate revisions must be point-in-time if used"]
    blockers = []
    for value, reason in ((dataset, "exact dataset missing"), (timeframe, "exact timeframe missing"), (exact_test, "exact test/measurement protocol missing"), (falsification, "pre-specified falsification rule missing")):
        if value == MISSING:
            blockers.append(reason)
    return TestMatrix(
        hid, statement, domain, dataset, dataset_source,
        _first(execution.get("unit_of_analysis"), hypothesis.get("unit_of_analysis"), default=MISSING),
        variables, timeframe, exact_test, _baseline(domain, hypothesis), null, falsification,
        _metrics(domain, hypothesis), sample, confounders, leakage, split,
        ["Nearby parameter/threshold neighborhood", "Different regimes/time/site", "Sensitivity to reasonable cleaning choices", "Replication or walk-forward", "Reject one magical threshold without stable neighborhood"],
        ["Remove each component one at a time", "Re-run same protocol", "If removal causes no material degradation, remove that component"],
        ["Effect size, not p-value alone", "Confidence interval/bootstrap", "Permutation/randomization where valid", "Multiple-testing correction", "Monte-Carlo/scenario sensitivity for tails"],
        _frictions(domain, hypothesis), _failure_modes(domain), _implementation(domain), blockers,
    )


def audit_split(meta: Mapping[str, Any], *, domain: str) -> List[AuditFinding]:
    split = _map(meta.get("split"))
    if not split:
        return [AuditFinding("data split recorded", "UNKNOWN", Severity.CRITICAL, "train/validation/untouched-test metadata supplied nahi hai")]
    train, validation, test = split.get("train"), split.get("validation"), split.get("test") or split.get("untouched_test")
    out = [AuditFinding("train/validation/test present", "PASS" if train and validation and test else "FAIL", Severity.INFO if train and validation and test else Severity.CRITICAL, "three splits declared" if train and validation and test else "required split missing")]
    touched_flag = meta.get("test_touched_for_tuning", split.get("test_touched_for_tuning"))
    touched = bool(touched_flag)
    out.append(AuditFinding("untouched test not used for tuning", "FAIL" if touched else ("PASS" if touched_flag is False else "UNKNOWN"), Severity.CRITICAL if touched else Severity.INFO, "test tuning me use hua" if touched else ("explicitly untouched" if touched_flag is False else "explicit untouched flag missing")))
    if domain == "trading":
        chronological = bool(split.get("chronological") or meta.get("chronological_split"))
        out.append(AuditFinding("chronological split", "PASS" if chronological else "FAIL", Severity.INFO if chronological else Severity.CRITICAL, "trading future leakage control"))
    before, after = _first(meta.get("holdout_seal_before"), split.get("holdout_seal_before")), _first(meta.get("holdout_seal_after"), split.get("holdout_seal_after"))
    if before or after:
        ok = bool(before and after and before == after)
        out.append(AuditFinding("holdout seal unchanged", "PASS" if ok else "FAIL", Severity.INFO if ok else Severity.CRITICAL, "holdout fingerprint same" if ok else "holdout fingerprint missing/changed"))
    else:
        out.append(AuditFinding("holdout seal unchanged", "UNKNOWN", Severity.WARNING, "holdout fingerprint not recorded"))
    return out


_BIASES = {"look_ahead": "look-ahead", "hindsight": "hindsight", "survivorship": "survivorship", "data_snooping": "data snooping", "cherry_picking": "cherry-picking", "publication_bias": "publication bias", "selection_bias": "selection bias", "p_hacking": "p-hacking", "hidden_leakage": "hidden leakage", "future_known_variables": "future-known variables", "revised_data": "revised data"}


def audit_bias(meta: Mapping[str, Any]) -> List[AuditFinding]:
    raw, out = _map(meta.get("bias_flags") or meta.get("bias_audit")), []
    for key, label in _BIASES.items():
        if key not in raw:
            out.append(AuditFinding(label, "UNKNOWN", Severity.WARNING, "explicit audit result supplied nahi"))
        else:
            bad = bool(raw.get(key))
            out.append(AuditFinding(label, "FAIL" if bad else "PASS", Severity.CRITICAL if bad else Severity.INFO, "contamination present" if bad else "explicit audit me contamination nahi"))
    try:
        tried = int(meta.get("tests_tried")) if meta.get("tests_tried") is not None else 0
    except (TypeError, ValueError):
        tried = 0
    if tried > 1:
        correction = _first(meta.get("multiple_testing_correction"))
        out.append(AuditFinding("multiple testing correction", "PASS" if correction else "FAIL", Severity.INFO if correction else Severity.CRITICAL, f"{tried} tests tried; correction={correction or 'missing'}"))
    return out


def _trade_net(row: Mapping[str, Any]) -> Optional[float]:
    vals = _numbers([row.get("net_pnl")])
    if vals:
        return vals[0]
    gross = _numbers([row.get("gross_pnl")])
    if not gross:
        return None
    costs = sum((_numbers([row.get(key) or 0.0]) or [0.0])[0] for key in ("spread_cost", "commission", "slippage", "latency_cost", "news_slippage", "other_costs"))
    return gross[0] - costs


def _drawdown(pnls: Sequence[float], starting_equity: float = 0.0) -> Dict[str, float]:
    equity, peak, max_dd, max_pct = float(starting_equity), float(starting_equity), 0.0, 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        dd = peak - equity
        max_dd = max(max_dd, dd)
        if peak > 0:
            max_pct = max(max_pct, dd / peak)
    return {"max_drawdown": max_dd, "max_drawdown_pct": max_pct}


def trading_metrics(trades: Sequence[Mapping[str, Any]], *, starting_equity: float = 0.0) -> Dict[str, Any]:
    pnls = [x for x in (_trade_net(row) for row in trades) if x is not None]
    if not pnls:
        return {"status": UNKNOWN, "reason": "usable trade P&L rows nahi mile"}
    wins, losses = [x for x in pnls if x > 0], [x for x in pnls if x < 0]
    gp, gl = sum(wins), abs(sum(losses))
    pf = math.inf if gl == 0 and gp > 0 else (UNKNOWN if gl == 0 else gp / gl)
    return {"status": "TESTED", "trades": len(pnls), "wins": len(wins), "losses": len(losses), "win_rate": len(wins) / len(pnls), "average_win": statistics.fmean(wins) if wins else 0.0, "average_loss": statistics.fmean(losses) if losses else 0.0, "expectancy": statistics.fmean(pnls), "profit_factor": pf, "total_net_pnl": sum(pnls), **_drawdown(pnls, starting_equity)}


def monte_carlo_trade_failure(net_pnls: Sequence[float], *, starting_equity: float, ruin_equity: float = 0.0, trials: int = 5000, seed: int = 1618) -> Dict[str, Any]:
    xs = _numbers(net_pnls)
    if len(xs) < 5 or starting_equity <= ruin_equity:
        return {"status": UNKNOWN, "reason": ">=5 net trades and valid equity thresholds required"}
    trials, rng, failures, dds, n = max(500, min(50000, int(trials))), random.Random(seed), 0, [], len(xs)
    for _ in range(trials):
        equity, peak, max_dd, failed = starting_equity, starting_equity, 0.0, False
        for pnl in [xs[rng.randrange(n)] for _ in range(n)]:
            equity += pnl
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
            if equity <= ruin_equity:
                failed = True
                break
        failures += int(failed)
        dds.append(max_dd)
    return {"status": "TESTED", "method": "bootstrap-resampled empirical trade paths", "trials": trials, "seed": seed, "failure_probability": failures / trials, "median_max_drawdown": statistics.median(dds), "p95_max_drawdown": _percentile(dds, 0.95), "conditioning_note": "Only supplied historical trade outcomes are represented."}


def _prediction_result(execution: Mapping[str, Any]) -> QuantitativeResult:
    actual, pred = _numbers(execution.get("actual") or execution.get("y_true") or []), _numbers(execution.get("predicted") or execution.get("y_pred") or [])
    r = QuantitativeResult()
    if not actual or len(actual) != len(pred):
        r.notes.append("actual/predicted arrays missing ya unequal")
        return r
    errors = [p - y for p, y in zip(pred, actual)]
    mean_y, ss_res = statistics.fmean(actual), sum(e * e for e in errors)
    ss_tot = sum((y - mean_y) ** 2 for y in actual)
    r.executed, r.sample_size = True, len(actual)
    r.metrics = {"MAE": statistics.fmean(abs(e) for e in errors), "RMSE": math.sqrt(statistics.fmean(e * e for e in errors)), "R2": UNKNOWN if ss_tot == 0 else 1 - ss_res / ss_tot, "mean_error": statistics.fmean(errors)}
    r.statistical_tests["bootstrap_mean_error_ci"] = bootstrap_mean_ci(errors)
    baseline = _numbers(execution.get("baseline_predicted") or [])
    if len(baseline) == len(actual):
        bmae = statistics.fmean(abs(b - y) for b, y in zip(baseline, actual))
        r.baseline_results = {"baseline_MAE": bmae, "candidate_minus_baseline_MAE": r.metrics["MAE"] - bmae, "candidate_beats_baseline": r.metrics["MAE"] < bmae}
    else:
        r.baseline_results = {"status": UNKNOWN, "reason": "baseline predictions not supplied"}
    return r


def _group_result(execution: Mapping[str, Any]) -> QuantitativeResult:
    a, b, r = _numbers(execution.get("treatment") or execution.get("group_a") or []), _numbers(execution.get("control") or execution.get("group_b") or []), QuantitativeResult()
    if len(a) < 2 or len(b) < 2:
        r.notes.append("treatment/control me >=2 observations each chahiye")
        return r
    va, vb = statistics.variance(a), statistics.variance(b)
    pooled = math.sqrt(((len(a)-1)*va + (len(b)-1)*vb) / (len(a)+len(b)-2))
    delta = statistics.fmean(a) - statistics.fmean(b)
    r.executed, r.sample_size = True, len(a) + len(b)
    r.metrics = {"treatment_mean": statistics.fmean(a), "control_mean": statistics.fmean(b), "mean_difference": delta, "cohens_d": UNKNOWN if pooled == 0 else delta / pooled}
    r.statistical_tests["permutation"] = permutation_mean_difference(a, b)
    rng, diffs, iterations = random.Random(314159), [], max(500, min(10000, int(execution.get("bootstrap_iterations") or 2000)))
    for _ in range(iterations):
        ta = [a[rng.randrange(len(a))] for _ in a]
        cb = [b[rng.randrange(len(b))] for _ in b]
        diffs.append(statistics.fmean(ta) - statistics.fmean(cb))
    r.statistical_tests["bootstrap_effect_ci"] = {"status": "TESTED", "low": _percentile(diffs, .025), "high": _percentile(diffs, .975), "iterations": iterations, "seed": 314159}
    r.baseline_results = {"control_mean": statistics.fmean(b), "candidate_minus_control": delta}
    return r


def _trading_result(execution: Mapping[str, Any]) -> QuantitativeResult:
    rows = [x for x in _list(execution.get("trades")) if isinstance(x, Mapping)]
    r, metrics = QuantitativeResult(), trading_metrics(rows, starting_equity=float(execution.get("starting_equity") or 0.0))
    if metrics.get("status") != "TESTED":
        r.notes.append(metrics.get("reason") or "trade metrics unavailable")
        return r
    r.executed, r.sample_size, r.metrics = True, int(metrics["trades"]), metrics
    net = [x for x in (_trade_net(row) for row in rows) if x is not None]
    r.statistical_tests["bootstrap_expectancy_ci"] = bootstrap_mean_ci(net)
    if execution.get("starting_equity") is not None:
        r.statistical_tests["monte_carlo_failure"] = monte_carlo_trade_failure(net, starting_equity=float(execution.get("starting_equity") or 0.0), ruin_equity=float(execution.get("ruin_equity") or 0.0), trials=int(execution.get("monte_carlo_trials") or 5000))
    base = [x for x in _list(execution.get("baseline_trades")) if isinstance(x, Mapping)]
    if base:
        r.baseline_results = trading_metrics(base, starting_equity=float(execution.get("starting_equity") or 0.0))
        if r.baseline_results.get("status") == "TESTED":
            r.baseline_results["candidate_minus_baseline_expectancy"] = r.metrics["expectancy"] - r.baseline_results["expectancy"]
            r.baseline_results["candidate_beats_baseline"] = r.metrics["expectancy"] > r.baseline_results["expectancy"]
    else:
        r.baseline_results = {"status": UNKNOWN, "reason": "baseline trade ledger not supplied"}
    gross_rows = [row for row in rows if "gross_pnl" in row and "net_pnl" not in row]
    if gross_rows:
        required = ("spread_cost", "commission", "slippage")
        missing = [key for key in required if any(key not in row for row in gross_rows)]
        r.friction = {"status": "FAIL" if missing else "TESTED", "missing_cost_fields": missing}
    else:
        r.friction = {"status": "TESTED" if rows and all("net_pnl" in row for row in rows) else UNKNOWN, "note": "net_pnl supplied; detailed cost decomposition unknown"}
    if len(net) >= 12:
        chunk = len(net) // 3
        thirds = [net[:chunk], net[chunk:2*chunk], net[2*chunk:]]
        r.robustness["chronological_thirds_expectancy"] = [statistics.fmean(x) for x in thirds]
        r.robustness["edge_decay_signal"] = statistics.fmean(thirds[-1]) < 0 < statistics.fmean(thirds[0])
    else:
        r.robustness["edge_decay"] = UNKNOWN
    return r


def _parameter_robustness(execution: Mapping[str, Any], result: QuantitativeResult) -> None:
    rows = [x for x in _list(execution.get("parameter_runs")) if isinstance(x, Mapping)]
    if not rows:
        result.robustness.setdefault("parameter_neighborhood", {"status": UNKNOWN, "reason": "nearby parameter runs not supplied"})
        return
    metric, direction = _first(execution.get("primary_metric"), default="score"), _first(execution.get("metric_direction"), default="higher").lower()
    try:
        threshold = float(execution.get("pass_threshold"))
    except (TypeError, ValueError):
        threshold = None
    values, passed = [], 0
    for row in rows:
        nums = _numbers([row.get(metric)])
        if not nums:
            continue
        value = nums[0]
        values.append(value)
        if threshold is not None and ((direction == "lower" and value <= threshold) or (direction != "lower" and value >= threshold)):
            passed += 1
    if not values:
        result.robustness["parameter_neighborhood"] = {"status": UNKNOWN, "reason": f"{metric} values missing"}
        return
    mean, sd = statistics.fmean(values), statistics.stdev(values) if len(values) >= 2 else 0.0
    result.robustness["parameter_neighborhood"] = {"status": "TESTED", "metric": metric, "runs": len(values), "mean": mean, "stdev": sd, "coefficient_of_variation": UNKNOWN if mean == 0 else abs(sd/mean), "passing_fraction": UNKNOWN if threshold is None else passed/len(values), "threshold": UNKNOWN if threshold is None else threshold}


def _ablations(execution: Mapping[str, Any], result: QuantitativeResult) -> None:
    rows = [x for x in _list(execution.get("ablation_runs")) if isinstance(x, Mapping)]
    if not rows:
        result.ablations = {"status": UNKNOWN, "reason": "ablation runs not supplied"}
        return
    metric, direction = _first(execution.get("primary_metric"), default="score"), _first(execution.get("metric_direction"), default="higher").lower()
    base = (_numbers([execution.get("candidate_primary_metric")]) or [None])[0]
    materiality = float(execution.get("ablation_materiality") or 0.0)
    evaluated = []
    for row in rows:
        values = _numbers([row.get(metric)])
        if not values:
            continue
        value = values[0]
        component = _first(row.get("removed_component"), row.get("component"), default="unknown component")
        if base is None:
            delta, harm, rec = UNKNOWN, UNKNOWN, UNKNOWN
        else:
            delta = value - base
            degradation = base - value if direction != "lower" else value - base
            harm = degradation > materiality
            rec = "KEEP" if harm else "REMOVE / simplify candidate"
        evaluated.append({"removed_component": component, metric: value, "delta_vs_full": delta, "material_harm": harm, "recommendation": rec})
    result.ablations = {"status": "TESTED" if evaluated else UNKNOWN, "rows": evaluated}


def execute_quantitative_test(matrix: TestMatrix, execution: Optional[Mapping[str, Any]]) -> QuantitativeResult:
    execution = _map(execution)
    if not execution:
        return QuantitativeResult(executed=False, dataset=matrix.exact_dataset, notes=["Execution data/result packet supplied nahi; planning ko test result nahi maana."], baseline_results={"status": UNKNOWN}, robustness={"status": UNKNOWN}, ablations={"status": UNKNOWN}, friction={"status": UNKNOWN}, failure_modes=[{**row, "result": UNKNOWN} for row in matrix.failure_modes])
    kind = _first(execution.get("kind"), execution.get("test_kind")).lower()
    if matrix.domain == "trading" or kind == "trading":
        result = _trading_result(execution)
    elif kind in ("prediction", "regression", "predictive_modeling"):
        result = _prediction_result(execution)
    elif kind in ("group_comparison", "experiment", "treatment_control"):
        result = _group_result(execution)
    else:
        metrics = _map(execution.get("metrics"))
        try:
            sample = int(execution.get("sample_size") or 0)
        except (TypeError, ValueError):
            sample = 0
        result = QuantitativeResult(executed=bool(execution.get("executed") is True and metrics and sample > 0), sample_size=sample, metrics=dict(metrics), baseline_results=dict(_map(execution.get("baseline_results"))) or {"status": UNKNOWN}, statistical_tests=dict(_map(execution.get("statistical_tests"))), friction=dict(_map(execution.get("friction"))) or {"status": UNKNOWN}, notes=_unique(_list(execution.get("notes"))))
        if not result.executed:
            result.notes.append("recognized raw data ya complete executed-result packet nahi mila")
    result.dataset = _first(execution.get("dataset_name"), execution.get("dataset"), default=matrix.exact_dataset)
    result.split_audit, result.bias_audit = audit_split(execution, domain=matrix.domain), audit_bias(execution)
    _parameter_robustness(execution, result)
    _ablations(execution, result)
    supplied = [x for x in _list(execution.get("failure_mode_results")) if isinstance(x, Mapping)]
    result.failure_modes = supplied or [{**row, "result": UNKNOWN} for row in matrix.failure_modes]
    p_values = _numbers(execution.get("p_values") or [])
    if len(p_values) > 1:
        result.statistical_tests["multiple_testing_bh"] = benjamini_hochberg(p_values, alpha=float(execution.get("fdr_alpha") or .05))
    return result


def _critical_fail(findings: Sequence[AuditFinding]) -> Optional[str]:
    for finding in findings:
        if finding.status == "FAIL" and finding.severity == Severity.CRITICAL:
            return f"{finding.check}: {finding.reason}"
    return None


def _baseline_beaten(result: QuantitativeResult, execution: Mapping[str, Any]) -> Optional[bool]:
    if isinstance(result.baseline_results.get("candidate_beats_baseline"), bool):
        return bool(result.baseline_results["candidate_beats_baseline"])
    primary = _first(execution.get("primary_metric"))
    if primary:
        candidate = _numbers([result.metrics.get(primary)])
        baseline = _numbers([result.baseline_results.get(primary), result.baseline_results.get("baseline_" + primary)])
        if candidate and baseline:
            direction = _first(execution.get("metric_direction"), default="higher").lower()
            return candidate[0] < baseline[0] if direction == "lower" else candidate[0] > baseline[0]
    return None


def decide_status(matrix: TestMatrix, result: QuantitativeResult, execution: Optional[Mapping[str, Any]] = None) -> Tuple[FinalStatus, str]:
    execution = _map(execution)
    if not result.executed:
        return FinalStatus.INCONCLUSIVE, f"{UNKNOWN}: {'; '.join(result.notes[:2]) or 'actual execution data unavailable'}"
    critical = _critical_fail(result.split_audit + result.bias_audit)
    if critical:
        return FinalStatus.FAIL, f"Validation invalidated by contamination/control failure — {critical}"
    falsified = execution.get("falsified", execution.get("falsification_triggered"))
    if falsified is True:
        return FinalStatus.FAIL, f"Pre-specified falsification boundary triggered: {matrix.falsification_rule}"
    baseline = _baseline_beaten(result, execution)
    if baseline is False:
        return FinalStatus.FAIL, "Candidate simplest/declared baseline ko beat nahi kar saka; complexity earned nahi hui."
    for row in result.failure_modes:
        if str(row.get("severity") or "").upper() == "CATASTROPHIC" and bool(row.get("failed")):
            return FinalStatus.FAIL, f"Catastrophic failure mode triggered: {_first(row.get('mode'), row.get('name'))}"
    unknown_audits = [x for x in result.split_audit + result.bias_audit if x.status == "UNKNOWN" and x.severity in (Severity.CRITICAL, Severity.WARNING)]
    robust = _map(result.robustness.get("parameter_neighborhood"))
    robustness_tested = robust.get("status") == "TESTED"
    friction_ok = _first(result.friction.get("status")).upper() in ("TESTED", "PASS")
    if baseline is True and robustness_tested and friction_ok and not unknown_audits and falsified is False:
        return FinalStatus.PASS, "Actual test ran; baseline beat hua; leakage controls recorded; robustness + friction checked; falsification boundary trigger nahi hui."
    reasons = []
    if baseline is None: reasons.append("baseline comparison unknown")
    if not robustness_tested: reasons.append("nearby-parameter robustness not tested")
    if not friction_ok: reasons.append("real-world friction incomplete/unknown")
    if unknown_audits: reasons.append("some leakage/bias controls unknown")
    if falsified is None: reasons.append("falsification outcome not explicitly recorded")
    return FinalStatus.CONDITIONAL_PASS, "Primary execution usable hai, but full PASS pending: " + "; ".join(reasons or ["replication/confirmatory evidence"])


def _practical(validations: Sequence[HypothesisValidation]) -> Dict[str, Any]:
    rows = [x for x in validations if x.status in (FinalStatus.PASS, FinalStatus.CONDITIONAL_PASS)]
    if not rows:
        return {"status": "NONE", "reason": "Koi candidate validation gate se survive nahi hua.", "steps": []}
    rows.sort(key=lambda x: (0 if x.status == FinalStatus.PASS else 1, -int(x.result.sample_size or 0), x.hypothesis_id))
    best = rows[0]
    return {"status": best.status.value, "hypothesis_id": best.hypothesis_id, "statement": best.statement, "steps": best.test_matrix.implementation_steps, "stop_rule": best.test_matrix.falsification_rule, "note": "Operational scope tested population/time/regime se bahar generalize mat karo."}


class Agent3ValidationEngine:
    """Build tests and return the requested 14-section Agent-3 packet."""

    def build_test_matrices(self, question: str, research_packet: Mapping[str, Any], hypothesis_packet: Any, execution_packets: Optional[Mapping[str, Mapping[str, Any]]] = None) -> List[TestMatrix]:
        executions = _map(execution_packets)
        out = []
        for index, h in enumerate(_extract_hypotheses(hypothesis_packet), 1):
            hid = _hypothesis_id(h, index)
            out.append(build_test_matrix(question, _map(research_packet), h, _map(executions.get(hid)), index=index))
        return out

    def validate(self, question: str, research_packet: Mapping[str, Any], hypothesis_packet: Any, execution_packets: Optional[Mapping[str, Mapping[str, Any]]] = None) -> Dict[str, Any]:
        research, hypotheses, executions = _map(research_packet), _extract_hypotheses(hypothesis_packet), _map(execution_packets)
        validations: List[HypothesisValidation] = []
        for index, h in enumerate(hypotheses, 1):
            hid, execution = _hypothesis_id(h, index), _map(executions.get(_hypothesis_id(h, index)))
            matrix = build_test_matrix(question, research, h, execution, index=index)
            result = execute_quantitative_test(matrix, execution)
            status, reason = decide_status(matrix, result, execution)
            validations.append(HypothesisValidation(hid, matrix.statement, status, reason, matrix, result, status in (FinalStatus.PASS, FinalStatus.CONDITIONAL_PASS), "Status only supplied execution evidence par based hai; missing tests UNKNOWN hain; probability invent nahi ki."))

        performed, impossible, unknowns = [], [], []
        for row in validations:
            if row.result.executed:
                performed.append({"hypothesis_id": row.hypothesis_id, "test": row.test_matrix.exact_test, "dataset": row.result.dataset, "sample_size": row.result.sample_size, "metrics": row.result.metrics})
            else:
                impossible.append({"hypothesis_id": row.hypothesis_id, "reason": "; ".join(row.test_matrix.blockers + row.result.notes) or UNKNOWN, "required_next": row.test_matrix.to_dict()})
                unknowns.append(f"{row.hypothesis_id}: actual test execute nahi hua.")
            for finding in row.result.split_audit + row.result.bias_audit:
                if finding.status == "UNKNOWN":
                    unknowns.append(f"{row.hypothesis_id}: {finding.check} — UNKNOWN.")
            if _first(row.result.friction.get("status")).upper() in ("", "UNKNOWN", UNKNOWN):
                unknowns.append(f"{row.hypothesis_id}: real-world friction result UNKNOWN.")
        if not hypotheses:
            unknowns.append("Agent 2 hypothesis packet me usable hypothesis list nahi mili.")

        survivors = [{"hypothesis_id": row.hypothesis_id, "status": row.status.value, "statement": row.statement, "scope_warning": "Do not generalize beyond tested population/time/regime."} for row in validations if row.surviving_candidate]
        dataset_quality = {row.hypothesis_id: {"dataset": row.result.dataset or row.test_matrix.exact_dataset, "sample_size": row.result.sample_size if row.result.executed else UNKNOWN, "execution_state": "TESTED" if row.result.executed else UNKNOWN, "blockers": row.test_matrix.blockers} for row in validations}
        final = {"schema": "agent3-validation-packet-v1", "question": question, "candidate_count": len(validations), "pass": sum(x.status == FinalStatus.PASS for x in validations), "conditional_pass": sum(x.status == FinalStatus.CONDITIONAL_PASS for x in validations), "inconclusive": sum(x.status == FinalStatus.INCONCLUSIVE for x in validations), "fail": sum(x.status == FinalStatus.FAIL for x in validations), "survivors": survivors, "do_not_overclaim": ["Planning is not execution.", "NOT TESTED / UNKNOWN stays unknown.", "One failed tested model does not falsify an entire theory category.", "Preserve tested population/time/regime scope."], "validations": [x.to_dict() for x in validations]}
        return {
            "1. Tests actually performed": performed,
            "2. Tests not possible + reason": impossible,
            "3. Dataset / evidence quality": dataset_quality,
            "4. Baseline results": {x.hypothesis_id: x.result.baseline_results for x in validations},
            "5. Hypothesis results": {x.hypothesis_id: {"status": x.status.value, "reason": x.reason, "metrics": x.result.metrics} for x in validations},
            "6. Robustness tests": {x.hypothesis_id: x.result.robustness for x in validations},
            "7. Ablation results": {x.hypothesis_id: x.result.ablations for x in validations},
            "8. Bias/leakage audit": {x.hypothesis_id: {"split": [f.to_dict() for f in x.result.split_audit], "bias": [f.to_dict() for f in x.result.bias_audit]} for x in validations},
            "9. Real-world friction results": {x.hypothesis_id: x.result.friction for x in validations},
            "10. Failure-mode analysis": {x.hypothesis_id: x.result.failure_modes for x in validations},
            "11. Surviving final candidates": survivors,
            "12. Practical implementation candidate": _practical(validations),
            "13. Unknown/unverified elements": _unique(unknowns),
            "14. FINAL VALIDATION PACKET FOR AGENT 4": final,
        }


__all__ = ["Agent3ValidationEngine", "AuditFinding", "FinalStatus", "HypothesisValidation", "QuantitativeResult", "TestMatrix", "audit_bias", "audit_split", "benjamini_hochberg", "bootstrap_mean_ci", "build_test_matrix", "decide_status", "execute_quantitative_test", "monte_carlo_trade_failure", "permutation_mean_difference", "seal_holdout", "trading_metrics"]
