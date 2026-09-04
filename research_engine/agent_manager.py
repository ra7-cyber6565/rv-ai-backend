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

Parallel research-company integration:
    Core DeepResearchEngine ke measured result ke baad deterministic director
    packets attach hote hain. AI-1 evidence packet pehle attach hota hai; AI-1's
    source-family extension then adds capability/anatomy receipts without
    changing its exact 15 sections; AI-2 consumes that complete handoff. Every
    layer is additive and fail-closed.
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional

from .ai1_packet_extensions import extend_ai1_packet
from .ai1_research_director import attach_ai1_research_packet
from .ai1_structured_runtime import configure_ai1_structured_runtime
from .orchestrator import DeepResearchEngine
from .validation_director import attach_ai2_validation
from .validation_spec_final_guard import enforce_ai2_final_truth_guards
from .validation_spec_hardening import harden_ai2_runtime_result
from .validation_spec_quant_extension import extend_ai2_quantitative_receipts

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
                # AI-1 source-family lanes live inside the core evidence stage,
                # before contradiction/reasoning. Ordinary discovery/readers are
                # preserved; the adapter adds bounded code/dataset, dissertation,
                # official-archive and critical-source anatomy receipts.
                engine = configure_ai1_structured_runtime(engine)
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

        # Base AI-1 creates the exact 15-section evidence handoff.
        result = attach_ai1_research_packet(question, result)
        # Source-family completeness stays inside that contract: it attaches a
        # machine capability matrix and nested critical-document anatomy receipts,
        # never a 16th section and never an evidence-grade promotion.
        result = extend_ai1_packet(question, result)

        # AI-2 runs after the complete AI-1 handoff while preserving the original
        # result. It keeps plans/results distinct and fails closed to
        # INCONCLUSIVE/NOT TESTED when provenance is missing.
        result = attach_ai2_validation(question, result)

        ai2_packet = result.get("ai2_validation")
        ai2_sections = ai2_packet.get("sections") if isinstance(ai2_packet, dict) else None
        if (
            isinstance(ai2_packet, dict)
            and ai2_packet.get("title") == "AI-2 VALIDATION PACKET"
            and isinstance(ai2_sections, dict)
            and len(ai2_sections) == 17
        ):
            result = harden_ai2_runtime_result(question, result)
            result = extend_ai2_quantitative_receipts(result)
            result = enforce_ai2_final_truth_guards(result)

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
                "ai1_packet_valid": bool(
                    (result.get("ai1_research_packet") or {})
                    .get("validation", {}).get("valid")
                ),
                "ai1_source_family_extension_valid": bool(
                    (result.get("ai1_research_packet") or {})
                    .get("source_family_extension", {}).get("valid")
                ),
                "ai1_packet_confidence": (
                    (result.get("ai1_research_packet") or {})
                    .get("sections", {})
                    .get("14. Confidence in Research Packet /100", {})
                    .get("score")
                ),
                "ai2_packet_valid": bool(
                    (result.get("ai2_validation") or {})
                    .get("packet_integrity", {}).get("valid")
                ),
                "ai2_packet_confidence": (
                    (result.get("ai2_validation") or {})
                    .get("sections", {})
                    .get("16. Confidence /100", {})
                    .get("score")
                ),
                "ai2_line_by_line_audit_valid": bool(
                    (result.get("ai2_line_by_line_audit") or {}).get("valid")
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


manager = AgentManager()
