import pytest

from research_engine.hypothesis_evolution import (
    EvolutionPolicy,
    HypothesisVariant,
    run_evolution,
    select_generation,
)


def _v(
    hid,
    *,
    generation=0,
    parents=(),
    statement=None,
    mechanism=None,
    evidence=0.7,
    falsifiability=0.7,
    testability=0.7,
    novelty=0.5,
    contradiction=0.1,
    complexity=2.0,
):
    return HypothesisVariant(
        hypothesis_id=hid,
        statement=statement or f"{hid} predicts a measurable response under intervention",
        mechanism=mechanism or f"{hid} mechanism changes the measured response pathway",
        evidence_fit=evidence,
        falsifiability=falsifiability,
        testability=testability,
        novelty_screening=novelty,
        contradiction_penalty=contradiction,
        complexity=complexity,
        generation=generation,
        parent_ids=tuple(parents),
    )


def _roots():
    return (
        _v(
            "H0-A",
            statement="A predicts a temperature-linked response in the target system",
            mechanism="Thermal coupling changes the measured target-system response",
            evidence=0.72,
        ),
        _v(
            "H0-B",
            statement="B predicts a pressure-linked response in the target system",
            mechanism="Pressure coupling changes the measured target-system response",
            evidence=0.68,
        ),
    )


def test_generation_records_mutation_crossover_lineage_and_never_claims_truth():
    roots = _roots()
    proposals = (
        _v(
            "H1-M",
            generation=1,
            parents=("H0-A",),
            statement="Mutation predicts a nonlinear thermal response after intervention",
            mechanism="A thresholded thermal pathway amplifies the measured response",
            evidence=0.82,
            falsifiability=0.9,
            testability=0.9,
        ),
        _v(
            "H1-X",
            generation=1,
            parents=("H0-A", "H0-B"),
            statement="Crossover predicts a joint thermal-pressure response after intervention",
            mechanism="Thermal and pressure pathways interact to alter the measured response",
            evidence=0.84,
            falsifiability=0.88,
            testability=0.86,
        ),
    )
    result = select_generation(roots, proposals, generation=1)
    assert result.mutations_seen == 1
    assert result.crossovers_seen == 1
    assert result.truth_proven is False
    assert len(result.population_hash) == 64
    assert result.survivors
    assert all(score.truth_proven is False for score in result.scores)
    assert all(score.global_novelty_proven is False for score in result.scores)
    assert all(len(score.lineage_hash) == 64 for score in result.scores)


def test_unknown_missing_or_forged_parent_lineage_fails_closed():
    roots = _roots()
    with pytest.raises(ValueError, match="at least one parent"):
        select_generation(roots, [_v("H1", generation=1)], generation=1)
    with pytest.raises(ValueError, match="unknown parent"):
        select_generation(
            roots,
            [_v("H1", generation=1, parents=("DOES-NOT-EXIST",))],
            generation=1,
        )
    with pytest.raises(ValueError, match="current generation"):
        select_generation(
            roots,
            [_v("H2", generation=2, parents=("H0-A",))],
            generation=1,
        )
    with pytest.raises(ValueError, match="generation 0 roots"):
        _v("FORGED-ROOT", parents=("ghost-parent",)).validate()


def test_near_duplicate_is_suppressed_and_elimination_is_preserved():
    roots = _roots()
    duplicate = _v(
        "H1-DUP",
        generation=1,
        parents=("H0-A",),
        statement=roots[0].statement,
        mechanism=roots[0].mechanism,
        evidence=0.3,
        falsifiability=0.3,
        testability=0.3,
        novelty=0.2,
        contradiction=0.7,
        complexity=8.0,
    )
    distinct = _v(
        "H1-DISTINCT",
        generation=1,
        parents=("H0-B",),
        statement="Distinct variant predicts an oscillatory response after intervention",
        mechanism="A feedback loop produces repeated oscillations in the measured response",
    )
    result = select_generation(roots, [duplicate, distinct], generation=1)
    assert "H1-DUP" not in {item.hypothesis_id for item in result.survivors}
    reasons = {item.hypothesis_id: item.reason for item in result.eliminated}
    assert reasons["H1-DUP"].startswith("near_duplicate_of:")


