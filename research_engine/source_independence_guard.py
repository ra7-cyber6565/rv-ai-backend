"""Separate *independent work* identity from *origin concentration* identity.

Historically ``SourceRecord.independence_key`` mixed two different questions:

1. Is this the same underlying study/work/invention copied somewhere else?
2. Did these records come from the same publisher/domain/provider origin?

For DOI-less sources the old fallback was the domain, so two genuinely distinct
papers hosted on the same journal/repository domain became one "independent
voice".  That undercounted evidence and, more seriously, caused Autonomous
Literature Debate to discard distinct A/B/C arguments before its reliability
gate could inspect them.

This deterministic package-boundary guard gives the two concepts separate keys:

- ``work_independence_key``: DOI/patent family/title/content identity used for
  evidence independence, consensus/debate and corroboration counts.
- ``origin_key``: compatibility form of the old key, used only where the intent
  is source-list concentration/ranking.

The public ``independence_key`` property is redirected to *work* identity because
all evidence-strength consumers use that name.  ``DeduplicationEngine``'s
``cap_per_origin`` is patched to use ``origin_key`` explicitly, preserving its
previous ranking/concentration behavior.  No network/model call is involved.
"""
from __future__ import annotations

import hashlib
import re
from typing import Dict, List
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .models import EvidencePack, SourceRecord, SourceType, normalize_doi


_TRACKING_QUERY_PREFIXES = ("utm_",)
_TRACKING_QUERY_NAMES = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "source",
}


def _normalized_title(source: SourceRecord) -> str:
    value = str(getattr(source, "normalized_title", "") or "").strip()
    if value:
        return value[:240]
    text = re.sub(r"[^\w\s]", " ", str(getattr(source, "title", "") or "").casefold())
    return re.sub(r"\s+", " ", text).strip()[:240]


