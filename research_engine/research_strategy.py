"""Bounded research strategy governance for capabilities #57-#61.

This module sits above the existing fixed ``DepthConfig`` presets. It does not
invent new unlimited budgets and it cannot trade away minimum evidence needs for
speed/cost. It provides:

* #57 Meta-Reasoning Agent: explicit reasoned choice among bounded strategies.
* #58 Strategy Selector: deterministic candidate scoring and disqualification.
* #59 Compute Economy: normalized utility per bounded cost, after evidence floor.
* #60 Adaptive Research Depth: escalation/de-escalation within existing presets.
* #61 Research Saturation Detector: conservative early-stop based on repeated
  marginal information gain while unresolved critical gaps/contradictions block
  saturation.

Scores are process-control heuristics, not truth probabilities.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence, Tuple

from .depth import DepthConfig, get_depth_config


_MODES = ("QUICK", "DEEP", "MAXIMUM", "MARATHON")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _unit(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be finite and in [0,1]")
    return number


def _count(value: object, field: str) -> int:
    if type(value) is not int or value < 0 or value > 1_000_000:
        raise ValueError(f"{field} must be a bounded nonnegative integer")
    return value


@dataclass(frozen=True)
class ResearchSignals:
    complexity: float
    uncertainty: float
    stakes: float
    novelty: float
    evidence_gap: float
    contradiction_pressure: float
    unresolved_critical_gaps: int = 0
    unresolved_contradictions: int = 0
    user_latency_priority: float = 0.5
    resource_pressure: float = 0.5

    def normalized(self) -> "ResearchSignals":
        return ResearchSignals(
            complexity=_unit(self.complexity, "complexity"),
            uncertainty=_unit(self.uncertainty, "uncertainty"),
            stakes=_unit(self.stakes, "stakes"),
            novelty=_unit(self.novelty, "novelty"),
            evidence_gap=_unit(self.evidence_gap, "evidence_gap"),
            contradiction_pressure=_unit(self.contradiction_pressure, "contradiction_pressure"),
            unresolved_critical_gaps=_count(self.unresolved_critical_gaps, "unresolved_critical_gaps"),
            unresolved_contradictions=_count(self.unresolved_contradictions, "unresolved_contradictions"),
            user_latency_priority=_unit(self.user_latency_priority, "user_latency_priority"),
            resource_pressure=_unit(self.resource_pressure, "resource_pressure"),
        )


@dataclass(frozen=True)
class StrategyScore:
    mode: str
    adequacy: float
    normalized_cost: float
    utility: float
    eligible: bool
    blockers: Tuple[str, ...]


@dataclass(frozen=True)
class StrategyDecision:
    selected_mode: str
    selected_config: Mapping[str, Any]
    scores: Tuple[StrategyScore, ...]
    reasons: Tuple[str, ...]
    evidence_floor_overrode_cost: bool
    truth_probability: bool
    decision_hash: str


def _capacity(config: DepthConfig) -> float:
    # Fixed normalized process capacity from already-bounded rails.
    components = (
        min(config.gemini_calls / 4.0, 1.0),
        min(config.max_sources / 40.0, 1.0),
        min(config.max_rounds / 5.0, 1.0),
        min(config.max_fulltext / 16.0, 1.0),
        1.0 if config.use_red_team else 0.0,
        1.0 if config.use_papers else 0.0,
        1.0 if config.use_datasets else 0.0,
    )
    return sum(components) / len(components)


def _cost(config: DepthConfig) -> float:
    # Relative bounded compute/network cost; not money and not API billing.
    weighted = (
        4.0 * config.gemini_calls
        + 0.25 * config.max_sources
        + 2.0 * config.max_rounds
        + 0.5 * config.max_fulltext
        + config.discovery_seconds / 60.0
    )
    marathon = get_depth_config("MARATHON")
    ceiling = (
        4.0 * marathon.gemini_calls
        + 0.25 * marathon.max_sources
        + 2.0 * marathon.max_rounds
        + 0.5 * marathon.max_fulltext
        + marathon.discovery_seconds / 60.0
    )
    return min(1.0, weighted / ceiling)


def select_research_strategy(signals: ResearchSignals) -> StrategyDecision:
    s = signals.normalized()
    need = min(1.0, (
        0.20 * s.complexity
        + 0.20 * s.uncertainty
        + 0.18 * s.stakes
        + 0.12 * s.novelty
        + 0.18 * s.evidence_gap
        + 0.12 * s.contradiction_pressure
    ))
    scores = []
    evidence_floor_overrode_cost = False
    for mode in _MODES:
        cfg = get_depth_config(mode)
        capacity = _capacity(cfg)
        cost = _cost(cfg)
        blockers = []
        if s.unresolved_critical_gaps and mode == "QUICK":
            blockers.append("critical evidence gaps forbid QUICK")
        if s.unresolved_contradictions and not cfg.use_red_team:
            blockers.append("unresolved contradictions require red-team capable strategy")
        if s.stakes >= 0.75 and mode == "QUICK":
            blockers.append("high stakes forbid QUICK")
        if s.uncertainty >= 0.8 and cfg.max_rounds < 2:
            blockers.append("high uncertainty requires multiple research rounds")
        if s.evidence_gap >= 0.75 and cfg.max_fulltext < 3:
            blockers.append("large evidence gap requires deeper full-text budget")
        adequacy = max(0.0, 1.0 - abs(capacity - need))
        if capacity < need:
            adequacy *= capacity / max(need, 1e-12)
        economy_penalty = cost * (0.15 + 0.35 * s.resource_pressure + 0.20 * s.user_latency_priority)
        risk_bonus = capacity * (0.20 * s.stakes + 0.15 * s.uncertainty + 0.10 * s.contradiction_pressure)
        utility = adequacy + risk_bonus - economy_penalty
        eligible = not blockers
        if blockers and cost < 0.4:
            evidence_floor_overrode_cost = True
        scores.append(StrategyScore(mode, adequacy, cost, utility, eligible, tuple(blockers)))

    eligible = [row for row in scores if row.eligible]
    if not eligible:
        # The deepest bounded mode is a safe fallback, never an unbounded run.
        selected = next(row for row in scores if row.mode == "MARATHON")
        reasons = ("all lower-cost modes violated evidence/risk floors; selected deepest bounded preset",)
    else:
        selected = max(eligible, key=lambda row: (row.utility, row.adequacy, -row.normalized_cost, row.mode))
        reasons = (
            f"selected {selected.mode}: utility={selected.utility:.4f}, adequacy={selected.adequacy:.4f}, cost={selected.normalized_cost:.4f}",
            "cost optimization applied only after evidence/risk eligibility gates",
        )
    config = get_depth_config(selected.mode)
    payload = {
        "selected_mode": selected.mode,
        "selected_config": config.to_dict(),
        "scores": [asdict(row) for row in scores],
        "reasons": reasons,
        "evidence_floor_overrode_cost": evidence_floor_overrode_cost,
        "truth_probability": False,
    }
    return StrategyDecision(
        selected_mode=selected.mode,
        selected_config=config.to_dict(),
        scores=tuple(scores),
        reasons=tuple(reasons),
        evidence_floor_overrode_cost=evidence_floor_overrode_cost,
        truth_probability=False,
        decision_hash=_sha(payload),
    )


@dataclass(frozen=True)
class RoundProgress:
    round_index: int
    new_relevant_sources: int
    new_independent_sources: int
    claims_newly_supported: int
    contradictions_resolved: int
    novel_evidence_fraction: float
    remaining_critical_gaps: int
    remaining_contradictions: int

    def normalized(self) -> "RoundProgress":
        if type(self.round_index) is not int or self.round_index < 1 or self.round_index > 10_000:
            raise ValueError("round_index must be a positive bounded integer")
        return RoundProgress(
            round_index=self.round_index,
            new_relevant_sources=_count(self.new_relevant_sources, "new_relevant_sources"),
            new_independent_sources=_count(self.new_independent_sources, "new_independent_sources"),
            claims_newly_supported=_count(self.claims_newly_supported, "claims_newly_supported"),
            contradictions_resolved=_count(self.contradictions_resolved, "contradictions_resolved"),
            novel_evidence_fraction=_unit(self.novel_evidence_fraction, "novel_evidence_fraction"),
            remaining_critical_gaps=_count(self.remaining_critical_gaps, "remaining_critical_gaps"),
            remaining_contradictions=_count(self.remaining_contradictions, "remaining_contradictions"),
        )


@dataclass(frozen=True)
class SaturationAssessment:
    saturated: bool
    consecutive_low_gain_rounds: int
    marginal_gain_scores: Tuple[float, ...]
    blockers: Tuple[str, ...]
    recommended_action: str
    assessment_hash: str
    truth_proven: bool = False


def assess_research_saturation(
    rounds: Sequence[RoundProgress],
    *,
    low_gain_threshold: float = 0.12,
    required_consecutive_low_gain: int = 2,
    minimum_rounds: int = 2,
    require_all_rounds: bool = False,
) -> SaturationAssessment:
    if isinstance(rounds, (str, bytes, bytearray)) or not isinstance(rounds, Sequence):
        raise ValueError("rounds must be a finite sequence")
    if not 1 <= len(rounds) <= 10_000:
        raise ValueError("rounds must contain 1..10,000 items")
    threshold = _unit(low_gain_threshold, "low_gain_threshold")
    if type(required_consecutive_low_gain) is not int or required_consecutive_low_gain < 1:
        raise ValueError("required_consecutive_low_gain must be positive")
    if type(minimum_rounds) is not int or minimum_rounds < 1:
        raise ValueError("minimum_rounds must be positive")
    normalized = tuple(row.normalized() for row in rounds)
    indices = [row.round_index for row in normalized]
    if indices != sorted(indices) or len(set(indices)) != len(indices):
        raise ValueError("round indices must be unique and increasing")

    gains = []
    for row in normalized:
        source_signal = min(1.0, row.new_relevant_sources / 5.0)
        independent_signal = min(1.0, row.new_independent_sources / 3.0)
        claim_signal = min(1.0, row.claims_newly_supported / 3.0)
        contradiction_signal = min(1.0, row.contradictions_resolved / 2.0)
        gain = (
            0.25 * source_signal
            + 0.30 * independent_signal
            + 0.20 * claim_signal
            + 0.10 * contradiction_signal
            + 0.15 * row.novel_evidence_fraction
        )
        gains.append(gain)

    consecutive = 0
    for gain in reversed(gains):
        if gain <= threshold:
            consecutive += 1
        else:
            break
    latest = normalized[-1]
    blockers = []
    if len(normalized) < minimum_rounds:
        blockers.append("minimum research rounds not reached")
    if latest.remaining_critical_gaps:
        blockers.append("critical evidence gaps remain")
    if latest.remaining_contradictions:
        blockers.append("unresolved contradictions remain")
    if consecutive < required_consecutive_low_gain:
        blockers.append("marginal information gain has not stayed low long enough")
    if require_all_rounds:
        blockers.append("configured depth requires all research rounds")
    saturated = not blockers
    action = "STOP_EARLY_SATURATED" if saturated else "CONTINUE_RESEARCH"
    payload = {
        "saturated": saturated,
        "consecutive_low_gain_rounds": consecutive,
        "marginal_gain_scores": gains,
        "blockers": blockers,
        "recommended_action": action,
        "truth_proven": False,
    }
    return SaturationAssessment(
        saturated=saturated,
        consecutive_low_gain_rounds=consecutive,
        marginal_gain_scores=tuple(gains),
        blockers=tuple(blockers),
        recommended_action=action,
        assessment_hash=_sha(payload),
        truth_proven=False,
    )


def adapt_depth_after_rounds(
    current_mode: str,
    signals: ResearchSignals,
    rounds: Sequence[RoundProgress],
) -> Mapping[str, Any]:
    current = str(current_mode or "").strip().upper()
    if current not in _MODES:
        raise ValueError("current_mode must be a named bounded preset")
    cfg = get_depth_config(current)
    saturation = assess_research_saturation(
        rounds,
        require_all_rounds=bool(cfg.require_all_rounds),
    )
    if saturation.saturated:
        return {
            "action": "STOP",
            "current_mode": current,
            "next_mode": current,
            "reason": "research saturation criteria satisfied",
            "saturation": asdict(saturation),
            "truth_proven": False,
        }
    desired = select_research_strategy(signals).selected_mode
    current_index = _MODES.index(current)
    desired_index = _MODES.index(desired)
    # Adaptive depth can escalate by at most one tier per round, preventing a
    # single noisy signal from jumping directly from QUICK to MARATHON.
    next_index = min(current_index + 1, desired_index) if desired_index > current_index else current_index
    next_mode = _MODES[next_index]
    return {
        "action": "CONTINUE",
        "current_mode": current,
        "next_mode": next_mode,
        "reason": "critical gaps/contradictions or marginal gain require more research",
        "saturation": asdict(saturation),
        "truth_proven": False,
    }
