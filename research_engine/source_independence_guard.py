"""Separate *independent work* identity from *origin concentration* identity.

Historically ``SourceRecord.independence_key`` mixed two different questions:

1. Is this the same underlying study/work/invention copied somewhere else?
2. Did these records come from the same publisher/domain/provider origin?

For DOI-less sources the old fallback was the domain, so two genuinely distinct
papers hosted on the same journal/repository domain became one "independent
voice". That undercounted evidence and, more seriously, caused Autonomous
Literature Debate to discard distinct A/B/C arguments before its reliability
gate could inspect them.

This deterministic package-boundary guard gives the two concepts separate keys:

- ``work_independence_key``: DOI/patent family/title/content identity used for
  evidence independence, consensus/debate and corroboration counts.
- ``origin_key``: publisher/domain/provider identity used only for source-list
  concentration and diversity reporting.

The public ``independence_key`` property is redirected to *work* identity because
all evidence-strength consumers use that name. ``DeduplicationEngine``'s
``cap_per_origin`` is patched to use ``origin_key`` explicitly. Literature-debate
coverage is also normalized so "works" and "origins" are never reported as the
same denominator.

No network/model call is involved.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Mapping
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


def _origin_text(value: object, limit: int = 180) -> str:
    """Stable readable identity for publisher/provider metadata."""
    text = re.sub(r"[^\w.\-\s]", " ", str(value or "").casefold())
    text = re.sub(r"\s+", " ", text).strip()
    return text[: max(20, int(limit))]


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
    """Publisher/domain/provider identity for concentration and diversity.

    This key must *not* use DOI or patent-family identity before origin metadata.
    A DOI identifies a work, not its hosting/publishing origin. The previous
    implementation returned ``doi:<full-doi>`` first, which meant four papers
    from the same journal escaped ``cap_per_origin`` merely because each had a
    different DOI. That silently defeated the concentration guard exactly on
    the best-metadata scholarly records.

    Priority therefore is:
      user document -> host/domain -> publisher/venue -> connector/provider ->
      DOI registrant prefix (last metadata fallback) -> unknown origin.
    """
    if getattr(source, "source_type", None) == SourceType.DOCUMENT:
        title = _normalized_title(source)
        return f"doc:{title}" if title else "doc:unknown"

    domain = _origin_text(getattr(source, "domain", ""))
    if domain:
        return f"domain:{domain}"

    publisher = _origin_text(
        getattr(source, "publisher", "") or getattr(source, "venue", "")
    )
    if publisher:
        return f"publisher:{publisher}"

    connector = _origin_text(getattr(source, "connector", ""))
    if connector:
        return f"connector:{connector}"

    # DOI registrant prefix is weaker than an actual publisher/domain, but when
    # it is the only origin-like metadata it is still safer than treating every
    # DOI as its own origin. Example 10.1234/a and 10.1234/b share one registrant.
    doi = normalize_doi(getattr(source, "doi", ""))
    if doi and "/" in doi:
        return f"doi-prefix:{doi.split('/', 1)[0]}"

    return "unknown-origin"


def work_independence_key(source: SourceRecord) -> str:
    """Underlying-work identity used when counting independent evidence.

    Priority is intentionally strongest-to-weakest. DOI and patent family are
    explicit work identities. A sufficiently descriptive normalized title is
    next because exact/near-title duplicates have already gone through the
    normal dedup engine; it also collapses the same DOI-less work mirrored on a
    second host. Canonical URL then distinguishes different pages on one domain.
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
                "alag studies ko sirf host same hone ki wajah se ek nahi maana jaata. "
                "Origin diversity alag metric hai aur DOI ko origin nahi maana jaata."
            ),
        }

    def cap_per_origin(self, sources: List[SourceRecord], max_per_origin: int = 3) -> List[SourceRecord]:
        """Bound one publisher/domain/provider without collapsing distinct works."""
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


