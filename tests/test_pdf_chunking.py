"""
§16 TEST I — "4MB se badi PDF chunked processing se handle honi chahiye"

Live failure (superconductivity test #3) mein content_fetcher ek line par PDF
chhod deta tha: `if size > 4MB: skip`. Bug report ka jumla — "A 20 MB or 100 MB
scientific document should not automatically become unusable."

Ye test us behaviour ko pakadta hai BINA PyMuPDF ke. Kyun? Kyunki asli page
extraction (fitz) aur page SELECTION (pdf_chunker) ab do alag cheezein hain;
selection pure-Python hai aur kisi bhi iterable of {"page", "text"} par chalti
hai. Isliye ye test CI/sandbox dono mein chalta hai, jahan fitz nahi hota.

Chalane ka tarika:
    python3 tests/test_pdf_chunking.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.processing import pdf_chunker

PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"[PASS] {label}")
    else:
        FAIL += 1
        print(f"[FAIL] {label}" + (f" — {detail}" if detail else ""))


QUESTION = ("Kya room-temperature superconductivity practically possible hai? "
            "Ambient pressure par hydrides aur cuprates ka critical temperature "
            "kitna hai?")

RELEVANT_BODY = (
    "This review discusses room-temperature superconductivity in hydrides. "
    "The critical temperature Tc of LaH10 reaches 250 K under high pressure, "
    "while cuprate superconductors show a transition temperature near 133 K at "
    "ambient pressure. Cooper pairing and the Meissner effect are confirmed by "
    "magnetic susceptibility measurements. " * 4)

IRRELEVANT_BODY = (
    "Maternal mortality ratio estimates by country and region, derived from "
    "civil registration and household survey data. The dataset reports deaths "
    "per 100000 live births with uncertainty intervals. " * 4)


def synthetic_pages(total: int = 520):
    """
    ~520 page ka document: 3 head pages (abstract/intro), thodi der baad kuch
    genuinely relevant pages, ek monster page, kuch image-only (khaali) pages,
    aur baaki bilkul off-topic bharti.
    """
    pages = []
    for number in range(1, total + 1):
        if number <= 3:
            text = "Abstract. " + RELEVANT_BODY
        elif number in (40, 41, 120, 300, 455):
            text = RELEVANT_BODY
        elif number == 200:
            text = RELEVANT_BODY + ("x" * 60_000)      # monster page
        elif number % 50 == 0:
            text = ""                                   # scanned / image-only
        else:
            text = IRRELEVANT_BODY
        pages.append({"page": number, "text": text})
    return pages


def stream(pages):
    """Generator — production ka iter_pages() bhi generator hi hai."""
    for page in pages:
        yield page


# ── [I-1] bada document skip nahi hota ───────────────────────────────────────
print("\n== [I-1] 4MB+ / 500-page document usable rehta hai ==")

check("20 MB file 'large' hai (skip nahi, streaming)",
      pdf_chunker.is_large(size_bytes=20 * 1024 * 1024) is True)
check("100 MB file 'large' hai",
      pdf_chunker.is_large(size_bytes=100 * 1024 * 1024) is True)
check("520-page chhoti file bhi page-count se 'large' hai",
      pdf_chunker.is_large(size_bytes=1024, page_count=520) is True)
check("2 MB / 10-page file normal path par jaati hai",
      pdf_chunker.is_large(size_bytes=2 * 1024 * 1024, page_count=10) is False)

pages = synthetic_pages()
selection = pdf_chunker.select_pages(stream(pages), QUESTION,
                                     file_name="huge_review.pdf",
                                     pages_total=len(pages))

check("selection se text mila (document unusable nahi hua)", selection.ok,
      f"chunks={len(selection.chunks)}")
check("520 pages stream hue", selection.pages_scanned == 520,
      f"pages_scanned={selection.pages_scanned}")
check("pages_total sahi report hua", selection.pages_total == 520)

# ── [I-2] sirf kaam ke pages rakhe gaye ──────────────────────────────────────
print("\n== [I-2] relevance filter: poora document nahi, chune hue pages ==")

kept_pages = [c["page"] for c in selection.chunks]
check("kept pages, total pages se kaafi kam hain",
      0 < len(kept_pages) < 60, f"kept={len(kept_pages)}")
check("head pages (abstract/intro) bache", 1 in kept_pages,
      f"kept={kept_pages[:10]}")
for relevant_page in (40, 120, 300):
    check(f"relevant page p.{relevant_page} chuna gaya",
          relevant_page in kept_pages, f"kept={kept_pages}")
check("off-topic bharti pages drop hue", selection.dropped_for_budget > 0,
      f"dropped={selection.dropped_for_budget}")
check("kept mein bahut saare off-topic pages nahi hain",
      sum(1 for c in selection.chunks
          if "maternal" in c["text"].lower()) <= 5,
      f"offtopic_kept={[c['page'] for c in selection.chunks if 'maternal' in c['text'].lower()]}")

# ── [I-3] memory budget lagta hai (RAM document-size se nahi bandhi) ─────────
print("\n== [I-3] page/chunk based safety limits (byte-based nahi) ==")

tight = pdf_chunker.select_pages(stream(pages), QUESTION,
                                 file_name="huge_review.pdf",
                                 pages_total=len(pages),
                                 max_keep_pages=8, max_keep_chars=20_000,
                                 per_page_chars=1_500)
check("max_keep_pages enforce hua", len(tight.chunks) <= 8,
      f"kept={len(tight.chunks)}")
check("max_keep_chars enforce hua", tight.chars_kept <= 20_000,
      f"chars={tight.chars_kept}")
check("per_page_chars enforce hua (monster page bhi kata)",
      all(len(c["text"]) <= 1_600 for c in tight.chunks),
      f"max_len={max((len(c['text']) for c in tight.chunks), default=0)}")
check("monster page (60k chars) ne budget nahi khaya",
      all(len(c["text"]) <= 6_100 for c in selection.chunks),
      f"max_len={max((len(c['text']) for c in selection.chunks), default=0)}")

stopped = pdf_chunker.select_pages(stream(pages), QUESTION,
                                   file_name="huge_review.pdf",
                                   pages_total=len(pages),
                                   max_pages_scanned=25)
check("max_pages_scanned par ruka", stopped.pages_scanned <= 25,
      f"scanned={stopped.pages_scanned}")
check("ruk-jaane ko imaandaari se report kiya", stopped.stopped_early is True)
check("stopped_early note mein dikhta hai",
      "safety limit" in stopped.note(), stopped.note())

# ── [I-4] image-only pages ginne aur batane hain ─────────────────────────────
print("\n== [I-4] scanned/image-only pages chhupte nahi ==")

check("image-only pages count hue", len(selection.image_only_pages) >= 8,
      f"image_only={selection.image_only_pages[:12]}")
check("image-only page kept chunks mein nahi hai",
      not set(selection.image_only_pages) & set(kept_pages))
check("note mein image-only ka zikr hai",
      "image-only" in selection.note(), selection.note())
check("note mein 'page-by-page' saaf likha hai",
      "page-by-page" in selection.note(), selection.note())
check("note poora-document ka jhootha dava nahi karta",
      "poora document nahi bheja gaya" in selection.note()
      or "sabse milte-julte" in selection.note(), selection.note())

# ── [I-5] citation shape: page order + p.N locator ───────────────────────────
print("\n== [I-5] citation-ready chunks ==")

check("chunks page-number ke kram mein aaye", kept_pages == sorted(kept_pages),
      f"kept={kept_pages}")
check("har chunk ka locator p.N hai",
      all(c["locator"] == f"p.{c['page']}" for c in selection.chunks))
check("har chunk mein source header hai",
      all("huge_review.pdf" in (c.get("header") or "") for c in selection.chunks))
check("selection.text() mein header + text dono hain",
      "[Source: huge_review.pdf, Page" in selection.text()
      and "critical temperature" in selection.text().lower())

as_dict = selection.to_dict()
for key in ("pages_total", "pages_scanned", "pages_kept", "image_only_pages",
            "chars_kept", "stopped_early", "dropped_for_budget",
            "selected_pages", "note"):
    check(f"to_dict mein '{key}' hai", key in as_dict)
check("to_dict ka pages_kept, chunks se match karta hai",
      as_dict["pages_kept"] == len(selection.chunks))

# ── [I-6] document jitna bada, utna sakht budget ─────────────────────────────
print("\n== [I-6] budget_for(): 20MB / 100MB par limits sikudti hain ==")

small = pdf_chunker.budget_for(size_bytes=5 * 1024 * 1024, page_count=80)
mid = pdf_chunker.budget_for(size_bytes=25 * 1024 * 1024, page_count=500)
huge = pdf_chunker.budget_for(size_bytes=100 * 1024 * 1024, page_count=3000)

check("mid (25MB) ka page budget small se kam hai",
      mid["max_keep_pages"] < small["max_keep_pages"],
      f"{mid['max_keep_pages']} vs {small['max_keep_pages']}")
check("huge (100MB/3000p) ka page budget mid se kam hai",
      huge["max_keep_pages"] < mid["max_keep_pages"],
      f"{huge['max_keep_pages']} vs {mid['max_keep_pages']}")
check("huge ka char budget bhi kam hai",
      huge["max_keep_chars"] < mid["max_keep_chars"] < small["max_keep_chars"])
check("huge par bhi kaam band nahi hota (budget > 0)",
      huge["max_keep_pages"] > 0 and huge["max_keep_chars"] > 0
      and huge["max_pages_scanned"] > 0)
check("3000-page document par scan limit badhi hai (2500 pages)",
      huge["max_pages_scanned"] >= 2_500, str(huge))

huge_selection = pdf_chunker.select_pages(
    stream(pages), QUESTION, file_name="thesis_100mb.pdf",
    pages_total=len(pages), **huge)
check("100MB budget par bhi text mila (unusable nahi)", huge_selection.ok,
      f"kept={len(huge_selection.chunks)}")
check("100MB budget par pages 12 se zyada nahi rakhe",
      len(huge_selection.chunks) <= 12, f"kept={len(huge_selection.chunks)}")

# ── [I-7] khaali / kharaab input par crash nahi ──────────────────────────────
print("\n== [I-7] edge cases ==")

empty = pdf_chunker.select_pages([], QUESTION, file_name="x.pdf")
check("khaali input par crash nahi", empty.ok is False)
check("khaali input ka note imaandaar hai",
      "ek bhi page padha nahi" in empty.note(), empty.note())

all_scanned = pdf_chunker.select_pages(
    [{"page": n, "text": ""} for n in range(1, 21)], QUESTION,
    file_name="scan.pdf", pages_total=20)
check("poore scanned document par chunks nahi bante",
      all_scanned.ok is False)
check("poore scanned document ke saare pages image-only gine gaye",
      len(all_scanned.image_only_pages) == 20)

no_question = pdf_chunker.select_pages(stream(pages), "",
                                       file_name="q.pdf",
                                       pages_total=len(pages))
check("khaali sawaal par bhi kuch pages aate hain (head bonus)",
      no_question.ok, f"kept={len(no_question.chunks)}")

missing_numbers = pdf_chunker.select_pages(
    [{"text": RELEVANT_BODY} for _ in range(5)], QUESTION, file_name="n.pdf")
check("page number missing ho to sequence se bhar jaata hai",
      [c["page"] for c in missing_numbers.chunks] == [1, 2, 3, 4, 5],
      str([c["page"] for c in missing_numbers.chunks]))

# ── [I-8] page_score deterministic aur sawaal-sapeksh ────────────────────────
print("\n== [I-8] page_score ==")

relevant_score = pdf_chunker.page_score(RELEVANT_BODY, QUESTION)
irrelevant_score = pdf_chunker.page_score(IRRELEVANT_BODY, QUESTION)
check("relevant page ka score off-topic page se zyada hai",
      relevant_score > irrelevant_score,
      f"{relevant_score} vs {irrelevant_score}")
check("khaali text ka score 0 hai",
      pdf_chunker.page_score("", QUESTION) == 0.0)
check("score deterministic hai",
      pdf_chunker.page_score(RELEVANT_BODY, QUESTION) == relevant_score)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
