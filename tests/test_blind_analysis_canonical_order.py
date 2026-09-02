from pathlib import Path

from research_engine.blind_analysis_attestor import (
    build_blind_analysis_execution_receipt,
    validate_blind_analysis_execution_receipt,
)
from research_engine.scientist_society import AgentSpec, ResearchTask


ROOT = Path(__file__).resolve().parents[1]


def _runner(label):
    def run(task):
        assert task.expected_result is None
        return {
            "answer": f"{label}: blinded conclusion",
            "evidence_ids": ["E1"],
            "confidence": 0.6,
        }
    return run


def _agents():
    return [
        (
            AgentSpec(
                "agent-a", "analyst", "runner-a", "family-a", "mechanistic", True
            ),
            _runner("A"),
        ),
        (
            AgentSpec(
                "agent-b", "replicator", "runner-b", "family-b", "statistical", True
            ),
            _runner("B"),
        ),
    ]


def _task():
    return ResearchTask(
        question="Does evidence support H1?",
        evidence=({"id": "E1", "value": 1.0},),
        hypothesis="H1",
        expected_result="HIDDEN-TARGET",
        constraints={"metric": "score"},
    )


def test_agent_configuration_order_does_not_change_manifest_or_protocol_hash(tmp_path):
    forward = build_blind_analysis_execution_receipt(
        repo_root=ROOT,
        task=_task(),
        agents=_agents(),
        created_at_epoch=20_000,
        repetitions=2,
    )
    reverse = build_blind_analysis_execution_receipt(
        repo_root=ROOT,
        task=_task(),
        agents=list(reversed(_agents())),
        created_at_epoch=20_000,
        repetitions=2,
    )

    assert forward["protocol"]["agent_manifest"] == reverse["protocol"]["agent_manifest"]
    assert forward["protocol"]["agent_manifest_hash"] == reverse["protocol"]["agent_manifest_hash"]
    assert forward["protocol"]["protocol_hash"] == reverse["protocol"]["protocol_hash"]
    assert [row["agent_id"] for row in reverse["protocol"]["agent_manifest"]] == [
        "agent-a",
        "agent-b",
    ]

    path = tmp_path / "reverse.json"
    import json
    path.write_text(json.dumps(reverse, sort_keys=True), encoding="utf-8")
    validated = validate_blind_analysis_execution_receipt(
        path,
        repo_root=ROOT,
        expected_revision=reverse["implementation_revision"],
        now=20_010,
    )
    assert validated.agent_manifest_hash == reverse["protocol"]["agent_manifest_hash"]
