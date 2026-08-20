"""Non-blocking API for long DEEP/MAXIMUM research runs."""
from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from research_engine.depth import BOOL_FIELDS, depth_limits
from utils.progress_tracker import get_progress
from utils.research_jobs import runner


router = APIRouter()


class ResearchJobRequest(BaseModel):
    question: str
    project_id: str = "default"
    depth_mode: str = "DEEP"
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


@router.post("/research-jobs", status_code=202)
def start_research_job(request: ResearchJobRequest):
    """Research ko background worker mein start karke turant job_id do."""
    mode = (request.depth_mode or "DEEP").upper().strip()
    if mode not in {"QUICK", "DEEP", "MAXIMUM", "CUSTOM"}:
        raise HTTPException(status_code=400, detail="depth_mode invalid hai")
    if not (request.question or "").strip():
        raise HTTPException(status_code=400, detail="question khaali nahi ho sakta")

    # Lazy import keeps startup light.
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
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    return {
        "job_id": job.job_id,
        "status": job.status,
        "status_url": f"/api/v1/research-jobs/{job.job_id}",
        "result_url": f"/api/v1/research-jobs/{job.job_id}/result",
        "progress_url": f"/api/v1/research-jobs/{job.job_id}/progress",
        "note": "Request disconnect/timeout hone par bhi process ke zinda rehne tak research chal sakti hai.",
    }


@router.get("/research-jobs/{job_id}")
def research_job_status(job_id: str):
    item = runner.get(job_id)
    if not item:
        raise HTTPException(status_code=404, detail="Research job nahi mila")
    return item


@router.get("/research-jobs/{job_id}/progress")
def research_job_progress(job_id: str):
    item = runner.get(job_id)
    if not item:
        raise HTTPException(status_code=404, detail="Research job nahi mila")
    return {"job": item, "progress": get_progress(job_id)}


@router.get("/research-jobs/{job_id}/result")
def research_job_result(job_id: str):
    item = runner.get(job_id, include_result=True)
    if not item:
        raise HTTPException(status_code=404, detail="Research job nahi mila")
    if item["status"] in {"queued", "running"}:
        raise HTTPException(status_code=202, detail={
            "message": "Research abhi chal rahi hai",
            "status": item["status"],
        })
    if item["status"] == "failed":
        raise HTTPException(status_code=500, detail={
            "message": "Research job fail hua",
            "error": item.get("error", ""),
        })
    return item["result"]


@router.get("/research-jobs")
def list_research_jobs(limit: int = 20):
    return {"jobs": runner.list(limit=limit)}
