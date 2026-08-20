"""
§12 — badi PDF ko "unusable" nahi hone dena.

PEHLE KYA GALAT THA (live failure, superconductivity test #3):
    content_fetcher ek hi line par PDF chhod deta tha —

        if size > _MAX_BYTES:      # 4 MB
            return {"error": "file 4MB se badi hai — skip (memory safety)"}

    Yaani 20 MB ka review, 100 MB ki thesis, ya scanned book ka koi bhi page
    kabhi padha hi nahi jaata tha. Bug report ka jumla: "A 20 MB or 100 MB
    scientific document should not automatically become unusable."

AB KYA HOTA HAI:
    Byte-size par faisla nahi hota. Document PAGE-BY-PAGE stream hota hai:

        PDF → (ek waqt mein ek page) → halka relevance filter →
        sirf sabse kaam ke pages rakho → unhi ko process karo

    Memory safety khatam nahi hui, sirf uska naap badal gaya: ab limit
    "kitne bytes download hue" nahi, "kitne pages ek saath yaad rakhe" hai
    (`max_keep_pages`, `max_keep_chars`, `per_page_chars`). Isliye 100 MB ki
    file bhi utni hi RAM leti hai jitni 2 MB ki.

Ye module JAAN-BOOJH KAR pure-Python hai — koi PyMuPDF, koi network. Pages ek
iterable ke roop mein aate hain (production mein PDFProcessor.iter_pages ka
generator, test mein seedha list). Isi wajah se §16 ka TEST I bina PDF library
ke bhi chalta hai.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Dict, Iterable, List

# ── budget (page/chunk based, byte based NAHI) ────────────────────────────────
DEFAULT_HEAD_PAGES = 3          # shuruaati pages (abstract/intro) ko bonus
DEFAULT_MAX_PAGES_SCANNED = 800  # itne pages tak stream karenge (safety)
DEFAULT_MAX_KEEP_PAGES = 30      # ek waqt mein itne hi pages memory mein
DEFAULT_MAX_KEEP_CHARS = 200_000  # kul itna text aage bhejenge
DEFAULT_PER_PAGE_CHARS = 6_000   # ek page se itna hi (monster page se bachav)

# Itne se kam text wala page = image-only / khaali (scan). Ye PDFProcessor ke
# _MIN_CHARS_PER_PAGE se milta hai — dono jagah ek hi soch honi chahiye.
SCANNED_PAGE_CHARS = 40
# Head page ko itna bonus, taaki abstract/intro relevance kam hone par bhi bache.
_HEAD_BONUS = 1.0


def page_score(text: str, question: str) -> float:
    """
    Ek page kitna kaam ka hai — 0..1. Halka aur deterministic.

    semantic.similarity wahi weighted+bigram scoring hai jo §2/§5 ke relevance
    engine mein chalti hai, isliye "kaam ka page" ki definition poore system
    mein ek jaisi rehti hai. Agar wo import kisi wajah se na mile to plain word
    overlap par gir jaate hain — filter kabhi band nahi hota.
    """
    body = str(text or "").strip()
    if not body:
        return 0.0
    try:
        from .. import semantic
        return float(semantic.similarity(question or "", body))
    except Exception:      # pragma: no cover - defensive
        import re
        q = {w for w in re.findall(r"[a-z]{4,}", (question or "").lower())}
        if not q:
            return 0.0
        t = {w for w in re.findall(r"[a-z]{4,}", body.lower())}
        return round(len(q & t) / len(q), 4)


@dataclass
class PageSelection:
    """Kitna padha, kitna chhoda, aur kyun — sab likha hua."""
    chunks: List[Dict] = field(default_factory=list)
    pages_total: int = 0
    pages_scanned: int = 0
    pages_kept: int = 0
    image_only_pages: List[int] = field(default_factory=list)
    chars_kept: int = 0
    stopped_early: bool = False
    dropped_for_budget: int = 0
    file_name: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.chunks)

    def text(self) -> str:
        return "\n\n".join(
            f"{c.get('header') or ''}\n{c.get('text') or ''}".strip()
            for c in self.chunks)

    def note(self) -> str:
        if not self.pages_scanned:
            return "PDF se ek bhi page padha nahi ja saka."
        total = self.pages_total or self.pages_scanned
        pages = ", ".join(str(c.get("page")) for c in self.chunks[:8]
                          if c.get("page"))
        bits = [f"badi PDF page-by-page padhi gayi: {self.pages_scanned}/{total} "
                f"pages scan hue, sawaal se sabse milte-julte {self.pages_kept} "
                f"pages rakhe gaye"]
        if pages:
            bits.append(f"chune gaye pages: p.{pages}")
        if self.image_only_pages:
            bits.append(f"{len(self.image_only_pages)} pages image-only (scanned) "
                        f"the — unka content OCR ke bina use nahi hua")
        if self.dropped_for_budget:
            bits.append(f"{self.dropped_for_budget} kam-relevant pages budget ke "
                        f"bahar rahe (poora document nahi bheja gaya)")
        if self.stopped_early:
            bits.append(f"safety limit par ruke — {total} mein se pehle "
                        f"{self.pages_scanned} pages hi dekhe")
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
) -> PageSelection:
    """
    Pages ka stream lo, sirf kaam ke pages rakho.

    `pages` kuch bhi ho sakta hai jo `{"page": int, "text": str}` deta ho —
    generator (production) ya list (test). Poora document kabhi ek saath memory
    mein nahi aata: hum bas `max_keep_pages` ka ek chhota heap rakhte hain.

    Kram ka faisla soch kar liya gaya hai: chunna RELEVANCE se hota hai, par
    aakhir mein pages PAGE NUMBER ke kram mein aate hain — kyunki citation
    "p.12" ke baad "p.4" padhna insaan ke liye bekaar hai.
    """
    sel = PageSelection(pages_total=int(pages_total or 0), file_name=file_name or "")
    heap: List = []          # (score, page_no, text) — sabse kamzor upar
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
            # khaali ya image-only — ye page "padha" nahi gina jaata
            sel.image_only_pages.append(page_no)
            continue

        if len(text) > per_page_chars:
            text = text[:per_page_chars].rsplit(" ", 1)[0] + " …"

        score = page_score(text, question)
        if seq <= max(0, head_pages):
            score += _HEAD_BONUS      # abstract/intro mein thesis hoti hai
        elif score <= min_score:
            sel.dropped_for_budget += 1
            continue

        heapq.heappush(heap, (round(score, 4), page_no, text))
        if len(heap) > max(1, max_keep_pages):
            heapq.heappop(heap)      # sabse kam relevant page bahar
            sel.dropped_for_budget += 1

    if not sel.pages_total:
        sel.pages_total = sel.pages_scanned

    # char budget: pehle sabse relevant pages, phir padhne ka kram
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
    sel.chunks = [{"locator": f"p.{page_no}", "page": page_no, "text": text,
                   "score": score,
                   "header": f"[Source: {name}, Page {page_no}]"}
                  for score, page_no, text in kept]
    sel.pages_kept = len(sel.chunks)
    sel.chars_kept = used
    return sel


def is_large(size_bytes: int = 0, page_count: int = 0,
             large_bytes: int = 4 * 1024 * 1024,
             large_pages: int = 60) -> bool:
    """
    "Badi PDF" ka faisla — size YA page count, jo pehle chhoo jaye.

    Note: ye "skip karo" ka faisla NAHI hai (wo bug tha). Ye sirf "streaming
    page-by-page path lo" ka faisla hai.
    """
    return bool((size_bytes and size_bytes > large_bytes)
                or (page_count and page_count > large_pages))


def budget_for(size_bytes: int = 0, page_count: int = 0) -> Dict:
    """
    Document jitna bada, utna sakht page budget — RAM constant rehti hai.

    Free tier par yahi farak hai "100 MB thesis padhi ja sakti hai" aur
    "process OOM se mar gaya" ke beech.
    """
    mb = float(size_bytes or 0) / (1024 * 1024)
    if page_count > 2000 or mb > 60:
        return {"max_keep_pages": 12, "max_keep_chars": 90_000,
                "per_page_chars": 4_000, "max_pages_scanned": 2_500}
    if page_count > 400 or mb > 20:
        return {"max_keep_pages": 18, "max_keep_chars": 140_000,
                "per_page_chars": 5_000, "max_pages_scanned": 1_500}
    return {"max_keep_pages": DEFAULT_MAX_KEEP_PAGES,
            "max_keep_chars": DEFAULT_MAX_KEEP_CHARS,
            "per_page_chars": DEFAULT_PER_PAGE_CHARS,
            "max_pages_scanned": DEFAULT_MAX_PAGES_SCANNED}
