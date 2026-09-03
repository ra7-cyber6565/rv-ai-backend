"""
AgentManager — Spec Section 16 (agent_manager.py)

Purane code mein api/agent_routes.py ke andar ek module-level dict tha:
    _agents = {}
    def get_agent(project_id): ...

Wahi kaam ab yahan hai, do sudhaar ke saath:
    1. THREAD-SAFE — FastAPI ke worker threads ek hi project pe saath aa sakte
       hain; dict ko lock ke andar rakha hai.
    2. HISTORY yahan rehti hai (engine stateless rehta hai) — isse ek hi project
       ke do parallel sawal ek dusre ki history corrupt nahi karte.

AI-1 integration:
    DeepResearchEngine ka measured result return hote hi deterministic AI-1
    Research & Evidence Director packet attach hota hai. Isse /deep-research,
    background jobs aur purana ResearchAgent shim sab ek hi structured handoff
    paate hain. Packet existing evidence gates ko replace nahi karta; unhi ke
    outputs ko fail-closed research-company handoff mein organize karta hai.
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional

from .ai1_research_director import attach_ai1_research_packet
from .orchestrator import DeepResearchEngine

_MAX_HISTORY = 30


class AgentManager:
    def __init__(self):
        self._engines: Dict[str, DeepResearchEngine] = {}
        self._history: Dict[str, List[Dict]] = {}
        self._lock = threading.Lock()

    # ── engines ──────────────────────────────────────────────────────────────
    def get(self, project_id: str = "default") -> DeepResearchEngine:
        project_id = project_id or "default"
        with self._lock:
            engine = self._engines.get(project_id)
            if engine is None:
                engine = DeepResearchEngine(project_id=project_id)
                self._engines[project_id] = engine
            return engine

    def drop(self, project_id: str) -> bool:
        with self._lock:
            self._history.pop(project_id, None)
            return self._engines.pop(project_id, None) is not None

    def projects(self) -> List[str]:
        with self._lock:
            return sorted(self._engines)

    # ── research ──────────────────────────────────────────────────────────────
    def research(self, question: str, project_id: str = "default",
                 depth_mode: str = "DEEP", custom: Optional[Dict] = None,
                 job_id: Optional[str] = None) -> Dict:
        engine = self.get(project_id)
        result = engine.research(question, depth_mode=depth_mode, custom=custom,
                                 job_id=job_id or project_id)
        # AI-1 is deliberately attached AFTER the core engine has finished its
        # own citation/A-E/relevance/contradiction/source-integrity checks.  It
        # therefore cannot create evidence or upgrade a claim; it can only
        # expose, decompose, route, or mark what the measured run actually has.
        result = attach_ai1_research_packet(question, result)
        self._remember(project_id, result)
        return result

    def _remember(self, project_id: str, result: Dict) -> None:
        with self._lock:
            history = self._history.setdefault(project_id, [])
            history.append({
                "question": result.get("question", ""),
                "answer": result.get("answer", ""),
                "evidence_level": result.get("evidence_level", ""),
                "mode": result.get("mode", ""),
                "source_count": len(result.get("sources", [])),
                "gemini_calls_used": result.get("gemini_calls_used", 0),
                # History stays compact: only packet status/score, never the
                # whole evidence packet or copied source metadata.
                "ai1_packet_valid": bool(
                    (result.get("ai1_research_packet") or {})
                    .get("validation", {}).get("valid")
                ),
                "ai1_packet_confidence": (
                    (result.get("ai1_research_packet") or {})
                    .get("sections", {})
                    .get("14. Confidence in Research Packet /100", {})
                    .get("score")
                ),
            })
            if len(history) > _MAX_HISTORY:
                del history[:-_MAX_HISTORY]

    # ── history ──────────────────────────────────────────────────────────────
    def history(self, project_id: str = "default") -> List[Dict]:
        with self._lock:
            return list(self._history.get(project_id, []))

    def clear_history(self, project_id: str = "default") -> int:
        with self._lock:
            count = len(self._history.get(project_id, []))
            self._history[project_id] = []
            return count


# Process-wide single instance (routes isi ko import karti hain)
manager = AgentManager()
