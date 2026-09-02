"""Fail-closed tests for the production #103 debate reliability facade."""
from __future__ import annotations

from research_engine.advanced_discovery_integrated import AutonomousLiteratureDebate as WiredDebate
from research_engine.literature_debate_guard import (
    GuardedAutonomousLiteratureDebate,
    source_reliability,
)
from research_engine.models import EvidencePack, Passage, SourceRecord, SourceType


QUESTION = "Does intervention X improve outcome Y, and what does the literature dispute?"


def _source(
    sid: str,
    text: str,
    *,
    read_level: str = "full_text",
    relevance: float = 0.9,
    quality: float = 0.8,
    peer_reviewed: bool | None = True,
    primary: bool | None = None,
    retracted: bool | None = None,
) -> SourceRecord:
    row = SourceRecord(
        source_id=sid,
        title=f"Study {sid}",
        url=f"https://journal-{sid.lower()}.example/paper",
        snippet=text,
        authors=[f"Author {sid}"],
        source_type=SourceType.PAPER,
        read_level=read_level,
        full_text_chars=len(text) if read_level == "full_text" else 0,
        relevance_score=relevance,
        quality_score=quality,
        peer_reviewed=peer_reviewed,
        is_primary=primary,
        retracted=retracted,
    )
    return row


def _pack(rows) -> EvidencePack:
    rows = list(rows)
    return EvidencePack(
        question=QUESTION,
        sources=rows,
        passages=[Passage(row.source_id, row.snippet) for row in rows],
    )


def _three_roles(**kwargs):
    return [
        _source(
            "S1",
            "The controlled experiment showed that intervention X improved outcome Y because the measured mediator increased.",
            **kwargs,
        ),
        _source(
            "S2",
            "However, a methodological limitation and selection bias could explain the reported effect.",
            **kwargs,
        ),
        _source(
            "S3",
            "An independent replication did not confirm the reported improvement under the preregistered protocol.",
            **kwargs,
        ),
    ]


def test_production_advanced_integration_imports_guarded_debate():
    assert WiredDebate is GuardedAutonomousLiteratureDebate


def test_three_good_independent_sources_can_still_make_ready_debate():
    report = GuardedAutonomousLiteratureDebate().reconstruct(
        QUESTION,
        _pack(_three_roles()),
    )

    assert report["status"] == "DEBATE_MAP_READY"
    assert all(report["role_presence_grounded_available_text"].values())
    assert all(report["role_presence_reliable"].values())
    assert report["missing_roles_in_available_text"] == []
    assert report["missing_roles_for_ready_debate"] == []
    assert report["coverage"]["reliable_argument_origins"] == 3
    assert report["honesty"]["reliability_requires_depth_relevance_and_quality"] is True
    assert report["honesty"]["grounded_presence_separate_from_readiness"] is True
    assert report["maturity_proof"]["quality_and_depth_reliability_gate"] is True


def test_search_snippets_remain_visible_but_cannot_fake_ready_debate():
    report = GuardedAutonomousLiteratureDebate().reconstruct(
        QUESTION,
        _pack(_three_roles(read_level="snippet")),
    )

    assert report["status"] == "PARTIAL_DEBATE"
    assert report["coverage"]["arguments_total"] >= 3
    assert report["coverage"]["arguments_reliable_current"] == 0
    assert report["coverage"]["reliable_argument_origins"] == 0
    # The arguments really are present in available text. Only readiness is
    # blocked. This distinction prevents an honesty field from changing meaning.
    assert all(report["role_presence_grounded_available_text"].values())
    assert report["missing_roles_in_available_text"] == []
    assert not any(report["role_presence_reliable"].values())
    assert set(report["missing_roles_for_ready_debate"]) == {
        "Researcher A reasoning",
        "Researcher B critique",
        "Researcher C replication failure",
    }
    reasons = {
        row["reliability_reason"]
        for role in report["role_slots"].values()
        for row in role
    }
    assert reasons == {"access_depth_snippet_too_shallow_for_readiness"}
    assert report["honesty"]["shallow_or_low_quality_arguments_count_as_reliable"] is False


def test_full_text_with_unestablished_quality_does_not_count_as_reliable():
    rows = _three_roles(quality=0.05, peer_reviewed=False, primary=False)
    report = GuardedAutonomousLiteratureDebate().reconstruct(QUESTION, _pack(rows))

    assert report["status"] == "PARTIAL_DEBATE"
    assert all(report["role_presence_grounded_available_text"].values())
    assert report["missing_roles_in_available_text"] == []
    assert report["coverage"]["arguments_reliable_current"] == 0
    assert all(
        row["reliability_reason"] == "source_quality_not_established"
        for role in report["role_slots"].values()
        for row in role
    )


def test_peer_reviewed_or_primary_metadata_can_establish_source_quality_signal():
    peer = _source(
        "S1",
        "The controlled experiment showed that outcome Y improved after intervention X.",
        quality=0.0,
        peer_reviewed=True,
    )
    primary = _source(
        "S2",
        "However, a methodological limitation makes the estimate uncertain.",
        quality=0.0,
        peer_reviewed=False,
        primary=True,
    )
    assert source_reliability(peer) == (True, "accepted_current_debate_evidence")
    assert source_reliability(primary) == (True, "accepted_current_debate_evidence")


def test_low_relevance_full_text_cannot_promote_role_readiness():
    rows = _three_roles()
    rows[2].relevance_score = 0.05
    report = GuardedAutonomousLiteratureDebate().reconstruct(QUESTION, _pack(rows))

    assert report["status"] == "PARTIAL_DEBATE"
    assert report["role_presence_grounded_available_text"]["researcher_c_replication_failure"] is True
    assert report["role_presence_reliable"]["researcher_a_reasoning"] is True
    assert report["role_presence_reliable"]["researcher_b_critique"] is True
    assert report["role_presence_reliable"]["researcher_c_replication_failure"] is False
    assert "Researcher C replication failure" in report["missing_roles_for_ready_debate"]
    failure = report["role_slots"]["researcher_c_replication_failure"][0]
    assert failure["reliability_reason"] == "relevance_below_readiness_gate"


def test_retracted_argument_stays_historical_and_never_becomes_reliable():
    source = _source(
        "S1",
        "The study showed a dramatic improvement and supports the proposed mechanism.",
        retracted=True,
    )
    report = GuardedAutonomousLiteratureDebate().reconstruct(QUESTION, _pack([source]))
    row = report["role_slots"]["researcher_a_reasoning"][0]

    assert row["retracted"] is True
    assert row["reliable_current_evidence"] is False
    assert row["reliability_reason"] == "retracted_historical_context_only"
    assert report["role_presence_grounded_available_text"]["researcher_a_reasoning"] is True
    assert report["role_presence_reliable"]["researcher_a_reasoning"] is False
    assert "Researcher A reasoning" not in report["missing_roles_in_available_text"]
    assert "Researcher A reasoning" in report["missing_roles_for_ready_debate"]
    assert report["status"] == "PARTIAL_DEBATE"
