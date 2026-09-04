import requests

from research_engine import network_safety
from research_engine.ai1_structured_runtime import (
    AI1StructuredSourceDiscovery,
    StructuredAwareContentFetcher,
    media_lane_relevant,
)
from research_engine.models import EvidencePack, SourceRecord, SourceType
from research_engine.multilingual_source_provenance import (
    annotate_multilingual_provenance,
    build_original_text_receipt,
)
from research_engine.public_documentation_reader import (
    PublicDocumentationReader,
    documentation_candidate,
)
from research_engine.source_capability_matrix import (
    BOUNDED_RUNTIME,
    CONDITIONAL_RUNTIME,
    build_source_capability_matrix,
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


class _FakeResponse:
    def __init__(self, body: bytes, url: str = "https://docs.example.com/reference/api"):
        self.status_code = 200
        self.headers = {"Content-Type": "text/html; charset=utf-8",
                        "Content-Length": str(len(body))}
        self.url = url
        self.encoding = "utf-8"
        self._body = body
        self.closed = False

    def iter_content(self, chunk_size=64 * 1024):
        yield self._body

    def close(self):
        self.closed = True


def _doc_source():
    return SourceRecord(
        source_id="DOC1",
        title="Client API Reference and Configuration Guide",
        url="https://docs.example.com/reference/api",
        connector="web",
        source_type=SourceType.WEB,
        read_level="snippet",
        combined_score=0.9,
    )


def test_general_media_lane_is_not_limited_to_craft_study():
    assert media_lane_relevant(_plan(), "Find the full interview transcript with the researcher") is True
    assert media_lane_relevant(
        _plan(useful_source_types=["podcast transcripts", "papers"]), "research history") is True
    assert media_lane_relevant(_plan(), "ordinary randomized trial evidence") is False

    discovery = AI1StructuredSourceDiscovery(max_workers=1)
    tasks = discovery._tasks(
        ["lecture transcript on quantum computing"], _plan(), 2, 4)
    assert "ai1_media_transcript" in [name for name, _call in tasks]


def test_documentation_candidate_requires_real_docs_manual_signal():
    assert documentation_candidate(_doc_source()) is True
    ordinary = SourceRecord(
        source_id="W1", title="Company homepage",
        url="https://www.example.com/about", connector="web",
        source_type=SourceType.WEB, read_level="snippet",
    )
    assert documentation_candidate(ordinary) is False


def test_public_documentation_reader_reads_bounded_page_not_whole_site(monkeypatch):
    html = b"""
    <html><body>
      <h1>Client API Reference</h1>
      <p>Configure the client timeout with the timeout option before making requests.</p>
      <h2>Retry policy</h2>
      <p>Set max retries explicitly and handle rate limit responses with bounded backoff.</p>
      <pre>client = Client(timeout=10, max_retries=2)</pre>
    </body></html>
    """
    monkeypatch.setattr(network_safety, "_resolved_addresses",
                        lambda host: ["93.184.216.34"])
    monkeypatch.setattr(requests, "get",
                        lambda *args, **kwargs: _FakeResponse(html))

    result = PublicDocumentationReader(allow_network=True).inspect(
        _doc_source(), "How do I configure timeout and retries?")
    assert result["ok"] is True
    inspection = result["inspection"]
    assert inspection["status"] == "DOCUMENTATION_PAGE_INSPECTED"
    assert inspection["site_or_manual_complete"] is False
    assert inspection["page_complete_claimed"] is False
    assert inspection["authentication_bypassed"] is False
    assert inspection["bytes_read"] == len(html)
    assert "timeout" in result["excerpt"].lower()
    assert "whole manual/site" in inspection["truth_boundary"]


def test_documentation_reader_blocks_private_target_before_request(monkeypatch):
    called = {"value": False}

    def fake_get(*args, **kwargs):
        called["value"] = True
        raise AssertionError("private URL must be blocked before HTTP")

    monkeypatch.setattr(requests, "get", fake_get)
    source = SourceRecord(
        source_id="D2", title="API Documentation",
        url="http://127.0.0.1/docs/api", connector="web",
        source_type=SourceType.WEB, read_level="snippet",
    )
    result = PublicDocumentationReader(allow_network=True).inspect(source, "API")
    assert result["ok"] is False
    assert called["value"] is False
    assert "private" in result["reason"].lower() or "unsafe" in result["reason"].lower()


def test_documentation_enrich_clamps_to_sections_and_replaces_snippet_passage(monkeypatch):
    reader = PublicDocumentationReader(allow_network=False)
    source = _doc_source()
    pack = EvidencePack(question="configure timeout", sources=[source])

    monkeypatch.setattr(reader, "inspect", lambda source, question: {
        "ok": True,
        "excerpt": "[Timeout] Configure timeout to 10 seconds.",
        "locator": "documentation page: Timeout",
        "inspection": {
            "status": "DOCUMENTATION_PAGE_INSPECTED",
            "bytes_read": 500,
            "blocks_parsed": 10,
            "blocks_selected": 1,
            "site_or_manual_complete": False,
            "authentication_bypassed": False,
        },
    })
    report = reader.enrich(pack, max_sources=1)
    assert report["succeeded"] == 1
    assert source.reading_level() == "sections"
    assert source.full_text_available is False
    assert source.full_text_chars == 0
    assert source.domain_verdict["documentation_inspection"]["site_or_manual_complete"] is False
    assert len(pack.passages) == 1
    assert pack.passages[0].provenance == "public_documentation_page_excerpt"
    assert pack.passages[0].read_level_at_capture == "sections"


def test_multilingual_receipt_records_script_not_guessed_language_or_translation():
    receipt = build_original_text_receipt(
        "यह मूल हिंदी लिपि में लिखा हुआ स्रोत अंश है।")
    assert receipt["text_observed"] is True
    assert "devanagari" in receipt["observed_scripts"]
    assert receipt["language_inferred"] is False
    assert receipt["original_text_preserved"] is True
    assert receipt["translation_claimed"] is False
    assert receipt["search_or_transliteration_bridge_is_translation"] is False


def test_translation_claim_is_separate_from_original_script_receipt():
    receipt = build_original_text_receipt(
        "Translated evidence surface",
        {
            "method": "translation",
            "verification_verdict": "AGREEMENT_OK",
            "review_required": False,
        },
    )
    assert receipt["translation_claimed"] is True
    assert receipt["original_text_preserved"] is False
    assert receipt["translation_verification_verdict"] == "AGREEMENT_OK"
    assert receipt["translation_review_required"] is False
    assert receipt["language_inferred"] is False


def test_multilingual_annotation_adds_receipt_without_copying_raw_text_to_report():
    source = SourceRecord(
        source_id="M1", title="मूल दस्तावेज", snippet="मूल स्रोत का पाठ यहाँ है।",
        source_type=SourceType.DOCUMENT, read_level="full_text",
    )
    pack = EvidencePack(question="source", sources=[source])
    report = annotate_multilingual_provenance(pack)
    assert report["sources_annotated"] == 1
    assert report["non_latin_or_mixed_sources"] == 1
    assert report["raw_text_copied_into_report"] is False
    receipt = source.domain_verdict["multilingual_source_provenance"]
    assert receipt["original_text_preserved"] is True
    assert "devanagari" in receipt["observed_scripts"]


def test_production_fetcher_contains_documentation_and_multilingual_stages():
    fetcher = StructuredAwareContentFetcher(allow_network=False)
    assert isinstance(fetcher.documentation, PublicDocumentationReader)


def test_capability_matrix_upgrades_docs_media_and_multilingual_without_overclaim():
    result = {
        "sources": [{
            "source_id": "D1", "source_type": "web", "connector": "web",
            "reading_level": "sections",
            "domain_verdict": {
                "documentation_inspection": {"status": "DOCUMENTATION_PAGE_INSPECTED"},
                "multilingual_source_provenance": {
                    "text_observed": True, "observed_scripts": ["devanagari"],
                    "language_inferred": False,
                },
            },
        }, {
            "source_id": "T1", "source_type": "transcript", "connector": "archive_media",
            "reading_level": "full_text", "locator": "00:10:00",
        }]
    }
    matrix = build_source_capability_matrix(result)
    assert matrix["valid"] is True
    assert matrix["schema_version"] == "ai1-source-capability-matrix-1.1"
    assert matrix["missing_required_modules"] == []
    by_family = {row["source_family"]: row for row in matrix["families"]}

    docs = by_family["documentation_manuals_technical_notes"]
    assert docs["implementation_status"] == BOUNDED_RUNTIME
    assert docs["runtime"]["deep_exercised_count"] == 1
    assert "whole manual/site" in docs["truth_boundary"]

    media = by_family["video_audio_transcripts_interviews_lectures"]
    assert media["implementation_status"] == CONDITIONAL_RUNTIME
    assert media["runtime"]["deep_exercised_count"] == 1
    assert "general AI-1 media-intent route" in media["discovery_path"]

    multilingual = by_family["multilingual_sources"]
    assert multilingual["implementation_status"] == CONDITIONAL_RUNTIME
    assert multilingual["runtime"]["deep_exercised_count"] == 1
    assert "translation" in multilingual["truth_boundary"]
