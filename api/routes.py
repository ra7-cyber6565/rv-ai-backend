"""
RAG routes — upload aur ask.

BADLAV (Spec Section 4/5 ka missing wiring):
    Pehle sirf /upload-pdf tha, jo seedha rag.pipeline.ingest_pdf par jaata tha.
    Uska matlab tha:
        * scanned PDF upload karo → chup-chaap 0 useful chunks (OCR kahin
          connected nahi tha)
        * .docx / .txt / .vtt / .srt upload karne ka koi rasta hi nahi tha
        * processing/ ke chaaron module bane pade the par unhe koi call nahi
          karta tha

    Ab upload DocumentProcessor ke through jaata hai, isliye OCR fallback,
    docx, plain text, HTML aur timestamped transcripts sach mein kaam karte hain.
"""
import os
import shutil
import tempfile
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from pydantic import BaseModel

from rag.pipeline import ask_question
from research_engine.vector_search import VectorSearch
from research_engine.agent_manager import manager  # ✅ ADD: Deep research engine

router = APIRouter()

# Kaunse formats andar aa sakte hain (DocumentProcessor inhe handle karta hai)
SUPPORTED = (".pdf", ".docx", ".txt", ".md", ".markdown", ".text",
             ".html", ".htm", ".vtt", ".srt")

# Upload size cap — bina cap ke ek badi file server ki memory kha sakti hai
MAX_UPLOAD_BYTES = 60 * 1024 * 1024      # 60 MB
# Audio/podcast files documents se badi hoti hain — inke liye alag, bada cap
MAX_AUDIO_BYTES = 200 * 1024 * 1024      # 200 MB
# Local STT ye audio/video formats leta hai
AUDIO_SUPPORTED = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma",
                   ".mp4", ".mov", ".mkv", ".webm", ".m4b", ".opus")


class QuestionRequest(BaseModel):
    question: str
    project_id: str = "default"


class YouTubeRequest(BaseModel):
    video: str                            # URL ya sirf video id
    project_id: str = "default"
    title: str = ""


def _save_upload(file: UploadFile, content: bytes) -> str:
    """Bytes ko temp file mein likho, extension bachaate hue."""
    extension = os.path.splitext(file.filename or "")[1].lower() or ".bin"
    directory = tempfile.mkdtemp(prefix="infinity_upload_")
    path = os.path.join(directory, f"upload{extension}")
    with open(path, "wb") as handle:
        handle.write(content)
    return path


async def _read_upload(file: UploadFile, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File khaali hai.")
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File {max_bytes // (1024 * 1024)}MB se badi hai.")
    return content


def _ingest(file_path: str, filename: str, project_id: str, use_ocr: bool) -> dict:
    result = VectorSearch().ingest_file(file_path, project_id,
                                       use_ocr=use_ocr, filename=filename)
    if not result["ok"]:
        # 422: file mili par usme se kaam ka text nahi nikla — ye user ko
        # saaf pata hona chahiye, chup-chaap "success" nahi bolna
        raise HTTPException(status_code=422, detail={
            "message": f"'{filename}' se text nahi nikala ja saka.",
            "error": result.get("error", ""),
            "notes": result.get("notes", []),
        })
    return result


@router.post("/upload-audio")
async def upload_audio(file: UploadFile = File(...),
                      project_id: str = Form("default"),
                      language: str = Form(None)):
    """
    Audio/video file upload karo — automatic speech-to-text.

    Supported: mp3, wav, m4a, ogg, flac, mp4, mov, etc.

    Requires: openai-whisper (optional dependency)
    Install: pip install openai-whisper

    Agar installed nahi hai, to 422 error milega with instructions.
    """
    filename = file.filename or "audio"
    extension = os.path.splitext(filename)[1].lower()

    if extension not in AUDIO_SUPPORTED:
        raise HTTPException(
            status_code=400,
            detail=f"'{extension}' audio format supported nahi hai. "
                   f"Supported: {', '.join(AUDIO_SUPPORTED)}"
        )

    content = await _read_upload(file, MAX_AUDIO_BYTES)
    file_path = _save_upload(file, content)

    try:
        from research_engine.memory.speech_to_text import transcribe_to_vtt

        # Generate VTT transcript
        result = transcribe_to_vtt(file_path, language=language or None)

        if not result["ok"]:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Speech-to-text failed",
                    "error": result["error"],
                    "hint": "Make sure openai-whisper is installed: pip install openai-whisper"
                }
            )

        # Ingest the generated VTT file
        vtt_result = _ingest(result["vtt_path"], f"{filename}.vtt", project_id, use_ocr=False)

        return {
            "message": "Audio transcript successfully processed",
            "filename": filename,
            "transcript_chunks": vtt_result.get("chunks", 0),
            "language": result.get("language", "unknown"),
            "project_id": project_id,
        }

    finally:
        # Cleanup
        try:
            os.remove(file_path)
            if result.get("vtt_path"):
                os.remove(result["vtt_path"])
        except Exception:
            pass


