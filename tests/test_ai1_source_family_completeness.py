import pytest

from research_engine.ai1_packet_extensions import extend_ai1_packet
from research_engine.ai1_research_director import PACKET_SECTION_NAMES
from research_engine.ai1_structured_runtime import (
    AI1StructuredSourceDiscovery,
    StructuredAwareContentFetcher,
    archive_lane_relevant,
    thesis_lane_relevant,
)
from research_engine.connectors.archive_connector import NaraCatalogConnector
from research_engine.connectors.base import ConnectorSkipped
from research_engine.connectors.thesis_connector import CrossrefDissertationConnector
from research_engine.content_fetcher import ContentFetcher
from research_engine.critical_source_anatomy import (
    FIELDS,
    PRESENT,
    UNKNOWN,
    extract_critical_source_anatomy,
)
from research_engine.models import EvidencePack, SourceRecord, SourceType
from research_engine.source_capability_matrix import (
    BOUNDED_RUNTIME,
    CONDITIONAL_RUNTIME,
    build_source_capability_matrix,
)
from research_engine.structured_source_reader import (
    StructuredAwareContentFetcher as BaseStructuredAwareContentFetcher,
)


def _plan(**extra):
    base = {
        "web": False,
        "papers": [],
        "books": [],
        "datasets": [],
        "patents": [],
        "markets": [],
        "classics": [],
        "classic_queries": [],
        "summary_queries": [],
        "official_archive_queries": [],
        "book_queries": [],
        "craft_study": [],
        "listener_study": [],
        "music_study": [],
        "trade_study": [],
        "exam_study": [],
        "domain": "generic",
        "useful_source_types": [],
    }
    base.update(extra)
    return base


def _anatomy_text(include_limitations=True):
    limitations = (
        "Limitations\nThe sample came from one region, so external generalization remains uncertain.\n\n"
        if include_limitations else ""
    )
    return (
        "Methods\nWe randomized participants and measured the prespecified outcome using a blinded protocol.\n\n"
        "Participants\nThe study included 120 participants with complete baseline and outcome observations.\n\n"
        "Assumptions\nWe assume measurement error is independent of randomized assignment for this analysis.\n\n"
        "Results\nWe found the treatment arm changed the primary outcome relative to the control arm.\n\n"
        + limitations
        + "Robustness\nSensitivity analysis and external validation were used to test robustness of the estimate.\n"
    )


def test_dissertation_metadata_never_becomes_body_read():
    payload = {
        "message": {"items": [{
            "type": "dissertation",
            "title": ["Quantum superconductivity mechanism dissertation"],
            "abstract": "A dissertation study of quantum superconductivity mechanism.",
            "DOI": "10.1234/example.thesis",
            "URL": "https://doi.org/10.1234/example.thesis",
            "author": [{"given": "A", "family": "Researcher"}],
            "publisher": "Example University",
            "issued": {"date-parts": [[2025]]},
        }]}
    }
    rows = CrossrefDissertationConnector().parse(
        payload, query="quantum superconductivity mechanism")
    assert len(rows) == 1
    source = rows[0]
    assert source.doc_kind == "thesis"
    assert source.reading_level() == "abstract"
    assert source.full_text_available is False
    assert "body not read" in source.read_note


def test_dissertation_pdf_requires_explicit_open_license():
    base = {
        "type": "dissertation",
        "title": ["Open dissertation on causal inference"],
        "abstract": "Causal inference dissertation with empirical analysis.",
        "DOI": "10.5678/open.thesis",
        "URL": "https://doi.org/10.5678/open.thesis",
        "link": [{"URL": "https://repo.example.edu/thesis.pdf", "content-type": "application/pdf"}],
    }
    closed = CrossrefDissertationConnector().parse(
        {"message": {"items": [base]}}, query="causal inference dissertation")[0]
    assert closed.url != "https://repo.example.edu/thesis.pdf"
    assert closed.full_text_available is False

    opened = dict(base)
    opened["license"] = [{"URL": "https://creativecommons.org/licenses/by/4.0/"}]
    open_source = CrossrefDissertationConnector().parse(
        {"message": {"items": [opened]}}, query="causal inference dissertation")[0]
    assert open_source.url == "https://repo.example.edu/thesis.pdf"
    assert open_source.full_text_available is True
    assert open_source.reading_level() == "abstract"


def test_nara_catalog_description_is_not_archive_body():
    payload = {"body": {"hits": {"hits": [{"_source": {"record": {
        "naId": "12345",
        "title": "Project Stargate administrative record",
        "scopeAndContentNote": "Catalog description of Project Stargate files.",
    }}}]}}}
    rows = NaraCatalogConnector().parse(payload, query="Project Stargate")
    assert len(rows) == 1
    source = rows[0]
    assert source.reading_level() == "snippet"
    assert source.domain_verdict["archive_body_exposed"] is False
    assert "body was not read" in source.read_note


