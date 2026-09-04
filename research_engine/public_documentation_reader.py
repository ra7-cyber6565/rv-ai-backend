"""Bounded public documentation/manual page reader for AI-1.

This closes a source-family gap without turning the engine into an unrestricted
scraper. Only sources already selected into the EvidencePack and carrying
strong documentation/manual/reference signals are eligible. Requests use the
shared SSRF/redirect guards, public DNS resolution, a strict byte cap, and HTML
content-type checks. Authentication, paywalls and whole-site crawling are never
attempted.

Truth boundaries:
- search snippet != documentation body;
- one public documentation page != an entire manual/site;
- documentation text describes an implementation/interface; it is not proof
  that software behaves correctly in every environment;
- code examples are text unless separately inspected/executed by the code lane.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Dict, List, Sequence, Tuple
from urllib.parse import urlsplit

from .connectors.base import SLOW_TIMEOUT
from .models import Passage, SourceRecord, SourceType
from .network_safety import (
    NetworkSafetyError,
    public_error,
    read_bounded_response,
    require_content_type,
    safe_get_with_redirects,
    validate_public_http_url,
)

MAX_DOC_HTML_BYTES = 2 * 1024 * 1024
MAX_DOC_BLOCKS = 1200
MAX_DOC_EXCERPT_CHARS = 5000
MAX_SELECTED_BLOCKS = 8

_DOC_TITLE_CUES = re.compile(
    r"\b(documentation|docs?|manual|reference|api reference|developer guide|"
    r"user guide|technical note|specification|configuration|command reference|"
    r"integration guide|sdk reference)\b", re.I,
)
_DOC_PATH_CUES = (
    "/docs/", "/doc/", "/documentation/", "/manual/", "/reference/",
    "/guide/", "/guides/", "/api/", "/developers/", "/developer/",
)
_DOC_HOST_PREFIXES = ("docs.", "doc.", "developer.", "developers.", "api.")
_DOC_HOST_MARKERS = ("readthedocs.io", "readthedocs.org")
_BLOCK_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "code",
    "dt", "dd", "blockquote", "td", "th",
}
_SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "iframe"}


def documentation_candidate(source: SourceRecord) -> bool:
    if source.source_type not in {SourceType.WEB, SourceType.ENCYCLOPEDIA}:
        return False
    url = str(source.url or "").strip()
    if not url.startswith(("https://", "http://")):
        return False
    try:
        parsed = urlsplit(url)
    except Exception:
        return False
    host = (parsed.hostname or "").casefold()
    path = (parsed.path or "/").casefold()
    blob = " ".join((
        str(source.title or ""), str(source.doc_kind or ""),
        str(source.doc_kind_label or ""), str(source.venue or ""),
    ))
    return bool(
        _DOC_TITLE_CUES.search(blob)
        or any(path.startswith(cue) or cue in path for cue in _DOC_PATH_CUES)
        or any(host.startswith(prefix) for prefix in _DOC_HOST_PREFIXES)
        or any(marker in host for marker in _DOC_HOST_MARKERS)
    )


class _BlockParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._stack: List[str] = []
        self._capture_tag = ""
        self._buffer: List[str] = []
        self.blocks: List[Dict] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        low = str(tag or "").casefold()
        self._stack.append(low)
        if low in _SKIP_TAGS:
            return
        if low in _BLOCK_TAGS and not self._capture_tag:
            self._capture_tag = low
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        low = str(tag or "").casefold()
        if self._capture_tag == low:
            text = " ".join(" ".join(self._buffer).split())
            if len(text) >= 20 and len(self.blocks) < MAX_DOC_BLOCKS:
                self.blocks.append({"tag": low, "text": text[:6000]})
            self._capture_tag = ""
            self._buffer = []
        if self._stack:
            try:
                index = len(self._stack) - 1 - self._stack[::-1].index(low)
                del self._stack[index:]
            except ValueError:
                pass

    def handle_data(self, data: str) -> None:
        if not self._capture_tag:
            return
        if any(tag in _SKIP_TAGS for tag in self._stack):
            return
        clean = " ".join(str(data or "").split())
        if clean:
            self._buffer.append(clean)


def _query_terms(question: str) -> set[str]:
    stop = {
        "the", "and", "for", "with", "that", "this", "from", "what", "how",
        "why", "does", "can", "kya", "kaise", "hai", "mein", "aur", "par",
    }
    return {
        word.casefold() for word in re.findall(r"[^\W_]{3,}", str(question or ""), re.UNICODE)
        if word.casefold() not in stop
    }


def _select_blocks(blocks: Sequence[Dict], question: str) -> List[Dict]:
    terms = _query_terms(question)
    scored: List[Tuple[int, int, Dict]] = []
    last_heading = ""
    for index, raw in enumerate(blocks):
        block = dict(raw)
        tag = str(block.get("tag") or "")
        text = str(block.get("text") or "")
        if tag.startswith("h"):
            last_heading = text[:180]
        words = {word.casefold() for word in re.findall(r"[^\W_]{3,}", text, re.UNICODE)}
        overlap = len(terms & words)
        heading_bonus = 2 if tag.startswith("h") else 0
        code_bonus = 1 if tag in {"pre", "code"} and overlap else 0
        block["heading_context"] = last_heading
        scored.append((overlap * 4 + heading_bonus + code_bonus, -index, block))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    selected: List[Dict] = []
    chars = 0
    for score, _neg_index, block in scored:
        if len(selected) >= MAX_SELECTED_BLOCKS or chars >= MAX_DOC_EXCERPT_CHARS:
            break
        text = str(block.get("text") or "")
        if not text:
            continue
        room = MAX_DOC_EXCERPT_CHARS - chars
        if len(text) > room:
            text = text[:room].rsplit(" ", 1)[0] + " …"
        item = dict(block)
        item["text"] = text
        item["relevance_score"] = score
        selected.append(item)
        chars += len(text)
    return selected


def _decode_html(data: bytes, response) -> str:
    encoding = str(getattr(response, "encoding", "") or "").strip() or "utf-8"
    try:
        return data.decode(encoding, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


class PublicDocumentationReader:
    name = "public_documentation_reader"

    def __init__(self, allow_network: bool = True):
        self.allow_network = bool(allow_network)

    def inspect(self, source: SourceRecord, question: str) -> Dict:
        if not self.allow_network:
            return {"ok": False, "reason": "documentation network fetch config se band hai"}
        if not documentation_candidate(source):
            return {"ok": False, "reason": "source documentation/manual page candidate nahi hai"}
        try:
            validate_public_http_url(source.url, resolve_dns=True)
        except NetworkSafetyError as exc:
            return {"ok": False, "reason": public_error(exc)}

        response = None
        try:
            import requests
            response, final_url = safe_get_with_redirects(
                requests,
                source.url,
                headers={
                    "User-Agent": "InfinityResearchAI/1.0 (bounded public documentation research)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/xml;q=0.8",
                },
                timeout=SLOW_TIMEOUT,
                stream=True,
                resolve_dns=True,
                max_redirects=3,
            )
            status = int(getattr(response, "status_code", 200) or 200)
            if status in {401, 403}:
                return {"ok": False, "reason": f"documentation access HTTP {status}; auth bypass nahi kiya"}
            if status == 429:
                return {"ok": False, "reason": "documentation host rate limited (HTTP 429)"}
            if status >= 400:
                return {"ok": False, "reason": f"documentation page HTTP {status}"}
            require_content_type(response, "html")
            data = read_bounded_response(response, MAX_DOC_HTML_BYTES)
            parser = _BlockParser()
            parser.feed(_decode_html(data, response))
            blocks = parser.blocks
            if not blocks:
                return {"ok": False, "reason": "public documentation HTML me usable text blocks nahi mile"}
            selected = _select_blocks(blocks, question)
            if not selected:
                return {"ok": False, "reason": "documentation page se bounded relevant excerpt nahi bana"}
            rendered: List[str] = []
            for row in selected:
                context = str(row.get("heading_context") or "").strip()
                label = f"[{context}]" if context else f"[{row.get('tag') or 'block'}]"
                rendered.append(f"{label} {row.get('text')}")
            excerpt = "\n\n".join(rendered)[:MAX_DOC_EXCERPT_CHARS]
            first_context = str(selected[0].get("heading_context") or "").strip()
            locator = f"documentation page: {first_context}" if first_context else "documentation page excerpt"
            return {
                "ok": True,
                "excerpt": excerpt,
                "locator": locator,
                "inspection": {
                    "status": "DOCUMENTATION_PAGE_INSPECTED",
                    "requested_url": source.url,
                    "final_url": final_url,
                    "bytes_read": len(data),
                    "blocks_parsed": len(blocks),
                    "blocks_selected": len(selected),
                    "page_complete_claimed": False,
                    "site_or_manual_complete": False,
                    "authentication_bypassed": False,
                    "bounded": True,
                    "truth_boundary": (
                        "one public documentation page != whole manual/site; documentation text != runtime correctness proof"
                    ),
                },
            }
        except Exception as exc:
            return {"ok": False, "reason": f"documentation read fail: {public_error(exc)}"}
        finally:
            try:
                if response is not None:
                    response.close()
            except Exception:
                pass

    def enrich(self, pack, *, max_sources: int = 2) -> Dict:
        report = {"attempted": 0, "succeeded": 0, "failed": 0, "entries": []}
        candidates = [
            (index, source) for index, source in enumerate(list(getattr(pack, "sources", []) or []))
            if documentation_candidate(source)
            and source.reading_level() not in {"sections", "claims", "full_text"}
        ]
        candidates.sort(key=lambda row: (-float(row[1].combined_score or 0.0), row[0]))
        for _index, source in candidates[:max(0, int(max_sources))]:
            report["attempted"] += 1
            result = self.inspect(source, getattr(pack, "question", ""))
            report["entries"].append({
                "source_id": source.source_id,
                "title": source.title[:100],
                "ok": bool(result.get("ok")),
                "reason": result.get("reason", ""),
            })
            if not result.get("ok"):
                report["failed"] += 1
                continue
            inspection = dict(result.get("inspection") or {})
            verdict = dict(source.domain_verdict or {})
            verdict["documentation_inspection"] = inspection
            source.domain_verdict = verdict
            source.read_level = "sections"
            source.full_text_available = False
            source.full_text_chars = 0
            source.read_note = (
                "Public documentation/manual ka ek bounded page inspect hua; poora docs site/manual "
                "nahi padha maana gaya, auth/paywall bypass nahi hua."
            )
            source.snippet = str(result.get("excerpt") or "")
            source.locator = str(result.get("locator") or source.locator)
            pack.passages[:] = [p for p in pack.passages if p.source_id != source.source_id]
            pack.passages.append(Passage(
                source_id=source.source_id,
                text=source.snippet,
                locator=source.locator,
                provenance="public_documentation_page_excerpt",
                read_level_at_capture="sections",
            ))
            report["succeeded"] += 1
        report["note"] = (
            f"{report['succeeded']}/{report['attempted']} bounded public documentation page inspect hue; "
            "page ko whole manual/site ya runtime proof nahi maana gaya."
            if report["attempted"] else
            "Pack me shallow documentation/manual page candidate nahi tha."
        )
        return report


__all__ = ["PublicDocumentationReader", "documentation_candidate"]
