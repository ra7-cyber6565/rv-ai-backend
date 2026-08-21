from typing import Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from research_engine.agent_manager import manager
from research_engine.depth import (BOOL_FIELDS, depth_limits,
                                    get_depth_config, quota_note)
from utils.admin_guard import require_admin
from utils.progress_tracker import get_progress
from utils.reasoning_status import reasoning_status

router = APIRouter()


class ChatRequest(BaseModel):
    # QUICK mode = seedhi, turant baat-cheet. Koi deep research nahi unless every
    # configured chat model is unavailable; then the route automatically falls
    # back to QUICK evidence research instead of returning a quota/server error.
    message: str
    history: Optional[List[Dict]] = None
    project_id: str = "default"


class DeepResearchRequest(BaseModel):
    question: str
    project_id: str = "default"
    depth_mode: str = "DEEP"          # QUICK | DEEP | MAXIMUM | CUSTOM
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


def _custom(request: DeepResearchRequest) -> Optional[Dict]:
    custom = {field: getattr(request, field, None) for field in _CUSTOM_FIELDS}
    custom = {k: v for k, v in custom.items() if v is not None}
    return custom or None


@router.post("/deep-research")
def deep_research(request: DeepResearchRequest):
    """Deep multi-step research with bounded CUSTOM controls."""
    return manager.research(
        question=request.question,
        project_id=request.project_id,
        depth_mode=request.depth_mode,
        custom=_custom(request),
        job_id=request.project_id,
    )


def _safe_research_chat_fallback(request: ChatRequest) -> Dict:
    """Last route-level fallback after every configured chat model fails.

    QUICK research can still search/read public evidence and ultimately use the
    deterministic evidence reasoner, so a hosted-model quota outage does not turn
    the chat endpoint into an HTTP/provider error. Unexpected research-engine
    exceptions are converted to one safe degraded response; raw exception text is
    never returned to the client.
    """
    try:
        result = manager.research(
            question=request.message,
            project_id=request.project_id,
            depth_mode="QUICK",
            job_id=request.project_id,
        )
        if not isinstance(result, dict):
            raise RuntimeError("research result was not a mapping")
        answer = str(result.get("answer") or "").strip()
        if not answer:
            raise RuntimeError("research result had no answer")
        # Preserve research evidence/audit fields. Add compatibility fields used
        # by the normal chat UI without pretending this was a normal model pass.
        result["ok"] = True
        result["degraded"] = True
        result["mode"] = result.get("mode") or "QUICK"
        result["chat_fallback"] = "quick_evidence_research"
        return result
    except Exception:
        return {
            "answer": (
                "Is sawal ka reliable jawab is run mein establish nahi ho saka. "
                "Koi raw provider/server error dikhane ya guess karne ke bajay app ne "
                "safe fallback use kiya. Deep/Maximum mode ya uploaded source ke saath "
                "dobara chalane par zyada evidence mil sakta hai."
            ),
            "mode": "QUICK",
            "ok": True,
            "degraded": True,
            "chat_fallback": "safe_local_failure_message",
            "evidence_level": "UNKNOWN",
            "sources": [],
        }


@router.post("/chat")
def chat(request: ChatRequest):
    """QUICK chat with zero-cost provider failover and evidence fallback.

    Normal path:
        deterministic trivial-chat reply (0 API calls), or
        confirmed Gemini -> confirmed Groq free -> OpenRouter free-only ->
        localhost Ollama.

    If every configured model layer is unavailable, the same message is sent to
    QUICK research. That path can retrieve evidence and has its own deterministic
    evidence-only last resort, so a Gemini quota outage no longer means the chat
    endpoint simply stops working.
    """
    from research_engine.chat import quick_chat

    result = quick_chat(request.message, request.history)
    if not result.get("fallback_required"):
        return result
    return _safe_research_chat_fallback(request)


@router.get("/chat/diag")
def chat_diag():
    """Read-only, zero-call reasoning readiness report.

    The old diagnostic endpoint performed a real `Say OK` Gemini generation on
    every request, which consumed quota just to diagnose quota. This endpoint now
    makes **zero provider calls** and exposes only non-secret configuration/policy
    readiness. Live quota/reachability is learned naturally when a real user
    request runs through the resilient router.
    """
    return reasoning_status()


@router.get("/depth-modes")
def depth_modes():
    """Har mode ka honest quota/limit disclosure (Spec Section 13 + 18)."""
    modes = {}
    for name in ("QUICK", "DEEP", "MAXIMUM"):
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
def get_research_progress(project_id: str):
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
