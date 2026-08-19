"""
Knowledge Graph — Spec Section 16 (hint layer, EVIDENCE layer nahi)

Ye file entities aur unke beech ke co-occurrence links ek JSON file mein rakhti
hai. Do imaandaari ke rules yahan code mein baandhe gaye hain:

  1. Relationship "co_occurs_with" hai, "related_to" nahi, aur har relationship
     par `verified: False` likha rehta hai. Wajah: detection sirf itna dekhta hai
     ki do naam EK HI sentence mein aaye — isse causation ya rishta sabit nahi
     hota. Isi liye KnowledgeGraphAdapter iska output kabhi cite nahi karta.

  2. Entity extraction regex-based hai (spaCy ka en_core_web_sm Hinglish par
     galat tag karta hai — wo dead end memory mein documented hai).

Do defects yahan theek kiye gaye the:
  * GRAPH_FILE relative tha ("knowledge_graph.json"), yani file wahan banti thi
    jahan se server start hua tha. Directory badalne par poora graph "gayab" ho
    jaata tha. Ab path backend folder se anchor hota hai (env se override ho
    sakta hai).
  * Har dict access `e["project_id"]` jaisa tha. Purani ya haath se edit ki hui
    graph file par ye KeyError deta tha, aur adapter ke try/except mein wo
    chup-chaap ghum jaata tha — matlab feature bina bataye band. Ab sab .get()
    se padha jaata hai aur corrupt file par blank graph se kaam chalta hai.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List

# CWD par bharosa nahi — file hamesha backend/ ke andar (ya env se di gayi jagah)
_DEFAULT_GRAPH_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge_graph.json",
)
GRAPH_FILE = os.getenv("KNOWLEDGE_GRAPH_FILE", _DEFAULT_GRAPH_FILE)

_RELATION_NOTE = ("same sentence mein saath aaye — ye sirf co-occurrence hint hai, "
                  "proven rishta nahi")


def _blank_graph() -> Dict:
    return {"entities": [], "relationships": [], "research_log": []}


def _load_graph() -> Dict:
    """Corrupt/missing/purani file par bhi kaam karta hai — kabhi raise nahi karta."""
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
    try:
        directory = os.path.dirname(GRAPH_FILE)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(GRAPH_FILE, "w", encoding="utf-8") as f:
            json.dump(graph, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def extract_entities_nlp(text: str) -> List[Dict]:
    """
    Regex-based entity extraction — Hindi-English mix content ke liye.
    Markdown formatting hataata hai, phir capitalized-word pattern use karta hai.
    """
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
    """
    Sentence-level co-occurrence. Naam jaan-boojh kar "co_occurs_with" hai:
    ek sentence mein saath dikhna rishta nahi sabit karta, isliye ye layer
    hint hai aur `verified: False` ke saath store hoti hai.
    """
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
                    # Spec Section 7/17: hint ko evidence ki tarah pesh mat karo
                    "verified": False,
                    "evidence": _RELATION_NOTE,
                })

    return relationships[:15]


def extract_and_store(question: str, answer_text: str, project_id: str = "default") -> Dict:
    """
    Spec Section 16 — Knowledge Graph / Research Memory
    Regex-based entity + relationship extraction (free, local, koi Gemini call nahi)
    """
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
    """Spec Section 16 — poora Knowledge Graph structure (hint layer)."""
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
