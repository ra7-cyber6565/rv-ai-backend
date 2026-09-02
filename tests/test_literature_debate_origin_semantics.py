"""Production #103 must never confuse independent works with source origins."""
from __future__ import annotations

from research_engine.literature_debate_guard import GuardedAutonomousLiteratureDebate
from research_engine.models import EvidencePack, Passage, SourceRecord, SourceType


QUESTION = "Does intervention X improve outcome Y and why do studies disagree?"


def _row(sid: str, title: str, text: str, doi: str) -> SourceRecord:
    return SourceRecord(
        source_id=sid,
        title=title,
        url=f"https://same-journal.example/articles/{sid.lower()}",
        doi=doi,
        snippet=text,
        authors=[f"Author {sid}"],
        source_type=SourceType.PAPER,
        read_level="full_text",
        full_text_chars=len(text),
        relevance_score=0.9,
        quality_score=0.85,
        peer_reviewed=True,
    )


def _same_origin_three_work_pack() -> EvidencePack:
    rows = [
        _row(
            "S1",
            "Mechanistic intervention X study",
            "The controlled experiment showed intervention X improved outcome Y because the measured mediator increased.",
            "10.5151/mechanism.1",
        ),
        _row(
            "S2",
            "Methodological critique of intervention X",
            "However, a methodological limitation and selection bias could explain the reported improvement.",
            "10.5151/critique.2",
        ),
        _row(
            "S3",
            "Independent replication of intervention X",
            "An independent replication did not confirm the reported improvement under the preregistered protocol.",
            "10.5151/replication.3",
        ),
    ]
    return EvidencePack(
        question=QUESTION,
        sources=rows,
        passages=[Passage(row.source_id, row.snippet) for row in rows],
    )


def test_guarded_debate_readiness_counts_works_but_reports_one_origin():
    report = GuardedAutonomousLiteratureDebate().reconstruct(
        QUESTION, _same_origin_three_work_pack()
    )
    coverage = report["coverage"]

    # Three genuinely different studies may fill the three debate roles even
    # when one journal hosts all of them. Host concentration is not work identity.
    assert report["status"] == "DEBATE_MAP_READY"
    assert coverage["independent_current_works"] == 3
    assert coverage["reliable_argument_works"] == 3

    # But the audit must not rename those three DOI/work identities as origins.
    assert coverage["independent_current_origins"] == 1
    assert coverage["reliable_argument_origins"] == 1
    assert coverage["full_text_argument_origins"] == 1
    assert coverage["origin_concentration_warning"] is True
    assert report["honesty"]["debate_readiness_uses_independent_works"] is True
    assert report["honesty"]["origin_diversity_reported_separately"] is True
    assert report["honesty"]["doi_or_work_identity_counted_as_origin"] is False
    assert report["reliability_gate"]["readiness_identity"] == "independent_work"


def test_each_argument_exposes_work_and_origin_keys_separately():
    report = GuardedAutonomousLiteratureDebate().reconstruct(
        QUESTION, _same_origin_three_work_pack()
    )
    rows = [row for slot in report["role_slots"].values() for row in slot]
    assert len(rows) >= 3

    work_keys = {row["work_independence_key"] for row in rows if row["reliable_current_evidence"]}
    origin_keys = {row["source_origin_key"] for row in rows if row["reliable_current_evidence"]}
    assert len(work_keys) == 3
    assert origin_keys == {"domain:same-journal.example"}
    assert all(key.startswith("doi:") for key in work_keys)
