"""Provider response fixtures; no live retrieval or model calls."""
from types import SimpleNamespace

import pytest

from research_engine.connectors import paper_connector as papers
from research_engine.content_fetcher import ContentFetcher
from research_engine.models import EvidencePack, SourceRecord, SourceType


def test_openalex_oa_copy_reaches_reader_without_replacing_citation(monkeypatch):
    item = {"id": "https://openalex.org/W123", "doi": "https://doi.org/10.1234/fixture",
            "title": "Controlled paper", "open_access": {"is_oa": True},
            "best_oa_location": {"is_oa": True, "pdf_url": "https://example.org/paper.pdf"}}
    monkeypatch.setattr(papers, "http_get", lambda *a, **k: SimpleNamespace(json=lambda: {"results": [item]}))
    source, = papers.OpenAlexConnector().search("controlled paper")
    assert source.url == item["doi"]
    assert source.full_text_urls == ["https://example.org/paper.pdf"]
    assert source.reading_level() != "full_text"
    assert EvidencePack(sources=[source]).full_text_read_count == 0
    route = ContentFetcher().resolve(source)
    assert route["ok"] is True and route["url"] == source.full_text_urls[0]
    assert source.url == item["doi"]


def test_reader_tries_safe_repository_after_blocked_publisher_copy():
    source = SourceRecord(url="https://doi.org/10.1234/fixture", source_type=SourceType.PAPER,
                          full_text_urls=["https://nature.com/blocked.pdf", "http://127.0.0.1/private.pdf",
                                          "https://arxiv.org/abs/2303.08759"])
    route = ContentFetcher().resolve(source)
    assert route["ok"] is True
    assert route["url"] == "https://arxiv.org/pdf/2303.08759"
    assert source.reading_level() != "full_text"


@pytest.mark.parametrize("hint", ["http://127.0.0.1/private.pdf", "file:///tmp/private.pdf",
                                  "https://nature.com/blocked.pdf", "https://example.org/landing",
                                  "https://user:password@example.org/paper.pdf"])
def test_oa_metadata_cannot_waive_existing_read_route_restrictions(hint):
    source = SourceRecord(url="https://doi.org/10.1234/fixture", full_text_urls=[hint])
    assert ContentFetcher().resolve(source)["ok"] is False


def test_copy_hints_survive_canonical_serialization_but_never_upgrade_read_state():
    source = SourceRecord(url="https://doi.org/10.1234/fixture", full_text_available=True,
                          full_text_urls=["https://example.org/paper.pdf"])
    wire = source.to_dict()
    assert wire["full_text_urls"] == source.full_text_urls
    restored = SourceRecord(**{k: v for k, v in wire.items() if k in SourceRecord.__dataclass_fields__
                              and k != "source_type"})
    assert ContentFetcher().resolve(restored)["ok"] is True
    assert EvidencePack(sources=[restored]).full_text_read_count == 0


def test_openalex_ignores_closed_locations_and_caps_candidate_count():
    item = {"best_oa_location": {"is_oa": False, "pdf_url": "https://example.org/closed.pdf"},
            "open_access": {"is_oa": False, "oa_url": "https://example.org/also-closed.pdf"},
            "locations": [{"is_oa": True, "pdf_url": f"https://example.org/{i}.pdf"} for i in range(50)]}
    urls = papers.OpenAlexConnector._oa_urls(item)
    assert len(urls) == 8
    assert all("closed" not in url for url in urls)


def test_semantic_scholar_requests_and_retains_open_pdf(monkeypatch):
    seen = []
    def fetch(*args, **kwargs):
        seen.append(kwargs["params"]["fields"])
        return SimpleNamespace(json=lambda: {"data": [{"title": "Controlled paper",
            "url": "https://www.semanticscholar.org/paper/fixture", "isOpenAccess": True,
            "openAccessPdf": {"url": "https://example.org/paper.pdf"}}]})
    monkeypatch.setattr(papers, "http_get", fetch)
    source, = papers.SemanticScholarConnector().search("controlled")
    assert "openAccessPdf" in seen[0].split(",")
    assert ContentFetcher().resolve(source)["url"] == "https://example.org/paper.pdf"
    assert source.url.startswith("https://www.semanticscholar.org/")


def test_oa_hint_does_not_override_original_book_licence(monkeypatch):
    from research_engine import content_fetcher as fetcher
    original = fetcher.classics.copyright_stance
    def stance(source):
        if source.url == "https://example.org/restricted-book":
            return {"full_text_allowed": False, "read_ceiling": "abstract", "summary_lane": True}
        return original(source)
    monkeypatch.setattr(fetcher.classics, "copyright_stance", stance)
    source = SourceRecord(url="https://example.org/restricted-book",
                          full_text_urls=["https://example.org/book.pdf"])
    assert ContentFetcher().resolve(source)["ok"] is False
