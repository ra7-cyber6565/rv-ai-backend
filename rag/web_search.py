"""
DEPRECATED — ye file ab pipeline mein use NAHI hoti.

Iski jagah: research_engine/connectors/ (WebConnector, PaperConnector,
BookConnector) + research_engine/source_discovery.py

Kyun replace hua:
    * yahan connectors sequential the; naya version parallel fan-out karta hai
    * yahan har error crash kar sakta tha; naye connectors safe_search() se
      guzarte hain, isliye ek API down hone par poori research nahi rukti
    * yahan output plain dict tha (koi source_id, independence key, ya
      peer-review flag nahi) — citation verification isse possible nahi thi

File reference ke liye rakhi hai. Naya kaam research_engine/connectors/ mein
karo, warna do jagah logic diverge ho jayega.
"""
from typing import Dict, List

import xml.etree.ElementTree as ET
import os

import requests
from dotenv import load_dotenv

from rag.academic_sources import search_academic_all


def _ddgs():
    """Lazy + dono package naam support — top-level import server ko na girae."""
    try:
        from ddgs import DDGS            # naya naam
    except ImportError:
        from duckduckgo_search import DDGS  # purana naam
    return DDGS

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")


def clean_query(question: str) -> str:
    filler_words = ["ke baare mein bataiye", "ke baare mein", "kya hai", "batao", "bताओ", "kaun hai", "kya", "hai"]
    query = question
    for fw in filler_words:
        query = query.replace(fw, "")
    return query.strip()


def search_tavily(query: str, max_results: int = 5) -> List[Dict]:
    """Tavily — primary search source (AI-optimized, reliable official API)"""
    results = []
    if not TAVILY_API_KEY:
        return results
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_API_KEY)
        response = client.search(query=query, max_results=max_results)
        for r in response.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "snippet": r.get("content", ""),
                "url": r.get("url", "")
            })
    except Exception as e:
        print(f"TAVILY SEARCH ERROR: {type(e).__name__}: {e}")

    return results


def search_duckduckgo(query: str, max_results: int = 5) -> List[Dict]:
    """DuckDuckGo — secondary backup"""
    results = []
    try:
        with _ddgs()() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", "")
                })
    except Exception as e:
        print(f"DDG SEARCH ERROR: {type(e).__name__}: {e}")

    return results


def search_wikipedia(query: str, max_results: int = 3) -> List[Dict]:
    """Wikipedia — tertiary backup (official API)"""
    results = []
    try:
        search_url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": max_results
        }
        headers = {"User-Agent": "InfinityResearchAI/1.0 (educational project)"}
        resp = requests.get(search_url, params=params, headers=headers, timeout=5)
        data = resp.json()

        for item in data.get("query", {}).get("search", []):
            title = item["title"]
            snippet = item["snippet"].replace('<span class="searchmatch">', '').replace('</span>', '')
            results.append({
                "title": title,
                "snippet": snippet,
                "url": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
            })
    except Exception as e:
        print(f"WIKIPEDIA SEARCH ERROR: {type(e).__name__}: {e}")

    return results


def search_arxiv(query: str, max_results: int = 3) -> List[Dict]:
    """arXiv — scientific/research papers"""
    results = []
    try:
        url = "http://export.arxiv.org/api/query"
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results
        }
        resp = requests.get(url, params=params, timeout=8)
        root = ET.fromstring(resp.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
            summary = entry.find("atom:summary", ns).text.strip().replace("\n", " ")[:300]
            link = entry.find("atom:id", ns).text.strip()
            results.append({
                "title": title,
                "snippet": summary,
                "url": link
            })
    except Exception as e:
        print(f"ARXIV SEARCH ERROR: {type(e).__name__}: {e}")

    return results


def search_web(query: str, max_results: int = 5) -> List[Dict]:
    """
    Blueprint Section 6 — Source Discovery Engine
    Priority: Tavily (reliable) -> DuckDuckGo -> Wikipedia
    """
    clean = clean_query(query)

    results = search_tavily(clean, max_results=max_results)
    print(f"TAVILY: found {len(results)} results for: {clean}")

    if len(results) < max_results:
        ddg_results = search_duckduckgo(clean, max_results=max_results - len(results))
        print(f"DDG: found {len(ddg_results)} additional results")
        results.extend(ddg_results)

    if len(results) < max_results:
        wiki_results = search_wikipedia(clean, max_results=max_results - len(results))
        print(f"WIKIPEDIA: found {len(wiki_results)} additional results")
        results.extend(wiki_results)

    return results


def search_all_sources(query: str, max_results: int = 5, include_papers: bool = False) -> List[Dict]:
    """Poora Source Discovery — web + optionally research papers (arXiv + academic databases)"""
    results = search_web(query, max_results=max_results)

    if include_papers:
        papers = search_arxiv(query, max_results=2)
        print(f"ARXIV: found {len(papers)} papers")
        results.extend(papers)

        academic = search_academic_all(query, max_per_source=2)
        print(f"ACADEMIC (OpenAlex+SemanticScholar+Crossref+DOAJ): found {len(academic)} papers")
        results.extend(academic)

    return results


def format_web_context(results: List[Dict]) -> str:
    if not results:
        return ""
    parts = []
    for r in results:
        parts.append(f"[Web Source: {r['title']}]\nURL: {r['url']}\n{r['snippet']}")
    return "\n\n".join(parts)