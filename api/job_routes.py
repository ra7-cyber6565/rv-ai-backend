"""Non-blocking API for long DEEP/MAXIMUM research runs."""
from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from research_engine.depth import BOOL_FIELDS, depth_limits
from utils.admin_guard import require_admin
from utils.job_access import job_access
from utils.progress_tracker import get_progress
from utils.research_jobs import runner


router = APIRouter()
_MAX_QUESTION_CHARS = 20_000
_MAX_PROJECT_ID_CHARS = 80


class ResearchJobRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=_MAX_QUESTION_CHARS)
    project_id: str = Field(default="default", min_length=1, max_length=_MAX_PROJECT_ID_CHARS)
    depth_mode: str = Field(default="DEEP", min_length=1, max_length=16)
    max_sources: Optional[int] = None
    max_rounds: Optional[int] = None
    gemini_calls: Optional[int] = None
    max_per_connector: Optional[int] = None
    chars_per_source: Optional[int] = None
    max_fulltext: Optional[int] = None
    discovery_seconds: Optional[int] = None
    use_papers: Optional[bool] = None
    use_books: Optional[bool] = None
    use_datasets: Optional[bool] = None
    use_red_team: Optional[bool] = None


_CUSTOM_FIELDS = tuple(depth_limits()) + BOOL_FIELDS


def _custom(request: ResearchJobRequest) -> Optional[Dict]:
    values = {name: getattr(request, name, None) for name in _CUSTOM_FIELDS}
    values = {key: value for key, value in values.items() if value is not None}
    return values or None


def _authorized_job(
    job_id: str,
    token: str | None,
    *,
    include_result: bool = False,
) -> Dict:
    """Capability check before returning any per-job metadata/result.

    Deliberately returns the same 404 for unknown job and wrong/missing token so
    the public endpoint cannot be used as a job-id existence oracle.
    """
    if not job_access.verify(job_id, token):
        raise HTTPException(status_code=404, detail="Research job nahi mila")
    item = runner.get(job_id, include_result=include_result)
    if not item:
        raise HTTPException(status_code=404, detail="Research job nahi mila")
    return item


@router.post("/research-jobs", status_code=202)
def start_research_job(request: ResearchJobRequest):
    """Research ko background worker mein start karke turant job id + private token do."""
    mode = (request.depth_mode or "DEEP").upper().strip()
    if mode not in {"QUICK", "DEEP", "MAXIMUM", "CUSTOM"}:
        raise HTTPException(status_code=400, detail="depth_mode invalid hai")
    if not (request.question or "").strip():
        raise HTTPException(status_code=400, detail="question khaali nahi ho sakta")

    if not job_access.status().get("job_capability_tokens_ready"):
        raise HTTPException(
            status_code=503,
            detail="Research job private-access layer ready nahi hai; job start nahi kiya gaya.",
        )

    from research_engine.agent_manager import manager

    try:
        job = runner.submit(
            project_id=request.project_id,
            question=request.question,
            mode=mode,
            custom=_custom(request),
            run=manager.research,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=429,
            detail="Research queue abhi busy/unavailable hai. Thodi der baad dobara try karein.",
        ) from exc

    access_token = job_access.issue(job.job_id)
    return {
        "job_id": job.job_id,
        "job_access_token": access_token,
        "job_access_header": "X-Research-Job-Token",
        "status": job.status,
        "status_url": f"/api/v1/research-jobs/{job.job_id}",
        "result_url": f"/api/v1/research-jobs/{job.job_id}/result",
        "progress_url": f"/api/v1/research-jobs/{job.job_id}/progress",
        "note": (
            "Request disconnect/timeout hone par bhi process ke zinda rehne tak research chal sakti hai. "
            "Completed results local durable store me save hote hain. Poll/result requests me returned "
            "job_access_token ko X-Research-Job-Token header me bhejein; token ko URL/log me mat daalein."
        ),
    }


@router.get("/research-jobs/{job_id}")
def research_job_status(
    job_id: str,
    x_research_job_token: str | None = Header(default=None, alias="X-Research-Job-Token"),
):
    return _authorized_job(job_id, x_research_job_token)


@router.get("/research-jobs/{job_id}/progress")
def research_job_progress(
    job_id: str,
    x_research_job_token: str | None = Header(default=None, alias="X-Research-Job-Token"),
):
    item = _authorized_job(job_id, x_research_job_token)
    return {"job": item, "progress": get_progress(job_id)}


@router.get("/research-jobs/{job_id}/result")
def research_job_result(
    job_id: str,
    x_research_job_token: str | None = Header(default=None, alias="X-Research-Job-Token"),
):
    item = _authorized_job(job_id, x_research_job_token, include_result=True)
    if item["status"] in {"queued", "running"}:
        raise HTTPException(status_code=202, detail={
            "message": "Research abhi chal rahi hai",
            "status": item["status"],
        })
    if item["status"] == "interrupted":
        raise HTTPException(status_code=409, detail={
            "message": "Research server/process restart ki wajah se beech me ruk gayi. Is job ko dobara start karein.",
            "status": "interrupted",
        })
    if item["status"] == "failed":
        # The durable store keeps a redacted internal error for operator/debug
        # use, but a public bearer-capability client does not need exception type,
        # local path or provider detail. Never reflect it here.
        raise HTTPException(status_code=500, detail={
            "message": "Research job complete nahi ho saka. Safe retry ya naya job start karein.",
            "status": "failed",
        })
    return item["result"]


@router.get("/research-jobs")
def list_research_jobs(limit: int = 20, _admin: None = Depends(require_admin)):
    """Server-wide job listing is operational metadata and therefore admin-only."""
    return {"jobs": runner.list(limit=limit)}
