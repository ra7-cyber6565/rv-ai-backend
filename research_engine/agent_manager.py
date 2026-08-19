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
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional

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

    # ── research ─────────────────────────────────────────────────────────────
    def research(self, question: str, project_id: str = "default",
                 depth_mode: str = "DEEP", custom: Optional[Dict] = None,
                 job_id: Optional[str] = None) -> Dict:
        engine = self.get(project_id)
        result = engine.research(question, depth_mode=depth_mode, custom=custom,
                                 job_id=job_id or project_id)
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
