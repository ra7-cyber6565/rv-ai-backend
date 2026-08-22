"""
ResearchMemory — Spec Section 16 (research_memory.py)

Har project ka apna JSON file. Isme wo cheezein rakhi jaati hain jo agli baar
kaam aayengi:
    * past research runs (sawal, evidence level, kitne sources)
    * hypotheses aur unka status (UNTESTED / SUPPORTED_LATER / REJECTED)
    * dead ends — kaun sa approach ya query kaam nahi karti
    * seen source URLs — dobara wahi source discovery mein na aaye

Deliberately simple: file-based JSON, koi paid DB/service nahi. Runtime path
``RESEARCH_MEMORY_DIR`` se aata hai; main.py ise INFINITY_DATA_ROOT ke andar
set karta hai, taaki laptop par memory files project folder/C: ko na bharen.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from typing import Dict, List, Optional


def _default_dir() -> str:
    configured = str(os.getenv("RESEARCH_MEMORY_DIR", "")).strip()
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    # Standalone/test import ke liye centralized fallback use karo.
    try:
        from utils.storage_paths import ensure_layout
        return ensure_layout()["research_memory"]
    except Exception:
        return os.path.abspath("./research_memory")


_MAX_RUNS = 50
_MAX_URLS = 400
_MAX_DISCOVERIES = 50
_STOP = {"kya", "hai", "the", "ka", "ki", "ke", "se", "mein", "aur", "what", "is",
         "of", "and", "the", "how", "why", "does", "do", "a", "an", "for", "in", "to"}


def _words(text: str) -> set:
    return {w for w in re.findall(r"[\w']+", (text or "").lower())
            if len(w) > 2 and w not in _STOP}


class ResearchMemory:
    def __init__(self, project_id: str = "default", directory: Optional[str] = None):
        self.project_id = project_id or "default"
        self.directory = os.path.abspath(directory or _default_dir())
        self._data: Optional[Dict] = None

    # ── storage ──────────────────────────────────────────────────────────────
    @property
    def path(self) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", self.project_id)
        return os.path.join(self.directory, f"{safe}.json")

    def _blank(self) -> Dict:
        return {"project_id": self.project_id, "runs": [], "hypotheses": [],
                "discoveries": [], "dead_ends": [], "seen_urls": []}

    def load(self) -> Dict:
        if self._data is not None:
            return self._data
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("research memory root must be an object")
            for key, default in self._blank().items():
                if key not in data or not isinstance(data[key], type(default)):
                    data[key] = default
            self._data = data
        except Exception:
            # File nahi hai ya corrupt hai — memory se research nahi rukni chahiye
            self._data = self._blank()
        return self._data

    def save(self) -> bool:
        data = self.load()
        data["runs"] = data["runs"][-_MAX_RUNS:]
        data["seen_urls"] = data["seen_urls"][-_MAX_URLS:]
        data["discoveries"] = list(data.get("discoveries") or [])[-_MAX_DISCOVERIES:]
        try:
            os.makedirs(self.directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="memory_", suffix=".json", dir=self.directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
            return True
        except Exception:
            return False

    # ── writes ───────────────────────────────────────────────────────────────
    def remember_run(self, question: str, evidence_level: str, source_count: int,
                     mode: str, connectors: Optional[List[str]] = None,
                     summary: str = "") -> None:
        self.load()["runs"].append({
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "question": question,
            "evidence_level": evidence_level,
            "source_count": source_count,
            "mode": mode,
            "connectors": connectors or [],
            "summary": (summary or "")[:400],
        })

    def remember_hypotheses(self, question: str, hypotheses: List[Dict]) -> None:
        store = self.load()["hypotheses"]
        existing = {h.get("statement", "")[:120] for h in store}
        for h in hypotheses:
            statement = h.get("statement", "")
            if not statement or statement[:120] in existing:
                continue
            store.append({
                "at": time.strftime("%Y-%m-%d"),
                "question": question,
                "statement": statement,
                "how_to_test": h.get("how_to_test", ""),
                "status": h.get("status", "UNTESTED HYPOTHESIS"),
            })

    def remember_discovery(self, question: str, discovery: Dict) -> None:
        """Store a compact discovery checkpoint, never the full evidence graph."""
        if not isinstance(discovery, dict):
            return
        tournament = discovery.get("tournament") or {}
        reality = discovery.get("reality_ladder") or {}
        weakest = discovery.get("weakest_link") or {}
        record = {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "question": (question or "")[:500],
            "status": str(discovery.get("status") or "")[:80],
            "winner": str(tournament.get("winner") or "")[:40],
            "reality_level": reality.get("level"),
            "weakest_link": str(weakest.get("key") or "")[:80],
        }
        store = self.load().setdefault("discoveries", [])
        if store and all(store[-1].get(key) == record.get(key)
                         for key in ("question", "status", "winner",
                                     "reality_level", "weakest_link")):
            return
        store.append(record)

    def remember_dead_end(self, what: str, why: str) -> None:
        store = self.load()["dead_ends"]
        if any(d.get("what") == what for d in store):
            return
        store.append({"at": time.strftime("%Y-%m-%d"), "what": what, "why": why})

    def remember_urls(self, urls: List[str]) -> None:
        store = self.load()["seen_urls"]
        known = set(store)
        for url in urls:
            key = (url or "").strip().rstrip("/").lower()
            if key and key not in known:
                known.add(key)
                store.append(key)

    # ── reads ────────────────────────────────────────────────────────────────
    def recall_related(self, question: str, limit: int = 3) -> List[Dict]:
        """Purane runs jo is sawal se milte-julte hain (keyword overlap)."""
        target = _words(question)
        if not target:
            return []
        scored = []
        for run in self.load()["runs"]:
            overlap = len(target & _words(run.get("question", "")))
            if overlap >= 2:
                scored.append((overlap, run))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [run for _, run in scored[:limit]]

    def known_hypotheses(self, question: str, limit: int = 3) -> List[Dict]:
        target = _words(question)
        out = []
        for h in self.load()["hypotheses"]:
            if len(target & _words(h.get("question", "") + " " + h.get("statement", ""))) >= 2:
                out.append(h)
        return out[-limit:]

    def recall_discoveries(self, question: str, limit: int = 3) -> List[Dict]:
        target = _words(question)
        if not target:
            return []
        scored = []
        for item in self.load().get("discoveries", []):
            overlap = len(target & _words(item.get("question", "")))
            if overlap >= 2:
                scored.append((overlap, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def dead_ends(self) -> List[Dict]:
        return list(self.load()["dead_ends"])

    def seen_urls(self) -> set:
        return set(self.load()["seen_urls"])

    def context_note(self, question: str) -> str:
        """Prompt mein daalne layak chhota note — pichhli baar kya hua tha."""
        runs = self.recall_related(question)
        hyps = self.known_hypotheses(question)
        discoveries = self.recall_discoveries(question)
        dead = self.related_dead_ends(question)
        if not runs and not hyps and not discoveries and not dead:
            return ""
        lines = ["PICHHLI RESEARCH (isi project se):"]
        for run in runs:
            lines.append(
                f"  - {run.get('at', 'kabhi')}: \"{(run.get('question') or '')[:90]}\" → "
                f"evidence {run.get('evidence_level', 'pata nahi')}, "
                f"{run.get('source_count', 0)} sources")
        for h in hyps:
            lines.append(f"  - purani hypothesis ({h.get('status', 'UNTESTED')}): "
                         f"{(h.get('statement') or '')[:110]}")
        for item in discoveries:
            lines.append(
                f"  - discovery checkpoint: status {item.get('status') or 'unknown'}, "
                f"reality level {item.get('reality_level', 'unknown')}, "
                f"weakest link {item.get('weakest_link') or 'not assessed'}")
        for d in dead:
            lines.append(f"  - pehle kaam nahi aaya: {(d.get('what') or '')[:60]} "
                         f"({(d.get('why') or '')[:70]})")
        lines.append("  (Ise dohraane ki zaroorat nahi — isse aage badho.)")
        return "\n".join(lines)

    def related_dead_ends(self, question: str, limit: int = 3) -> List[Dict]:
        """Is sawal se milte-julte dead ends (keyword overlap)."""
        target = _words(question)
        if not target:
            return []
        out = []
        for d in self.load()["dead_ends"]:
            if len(target & _words(f"{d.get('what', '')} {d.get('why', '')}")) >= 1:
                out.append(d)
        return out[-limit:]

    def clear(self) -> bool:
        self._data = self._blank()
        return self.save()
