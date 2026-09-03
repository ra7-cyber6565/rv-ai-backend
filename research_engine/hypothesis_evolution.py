"""Auditable, bounded multi-generation search over explicit hypotheses.

The engine never invents a scientific claim by itself. A proposal factory (the
existing hypothesis generator, a human, or another bounded model) proposes
variants. This layer only validates lineage, suppresses near-duplicates, applies
multi-objective/Pareto selection with diversity pressure, preserves rejected
variants, and enforces hard population/generation/proposal budgets.

All scores are search-priority signals. They are never probabilities of truth,
proof of novelty, or evidence that an experiment worked in the real world.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Callable, Dict, Mapping, Sequence, Tuple


_WORD_RE = re.compile(r"[A-Za-z0-9\u0900-\u097f][A-Za-z0-9_\-\u0900-\u097f]*")


def _finite_unit(value: float, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise ValueError(f"{field} must be finite and in [0,1]")
    return number


def _bounded_nonnegative(value: float, field: str, maximum: float = 1000.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or not 0 <= number <= maximum:
        raise ValueError(f"{field} must be finite and in [0,{maximum}]")
    return number


def _tokens(text: str) -> set[str]:
    return {
        item.lower()
        for item in _WORD_RE.findall(str(text or ""))
        if len(item) > 2
    }


def _similarity(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return (
            1.0
            if str(left).strip().casefold() == str(right).strip().casefold()
            else 0.0
        )
    return len(a & b) / len(a | b)


def _canonical_hash(value: object) -> str:
    body = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True)
class HypothesisVariant:
    hypothesis_id: str
    statement: str
    mechanism: str
    evidence_fit: float
    falsifiability: float
    testability: float
    novelty_screening: float
    contradiction_penalty: float
    complexity: float
    generation: int
    parent_ids: Tuple[str, ...] = ()
    source: str = "proposal"

    def validate(self) -> None:
        hid = str(self.hypothesis_id or "").strip()
        if not hid or len(hid) > 200:
            raise ValueError("hypothesis_id is required and bounded")
        statement = " ".join(str(self.statement or "").split())
        mechanism = " ".join(str(self.mechanism or "").split())
        if len(statement) < 12 or len(statement) > 4000:
            raise ValueError("statement must be 12..4000 characters")
        if len(mechanism) < 8 or len(mechanism) > 4000:
            raise ValueError("mechanism must be 8..4000 characters")
        for field in (
            "evidence_fit",
            "falsifiability",
            "testability",
            "novelty_screening",
            "contradiction_penalty",
        ):
            _finite_unit(getattr(self, field), field)
        _bounded_nonnegative(self.complexity, "complexity", 100.0)
        if not isinstance(self.generation, int) or self.generation < 0:
            raise ValueError("generation must be a non-negative integer")
        parents = tuple(str(item or "").strip() for item in self.parent_ids)
        if any(not item or len(item) > 200 for item in parents):
            raise ValueError("parent_ids must be non-empty bounded ids")
        if len(parents) != len(set(parents)):
            raise ValueError("parent_ids cannot contain duplicates")
        if hid in parents:
            raise ValueError("hypothesis cannot be its own parent")
        if self.generation == 0 and parents:
            raise ValueError("generation 0 roots cannot declare parents")
        if self.generation > 0 and not parents:
            raise ValueError("evolved variants must declare at least one parent")


@dataclass(frozen=True)
class EvolutionPolicy:
    population_size: int = 6
    elite_count: int = 2
    duplicate_similarity: float = 0.88
    diversity_weight: float = 0.18
    complexity_weight: float = 0.08
    contradiction_weight: float = 0.20
    max_generations: int = 12
    max_proposals_per_generation: int = 64

    def validate(self) -> None:
        if (
            not isinstance(self.population_size, int)
            or not 2 <= self.population_size <= 100
        ):
            raise ValueError("population_size must be 2..100")
        if (
            not isinstance(self.elite_count, int)
            or not 1 <= self.elite_count < self.population_size
        ):
            raise ValueError("elite_count must be >=1 and below population_size")
        duplicate = _finite_unit(self.duplicate_similarity, "duplicate_similarity")
        if not 0.5 <= duplicate <= 1.0:
            raise ValueError("duplicate_similarity must be 0.5..1")
        _bounded_nonnegative(self.diversity_weight, "diversity_weight", 10.0)
        _bounded_nonnegative(self.complexity_weight, "complexity_weight", 10.0)
        _bounded_nonnegative(
            self.contradiction_weight, "contradiction_weight", 10.0
        )
        if (
            not isinstance(self.max_generations, int)
            or not 1 <= self.max_generations <= 100
        ):
            raise ValueError("max_generations must be 1..100")
        if (
            not isinstance(self.max_proposals_per_generation, int)
            or not 1 <= self.max_proposals_per_generation <= 1000
        ):
            raise ValueError("max_proposals_per_generation must be 1..1000")


@dataclass(frozen=True)
class VariantScore:
    hypothesis_id: str
    base_priority: float
    diversity_bonus: float
    final_priority: float
    pareto_dominated_by: int
    lineage_depth: int
    lineage_hash: str
    truth_proven: bool = False
    global_novelty_proven: bool = False


@dataclass(frozen=True)
class EliminatedVariant:
    hypothesis_id: str
    generation: int
    reason: str
    final_priority: float


@dataclass(frozen=True)
class EvolutionGeneration:
    generation: int
    survivors: Tuple[HypothesisVariant, ...]
    scores: Tuple[VariantScore, ...]
    eliminated: Tuple[EliminatedVariant, ...]
    mutations_seen: int
    crossovers_seen: int
    population_hash: str
    truth_proven: bool = False


def _base_priority(variant: HypothesisVariant, policy: EvolutionPolicy) -> float:
    positive = (
        0.32 * float(variant.evidence_fit)
        + 0.24 * float(variant.falsifiability)
        + 0.24 * float(variant.testability)
        + 0.20 * float(variant.novelty_screening)
    )
    complexity_penalty = policy.complexity_weight * (
        float(variant.complexity) / (1.0 + float(variant.complexity))
    )
    contradiction_penalty = (
        policy.contradiction_weight * float(variant.contradiction_penalty)
    )
    return positive - complexity_penalty - contradiction_penalty


def _dominates(left: HypothesisVariant, right: HypothesisVariant) -> bool:
    """Pareto dominance across benefits and penalties without scalar weights."""
    left_benefits = (
        left.evidence_fit,
        left.falsifiability,
        left.testability,
        left.novelty_screening,
    )
    right_benefits = (
        right.evidence_fit,
        right.falsifiability,
        right.testability,
        right.novelty_screening,
    )
    left_costs = (left.contradiction_penalty, left.complexity)
    right_costs = (right.contradiction_penalty, right.complexity)
    no_worse = (
        all(a >= b for a, b in zip(left_benefits, right_benefits))
        and all(a <= b for a, b in zip(left_costs, right_costs))
    )
    strictly_better = (
        any(a > b for a, b in zip(left_benefits, right_benefits))
        or any(a < b for a, b in zip(left_costs, right_costs))
    )
    return no_worse and strictly_better


def _validate_previous_lineage(
    previous: Sequence[HypothesisVariant], generation: int
) -> Dict[str, HypothesisVariant]:
    known = {item.hypothesis_id: item for item in previous}
    if len(known) != len(previous):
        raise ValueError("previous hypothesis ids must be unique")
    for item in previous:
        if item.generation >= generation:
            raise ValueError("previous variants must come from an earlier generation")
        # Parents that survived in the current population must be older than the
        # child. Missing parents are allowed because the elimination history is
        # preserved outside the survivor population.
        for parent_id in item.parent_ids:
            parent = known.get(parent_id)
            if parent is not None and parent.generation >= item.generation:
                raise ValueError("lineage parent must come from an earlier generation")
    # Detect cycles among all parent edges still present in this survivor set.
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(hid: str) -> None:
        if hid in visited:
            return
        if hid in visiting:
            raise ValueError("cyclic hypothesis lineage detected")
        visiting.add(hid)
        item = known[hid]
        for parent_id in item.parent_ids:
            if parent_id in known:
                visit(parent_id)
        visiting.remove(hid)
        visited.add(hid)

    for hid in sorted(known):
        visit(hid)
    return known


def _lineage_depth(
    variant: HypothesisVariant, known: Mapping[str, HypothesisVariant]
) -> int:
    """Best auditable depth from surviving ancestors; never invent missing edges."""
    if not variant.parent_ids:
        return 0
    visiting: set[str] = set()

    def depth(hid: str) -> int:
        if hid in visiting:
            raise ValueError("cyclic hypothesis lineage detected")
        parent = known.get(hid)
        if parent is None:
            return 1
        if not parent.parent_ids:
            return 1
        visiting.add(hid)
        try:
            return 1 + max(depth(parent_id) for parent_id in parent.parent_ids)
        finally:
            visiting.remove(hid)

    return max(depth(parent_id) for parent_id in variant.parent_ids)


def select_generation(
    previous_population: Sequence[HypothesisVariant],
    proposals: Sequence[HypothesisVariant],
    *,
    generation: int,
    policy: EvolutionPolicy | None = None,
) -> EvolutionGeneration:
    """Select one bounded generation and preserve every rejection reason."""
    policy = policy or EvolutionPolicy()
    policy.validate()
    if (
        not isinstance(generation, int)
        or not 1 <= generation <= policy.max_generations
    ):
        raise ValueError("generation outside policy bounds")
    if not previous_population:
        raise ValueError("previous_population cannot be empty")
    if not proposals:
        raise ValueError("at least one new proposal is required")
    if len(previous_population) > policy.population_size:
        raise ValueError("previous population exceeds configured population_size")
    if len(proposals) > policy.max_proposals_per_generation:
        raise ValueError("proposal batch exceeds max_proposals_per_generation")

    previous = list(previous_population)
    new = list(proposals)
    for variant in previous + new:
        variant.validate()

    known = _validate_previous_lineage(previous, generation)
    new_ids = [item.hypothesis_id for item in new]
    if len(new_ids) != len(set(new_ids)):
        raise ValueError("proposal hypothesis ids must be unique")
    overlap = set(known) & set(new_ids)
    if overlap:
        raise ValueError("hypothesis ids must be unique across previous and proposals")

    for variant in new:
        if variant.generation != generation:
            raise ValueError("new proposals must be stamped with the current generation")
        missing = [parent for parent in variant.parent_ids if parent not in known]
        if missing:
            raise ValueError(
                f"proposal references unknown parent(s): {', '.join(sorted(missing))}"
            )
        for parent_id in variant.parent_ids:
            if known[parent_id].generation >= variant.generation:
                raise ValueError("lineage parent must come from an earlier generation")

    all_variants = previous + new
    # Near-duplicate suppression is deterministic. A better-priority duplicate
    # may replace the earlier candidate; the loser remains in the graveyard.
    candidates: list[HypothesisVariant] = []
    duplicate_eliminated: list[EliminatedVariant] = []
    for variant in sorted(all_variants, key=lambda item: item.hypothesis_id):
        duplicate_of = None
        for existing in candidates:
            similarity = _similarity(
                f"{variant.statement} {variant.mechanism}",
                f"{existing.statement} {existing.mechanism}",
            )
            if similarity >= policy.duplicate_similarity:
                duplicate_of = existing
                break
        if duplicate_of is None:
            candidates.append(variant)
            continue
        left_score = _base_priority(variant, policy)
        right_score = _base_priority(duplicate_of, policy)
        if (left_score, variant.hypothesis_id) > (
            right_score,
            duplicate_of.hypothesis_id,
        ):
            candidates.remove(duplicate_of)
            candidates.append(variant)
            duplicate_eliminated.append(
                EliminatedVariant(
                    duplicate_of.hypothesis_id,
                    generation,
                    f"near_duplicate_of:{variant.hypothesis_id}",
                    right_score,
                )
            )
        else:
            duplicate_eliminated.append(
                EliminatedVariant(
                    variant.hypothesis_id,
                    generation,
                    f"near_duplicate_of:{duplicate_of.hypothesis_id}",
                    left_score,
                )
            )

    known_all = {item.hypothesis_id: item for item in all_variants}
    base_scores = {
        item.hypothesis_id: _base_priority(item, policy) for item in candidates
    }
    dominated_by = {
        item.hypothesis_id: sum(
            1
            for challenger in candidates
            if challenger.hypothesis_id != item.hypothesis_id
            and _dominates(challenger, item)
        )
        for item in candidates
    }

    ordered = sorted(
        candidates,
        key=lambda item: (
            dominated_by[item.hypothesis_id],
            -base_scores[item.hypothesis_id],
            item.hypothesis_id,
        ),
    )
    selected = ordered[: min(policy.elite_count, len(ordered))]
    remaining = [item for item in ordered if item not in selected]
    final_priority: Dict[str, float] = {}
    diversity_bonus: Dict[str, float] = {}

    for item in selected:
        bonus = (
            1.0
            if len(selected) == 1
            else min(
                1.0,
                min(
                    1.0 - _similarity(item.statement, other.statement)
                    for other in selected
                    if other.hypothesis_id != item.hypothesis_id
                ),
            )
        )
        diversity_bonus[item.hypothesis_id] = bonus
        final_priority[item.hypothesis_id] = (
            base_scores[item.hypothesis_id] + policy.diversity_weight * bonus
        )

    while remaining and len(selected) < policy.population_size:
        rescored = []
        for item in remaining:
            diversity = (
                min(
                    1.0 - _similarity(item.statement, chosen.statement)
                    for chosen in selected
                )
                if selected
                else 1.0
            )
            score = (
                base_scores[item.hypothesis_id]
                + policy.diversity_weight * diversity
                - 0.02 * dominated_by[item.hypothesis_id]
            )
            rescored.append((score, diversity, item))
        rescored.sort(key=lambda row: (-row[0], -row[1], row[2].hypothesis_id))
        score, diversity, winner = rescored[0]
        selected.append(winner)
        remaining.remove(winner)
        final_priority[winner.hypothesis_id] = score
        diversity_bonus[winner.hypothesis_id] = diversity

    eliminated = list(duplicate_eliminated)
    for item in candidates:
        if item not in selected:
            eliminated.append(
                EliminatedVariant(
                    hypothesis_id=item.hypothesis_id,
                    generation=generation,
                    reason="population_limit_or_multi_objective_dominance",
                    final_priority=base_scores[item.hypothesis_id],
                )
            )

    scores: list[VariantScore] = []
    for item in selected:
        lineage = {
            "id": item.hypothesis_id,
            "generation": item.generation,
            "parents": item.parent_ids,
            "statement": " ".join(item.statement.split()),
            "mechanism": " ".join(item.mechanism.split()),
        }
        scores.append(
            VariantScore(
                hypothesis_id=item.hypothesis_id,
                base_priority=base_scores[item.hypothesis_id],
                diversity_bonus=diversity_bonus.get(item.hypothesis_id, 0.0),
                final_priority=final_priority.get(
                    item.hypothesis_id, base_scores[item.hypothesis_id]
                ),
                pareto_dominated_by=dominated_by[item.hypothesis_id],
                lineage_depth=_lineage_depth(item, known_all),
                lineage_hash=_canonical_hash(lineage),
            )
        )
    scores.sort(key=lambda item: (-item.final_priority, item.hypothesis_id))
    order = {score.hypothesis_id: index for index, score in enumerate(scores)}
    selected.sort(key=lambda item: order[item.hypothesis_id])
    eliminated.sort(key=lambda item: (item.reason, item.hypothesis_id))

    mutations_seen = sum(len(item.parent_ids) == 1 for item in new)
    crossovers_seen = sum(len(item.parent_ids) >= 2 for item in new)
    population_hash = _canonical_hash(
        {
            "generation": generation,
            "policy": {
                "population_size": policy.population_size,
                "elite_count": policy.elite_count,
                "duplicate_similarity": policy.duplicate_similarity,
                "diversity_weight": policy.diversity_weight,
                "complexity_weight": policy.complexity_weight,
                "contradiction_weight": policy.contradiction_weight,
                "max_generations": policy.max_generations,
                "max_proposals_per_generation": policy.max_proposals_per_generation,
            },
            "survivors": [
                {
                    "id": item.hypothesis_id,
                    "generation": item.generation,
                    "parents": item.parent_ids,
                    "statement": item.statement,
                    "mechanism": item.mechanism,
                }
                for item in selected
            ],
            "scores": [
                {
                    "id": score.hypothesis_id,
                    "base": score.base_priority,
                    "diversity": score.diversity_bonus,
                    "final": score.final_priority,
                    "dominated_by": score.pareto_dominated_by,
                    "lineage": score.lineage_hash,
                }
                for score in scores
            ],
            "eliminated": [
                (item.hypothesis_id, item.reason) for item in eliminated
            ],
        }
    )
    return EvolutionGeneration(
        generation=generation,
        survivors=tuple(selected),
        scores=tuple(scores),
        eliminated=tuple(eliminated),
        mutations_seen=mutations_seen,
        crossovers_seen=crossovers_seen,
        population_hash=population_hash,
    )


ProposalFactory = Callable[
    [int, Tuple[HypothesisVariant, ...]],
    Sequence[HypothesisVariant],
]


def run_evolution(
    initial_population: Sequence[HypothesisVariant],
    proposal_factory: ProposalFactory,
    *,
    generations: int,
    policy: EvolutionPolicy | None = None,
) -> Tuple[EvolutionGeneration, ...]:
    """Execute a reproducibly bounded number of generations."""
    policy = policy or EvolutionPolicy()
    policy.validate()
    if not callable(proposal_factory):
        raise ValueError("proposal_factory must be callable")
    if (
        not isinstance(generations, int)
        or not 1 <= generations <= policy.max_generations
    ):
        raise ValueError("generations outside policy bounds")
    population = tuple(initial_population)
    if len(population) < 2:
        raise ValueError("initial population must contain at least two hypotheses")
    if len(population) > policy.population_size:
        raise ValueError("initial population exceeds configured population_size")
    for item in population:
        item.validate()
        if item.generation != 0:
            raise ValueError("initial population must be generation 0")
        if item.parent_ids:
            raise ValueError("generation 0 roots cannot declare parents")
    if len({item.hypothesis_id for item in population}) != len(population):
        raise ValueError("initial hypothesis ids must be unique")

    history = []
    for generation in range(1, generations + 1):
        try:
            raw = proposal_factory(generation, population)
            proposals = tuple(raw)
        except TypeError as exc:
            raise ValueError("proposal_factory must return a finite sequence") from exc
        if len(proposals) > policy.max_proposals_per_generation:
            raise ValueError("proposal batch exceeds max_proposals_per_generation")
        result = select_generation(
            population,
            proposals,
            generation=generation,
            policy=policy,
        )
        history.append(result)
        population = result.survivors
    return tuple(history)
