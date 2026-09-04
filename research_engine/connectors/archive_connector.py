"""Official/declassified archive connector for the National Archives Catalog.

NARA's Catalog API is key-gated.  Absence of a key is therefore a *not searched*
state, never a zero-result claim.  The connector is read-only and consumes only
metadata/extracted text/transcriptions returned by the official API; it does not
post contributions and it does not bulk-download digital objects.

Truth boundaries:
- an official catalog record proves provenance/catalog presence, not every claim;
- catalog title/description != archived body;
- only API-exposed OCR/extracted/transcription text upgrades access to bounded
  relevant sections;
- OCR/transcription text is still a transformation and never becomes automatic
  claim truth.
"""
from __future__ import annotations

import os
import re
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from ..models import SourceRecord, SourceType
from ..network_safety import (
    read_bounded_response,
    require_content_type,
    safe_get_with_redirects,
)
from .base import (
    SLOW_TIMEOUT,
    AccessBlocked,
    BaseConnector,
    ConnectorHTTPError,
    ConnectorSkipped,
    RateLimited,
    content_terms,
    term_overlap,
)

NARA_API = "https://catalog.archives.gov/api/v2/records/search"
NARA_HOSTS = {"catalog.archives.gov"}
MAX_NARA_JSON_BYTES = 12 * 1024 * 1024
MAX_ARCHIVE_BODY_CHARS = 16_000


def api_key() -> str:
    return (os.getenv("NARA_CATALOG_API_KEY") or os.getenv("CATALOG_API_KEY") or "").strip()


def nara_json(*, params: Dict, key: str):
    """Bounded read-only GET against the one official Catalog host."""
    import requests

    response = None
    try:
        response, _final = safe_get_with_redirects(
            requests,
            NARA_API,
            params=params,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "x-api-key": key,
                "User-Agent": "InfinityResearchAI/1.0 (read-only archival research)",
            },
            timeout=SLOW_TIMEOUT,
            stream=True,
            allowed_hosts=NARA_HOSTS,
            resolve_dns=False,
            max_redirects=1,
        )
        status = int(getattr(response, "status_code", 200) or 200)
        if status in {429, 503}:
            raise RateLimited(f"NARA Catalog API HTTP {status} rate limit")
        if status in {401, 403}:
            raise AccessBlocked("NARA Catalog API key/access rejected")
        if status >= 400:
            raise ConnectorHTTPError(f"NARA Catalog API HTTP {status}", status=status)
        require_content_type(response, "json")
        read_bounded_response(response, MAX_NARA_JSON_BYTES)
        return response.json()
    finally:
        try:
            if response is not None:
                response.close()
        except Exception:
            pass


def _clean_text(value: object, limit: int = MAX_ARCHIVE_BODY_CHARS) -> str:
    if isinstance(value, str):
        return " ".join(value.split())[:limit]
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _description(record: Mapping) -> str:
    for key in (
        "scopeAndContentNote", "generalNote", "description", "recordHistory",
        "title", "subtitle",
    ):
        raw = record.get(key)
        if isinstance(raw, str) and raw.strip():
            return _clean_text(raw, 2500)
        if isinstance(raw, Mapping):
            for sub in ("note", "value", "text"):
                text = _clean_text(raw.get(sub), 2500)
                if text:
                    return text
    return ""