def test_nara_extracted_text_is_bounded_archive_section_not_full_text():
    payload = {"body": {"hits": {"hits": [{"_source": {"record": {
        "naId": "67890",
        "title": "Declassified remote viewing assessment",
        "digitalObjects": [{
            "extractedText": (
                "This declassified remote viewing assessment contains extracted OCR text "
                "from the archived digital object and records the agency discussion."
            )
        }],
    }}}]}}}
    rows = NaraCatalogConnector().parse(payload, query="remote viewing assessment")
    assert len(rows) == 1
    source = rows[0]
    assert source.reading_level() == "sections"
    assert source.full_text_available is False
    assert source.full_text_chars == 0
    assert source.domain_verdict["archive_body_exposed"] is True
    assert source.domain_verdict["archive_transformation_methods"]
    assert "provenance does not prove claims" in source.read_note


def test_nara_missing_api_key_is_not_zero_result(monkeypatch):
    monkeypatch.delenv("NARA_CATALOG_API_KEY", raising=False)
    monkeypatch.delenv("CATALOG_API_KEY", raising=False)
    with pytest.raises(ConnectorSkipped) as exc:
        NaraCatalogConnector().search("Project Stargate", 2)
    assert "search chali hi nahi" in str(exc.value)


def test_specialist_lanes_are_relevance_gated_not_global():
    assert thesis_lane_relevant(_plan(), "find the doctoral dissertation on this topic") is True
    assert thesis_lane_relevant(
        _plan(domain="archaeology_history"), "empirical research evidence for chronology") is True
    assert thesis_lane_relevant(_plan(), "weather tomorrow") is False

    assert archive_lane_relevant(
        _plan(official_archive_queries=["Project Stargate declassified records"]), "question") is True
    assert archive_lane_relevant(_plan(), "CIA Reading Room Project Stargate documents") is True
    assert archive_lane_relevant(_plan(), "ordinary machine learning benchmark") is False


def test_runtime_tasks_add_thesis_and_archive_only_when_relevant():
    discovery = AI1StructuredSourceDiscovery(max_workers=1)
    scholarly = discovery._tasks(
        ["doctoral dissertation causal mechanism"], _plan(), 2, 4)
    archive = discovery._tasks(
        ["Project Stargate"],
        _plan(official_archive_queries=["Project Stargate declassified"]), 2, 4)
    generic = discovery._tasks(["weather forecast"], _plan(), 2, 4)

    assert "crossref_dissertation" in [name for name, _call in scholarly]
    assert "nara_archive" in [name for name, _call in archive]
    assert "crossref_dissertation" not in [name for name, _call in generic]
    assert "nara_archive" not in [name for name, _call in generic]


def test_critical_anatomy_extracts_six_fields_with_spans_without_truth_upgrade():
    anatomy = extract_critical_source_anatomy(_anatomy_text())
    assert anatomy["ran"] is True
    assert anatomy["complete"] is True
    assert anatomy["present_count"] == len(FIELDS) == 6
    assert anatomy["missing_count"] == 0
    assert "does not prove" in anatomy["truth_boundary"]
    for field in FIELDS:
        row = anatomy["fields"][field]
        assert row["status"] == PRESENT
        assert isinstance(row["span_start"], int)
        assert isinstance(row["span_end"], int)
        assert row["span_end"] > row["span_start"]
        assert row["excerpt"]


def test_critical_anatomy_missing_heading_stays_unknown_not_negative_fact():
    anatomy = extract_critical_source_anatomy(_anatomy_text(include_limitations=False))
    assert anatomy["complete"] is False
    assert "limitations" in anatomy["missing_fields"]
    assert anatomy["fields"]["limitations"]["status"] == UNKNOWN
    assert "absence is not evidence" in anatomy["fields"]["limitations"]["reason"]


def test_structured_reader_derives_anatomy_from_processed_full_text_without_retaining_raw(monkeypatch):
    text = _anatomy_text()

    class FakeProcessor:
        def process(self, *args, **kwargs):
            return {
                "ok": True,
                "text": text,
                "chunks": [{"locator": "p. 1", "text": text}],
                "notes": [],
                "kind": "txt",
                "streamed": False,
                "selection": {},
            }

    monkeypatch.setattr(
        ContentFetcher, "resolve",
        lambda self, source: {
            "ok": True, "url": source.url, "kind": "txt", "reason": "test open text",
            "copyright_stance": {"full_text_allowed": True, "read_ceiling": "full_text"},
        })
    monkeypatch.setattr(
        ContentFetcher, "_download",
        lambda self, url, kind, directory: {
            "ok": True, "path": "/tmp/fake-ai1.txt", "bytes": 5000, "large": False,
        })
    monkeypatch.setattr(ContentFetcher, "_processor", lambda self: FakeProcessor())

    fetcher = StructuredAwareContentFetcher(allow_network=True)
    source = SourceRecord(
        source_id="S1", title="Critical paper", url="https://example.org/open.txt",
        connector="test", source_type=SourceType.PAPER, read_level="abstract",
    )
    entry = fetcher.read_source(source, "study outcome", budget_chars=1200)
    assert entry["ok"] is True
    assert entry["critical_source_anatomy"]["complete"] is True
    assert "text" not in entry
    assert fetcher._last_processed_text == ""


