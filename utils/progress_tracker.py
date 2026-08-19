"""
Progress Tracker — real stage tracking, fake percentage NAHI.

Design rule (user ki pehle di gayi feedback): kabhi bhi banaya hua "62% done"
nahi dikhana. Yahan sirf wahi cheezein hain jo sach mein ginee ja sakti hain:
kaunsa stage chal raha hai, kitne stage poore hue, kitne sources mile, kitne
documents process hue, kitne conflicts nikle, kitne sources ka full text padha.

`stages_completed` mein duplicate nahi aate (ek hi stage do baar chal sakta hai,
jaise PROCESSING — documents ke liye aur full-text reading ke liye).
"""
from typing import Dict, List, Optional
from datetime import datetime

STAGES = [
    "QUEUED",
    "PLANNING",
    "DISCOVERING",
    "PROCESSING",          # uploaded documents
    "READING",             # sources ka legally-free full text (Spec 3/4/5)
    "EVIDENCE_ANALYSIS",
    "SPECIALIST_ANALYSIS",
    "CRITIQUE",
    "HYPOTHESIS",
    "SYNTHESIS",
    "SAFETY_CHECK",
    "COMPLETE",
]

_progress_store: Dict[str, Dict] = {}


def start_tracking(job_id: str, question: str) -> None:
    _progress_store[job_id] = {
        "job_id": job_id,
        "question": question,
        "current_stage": "QUEUED",
        "stages_completed": [],
        "stages_total": len(STAGES),
        "sources_discovered": 0,
        "documents_processed": 0,
        "evidence_conflicts_found": 0,
        "full_text_sources_read": 0,
        "gemini_calls_used": 0,
        "started_at": datetime.now().isoformat(),
        "finished_at": "",
        "log": [],
    }


def update_stage(job_id: str, stage: str, note: str = "") -> None:
    if job_id not in _progress_store:
        # Job register nahi hua (jaise seedha engine.research() call hua) —
        # tab bhi crash nahi karna, sirf chup-chaap chhod dena.
        return
    if stage not in STAGES:
        return
    entry = _progress_store[job_id]
    entry["current_stage"] = stage
    if stage not in entry["stages_completed"]:
        entry["stages_completed"].append(stage)
    entry["log"].append({
        "stage": stage,
        "note": note,
        "timestamp": datetime.now().isoformat(),
    })
    if stage == "COMPLETE":
        entry["finished_at"] = datetime.now().isoformat()


def set_counts(job_id: str,
               sources: Optional[int] = None,
               documents: Optional[int] = None,
               conflicts: Optional[int] = None,
               full_text_read: Optional[int] = None,
               gemini_calls: Optional[int] = None) -> None:
    """
    Sab counts optional hain. Naya count add karte waqt yahan naam jodna zaroori
    hai — warna caller ka kwarg TypeError deta hai aur chup-chaap gir jaata hai
    (orchestrator ke andar ye call try/except mein hai).
    """
    if job_id not in _progress_store:
        return
    entry = _progress_store[job_id]
    if sources is not None:
        entry["sources_discovered"] = sources
    if documents is not None:
        entry["documents_processed"] = documents
    if conflicts is not None:
        entry["evidence_conflicts_found"] = conflicts
    if full_text_read is not None:
        entry["full_text_sources_read"] = full_text_read
    if gemini_calls is not None:
        entry["gemini_calls_used"] = gemini_calls


def get_progress(job_id: str) -> Dict:
    entry = _progress_store.get(job_id)
    if not entry:
        return {"error": "Job not found",
                "hint": "Job id galat hai, ya research ab tak start nahi hui, "
                        "ya server restart ho gaya (progress memory mein hai)."}
    done = len(entry["stages_completed"])
    return {
        **entry,
        # Ye "percentage" nahi hai — ye asli ginti hai: kitne stage poore hue
        "stages_done": done,
        "stages_remaining": max(0, len(STAGES) - done),
    }


def active_jobs() -> List[str]:
    return sorted(_progress_store.keys())


def clear_tracking(job_id: str) -> None:
    _progress_store.pop(job_id, None)
