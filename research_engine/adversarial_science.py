"""Deterministic adversarial-science core for #36 Red-Team AI and #38 Falsification Budget.

The legacy red-team path is useful for prompting a critic, but a prompt is not an
auditable falsification program.  This module adds a bounded structured layer:

* explicit attack targets and attack proposals,
* precommitted cost/safety/falsification metadata,
* champion-target reserve and anti-confirmation coverage,
* target/type/independent-group diversity diagnostics,
* deterministic budget allocation and hashes,
* exact planned-attack execution observations,
* fail-closed separation between "survived registered attacks" and truth.

No natural-language claim is silently converted into an attack.  No planner call
is an experiment.  No successful survival result proves a claim true.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple


_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")
_ALLOWED_ATTACK_TYPES = {
    "COUNTEREXAMPLE",
    "ALTERNATIVE_MECHANISM",
    "ASSUMPTION_BREAK",
    "MEASUREMENT_STRESS",
    "LEAKAGE_PROBE",
    "PLACEBO_CONTROL",
    "OOD_STRESS",
    "NEGATIVE_CONTROL",
}
_ALLOWED_SAFETY = {"APPROVED", "REVIEW_REQUIRED", "BLOCKED"}
_ALLOWED_OBSERVATIONS = {"FALSIFIED", "NOT_FALSIFIED", "INCONCLUSIVE", "ERROR"}
_MAX_ITEMS = 10_000


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("adversarial payload must be finite JSON-compatible data") from exc


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _text(value: object, field: str, *, minimum: int = 3, maximum: int = 20_000) -> str:
    text = str(value or "").strip()
    if not minimum <= len(text) <= maximum:
        raise ValueError(f"{field} length is invalid")
    return text


def _finite(value: object, field: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    if minimum is not None and number < minimum:
        raise ValueError(f"{field} is below minimum")
    if maximum is not None and number > maximum:
        raise ValueError(f"{field} exceeds maximum")
    return number


@dataclass(frozen=True)
class AttackTarget:
    target_id: str
    statement: str
    impact: float
    uncertainty: float
    champion: bool = False

    def normalized(self) -> "AttackTarget":
        return AttackTarget(
            target_id=_safe_id(self.target_id, "target_id"),
            statement=_text(self.statement, "target.statement", minimum=5),
            impact=_finite(self.impact, "target.impact", minimum=0.0, maximum=1.0),
            uncertainty=_finite(
                self.uncertainty, "target.uncertainty", minimum=0.0, maximum=1.0
            ),
            champion=bool(self.champion),
        )


@dataclass(frozen=True)
class AttackProposal:
    attack_id: str
    target_id: str
    attack_type: str
    cost_units: float
    falsification_power: float
    independent_group: str
    expected_observation: str
    falsification_condition: str
    safety_status: str = "APPROVED"
    feasible: bool = True

    def normalized(self) -> "AttackProposal":
        attack_type = str(self.attack_type or "").strip().upper()
        if attack_type not in _ALLOWED_ATTACK_TYPES:
            raise ValueError("unsupported attack_type")
        safety = str(self.safety_status or "").strip().upper()
        if safety not in _ALLOWED_SAFETY:
            raise ValueError("unsupported safety_status")
        return AttackProposal(
            attack_id=_safe_id(self.attack_id, "attack_id"),
            target_id=_safe_id(self.target_id, "attack.target_id"),
            attack_type=attack_type,
            cost_units=_finite(self.cost_units, "attack.cost_units", minimum=1e-12),
            falsification_power=_finite(
                self.falsification_power,
                "attack.falsification_power",
                minimum=0.0,
                maximum=1.0,
            ),
            independent_group=_safe_id(self.independent_group, "independent_group"),
            expected_observation=_text(
                self.expected_observation, "expected_observation", minimum=5
            ),
            falsification_condition=_text(
                self.falsification_condition, "falsification_condition", minimum=5
            ),
            safety_status=safety,
            feasible=bool(self.feasible),
        )


@dataclass(frozen=True)
class FalsificationPolicy:
    total_budget: float
    champion_reserve_fraction: float = 0.30
    max_target_budget_fraction: float = 0.70
    min_attacks_per_target: int = 1
    min_attack_type_diversity: int = 2
    min_independent_groups: int = 2
    allow_review_required: bool = False

    def normalized(self) -> "FalsificationPolicy":
        for field in (
            "min_attacks_per_target",
            "min_attack_type_diversity",
            "min_independent_groups",
        ):
            value = getattr(self, field)
            if type(value) is not int or not 1 <= value <= _MAX_ITEMS:
                raise ValueError(f"{field} must be a bounded positive integer")
        reserve = _finite(
            self.champion_reserve_fraction,
            "champion_reserve_fraction",
            minimum=0.0,
            maximum=1.0,
        )
        max_share = _finite(
            self.max_target_budget_fraction,
            "max_target_budget_fraction",
            minimum=0.0,
            maximum=1.0,
        )
        if max_share < reserve:
            raise ValueError("max_target_budget_fraction cannot be below champion reserve")
        return FalsificationPolicy(
            total_budget=_finite(self.total_budget, "total_budget", minimum=1e-12),
            champion_reserve_fraction=reserve,
            max_target_budget_fraction=max_share,
            min_attacks_per_target=self.min_attacks_per_target,
            min_attack_type_diversity=self.min_attack_type_diversity,
            min_independent_groups=self.min_independent_groups,
            allow_review_required=bool(self.allow_review_required),
        )


@dataclass(frozen=True)
class RejectedAttack:
    attack_id: str
    target_id: str
    reason: str


@dataclass(frozen=True)
class FalsificationPlan:
    targets: Tuple[AttackTarget, ...]
    selected_attacks: Tuple[AttackProposal, ...]
    rejected_attacks: Tuple[RejectedAttack, ...]
    total_budget: float
    spent_budget: float
    champion_target_id: str
    champion_reserved_budget: float
    champion_spent_budget: float
    target_attack_counts: Mapping[str, int]
    target_budget: Mapping[str, float]
    attack_types: Tuple[str, ...]
    independent_groups: Tuple[str, ...]
    blockers: Tuple[str, ...]
    status: str
    plan_hash: str
    planning_only: bool = True
    attacks_executed: bool = False
    truth_proven: bool = False
    survival_is_truth: bool = False


@dataclass(frozen=True)
class AttackObservation:
    attack_id: str
    status: str
    measured_result: str
    observer_id: str

    def normalized(self) -> "AttackObservation":
        status = str(self.status or "").strip().upper()
        if status not in _ALLOWED_OBSERVATIONS:
            raise ValueError("unsupported attack observation status")
        return AttackObservation(
            attack_id=_safe_id(self.attack_id, "observation.attack_id"),
            status=status,
            measured_result=_text(self.measured_result, "measured_result", minimum=1),
            observer_id=_safe_id(self.observer_id, "observer_id"),
        )


@dataclass(frozen=True)
class TargetAttackResult:
    target_id: str
    status: str
    attack_ids: Tuple[str, ...]
    falsified_by: Tuple[str, ...]


@dataclass(frozen=True)
class FalsificationExecutionReport:
    plan_hash: str
    target_results: Tuple[TargetAttackResult, ...]
    observations: Tuple[AttackObservation, ...]
    execution_complete: bool
    falsified_target_ids: Tuple[str, ...]
    survived_target_ids: Tuple[str, ...]
    inconclusive_target_ids: Tuple[str, ...]
    report_hash: str
    truth_proven: bool = False
    survival_is_truth: bool = False
    scientific_verification_implied: bool = False


def _proposal_score(target: AttackTarget, proposal: AttackProposal) -> float:
    # Explicitly heuristic prioritization, not probability of successful falsification.
    numerator = proposal.falsification_power * (0.5 + target.impact) * (0.5 + target.uncertainty)
    return numerator / proposal.cost_units


def _normalize_inputs(
    targets: Sequence[AttackTarget],
    proposals: Sequence[AttackProposal],
) -> tuple[Tuple[AttackTarget, ...], Tuple[AttackProposal, ...]]:
    if isinstance(targets, (str, bytes, bytearray)) or not isinstance(targets, Sequence):
        raise ValueError("targets must be a finite sequence")
    if isinstance(proposals, (str, bytes, bytearray)) or not isinstance(proposals, Sequence):
        raise ValueError("proposals must be a finite sequence")
    if not 1 <= len(targets) <= _MAX_ITEMS:
        raise ValueError("targets must contain 1..10000 items")
    if not 1 <= len(proposals) <= _MAX_ITEMS:
        raise ValueError("proposals must contain 1..10000 items")
    normalized_targets = tuple(item.normalized() for item in targets)
    normalized_proposals = tuple(item.normalized() for item in proposals)
    target_ids = [item.target_id for item in normalized_targets]
    attack_ids = [item.attack_id for item in normalized_proposals]
    if len(set(target_ids)) != len(target_ids):
        raise ValueError("target_id values must be unique")
    if len(set(attack_ids)) != len(attack_ids):
        raise ValueError("attack_id values must be unique")
    champion_ids = [item.target_id for item in normalized_targets if item.champion]
    if len(champion_ids) != 1:
        raise ValueError("exactly one precommitted champion target is required")
    known = set(target_ids)
    unknown = sorted({item.target_id for item in normalized_proposals} - known)
    if unknown:
        raise ValueError("attack proposal references unknown target_id")
    return (
        tuple(sorted(normalized_targets, key=lambda item: item.target_id)),
        tuple(sorted(normalized_proposals, key=lambda item: item.attack_id)),
    )


def plan_falsification_campaign(
    targets: Sequence[AttackTarget],
    proposals: Sequence[AttackProposal],
    policy: FalsificationPolicy,
) -> FalsificationPlan:
    """Allocate a deterministic precommitted attack budget without executing attacks."""
    targets_n, proposals_n = _normalize_inputs(targets, proposals)
    policy_n = policy.normalized()
    by_target = {item.target_id: item for item in targets_n}
    champion_id = next(item.target_id for item in targets_n if item.champion)
    champion_reserve = policy_n.total_budget * policy_n.champion_reserve_fraction
    target_cap = policy_n.total_budget * policy_n.max_target_budget_fraction

    eligible = []
    rejected = []
    for proposal in proposals_n:
        if not proposal.feasible:
            rejected.append(RejectedAttack(proposal.attack_id, proposal.target_id, "infeasible"))
            continue
        if proposal.safety_status == "BLOCKED":
            rejected.append(RejectedAttack(proposal.attack_id, proposal.target_id, "safety_blocked"))
            continue
        if proposal.safety_status == "REVIEW_REQUIRED" and not policy_n.allow_review_required:
            rejected.append(RejectedAttack(proposal.attack_id, proposal.target_id, "safety_review_required"))
            continue
        if proposal.cost_units > policy_n.total_budget:
            rejected.append(RejectedAttack(proposal.attack_id, proposal.target_id, "cost_exceeds_total_budget"))
            continue
        eligible.append(proposal)

    def ranked(rows: Sequence[AttackProposal]) -> list[AttackProposal]:
        return sorted(
            rows,
            key=lambda item: (
                -_proposal_score(by_target[item.target_id], item),
                item.cost_units,
                item.attack_id,
            ),
        )

    selected: list[AttackProposal] = []
    selected_ids = set()
    spent = 0.0
    target_spend: Dict[str, float] = {item.target_id: 0.0 for item in targets_n}
    target_counts: Dict[str, int] = {item.target_id: 0 for item in targets_n}

    def try_select(proposal: AttackProposal) -> bool:
        nonlocal spent
        if proposal.attack_id in selected_ids:
            return False
        if spent + proposal.cost_units > policy_n.total_budget + 1e-12:
            return False
        new_target_spend = target_spend[proposal.target_id] + proposal.cost_units
        if new_target_spend > target_cap + 1e-12:
            return False
        selected.append(proposal)
        selected_ids.add(proposal.attack_id)
        spent += proposal.cost_units
        target_spend[proposal.target_id] = new_target_spend
        target_counts[proposal.target_id] += 1
        return True

    # 1) Protect the explicit champion against confirmation bias before filling
    # the rest of the budget.
    champion_rows = ranked([row for row in eligible if row.target_id == champion_id])
    for proposal in champion_rows:
        if target_spend[champion_id] + 1e-12 >= champion_reserve:
            break
        try_select(proposal)

    # 2) Guarantee target coverage where budget/eligible attacks permit.
    for target in targets_n:
        rows = ranked([row for row in eligible if row.target_id == target.target_id])
        for proposal in rows:
            if target_counts[target.target_id] >= policy_n.min_attacks_per_target:
                break
            try_select(proposal)

    # 3) Fill remaining budget by disconfirming-value-per-cost heuristic.
    for proposal in ranked(eligible):
        try_select(proposal)

    for proposal in eligible:
        if proposal.attack_id not in selected_ids:
            reason = "budget_or_target_cap_not_selected"
            rejected.append(RejectedAttack(proposal.attack_id, proposal.target_id, reason))

    attack_types = tuple(sorted({row.attack_type for row in selected}))
    groups = tuple(sorted({row.independent_group for row in selected}))
    blockers = []
    if target_spend[champion_id] + 1e-12 < champion_reserve:
        blockers.append("champion_reserve_not_met")
    uncovered = [
        target_id for target_id, count in target_counts.items()
        if count < policy_n.min_attacks_per_target
    ]
    if uncovered:
        blockers.append("target_coverage_incomplete:" + ",".join(sorted(uncovered)))
    if len(attack_types) < policy_n.min_attack_type_diversity:
        blockers.append("attack_type_diversity_below_policy")
    if len(groups) < policy_n.min_independent_groups:
        blockers.append("independent_group_diversity_below_policy")
    if not selected:
        blockers.append("no_attacks_selected")

    selected_sorted = tuple(sorted(selected, key=lambda item: item.attack_id))
    rejected_sorted = tuple(sorted(rejected, key=lambda item: (item.attack_id, item.reason)))
    payload = {
        "targets": [item.__dict__ for item in targets_n],
        "selected_attacks": [item.__dict__ for item in selected_sorted],
        "rejected_attacks": [item.__dict__ for item in rejected_sorted],
        "policy": policy_n.__dict__,
        "spent_budget": round(spent, 12),
        "champion_target_id": champion_id,
        "champion_reserved_budget": round(champion_reserve, 12),
        "champion_spent_budget": round(target_spend[champion_id], 12),
        "target_attack_counts": dict(sorted(target_counts.items())),
        "target_budget": {key: round(value, 12) for key, value in sorted(target_spend.items())},
        "attack_types": attack_types,
        "independent_groups": groups,
        "blockers": tuple(sorted(blockers)),
        "planning_only": True,
        "attacks_executed": False,
        "truth_proven": False,
        "survival_is_truth": False,
    }
    return FalsificationPlan(
        targets=targets_n,
        selected_attacks=selected_sorted,
        rejected_attacks=rejected_sorted,
        total_budget=policy_n.total_budget,
        spent_budget=round(spent, 12),
        champion_target_id=champion_id,
        champion_reserved_budget=round(champion_reserve, 12),
        champion_spent_budget=round(target_spend[champion_id], 12),
        target_attack_counts=dict(sorted(target_counts.items())),
        target_budget={key: round(value, 12) for key, value in sorted(target_spend.items())},
        attack_types=attack_types,
        independent_groups=groups,
        blockers=tuple(sorted(blockers)),
        status="READY" if not blockers else "INCOMPLETE",
        plan_hash=_sha(payload),
    )


def execute_registered_attacks(
    plan: FalsificationPlan,
    observations: Sequence[AttackObservation],
) -> FalsificationExecutionReport:
    """Evaluate exact precommitted attack observations; post-hoc attacks are rejected."""
    if not isinstance(plan, FalsificationPlan):
        raise ValueError("plan must be a FalsificationPlan")
    if plan.status != "READY" or plan.blockers:
        raise ValueError("cannot execute an incomplete falsification plan")
    if isinstance(observations, (str, bytes, bytearray)) or not isinstance(observations, Sequence):
        raise ValueError("observations must be a finite sequence")
    if len(observations) > _MAX_ITEMS:
        raise ValueError("observation limit exceeded")
    normalized = tuple(item.normalized() for item in observations)
    observation_ids = [item.attack_id for item in normalized]
    if len(set(observation_ids)) != len(observation_ids):
        raise ValueError("observation attack_id values must be unique")
    planned_ids = {item.attack_id for item in plan.selected_attacks}
    unknown = sorted(set(observation_ids) - planned_ids)
    if unknown:
        raise ValueError("post-hoc observation references an unplanned attack")

    by_attack = {item.attack_id: item for item in normalized}
    target_results = []
    falsified_targets = []
    survived_targets = []
    inconclusive_targets = []
    for target in plan.targets:
        attacks = tuple(
            item.attack_id for item in plan.selected_attacks if item.target_id == target.target_id
        )
        observed = [by_attack[item] for item in attacks if item in by_attack]
        falsifiers = tuple(sorted(item.attack_id for item in observed if item.status == "FALSIFIED"))
        if falsifiers:
            status = "FALSIFIED"
            falsified_targets.append(target.target_id)
        elif len(observed) != len(attacks):
            status = "INCOMPLETE_EXECUTION"
            inconclusive_targets.append(target.target_id)
        elif any(item.status in {"INCONCLUSIVE", "ERROR"} for item in observed):
            status = "INCONCLUSIVE"
            inconclusive_targets.append(target.target_id)
        elif attacks and all(item.status == "NOT_FALSIFIED" for item in observed):
            status = "SURVIVED_REGISTERED_ATTACKS"
            survived_targets.append(target.target_id)
        else:
            status = "INCOMPLETE_EXECUTION"
            inconclusive_targets.append(target.target_id)
        target_results.append(
            TargetAttackResult(
                target_id=target.target_id,
                status=status,
                attack_ids=tuple(sorted(attacks)),
                falsified_by=falsifiers,
            )
        )

    execution_complete = set(observation_ids) == planned_ids
    ordered_observations = tuple(sorted(normalized, key=lambda item: item.attack_id))
    ordered_results = tuple(sorted(target_results, key=lambda item: item.target_id))
    payload = {
        "plan_hash": plan.plan_hash,
        "target_results": [item.__dict__ for item in ordered_results],
        "observations": [item.__dict__ for item in ordered_observations],
        "execution_complete": execution_complete,
        "falsified_target_ids": sorted(falsified_targets),
        "survived_target_ids": sorted(survived_targets),
        "inconclusive_target_ids": sorted(inconclusive_targets),
        "truth_proven": False,
        "survival_is_truth": False,
        "scientific_verification_implied": False,
    }
    return FalsificationExecutionReport(
        plan_hash=plan.plan_hash,
        target_results=ordered_results,
        observations=ordered_observations,
        execution_complete=execution_complete,
        falsified_target_ids=tuple(sorted(falsified_targets)),
        survived_target_ids=tuple(sorted(survived_targets)),
        inconclusive_target_ids=tuple(sorted(inconclusive_targets)),
        report_hash=_sha(payload),
    )


def red_team_coverage(plan: FalsificationPlan) -> Mapping[str, Any]:
    """Machine-readable #36 attack coverage; never a quality/truth probability."""
    target_count = len(plan.targets)
    covered = sum(1 for value in plan.target_attack_counts.values() if value > 0)
    return {
        "status": plan.status,
        "target_coverage": (covered / target_count) if target_count else 0.0,
        "covered_targets": covered,
        "total_targets": target_count,
        "attack_types": list(plan.attack_types),
        "independent_groups": list(plan.independent_groups),
        "champion_target_id": plan.champion_target_id,
        "champion_reserve_met": (
            plan.champion_spent_budget + 1e-12 >= plan.champion_reserved_budget
        ),
        "blockers": list(plan.blockers),
        "planning_only": True,
        "truth_proven": False,
    }
