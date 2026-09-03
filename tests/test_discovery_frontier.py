import pytest

from research_engine.discovery_frontier import (
    MechanismPattern,
    ResearchSignal,
    TransferTarget,
    build_discovery_frontier,
    evaluate_cross_domain_transfer,
    generate_autonomous_questions,
    generate_creative_candidates,
    rank_serendipity,
)


def _signal(**overrides):
    values = {
        "signal_id": "sig-1",
        "kind": "gap",
        "statement": "Independent replication evidence is missing for the central claim.",
        "domain": "physics",
        "source_refs": ("S1",),
        "provenance_ref": "coverage.gaps[0]",
        "provenance_complete": True,
        "unresolved": True,
        "relevance": 0.9,
        "surprise": 0.2,
        "evidence_strength": 0.2,
    }
    values.update(overrides)
    return ResearchSignal(**values)


def _mechanism(mid="M1", domain="biology", invariant="negative feedback"):
    return MechanismPattern(
        mechanism_id=mid,
        domain=domain,
        mechanism=f"{invariant} stabilizes the measured system after perturbation",
        invariants=(invariant, "bounded response"),
        assumptions=("measurement is calibrated",),
        evidence_refs=(f"{mid}-E1",),
    )


def _target(domain="control", *, evidence=True, disanalogies=("actuator latency differs",)):
    return TransferTarget(
        target_id="T1",
        domain=domain,
        context="A bounded feedback controller under an external perturbation",
        preserved_invariants=("negative feedback", "bounded response"),
        disanalogies=disanalogies,
        evidence_refs=("T-E1",) if evidence else (),
    )


def test_question_generator_uses_only_unresolved_structured_signals():
    questions = generate_autonomous_questions([
        _signal(signal_id="open"),
        _signal(signal_id="closed", unresolved=False),
    ])
    assert len(questions) == 1
    assert questions[0]["trigger_id"] == "open"
    assert questions[0]["candidate_only"] is True
    assert questions[0]["priority_is_truth_probability"] is False
    assert "replication evidence" in questions[0]["question"]


def test_question_output_is_deterministic_and_bounded():
    signals = [
        _signal(signal_id=f"s{i}", statement=f"Evidence gap number {i} remains unresolved.")
        for i in range(30)
    ]
    first = generate_autonomous_questions(signals, max_questions=5)
    second = generate_autonomous_questions(signals, max_questions=5)
    assert first == second
    assert len(first) == 5
    assert all(len(row["candidate_hash"]) == 64 for row in first)


def test_serendipity_without_provenance_never_becomes_candidate_discovery():
    signal = _signal(
        kind="unexpected_observation",
        surprise=0.95,
        relevance=0.95,
        evidence_strength=0.95,
        provenance_complete=False,
        provenance_ref="",
        source_refs=(),
    )
    result = rank_serendipity([signal])
    assert result[0]["state"] == "REVIEW_REQUIRED"
    assert result[0]["provenance_complete"] is False
    assert result[0]["truth_proven"] is False
    assert result[0]["global_novelty_proven"] is False


def test_serendipity_requires_surprise_and_relevance_even_with_provenance():
    signal = _signal(
        kind="unexpected_observation",
        surprise=0.1,
        relevance=0.95,
        evidence_strength=0.95,
    )
    assert rank_serendipity([signal])[0]["state"] == "REVIEW_REQUIRED"


def test_provenance_backed_unexpected_observation_is_only_a_candidate():
    signal = _signal(
        kind="unexpected_observation",
        surprise=0.9,
        relevance=0.8,
        evidence_strength=0.7,
    )
    result = rank_serendipity([signal])[0]
    assert result["state"] == "CANDIDATE_SERENDIPITY"
    assert result["candidate_discovery_not_established_fact"] is True
    assert result["truth_proven"] is False


def test_cross_domain_transfer_rejects_same_domain():
    with pytest.raises(ValueError, match="distinct source and target domains"):
        evaluate_cross_domain_transfer(_mechanism(domain="control"), _target(domain="control"))


def test_cross_domain_transfer_requires_explicit_disanalogies():
    with pytest.raises(ValueError, match="requires explicit disanalogies"):
        evaluate_cross_domain_transfer(_mechanism(), _target(disanalogies=()))


def test_cross_domain_transfer_without_target_evidence_fails_conceptual_gate():
    result = evaluate_cross_domain_transfer(_mechanism(), _target(evidence=False))
    assert result["conceptual_gate_passed"] is False
    assert result["target_evidence_refs"] == []
    assert result["truth_proven"] is False


def test_cross_domain_transfer_surfaces_unmatched_invariants_and_falsifier():
    target = TransferTarget(
        target_id="T2",
        domain="control",
        context="Controller with delayed feedback",
        preserved_invariants=("negative feedback",),
        disanalogies=("delay changes stability margin",),
        evidence_refs=("T2-E1",),
    )
    result = evaluate_cross_domain_transfer(_mechanism(), target)
    assert result["conceptual_gate_passed"] is True
    assert "bounded response" in result["unmatched_invariants"]
    assert "Reject the transfer" in result["falsifier"]
    assert result["candidate_discovery_not_established_fact"] is True


def test_creativity_recombines_only_supplied_evidence_backed_mechanisms():
    candidates = generate_creative_candidates(
        [_mechanism("M1"), _mechanism("M2", domain="engineering", invariant="energy balance")],
        target_domain="materials",
    )
    assert len(candidates) == 1
    row = candidates[0]
    assert row["mechanism_ids"] == ["M1", "M2"]
    assert row["requires_ablation"] is True
    assert row["requires_independent_validation"] is True
    assert row["truth_proven"] is False
    assert row["global_novelty_proven"] is False


def test_mechanism_without_evidence_is_rejected_before_creativity():
    invalid = MechanismPattern(
        mechanism_id="Mbad",
        domain="physics",
        mechanism="A bounded mechanism with no supplied evidence refs",
        invariants=("conservation",),
        assumptions=(),
        evidence_refs=(),
    )
    with pytest.raises(ValueError, match="requires evidence_refs"):
        generate_creative_candidates([invalid, _mechanism("M2")], target_domain="physics")


def test_frontier_report_is_deterministic_and_delegates_evolution():
    signals = [_signal()]
    mechanisms = [_mechanism("M1"), _mechanism("M2", domain="engineering", invariant="energy balance")]
    targets = [_target()]
    first = build_discovery_frontier(
        signals=signals,
        mechanisms=mechanisms,
        transfer_targets=targets,
        target_domain="materials",
    )
    second = build_discovery_frontier(
        signals=signals,
        mechanisms=mechanisms,
        transfer_targets=targets,
        target_domain="materials",
    )
    assert first == second
    assert first["evolutionary_search_delegate"] == "research_engine.hypothesis_evolution"
    assert first["evolutionary_search_executed_here"] is False
    assert first["candidate_discovery_label"] == "Candidate discovery — not established fact."
    assert first["truth_proven"] is False
    assert len(first["report_hash"]) == 64
