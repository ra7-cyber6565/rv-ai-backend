import pytest
from research_engine.content_fetcher import ContentFetcher
from research_engine.models import EvidencePack, SourceRecord, SourceType

@pytest.mark.parametrize("level,read,total,expected", [
    ("abstract", 0, 0, 0),
    ("claims", 0, 0, 0),
    ("", 0, 0, 0),
    ("full_text", 3, 30, 0),
    ("full_text", 30, 30, 1),
    ("full_text", 0, 0, 1),
])
def test_whole_source_count_matches_recorded_read_scope(level, read, total, expected):
    source = SourceRecord(title="Controlled read-scope fixture", read_level=level,
                          full_text_chars=1000, pages_read=read, pages_total=total)
    pack = EvidencePack(question="Controlled audit", sources=[source])
    assert pack.full_text_read_count == expected
    assert pack.coverage_report()["full_text_sources_read"] == expected


@pytest.mark.parametrize("source_type,level,expected", [
    (SourceType.DOCUMENT, "full_text", 1),
    (SourceType.DOCUMENT, "abstract", 0),
    (SourceType.DOCUMENT, "", 0),
    (SourceType.PAPER, "full_text", 0),
])
def test_uploaded_processing_record_keeps_its_existing_contract(source_type, level, expected):
    source = SourceRecord(source_type=source_type, read_level=level)
    pack = EvidencePack(question="Controlled audit", sources=[source])
    assert pack.full_text_read_count == expected


@pytest.mark.parametrize("pages_kept,level,capped,expected", [
    (3, "full_text", 0, 0),
    (30, "full_text", 0, 1),
    (3, "abstract", 1, 0),
])
def test_reading_headline_honors_page_selection_and_licence_ceiling(pages_kept, level, capped, expected):
    report = {"attempted": 1, "succeeded": 1, "chars_read": 1000, "capped": capped,
              "entries": [{"ok": True, "streamed": True, "read_level": level,
                           "selection": {"pages_kept": pages_kept, "pages_total": 30}}]}
    note = ContentFetcher.reading_note(report)
    assert note.startswith(f"{expected}/1 sources ka full text")
    assert f"{pages_kept} pages process hue" in note


def test_partial_read_cannot_pass_hosted_full_text_acceptance():
    from research_engine.models import ResearchResult
    from scripts.run_live_zero_cost_gate import evaluate_result
    source = SourceRecord(read_level="full_text", full_text_chars=1000,
                          pages_read=3, pages_total=30)
    pack = EvidencePack(question="Controlled audit", sources=[source])
    result = ResearchResult(mode="COMPANY", status="PARTIAL", coverage=pack.coverage_report())
    receipt = evaluate_result(result.to_dict(), required_depth_mode="COMPANY")
    check = next(row for row in receipt["checks"] if row["name"] == "full_text_read")
    assert check["passed"] is False
