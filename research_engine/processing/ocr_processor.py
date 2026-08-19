"""
OCRProcessor — Spec Section 4 (scanned pages / image documents)

Free + offline: Tesseract (pytesseract) + PyMuPDF se page ko image banakar OCR.

Ye module jaan-boojh kar "optional" hai:
    * Tesseract Windows pe alag installer se aata hai (Python package se nahi)
    * install na ho to ye SAAF batata hai ki OCR unavailable hai aur kaise
      install karna hai — pretend nahi karta ki text nikal gaya

Spec Section 18 ke hisaab se: Tesseract 100% free aur open-source hai, koi API
key ya quota nahi.
"""
from __future__ import annotations

import os
import shutil
from typing import Dict, List, Optional

INSTALL_HINT = (
    "OCR ke liye Tesseract chahiye:\n"
    "  1. Windows installer: https://github.com/UB-Mannheim/tesseract/wiki\n"
    "  2. pip install pytesseract\n"
    "  3. Agar PATH mein na ho to .env mein TESSERACT_CMD=C:\\Program Files\\"
    "Tesseract-OCR\\tesseract.exe set karein\n"
    "  4. Hindi ke liye install ke waqt 'Devanagari/Hindi' language data chunein "
    "(lang='hin+eng')"
)


class OCRProcessor:
    name = "ocr"

    def __init__(self, lang: str = "eng", dpi: int = 200):
        self.lang = lang
        self.dpi = dpi
        self.last_error: str = ""

    # ── availability ─────────────────────────────────────────────────────────
    def _pytesseract(self):
        import pytesseract  # lazy
        cmd = os.getenv("TESSERACT_CMD", "")
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        return pytesseract

    def available(self) -> Dict:
        """{"ok": bool, "reason": str} — kabhi exception nahi."""
        try:
            pytesseract = self._pytesseract()
        except Exception as exc:
            return {"ok": False, "reason": f"pytesseract import nahi hua ({exc}). {INSTALL_HINT}"}

        cmd = os.getenv("TESSERACT_CMD", "") or "tesseract"
        if not (os.path.isfile(cmd) or shutil.which(cmd)):
            return {"ok": False,
                    "reason": f"tesseract binary nahi mila ('{cmd}'). {INSTALL_HINT}"}
        try:
            import fitz  # noqa: F401  — page ko image banane ke liye
        except Exception as exc:
            return {"ok": False, "reason": f"PyMuPDF nahi hai ({exc})"}
        try:
            _ = pytesseract.get_tesseract_version()
        except Exception as exc:
            return {"ok": False, "reason": f"tesseract chal nahi raha ({exc}). {INSTALL_HINT}"}
        return {"ok": True, "reason": ""}

    # ── main ─────────────────────────────────────────────────────────────────
    def ocr_pdf_pages(self, file_path: str, pages: List[int],
                      max_pages: int = 20) -> Dict:
        """
        pages: 1-based page numbers (PDFProcessor ke scanned_pages).
        Returns {"ok", "reason", "pages":[{"page","text","chars"}], "text"}
        """
        status = self.available()
        if not status["ok"]:
            return {"ok": False, "reason": status["reason"], "pages": [], "text": ""}
        if not pages:
            return {"ok": True, "reason": "koi scanned page nahi tha", "pages": [], "text": ""}

        import fitz
        import pytesseract
        from PIL import Image

        out: List[Dict] = []
        chunks: List[str] = []
        name = os.path.basename(file_path)
        reason = ""

        try:
            doc = fitz.open(file_path)
        except Exception as exc:
            return {"ok": False, "reason": f"PDF khul nahi rahi: {exc}",
                    "pages": [], "text": ""}

        try:
            for page_no in pages[:max_pages]:
                index = page_no - 1
                if index < 0 or index >= doc.page_count:
                    continue
                try:
                    pixmap = doc[index].get_pixmap(dpi=self.dpi)
                    image = Image.frombytes("RGB", (pixmap.width, pixmap.height),
                                            pixmap.samples)
                    text = (pytesseract.image_to_string(image, lang=self.lang) or "").strip()
                except Exception as exc:
                    reason = f"page {page_no} OCR fail: {type(exc).__name__}: {exc}"
                    continue
                out.append({"page": page_no, "text": text, "chars": len(text)})
                if text:
                    chunks.append(f"[Source: {name}, Page {page_no}]\n{text}")
        finally:
            try:
                doc.close()
            except Exception:
                pass

        skipped = max(0, len(pages) - max_pages)
        if skipped:
            reason = (reason + " | " if reason else "") + \
                     f"{skipped} scanned pages OCR nahi hue (limit {max_pages})"

        return {"ok": True, "reason": reason, "pages": out, "text": "\n\n".join(chunks)}

    def note(self, result: Dict) -> str:
        if not result.get("ok"):
            return f"OCR nahi chala — {result.get('reason', '')}"
        done = len([p for p in result.get("pages", []) if p.get("chars")])
        extra = f" ({result['reason']})" if result.get("reason") else ""
        return f"OCR se {done} scanned pages ka text nikla{extra}"
