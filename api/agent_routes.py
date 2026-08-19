from typing import Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from research_engine.agent_manager import manager
from research_engine.depth import (BOOL_FIELDS, depth_limits,
                                    get_depth_config, quota_note)
from utils.progress_tracker import get_progress

router = APIRouter()


class DeepResearchRequest(BaseModel):
    question: str
    project_id: str = "default"
    depth_mode: str = "DEEP"          # QUICK | DEEP | MAXIMUM | CUSTOM
    # CUSTOM ke liye (Spec Section 13 — "user khud source count / depth / TIME
    # tay kar sake"). QUICK/DEEP/MAXIMUM mein ye ignore hote hain.
    #
    # Pehle sirf teen fields yahan thi (max_sources / max_rounds / gemini_calls),
    # jabki depth.py ke andar saat knobs clamp hote the — yaani "time" aur
    # "full text kitna padhna hai" API se pahunche hi nahi ja sakte the. Spec
    # ka CUSTOM mode utna hi tha jitna request model expose karta hai, isliye
    # baaki knobs bhi yahan hain.
    max_sources: Optional[int] = None
    max_rounds: Optional[int] = None
    gemini_calls: Optional[int] = None
    max_per_connector: Optional[int] = None
    chars_per_source: Optional[int] = None
    max_fulltext: Optional[int] = None          # 0 = koi full-text download nahi
    discovery_seconds: Optional[int] = None     # ek round ki search ka time budget
    use_papers: Optional[bool] = None
    use_books: Optional[bool] = None
    use_datasets: Optional[bool] = None         # Spec §2 + §11 — public datasets
    use_red_team: Optional[bool] = None


# jo keys CUSTOM mode mein aage bheji jaati hain (depth.py inhe clamp karta hai)
_CUSTOM_FIELDS = tuple(depth_limits()) + BOOL_FIELDS


def _custom(request: DeepResearchRequest) -> Optional[Dict]:
    custom = {field: getattr(request, field, None) for field in _CUSTOM_FIELDS}
    custom = {k: v for k, v in custom.items() if v is not None}
    return custom or None


@router.post("/deep-research")
def deep_research(request: DeepResearchRequest):
    """
    Deep multi-step research.

    depth_mode:
        QUICK    1 Gemini call,  ~5 sources,  1 round
        DEEP     2 Gemini calls, ~10 sources, 2 rounds  (default)
        MAXIMUM  3 Gemini calls, ~18 sources, 3 rounds
        CUSTOM   apne numbers bhejo — max_sources, max_rounds, gemini_calls,
                 max_per_connector, chars_per_source, max_fulltext,
                 discovery_seconds, use_papers, use_books, use_datasets,
                 use_red_team
                 (sab safe limits mein clamp hote hain; /depth-modes par
                 har limit likhi hai)

    Document retrieval aur external discovery DONO hamesha chalti hain —
    PDF upload hone par internet/academic search band nahi hoti.
    """
    return manager.research(
        question=request.question,
        project_id=request.project_id,
        depth_mode=request.depth_mode,
        custom=_custom(request),
        job_id=request.project_id,
    )


@router.get("/depth-modes")
def depth_modes():
    """Har mode ka honest quota/limit disclosure (Spec Section 13 + 18)."""
    modes = {}
    for name in ("QUICK", "DEEP", "MAXIMUM"):
        config = get_depth_config(name)
        modes[name] = {**config.to_dict(), "note": quota_note(config)}
    modes["CUSTOM"] = {
        # limits code se hi padhte hain — warna doc aur asli clamp alag ho
        # jaate hain aur disclosure jhooth ban jaata hai
        "limits": {field: {"min": lo, "max": hi}
                   for field, (lo, hi) in depth_limits().items()},
        "flags": list(BOOL_FIELDS),
        "note": "Ye fields bhejo; values safe limits ke andar clamp ho jaati "
                "hain, taaki free quota ek hi sawal mein khatam na ho. "
                "discovery_seconds ek ROUND ki search ka wall-clock budget hai "
                "(Gemini quota nahi, sirf time/bandwidth). max_fulltext=0 "
                "matlab koi full-text download nahi, sirf abstract/snippet. "
                "red team ke liye gemini_calls>=2 chahiye — kam hone par wo "
                "apne aap band ho jaata hai (chup-chaap nahi, report mein "
                "likha jaata hai).",
    }
    return modes


@router.get("/progress/{project_id}")
def get_research_progress(project_id: str):
    """Research progress dekho — stages, sources discovered, log"""
    return get_progress(project_id)


@router.get("/history/{project_id}")
def get_history(project_id: str):
    """Research history dekho"""
    return {"history": manager.history(project_id)}


@router.delete("/history/{project_id}")
def clear_history(project_id: str):
    """History clear karo"""
    removed = manager.clear_history(project_id)
    return {"message": "History clear ho gayi", "removed": removed}
