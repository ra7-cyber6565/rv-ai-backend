"""
processing/ — Spec Section 3, 4, 5 (Books/PDF/Video pipelines)

    DocumentProcessor       entry point: file → text + citation-ready chunks
    PDFProcessor            page-wise extraction + scanned page detection
    OCRProcessor            Tesseract (optional, honestly reports if missing)
    TranscriptProcessor     .vtt/.srt → timestamped chunks
    SpeechToTextProcessor   local Whisper (optional) → timestamped chunks from audio

Sab lazy hain: bhaari deps (fitz, pytesseract, docx, faster-whisper) tabhi import
hote hain jab us format ki file actually aati hai.
"""
from .document_processor import DocumentProcessor
from .ocr_processor import OCRProcessor
from .pdf_processor import PDFProcessor
from .speech_to_text import SpeechToTextProcessor
from .transcript_processor import TranscriptProcessor

__all__ = ["DocumentProcessor", "PDFProcessor", "OCRProcessor",
           "TranscriptProcessor", "SpeechToTextProcessor"]
