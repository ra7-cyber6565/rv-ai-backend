"""
RAG routes — upload aur ask.

Uploads use bounded streaming + cleanup and all public error responses are kept
human-readable. Raw local paths/library exception text stay inside the backend;
capability endpoints explain optional dependencies separately.

Every endpoint that reads/writes a project namespace requires the server-issued
``X-Project-Token`` capability. A caller can still create its own anonymous
session for ₹0, but cannot poison or query another session merely by guessing a
project id.
"""
import os

from fastapi import APIRouter, UploadFile, File, HTTPException, Form, Header
from pydantic import BaseModel, Field

from research_engine.vector_search import VectorSearch
from research_engine.agent_manager import manager
from utils.project_guard import require_project_access
from utils.upload_safety import cleanup_upload_path, save_upload_stream

router = APIRouter()

SUPPORTED = (".pdf", ".docx", ".txt", ".md", ".markdown", ".text",
             ".html", ".htm", ".vtt", ".srt")
MAX_UPLOAD_BYTES = 60 * 1024 * 1024
MAX_AUDIO_BYTES = 200 * 1024 * 1024
AUDIO_SUPPORTED = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma",
                   ".mp4", ".mov", ".mkv", ".webm", ".m4b", ".opus")
_MAX_QUESTION_CHARS = 20_000
_MAX_PROJECT_ID_CHARS = 80
_MAX_VIDEO_REF_CHARS = 2048
_MAX_TITLE_CHARS = 300


class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=_MAX_QUESTION_CHARS)
    project_id: str = Field(default="default", min_length=1, max_length=_MAX_PROJECT_ID_CHARS)


class YouTubeRequest(BaseModel):
    video: str = Field(..., min_length=1, max_length=_MAX_VIDEO_REF_CHARS)
    project_id: str = Field(default="default", min_length=1, max_length=_MAX_PROJECT_ID_CHARS)
    title: str = Field(default="", max_length=_MAX_TITLE_CHARS)


def _safe_notes(value) -> list[str]:
    """Return short human processing notes without raw exception/path dumps."""
    out: list[str] = []
    for item in list(value or [])[:8]:
        text = " ".join(str(item or "").split())[:300]
        low = text.lower()
        if not text:
            continue
        if any(marker in low for marker in (
            "traceback", "exception", "errno", "c:\\", "/tmp/", "/home/",
            "resourceexhausted", "protobuf", "api_key",
        )):
            continue
        out.append(text)
    return out


def _ingest(file_path: str, filename: str, project_id: str, use_ocr: bool) -> dict:
    result = VectorSearch().ingest_file(file_path, project_id,
                                       use_ocr=use_ocr, filename=filename)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail={
            "message": f"'{filename}' se usable text store nahi ho saka.",
            "notes": _safe_notes(result.get("notes")),
            "hint": "Processing capabilities endpoint se PDF/OCR/document support check kar sakte hain.",
        })
    return result


@router.post("/upload-audio")
async def upload_audio(
    file: UploadFile = File(...),
    project_id: str = Form("default", min_length=1, max_length=_MAX_PROJECT_ID_CHARS),
    language: str | None = Form(None, max_length=32),
    x_project_token: str | None = Header(default=None, alias="X-Project-Token"),
):
    """Audio/video upload -> local speech-to-text -> timestamped vector chunks."""
    require_project_access(project_id, x_project_token)
    filename = file.filename or "audio"
    extension = os.path.splitext(filename)[1].lower()

    if extension not in AUDIO_SUPPORTED:
        raise HTTPException(
            status_code=400,
            detail=f"'{extension}' audio format supported nahi hai. "
                   f"Supported: {', '.join(AUDIO_SUPPORTED)}"
        )

    file_path = await save_upload_stream(file, max_bytes=MAX_AUDIO_BYTES)
    result = None
    try:
        from research_engine.memory.speech_to_text import transcribe_to_vtt

        result = transcribe_to_vtt(file_path, language=language or None)
        if not result["ok"]:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Speech-to-text complete nahi ho saka.",
                    "hint": "Processing capabilities check karein; local speech-to-text optional dependency hai.",
                }
            )

        vtt_result = _ingest(result["vtt_path"], f"{filename}.vtt", project_id, use_ocr=False)
        return {
            "message": "Audio transcript successfully processed",
            "filename": filename,
            "transcript_chunks": vtt_result.get("chunks", 0),
            "language": result.get("language", "unknown"),
            "project_id": project_id,
        }
    finally:
        try:
            if result and result.get("vtt_path"):
                vtt_path = os.path.abspath(result["vtt_path"])
                if os.path.exists(vtt_path):
                    os.remove(vtt_path)
        except Exception:
            pass
        cleanup_upload_path(file_path)


