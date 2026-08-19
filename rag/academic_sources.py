"""
DEPRECATED — ye file ab pipeline mein use NAHI hoti.

Iski jagah: research_engine/connectors/paper_connector.py
(OpenAlex, arXiv, Crossref, DOAJ, PubMed, Semantic Scholar — sab BaseConnector
subclass, safe_search() ke saath) aur book_connector.py (Internet Archive,
Open Library, Google Books).

NOTE: purani memory mein likha tha "next step = academic_sources.py wire karna".
Wo kaam ab poora ho chuka hai, par naye connectors ke roop mein — ye file usi
logic ki purani copy hai. Ise edit karne se kuch nahi badlega.

File reference ke liye rakhi hai.
"""
import requests
from typing import Dict, List

HEADERS = {"User-Agent": "InfinityResearchAI/1.0 (educational project)"}


def _decode_openalex_abstract(inverted_index: dict) -> str:
    """OpenAlex abstract ko 'inverted index' format se normal text mein badalo"""
    if not inverted_index:
        return ""
    try:
        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort()
        return " ".join(word for _, word in word_positions)[:400]
    except Exception:
        return ""


def search_openalex(query: str, max_results: int = 5) -> List[Dict]:
    """OpenAlex — free, no API key, 200M+ scholarly works"""
    results = []
    try:
        url = "https://api.openalex.org/works"
        params = {"search": query, "per_page": max_results}
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        data = resp.json()
        for item in data.get("results", []):
            abstract = _decode_openalex_abstract(item.get("abstract_inverted_index"))
            results.append({
                "title": item.get("title", ""),
                "snippet": abstract,
                "url": item.get("id", "")
            })
    except Exception as e:
        print(f"OPENALEX ERROR: {type(e).__name__}: {e}")
    return results


def search_semantic_scholar(query: str, max_results: int = 5) -> List[Dict]:
    """Semantic Scholar — free, no API key needed for basic search"""
    results = []
    try:
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {"query": query, "limit": max_results, "fields": "title,abstract,url"}
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        data = resp.json()
        for item in data.get("data", []):
            results.append({
                "title": item.get("title", ""),
                "snippet": (item.get("abstract") or "")[:300],
                "url": item.get("url", "")
            })
    except Exception as e:
        print(f"SEMANTIC SCHOLAR ERROR: {type(e).__name__}: {e}")
    return results


def search_pubmed(query: str, max_results: int = 5) -> List[Dict]:
    """PubMed/NCBI — free, medical/biological research"""
    results = []
    try:
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        params = {"db": "pubmed", "term": query, "retmax": max_results, "retmode": "json"}
        resp = requests.get(search_url, params=params, headers=HEADERS, timeout=8)
        ids = resp.json().get("esearchresult", {}).get("idlist", [])

        if not ids:
            return results

        summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        params2 = {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
        resp2 = requests.get(summary_url, params=params2, headers=HEADERS, timeout=8)
        data = resp2.json().get("result", {})

        for pid in ids:
            item = data.get(pid, {})
            if item:
                results.append({
                    "title": item.get("title", ""),
                    "snippet": f"Published: {item.get('pubdate', 'N/A')}, Source: {item.get('source', 'N/A')}",
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/"
                })
    except Exception as e:
        print(f"PUBMED ERROR: {type(e).__name__}: {e}")
    return results


def search_crossref(query: str, max_results: int = 5) -> List[Dict]:
    """Crossref — free, academic paper metadata/DOIs"""
    results = []
    try:
        url = "https://api.crossref.org/works"
        params = {"query": query, "rows": max_results}
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        data = resp.json()
        for item in data.get("message", {}).get("items", []):
            title = item.get("title", [""])[0] if item.get("title") else ""
            results.append({
                "title": title,
                "snippet": f"Published: {item.get('published-print', {}).get('date-parts', [['N/A']])[0][0]}, Publisher: {item.get('publisher', 'N/A')}",
                "url": item.get("URL", "")
            })
    except Exception as e:
        print(f"CROSSREF ERROR: {type(e).__name__}: {e}")
    return results


def search_doaj(query: str, max_results: int = 5) -> List[Dict]:
    """DOAJ — Directory of Open Access Journals, free"""
    results = []
    try:
        url = f"https://doaj.org/api/search/articles/{query}"
        params = {"pageSize": max_results}
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        data = resp.json()
        for item in data.get("results", []):
            bibjson = item.get("bibjson", {})
            title = bibjson.get("title", "")
            links = bibjson.get("link", [])
            url_val = links[0].get("url", "") if links else ""
            results.append({
                "title": title,
                "snippet": (bibjson.get("abstract") or "")[:300],
                "url": url_val
            })
    except Exception as e:
        print(f"DOAJ ERROR: {type(e).__name__}: {e}")
    return results


def search_internet_archive(query: str, max_results: int = 5) -> List[Dict]:
    """Internet Archive — free, books/media metadata"""
    results = []
    try:
        url = "https://archive.org/advancedsearch.php"
        params = {
            "q": query,
            "fl[]": ["identifier", "title", "description"],
            "rows": max_results,
            "output": "json"
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        docs = resp.json().get("response", {}).get("docs", [])
        for item in docs:
            results.append({
                "title": item.get("title", ""),
                "snippet": (item.get("description") or "")[:300] if isinstance(item.get("description"), str) else "",
                "url": f"https://archive.org/details/{item.get('identifier', '')}"
            })
    except Exception as e:
        print(f"INTERNET ARCHIVE ERROR: {type(e).__name__}: {e}")
    return results


def search_google_books(query: str, max_results: int = 5) -> List[Dict]:
    """Google Books — free (rate-limited without key), book metadata"""
    results = []
    try:
        url = "https://www.googleapis.com/books/v1/volumes"
        params = {"q": query, "maxResults": max_results}
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        data = resp.json()
        for item in data.get("items", []):
            info = item.get("volumeInfo", {})
            results.append({
                "title": info.get("title", ""),
                "snippet": (info.get("description") or "")[:300],
                "url": info.get("infoLink", "")
            })
    except Exception as e:
        print(f"GOOGLE BOOKS ERROR: {type(e).__name__}: {e}")
    return results


def search_academic_all(query: str, max_per_source: int = 3) -> List[Dict]:
    """
    Blueprint Section 2 — sabhi academic/research connectors ek saath
    (Book Research + Paper Research sections)
    Always-free: OpenAlex, Crossref, DOAJ, PubMed, Internet Archive
    Rate-limited without key: Semantic Scholar (429 hoga), Google Books (429 hoga)
    """
    all_results = []
    all_results.extend(search_openalex(query, max_per_source))
    all_results.extend(search_crossref(query, max_per_source))
    all_results.extend(search_doaj(query, max_per_source))
    all_results.extend(search_pubmed(query, max_per_source))
    all_results.extend(search_internet_archive(query, max_per_source))
    # Semantic Scholar + Google Books: try karo, 429 pe silently skip (error handler inke andar hai)
    all_results.extend(search_semantic_scholar(query, max_per_source))
    return all_results