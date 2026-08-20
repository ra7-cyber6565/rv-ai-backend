"""
PDFProcessor — Spec Section 4 (PDF Pipeline)

Kaam:
    * page-wise text extraction (PyMuPDF / fitz)
    * SCANNED page detection — jis page pe text almost zero hai wo scan hai;
      uske liye OCR chahiye (OCRProcessor dekho)
    * metadata (title, author, page count)

Honesty (Spec Section 3/13): agar PDF encrypted hai ya scanned hai aur OCR
available nahi hai, to ye module saaf "extracted: false" bolta hai — chup-chaap
khaali text return karke aage nahi badhta.
"""
from __future__ import annotations

import os
from typing import Dict, Iterator, List

from . import pdf_chunker

# Itne se kam chars wale page ko scanned/image-only maana jaata hai
_MIN_CHARS_PER_PAGE = 40


class PDFProcessor:
    name = "pdf"

    def _fitz(self):
        import fitz  # lazy — PyMuPDF
        return fitz

    def available(self) -> bool:
        try:
            self._fitz()
            return True
        except Exception:
            return False

    # ── main ─────────────────────────────────────────────────────────────────
    def extract(self, file_path: str, max_pages: int = 0) -> Dict:
        """
        Returns:
            {
              "extracted": bool, "error": str, "page_count": int,
              "pages": [{"page": 1, "text": "...", "chars": n, "scanned": bool}],
              "scanned_pages": [int], "metadata": {...}, "text": "full text"
            }
        """
        result: Dict = {"extracted": False, "error": "", "page_count": 0, "pages": [],
                        "scanned_pages": [], "metadata": {}, "text": ""}

        if not os.path.exists(file_path):
            result["error"] = f"file nahi mili: {file_path}"
            return result
        if not self.available():
            result["error"] = "PyMuPDF (fitz) install nahi hai — pip install pymupdf"
            return result

        fitz = self._fitz()
        try:
            doc = fitz.open(file_path)
        except Exception as exc:
            result["error"] = f"PDF khul nahi rahi: {type(exc).__name__}: {exc}"
            return result

        try:
            if getattr(doc, "needs_pass", False):
                result["error"] = ("PDF password-protected hai. Encryption bypass nahi "
                                   "kiya jaata — password ke saath dobara bhejein.")
                return result

            result["metadata"] = {
                "title": (doc.metadata or {}).get("title", ""),
                "author": (doc.metadata or {}).get("author", ""),
                "file": os.path.basename(file_path),
            }
            result["page_count"] = doc.page_count

            limit = doc.page_count if max_pages <= 0 else min(max_pages, doc.page_count)
            chunks: List[str] = []
            for index in range(limit):
                try:
                    text = doc[index].get_text() or ""
                except Exception as exc:
                    text = ""
                    result["error"] = f"page {index + 1} read fail: {type(exc).__name__}"
                stripped = text.strip()
                is_scanned = len(stripped) < _MIN_CHARS_PER_PAGE
                result["pages"].append({
                    "page": index + 1, "text": stripped,
                    "chars": len(stripped), "scanned": is_scanned,
                })
                if is_scanned:
                    result["scanned_pages"].append(index + 1)
                elif stripped:
                    chunks.append(f"[Source: {result['metadata']['file']}, "
                                  f"Page {index + 1}]\n{stripped}")

            result["text"] = "\n\n".join(chunks)
            result["extracted"] = bool(result["text"]) or bool(result["pages"])
            return result
        finally:
            try:
                doc.close()
            except Exception:
                pass

    # ── §12: streaming (badi PDF ke liye) ────────────────────────────────────
    def page_count(self, file_path: str) -> int:
        """Sirf page count — poora text nikaale bina (streaming ka faisla isi par)."""
        if not os.path.exists(file_path) or not self.available():
            return 0
        try:
            doc = self._fitz().open(file_path)
        except Exception:
            return 0
        try:
            return int(getattr(doc, "page_count", 0) or 0)
        finally:
            try:
                doc.close()
            except Exception:
                pass

    def iter_pages(self, file_path: str, max_pages: int = 0,
                   start_page: int = 0) -> Iterator[Dict]:
        """
        Ek waqt mein EK page — yahi §12 ka dil hai.

        `extract()` poore document ka text ek list mein jama karta hai; 100 MB ki
        thesis par wahi memory problem hai jiski wajah se pehle file skip hoti
        thi. Ye generator har page dene ke baad usko chhod deta hai, isliye RAM
        document ke size se nahi, ek page ke size se bandhi hai.
        """
        if not os.path.exists(file_path) or not self.available():
            return
        try:
            doc = self._fitz().open(file_path)
        except Exception:
            return
        try:
            if getattr(doc, "needs_pass", False):
                return          # encryption bypass nahi karte
            total = int(getattr(doc, "page_count", 0) or 0)
            last = total if max_pages <= 0 else min(start_page + max_pages, total)
            for index in range(max(0, start_page), last):
                try:
                    text = doc[index].get_text() or ""
                except Exception:
                    text = ""
                yield {"page": index + 1, "text": text.strip(),
                       "chars": len(text.strip()), "page_count": total,
                       "scanned": len(text.strip()) < _MIN_CHARS_PER_PAGE}
        finally:
            try:
                doc.close()
            except Exception:
                pass

    def extract_relevant(self, file_path: str, question: str,
                         size_bytes: int = 0, **budget) -> Dict:
        """
        Badi PDF ka page-by-page reading: stream → relevance filter → chune
        hue pages. Shape `extract()` jaisi hi hai, plus "selection".
        """
        result: Dict = {"extracted": False, "error": "", "page_count": 0,
                        "pages": [], "scanned_pages": [], "metadata": {},
                        "text": "", "chunks": [], "selection": {},
                        "streamed": True}
        if not os.path.exists(file_path):
            result["error"] = f"file nahi mili: {file_path}"
            return result
        if not self.available():
            result["error"] = "PyMuPDF (fitz) install nahi hai — pip install pymupdf"
            return result

        total = self.page_count(file_path)
        result["page_count"] = total
        result["metadata"] = {"title": "", "author": "",
                              "file": os.path.basename(file_path)}
        try:
            doc = self._fitz().open(file_path)
            try:
                if getattr(doc, "needs_pass", False):
                    result["error"] = ("PDF password-protected hai. Encryption "
                                       "bypass nahi kiya jaata — password ke "
                                       "saath dobara bhejein.")
                    return result
                meta = doc.metadata or {}
                result["metadata"].update({"title": meta.get("title", ""),
                                           "author": meta.get("author", "")})
            finally:
                doc.close()
        except Exception as exc:
            result["error"] = f"PDF khul nahi rahi: {type(exc).__name__}: {exc}"
            return result

        limits = dict(pdf_chunker.budget_for(size_bytes=size_bytes, page_count=total))
        limits.update({k: v for k, v in (budget or {}).items() if v})
        selection = pdf_chunker.select_pages(
            self.iter_pages(file_path, max_pages=limits.get("max_pages_scanned", 0)),
            question,
            file_name=result["metadata"]["file"],
            pages_total=total,
            head_pages=limits.get("head_pages", pdf_chunker.DEFAULT_HEAD_PAGES),
            max_pages_scanned=limits.get("max_pages_scanned",
                                         pdf_chunker.DEFAULT_MAX_PAGES_SCANNED),
            max_keep_pages=limits.get("max_keep_pages",
                                      pdf_chunker.DEFAULT_MAX_KEEP_PAGES),
            max_keep_chars=limits.get("max_keep_chars",
                                      pdf_chunker.DEFAULT_MAX_KEEP_CHARS),
            per_page_chars=limits.get("per_page_chars",
                                      pdf_chunker.DEFAULT_PER_PAGE_CHARS),
        )
        result["selection"] = selection.to_dict()
        result["scanned_pages"] = list(selection.image_only_pages)
        result["chunks"] = list(selection.chunks)
        result["pages"] = [{"page": c["page"], "text": c["text"],
                            "chars": len(c["text"]), "scanned": False}
                           for c in selection.chunks]
        result["text"] = selection.text()
        result["extracted"] = bool(result["text"])
        if not result["extracted"]:
            result["error"] = ("badi PDF ke kisi bhi page se padhne layak text "
                               "nahi mila (poora document scanned ho sakta hai)")
        return result

    # ── honest report ────────────────────────────────────────────────────────
    def coverage_note(self, result: Dict) -> str:
        if not result.get("extracted"):
            return f"PDF se text nahi nikla: {result.get('error') or 'unknown reason'}"
        if result.get("streamed"):
            # §12 ka honest hisaab: yahan "N/M pages se text mila" likhna jhooth
            # hota, kyunki humne jaan-boojh kar sirf kaam ke pages padhe hain.
            return (result.get("selection") or {}).get(
                "note", "badi PDF page-by-page padhi gayi")
        total = result.get("page_count", 0)
        read = len([p for p in result.get("pages", []) if not p.get("scanned")])
        scanned = len(result.get("scanned_pages", []))
        note = f"{read}/{total} pages se text mila"
        if scanned:
            note += (f"; {scanned} page image-only (scanned) hain — inka content "
                     f"tab tak use nahi hoga jab tak OCR na chale")
        return note