def test_structured_enrich_attaches_anatomy_receipt_to_source_metadata(monkeypatch):
    anatomy = extract_critical_source_anatomy(_anatomy_text())

    def fake_base_enrich(self, pack, max_sources=3, budget_chars=2400):
        return {
            "attempted": 1,
            "succeeded": 1,
            "entries": [{"source_id": "S1", "ok": True,
                         "critical_source_anatomy": anatomy}],
            "structured": {"attempted": 0},
        }

    monkeypatch.setattr(BaseStructuredAwareContentFetcher, "enrich", fake_base_enrich)
    source = SourceRecord(
        source_id="S1", title="Critical paper", source_type=SourceType.PAPER,
        domain_verdict={"existing": "preserved"},
    )
    pack = EvidencePack(question="q", sources=[source])
    report = StructuredAwareContentFetcher(allow_network=False).enrich(pack)
    assert report["critical_source_anatomy"]["attached"] == 1
    assert report["critical_source_anatomy"]["raw_full_text_retained"] is False
    assert pack.sources[0].domain_verdict["existing"] == "preserved"
    assert pack.sources[0].domain_verdict["critical_source_anatomy"]["complete"] is True


def test_capability_matrix_requires_real_paths_and_separates_runtime_exercise():
    result = {
        "sources": [{
            "source_id": "D1", "source_type": "dataset", "connector": "world_bank",
            "reading_level": "sections", "dataset_inspection": {"rows_inspected": 5},
        }, {
            "source_id": "T1", "source_type": "paper", "connector": "crossref_dissertation",
            "doc_kind": "thesis", "reading_level": "abstract",
        }]
    }
    matrix = build_source_capability_matrix(result)
    assert matrix["valid"] is True
    assert matrix["missing_required_modules"] == []
    assert matrix["family_count"] >= 14

    by_family = {row["source_family"]: row for row in matrix["families"]}
    assert by_family["datasets_and_time_series"]["implementation_status"] == BOUNDED_RUNTIME
    assert by_family["datasets_and_time_series"]["runtime"]["deep_exercised_count"] == 1
    assert by_family["theses_and_dissertations"]["implementation_status"] == CONDITIONAL_RUNTIME
    assert by_family["theses_and_dissertations"]["runtime"]["exercised"] is True
    assert by_family["theses_and_dissertations"]["runtime"]["deep_exercised_count"] == 0
    assert "not access to the entire internet" in matrix["absolute_scope_disclaimer"]


def test_packet_extension_preserves_exact_15_sections_and_caps_missing_anatomy():
    anatomy = extract_critical_source_anatomy(_anatomy_text(include_limitations=False))
    sections = {name: [] for name in PACKET_SECTION_NAMES}
    sections["5. Strongest Sources"] = [{
        "source_id": "S1", "source_family": "paper",
        "full_text_status": "FULL TEXT ACCESSED",
    }]
    sections["11. Missing Evidence"] = []
    sections["13. Highest-Value Second-Pass Research Tasks"] = []
    sections["14. Confidence in Research Packet /100"] = {"score": 99}
    sections["15. Exactly What Prevents a Higher Score"] = []
    result = {
        "sources": [{
            "source_id": "S1", "source_type": "paper",
            "doc_kind": "peer_reviewed_article", "reading_level": "full_text",
            "domain_verdict": {"critical_source_anatomy": anatomy},
        }],
        "ai1_research_packet": {"sections": sections},
    }

    extended = extend_ai1_packet("question", result)
    packet = extended["ai1_research_packet"]
    assert list(packet["sections"]) == list(PACKET_SECTION_NAMES)
    assert len(packet["sections"]) == 15
    assert packet["source_family_extension"]["exact_15_sections_preserved"] is True
    assert packet["source_family_extension"]["claim_grades_modified"] is False
    assert packet["source_family_extension"]["critical_anatomy_gap_count"] >= 1
    assert packet["sections"]["14. Confidence in Research Packet /100"]["score"] <= 92
    assert any(
        row.get("anatomy_field") == "limitations"
        for row in packet["sections"]["11. Missing Evidence"]
        if isinstance(row, dict)
    )
    tasks = packet["sections"]["13. Highest-Value Second-Pass Research Tasks"]
    assert any(row.get("priority_formula") == "Importance × Expected Information Gain" for row in tasks)
