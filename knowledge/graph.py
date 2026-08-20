"""
Knowledge Graph — Spec Section 16 (hint layer, EVIDENCE layer nahi)

Entities aur sentence-level co-occurrence links JSON mein store hote hain. Ye
verified evidence nahi hain; relationships hamesha ``verified: False`` rehti hain.
Runtime file ``KNOWLEDGE_GRAPH_FILE`` se aati hai. main.py ise centralized
INFINITY_DATA_ROOT ke ``knowledge`` folder mein set karta hai taaki laptop ki
system drive/repository silently na bhare.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from typing import Dict, List


def _default_graph_file() -> str:
    configured = str(os.getenv("KNOWLEDGE_GRAPH_FILE", "")).strip()
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    try:
        from utils.storage_paths import ensure_layout
        return os.path.join(ensure_layout()["knowledge"], "knowledge_graph.json")
    except Exception:
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "knowledge_graph.json",
        )


GRAPH_FILE = _default_graph_file()

_RELATION_NOTE = ("same sentence mein saath aaye — ye sirf co-occurrence hint hai, "
                  "proven rishta nahi")


def _blank_graph() -> Dict:
    return {"entities": [], "relationships": [], "research_log": []}


def _load_graph() -> Dict:
    """Corrupt/missing/purani file par blank graph mile; research crash na ho."""
    try:
        if not os.path.exists(GRAPH_FILE):
            return _blank_graph()
        with open(GRAPH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _blank_graph()
        for key, default in _blank_graph().items():
            value = data.get(key)
            data[key] = value if isinstance(value, list) else default
        return data
    except Exception:
        return _blank_graph()


def _save_graph(graph: Dict) -> bool:
    """Atomic save: half-written JSON ko final file kabhi replace nahi karega."""
    try:
        directory = os.path.dirname(GRAPH_FILE)
        if directory:
            os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="knowledge_graph_", suffix=".json", dir=directory or None)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(graph, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, GRAPH_FILE)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return True
    except Exception:
        return False


def extract_entities_nlp(text: str) -> List[Dict]:
    """Regex-based entity hints — Hindi-English mix content ke liye."""
    clean_text = re.sub(r'\*\*|##|\*|_', '', text or "")

    stopwords = {"Unke", "Unki", "Unka", "Ye", "Yeh", "Is", "Iske", "Uske", "Wo", "Woh",
                 "Hai", "The", "This", "That", "It", "He", "She", "They", "Note", "Source",
                 "Web", "Parichay", "Janam Sthan", "Sthan", "Aur", "Unhe Rajasthan",
                 "Balidaan", "Swari", "Ghodi"}

    words = re.findall(r'\b[A-Z][a-zA-Z]{2,}(?:\s[A-Z][a-zA-Z]{2,})?\b', clean_text)
    entities = []
    seen = set()

    for w in words:
        w = w.strip()
        if w in stopwords or w in seen or len(w) < 3:
            continue
        entities.append({"name": w, "type": "ENTITY"})
        seen.add(w)

    return entities[:15]


def extract_relationships(text: str, entities: List[Dict]) -> List[Dict]:
    """Sentence-level co-occurrence hints, proven relationships nahi."""
    if len(entities) < 2:
        return []

    sentences = re.split(r'[।.!?]\s*', text or "")
    entity_names = [e.get("name", "") for e in entities if e.get("name")]
    relationships = []

    for sent in sentences:
        present = [name for name in entity_names if name in sent]
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                relationships.append({
                    "from": present[i],
                    "relation": "co_occurs_with",
                    "to": present[j],
                    "context": sent.strip()[:150],
                    "verified": False,
                    "evidence": _RELATION_NOTE,
                })

    return relationships[:15]


def extract_and_store(question: str, answer_text: str, project_id: str = "default") -> Dict:
    """Free/local knowledge-graph hint extraction + persistence."""
    graph = _load_graph()
    project_id = project_id or "default"

    graph["research_log"].append({
        "question": question,
        "answer_summary": (answer_text or "")[:500],
        "project_id": project_id,
    })

    entities = extract_entities_nlp(answer_text)
    relationships = extract_relationships(answer_text, entities)

    for entity in entities:
        existing = next(
            (e for e in graph["entities"]
             if e.get("name") == entity["name"] and e.get("project_id") == project_id),
            None,
        )
        if existing:
            existing["mention_count"] = int(existing.get("mention_count", 0)) + 1
        else:
            graph["entities"].append({
                "name": entity["name"],
                "type": entity.get("type", "ENTITY"),
                "project_id": project_id,
                "mention_count": 1,
                "first_seen_question": question,
            })

    for rel in relationships:
        rel["project_id"] = project_id
        graph["relationships"].append(rel)

    saved = _save_graph(graph)
    return {
        "entities_found": len(entities),
        "relationships_found": len(relationships),
        "saved": saved,
        "graph_file": GRAPH_FILE,
        "note": _RELATION_NOTE,
    }


def get_related_knowledge(question: str, project_id: str = "default") -> str:
    """Pichhle research se related context dhoondo (hint, evidence nahi)."""
    graph = _load_graph()
    q_lower = (question or "").lower()
    related_logs = [
        log for log in graph["research_log"]
        if log.get("project_id") == project_id and any(
            word.lower() in q_lower
            for word in (log.get("question") or "").split() if len(word) > 3
        )
    ]
    if not related_logs:
        return ""
    lines = [f"Pehle poocha gaya: '{log.get('question', '')}' — "
             f"{(log.get('answer_summary') or '')[:150]}..."
             for log in related_logs[-3:]]
    return "Pichhle related research:\n" + "\n".join(lines)


def get_entity_stats(project_id: str = "default") -> Dict:
    """Kaun si entities sabse zyada mention hui."""
    graph = _load_graph()
    project_entities = [e for e in graph["entities"] if e.get("project_id") == project_id]
    sorted_entities = sorted(project_entities,
                             key=lambda x: int(x.get("mention_count", 0)), reverse=True)
    return {"top_entities": sorted_entities[:10], "total_entities": len(project_entities)}


def get_entity_graph(project_id: str = "default") -> Dict:
    """Poora Knowledge Graph structure (hint layer)."""
    graph = _load_graph()
    project_relationships = [r for r in graph["relationships"]
                             if r.get("project_id") == project_id]
    project_entities = [e for e in graph["entities"] if e.get("project_id") == project_id]

    return {
        "entities": project_entities,
        "relationships": project_relationships,
        "total_entities": len(project_entities),
        "total_relationships": len(project_relationships),
        "graph_file": GRAPH_FILE,
        "honesty_note": ("Relationships sirf co-occurrence hints hain (ek hi sentence "
                         "mein saath aaye). Ye verified rishte nahi hain aur inhe "
                         "citation ki tarah use nahi kiya jaata."),
    }
