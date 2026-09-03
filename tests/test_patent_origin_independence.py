"""Patent prior-art recall must survive the work-vs-origin split."""
from __future__ import annotations

from research_engine.dedup import DeduplicationEngine
from research_engine.models import SourceRecord, SourceType
from research_engine.source_independence_guard import origin_key, work_independence_key


def _patent(sid: str, family: str, number: str) -> SourceRecord:
    return SourceRecord(
        source_id=sid,
        title=f"Distinct battery control invention {sid}",
        url=f"https://data.epo.org/publication/{number.lower()}",
        connector="epo",
        source_type=SourceType.PATENT,
        patent_meta={
            "number": number,
            "title": f"Distinct battery control invention {sid}",
            "family_id": family,
            "provider": "epo",
        },
        relevance_score=0.9,
        quality_score=0.7,
    )


def test_distinct_patent_families_share_registry_origin_but_keep_work_identity():
    rows = [
        _patent("S1", "FAM-1", "EP100001A1"),
        _patent("S2", "FAM-2", "EP100002A1"),
        _patent("S3", "FAM-3", "EP100003A1"),
        _patent("S4", "FAM-4", "EP100004A1"),
    ]

    assert {origin_key(row) for row in rows} == {"domain:data.epo.org"}
    assert len({work_independence_key(row) for row in rows}) == 4
    assert all(work_independence_key(row).startswith("patfam:") for row in rows)


def test_origin_cap_does_not_throw_away_distinct_prior_art_families():
    rows = [
        _patent("S1", "FAM-1", "EP100001A1"),
        _patent("S2", "FAM-2", "EP100002A1"),
        _patent("S3", "FAM-3", "EP100003A1"),
        _patent("S4", "FAM-4", "EP100004A1"),
    ]
    dedup = DeduplicationEngine()

    # max_per_origin=2 would cut ordinary same-domain papers to two, but an
    # official patent registry is a common host for many unrelated inventions.
    # Patent-family dedup already handles copies/jurisdictions of one invention.
    capped = dedup.cap_per_origin(rows, max_per_origin=2)
    assert [row.source_id for row in capped] == ["S1", "S2", "S3", "S4"]

    report = dedup.independence_report(rows)
    assert report["patent_independent_families"] == 4
    assert report["patent_registry_origins"] == 1
    assert report["independent_works"] == 4
    assert report["independent_origins"] == 1


def test_same_patent_family_still_collapses_before_ranking():
    a = _patent("S1", "FAM-SAME", "EP200001A1")
    b = _patent("S2", "FAM-SAME", "WO200001A1")
    unique = DeduplicationEngine().deduplicate([a, b])

    assert len(unique) == 1
    assert work_independence_key(a) == work_independence_key(b) == "patfam:famsame"