def test_pareto_dominance_is_visible_not_silently_collapsed_into_one_score():
    roots = _roots()
    dominated = _v(
        "H1-WEAK",
        generation=1,
        parents=("H0-A",),
        statement="Weak variant predicts a delayed response in a secondary channel",
        mechanism="A secondary pathway slowly changes the delayed measured response",
        evidence=0.3,
        falsifiability=0.3,
        testability=0.3,
        novelty=0.2,
        contradiction=0.7,
        complexity=10.0,
    )
    dominant = _v(
        "H1-STRONG",
        generation=1,
        parents=("H0-B",),
        statement="Strong variant predicts a rapid response in a primary channel",
        mechanism="A primary pathway directly changes the rapidly measured response",
        evidence=0.9,
        falsifiability=0.9,
        testability=0.9,
        novelty=0.8,
        contradiction=0.1,
        complexity=1.0,
    )
    policy = EvolutionPolicy(population_size=4, elite_count=1)
    result = select_generation(roots, [dominated, dominant], generation=1, policy=policy)
    by_id = {score.hypothesis_id: score for score in result.scores}
    assert by_id["H1-WEAK"].pareto_dominated_by >= 1
    assert by_id["H1-STRONG"].pareto_dominated_by == 0


def test_population_is_bounded_and_eliminated_candidates_go_to_generation_graveyard():
    roots = _roots()
    proposals = tuple(
        _v(
            f"H1-{index}",
            generation=1,
            parents=("H0-A" if index % 2 == 0 else "H0-B",),
            statement=f"Variant {index} predicts response pattern channel {index} after intervention",
            mechanism=f"Mechanism pathway {index} changes response channel {index} measurably",
            evidence=0.55 + index * 0.03,
        )
        for index in range(8)
    )
    policy = EvolutionPolicy(population_size=3, elite_count=1)
    result = select_generation(roots, proposals, generation=1, policy=policy)
    assert len(result.survivors) <= 3
    assert len(result.eliminated) >= 1
    survivor_ids = {item.hypothesis_id for item in result.survivors}
    eliminated_ids = {item.hypothesis_id for item in result.eliminated}
    assert survivor_ids.isdisjoint(eliminated_ids)


def test_selection_is_deterministic_under_proposal_order_permutation():
    roots = _roots()
    proposals = (
        _v(
            "H1-A",
            generation=1,
            parents=("H0-A",),
            statement="Variant alpha predicts response alpha after controlled intervention",
            mechanism="Alpha pathway produces a measurable controlled response change",
        ),
        _v(
            "H1-B",
            generation=1,
            parents=("H0-B",),
            statement="Variant beta predicts response beta after controlled intervention",
            mechanism="Beta pathway produces a measurable controlled response change",
        ),
    )
    first = select_generation(roots, proposals, generation=1)
    second = select_generation(tuple(reversed(roots)), tuple(reversed(proposals)), generation=1)
    assert first.population_hash == second.population_hash
    assert [item.hypothesis_id for item in first.survivors] == [
        item.hypothesis_id for item in second.survivors
    ]
    assert [score.lineage_hash for score in first.scores] == [
        score.lineage_hash for score in second.scores
    ]


def test_invalid_scores_complexity_ids_and_self_parent_fail_closed():
    bad = _v("BAD", evidence=float("nan"))
    with pytest.raises(ValueError, match="finite"):
        bad.validate()
    with pytest.raises(ValueError, match="complexity"):
        _v("BAD2", complexity=101.0).validate()
    with pytest.raises(ValueError, match="own parent"):
        _v("BAD3", generation=1, parents=("BAD3",)).validate()
    with pytest.raises(ValueError, match="hypothesis_id"):
        _v("", statement="A sufficiently long statement", mechanism="valid mechanism").validate()


