from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from research_engine.agent_manager import manager
from research_engine.depth import (BOOL_FIELDS, depth_limits,
                                    get_depth_config, quota_note)
from utils.admin_guard import require_admin
from utils.progress_tracker import get_progress
from utils.project_guard import require_project_access
from utils.reasoning_status import reasoning_status

router = APIRouter()

# Public JSON endpoints must not accept arbitrarily large single strings. Large
# source material belongs in the streaming upload path; a question/message stays
# bounded so one request cannot consume unbounded memory or prompt budget.
_MAX_QUESTION_CHARS = 20_000
_MAX_PROJECT_ID_CHARS = 80


class ChatRequest(BaseModel):
    # QUICK mode = seedhi, turant baat-cheet. Koi deep research nahi unless every
    # configured chat model is unavailable; then the route automatically falls
    # back to QUICK evidence research instead of returning a quota/server error.
    message: str = Field(..., min_length=1, max_length=_MAX_QUESTION_CHARS)
    history: Optional[List[Dict]] = None
    project_id: str = Field(default="default", min_length=1, max_length=_MAX_PROJECT_ID_CHARS)


class DeepResearchRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=_MAX_QUESTION_CHARS)
    project_id: str = Field(default="default", min_length=1, max_length=_MAX_PROJECT_ID_CHARS)
    depth_mode: str = Field(default="DEEP", min_length=1, max_length=16)  # QUICK | DEEP | MAXIMUM | MARATHON | CUSTOM
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


def _custom(request: DeepResearchRequest) -> Optional[Dict]:
    custom = {field: getattr(request, field, None) for field in _CUSTOM_FIELDS}
    custom = {k: v for k, v in custom.items() if v is not None}
    return custom or None


@router.post("/deep-research")
def deep_research(
    request: DeepResearchRequest,
    x_project_token: str | None = Header(default=None, alias="X-Project-Token"),
):
    """Deep research inside a server-issued private project namespace."""
    require_project_access(request.project_id, x_project_token)
    return manager.research(
        question=request.question,
        project_id=request.project_id,
        depth_mode=request.depth_mode,
        custom=_custom(request),
        job_id=request.project_id,
    )


def _async_research_chat_fallback(reason: object = "") -> Dict:
    """Tell capable clients to recover through the durable QUICK job route.

    Running evidence research synchronously inside ``/chat`` used the QUICK
    discovery budget (up to 45 seconds) and could cross a hosting/proxy request
    timeout.  The browser then replaced the still-running work with the same
    generic "server se baat nahi" line on every attempt.  Research jobs already
    provide bounded concurrency, progress, capability protection and durable
    results, so the client should use that path instead of duplicating it here.

    The response is also useful to older clients: it contains a human-readable
    action and no provider exception.  ``reason`` is reduced to a small enum so
    raw SDK/server text can never cross this boundary.
    """
    allowed = {
        "no_model_layer_configured",
        "all_configured_model_layers_unavailable",
    }
    safe_reason = str(reason or "").strip()
    if safe_reason not in allowed:
        safe_reason = "model_layer_unavailable"
    return {
        "answer": (
            "Chat model se jawab nahi mila, isliye source-based QUICK research "
            "background job mein chalani hogi. Official web app ise automatically "
            "start karegi aur yahin progress dikhayegi."
        ),
        "mode": "QUICK",
        "ok": True,
        "degraded": True,
        "fallback_required": True,
        "start_research_job": True,
        "research_depth_mode": "QUICK",
        "chat_fallback": "async_quick_evidence_research",
        "reason": safe_reason,
        "evidence_level": "PENDING",
        "sources": [],
    }


@router.post("/chat")
def chat(
    request: ChatRequest,
    x_project_token: str | None = Header(default=None, alias="X-Project-Token"),
):
    """QUICK chat isolated to a server-issued project capability."""
    require_project_access(request.project_id, x_project_token)
    from research_engine.chat import quick_chat

    result = quick_chat(request.message, request.history)
    if not result.get("fallback_required"):
        return result
    return _async_research_chat_fallback(result.get("reason"))


@router.get("/chat/diag")
def chat_diag():
    """Read-only, zero-call reasoning readiness report."""
    return reasoning_status()


@router.get("/depth-modes")
def depth_modes():
    """Har mode ka honest quota/limit disclosure (Spec Section 13 + 18)."""
    modes = {}
    for name in ("QUICK", "DEEP", "MAXIMUM", "MARATHON"):
        config = get_depth_config(name)
        modes[name] = {**config.to_dict(), "note": quota_note(config)}
    modes["CUSTOM"] = {
        "limits": {field: {"min": lo, "max": hi}
                   for field, (lo, hi) in depth_limits().items()},
        "flags": list(BOOL_FIELDS),
        "note": "Ye fields bhejo; values safe limits ke andar clamp ho jaati "
                "hain, taaki free quota ek hi sawal mein khatam na ho. "
                "discovery_seconds ek ROUND ki search ka wall-clock budget hai "
                "(reasoning quota nahi, sirf time/bandwidth). max_fulltext=0 "
                "matlab koi full-text download nahi, sirf abstract/snippet. "
                "red team ke liye reasoning budget >=2 chahiye — kam hone par wo "
                "apne aap band ho jaata hai aur report mein disclose hota hai.",
    }
    return modes


@router.get("/progress/{project_id}")
def get_research_progress(project_id: str, _admin: None = Depends(require_admin)):
    """Legacy project-id progress feed is server-side metadata, so admin-only.

    The public web app uses the random job-id capability endpoint instead. Keeping
    this legacy project-id feed public would let callers probe predictable IDs such
    as `default` and read another run's stage/log metadata.
    """
    return get_progress(project_id)


@router.get("/history/{project_id}")
def get_history(project_id: str, _admin: None = Depends(require_admin)):
    """Server-side research history (admin-only; never public by project id)."""
    return {"history": manager.history(project_id)}


@router.delete("/history/{project_id}")
def clear_history(project_id: str, _admin: None = Depends(require_admin)):
    """Server-side history clear karo (admin-only)."""
    removed = manager.clear_history(project_id)
    return {"message": "History clear ho gayi", "removed": removed}