def _install_literature_debate_semantics() -> None:
    """Keep debate work-independence while reporting origin diversity truthfully.

    ``literature_debate.py`` historically named its set of ``independence_key``
    values ``reliable_origins``. After ``independence_key`` became a *work* key,
    the debate readiness logic became correct (three distinct studies remain
    three studies) but coverage labels became misleading. Patch only the output
    accounting: readiness remains based on independent works, while publisher/
    host origin concentration is exposed separately.
    """
    from .literature_debate import AutonomousLiteratureDebate

    if getattr(AutonomousLiteratureDebate, "_independence_semantics_version", "") == "2.1":
        return

    original = AutonomousLiteratureDebate.reconstruct

    def reconstruct(self, question: str, pack: EvidencePack, contradictions=()):
        result = original(self, question, pack, contradictions)
        if not isinstance(result, dict) or not isinstance(pack, EvidencePack):
            return result

        # Compatibility alias: some callers/tests historically used role_presence
        # while the production module exposes the more explicit reliable name.
        role_presence = dict(result.get("role_presence_reliable") or {})
        if role_presence:
            result["role_presence"] = dict(role_presence)

        if result.get("status") == "INVALID_INPUT":
            return result

        by_id = {
            str(getattr(source, "source_id", "") or ""): source
            for source in (pack.sources or [])
            if str(getattr(source, "source_id", "") or "").strip()
        }
        work_keys = set()
        origin_keys = set()
        full_work_keys = set()
        full_origin_keys = set()

        slots = result.get("role_slots") or {}
        if isinstance(slots, Mapping):
            for arguments in slots.values():
                for argument in list(arguments or []):
                    if not isinstance(argument, Mapping):
                        continue
                    if not bool(argument.get("reliable_current_evidence")):
                        continue
                    sid = str(argument.get("source_id") or "")
                    source = by_id.get(sid)
                    if source is None:
                        continue
                    work = work_independence_key(source)
                    origin = origin_key(source)
                    work_keys.add(work)
                    origin_keys.add(origin)
                    if str(argument.get("read_level") or "") == "full_text":
                        full_work_keys.add(work)
                        full_origin_keys.add(origin)

        coverage = result.setdefault("coverage", {})
        if isinstance(coverage, dict):
            coverage["independent_current_works"] = len(work_keys)
            coverage["independent_current_origins"] = len(origin_keys)
            coverage["reliable_argument_works"] = len(work_keys)
            # Correct the old misleading name, which previously held work count.
            coverage["reliable_argument_origins"] = len(origin_keys)
            coverage["full_text_argument_works"] = len(full_work_keys)
            coverage["full_text_argument_origins"] = len(full_origin_keys)
            coverage["origin_concentration_warning"] = bool(
                len(work_keys) >= 3 and len(origin_keys) < 2
            )

        honesty = result.setdefault("honesty", {})
        if isinstance(honesty, dict):
            honesty["debate_readiness_uses_independent_works"] = True
            honesty["origin_diversity_reported_separately"] = True
            honesty["same_domain_distinct_works_collapsed"] = False

        note = str(result.get("note") or "").strip()
        addition = (
            "Debate readiness independent WORKS par based hai; journal/publisher/host "
            "origin diversity alag report hoti hai aur usse work count nahi banaya jaata."
        )
        if addition not in note:
            result["note"] = f"{note} {addition}".strip()
        return result

    AutonomousLiteratureDebate.reconstruct = reconstruct  # type: ignore[assignment]
    AutonomousLiteratureDebate._independence_semantics_version = "2.1"  # type: ignore[attr-defined]


def install() -> None:
    """Install the split identity semantics idempotently at package import."""
    if getattr(SourceRecord, "_independence_semantics_version", "") == "2.1":
        return
    _install_source_properties()
    _install_pack_property()
    _install_dedup_semantics()
    _install_literature_debate_semantics()
    SourceRecord._independence_semantics_version = "2.1"  # type: ignore[attr-defined]


__all__ = ["install", "origin_key", "work_independence_key"]