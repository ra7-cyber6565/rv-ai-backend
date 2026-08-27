import pytest

from research_engine.scientist_society import (
    AgentSpec,
    DebateTournament,
    IndependentReplicationEngine,
    ReplicaSpec,
    ResearchTask,
    ScientistSociety,
    TournamentCandidate,
)


def test_scientist_society_runs_distinct_runners_and_blinds_selected_agent():
    seen = {}

    def scientist(task):
        seen["scientist_expected"] = task.expected_result
        return {"answer": "mechanism A", "evidence_ids": ["E1"], "confidence": 0.6}

    def skeptic(task):
        seen["skeptic_expected"] = task.expected_result
        return {"answer": "counterexample B", "evidence_ids": ["E2"], "confidence": 0.7}

    society = ScientistSociety([
        (
            AgentSpec("A1", "scientist", "runner-1", "model-X", "mechanistic", True),
            scientist,
        ),
        (
            AgentSpec("A2", "skeptic", "runner-2", "model-Y", "adversarial", False),
            skeptic,
        ),
    ])
    result = society.run(ResearchTask("Does H work?", expected_result="EXPECTED WINNER"))
    assert result.independent is True
    assert result.distinct_runner_ids == 2
    assert result.distinct_model_families == 2
    assert result.distinct_perspectives == 2
    assert result.blind_outputs == 1
    assert seen["scientist_expected"] is None
    assert seen["skeptic_expected"] == "EXPECTED WINNER"


def test_same_runner_identity_cannot_fake_independence_with_multiple_role_names():
    def runner(task):
        return {"answer": "same engine", "evidence_ids": []}

    society = ScientistSociety([
        (AgentSpec("A1", "scientist", "same-runner", "same-model", "p1"), runner),
        (AgentSpec("A2", "skeptic", "same-runner", "same-model", "p2"), runner),
    ])
    result = society.run(ResearchTask("question"))
    assert result.successful_agents == 2
    assert result.distinct_runner_ids == 1
    assert result.independent is False


def test_agent_failure_is_recorded_without_being_counted_as_independent_success():
    def good(task):
        return {"answer": "ok", "evidence_ids": ["E1"]}

    def bad(task):
        raise RuntimeError("provider failed")

    society = ScientistSociety([
        (AgentSpec("A1", "scientist", "r1", "m1", "p1"), good),
        (AgentSpec("A2", "skeptic", "r2", "m2", "p2"), bad),
    ])
    result = society.run(ResearchTask("question"))
    assert result.successful_agents == 1
    assert result.independent is False
    assert "RuntimeError" in result.outputs[1].error


def test_debate_tournament_withholds_author_identity_and_records_auditable_matches():
    packets = []

    def judge(packet):
        packets.append(packet)
        left = packet["candidate_A"]
        right = packet["candidate_B"]
        winner = "A" if len(left["evidence_ids"]) >= len(right["evidence_ids"]) else "B"
        return {
            "winner": winner,
            "confidence": 0.75,
            "reasons": ["more independent evidence"],
            "evidence_ids": list(left["evidence_ids"] + right["evidence_ids"]),
        }

    candidates = [
        TournamentCandidate("H1", "one", ("E1", "E2"), author_agent_id="AUTHOR-SECRET-1"),
        TournamentCandidate("H2", "two", ("E3",), author_agent_id="AUTHOR-SECRET-2"),
        TournamentCandidate("H3", "three", ("E4",), author_agent_id="AUTHOR-SECRET-3"),
    ]
    result = DebateTournament(judge).run(candidates)
    assert result.status == "WINNER_SELECTED"
    assert result.winner_id == "H1"
    assert len(result.matches) == 2
    assert all(len(match.judge_hash) == 64 for match in result.matches)
    assert all("AUTHOR-SECRET" not in repr(packet) for packet in packets)


def test_inconclusive_judge_stops_tournament_instead_of_inventing_winner():
    tournament = DebateTournament(
        lambda packet: {"winner": "INCONCLUSIVE", "confidence": 0.5, "reasons": ["tie"]}
    )
    result = tournament.run([
        TournamentCandidate("H1", "one", ()),
        TournamentCandidate("H2", "two", ()),
    ])
    assert result.status == "INCONCLUSIVE"
    assert result.winner_id is None


def test_replication_requires_distinct_runners_distinct_implementations_and_matching_metrics():
    def python_replica(protocol):
        assert protocol["hypothesis_id"] == "H1"
        return {"implementation_hash": "python-code", "metrics": {"effect": 0.51, "n": 100}}

    def independent_replica(protocol):
        return {"implementation_hash": "independent-code", "metrics": {"effect": 0.50, "n": 100}}

    engine = IndependentReplicationEngine([
        ReplicaSpec("R1", "python-runner", python_replica),
        ReplicaSpec("R2", "independent-runner", independent_replica),
    ])
    report = engine.run(
        {"hypothesis_id": "H1", "metric": "effect"},
        metric_tolerances={"effect": 0.02, "n": 0},
    )
    assert report.independently_replicated is True
    assert report.reasons == ()
    assert len({item.implementation_hash for item in report.results}) == 2


def test_replication_fails_when_same_implementation_is_reused_or_metric_disagrees():
    same = lambda protocol: {"implementation_hash": "same-code", "metrics": {"effect": 0.5}}
    reused = IndependentReplicationEngine([
        ReplicaSpec("R1", "runner-1", same),
        ReplicaSpec("R2", "runner-2", same),
    ]).run({"hypothesis_id": "H1"}, metric_tolerances={"effect": 0.01})
    assert reused.independently_replicated is False
    assert "distinct implementation hashes" in " ".join(reused.reasons)

    disagree = IndependentReplicationEngine([
        ReplicaSpec("R1", "runner-1", lambda p: {"implementation_hash": "a", "metrics": {"effect": 0.5}}),
        ReplicaSpec("R2", "runner-2", lambda p: {"implementation_hash": "b", "metrics": {"effect": 0.8}}),
    ]).run({"hypothesis_id": "H1"}, metric_tolerances={"effect": 0.01})
    assert disagree.independently_replicated is False
    assert "differs beyond tolerance" in " ".join(disagree.reasons)


def test_invalid_society_and_tournament_configs_fail_closed():
    runner = lambda task: {"answer": "x"}
    with pytest.raises(ValueError):
        ScientistSociety([(AgentSpec("A1", "role", "r1", "m1", "p1"), runner)])
    with pytest.raises(ValueError):
        ScientistSociety([
            (AgentSpec("A1", "role", "r1", "m1", "p1"), runner),
            (AgentSpec("A1", "role2", "r2", "m2", "p2"), runner),
        ])
    with pytest.raises(ValueError):
        DebateTournament(lambda packet: {"winner": "A"}).run([
            TournamentCandidate("H1", "one", ())
        ])
