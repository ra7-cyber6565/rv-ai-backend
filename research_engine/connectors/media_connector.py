"""MediaArchiveConnector — keyless archive media discovery + public captions.

This lane uses archive.org's own public APIs.  It never downloads audio/video
media, never bypasses access control and never treats a search description as a
transcript.  When an item exposes a public .vtt/.srt file in Archive metadata,
the connector may read that *text caption file* completely, parse timestamps,
and pass only a bounded relevant excerpt downstream while retaining an honest
full-transcript read marker.  Otherwise it falls back to the uploader-written
description with SNIPPET ONLY depth.

Critical truth boundaries:
- media discovered != media watched/listened
- description != transcript
- public caption text != audio/visual analysis
- transcript can support spoken-word claims only; not tone, melody, performance,
  frames, scenes or visuals
- existing-song lyrics/file-hunt queries remain blocked
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

from .. import songcraft
from ..models import SourceRecord, SourceType
from ..processing.transcript_processor import TranscriptProcessor
from .base import SLOW_TIMEOUT, BaseConnector, http_get

SEARCH_URL = "https://archive.org/advancedsearch.php"
METADATA_URL = "https://archive.org/metadata/{identifier}"
DOWNLOAD_URL = "https://archive.org/download/{identifier}/{name}"

MEDIA_TYPES: Tuple[str, ...] = ("movies", "audio")
MEDIATYPE_FILTER = "mediatype:(movies OR audio)"
CAPTION_EXTENSIONS: Tuple[str, ...] = (".vtt", ".srt")
MIN_DESCRIPTION_CHARS = 40
MIN_TRANSCRIPT_CHARS = 120
MAX_TRANSCRIPT_CHARS = 2_000_000
MAX_EXCERPT_CHARS = 1600

READ_LEVEL = "snippet"
NOT_READ_NOTE = (
    "Media KHUD nahi padha gaya — sirf archive.org par likha hua parichay "
    "(description) padha gaya. Video dekha nahi gaya, aawaz suni nahi gayi, "
    "public transcript/caption nahi mila.")
CAPTION_READ_NOTE = (
    "Archive.org ka PUBLIC caption/subtitle text poora process hua. Media file "
    "download/dekhi/suni nahi gayi; transcript se frame, scene, tone, melody, "
    "sur ya performance ka daawa nahi kiya ja sakta.")

MEDIA_LABELS: Dict[str, str] = {
    "movies": "video/lecture recording — media khud dekha nahi gaya",
    "audio": "aawaz ki recording — media khud suni nahi gayi",
}

LYRICS_BLOCK_NOTE = (
    "ye query kisi maujooda gaane ke bol/file dhoondh rahi thi, isliye ye "
    "lane chali hi nahi — craft padhna aur gaana utha lena do alag baat hai")


def media_label(mediatype: str) -> str:
    return MEDIA_LABELS.get(str(mediatype or "").strip().lower(), "")


def build_query(query: str) -> str:
    clean = " ".join(str(query or "").split())
    return f"{clean} AND {MEDIATYPE_FILTER}" if clean else ""


def _caption_name(files: List[Dict]) -> str:
    """Choose an explicit public subtitle/caption file; never choose media."""
    candidates: List[Tuple[int, str]] = []
    for raw in files or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        low = name.casefold()
        ext = next((suffix for suffix in CAPTION_EXTENSIONS if low.endswith(suffix)), "")
        if not name or not ext or low.startswith("__ia_thumb"):
            continue
        # Prefer VTT because it is a native web caption format; otherwise SRT.
        rank = 0 if ext == ".vtt" else 1
        candidates.append((rank, name))
    candidates.sort(key=lambda row: (row[0], len(row[1]), row[1].casefold()))
    return candidates[0][1] if candidates else ""


def _query_terms(query: str) -> set[str]:
    # This scorer only selects which already-read transcript block to expose; it
    # is not the search/relevance gate. Unicode word matching is intentionally
    # permissive and empty terms simply choose the earliest block.
    return {
        token.casefold() for token in re.findall(r"[^\W_]{3,}", str(query or ""), re.UNICODE)
        if token
    }


def _best_chunk(chunks: List[Dict], query: str) -> Dict:
    if not chunks:
        return {}
    terms = _query_terms(query)
    scored = []
    for index, chunk in enumerate(chunks):
        text = str(chunk.get("text") or "")
        words = {w.casefold() for w in re.findall(r"[^\W_]{3,}", text, re.UNICODE)}
        score = len(terms & words) if terms else 0
        scored.append((score, -index, chunk))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return dict(scored[0][2])


class MediaArchiveConnector(BaseConnector):
    """Archive.org media search; upgrades to transcript only with public captions."""

    name = "archive_media"
    source_type = SourceType.TRANSCRIPT
    timeout: Tuple[int, int] = SLOW_TIMEOUT

    def _public_caption(self, identifier: str, title: str, query: str) -> Dict:
        """Read a public VTT/SRT text file from Archive metadata, fail-closed."""
        try:
            meta_resp = http_get(
                METADATA_URL.format(identifier=quote(identifier, safe="")),
                timeout=self.timeout,
            )
            payload = meta_resp.json()
            name = _caption_name(payload.get("files") or [])
            if not name:
                return {"ok": False, "reason": "public caption file nahi mila"}

            caption_resp = http_get(
                DOWNLOAD_URL.format(
                    identifier=quote(identifier, safe=""),
                    name=quote(name, safe="/"),
                ),
                timeout=self.timeout,
            )
            raw = caption_resp.text or ""
            if len(raw) < MIN_TRANSCRIPT_CHARS:
                return {"ok": False, "reason": "caption text bahut chhota/khaali tha"}
            if len(raw) > MAX_TRANSCRIPT_CHARS:
                return {"ok": False,
                        "reason": "caption text local transcript safety cap se badi thi"}

            processor = TranscriptProcessor()
            cues = processor._parse_cues(raw)  # same parser used by uploaded VTT/SRT
            if not cues:
                return {"ok": False, "reason": "caption timestamps parse nahi hue"}
            chunks = processor.chunk(cues, title or identifier)
            best = _best_chunk(chunks, query)
            if not best or not str(best.get("text") or "").strip():
                return {"ok": False, "reason": "caption se usable block nahi bana"}
            return {
                "ok": True,
                "file": name,
                "chars": len(raw),
                "cues": len(cues),
                "blocks": len(chunks),
                "locator": str(best.get("locator") or ""),
                "excerpt": str(best.get("text") or "")[:MAX_EXCERPT_CHARS],
            }
        except Exception as exc:  # safe_search must not lose other media items
            return {"ok": False, "reason": f"public caption read fail: {type(exc).__name__}"}

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        clean = " ".join(str(query or "").split())
        if not clean:
            self.last_reason = "empty_query"
            self.last_note = "query khaali thi — koi call nahi bheji gayi"
            return []
        if songcraft.is_lyrics_hunt(clean):
            self.last_reason = "lyrics_hunt_blocked"
            self.last_note = LYRICS_BLOCK_NOTE
            return []

        rows = max(1, min(int(max_results or 1), 20))
        resp = http_get(
            SEARCH_URL,
            params={
                "q": build_query(clean),
                "fl[]": ["identifier", "title", "description", "creator",
                         "year", "date", "publisher", "mediatype", "subject"],
                "rows": rows,
                "page": 1,
                "output": "json",
            },
            timeout=self.timeout,
        )
        docs = (resp.json().get("response") or {}).get("docs", []) or []

        out: List[SourceRecord] = []
        dropped_kind = 0
        dropped_thin = 0
        caption_reads = 0
        caption_misses = 0
        for item in docs:
            mediatype = str(item.get("mediatype") or "").strip().lower()
            if mediatype not in MEDIA_TYPES:
                dropped_kind += 1
                continue
            identifier = str(item.get("identifier") or "").strip()
            if not identifier:
                dropped_thin += 1
                continue

            title = self._clean(item.get("title")) or identifier
            creator = item.get("creator")
            authors = creator if isinstance(creator, list) else ([creator] if creator else [])
            subject = item.get("subject")
            if isinstance(subject, list):
                subject = ", ".join(str(s) for s in subject[:5])

            caption = self._public_caption(identifier, title, clean)
            if caption.get("ok"):
                caption_reads += 1
                out.append(SourceRecord(
                    title=title,
                    url=f"https://archive.org/details/{identifier}",
                    snippet=self._clean(
                        f"{caption['excerpt']} [Public caption file: {caption['file']}] "
                        f"[{CAPTION_READ_NOTE}]", MAX_EXCERPT_CHARS + 500),
                    connector=self.name,
                    source_type=SourceType.TRANSCRIPT,
                    authors=[a for a in authors if a][:8],
                    year=self._year(item.get("year") or item.get("date")),
                    publisher=self._clean(item.get("publisher"), 200),
                    locator=str(caption.get("locator") or ""),
                    peer_reviewed=None,
                    is_primary=None,
                    full_text_available=True,
                    read_level="full_text",
                    full_text_chars=int(caption.get("chars") or 0),
                    read_note=(
                        f"{CAPTION_READ_NOTE} {caption.get('cues', 0)} cues / "
                        f"{caption.get('blocks', 0)} timestamped blocks process hue."
                    ),
                ))
                continue

            caption_misses += 1
            description = item.get("description")
            if isinstance(description, list):
                description = " ".join(str(part) for part in description)
            description = self._clean(description, 1200)
            if len(description) < MIN_DESCRIPTION_CHARS:
                dropped_thin += 1
                continue
            out.append(SourceRecord(
                title=title,
                url=f"https://archive.org/details/{identifier}",
                snippet=self._clean(
                    f"{description} [Media: {media_label(mediatype)}] "
                    f"[Subject: {subject or 'n/a'}] [{NOT_READ_NOTE}]", 1600),
                connector=self.name,
                source_type=SourceType.TRANSCRIPT,
                authors=[a for a in authors if a][:8],
                year=self._year(item.get("year") or item.get("date")),
                publisher=self._clean(item.get("publisher"), 200),
                peer_reviewed=None,
                is_primary=None,
                full_text_available=False,
                read_level=READ_LEVEL,
                read_note=NOT_READ_NOTE,
            ))

        if not out:
            if dropped_kind or dropped_thin or caption_misses:
                self.last_reason = "filtered"
            self.last_note = (
                f"0 media source bheje — {dropped_kind} non-media, {dropped_thin} "
                f"bina usable description, {caption_misses} item par public caption "
                f"nahi/usable nahi thi")
        else:
            self.last_note = (
                f"{len(out)} media source mile: {caption_reads} public caption text "
                f"poori process hui, {caption_misses} item caption ke bina description-only "
                f"rahe; media files kabhi download/dekhi/suni nahi gayi")
        return out


class MediaConnector:
    """Media lane facade."""

    def __init__(self):
        self.connectors: List[BaseConnector] = [MediaArchiveConnector()]

    def by_name(self, name: str) -> Optional[BaseConnector]:
        return next((c for c in self.connectors if c.name == name), None)

    def search(self, query: str, max_per_source: int = 3,
               only: Optional[List[str]] = None) -> Dict:
        records: List[SourceRecord] = []
        log: List[Dict] = []
        for connector in self.connectors:
            if only and connector.name not in only:
                continue
            result = connector.safe_search(query, max_per_source)
            records.extend(result["records"])
            log.append({k: v for k, v in result.items() if k != "records"})
        return {"records": records, "log": log}
