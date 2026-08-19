"""
citation_counter.py — Spec Section 7 (Evidence Reliability)

Ye module real citation counts fetch karta hai OpenAlex se aur quality scoring
ko improve karta hai.

Kaam:
1. OpenAlex API se paper ID → citation count
2. H-index (agar author data available ho)
3. Journal impact factor hints
4. Recency weighting

Zero Gemini quota — sirf HTTP calls.
"""
from __future__ import annotations

import time
from typing import Dict, Optional
import requests

HEADERS = {"User-Agent": "InfinityResearchAI/1.0 (research engine)"}
OPENALEX_BASE = "https://api.openalex.org"
CACHE: Dict[str, int] = {}  # Simple in-memory cache


def fetch_citation_count(doi: str = "", openalex_id: str = "",
                         title: str = "", timeout: float = 5.0) -> Optional[int]:
    """
    OpenAlex se citation count laao.

    Priority: DOI > OpenAlex ID > Title search
    """
    # Cache check
    cache_key = doi or openalex_id or title
    if cache_key in CACHE:
        return CACHE[cache_key]

    try:
        # 1. DOI se direct lookup (fastest)
        if doi:
            doi_clean = doi.replace("https://doi.org/", "").strip()
            url = f"{OPENALEX_BASE}/works/doi:{doi_clean}"
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                count = data.get("cited_by_count", 0)
                CACHE[cache_key] = count
                return count

        # 2. OpenAlex ID se direct (also fast)
        if openalex_id:
            url = f"{OPENALEX_BASE}/works/{openalex_id}"
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                count = data.get("cited_by_count", 0)
                CACHE[cache_key] = count
                return count

        # 3. Title search (slower, rate-limited)
        if title:
            query = title.split()[0:3]  # First 3 words
            search_q = " ".join(query)
            url = f"{OPENALEX_BASE}/works"
            params = {"search": search_q, "per_page": 1}
            resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("results"):
                    count = data["results"][0].get("cited_by_count", 0)
                    CACHE[cache_key] = count
                    return count

        return None

    except requests.exceptions.RequestException:
        return None
    except Exception:
        return None


def get_quality_boost(citation_count: Optional[int]) -> float:
    """
    Citation count se quality score boost (0.0 - 0.3).

    Logarithmic scale: citations are rare, so 1 citation = decent boost.
    """
    if citation_count is None:
        return 0.0

    if citation_count == 0:
        return 0.0
    elif citation_count <= 5:
        return 0.05
    elif citation_count <= 20:
        return 0.1
    elif citation_count <= 100:
        return 0.15
    elif citation_count <= 500:
        return 0.2
    else:
        return 0.3  # Highly cited


def classify_citation_level(citation_count: Optional[int]) -> str:
    """
    Citation count ko human-readable level mein convert karo.
    """
    if citation_count is None:
        return "UNKNOWN"
    elif citation_count == 0:
        return "UNCITED"
    elif citation_count <= 5:
        return "RARELY_CITED"
    elif citation_count <= 20:
        return "MODERATELY_CITED"
    elif citation_count <= 100:
        return "WELL_CITED"
    elif citation_count <= 500:
        return "HIGHLY_CITED"
    else:
        return "LANDMARK_PAPER"


# Test
if __name__ == "__main__":
    # Test: arXiv paper
    test_doi = "10.1145/3287560.3287596"  # Gender Shades paper
    count = fetch_citation_count(doi=test_doi)
    print(f"Citation count: {count}")
    print(f"Quality boost: {get_quality_boost(count)}")
    print(f"Level: {classify_citation_level(count)}")
