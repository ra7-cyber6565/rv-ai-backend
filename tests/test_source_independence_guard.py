"""Regression tests for work-vs-origin evidence independence semantics."""
from __future__ import annotations

from research_engine.dedup import DeduplicationEngine
from research_engine.literature_debate import AutonomousLiteratureDebate
from research_engine.models import EvidencePack, Passage, SourceRecord, SourceType
from research_engine.source_independence_guard import origin_key, work_independence_key


QUESTION = "Does intervention X improve outcome Y and why do studies disagree?"


def _paper(
    sid: str,
    title: str,
    text: str,
    *,
    url: str,
    doi: str = "",
    publisher: str = "",
    connector: str = "",
) -> SourceRecord:
    return SourceRecord(
        source_id=sid,
        title=title,
        url=url,
        doi=doi,
        publisher=publisher,
        connector=connector,
        snippet=text,
        source_type=SourceType.PAPER,
        read_level="full_text",
        full_text_chars=len(text),
        relevance_score=0.9,
        quality_score=0.85,
        peer_reviewed=True,
    )


def test_two_distinct_papers_on_same_journal_domain_are_two_independent_works():
    a = _paper(
        "S1",
        "Controlled intervention X improves outcome Y in cohort A",
        "The controlled experiment showed intervention X improved outcome Y in cohort A.",
        url="https://journal.example/articles/a",
    )
    b = _paper(
        "S2",
        "Independent replication of intervention X in cohort B",
        "The independent replication did not confirm the original improvement in cohort B.",
        url="https://journal.example/articles/b",
    )
    pack = EvidencePack(question=QUESTION, sources=[a, b])

    assert a.domain == b.domain == "journal.example"
    assert origin_key(a) == origin_key(b) == "domain:journal.example"
    assert work_independence_key(a) != work_independence_key(b)
    assert a.independence_key != b.independence_key
    assert pack.independent_source_count == 2


def test_distinct_dois_do_not_bypass_same_domain_origin_cap():
    """DOI is a work identifier, never a free pass around publisher concentration."""
    rows = [
        _paper(
            f"S{i}",
            f"Distinct randomized intervention X study {i} with outcome Y",
            f"Study {i} independently measured intervention X and outcome Y under a distinct protocol.",
            url=f"https://journal.example/articles/{i}",
            doi=f"10.9999/intervention.{i}",
        )
        for i in range(1, 5)
    ]
    dedup = DeduplicationEngine()

    assert len({work_independence_key(row) for row in rows}) == 4
    assert {origin_key(row) for row in rows} == {"domain:journal.example"}
    assert len(dedup.cap_per_origin(rows, max_per_origin=2)) == 2
    report = dedup.independence_report(rows)
    assert report["independent_works"] == 4
    assert report["independent_origins"] == 1
    assert report["repeated_origins"] == {"domain:journal.example": 4}


def test_doi_only_records_use_registrant_prefix_as_last_resort_origin():
    a = _paper(
        "S1",
        "Intervention X trial one",
        "The first trial measured intervention X and outcome Y in a controlled cohort.",
        url="",
        doi="10.4242/trial.one",
    )
    b = _paper(
        "S2",
        "Intervention X trial two",
        "The second trial measured intervention X and outcome Y in an independent cohort.",
        url="",
        doi="10.4242/trial.two",
    )

    assert work_independence_key(a) != work_independence_key(b)
    assert origin_key(a) == origin_key(b) == "doi-prefix:10.4242"


def test_same_doi_mirrored_on_different_hosts_is_one_work_but_two_origins():
    a = _paper(
        "S1",
        "Intervention X trial",
        "The trial measured outcome Y after intervention X.",
        url="https://publisher.example/a",
        doi="https://doi.org/10.1234/ABC.55",
    )
    b = _paper(
        "S2",
        "Repository copy of intervention X trial",
        "The repository copy reports the same trial and outcome Y.",
        url="https://repository.example/copy",
        doi="doi:10.1234/abc.55",
    )
    pack = EvidencePack(question=QUESTION, sources=[a, b])
    report = DeduplicationEngine().independence_report([a, b])

    assert work_independence_key(a) == "doi:10.1234/abc.55"
    assert work_independence_key(a) == work_independence_key(b)
    assert origin_key(a) == "domain:publisher.example"
    assert origin_key(b) == "domain:repository.example"
    assert pack.independent_source_count == 1
    assert report["independent_works"] == 1
    assert report["independent_origins"] == 2
    assert report["repeated_works"] == {"doi:10.1234/abc.55": 2}