@router.post("/upload-document")
async def upload_document(file: UploadFile = File(...),
                          project_id: str = Form("default"),
                          use_ocr: bool = Form(True)):
    """
    Koi bhi supported document upload karo: pdf, docx, txt, md, html, vtt, srt.

    PDF ke scanned pages ke liye OCR automatically try hota hai (agar
    pytesseract installed ho). Response mein honest notes aate hain — kitne
    pages se text mila, kitne scanned the, OCR chala ya nahi.
    """
    filename = file.filename or "upload"
    extension = os.path.splitext(filename)[1].lower()
    if extension not in SUPPORTED:
        raise HTTPException(
            status_code=400,
            detail=f"'{extension or 'unknown'}' supported nahi hai. "
                   f"Supported: {', '.join(SUPPORTED)}")

    content = await _read_upload(file)
    path = _save_upload(file, content)
    try:
        result = _ingest(path, filename, project_id, use_ocr)
    finally:
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    return {
        "message": f"'{filename}' process ho gayi",
        "kind": result["kind"],
        "chunks": result["chunks"],
        "chars_extracted": result["chars"],
        "notes": result["notes"],
    }


@router.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...),
                     project_id: str = Form("default")):
    """
    Purana endpoint (backward compatible response shape).

    Ab ye bhi DocumentProcessor se jaata hai, isliye scanned PDF par OCR
    fallback milta hai — pehle aisa nahi tha.
    """
    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400,
                            detail="Sirf PDF files allowed hain. Dusre formats ke "
                                   "liye /upload-document use karein.")
    content = await _read_upload(file)
    path = _save_upload(file, content)
    try:
        result = _ingest(path, filename, project_id, use_ocr=True)
    finally:
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    return {
        "message": f"✅ '{filename}' successfully processed",
        "chunks": result["chunks"],
        "notes": result["notes"],
    }


@router.post("/ingest-youtube")
async def ingest_youtube(request: YouTubeRequest):
    """
    YouTube ke PUBLIC captions ko timestamped chunks bana kar store karo
    (Spec Section 5 — video/audio pipeline).

    Ye default OFF hai. Chalane ke liye backend/.env mein:
        ALLOW_YT_TRANSCRIPT=true
    aur `pip install youtube-transcript-api`.

    Honesty: ye audio ka transcription nahi karta — sirf wahi captions leta hai
    jo video par publicly maujood hain. Platform ToS ka faisla user ka hai,
    isliye flag deliberately default se band hai.
    """
    from research_engine.processing import TranscriptProcessor

    raw = (request.video or "").strip()
    video_id = raw
    for marker in ("v=", "youtu.be/", "/shorts/", "/embed/"):
        if marker in raw:
            video_id = raw.split(marker, 1)[1]
            break
    video_id = video_id.split("&")[0].split("?")[0].strip("/")
    if not video_id:
        raise HTTPException(status_code=400, detail="Video id/URL samajh nahi aaya.")

    processor = TranscriptProcessor()
    captions = processor.youtube_captions(video_id)
    if not captions.get("ok"):
        raise HTTPException(status_code=422, detail=captions.get("error", "captions nahi mile"))

    name = request.title.strip() or f"youtube_{video_id}"
    chunks = processor.chunk(captions["cues"], name)
    stored = VectorSearch().ingest_chunks(chunks, name, request.project_id)
    if not stored["ok"]:
        raise HTTPException(status_code=500, detail=stored.get("error", "store fail"))

    return {
        "message": f"'{name}' ke captions store ho gaye",
        "cues": len(captions["cues"]),
        "timestamped_blocks": len(chunks),
        "chunks": stored["chunks"],
        "honesty_note": "Ye video ke public captions hain, audio transcription nahi. "
                        "Citations timestamp ke saath aayengi.",
    }


