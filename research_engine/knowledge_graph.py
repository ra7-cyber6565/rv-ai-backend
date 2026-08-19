"""
KnowledgeGraphAdapter — Spec Section 16 (knowledge_graph.py)

Project mein already knowledge/graph.py hai (entities + relationships, JSON file).

IMPORTANT — pehle ke testing se pata chala: spaCy ka en_core_web_sm Hinglish text
par bharosemand nahi hai (usne "mein hua tha" ko PERSON tag kar diya tha).
Isliye is adapter ka rule:

    Knowledge graph = HINT layer, EVIDENCE layer nahi.

Iska output kabhi citation ya evidence ki tarah use nahi hoga; sirf ye batane ke
liye ki "is project mein pehle ye entities dekhi gayi thi". Aur graph fail ho
jaaye to research bilkul nahi rukti.
"""
from __future__ import annotations

from typing import Dict, List, Optional

_LOW_CONFIDENCE_NOTE = (
    "(knowledge graph hint hai, evidence nahi — entity extraction Hinglish par "
    "kamzor hai, isliye ise cite nahi kiya jaata)"
)


class KnowledgeGraphAdapter:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._graph = None
        self.last_error: str = ""

    def _module(self):
        if self._graph is None:
            from knowledge import graph  # lazy
            self._graph = graph
        return self._graph

    @property
    def available(self) -> bool:
        if not self.enabled:
            return False
        try:
            self._module()
            return True
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False

    # ── read ─────────────────────────────────────────────────────────────────
    def related_note(self, question: str, project_id: str = "default") -> str:
        """Prompt mein daalne layak hint block. Fail ho to khaali string."""
        if not self.enabled:
            return ""
        try:
            related = self._module().get_related_knowledge(question, project_id)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return ""
        related = (related or "").strip()
        if not related:
            return ""
        return f"PROJECT KNOWLEDGE GRAPH HINT {_LOW_CONFIDENCE_NOTE}:\n{related}"

    def stats(self, project_id: str = "default") -> Dict:
        if not self.enabled:
            return {}
        try:
            return self._module().get_entity_stats(project_id) or {}
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return {}

    # ── write ────────────────────────────────────────────────────────────────
    def store(self, question: str, answer: str, project_id: str = "default") -> bool:
        """Answer se entities nikaal kar graph mein daalo. Best-effort."""
        if not self.enabled or not (answer or "").strip():
            return False
        try:
            self._module().extract_and_store(question, answer, project_id)
            return True
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False
