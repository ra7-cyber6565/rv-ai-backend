"""P0-D regressions: evidence depth is frozen when a passage is captured."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.content_fetcher import ContentFetcher
from research_engine.evidence_drafting import build_evidence_draft_manifest
from research_engine.models import EvidencePack, Passage, SourceRecord, SourceType


CLAIM = (
    "Lanthanum hydride LaH10 shows a superconducting transition temperature "
    "of 250 K at a pressure of 170 GPa"
)
STALE_SEARCH = (
    "Search-result text says lanthanum hydride LaH10 may show a transition near "
    "250 K at 170 GPa, but this text was captured before the paper was opened. "
) * 3
FULL_TEXT = (
    "Electrical resistance measurements reproducibly show that lanthanum hydride "
    "LaH10 has a superconducting transition temperature of 250 K at 170 GPa. "
    "Magnetic susceptibility independently tracks the same transition. "
) * 3


def _source(*, source_type: SourceType = SourceType.PAPER,
            read_level: str = "snippet", snippet: str = STALE_SEARCH,
            full_text_chars: int = 0) -> SourceRecord:
    return SourceRecord(
        title="Fixture source",
        url="https://example.org/paper.pdf",
        snippet=snippet,
        connector="fixture",
        source_type=source_type,
        peer_reviewed=True,
        read_level=read_level,
        full_text_chars=full_text_chars,
        relevance_score=0.95,
        quality_score=0.90,
        combined_score=0.92,
        source_id="S1",
    )


class _SuccessfulReader(ContentFetcher):
    def __init__(self):
        super().__init__(allow_network=False)

    def resolve(self, source):
        return {"ok": True, "url": source.url, "kind": "pdf", "reason": "fixture"}

    def read_source(self, source, question, budget_chars=2400):
        return {
            "source_id": source.source_id,
            "title": source.title,
            "url": source.url,
            "ok": True,
            "reason": "fixture full text",
            "chars": 40000,
            "excerpts": [{"locator": "p.10 ¶2", "text": FULL_TEXT, "score": 9.0}],
            "notes": [],
            "kind": "pdf",
            "bytes": 1000,
            "streamed": False,
            "selection": {},
            "signals": {},
        }


def test_fulltext_upgrade_replaces_stale_pre_read_passage_and_stamps_provenance():
    source = _source()
    pack = EvidencePack(question=CLAIM, sources=[source], passages=[Passage(
        source_id="S1",
        text=STALE_SEARCH,
        locator="search result",
        provenance="retrieval_excerpt",
        read_level_at_capture="snippet",
    )])

    result = _SuccessfulReader().enrich(pack, max_sources=1, budget_chars=2400)

    assert result["succeeded"] == 1
    assert source.reading_level() == "full_text"
    assert STALE_SEARCH not in [p.text for p in pack.passages]
    assert len(pack.passages) == 1
    current = pack.passages[0]
    assert current.text == FULL_TEXT
    assert current.locator == "p.10 ¶2"
    assert current.provenance == "full_text_excerpt"
    assert current.read_level_at_capture == "full_text"


def test_capture_time_snippet_cannot_be_promoted_by_later_source_mutation():
    source = _source(read_level="full_text", snippet=FULL_TEXT, full_text_chars=40000)
    pack = EvidencePack(question=CLAIM, sources=[source], passages=[
        Passage(
            source_id="S1", text=STALE_SEARCH, locator="search result",
            provenance="retrieval_excerpt", read_level_at_capture="snippet",
        ),
        Passage(
            source_id="S1", text=FULL_TEXT, locator="p.10 ¶2",
            provenance="full_text_excerpt", read_level_at_capture="full_text",
        ),
    ])

    manifest = build_evidence_draft_manifest(
        CLAIM, pack, max_segments_per_source=4, max_segments=8)
    stale = next(s for s in manifest.spans if "Search-result text" in s.passage)
    current = next(s for s in manifest.spans
                   if "Electrical resistance measurements" in s.passage
                   and s.span_kind == "passage")

    assert stale.strong_claim_eligible is False
    assert "passage_capture_depth_not_strong" in stale.eligibility_reasons
    assert stale.read_level_at_capture == "snippet"
    assert current.strong_claim_eligible is True
    assert current.read_level_at_capture == "full_text"
    assert current.passage_provenance == "full_text_excerpt"


def test_generic_source_snippet_is_context_only_not_strong_evidence_span():
    # ContentFetcher stores a combined display snippet with locator prefixes;
    # this is intentionally not byte-identical to the exact Passage record.
    source = _source(
        read_level="full_text", snippet="[p.10 ¶2] " + FULL_TEXT,
        full_text_chars=40000)
    pack = EvidencePack(question=CLAIM, sources=[source], passages=[Passage(
        source_id="S1", text=FULL_TEXT, locator="p.10 ¶2",
        provenance="full_text_excerpt", read_level_at_capture="full_text",
    )])
    manifest = build_evidence_draft_manifest(
        CLAIM, pack, max_segments_per_source=4, max_segments=8)

    precise = [s for s in manifest.spans if s.span_kind == "passage"]
    generic = [s for s in manifest.spans if s.span_kind == "snippet"]
    assert precise and precise[0].strong_claim_eligible is True
    assert generic
    assert all(s.strong_claim_eligible is False for s in generic)
    assert all("snippet_not_strong_evidence_span" in s.eligibility_reasons
               for s in generic)


def test_uploaded_document_passage_remains_strong_without_network_fulltext_chars():
    source = _source(
        source_type=SourceType.DOCUMENT,
        read_level="full_text",
        snippet=FULL_TEXT,
        full_text_chars=0,
    )
    source.url = ""
    source.locator = "Page 42"
    pack = EvidencePack(question=CLAIM, sources=[source], passages=[Passage(
        source_id="S1", text=FULL_TEXT, locator="Page 42",
        provenance="retrieval_excerpt", read_level_at_capture="full_text",
    )])
    manifest = build_evidence_draft_manifest(CLAIM, pack)
    exact = next(s for s in manifest.spans if s.span_kind == "passage")
    assert exact.strong_claim_eligible is True
    assert exact.locator == "Page 42"
    assert exact.read_level_at_capture == "full_text"


def test_manifest_compact_record_exposes_provenance_without_raw_passage():
    source = _source(read_level="full_text", snippet=FULL_TEXT, full_text_chars=40000)
    pack = EvidencePack(question=CLAIM, sources=[source], passages=[Passage(
        source_id="S1", text=FULL_TEXT, locator="p.10 ¶2",
        provenance="full_text_excerpt", read_level_at_capture="full_text",
    )])
    manifest = build_evidence_draft_manifest(CLAIM, pack)
    row = next(row for row in manifest.to_dict()["spans"]
               if row["span_kind"] == "passage")
    assert row["passage_provenance"] == "full_text_excerpt"
    assert row["read_level_at_capture"] == "full_text"
    assert "passage" not in row
    assert len(row["passage_sha256"]) == 64