def _canonical_url(value: object) -> str:
    """Stable URL identity without fragments or obvious tracking parameters."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return raw.casefold().rstrip("/")[:700]
    if not parsed.netloc:
        return raw.casefold().rstrip("/")[:700]
    host = parsed.netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/") or "/"
    kept = []
    for key, val in parse_qsl(parsed.query, keep_blank_values=True):
        low = key.casefold()
        if low in _TRACKING_QUERY_NAMES or any(low.startswith(p) for p in _TRACKING_QUERY_PREFIXES):
            continue
        kept.append((key, val))
    query = urlencode(sorted(kept))
    return urlunparse(("", host, path, "", query, ""))[:700]


def _content_fingerprint(source: SourceRecord) -> str:
    text = re.sub(r"\s+", " ", str(getattr(source, "snippet", "") or "").casefold()).strip()
    if not text:
        return ""
    return hashlib.sha256(text[:4000].encode("utf-8", errors="ignore")).hexdigest()[:24]


def origin_key(source: SourceRecord) -> str:
    """Compatibility form of the pre-split key used for concentration caps."""
    if getattr(source, "is_patent", False):
        family = str(getattr(source, "patent_family_key", "") or "")
        if family:
            return family
    doi = normalize_doi(getattr(source, "doi", ""))
    if doi:
        return f"doi:{doi}"
    if getattr(source, "source_type", None) == SourceType.DOCUMENT:
        return f"doc:{str(getattr(source, 'title', '') or '').casefold()}"
    domain = str(getattr(source, "domain", "") or "")
    if domain:
        return f"domain:{domain}"
    title = _normalized_title(source)
    return f"title:{title[:60]}" if title else "unknown-origin"


def work_independence_key(source: SourceRecord) -> str:
    """Underlying-work identity used when counting independent evidence.

    Priority is intentionally strongest-to-weakest.  DOI and patent family are
    explicit work identities.  A sufficiently descriptive normalized title is
    next because exact/near-title duplicates have already gone through the
    normal dedup engine; it also collapses the same DOI-less work mirrored on a
    second host.  Canonical URL then distinguishes different pages on one domain.
    Content fingerprint is a last-resort identity for untitled excerpts.
    """
    if getattr(source, "is_patent", False):
        family = str(getattr(source, "patent_family_key", "") or "")
        if family:
            return family

    doi = normalize_doi(getattr(source, "doi", ""))
    if doi:
        return f"doi:{doi}"

    title = _normalized_title(source)
    title_tokens = [token for token in title.split() if len(token) >= 3]
    if getattr(source, "source_type", None) == SourceType.DOCUMENT and title:
        return f"doc:{title}"
    if len(title_tokens) >= 3 and len(title) >= 18:
        return f"work-title:{title}"

    url = _canonical_url(getattr(source, "url", ""))
    if url:
        return f"url:{url}"

    fingerprint = _content_fingerprint(source)
    if fingerprint:
        return f"content:{fingerprint}"

    # With no work-level identifier or content, fail conservatively to origin:
    # metadata-only anonymous rows from one origin should not inflate evidence.
    return origin_key(source)


def _install_source_properties() -> None:
    SourceRecord.origin_key = property(origin_key)  # type: ignore[attr-defined]
    SourceRecord.work_independence_key = property(work_independence_key)  # type: ignore[attr-defined]
    SourceRecord.independence_key = property(work_independence_key)  # type: ignore[assignment]


def _install_pack_property() -> None:
    def independent_source_count(pack: EvidencePack) -> int:
        return len({work_independence_key(source) for source in (pack.sources or [])})

    EvidencePack.independent_source_count = property(independent_source_count)  # type: ignore[assignment]


def _install_dedup_semantics() -> None:
    # Import lazily here so this small module can be imported with models only.
    from .dedup import DeduplicationEngine

    def independence_groups(self, sources: List[SourceRecord]) -> Dict[str, List[SourceRecord]]:
        groups: Dict[str, List[SourceRecord]] = {}
        for source in sources:
            groups.setdefault(work_independence_key(source), []).append(source)
        return groups

    def independence_report(self, sources: List[SourceRecord]) -> Dict:
        work_groups = independence_groups(self, sources)
        origin_groups: Dict[str, List[SourceRecord]] = {}
        for source in sources:
            origin_groups.setdefault(origin_key(source), []).append(source)
        repeated_works = {key: len(rows) for key, rows in work_groups.items() if len(rows) > 1}
        repeated_origins = {key: len(rows) for key, rows in origin_groups.items() if len(rows) > 1}
        return {
            "total_sources": len(sources),
            # Legacy key remains for API compatibility, but its meaning is now
            # exactly independent underlying works rather than a domain/work mix.
            "independent_voices": len(work_groups),
            "independent_works": len(work_groups),
            "independent_origins": len(origin_groups),
            "repeated_works": repeated_works,
            "repeated_origins": repeated_origins,
            "note": (
                "Independent works aur source origins alag ginte hain: same DOI/patent-family/"
                "same work copy ek evidence hai, lekin ek hi journal/domain par chhapi do "
                "alag studies ko sirf host same hone ki wajah se ek nahi maana jaata."
            ),
        }

    def cap_per_origin(self, sources: List[SourceRecord], max_per_origin: int = 3) -> List[SourceRecord]:
        """Preserve the legacy concentration-cap semantics using explicit origin keys."""
        counts: Dict[str, int] = {}
        out: List[SourceRecord] = []
        for source in sources:
            key = origin_key(source)
            if counts.get(key, 0) >= max_per_origin:
                continue
            counts[key] = counts.get(key, 0) + 1
            out.append(source)
        return out

    DeduplicationEngine.independence_groups = independence_groups  # type: ignore[assignment]
    DeduplicationEngine.independence_report = independence_report  # type: ignore[assignment]
    DeduplicationEngine.cap_per_origin = cap_per_origin  # type: ignore[assignment]


def install() -> None:
    """Install the split identity semantics idempotently at package import."""
    if getattr(SourceRecord, "_independence_semantics_version", "") == "2.0":
        return
    _install_source_properties()
    _install_pack_property()
    _install_dedup_semantics()
    SourceRecord._independence_semantics_version = "2.0"  # type: ignore[attr-defined]


__all__ = ["install", "origin_key", "work_independence_key"]
