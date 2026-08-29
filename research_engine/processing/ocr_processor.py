"""
OCRProcessor — Spec Section 4 (scanned pages / image documents)

Free + offline: Tesseract (pytesseract) + PyMuPDF se page ko image banakar OCR.

Ye module jaan-boojh kar "optional" hai:
    * Tesseract Windows pe alag installer se aata hai (Python package se nahi)
    * install na ho to ye SAAF batata hai ki OCR unavailable hai aur kaise
      install karna hai — pretend nahi karta ki text nikal gaya

OCR confidence ko accuracy probability nahi maana jaata. Tesseract ke raw
word-confidence values sirf extraction-quality triage signal hain. Har OCR page
ke saath conservative integrity ledger attach hota hai; low/unknown quality
critical evidence ko downstream claim gate par review-required banati hai.
"""
from __future__ import annotations

import os
import shutil
from typing import Dict, List

from ..extraction_integrity import assess_ocr_confidences

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
            import fitz  # noqa: F401
        except Exception as exc:
            return {"ok": False, "reason": f"PyMuPDF nahi hai ({exc})"}
        try:
            _ = pytesseract.get_tesseract_version()
        except Exception as exc:
            return {"ok": False, "reason": f"tesseract chal nahi raha ({exc}). {INSTALL_HINT}"}
        return {"ok": True, "reason": ""}

    @staticmethod
    def _text_from_data(data: Dict) -> str:
        """Rebuild readable lines from pytesseract image_to_data output."""
        texts = list(data.get("text") or [])
        blocks = list(data.get("block_num") or [])
        pars = list(data.get("par_num") or [])
        lines = list(data.get("line_num") or [])
        grouped: Dict[tuple, List[str]] = {}
        order: List[tuple] = []
        for index, raw in enumerate(texts):
            token = str(raw or "").strip()
            if not token:
                continue
            key = (
                blocks[index] if index < len(blocks) else 0,
                pars[index] if index < len(pars) else 0,
                lines[index] if index < len(lines) else index,
            )
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(token)
        return "\n".join(" ".join(grouped[key]) for key in order if grouped[key]).strip()

    def _ocr_image(self, pytesseract, image) -> Dict:
        """One OCR call returns text plus confidence ledger."""
        output = getattr(getattr(pytesseract, "Output", None), "DICT", "dict")
        data = pytesseract.image_to_data(image, lang=self.lang, output_type=output) or {}
        if not isinstance(data, dict):
            raise ValueError("pytesseract image_to_data did not return a dict")
        texts = list(data.get("text") or [])
        confs = list(data.get("conf") or [])
        text = self._text_from_data(data)
        integrity = assess_ocr_confidences(
            confs,
            total_tokens=len(texts),
            nonempty_tokens=sum(1 for item in texts if str(item or "").strip()),
            engine="tesseract",
            language=self.lang,
            dpi=self.dpi,
        )
        return {"text": text, "integrity": integrity}

    def ocr_pdf_pages(self, file_path: str, pages: List[int],
                      max_pages: int = 20) -> Dict:
        """
        pages: 1-based page numbers (PDFProcessor ke scanned_pages).
        Returns pages with text, chars and extraction_integrity.
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
        reasons: List[str] = []

        try:
            doc = fitz.open(file_path)
        except Exception as exc:
            return {"ok": False, "reason": f"PDF khul nahi rahi: {exc}",
                    "pages": [], "text": ""}

        try:
            for page_no in pages[:max_pages]:
                index = page_no - 1
                if index < 0 or index >= doc.page_count:
                    reasons.append(f"page {page_no} range ke bahar tha")
                    continue
                try:
                    pixmap = doc[index].get_pixmap(dpi=self.dpi)
                    image = Image.frombytes("RGB", (pixmap.width, pixmap.height),
                                            pixmap.samples)
                    captured = self._ocr_image(pytesseract, image)
                    text = str(captured.get("text") or "").strip()
                    integrity = dict(captured.get("integrity") or {})
                except Exception as exc:
                    reasons.append(f"page {page_no} OCR fail: {type(exc).__name__}: {exc}")
                    continue
                out.append({
                    "page": page_no,
                    "text": text,
                    "chars": len(text),
                    "extraction_integrity": integrity,
                })
                if text:
                    chunks.append(f"[Source: {name}, Page {page_no}]\n{text}")
        finally:
            try:
                doc.close()
            except Exception:
                pass

        skipped = max(0, len(pages) - max_pages)
        if skipped:
            reasons.append(f"{skipped} scanned pages OCR nahi hue (limit {max_pages})")

        return {"ok": True, "reason": " | ".join(reasons),
                "pages": out, "text": "\n\n".join(chunks)}

    def note(self, result: Dict) -> str:
        if not result.get("ok"):
            return f"OCR nahi chala — {result.get('reason', '')}"
        pages = [p for p in result.get("pages", []) if p.get("chars")]
        done = len(pages)
        review = len([
            p for p in pages
            if (p.get("extraction_integrity") or {}).get("review_required")
        ])
        quality = f"; {review}/{done} page manual/independent review maangte hain" if done else ""
        extra = f" ({result['reason']})" if result.get("reason") else ""
        return f"OCR se {done} scanned pages ka text nikla{quality}{extra}"
