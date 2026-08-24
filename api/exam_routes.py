"""Project-private API for deterministic exam intelligence.

The caller supplies legally obtained/public past-paper records and an official
syllabus mapping.  The endpoint performs no network/model call and stores a
bounded resumable ledger under the configured Infinity data root.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from research_engine.exam_intelligence import (
    ExamDataError,
    ExamIntelligenceEngine,
    ExamLedgerStore,
)
from utils.project_guard import require_project_access
from utils.process_lock import ProcessLockError
from utils.storage_paths import configured_root


router = APIRouter()


class SyllabusTopicInput(BaseModel):
    topic_id: str = Field(..., min_length=1, max_length=100)
    subject: str = Field(..., min_length=1, max_length=120)
    chapter: str = Field(..., min_length=1, max_length=180)
    topic: str = Field(..., min_length=1, max_length=220)
    official_weight: float = Field(default=1.0, ge=0.1, le=20.0)


class ExamQuestionInput(BaseModel):
    question_id: str = Field(..., min_length=1, max_length=100)
    text: str = Field(..., min_length=3, max_length=4000)
    topic_ids: list[str] = Field(..., min_length=1, max_length=12)
    marks: float = Field(default=1.0, gt=0, le=1000)
    question_type: Literal[
        "mcq", "numeric", "statement", "matching", "short_answer",
        "long_answer", "other",
    ] = "other"
    cognitive_level: Literal[
        "recall", "understanding", "application", "analysis", "mixed", "unknown",
    ] = "unknown"


class ExamPaperInput(BaseModel):
    paper_id: str = Field(..., min_length=1, max_length=100)
    held_on: date
    available_from: date | None = None
    source_id: str = Field(default="", max_length=160)
    source_url: str = Field(default="", max_length=2048)
    questions: list[ExamQuestionInput] = Field(..., min_length=1, max_length=500)


class ExamIntelligenceRequest(BaseModel):
    exam_name: str = Field(..., min_length=1, max_length=200)
    project_id: str = Field(default="default", min_length=1, max_length=80)
    as_of: date
    target_exam_date: date | None = None
    syllabus_version: str = Field(default="", max_length=160)
    syllabus_published_at: date | None = None
    syllabus: list[SyllabusTopicInput] = Field(..., min_length=1, max_length=500)
    papers: list[ExamPaperInput] = Field(..., min_length=1, max_length=60)
    top_k: int = Field(default=10, ge=1, le=50)


def _dump(model):
    method = getattr(model, "model_dump", None)
    if callable(method):
        return method(mode="json")
    return model.dict()


def _ledger() -> ExamLedgerStore:
    root, _explicit = configured_root()
    return ExamLedgerStore(Path(root) / "research_memory" / "exam_intelligence")


@router.post("/exam-intelligence/analyze")
def analyze_exam(
    request: ExamIntelligenceRequest,
    x_project_token: str | None = Header(default=None, alias="X-Project-Token"),
):
    """Run a bounded temporal forecast and persist its private structured audit."""
    require_project_access(request.project_id, x_project_token)
    try:
        result = ExamIntelligenceEngine().analyze(
            exam_name=request.exam_name,
            as_of=request.as_of,
            target_exam_date=request.target_exam_date,
            syllabus_version=request.syllabus_version,
            syllabus_published_at=request.syllabus_published_at,
            syllabus=[_dump(row) for row in request.syllabus],
            papers=[_dump(row) for row in request.papers],
            top_k=request.top_k,
        )
    except ExamDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    try:
        ledger = _ledger().save(request.project_id, result)
    except (ExamDataError, ProcessLockError, OSError, ValueError, TypeError):
        ledger = {"saved": False, "reason": "storage_unavailable"}
    return {
        **result,
        "ledger": ledger,
        "privacy_note": "Past-paper text and analysis remain inside this project capability namespace.",
    }


@router.get("/exam-intelligence/latest")
def latest_exam_analysis(
    project_id: str = Query(..., min_length=1, max_length=80),
    x_project_token: str | None = Header(default=None, alias="X-Project-Token"),
):
    """Resume the most recent private exam analysis without rerunning it."""
    require_project_access(project_id, x_project_token)
    try:
        result = _ledger().latest(project_id)
    except (ExamDataError, ProcessLockError, OSError, ValueError, TypeError):
        raise HTTPException(status_code=503, detail="Exam analysis ledger available nahi hai") from None
    if not result:
        raise HTTPException(status_code=404, detail="Is project mein exam analysis nahi mila")
    return {
        **result,
        "ledger": {"saved": True, "resumed": True},
    }


__all__ = [
    "ExamIntelligenceRequest",
    "ExamPaperInput",
    "ExamQuestionInput",
    "SyllabusTopicInput",
    "analyze_exam",
    "latest_exam_analysis",
    "router",
]
