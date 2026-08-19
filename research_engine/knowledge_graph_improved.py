"""
Knowledge Graph Improvements — Spec Section 12 (Cross-Disciplinary Synthesis)

Pehle wala version: basic regex entity extraction
Issue: Relationships extraction low accuracy

Ye version: Improved relationship patterns + entity linking
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple, Set

# Improved relationship patterns
_RELATION_PATTERNS = [
    # Causal relationships
    (r"(\w+)\s+causes?\s+(\w+)", "CAUSES"),
    (r"(\w+)\s+leads?\s+to\s+(\w+)", "LEADS_TO"),
    (r"(\w+)\s+results?\s+in\s+(\w+)", "RESULTS_IN"),
    (r"(\w+)\s+triggers?\s+(\w+)", "TRIGGERS"),

    # Association relationships
    (r"(\w+)\s+is\s+related\s+to\s+(\w+)", "RELATED_TO"),
    (r"(\w+)\s+connects?\s+to\s+(\w+)", "CONNECTS_TO"),
    (r"(\w+)\s+(?:and|aur)\s+(\w+)\s+(?:are|hain)\s+connected", "CONNECTED"),

    # Part-of relationships
    (r"(\w+)\s+is\s+part\s+of\s+(\w+)", "PART_OF"),
    (r"(\w+)\s+includes?\s+(\w+)", "INCLUDES"),
    (r"(\w+)\s+contains?\s+(\w+)", "CONTAINS"),

    # Comparison
    (r"(\w+)\s+(?:vs|versus)\s+(\w+)", "COMPARES_WITH"),
    (r"(\w+)\s+differs?\s+from\s+(\w+)", "DIFFERS_FROM"),
    (r"(\w+)\s+similar\s+to\s+(\w+)", "SIMILAR_TO"),

    # Temporal
    (r"(\w+)\s+before\s+(\w+)", "BEFORE"),
    (r"(\w+)\s+after\s+(\w+)", "AFTER"),
    (r"(\w+)\s+during\s+(\w+)", "DURING"),

    # Influence
    (r"(\w+)\s+affects?\s+(\w+)", "AFFECTS"),
    (r"(\w+)\s+influences?\s+(\w+)", "INFLUENCES"),
    (r"(\w+)\s+impacts?\s+(\w+)", "IMPACTS"),
]

# Stopwords (English + Hinglish)
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "ka", "ki", "ke", "se", "mein", "me", "par", "aur", "ya", "hai", "hain",
    "tha", "the", "ho", "hota", "hoti", "kya", "kaun", "kaise", "kyon"
}


def extract_entities_improved(text: str, min_length: int = 3) -> List[str]:
    """
    Improved entity extraction with better filtering.
    """
    # Capitalize words (entities are usually capitalized)
    words = text.split()
    entities = []

    for word in words:
        # Clean word
        clean_word = re.sub(r'[^\w\s]', '', word).strip()

        # Check if entity candidate
        if (len(clean_word) >= min_length and
            clean_word.lower() not in _STOPWORDS and
            clean_word[0].isupper()):  # Capitalized
            entities.append(clean_word)

    # Deduplicate
    return list(dict.fromkeys(entities))


def extract_relationships_improved(text: str) -> List[Tuple[str, str, str]]:
    """
    Extract (entity1, relation, entity2) triples with improved patterns.
    """
    relationships = []
    text_lower = text.lower()

    for pattern, rel_type in _RELATION_PATTERNS:
        matches = re.finditer(pattern, text_lower, re.IGNORECASE)
        for match in matches:
            entity1 = match.group(1).strip()
            entity2 = match.group(2).strip()

            # Filter stopwords
            if (entity1 not in _STOPWORDS and
                entity2 not in _STOPWORDS and
                len(entity1) >= 3 and len(entity2) >= 3):
                relationships.append((entity1, rel_type, entity2))

    return relationships[:20]  # Max 20 relationships


def build_knowledge_graph(text: str) -> Dict:
    """
    Build complete knowledge graph from text.

    Returns:
        {
            "entities": [...],
            "relationships": [(e1, rel, e2), ...],
            "entity_count": int,
            "relationship_count": int
        }
    """
    entities = extract_entities_improved(text)
    relationships = extract_relationships_improved(text)

    return {
        "entities": entities[:50],  # Top 50 entities
        "relationships": relationships,
        "entity_count": len(entities),
        "relationship_count": len(relationships),
    }


def find_cross_disciplinary_connections(entities: List[str],
                                       fields: List[str]) -> List[Dict]:
    """
    Identify which entities connect which fields.

    Example: "bias" connects Computer Science + Sociology + Psychology
    """
    # Field-specific keywords
    field_keywords = {
        "Computer Science": ["algorithm", "model", "ai", "ml", "training", "data"],
        "Psychology": ["behavior", "cognitive", "mental", "bias", "emotion"],
        "Sociology": ["society", "social", "culture", "discrimination", "inequality"],
        "Medicine": ["disease", "treatment", "health", "diagnosis", "symptoms"],
        "Economics": ["market", "finance", "economy", "trade", "investment"],
    }

    connections = []
    for entity in entities:
        entity_lower = entity.lower()
        connected_fields = []

        for field in fields:
            if field in field_keywords:
                keywords = field_keywords[field]
                if any(kw in entity_lower for kw in keywords):
                    connected_fields.append(field)

        if len(connected_fields) >= 2:  # Cross-disciplinary
            connections.append({
                "entity": entity,
                "connects_fields": connected_fields,
                "is_bridge": True
            })

    return connections


# Test
if __name__ == "__main__":
    test_text = """
    AI bias in hiring leads to discrimination. Machine learning models
    trained on historical data can perpetuate societal biases. This affects
    minority candidates and creates unfair outcomes. The Computer Science
    field must collaborate with Sociology and Psychology to address these
    ethical issues.
    """

    kg = build_knowledge_graph(test_text)
    print(f"Entities: {kg['entities']}")
    print(f"Relationships: {kg['relationships']}")

    connections = find_cross_disciplinary_connections(
        kg['entities'],
        ["Computer Science", "Sociology", "Psychology"]
    )
    print(f"Cross-disciplinary connections: {connections}")
