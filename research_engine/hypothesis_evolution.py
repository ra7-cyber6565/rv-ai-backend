"""Auditable multi-generation search over explicitly proposed hypotheses.

The engine does not invent scientific claims by itself. A proposal factory (for
example the existing hypothesis generator, a human, or another bounded model)
submits candidate variants. This layer enforces lineage, duplicate suppression,
multi-objective selection, diversity pressure, bounded generations, and a
preserved elimination record.

Scores are search priorities, not probabilities of truth or proof of novelty.
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
    return {item.lower() for item in _WORD_RE.findall(str(text or "")) if len(item) > 2}


def _similarity(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 1.0 if str(left).strip().casefold() == str(right).strip().casefold() else 0.0
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
            "evidence_fit", "falsifiability", "testability",
            "novelty_screening", "contradiction_penalty",
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


@dataclass(frozen=True)
class EvolutionPolicy:
    population_size: int = 6
    elite_count: int = 2
    duplicate_similarity: float = 0.88
    diversity_weight: float = 0.18
    complexity_weight: float = 0.08
    contradiction_weight: float = 0.20
    max_generations: int = 12

    def validate(self) -> None:
        if not isinstance(self.population_size, int) or not 2 <= self.population_size <= 100:
            raise ValueError("population_size must be 2..100")
        if not isinstance(self.elite_count, int) or not 1 <= self.elite_count < self.population_size:
            raise ValueError("elite_count must be >=1 and below population_size")
        if not 0.5 <= _finite_unit(self.duplicate_similarity, "duplicate_similarity") <= 1.0:
            raise ValueError("duplicate_similarity must be 0.5..1")
        _bounded_nonnegative(self.diversity_weight, "diversity_weight", 10.0)
        _bounded_nonnegative(self.complexity_weight, "complexity_weight", 10.0)
        _bounded_nonnegative(self.contradiction_weight, "contradiction_weight", 10.0)
        if not isinstance(self.max_generations, int) or not 1 <= self.max_generations <= 100:
            raise ValueError("max_generations must be 1..100")


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
    contradiction_penalty = policy.contradiction_weight * float(variant.contradiction_penalty)
    return positive - complexity_penalty - contradiction_penalty


def _dominates(left: HypothesisVariant, right: HypothesisVariant) -> bool:
    """Pareto dominance across benefits and penalties, without scalar weights."""
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


def _lineage_depth(variant: HypothesisVariant, known: Mapping[str, HypothesisVariant]) -> int:
    if not variant.parent_ids:
        return 0
    visiting = set()

    def depth(hid: str) -> int:
        if hid in visiting:
            raise ValueError("cyclic hypothesis lineage detected")
        parent = known.get(hid)
        if parent is None or not parent.parent_ids:
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
    """Select one bounded generation while preserving lineage and rejected ideas."""
    policy = policy or EvolutionPolicy()
    policy.validate()
    if not isinstance(generation, int) or not 1 <= generation <= policy.max_generations:
        raise ValueError("generation outside policy bounds")
    if not previous_population:
        raise ValueError("previous_population cannot be empty")
    if not proposals:
        raise ValueError("at least one new proposal is required")

    previous = list(previous_population)
    new = list(proposals)
    all_variants = previous + new
    for variant in all_variants:
        variant.validate()
    ids = [variant.hypothesis_id for variant in all_variants]
    if len(ids) != len(set(ids)):
        raise ValueError("hypothesis ids must be unique across previous and proposals")
    if any(variant.generation > generation for variant in all_variants):
        raise ValueError("variant generation cannot be in the future")
    if any(variant.generation != generation for variant in new):
        raise ValueError("new proposals must be stamped with the current generation")

    known = {variant.hypothesis_id: variant for variant in previous}
    for variant in new:
        if not variant.parent_ids:
            raise ValueError("evolved proposals must declare at least one parent")
        missing = [parent for parent in variant.parent_ids if parent not in known]
        if missing:
            raise ValueError(f"proposal references unknown parent(s): {', '.join(missing)}")

    # First reject near-duplicates. The better scalar candidate survives, with
    # deterministic id tie-break; rejected variants remain in the graveyard.
    candidates = []
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
        if (left_score, variant.hypothesis_id) > (right_score, duplicate_of.hypothesis_id):
            candidates.remove(duplicate_of)
            candidates.append(variant)
            duplicate_eliminated.append(EliminatedVariant(
                duplicate_of.hypothesis_id,
                generation,
                f"near_duplicate_of:{variant.hypothesis_id}",
                right_score,
            ))
        else:
            duplicate_eliminated.append(EliminatedVariant(
                variant.hypothesis_id,
                generation,
                f"near_duplicate_of:{duplicate_of.hypothesis_id}",
                left_score,
            ))

    known_all = {variant.hypothesis_id: variant for variant in all_variants}
    base_scores = {variant.hypothesis_id: _base_priority(variant, policy) for variant in candidates}
    dominated_by = {
        variant.hypothesis_id: sum(
            1 for challenger in candidates
            if challenger.hypothesis_id != variant.hypothesis_id
            and _dominates(challenger, variant)
        )
        for variant in candidates
    }

    # Elites are protected by strong evidence/testability priority, but every
    # later selection also receives diversity credit relative to chosen items.
    ordered = sorted(
        candidates,
        key=lambda variant: (
            dominated_by[variant.hypothesis_id],
            -base_scores[variant.hypothesis_id],
            variant.hypothesis_id,
        ),
    )
    selected = ordered[: min(policy.elite_count, len(ordered))]
    remaining = [variant for variant in ordered if variant not in selected]
    final_priority: Dict[str, float] = {}
    diversity_bonus: Dict[str, float] = {}
    for variant in selected:
        bonus = 1.0 if len(selected) == 1 else min(
            1.0,
            min(
                1.0 - _similarity(variant.statement, other.statement)
                for other in selected if other.hypothesis_id != variant.hypothesis_id
            ),
        )
        diversity_bonus[variant.hypothesis_id] = bonus
        final_priority[variant.hypothesis_id] = (
            base_scores[variant.hypothesis_id] + policy.diversity_weight * bonus
        )

    while remaining and len(selected) < policy.population_size:
        rescored = []
        for variant in remaining:
            diversity = min(
                1.0 - _similarity(variant.statement, chosen.statement)
                for chosen in selected
            ) if selected else 1.0
            score = (
                base_scores[variant.hypothesis_id]
                + policy.diversity_weight * diversity
                - 0.02 * dominated_by[variant.hypothesis_id]
            )
            rescored.append((score, diversity, variant))
        rescored.sort(key=lambda item: (-item[0], -item[1], item[2].hypothesis_id))
        score, diversity, winner = rescored[0]
        selected.append(winner)
        remaining.remove(winner)
        final_priority[winner.hypothesis_id] = score
        diversity_bonus[winner.hypothesis_id] = diversity

    eliminated = list(duplicate_eliminated)
    for variant in candidates:
        if variant not in selected:
            eliminated.append(EliminatedVariant(
                hypothesis_id=variant.hypothesis_id,
                generation=generation,
                reason="population_limit_or_multi_objective_dominance",
                final_priority=base_scores[variant.hypothesis_id],
            ))

    scores = []
    for variant in selected:
        lineage = {
            "id": variant.hypothesis_id,
            "generation": variant.generation,
            "parents": variant.parent_ids,
            "statement": " ".join(variant.statement.split()),
            "mechanism": " ".join(variant.mechanism.split()),
        }
        scores.append(VariantScore(
            hypothesis_id=variant.hypothesis_id,
            base_priority=base_scores[variant.hypothesis_id],
            diversity_bonus=diversity_bonus.get(variant.hypothesis_id, 0.0),
            final_priority=final_priority.get(
                variant.hypothesis_id, base_scores[variant.hypothesis_id]
            ),
            pareto_dominated_by=dominated_by[variant.hypothesis_id],
            lineage_depth=_lineage_depth(variant, known_all),
            lineage_hash=_canonical_hash(lineage),
        ))
    scores.sort(key=lambda item: (-item.final_priority, item.hypothesis_id))
    selected_by_score = {score.hypothesis_id: index for index, score in enumerate(scores)}
    selected.sort(key=lambda variant: selected_by_score[variant.hypothesis_id])
    eliminated.sort(key=lambda item: (item.reason, item.hypothesis_id))

    mutations_seen = sum(len(item.parent_ids) == 1 for item in new)
    crossovers_seen = sum(len(item.parent_ids) >= 2 for item in new)
    population_hash = _canonical_hash({
        "generation": generation,
        "survivors": [
            {
                "id": variant.hypothesis_id,
                "generation": variant.generation,
                "parents": variant.parent_ids,
                "statement": variant.statement,
                "mechanism": variant.mechanism,
            }
            for variant in selected
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
    })
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
    """Execute bounded generations using an explicit external proposal factory."""
    policy = policy or EvolutionPolicy()
    policy.validate()
    if not callable(proposal_factory):
        raise ValueError("proposal_factory must be callable")
    if not isinstance(generations, int) or not 1 <= generations <= policy.max_generations:
        raise ValueError("generations outside policy bounds")
    population = tuple(initial_population)
    if len(population) < 2:
        raise ValueError("initial population must contain at least two hypotheses")
    for variant in population:
        variant.validate()
        if variant.generation != 0:
            raise ValueError("initial population must be generation 0")
    if len({item.hypothesis_id for item in population}) != len(population):
        raise ValueError("initial hypothesis ids must be unique")

    history = []
    for generation in range(1, generations + 1):
        proposals = tuple(proposal_factory(generation, population))
        result = select_generation(
            population,
            proposals,
            generation=generation,
            policy=policy,
        )
        history.append(result)
        population = result.survivors
    return tuple(history)
