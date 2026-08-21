"""
WebConnector — Spec Section 2 (legally accessible webpages)

Priority (project ke real test results se decided, memory mein documented):
    1. Tavily      — official API, free ~1000/month, sabse reliable
    2. Wikipedia   — official API, unlimited, User-Agent header zaroori
    3. DuckDuckGo  — LAST resort. Server ke andar rate-limit hone se 0 results
                     deta hai, isliye ye primary nahi hai.

Google Custom Search jaan-boojh kar nahi hai (Cloud console pe API available
nahi hui + 2SV block) — dobara try mat karna.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from ..models import SourceRecord, SourceType
from .base import (BaseConnector, ConnectorHTTPError, ConnectorSkipped,
                   READ_TIMEOUT, http_get)


class TavilyConnector(BaseConnector):
    name = "tavily"
    source_type = SourceType.WEB
    free = True          # free tier ~1000 searches/month — unlimited NAHI
    rate_limited = True

    @property
    def api_key(self) -> str:
        return os.getenv("TAVILY_API_KEY", "")

    def search(self, query: str, max_results: int = 5) -> List[SourceRecord]:
        if not self.api_key:
            # "key nahi hai" aur "kuch nahi mila" ek jaise dikhne na paaye.
            # Sirf note likhna kaafi NAHI tha: reason khaali reh jaata tha, isliye
            # discovery_note ise "khaali (search chali, result 0)" bucket mein daal
            # deta tha, aur orchestrator research memory mein "tavily: chala par 0
            # result mila" likh deta tha — dono jhooth. Ab honest exception.
            raise ConnectorSkipped(
                "TAVILY_API_KEY .env mein nahi hai — Tavily search chali hi nahi "
                "(ye 'result nahi mila' se alag baat hai)"
            )
        from tavily import TavilyClient  # lazy

        client = TavilyClient(api_key=self.api_key)
        # Tavily/DDG apna HTTP khud karte hain, isliye base.http_get ka timeout
        # inpar nahi lagta — bina timeout ek hang poore research ko rok sakta hai.
        # Naye version `timeout` lete hain, purane nahi; isliye try/except.
        try:
            response = client.search(query=query, max_results=max_results,
                                     timeout=READ_TIMEOUT)
        except TypeError:
            # Purane SDK ka unbounded fallback poore process ko latka sakta hai.
            # Discovery budget thread ka result chhod sakta hai, running socket
            # ko force-stop nahi kar sakta. Mandatory timeout support na ho to
            # fail closed; user newer free client install kar sakta hai.
            raise ConnectorHTTPError(
                "Tavily client timeout support available nahi hai; unsafe unbounded call roki gayi"
            ) from None
        out: List[SourceRecord] = []
        for r in response.get("results", []) or []:
            out.append(SourceRecord(
                title=self._clean(r.get("title")),
                url=self._clean(r.get("url")),
                snippet=self._clean(r.get("content")),
                connector=self.name,
                source_type=SourceType.WEB,
            ))
        return out


class WikipediaConnector(BaseConnector):
    name = "wikipedia"
    source_type = SourceType.ENCYCLOPEDIA

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        resp = http_get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query", "list": "search", "srsearch": query,
                "format": "json", "srlimit": max_results,
            },
        )
        out: List[SourceRecord] = []
        for item in (resp.json().get("query") or {}).get("search", []) or []:
            title = item.get("title", "")
            snippet = (item.get("snippet", "")
                       .replace('<span class="searchmatch">', "")
                       .replace("</span>", ""))
            out.append(SourceRecord(
                title=self._clean(title),
                url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                snippet=self._clean(snippet),
                connector=self.name,
                source_type=SourceType.ENCYCLOPEDIA,
                # encyclopedia = secondary source, primary nahi
                is_primary=False,
            ))
        return out


class DuckDuckGoConnector(BaseConnector):
    name = "duckduckgo"
    source_type = SourceType.WEB
    rate_limited = True

    def search(self, query: str, max_results: int = 5) -> List[SourceRecord]:
        try:
            from ddgs import DDGS       # naya package name
        except ImportError:
            from duckduckgo_search import DDGS  # purana naam

        # DDG bhi apna HTTP khud karta hai — timeout dena zaroori hai
        try:
            session = DDGS(timeout=READ_TIMEOUT)
        except TypeError:
            raise ConnectorHTTPError(
                "DuckDuckGo client timeout support available nahi hai; unsafe unbounded call roki gayi"
            ) from None

        out: List[SourceRecord] = []
        with session as ddgs:
            for r in ddgs.text(query, max_results=max_results) or []:
                out.append(SourceRecord(
                    title=self._clean(r.get("title")),
                    url=self._clean(r.get("href") or r.get("url")),
                    snippet=self._clean(r.get("body")),
                    connector=self.name,
                    source_type=SourceType.WEB,
                ))
        return out


class WebConnector:
    """Spec Section 16 ka 'WebConnector' — fallback chain ke saath."""

    def __init__(self):
        self.tavily = TavilyConnector()
        self.wikipedia = WikipediaConnector()
        self.duckduckgo = DuckDuckGoConnector()
        self.connectors: List[BaseConnector] = [
            self.tavily, self.wikipedia, self.duckduckgo,
        ]

    def by_name(self, name: str) -> Optional[BaseConnector]:
        return next((c for c in self.connectors if c.name == name), None)

    def search(self, query: str, max_results: int = 5) -> Dict:
        """
        Fallback chain: Tavily se shuru karo; kam pade to Wikipedia; phir DDG.
        Jitna target hai utna milte hi ruk jao (free quota bachaao).
        """
        records: List[SourceRecord] = []
        log: List[Dict] = []

        for connector in (self.tavily, self.wikipedia, self.duckduckgo):
            if len(records) >= max_results:
                break
            need = max_results - len(records)
            result = connector.safe_search(query, need)
            records.extend(result["records"])
            log.append({k: v for k, v in result.items() if k != "records"})

        return {"records": records, "log": log}
