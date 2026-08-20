"""
DocumentProcessor — Spec Section 3/4/5 ka entry point (processing/)

File aayi → sahi processor chuno → text + citation-ready chunks do.

Supported:
    .pdf                  PDFProcessor (+ OCRProcessor scanned pages ke liye)
    .vtt .srt             TranscriptProcessor (timestamp citations)
    .txt .md              plain text
    .docx                 python-docx (agar installed ho)
    .html .htm            tag-strip (bhaari parser ke bina)

Har case mein return shape same rehta hai, taaki caller ko if-else na likhna pade.
Fail hone par bhi shape same — "ok": False + reason.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

from .ocr_processor import OCRProcessor
from .pdf_processor import PDFProcessor
from .transcript_processor import TranscriptProcessor
from . import pdf_chunker

TEXT_EXTENSIONS = (".txt", ".md", ".markdown", ".text")
TRANSCRIPT_EXTENSIONS = (".vtt", ".srt")
_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_ANY_TAG_RE = re.compile(r"<[^>]+>")


class DocumentProcessor:
    name = "document"

    def __init__(self, ocr_lang: str = "eng", ocr_max_pages: int = 20):
        self.pdf = PDFProcessor()
        self.ocr = OCRProcessor(lang=ocr_lang)
        self.transcript = TranscriptProcessor()
        self.ocr_max_pages = ocr_max_pages

    # ── dispatch ─────────────────────────────────────────────────────────────
    def process(self, file_path: str, use_ocr: bool = True,
                question: str = "", size_bytes: int = 0,
                large: bool = False) -> Dict:
        """
        File → text + citation-ready chunks.

        §12 ke naye (optional) arguments:
          question   — badi PDF mein kaun se pages rakhne hain, ye isse tay hota
                       hai. Khaali chhod do to purana behaviour (poora document).
          size_bytes — file ka size (caller ke paas pehle se hota hai)
          large      — caller zabardasti streaming path chun sakta hai
        Purane callers ne ye kuch nahi bheja tha, aur unke liye kuch nahi badla.
        """
        base = {"ok": False, "error": "", "text": "", "chunks": [], "notes": [],
                "kind": "", "file": os.path.basename(file_path or "")}

        if not file_path or not os.path.exists(file_path):
            base["error"] = f"file nahi mili: {file_path}"
            return base

        extension = os.path.splitext(file_path)[1].lower()

        if extension == ".pdf":
            return self._process_pdf(file_path, use_ocr, base, question=question,
                                     size_bytes=size_bytes, large=large)
        if extension in TRANSCRIPT_EXTENSIONS:
            return self._process_transcript(file_path, base)
        if extension in TEXT_EXTENSIONS:
            return self._process_text(file_path, base)
        if extension == ".docx":
            return self._process_docx(file_path, base)
        if extension in (".html", ".htm"):
            return self._process_html(file_path, base)

        base["error"] = (f"'{extension}' format supported nahi hai. Supported: "
                         f"pdf, vtt, srt, txt, md, docx, html")
        return base

    # ── pdf ──────────────────────────────────────────────────────────────────
    def _process_pdf(self, file_path: str, use_ocr: bool, base: Dict,
                     question: str = "", size_bytes: int = 0,
                     large: bool = False) -> Dict:
        base["kind"] = "pdf"

        # §12: byte-size par file skip karna band. Badi file ka matlab ab
        # "streaming page-by-page padho" hai, "chhod do" nahi.
        if not size_bytes:
            try:
                size_bytes = os.path.getsize(file_path)
            except Exception:
                size_bytes = 0
        pages_hint = self.pdf.page_count(file_path)
        if large or pdf_chunker.is_large(size_bytes=size_bytes,
                                        page_count=pages_hint):
            return self._process_pdf_streaming(file_path, use_ocr, base,
                                               question=question,
                                               size_bytes=size_bytes)

        result = self.pdf.extract(file_path)
        base["notes"].append(self.pdf.coverage_note(result))

        if not result["extracted"]:
            base["error"] = result["error"] or "PDF se text nahi nikla"
            return base

        text_parts = [result["text"]] if result["text"] else []
        chunks = [
            {"locator": f"p.{page['page']}", "text": page["text"],
             "header": f"[Source: {base['file']}, Page {page['page']}]"}
            for page in result["pages"] if page["text"] and not page["scanned"]
        ]

        scanned = result.get("scanned_pages", [])
        if scanned and use_ocr:
            ocr_result = self.ocr.ocr_pdf_pages(file_path, scanned,
                                                max_pages=self.ocr_max_pages)
            base["notes"].append(self.ocr.note(ocr_result))
            if ocr_result.get("text"):
                text_parts.append(ocr_result["text"])
                chunks += [
                    {"locator": f"p.{page['page']} (OCR)", "text": page["text"],
                     "header": f"[Source: {base['file']}, Page {page['page']}]"}
                    for page in ocr_result["pages"] if page.get("text")
                ]
        elif scanned:
            base["notes"].append(f"{len(scanned)} scanned pages skip hue (OCR off tha)")

        base["text"] = "\n\n".join(part for part in text_parts if part)
        base["chunks"] = chunks
        base["ok"] = bool(base["text"])
        if not base["ok"]:
            base["error"] = ("PDF mein padhne layak text nahi mila (poora document "
                             "scanned ho sakta hai aur OCR available nahi tha)")
        return base

    # ── pdf, badi file ka streaming path (§12) ───────────────────────────────
    def _process_pdf_streaming(self, file_path: str, use_ocr: bool, base: Dict,
                               question: str = "", size_bytes: int = 0) -> Dict:
        """
        20 MB / 100 MB / 3000-page document — ab bhi usable.

        Poora text ek string mein nahi banate. Pages stream hote hain, sawaal se
        milte-julte pages chune jaate hain, aur report mein saaf likha jaata hai
        ki kitne pages dekhe aur kaun rakhe gaye. Ye "poora document padh liya"
        ka daawa nahi karta — spec ki honesty isi mein hai.
        """
        base["kind"] = "pdf"
        base["streamed"] = True
        result = self.pdf.extract_relevant(file_path, question,
                                           size_bytes=size_bytes)
        base["notes"].append(self.pdf.coverage_note(result))
        base["selection"] = result.get("selection", {})
        base["page_count"] = result.get("page_count", 0)

        chunks = [{"locator": c["locator"], "text": c["text"],
                   "header": c.get("header", "")}
                  for c in (result.get("chunks") or []) if c.get("text")]
        text_parts = [result.get("text") or ""]

        # Scanned pages: badi file par poora OCR budget se bahar hai. Isliye OCR
        # sirf tab, jab text ki taraf se kuch bhi na mila ho — aur tab bhi sirf
        # pehle kuch pages. Feature band nahi kiya, seemit kiya hai.
        scanned = result.get("scanned_pages") or []
        if scanned and use_ocr and not chunks:
            budget = min(self.ocr_max_pages, 5)
            ocr_result = self.ocr.ocr_pdf_pages(file_path, scanned[:budget],
                                                max_pages=budget)
            base["notes"].append(self.ocr.note(ocr_result))
            if ocr_result.get("text"):
                text_parts.append(ocr_result["text"])
                chunks += [
                    {"locator": f"p.{page['page']} (OCR)", "text": page["text"],
                     "header": f"[Source: {base['file']}, Page {page['page']}]"}
                    for page in ocr_result["pages"] if page.get("text")
                ]
        elif scanned and not use_ocr:
            base["notes"].append(f"{len(scanned)} scanned pages skip hue (OCR off tha)")

        base["text"] = "\n\n".join(part for part in text_parts if part)
        base["chunks"] = chunks
        base["ok"] = bool(base["text"])
        if not base["ok"]:
            base["error"] = result.get("error") or (
                "badi PDF ke chune hue pages se bhi padhne layak text nahi mila")
        return base

    # ── transcript ───────────────────────────────────────────────────────────
    def _process_transcript(self, file_path: str, base: Dict) -> Dict:
        base["kind"] = "transcript"
        result = self.transcript.process_file(file_path)
        base["ok"] = result["ok"]
        base["error"] = result.get("error", "")
        base["text"] = result.get("text", "")
        base["chunks"] = result.get("chunks", [])
        if result.get("duration_note"):
            base["notes"].append(result["duration_note"])
        return base

    # ── plain text ───────────────────────────────────────────────────────────
    def _read(self, file_path: str) -> str:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def _chunk_plain(self, text: str, file_name: str,
                     chunk_chars: int = 1200) -> List[Dict]:
        """Paragraph-boundary pe todo, taaki sentence beech se na kate."""
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        chunks: List[Dict] = []
        buffer: List[str] = []
        size = 0
        index = 1

        def flush(idx: int):
            if not buffer:
                return
            chunks.append({
                "locator": f"part {idx}",
                "text": "\n\n".join(buffer),
                "header": f"[Source: {file_name}, Part {idx}]",
            })

        for paragraph in paragraphs:
            if size + len(paragraph) > chunk_chars and buffer:
                flush(index)
                index += 1
                buffer, size = [], 0
            buffer.append(paragraph)
            size += len(paragraph)
        flush(index)
        return chunks

    def _process_text(self, file_path: str, base: Dict) -> Dict:
        base["kind"] = "text"
        try:
            text = self._read(file_path).strip()
        except Exception as exc:
            base["error"] = f"file padhi nahi gayi: {type(exc).__name__}: {exc}"
            return base
        base["text"] = text
        base["chunks"] = self._chunk_plain(text, base["file"])
        base["ok"] = bool(text)
        base["notes"].append(f"{len(text)} chars, {len(base['chunks'])} chunks")
        if not text:
            base["error"] = "file khaali hai"
        return base

    # ── docx ─────────────────────────────────────────────────────────────────
    def _process_docx(self, file_path: str, base: Dict) -> Dict:
        base["kind"] = "docx"
        try:
            import docx  # python-docx, optional
        except Exception as exc:
            base["error"] = f"python-docx nahi hai ({exc}) — pip install python-docx"
            return base
        try:
            document = docx.Document(file_path)
        except Exception as exc:
            base["error"] = f"docx khul nahi rahi: {type(exc).__name__}: {exc}"
            return base
        text = "\n\n".join(p.text.strip() for p in document.paragraphs if p.text.strip())
        base["text"] = text
        base["chunks"] = self._chunk_plain(text, base["file"])
        base["ok"] = bool(text)
        base["notes"].append(f"{len(document.paragraphs)} paragraphs")
        if not text:
            base["error"] = "docx mein text nahi mila"
        return base

    # ── html ─────────────────────────────────────────────────────────────────
    def _process_html(self, file_path: str, base: Dict) -> Dict:
        base["kind"] = "html"
        try:
            raw = self._read(file_path)
        except Exception as exc:
            base["error"] = f"file padhi nahi gayi: {type(exc).__name__}: {exc}"
            return base
        without_scripts = _TAG_RE.sub(" ", raw)
        text = _ANY_TAG_RE.sub(" ", without_scripts)
        text = re.sub(r"&nbsp;?", " ", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        base["text"] = text
        base["chunks"] = self._chunk_plain(text, base["file"])
        base["ok"] = bool(text)
        if not text:
            base["error"] = "HTML se text nahi nikla"
        return base