@router.post("/transcribe-audio")
async def transcribe_audio(file: UploadFile = File(...),
                           project_id: str = Form("default"),
                           title: str = Form(""),
                           lang: str = Form("")):
    """
    Local audio/video file ko LOCALLY transcribe karo (Spec Section 5) aur
    timestamped chunks bana kar store karo — citation "12:30" ke saath aati hai.

    HONESTY:
        * Ye LOCAL + FREE hai (koi API key/quota nahi), par bhaari hai — isliye
          faster-whisper/openai-whisper optional install hai. Na ho to endpoint
          501 ke saath saaf install hint deta hai (chup-chaap fail nahi hota).
        * Transcript MACHINE KA BEST GUESS hai, verbatim sach nahi. Har chunk
          '(auto-transcribed)' mark hota hai taaki citation insaani transcript
          jaisa na dikhe.
        * Kisi platform se download/bypass NAHI karta — user apni file deta hai.
          Caption file (.vtt/.srt) available ho to /upload-document behtar hai.
    """
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
        # 501: feature install nahi hai — user ko saaf pata ho, jhooth nahi
        raise HTTPException(status_code=501, detail={
            "message": "Local speech-to-text install nahi hai.",
            "reason": status.get("reason", ""),
        })

    content = await _read_upload(file, MAX_AUDIO_BYTES)
    path = _save_upload(file, content)
    try:
        result = stt.process_file(path, lang=(lang.strip() or None))
    finally:
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    if not result.get("ok"):
        raise HTTPException(status_code=422, detail={
            "message": f"'{filename}' transcribe nahi hui.",
            "error": result.get("error", ""),
        })

    name = title.strip() or filename
    stored = VectorSearch().ingest_chunks(result["chunks"], result["source"],
                                          project_id)
    if not stored["ok"]:
        raise HTTPException(status_code=500, detail=stored.get("error", "store fail"))

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
    """
    Spec Section 18 ki honesty: jo cheez install nahi hai, wo saaf dikhni
    chahiye — chup-chaap degrade nahi hona chahiye.
    """
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
            "detail": ocr,
            "needs": "pytesseract + pillow + system Tesseract binary "
                     "(requirements-optional.txt)",
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
                    "se full text laata hai. Paywalled publishers deliberately "
                    "blocked hain — bypass nahi kiya jaata.",
        },
        "audio_video_transcription": {
            "available": bool(stt.get("ok")),
            "backend": stt.get("backend", ""),
            "detail": stt,
            "needs": "faster-whisper (halka) YA openai-whisper "
                     "(requirements-optional.txt) — dono FREE + local, koi API "
                     "key/quota nahi. Pehli baar model weights download honge.",
            "note": "Local audio/video file ka speech-to-text. Ye MACHINE ka best "
                    "guess hai (verbatim sach nahi) aur har chunk "
                    "'(auto-transcribed)' mark hota hai. Platform se download ya "
                    "bypass NAHI karta — user apni audio file deta hai. Caption "
                    "files (.vtt/.srt) ho to wo behtar hain (transcripts_vtt_srt).",
        },
    }


@router.post("/ask")
async def ask(request: QuestionRequest):
    """
    Sawal poocho — AI source/page number ke saath jawab dega (single call).

    ✅ FIX: Ab ye proper deep research engine use karta hai!
    - Web + Papers + Books + Datasets search
    - QUICK mode (1 Gemini call, ~5 sources)
    - Real external sources, not just uploaded PDFs
    """
    # Use proper deep research engine with QUICK mode
    return manager.research(
        question=request.question,
        project_id=request.project_id,
        depth_mode="QUICK",  # Fast single-call mode
        job_id=request.project_id,
    )