def test_same_doi_less_title_mirrored_on_different_hosts_is_one_work():
    title = "Longitudinal evidence for intervention X and outcome Y"
    a = _paper(
        "S1", title,
        "Longitudinal evidence showed a measurable association in the observed cohort.",
        url="https://publisher.example/article",
    )
    b = _paper(
        "S2", title,
        "A mirror of the same longitudinal article reports the same observed cohort.",
        url="https://archive.example/article-copy",
    )

    assert origin_key(a) != origin_key(b)
    assert work_independence_key(a) == work_independence_key(b)


def test_short_generic_titles_fall_back_to_url_not_whole_domain():
    a = _paper(
        "S1", "Results",
        "A detailed result page reports intervention X and measured outcome Y.",
        url="https://journal.example/articles/a",
    )
    b = _paper(
        "S2", "Results",
        "A different result page reports another experiment on outcome Y.",
        url="https://journal.example/articles/b",
    )

    assert work_independence_key(a).startswith("url:")
    assert work_independence_key(a) != work_independence_key(b)
    assert origin_key(a) == origin_key(b) == "domain:journal.example"


def test_origin_cap_preserves_same_domain_concentration_limit_without_collapsing_works():
    rows = [
        _paper(
            f"S{i}",
            f"Distinct intervention X study number {i} with outcome Y",
            f"Study {i} independently measured intervention X and outcome Y under a distinct protocol.",
            url=f"https://journal.example/articles/{i}",
        )
        for i in range(1, 5)
    ]
    dedup = DeduplicationEngine()

    capped = dedup.cap_per_origin(rows, max_per_origin=2)
    report = dedup.independence_report(rows)

    assert len({row.independence_key for row in rows}) == 4
    assert len(capped) == 2
    assert report["independent_works"] == 4
    assert report["independent_origins"] == 1
    assert report["independent_voices"] == 4
    assert report["repeated_origins"] == {"domain:journal.example": 4}


def test_literature_debate_keeps_three_same_domain_works_but_reports_one_origin():
    rows = [
        _paper(
            "S1",
            "Mechanistic study of intervention X and outcome Y",
            "The controlled experiment showed intervention X improved outcome Y because the measured mediator increased.",
            url="https://journal.example/articles/mechanism",
            doi="10.7777/mechanism.1",
        ),
        _paper(
            "S2",
            "Methodological critique of intervention X evidence",
            "However, a methodological limitation and selection bias could explain the reported improvement.",
            url="https://journal.example/articles/critique",
            doi="10.7777/critique.2",
        ),
        _paper(
            "S3",
            "Independent replication of intervention X outcome Y",
            "An independent replication did not confirm the reported improvement under the preregistered protocol.",
            url="https://journal.example/articles/replication",
            doi="10.7777/replication.3",
        ),
    ]
    pack = EvidencePack(
        question=QUESTION,
        sources=rows,
        passages=[Passage(row.source_id, row.snippet) for row in rows],
    )

    report = AutonomousLiteratureDebate().reconstruct(QUESTION, pack)
    coverage = report["coverage"]

    assert report["status"] == "DEBATE_MAP_READY"
    assert len({row.independence_key for row in rows}) == 3
    assert coverage["independent_current_works"] == 3
    assert coverage["independent_current_origins"] == 1
    assert coverage["reliable_argument_works"] == 3
    assert coverage["reliable_argument_origins"] == 1
    assert coverage["origin_concentration_warning"] is True
    assert report["role_presence_reliable"]["researcher_a_reasoning"] is True
    assert report["role_presence_reliable"]["researcher_b_critique"] is True
    assert report["role_presence_reliable"]["researcher_c_replication_failure"] is True
    assert report["role_presence"] == report["role_presence_reliable"]
    assert report["honesty"]["debate_readiness_uses_independent_works"] is True
    assert report["honesty"]["origin_diversity_reported_separately"] is True


def test_metadata_only_untitled_rows_from_same_origin_do_not_inflate_independence():
    a = SourceRecord(source_id="S1", url="https://catalog.example/item/a", source_type=SourceType.WEB)
    b = SourceRecord(source_id="S2", url="https://catalog.example/item/b", source_type=SourceType.WEB)
    # URLs are distinct work identifiers, so available pages are distinct. If
    # even URL/content identity is absent, fallback becomes the conservative
    # origin grouping instead of manufacturing independent voices.
    blank_a = SourceRecord(source_id="S3", url="", connector="catalog", source_type=SourceType.WEB)
    blank_b = SourceRecord(source_id="S4", url="", connector="catalog", source_type=SourceType.WEB)

    assert work_independence_key(a) != work_independence_key(b)
    assert origin_key(a) == origin_key(b) == "domain:catalog.example"
    assert work_independence_key(blank_a) == work_independence_key(blank_b) == "connector:catalog"
    assert origin_key(blank_a) == origin_key(blank_b) == "connector:catalog"
