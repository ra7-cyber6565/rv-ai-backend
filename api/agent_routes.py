from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from research_engine.agent_manager import manager
from research_engine.depth import (BOOL_FIELDS, depth_limits,
                                    get_depth_config, quota_note)
from utils.admin_guard import require_admin
from utils.progress_tracker import get_progress
from utils.project_guard import require_project_access
from utils.reasoning_status import reasoning_status

router = APIRouter()


class MemoryInput(BaseModel):
    kind: str = Field(default="preference", max_length=30)
    body: Dict


class SourceCorrection(BaseModel):
    source: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=1000)


class ToolRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=40)
    arguments: Dict
    call_id: str = Field(min_length=1, max_length=80)


@router.post("/projects/{project_id}/tools/execute")
def execute_project_tool(project_id: str, request: ToolRequest,
    x_project_token: str | None = Header(default=None, alias="X-Project-Token")):
    require_project_access(project_id, x_project_token)
    from research_engine.tool_registry import execute_tool
    from utils.research_runtime import RuntimeStore, RunContext, bind, digest, code_version
    # User endpoint has a fixed server-owned role/effects; role is not accepted
    # from arbitrary input or from a generated source document.
    store = RuntimeStore()
    run = digest(["tool", project_id, request.call_id])[:32]
    limits = {"http": 0, "input_bytes": 0, "output_tokens": 0, "seconds": 3600}
    try:
        store.start(project_id, run, digest([request.tool, request.arguments]), code_version(), limits)
        with bind(RunContext(store, project_id, run)):
            return execute_tool(request.tool, request.arguments, role="supervisor",
                allowed_effects={"bounded_calculation", "return_artifact"}, call_id=request.call_id)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail="Tool arguments or permissions invalid.") from exc


@router.get("/projects/{project_id}/research-memory")
def inspect_research_memory(project_id: str,
    x_project_token: str | None = Header(default=None, alias="X-Project-Token")):
    require_project_access(project_id, x_project_token)
    from utils.governed_memory import GovernedMemory
    return GovernedMemory().inspect(project_id)


@router.post("/projects/{project_id}/research-memory")
def add_research_memory(project_id: str, request: MemoryInput,
    x_project_token: str | None = Header(default=None, alias="X-Project-Token")):
    require_project_access(project_id, x_project_token)
    from utils.governed_memory import GovernedMemory
    try:
        return {"id": GovernedMemory().put(project_id, request.kind, request.body, user_supplied=True)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Memory kind, size or limit invalid.") from exc


@router.delete("/projects/{project_id}/research-memory/{record_id}")
def delete_research_memory(project_id: str, record_id: str,
    x_project_token: str | None = Header(default=None, alias="X-Project-Token")):
    require_project_access(project_id, x_project_token)
    from utils.research_jobs import runner
    if runner.has_active(project_id):
        raise HTTPException(status_code=409, detail="Pehle active research ko roko; phir memory delete karo.")
    from utils.governed_memory import GovernedMemory
    removed = GovernedMemory().delete(project_id, record_id)
    manager.drop(project_id)
    return {"deleted": removed, "scope": "governed record and dependent runtime checkpoints",
            "retained": "original uploaded documents, legacy memory files, job archives and external backups; not an account-wide erasure"}


@router.post("/projects/{project_id}/source-corrections")
def correct_research_source(project_id: str, request: SourceCorrection,
    x_project_token: str | None = Header(default=None, alias="X-Project-Token")):
    require_project_access(project_id, x_project_token)
    from utils.governed_memory import GovernedMemory
    result = GovernedMemory().invalidate_source(project_id, request.source, request.reason)
    manager.drop(project_id)
    return result

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
    for name in ("QUICK", "DEEP", "MAXIMUM", "MARATHON", "COMPANY", "COMPANY_PLUS"):
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