def _date_year(record: Mapping) -> Optional[int]:
    blob = " ".join(str(record.get(key) or "") for key in (
        "productionDateArray", "productionDate", "inclusiveStartDate", "inclusiveEndDate"
    ))
    match = re.search(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", blob)
    return int(match.group(1)) if match else None


def _collect_transformed_body(node: object, *, active: bool = False,
                              depth: int = 0) -> List[Tuple[str, str]]:
    """Collect text only from explicit OCR/extracted/transcription branches."""
    if depth > 8:
        return []
    out: List[Tuple[str, str]] = []
    if isinstance(node, Mapping):
        for raw_key, value in node.items():
            key = str(raw_key or "")
            low = key.casefold().replace("_", "")
            branch = active or any(marker in low for marker in (
                "extractedtext", "ocrtext", "transcription", "transcripttext"
            ))
            if branch and isinstance(value, str):
                text = _clean_text(value)
                if len(text) >= 40:
                    out.append((key, text))
            else:
                out.extend(_collect_transformed_body(value, active=branch, depth=depth + 1))
    elif isinstance(node, (list, tuple)):
        for item in node[:50]:
            out.extend(_collect_transformed_body(item, active=active, depth=depth + 1))
    elif active and isinstance(node, str):
        text = _clean_text(node)
        if len(text) >= 40:
            out.append(("transformed_text", text))
    return out


def _record_hits(payload: Mapping) -> List[Mapping]:
    body = payload.get("body") if isinstance(payload, Mapping) else {}
    hits = body.get("hits") if isinstance(body, Mapping) else {}
    rows = hits.get("hits") if isinstance(hits, Mapping) else []
    return [row for row in rows or [] if isinstance(row, Mapping)]


class NaraCatalogConnector(BaseConnector):
    """Read-only National Archives Catalog search + API-exposed body text."""

    name = "nara_archive"
    source_type = SourceType.WEB
    free = False
    rate_limited = True

    def parse(self, payload: Mapping, query: str = "") -> List[SourceRecord]:
        records: List[SourceRecord] = []
        for hit in _record_hits(payload):
            source = hit.get("_source") if isinstance(hit.get("_source"), Mapping) else {}
            record = source.get("record") if isinstance(source.get("record"), Mapping) else {}
            if not record:
                continue
            naid = str(record.get("naId") or record.get("naid") or "").strip()
            title = self._clean(record.get("title") or record.get("subtitle"), 500)
            description = _description(record)
            body_parts = _collect_transformed_body(record)
            body_texts: List[str] = []
            body_methods: List[str] = []
            for method, text in body_parts:
                if text not in body_texts:
                    body_texts.append(text)
                if method not in body_methods:
                    body_methods.append(method)
            body = "\n\n".join(body_texts)[:MAX_ARCHIVE_BODY_CHARS]
            if not (naid or title or description or body):
                continue
            url = f"https://catalog.archives.gov/id/{naid}" if naid else "https://catalog.archives.gov/"
            read_level = "sections" if body else ("snippet" if description else "metadata")
            snippet = body if body else description
            record_source = SourceRecord(
                title=title or f"NARA record {naid}" or "National Archives record",
                url=url,
                snippet=snippet,
                connector=self.name,
                source_type=SourceType.WEB,
                year=_date_year(record),
                publisher="U.S. National Archives and Records Administration",
                venue="National Archives Catalog",
                locator=f"NAID {naid}" if naid else "National Archives Catalog record",
                peer_reviewed=None,
                is_primary=True,
                full_text_available=False,
                read_level=read_level,
                full_text_chars=0,
                read_note=(
                    "Official NARA catalog record. "
                    + (f"API-exposed OCR/extracted/transcription text reviewed as bounded sections ({', '.join(body_methods[:5])}); "
                       "catalog provenance does not prove claims inside the record."
                       if body else
                       "Only catalog description/metadata exposed; archived document body was not read.")
                ),
                doc_kind="government_report",
                doc_kind_label="official archival record",
                doc_kind_confidence="high",
                domain_verdict={
                    "archive_naid": naid,
                    "archive_body_exposed": bool(body),
                    "archive_transformation_methods": body_methods,
                    "official_record_truth_boundary": (
                        "catalog provenance/release != truth of document contents"
                    ),
                },
            )
            records.append(record_source)

        if not query:
            return records
        terms = content_terms(query, limit=8)
        if not terms:
            return records
        kept = [row for row in records
                if term_overlap(terms, f"{row.title} {row.snippet}") >= 1]
        return kept

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        key = api_key()
        if not key:
            raise ConnectorSkipped(
                "NARA_CATALOG_API_KEY/CATALOG_API_KEY available nahi hai — official "
                "National Archives API search chali hi nahi; ise 0-result na maana jaye."
            )
        clean = " ".join(content_terms(query, limit=10)) or " ".join(str(query or "").split())
        payload = nara_json(params={
            "q": clean[:180],
            "availableOnline": "true",
            "limit": max(1, min(max(int(max_results or 1) * 3, 6), 20)),
        }, key=key)
        rows = self.parse(payload, query=query)[:max_results]
        deep = sum(1 for row in rows if row.reading_level() == "sections")
        if rows:
            self.last_note = (
                f"{len(rows)} NARA record mile; {deep} me API-exposed OCR/extracted/"
                "transcription body sections mile. Catalog description ko body read nahi maana gaya."
            )
        else:
            self.last_note = "NARA official API chali par relevant online archival record nahi mila"
        return rows


class ArchiveConnector:
    def __init__(self):
        self.connectors: List[BaseConnector] = [NaraCatalogConnector()]

    def by_name(self, name: str) -> Optional[BaseConnector]:
        return next((item for item in self.connectors if item.name == name), None)

    def available_names(self) -> List[str]:
        return [item.name for item in self.connectors]


__all__ = ["ArchiveConnector", "NaraCatalogConnector", "api_key", "nara_json"]
