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
from typing import Dict, List

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

    # ── honest report ────────────────────────────────────────────────────────
    def coverage_note(self, result: Dict) -> str:
        if not result.get("extracted"):
            return f"PDF se text nahi nikla: {result.get('error') or 'unknown reason'}"
        total = result.get("page_count", 0)
        read = len([p for p in result.get("pages", []) if not p.get("scanned")])
        scanned = len(result.get("scanned_pages", []))
        note = f"{read}/{total} pages se text mila"
        if scanned:
            note += (f"; {scanned} page image-only (scanned) hain — inka content "
                     f"tab tak use nahi hoga jab tak OCR na chale")
        return note
