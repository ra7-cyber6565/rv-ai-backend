"""Dedicated thesis/dissertation discovery for AI-1.

A generic Crossref result can be a journal article, chapter, editorial or thesis.
AI-1's source-family contract requires dissertations to be an explicit lane, so
this connector uses Crossref's work-type endpoint and never infers "thesis" from
an arbitrary paper hit.

Truth boundaries:
- Crossref metadata/abstract != thesis body read.
- A DOI != open full text.
- A deposited PDF link becomes a deep-read candidate only when Crossref also
  exposes an explicitly open/Creative-Commons-style licence marker.
- Even an open thesis PDF must pass the ordinary ContentFetcher safety/licence
  and processing pipeline before it can be called read.
"""
from __future__ import annotations

from typing import Dict, List, Optional
from urllib.parse import quote

from ..models import SourceRecord, SourceType
from .base import BaseConnector, content_terms, http_get, term_overlap


_OPEN_LICENSE_MARKERS = (
    "creativecommons.org", "creativecommons", "cc-by", "cc0", "publicdomain",
)


def _first_text(value) -> str:
    if isinstance(value, list):
        for item in value:
            clean = _first_text(item)
            if clean:
                return clean
        return ""
    if isinstance(value, dict):
        for key in ("name", "title", "value"):
            if value.get(key):
                return str(value.get(key))
        return ""
    return str(value or "")


def _year(item: Dict) -> Optional[int]:
    for key in ("published-print", "published-online", "issued", "created", "deposited"):
        node = item.get(key)
        if not isinstance(node, dict):
            continue
        parts = node.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                pass
    return None


def _authors(item: Dict) -> List[str]:
    out: List[str] = []
    for person in item.get("author") or []:
        if not isinstance(person, dict):
            continue
        name = " ".join(str(person.get(k) or "").strip() for k in ("given", "family")).strip()
        if name and name not in out:
            out.append(name)
    return out[:12]


def _open_license(item: Dict) -> bool:
    for row in item.get("license") or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("URL") or row.get("url") or "").casefold()
        if any(marker in url for marker in _OPEN_LICENSE_MARKERS):
            return True
    return False


def _open_pdf(item: Dict) -> str:
    """Return a deposited PDF only when an explicit open licence is present."""
    if not _open_license(item):
        return ""
    for row in item.get("link") or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("URL") or row.get("url") or "").strip()
        content_type = str(row.get("content-type") or row.get("content_type") or "").casefold()
        if url.startswith(("https://", "http://")) and (
            content_type == "application/pdf" or url.casefold().split("?", 1)[0].endswith(".pdf")
        ):
            return url
    return ""


class CrossrefDissertationConnector(BaseConnector):
    """Crossref ``types/dissertation/works`` — public, keyless metadata lane."""

    name = "crossref_dissertation"
    source_type = SourceType.PAPER
    rate_limited = True

    def parse(self, payload: Dict, query: str = "") -> List[SourceRecord]:
        message = (payload or {}).get("message") if isinstance(payload, dict) else {}
        rows = message.get("items") if isinstance(message, dict) else []
        records: List[SourceRecord] = []
        for item in rows or []:
            if not isinstance(item, dict):
                continue
            work_type = str(item.get("type") or "").casefold()
            if work_type and work_type not in {"dissertation", "posted-content"}:
                continue
            title = self._clean(_first_text(item.get("title")), 500)
            abstract = self._clean(item.get("abstract"), 1800)
            doi = self._clean(item.get("DOI"), 300)
            oa_pdf = _open_pdf(item)
            url = oa_pdf or self._clean(item.get("URL"), 600)
            if not url and doi:
                url = f"https://doi.org/{quote(doi, safe='/')}"
            institution = self._clean(
                _first_text(item.get("institution") or item.get("publisher")), 300)
            if not (title or doi or url):
                continue
            read_level = "abstract" if abstract else "metadata"
            records.append(SourceRecord(
                title=title or doi or "(dissertation title unavailable)",
                url=url,
                snippet=abstract,
                connector=self.name,
                source_type=SourceType.PAPER,
                authors=_authors(item),
                year=_year(item),
                publisher=institution,
                venue="doctoral/master's dissertation metadata (Crossref)",
                doi=doi,
                peer_reviewed=None,
                is_primary=True,
                full_text_available=bool(oa_pdf),
                read_level=read_level,
                read_note=(
                    "Crossref dissertation metadata/abstract only; thesis body not read yet. "
                    + ("Explicitly open-licensed PDF link is available for ordinary safe full-text reading."
                       if oa_pdf else "No explicitly open-licensed PDF proof exposed by this record.")
                ),
                doc_kind="thesis",
                doc_kind_label="thesis / dissertation",
                doc_kind_confidence="high",
            ))
        if not query:
            return records
        terms = content_terms(query, limit=8)
        if not terms:
            return records
        needed = 2 if len(terms) >= 4 else 1
        return [r for r in records
                if term_overlap(terms, f"{r.title} {r.snippet} {r.publisher}") >= needed]

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        clean = " ".join(content_terms(query, limit=8)) or " ".join(str(query or "").split())
        if not clean:
            self.last_reason = "empty_query"
            return []
        # Crossref recommends selective fields only when needed; the exact set
        # of selectable fields may evolve. The dissertation lane is already
        # tightly bounded to <=20 rows, so omitting `select` avoids a brittle
        # schema dependency while keeping response size modest.
        response = http_get(
            "https://api.crossref.org/types/dissertation/works",
            params={
                "query": clean[:180],
                "rows": max(1, min(max(int(max_results or 1) * 3, 6), 20)),
            },
        )
        records = self.parse(response.json(), query=query)[:max_results]
        if records:
            self.last_note = (
                f"{len(records)} dissertation-specific Crossref record mile; metadata/abstract "
                "ko thesis body read nahi maana gaya")
        else:
            self.last_note = "Crossref dissertation lane chali par relevant dissertation record nahi mila"
        return records


class ThesisConnector:
    """Facade kept separate from the ordinary paper tier for auditability."""

    def __init__(self):
        self.connectors: List[BaseConnector] = [CrossrefDissertationConnector()]

    def by_name(self, name: str) -> Optional[BaseConnector]:
        return next((item for item in self.connectors if item.name == name), None)

    def available_names(self) -> List[str]:
        return [item.name for item in self.connectors]


__all__ = ["CrossrefDissertationConnector", "ThesisConnector"]
