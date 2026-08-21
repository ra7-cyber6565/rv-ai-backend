"""
§12 — badi PDF ko "unusable" nahi hone dena.

Large documents are processed page-by-page with bounded memory.  A second
important guard is *coverage*: when a PDF has more pages than the scan budget,
we must not inspect only the first N pages.  That front-bias can silently miss a
late methods/results chapter.  ``sample_page_indices`` therefore keeps the
opening pages, the ending pages, and an evenly-spread sample across the whole
PDF.  Selection still happens by relevance, and the report says honestly when
only a sparse sample was inspected.

This module stays pure-Python so the selection/sampling policy is deterministic,
offline-testable and costs no model/API quota.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Dict, Iterable, List

DEFAULT_HEAD_PAGES = 3
DEFAULT_TAIL_PAGES = 3
DEFAULT_MAX_PAGES_SCANNED = 800
DEFAULT_MAX_KEEP_PAGES = 30
DEFAULT_MAX_KEEP_CHARS = 200_000
DEFAULT_PER_PAGE_CHARS = 6_000

SCANNED_PAGE_CHARS = 40
_HEAD_BONUS = 1.0


def page_score(text: str, question: str) -> float:
    """Ek page kitna kaam ka hai — 0..1, deterministic and zero-cost."""
    body = str(text or "").strip()
    if not body:
        return 0.0
    try:
        from .. import semantic
        return float(semantic.similarity(question or "", body))
    except Exception:  # pragma: no cover - defensive fallback
        import re
        q = {w for w in re.findall(r"[a-z]{4,}", (question or "").lower())}
        if not q:
            return 0.0
        t = {w for w in re.findall(r"[a-z]{4,}", body.lower())}
        return round(len(q & t) / len(q), 4)


def sample_page_indices(
    page_count: int,
    max_pages: int,
    *,
    head_pages: int = DEFAULT_HEAD_PAGES,
    tail_pages: int = DEFAULT_TAIL_PAGES,
) -> List[int]:
    """Return sorted 0-based page indices spread across the whole document."""
    total = max(0, int(page_count or 0))
    limit = int(max_pages or 0)
    if total <= 0:
        return []
    if limit <= 0 or limit >= total:
        return list(range(total))

    limit = max(1, min(limit, total))
    picked = set()

    head = min(max(0, int(head_pages or 0)), limit, total)
    picked.update(range(head))

    remaining = limit - len(picked)
    tail = min(max(0, int(tail_pages or 0)), remaining, total - len(picked))
    if tail:
        picked.update(range(total - tail, total))

    remaining = limit - len(picked)
    interior_start = head
    interior_end = max(interior_start, total - tail)
    span = max(0, interior_end - interior_start)

    if remaining > 0 and span > 0:
        for i in range(remaining):
            fraction = (i + 1) / (remaining + 1)
            candidate = interior_start + int(round(fraction * max(0, span - 1)))
            candidate = min(interior_end - 1, max(interior_start, candidate))
            picked.add(candidate)

    if len(picked) < limit:
        for candidate in range(total):
            picked.add(candidate)
            if len(picked) >= limit:
                break

    return sorted(picked)[:limit]


@dataclass
class PageSelection:
    """Kitna inspect kiya, kitna rakha, aur kis coverage policy se — sab track."""
    chunks: List[Dict] = field(default_factory=list)
    pages_total: int = 0
    pages_scanned: int = 0
    pages_kept: int = 0
    image_only_pages: List[int] = field(default_factory=list)
    chars_kept: int = 0
    stopped_early: bool = False
    dropped_for_budget: int = 0
    file_name: str = ""
    sampling_mode: str = "sequential"

    @property
    def ok(self) -> bool:
        return bool(self.chunks)

    def text(self) -> str:
        return "\n\n".join(
            f"{c.get('header') or ''}\n{c.get('text') or ''}".strip()
            for c in self.chunks
        )

    def note(self) -> str:
        if not self.pages_scanned:
            return "PDF se ek bhi page padha nahi / inspect nahi kiya ja saka."
        total = self.pages_total or self.pages_scanned
        pages = ", ".join(
            str(c.get("page")) for c in self.chunks[:8] if c.get("page")
        )

        if self.sampling_mode == "whole_document_sparse":
            bits = [
                f"badi PDF ko whole-document sparse sampling se padha gaya: "
                f"{self.pages_scanned}/{total} pages inspect hue (sirf starting pages "
                f"nahi — beginning, beech aur end tak spread sample), aur sawaal se "
                f"sabse milte-julte {self.pages_kept} pages rakhe gaye"
            ]
        else:
            bits = [
                f"badi PDF page-by-page padhi gayi: {self.pages_scanned}/{total} "
                f"pages inspect hue, sawaal se sabse milte-julte {self.pages_kept} "
                f"pages rakhe gaye"
            ]

        if pages:
            bits.append(f"chune gaye pages: p.{pages}")
        if self.image_only_pages:
            bits.append(
                f"inspect kiye sample mein {len(self.image_only_pages)} pages image-only "
                f"(scanned) the — unka content OCR ke bina use nahi hua"
            )
        if self.dropped_for_budget:
            bits.append(
                f"{self.dropped_for_budget} kam-relevant inspected pages final context "
                f"budget ke bahar rahe"
            )
        if self.stopped_early:
            if self.sampling_mode == "whole_document_sparse":
                bits.append(
                    f"safety budget ki wajah se har page inspect nahi hua; poore "
                    f"{total}-page document mein spread sample use hua, first-N-only nahi"
                )
            else:
                bits.append(
                    f"safety limit par ruke — {total} mein se pehle "
                    f"{self.pages_scanned} pages hi inspect hue"
                )
        return "; ".join(bits)

    def to_dict(self) -> Dict:
        return {
            "pages_total": self.pages_total,
            "pages_scanned": self.pages_scanned,
            "pages_kept": self.pages_kept,
            "image_only_pages": list(self.image_only_pages),
            "chars_kept": self.chars_kept,
            "stopped_early": self.stopped_early,
            "dropped_for_budget": self.dropped_for_budget,
            "selected_pages": [c.get("page") for c in self.chunks],
            "sampling_mode": self.sampling_mode,
            "note": self.note(),
        }


def select_pages(
    pages: Iterable[Dict],
    question: str,
    *,
    file_name: str = "",
    pages_total: int = 0,
    head_pages: int = DEFAULT_HEAD_PAGES,
    max_pages_scanned: int = DEFAULT_MAX_PAGES_SCANNED,
    max_keep_pages: int = DEFAULT_MAX_KEEP_PAGES,
    max_keep_chars: int = DEFAULT_MAX_KEEP_CHARS,
    per_page_chars: int = DEFAULT_PER_PAGE_CHARS,
    min_score: float = 0.0,
    sampling_mode: str = "sequential",
) -> PageSelection:
    """Stream candidate pages and keep only the strongest bounded evidence."""
    sel = PageSelection(
        pages_total=int(pages_total or 0),
        file_name=file_name or "",
        sampling_mode=sampling_mode or "sequential",
    )
    heap: List = []
    seq = 0

    for raw in pages or []:
        if sel.pages_scanned >= max_pages_scanned:
            sel.stopped_early = True
            break
        seq += 1
        page_no = int(raw.get("page") or seq)
        text = str(raw.get("text") or "").strip()
        sel.pages_scanned += 1
        if sel.pages_total and page_no > sel.pages_total:
            sel.pages_total = page_no

        if len(text) < SCANNED_PAGE_CHARS:
            sel.image_only_pages.append(page_no)
            continue

        if len(text) > per_page_chars:
            text = text[:per_page_chars].rsplit(" ", 1)[0] + " …"

        score = page_score(text, question)
        if seq <= max(0, head_pages):
            score += _HEAD_BONUS
        elif score <= min_score:
            sel.dropped_for_budget += 1
            continue

        heapq.heappush(heap, (round(score, 4), page_no, text))
        if len(heap) > max(1, max_keep_pages):
            heapq.heappop(heap)
            sel.dropped_for_budget += 1

    if not sel.pages_total:
        sel.pages_total = sel.pages_scanned

    if (
        sel.sampling_mode == "whole_document_sparse"
        and sel.pages_total > sel.pages_scanned
    ):
        sel.stopped_early = True

    ranked = sorted(heap, key=lambda row: (-row[0], row[1]))
    kept: List = []
    used = 0
    for score, page_no, text in ranked:
        if used >= max_keep_chars:
            sel.dropped_for_budget += 1
            continue
        room = max_keep_chars - used
        if len(text) > room:
            text = text[:room].rsplit(" ", 1)[0] + " …"
        kept.append((score, page_no, text))
        used += len(text)

    kept.sort(key=lambda row: row[1])
    name = sel.file_name or "document.pdf"
    sel.chunks = [
        {
            "locator": f"p.{page_no}",
            "page": page_no,
            "text": text,
            "score": score,
            "header": f"[Source: {name}, Page {page_no}]",
        }
        for score, page_no, text in kept
    ]
    sel.pages_kept = len(sel.chunks)
    sel.chars_kept = used
    return sel


def is_large(
    size_bytes: int = 0,
    page_count: int = 0,
    large_bytes: int = 4 * 1024 * 1024,
    large_pages: int = 60,
) -> bool:
    """Large means use bounded streaming; it never means reject the document."""
    return bool(
        (size_bytes and size_bytes > large_bytes)
        or (page_count and page_count > large_pages)
    )


def budget_for(size_bytes: int = 0, page_count: int = 0) -> Dict:
    """Larger documents get tighter retained-context limits, never zero budget."""
    mb = float(size_bytes or 0) / (1024 * 1024)
    if page_count > 2000 or mb > 60:
        return {
            "max_keep_pages": 12,
            "max_keep_chars": 90_000,
            "per_page_chars": 4_000,
            "max_pages_scanned": 2_500,
        }
    if page_count > 400 or mb > 20:
        return {
            "max_keep_pages": 18,
            "max_keep_chars": 140_000,
            "per_page_chars": 5_000,
            "max_pages_scanned": 1_500,
        }
    return {
        "max_keep_pages": DEFAULT_MAX_KEEP_PAGES,
        "max_keep_chars": DEFAULT_MAX_KEEP_CHARS,
        "per_page_chars": DEFAULT_PER_PAGE_CHARS,
        "max_pages_scanned": DEFAULT_MAX_PAGES_SCANNED,
    }
