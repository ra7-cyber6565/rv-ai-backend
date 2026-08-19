"""
DEPRECATED — ye file ab pipeline mein use NAHI hoti.

Iski jagah: research_engine/relevance.py (RelevanceEngine) +
research_engine/dedup.py (DeduplicationEngine)

Kyun replace hua:
    * dedup ab independence_key (DOI > domain > normalized title) par hota hai,
      isliye "ek hi information ki 100 copied websites" 100 independent sources
      nahi ginti — Spec Section 7
    * ranking ab peer-review, citation count, recency aur primary/secondary
      status dekhti hai, sirf keyword overlap nahi
    * is_evidence_sufficient() report bhi milti hai, jisse system khud bata
      sakta hai ki evidence kaafi hai ya nahi

File reference ke liye rakhi hai. Naya kaam research_engine/ mein karo.
"""
from typing import Dict, List
import re


def deduplicate_sources(sources: List[Dict]) -> List[Dict]:
    """Same URL ya same title wale duplicates remove karo. Pehla occurrence rakhte hain."""
    seen_urls = set()
    seen_titles = set()
    unique = []
    for s in sources:
        url = s.get("url", "").strip().rstrip("/").lower()
        title = re.sub(r'\s+', ' ', s.get("title", "").lower().strip())
        if url and url in seen_urls:
            continue
        if title and len(title) > 10 and title in seen_titles:
            continue
        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title)
        unique.append(s)
    return unique


def score_source_quality(source: Dict) -> float:
    """Source ko quality score do (0.0 - 1.0). Higher = better quality."""
    score = 0.5
    url = source.get("url", "").lower()
    snippet = source.get("snippet", "").lower()

    academic_domains = [
        "arxiv.org", "pubmed", "ncbi.nlm.nih.gov", "openalex.org",
        "semanticscholar.org", "crossref.org", "doaj.org", "archive.org",
        "doi.org", ".gov", ".edu", "wikipedia.org", "nature.com",
        "science.org", "springer.com", "elsevier.com", "ieee.org",
        "acm.org", "jstor.org", "plos.org", "biorxiv.org"
    ]
    for domain in academic_domains:
        if domain in url:
            score += 0.3
            break

    if any(w in snippet for w in ["published", "peer-reviewed", "journal", "doi:", "cited by", "abstract"]):
        score += 0.1

    if len(snippet) > 100:
        score += 0.1

    if any(w in url for w in ["reddit.com", "quora.com", "yahoo.com", "pinterest.com"]):
        score -= 0.2

    return min(max(score, 0.0), 1.0)


def rank_and_filter_sources(
    sources: List[Dict],
    query: str,
    max_sources: int = 10
) -> List[Dict]:
    """
    Blueprint Section 6 — Progressive Selection:
    1. Deduplicate
    2. Score quality + keyword relevance
    3. Sort by combined score
    4. Return top N
    """
    unique = deduplicate_sources(sources)
    query_words = set(re.findall(r'\b\w{3,}\b', query.lower()))

    scored = []
    for s in unique:
        q_score = score_source_quality(s)
        text = (s.get("title", "") + " " + s.get("snippet", "")).lower()
        text_words = set(re.findall(r'\b\w{3,}\b', text))
        overlap = len(query_words & text_words) / len(query_words) if query_words else 0.0
        combined = (q_score * 0.6) + (overlap * 0.4)
        scored.append((combined, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:max_sources]]
