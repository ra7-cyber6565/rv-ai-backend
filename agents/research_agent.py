"""
agents/research_agent.py — BACKWARDS-COMPATIBLE SHIM

Asli research logic ab research_engine/ package mein hai (Spec Section 16 ka
modular architecture). Ye file sirf isliye zinda hai ki purane callers na tootein:

    api/agent_routes.py     ->  from agents.research_agent import ResearchAgent
    agents/__init__.py      ->  from .research_agent import ResearchAgent
    Android app             ->  /deep-research ka JSON shape same rehta hai

Response ke purane 8 keys (question, answer, sources, safety_flags,
evidence_level, mode, question_types, relevant_fields) waise hi aate hain;
naye keys (citations, contradictions, hypotheses, verification, coverage,
warnings, gemini_calls_used) extra add hue hain — purane clients unhe ignore
kar denge.

Purane version se 3 asli farq:
    1. External discovery HAMESHA chalti hai — pehle wo `if not retrieval
       ["context"]` ke peeche chhupi thi, yani PDF hone par internet/academic
       search band ho jaati thi.
    2. Citations substring-URL match se nahi, [S#] IDs se verify hoti hain.
    3. Contradictions, verification aur coverage Gemini se nahi, local engines
       se aate hain — isliye quota khatam hone par bhi wo sach rehte hain.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from research_engine.agent_manager import manager
from research_engine.planner import classify_question  # noqa: F401 (purana re-export)

VALID_MODES = ("QUICK", "DEEP", "MAXIMUM", "CUSTOM")


class ResearchAgent:
    """Thin wrapper — poora kaam research_engine.DeepResearchEngine karta hai."""

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id or "default"

    # ── main ─────────────────────────────────────────────────────────────────
    def research(self, question: str, depth_mode: str = "DEEP",
                 custom: Optional[Dict] = None) -> Dict:
        mode = (depth_mode or "DEEP").upper()
        if mode not in VALID_MODES:
            mode = "DEEP"

        try:
            from utils.progress_tracker import start_tracking
            start_tracking(self.project_id, question)
        except Exception:
            pass

        return manager.research(question=question, project_id=self.project_id,
                                depth_mode=mode, custom=custom,
                                job_id=self.project_id)

    # ── history (ab AgentManager ke paas hai) ────────────────────────────────
    @property
    def history(self) -> List[Dict]:
        return manager.history(self.project_id)

    def get_history(self) -> List[Dict]:
        return manager.history(self.project_id)

    def clear_history(self) -> None:
        manager.clear_history(self.project_id)

    # ── naya engine seedha chahiye to ────────────────────────────────────────
    @property
    def engine(self):
        return manager.get(self.project_id)
