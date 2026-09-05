"""Non-blocking API for long DEEP/MAXIMUM/MARATHON research runs."""
from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from research_engine.depth import BOOL_FIELDS, depth_limits
from research_engine.quality_release import enforce_quality_release
from utils.admin_guard import require_admin
from utils.job_access import job_access
from utils.progress_tracker import STAGES, get_progress
from utils.project_guard import require_project_access
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
    use_patents: Optional[bool] = None
    use_red_team: Optional[bool] = None


_CUSTOM_FIELDS = tuple(depth_limits()) + BOOL_FIELDS
_PROGRESS_LOG_LIMIT = 24
_PROGRESS_NOTE_CHARS = 240
_UNSAFE_PROGRESS_MARKERS = (
    "traceback", "resourceexhausted", "protobuf", "grpc_status",
    "api_key", "authorization", "bearer ", "access_token", "refresh_token",
    "client_secret", "secret=", "<html", "<!doctype",
)


def _custom(request: ResearchJobRequest) -> Optional[Dict]:
    values = {name: getattr(request, name, None) for name in _CUSTOM_FIELDS}
    values = {key: value for key, value in values.items() if value is not None}
    return values or None


def _progress_result_snapshot(job_id: str) -> Dict:
    """Return a bounded, non-secret progress trail for the completed result.

    The live progress endpoint is intentionally separate while work is running,
    but the browser replaces that panel with the final answer at completion.
    Without a copy on the result boundary, useful lines such as contradiction,
    independence, reasoning and hypothesis stages disappear even though the run
    succeeded.  This compact snapshot lets any client keep a collapsible
    "research process" section after rendering the answer.

    Project/job ids, the question, timestamps and unbounded/raw notes are not
    copied.  The full live endpoint remains protected by the job capability.
    """
    progress = get_progress(job_id)
    if not isinstance(progress, dict) or progress.get("error"):
        return {"available": False}

    rows = []
    for item in list(progress.get("log") or [])[-_PROGRESS_LOG_LIMIT:]:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage") or "").strip().upper()
        if stage not in STAGES:
            continue
        note = " ".join(str(item.get("note") or "").split())[:_PROGRESS_NOTE_CHARS]
        if any(marker in note.lower() for marker in _UNSAFE_PROGRESS_MARKERS):
            note = "Technical provider detail hidden; stage status retained."
        rows.append({"stage": stage, "note": note})

    def count(name: str) -> int:
        try:
            return max(0, int(progress.get(name) or 0))
        except (TypeError, ValueError):
            return 0

    current = str(progress.get("current_stage") or "").strip().upper()
    if current not in STAGES:
        current = ""
    return {
        "available": True,
        "current_stage": current,
        "stages_done": min(len(STAGES), count("stages_done")),
        "stages_total": len(STAGES),
        "sources_discovered": count("sources_discovered"),
        "documents_processed": count("documents_processed"),
        "evidence_conflicts_found": count("evidence_conflicts_found"),
        "full_text_sources_read": count("full_text_sources_read"),
        "reasoning_calls_used": count("gemini_calls_used"),
        "log": rows,
    }


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
def start_research_job(
    request: ResearchJobRequest,
    x_project_token: str | None = Header(default=None, alias="X-Project-Token"),
):
    """Start long research only inside the caller's private project namespace."""
    require_project_access(request.project_id, x_project_token)
    mode = (request.depth_mode or "DEEP").upper().strip()
    if mode not in {"QUICK", "DEEP", "MAXIMUM", "MARATHON", "COMPANY", "COMPANY_PLUS", "CUSTOM"}:
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
        raise HTTPException(status_code=500, detail={
            "message": "Research job complete nahi ho saka. Safe retry ya naya job start karein.",
            "status": "failed",
        })
    result = item["result"]
    if not isinstance(result, dict):
        return result
    response = dict(result)
    progress = _progress_result_snapshot(job_id)
    response["research_progress"] = progress
    # Final research quality is enforced on the user-facing copy, after the
    # bounded progress snapshot is attached.  Persisted job bytes are never
    # mutated and a recovered/legacy result cannot keep a false VERIFIED badge.
    return enforce_quality_release(
        response,
        recovery_used=bool(response.get("recovered") or response.get("recovery_used")),
        progress_snapshot=progress,
    )


@router.get("/research-jobs")
def list_research_jobs(limit: int = 20, _admin: None = Depends(require_admin)):
    """Server-wide job listing is operational metadata and therefore admin-only."""
    return {"jobs": runner.list(limit=limit)}