@router.post("/upload-document")
async def upload_document(
    file: UploadFile = File(...),
    project_id: str = Form("default", min_length=1, max_length=_MAX_PROJECT_ID_CHARS),
    use_ocr: bool = Form(True),
    x_project_token: str | None = Header(default=None, alias="X-Project-Token"),
):
    """pdf/docx/txt/md/html/vtt/srt ko isolated project mein ingest karo."""
    require_project_access(project_id, x_project_token)
    filename = file.filename or "upload"
    extension = os.path.splitext(filename)[1].lower()
    if extension not in SUPPORTED:
        raise HTTPException(
            status_code=400,
            detail=f"'{extension or 'unknown'}' supported nahi hai. "
                   f"Supported: {', '.join(SUPPORTED)}")

    path = await save_upload_stream(file, max_bytes=MAX_UPLOAD_BYTES)
    try:
        result = _ingest(path, filename, project_id, use_ocr)
    finally:
        cleanup_upload_path(path)

    return {
        "message": f"'{filename}' process ho gayi",
        "kind": result["kind"],
        "chunks": result["chunks"],
        "chars_extracted": result["chars"],
        "notes": _safe_notes(result.get("notes")),
    }


@router.post("/upload-pdf")
async def upload_pdf(
    file: UploadFile = File(...),
    project_id: str = Form("default", min_length=1, max_length=_MAX_PROJECT_ID_CHARS),
    x_project_token: str | None = Header(default=None, alias="X-Project-Token"),
):
    """Backward-compatible PDF endpoint, protected by project capability."""
    require_project_access(project_id, x_project_token)
    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400,
                            detail="Sirf PDF files allowed hain. Dusre formats ke "
                                   "liye /upload-document use karein.")
    path = await save_upload_stream(file, max_bytes=MAX_UPLOAD_BYTES)
    try:
        result = _ingest(path, filename, project_id, use_ocr=True)
    finally:
        cleanup_upload_path(path)

    return {
        "message": f"✅ '{filename}' successfully processed",
        "chunks": result["chunks"],
        "notes": _safe_notes(result.get("notes")),
    }


@router.post("/ingest-youtube")
async def ingest_youtube(
    request: YouTubeRequest,
    x_project_token: str | None = Header(default=None, alias="X-Project-Token"),
):
    """Public YouTube captions ko private project ke timestamped chunks banao."""
    require_project_access(request.project_id, x_project_token)
    from research_engine.processing import TranscriptProcessor

    raw = (request.video or "").strip()
    video_id = raw
    for marker in ("v=", "youtu.be/", "/shorts/", "/embed/"):
        if marker in raw:
            video_id = raw.split(marker, 1)[1]
            break
    video_id = video_id.split("&")[0].split("?")[0].strip("/")
    if not video_id or len(video_id) > 64 or not all(ch.isalnum() or ch in "_-" for ch in video_id):
        raise HTTPException(status_code=400, detail="Video id/URL samajh nahi aaya.")

    processor = TranscriptProcessor()
    captions = processor.youtube_captions(video_id)
    if not captions.get("ok"):
        raise HTTPException(
            status_code=422,
            detail="Public captions available/process nahi ho sake. Processing capabilities check karein.",
        )

    name = request.title.strip() or f"youtube_{video_id}"
    chunks = processor.chunk(captions["cues"], name)
    stored = VectorSearch().ingest_chunks(chunks, name, request.project_id)
    if not stored["ok"]:
        raise HTTPException(
            status_code=500,
            detail="Transcript vector store me save nahi ho saka; local storage/capabilities check karein.",
        )

    return {
        "message": f"'{name}' ke captions store ho gaye",
        "cues": len(captions["cues"]),
        "timestamped_blocks": len(chunks),
        "chunks": stored["chunks"],
        "honesty_note": "Ye video ke public captions hain, audio transcription nahi. "
                        "Citations timestamp ke saath aayengi.",
    }


