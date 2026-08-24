"""Protected API for patient, resumable PDF/book ingestion."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from research_engine.reading_sessions import (
    DEFAULT_BATCH_PAGES,
    MAX_BATCH_PAGES,
    ReadingSessionError,
    ReadingSessionStore,
    ResumableReadingManager,
    build_metadata,
    public_session,
)
from utils.process_lock import ProcessLockError
from utils.project_guard import require_project_access
from utils.storage_paths import configured_root
from utils.upload_safety import cleanup_upload_path, save_upload_stream


router = APIRouter()
MAX_READING_PDF_BYTES = 60 * 1024 * 1024


class ResumeReadingRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=80)
    batch_pages: int = Field(default=DEFAULT_BATCH_PAGES, ge=1, le=MAX_BATCH_PAGES)
    use_ocr: bool = True


def _store() -> ReadingSessionStore:
    root, _explicit = configured_root()
    return ReadingSessionStore(f"{root}/research_memory/reading_sessions")


def _manager() -> ResumableReadingManager:
    return ResumableReadingManager(_store())


def _safe_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ReadingSessionError):
        message = str(exc)
        status = 404 if "nahi mila" in message else 422
        return HTTPException(status_code=status, detail=message)
    return HTTPException(
        status_code=503,
        detail="Reading session storage/processor abhi available nahi hai.",
    )


@router.post("/reading-sessions/start")
async def start_reading_session(
    file: UploadFile = File(...),
    project_id: str = Form(..., min_length=1, max_length=80),
    title: str = Form("", max_length=300),
    author: str = Form("", max_length=240),
    edition: str = Form("", max_length=160),
    publication_year: str = Form("", max_length=12),
    source_identifier: str = Form("", max_length=160),
    source_url: str = Form("", max_length=2048),
    access_basis: str = Form("unknown_user_supplied", max_length=64),
    original_language: str = Form("und", max_length=32),
    review_language: str = Form("en", max_length=32),
    translation_status: str = Form("pending_semantic_translation_review", max_length=64),
    translation_evidence_id: str = Form("", max_length=200),
    batch_pages: int = Form(DEFAULT_BATCH_PAGES, ge=1, le=MAX_BATCH_PAGES),
    use_ocr: bool = Form(True),
    x_project_token: str | None = Header(default=None, alias="X-Project-Token"),
):
    """Preserve a PDF and inspect/index its first bounded sequential batch."""
    require_project_access(project_id, x_project_token)
    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Resumable page-by-page reading abhi PDF ke liye supported hai; dusre documents /upload-document se ingest karein.",
        )
    temp_path = await save_upload_stream(
        file,
        max_bytes=MAX_READING_PDF_BYTES,
        prefix="infinity_reading_",
    )
    try:
        metadata = build_metadata(
            filename=filename,
            title=title,
            author=author,
            edition=edition,
            publication_year=publication_year,
            source_identifier=source_identifier,
            source_url=source_url,
            access_basis=access_basis,
            original_language=original_language,
            review_language=review_language,
            translation_status=translation_status,
            translation_evidence_id=translation_evidence_id,
        )
        state = _manager().start(
            project_id,
            temp_path,
            metadata,
            batch_pages=batch_pages,
            use_ocr=use_ocr,
        )
        return {
            "message": "Reading session save hui aur pehla bounded page batch process hua.",
            "session": public_session(state),
        }
    except (ReadingSessionError, ProcessLockError, OSError, ValueError, TypeError) as exc:
        raise _safe_error(exc) from None
    finally:
        cleanup_upload_path(temp_path)


@router.post("/reading-sessions/{session_id}/resume")
def resume_reading_session(
    session_id: str,
    request: ResumeReadingRequest,
    x_project_token: str | None = Header(default=None, alias="X-Project-Token"),
):
    """Continue with the next uninspected sequential page batch."""
    require_project_access(request.project_id, x_project_token)
    try:
        state = _manager().resume(
            request.project_id,
            session_id,
            batch_pages=request.batch_pages,
            use_ocr=request.use_ocr,
        )
        return {"session": public_session(state)}
    except (ReadingSessionError, ProcessLockError, OSError, ValueError, TypeError) as exc:
        raise _safe_error(exc) from None


@router.get("/reading-sessions/{session_id}")
def reading_session_status(
    session_id: str,
    project_id: str = Query(..., min_length=1, max_length=80),
    x_project_token: str | None = Header(default=None, alias="X-Project-Token"),
):
    require_project_access(project_id, x_project_token)
    try:
        return {"session": public_session(_store().load(project_id, session_id))}
    except (ReadingSessionError, ProcessLockError, OSError, ValueError, TypeError) as exc:
        raise _safe_error(exc) from None


@router.get("/reading-sessions")
def list_reading_sessions(
    project_id: str = Query(..., min_length=1, max_length=80),
    x_project_token: str | None = Header(default=None, alias="X-Project-Token"),
):
    require_project_access(project_id, x_project_token)
    try:
        return {"sessions": [public_session(row) for row in _store().list(project_id)]}
    except (ReadingSessionError, ProcessLockError, OSError, ValueError, TypeError) as exc:
        raise _safe_error(exc) from None


__all__ = ["router"]
