"""
PDFProcessor — Spec Section 4 (PDF Pipeline)

Kaam:
    * page-wise text extraction (PyMuPDF / fitz)
    * scanned/image-only page detection
    * metadata (title, author, page count)
    * huge-PDF sparse sampling across the whole document

Honesty rule: encrypted/scanned/unreadable content is reported, never silently
promoted to evidence.  Huge PDFs use bounded page sampling instead of reading
only the first N pages, so late methods/results chapters are not systematically
ignored.
"""
from __future__ import annotations

import os
from typing import Dict, Iterable, Iterator, List

from . import pdf_chunker

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

    def extract(self, file_path: str, max_pages: int = 0) -> Dict:
        result: Dict = {
            "extracted": False,
            "error": "",
            "page_count": 0,
            "pages": [],
            "scanned_pages": [],
            "metadata": {},
            "text": "",
        }
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
                result["error"] = (
                    "PDF password-protected hai. Encryption bypass nahi kiya jaata — "
                    "password ke saath dobara bhejein."
                )
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
                    "page": index + 1,
                    "text": stripped,
                    "chars": len(stripped),
                    "scanned": is_scanned,
                })
                if is_scanned:
                    result["scanned_pages"].append(index + 1)
                elif stripped:
                    chunks.append(
                        f"[Source: {result['metadata']['file']}, Page {index + 1}]\n{stripped}"
                    )

            result["text"] = "\n\n".join(chunks)
            result["extracted"] = bool(result["text"]) or bool(result["pages"])
            return result
        finally:
            try:
                doc.close()
            except Exception:
                pass

    def page_count(self, file_path: str) -> int:
        """Sirf page count — poora text nikaale bina."""
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

    @staticmethod
    def _page_row(doc, index: int, total: int) -> Dict:
        try:
            text = doc[index].get_text() or ""
        except Exception:
            text = ""
        stripped = text.strip()
        return {
            "page": index + 1,
            "text": stripped,
            "chars": len(stripped),
            "page_count": total,
            "scanned": len(stripped) < _MIN_CHARS_PER_PAGE,
        }

    def iter_pages(
        self,
        file_path: str,
        max_pages: int = 0,
        start_page: int = 0,
    ) -> Iterator[Dict]:
        """Sequential one-page-at-a-time reader."""
        if not os.path.exists(file_path) or not self.available():
            return
        try:
            doc = self._fitz().open(file_path)
        except Exception:
            return
        try:
            if getattr(doc, "needs_pass", False):
                return
            total = int(getattr(doc, "page_count", 0) or 0)
            last = total if max_pages <= 0 else min(start_page + max_pages, total)
            for index in range(max(0, start_page), last):
                yield self._page_row(doc, index, total)
        finally:
            try:
                doc.close()
            except Exception:
                pass

    def iter_page_indices(self, file_path: str, indices: Iterable[int]) -> Iterator[Dict]:
        """Read only selected 0-based pages while opening the PDF once.

        The index list is small (bounded by the scan budget), so memory remains
        independent of the full PDF size.  Invalid/duplicate indices are ignored.
        """
        if not os.path.exists(file_path) or not self.available():
            return
        try:
            doc = self._fitz().open(file_path)
        except Exception:
            return
        try:
            if getattr(doc, "needs_pass", False):
                return
            total = int(getattr(doc, "page_count", 0) or 0)
            seen = set()
            for raw in indices or []:
                try:
                    index = int(raw)
                except (TypeError, ValueError):
                    continue
                if index in seen or index < 0 or index >= total:
                    continue
                seen.add(index)
                yield self._page_row(doc, index, total)
        finally:
            try:
                doc.close()
            except Exception:
                pass

    def extract_relevant(
        self,
        file_path: str,
        question: str,
        size_bytes: int = 0,
        **budget,
    ) -> Dict:
        """Huge PDF: bounded read → relevance filter → citation-ready pages."""
        result: Dict = {
            "extracted": False,
            "error": "",
            "page_count": 0,
            "pages": [],
            "scanned_pages": [],
            "metadata": {},
            "text": "",
            "chunks": [],
            "selection": {},
            "streamed": True,
        }
        if not os.path.exists(file_path):
            result["error"] = f"file nahi mili: {file_path}"
            return result
        if not self.available():
            result["error"] = "PyMuPDF (fitz) install nahi hai — pip install pymupdf"
            return result

        total = self.page_count(file_path)
        result["page_count"] = total
        result["metadata"] = {
            "title": "",
            "author": "",
            "file": os.path.basename(file_path),
        }
        try:
            doc = self._fitz().open(file_path)
            try:
                if getattr(doc, "needs_pass", False):
                    result["error"] = (
                        "PDF password-protected hai. Encryption bypass nahi kiya jaata — "
                        "password ke saath dobara bhejein."
                    )
                    return result
                meta = doc.metadata or {}
                result["metadata"].update({
                    "title": meta.get("title", ""),
                    "author": meta.get("author", ""),
                })
            finally:
                doc.close()
        except Exception as exc:
            result["error"] = f"PDF khul nahi rahi: {type(exc).__name__}: {exc}"
            return result

        limits = dict(pdf_chunker.budget_for(size_bytes=size_bytes, page_count=total))
        limits.update({k: v for k, v in (budget or {}).items() if v})
        scan_limit = max(1, int(limits.get("max_pages_scanned") or pdf_chunker.DEFAULT_MAX_PAGES_SCANNED))
        head_pages = max(0, int(limits.get("head_pages") or pdf_chunker.DEFAULT_HEAD_PAGES))

        if total > scan_limit:
            indices = pdf_chunker.sample_page_indices(
                total,
                scan_limit,
                head_pages=head_pages,
                tail_pages=max(pdf_chunker.DEFAULT_TAIL_PAGES, head_pages),
            )
            page_stream = self.iter_page_indices(file_path, indices)
            sampling_mode = "whole_document_sparse"
            max_to_scan = len(indices)
        else:
            page_stream = self.iter_pages(file_path)
            sampling_mode = "sequential"
            max_to_scan = max(total, 1)

        selection = pdf_chunker.select_pages(
            page_stream,
            question,
            file_name=result["metadata"]["file"],
            pages_total=total,
            head_pages=head_pages,
            max_pages_scanned=max_to_scan,
            max_keep_pages=limits.get(
                "max_keep_pages", pdf_chunker.DEFAULT_MAX_KEEP_PAGES
            ),
            max_keep_chars=limits.get(
                "max_keep_chars", pdf_chunker.DEFAULT_MAX_KEEP_CHARS
            ),
            per_page_chars=limits.get(
                "per_page_chars", pdf_chunker.DEFAULT_PER_PAGE_CHARS
            ),
            sampling_mode=sampling_mode,
        )
        result["selection"] = selection.to_dict()
        result["scanned_pages"] = list(selection.image_only_pages)
        result["chunks"] = list(selection.chunks)
        result["pages"] = [
            {
                "page": c["page"],
                "text": c["text"],
                "chars": len(c["text"]),
                "scanned": False,
            }
            for c in selection.chunks
        ]
        result["text"] = selection.text()
        result["extracted"] = bool(result["text"])
        if not result["extracted"]:
            result["error"] = (
                "badi PDF ke inspected sample se padhne layak relevant text nahi mila "
                "(document scanned ho sakta hai ya evidence sampled pages mein nahi tha)"
            )
        return result

    def coverage_note(self, result: Dict) -> str:
        if not result.get("extracted"):
            return f"PDF se text nahi nikla: {result.get('error') or 'unknown reason'}"
        if result.get("streamed"):
            return (result.get("selection") or {}).get(
                "note", "badi PDF bounded page-by-page mode mein padhi gayi"
            )
        total = result.get("page_count", 0)
        read = len([p for p in result.get("pages", []) if not p.get("scanned")])
        scanned = len(result.get("scanned_pages", []))
        note = f"{read}/{total} pages se text mila"
        if scanned:
            note += (
                f"; {scanned} page image-only (scanned) hain — inka content tab tak "
                f"use nahi hoga jab tak OCR na chale"
            )
        return note