def test_policy_generation_population_and_proposal_limits_are_hard_bounds():
    with pytest.raises(ValueError, match="population_size"):
        EvolutionPolicy(population_size=1).validate()
    with pytest.raises(ValueError, match="max_generations"):
        EvolutionPolicy(max_generations=101).validate()
    with pytest.raises(ValueError, match="max_proposals_per_generation"):
        EvolutionPolicy(max_proposals_per_generation=1001).validate()
    with pytest.raises(ValueError, match="generation outside"):
        select_generation(
            _roots(),
            [_v("H101", generation=13, parents=("H0-A",))],
            generation=13,
            policy=EvolutionPolicy(max_generations=12),
        )

    proposals = tuple(
        _v(
            f"P{index}",
            generation=1,
            parents=("H0-A",),
            statement=f"Proposal {index} predicts a bounded measurable response",
            mechanism=f"Proposal mechanism {index} changes a bounded response pathway",
        )
        for index in range(4)
    )
    with pytest.raises(ValueError, match="proposal batch"):
        select_generation(
            _roots(),
            proposals,
            generation=1,
            policy=EvolutionPolicy(max_proposals_per_generation=3),
        )

    oversized_previous = _roots() + (
        _v(
            "H0-C",
            statement="C predicts a magnetic-linked response in the target system",
            mechanism="Magnetic coupling changes the measured target-system response",
        ),
    )
    with pytest.raises(ValueError, match="previous population"):
        select_generation(
            oversized_previous,
            [_v("H1-C", generation=1, parents=("H0-A",))],
            generation=1,
            policy=EvolutionPolicy(population_size=2, elite_count=1),
        )


def test_run_evolution_is_bounded_reproducible_and_requires_generation_zero_roots():
    roots = _roots()

    def factory(generation, population):
        first = population[0]
        second = population[-1]
        return (
            _v(
                f"G{generation}-M",
                generation=generation,
                parents=(first.hypothesis_id,),
                statement=f"Generation {generation} mutation predicts a measurable response shift",
                mechanism=f"Generation {generation} mutation pathway shifts the measured response",
            ),
            _v(
                f"G{generation}-X",
                generation=generation,
                parents=(first.hypothesis_id, second.hypothesis_id),
                statement=f"Generation {generation} crossover predicts a combined response shift",
                mechanism=f"Generation {generation} crossover pathways combine to shift response",
            ),
        )

    first = run_evolution(roots, factory, generations=3)
    second = run_evolution(roots, factory, generations=3)
    assert len(first) == 3
    assert [item.population_hash for item in first] == [item.population_hash for item in second]
    assert [item.generation for item in first] == [1, 2, 3]

    bad_roots = (
        _v("R1", generation=1, parents=("R2",)),
        _v("R2", generation=0),
    )
    with pytest.raises(ValueError, match="generation 0"):
        run_evolution(bad_roots, factory, generations=1)

    with pytest.raises(ValueError, match="generations outside"):
        run_evolution(
            roots,
            factory,
            generations=13,
            policy=EvolutionPolicy(max_generations=12),
        )


def test_run_evolution_rejects_non_sequence_and_oversized_factory_output():
    roots = _roots()

    def none_factory(_generation, _population):
        return None

    with pytest.raises(ValueError, match="finite sequence"):
        run_evolution(roots, none_factory, generations=1)

    def huge_factory(generation, _population):
        return tuple(
            _v(
                f"HUGE-{index}",
                generation=generation,
                parents=("H0-A",),
                statement=f"Huge proposal {index} predicts a measurable bounded response",
                mechanism=f"Huge proposal mechanism {index} changes the bounded response",
            )
            for index in range(4)
        )

    with pytest.raises(ValueError, match="proposal batch"):
        run_evolution(
            roots,
            huge_factory,
            generations=1,
            policy=EvolutionPolicy(max_proposals_per_generation=3),
        )


def test_duplicate_ids_and_current_or_future_previous_variants_are_rejected():
    roots = _roots()
    duplicate = _v("H0-A", generation=1, parents=("H0-B",))
    with pytest.raises(ValueError, match="unique across previous and proposals"):
        select_generation(roots, [duplicate], generation=1)

    future_previous = (
        _v("FUTURE", generation=2, parents=("H0-B",)),
        roots[1],
    )
    proposal = _v("H1", generation=1, parents=("H0-B",))
    with pytest.raises(ValueError, match="earlier generation"):
        select_generation(future_previous, [proposal], generation=1)