@router.post("/transcribe-audio")
async def transcribe_audio(
    file: UploadFile = File(...),
    project_id: str = Form("default", min_length=1, max_length=_MAX_PROJECT_ID_CHARS),
    title: str = Form("", max_length=_MAX_TITLE_CHARS),
    lang: str = Form("", max_length=32),
    x_project_token: str | None = Header(default=None, alias="X-Project-Token"),
):
    """User-provided local audio/video ko locally transcribe + ingest karo."""
    require_project_access(project_id, x_project_token)
    from research_engine.processing import SpeechToTextProcessor

    filename = file.filename or "audio"
    extension = os.path.splitext(filename)[1].lower()
    if extension not in AUDIO_SUPPORTED:
        raise HTTPException(
            status_code=400,
            detail=f"'{extension or 'unknown'}' audio/video format supported nahi. "
                   f"Supported: {', '.join(AUDIO_SUPPORTED)}")

    stt = SpeechToTextProcessor()
    status = stt.available()
    if not status.get("ok"):
        raise HTTPException(status_code=501, detail={
            "message": "Local speech-to-text install nahi hai.",
            "hint": "Processing capabilities endpoint par available local backend check karein.",
        })

    path = await save_upload_stream(file, max_bytes=MAX_AUDIO_BYTES)
    try:
        result = stt.process_file(path, lang=(lang.strip() or None))
    finally:
        cleanup_upload_path(path)

    if not result.get("ok"):
        raise HTTPException(status_code=422, detail={
            "message": f"'{filename}' transcribe nahi hui.",
            "hint": "Audio format/quality aur local speech-to-text capability check karein.",
        })

    name = title.strip() or filename
    stored = VectorSearch().ingest_chunks(result["chunks"], result["source"],
                                          project_id)
    if not stored["ok"]:
        raise HTTPException(
            status_code=500,
            detail="Transcript local vector store me save nahi ho saka.",
        )

    return {
        "message": f"'{name}' locally transcribe hoke store ho gayi",
        "backend": result.get("backend", ""),
        "timestamped_blocks": len(result["chunks"]),
        "chunks": stored["chunks"],
        "duration_note": result.get("duration_note", ""),
        "honesty_note": result.get("disclaimer", ""),
    }


@router.get("/processing-capabilities")
def processing_capabilities():
    """Optional processing capability readiness; no provider generation call."""
    from research_engine.processing import OCRProcessor, PDFProcessor, SpeechToTextProcessor

    ocr = OCRProcessor().available()
    stt = SpeechToTextProcessor().available()
    yt_flag = os.getenv("ALLOW_YT_TRANSCRIPT", "").lower() in ("1", "true", "yes")

    def _has(module: str) -> bool:
        try:
            __import__(module)
            return True
        except Exception:
            return False

    return {
        "pdf_text": {
            "available": PDFProcessor().available(),
            "needs": "pymupdf (requirements.txt mein hai)",
        },
        "pdf_ocr_for_scanned_pages": {
            "available": bool(ocr.get("ok")),
            "detail": {"ok": bool(ocr.get("ok")), "backend": str(ocr.get("backend") or "")},
            "needs": "pytesseract + pillow + system Tesseract binary (requirements-optional.txt)",
        },
        "docx": {"available": _has("docx"), "needs": "python-docx"},
        "transcripts_vtt_srt": {"available": True, "needs": "kuch nahi — built-in"},
        "youtube_captions": {
            "available": yt_flag and _has("youtube_transcript_api"),
            "enabled_flag": yt_flag,
            "library_installed": _has("youtube_transcript_api"),
            "needs": ".env mein ALLOW_YT_TRANSCRIPT=true + youtube-transcript-api",
        },
        "full_text_fetch": {
            "enabled": os.getenv("ALLOW_FULLTEXT_FETCH", "true").lower()
                       not in ("false", "0", "no", "off"),
            "note": "arXiv / Internet Archive / Europe PMC OA / Wikipedia / open PDFs "
                    "se full text laata hai. Paywalled publishers deliberately blocked hain.",
        },
        "audio_video_transcription": {
            "available": bool(stt.get("ok")),
            "backend": str(stt.get("backend") or ""),
            "needs": "faster-whisper YA openai-whisper (FREE + local).",
            "note": "Local file ka machine transcription; platform download/bypass nahi karta.",
        },
    }


@router.post("/ask")
async def ask(
    request: QuestionRequest,
    x_project_token: str | None = Header(default=None, alias="X-Project-Token"),
):
    """QUICK source-based research inside the caller's private project."""
    require_project_access(request.project_id, x_project_token)
    return manager.research(
        question=request.question,
        project_id=request.project_id,
        depth_mode="QUICK",
        job_id=request.project_id,
    )
