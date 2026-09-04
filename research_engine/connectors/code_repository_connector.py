"""Public code-repository discovery for the research runtime.

This lane deliberately separates three different claims:

* repository discovered != code inspected
* README/description != implementation
* code inspected != code executed/tested

Only GitHub's public REST API is used.  No repository is cloned, no arbitrary
shell command is run and no private repository endpoint is touched.  The
structured reader performs bounded file inspection later; this connector only
locates relevant public repositories and records honest metadata/snippet depth.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from ..models import SourceRecord, SourceType
from ..network_safety import (
    read_bounded_response,
    require_content_type,
    safe_get_with_redirects,
)
from .base import (
    SLOW_TIMEOUT,
    AccessBlocked,
    BaseConnector,
    ConnectorHTTPError,
    RateLimited,
    content_terms,
)

GITHUB_API = "https://api.github.com"
GITHUB_HOSTS = {"api.github.com"}
MAX_GITHUB_JSON_BYTES = 8 * 1024 * 1024


def _headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "InfinityResearchAI/1.0 (public research repository reader)",
    }
    token = (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_json(url: str, *, params: Optional[Dict] = None,
                timeout: Tuple[int, int] = SLOW_TIMEOUT,
                max_bytes: int = MAX_GITHUB_JSON_BYTES):
    """Read one code-owned public GitHub REST JSON endpoint, fail closed.

    The function accepts only ``api.github.com`` and never returns response
    bodies in exception messages.  It is shared by discovery and the later code
    inspector so both paths use exactly the same network boundary.
    """
    import requests  # lazy dependency, same policy as other connectors

    response = None
    try:
        response, _final = safe_get_with_redirects(
            requests,
            url,
            params=params,
            headers=_headers(),
            timeout=timeout,
            stream=True,
            allowed_hosts=GITHUB_HOSTS,
            resolve_dns=False,
            max_redirects=1,
        )
        status = int(getattr(response, "status_code", 200) or 200)
        remaining = str((getattr(response, "headers", None) or {}).get(
            "X-RateLimit-Remaining") or "").strip()
        if status in {429, 503} or (status == 403 and remaining == "0"):
            raise RateLimited(
                f"GitHub public API HTTP {status} rate limit — request poori nahi hui")
        if status == 403:
            raise AccessBlocked("GitHub public API ne access deny kiya")
        if status >= 400:
            raise ConnectorHTTPError(f"GitHub public API HTTP {status}", status=status)
        require_content_type(response, "json")
        read_bounded_response(response, max(1, int(max_bytes)))
        return response.json()
    finally:
        try:
            if response is not None:
                response.close()
        except Exception:
            pass


def _search_terms(query: str) -> str:
    terms = content_terms(query, limit=6)
    clean = " ".join(terms).strip()
    if not clean:
        clean = " ".join(str(query or "").split())[:140]
    return clean[:180]


class GitHubRepositoryConnector(BaseConnector):
    """Locate public GitHub repositories; never call this a code read."""

    name = "github_code"
    source_type = SourceType.WEB
    rate_limited = True
    timeout: Tuple[int, int] = SLOW_TIMEOUT

    def parse(self, payload: Dict) -> List[SourceRecord]:
        rows = (payload or {}).get("items") or []
        out: List[SourceRecord] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            full_name = self._clean(item.get("full_name"), 220)
            html_url = self._clean(item.get("html_url"), 400)
            if not full_name or not html_url.startswith("https://github.com/"):
                continue
            owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
            description = self._clean(item.get("description"), 900)
            language = self._clean(item.get("language"), 80)
            stars = item.get("stargazers_count")
            forks = item.get("forks_count")
            extras = []
            if language:
                extras.append(f"primary language: {language}")
            if isinstance(stars, int):
                extras.append(f"stars: {stars}")
            if isinstance(forks, int):
                extras.append(f"forks: {forks}")
            snippet = description
            if extras:
                snippet = (snippet + " | " if snippet else "") + "; ".join(extras)
            out.append(SourceRecord(
                title=full_name,
                url=html_url,
                snippet=snippet,
                connector=self.name,
                source_type=SourceType.WEB,
                authors=[self._clean(owner.get("login"), 120)] if owner.get("login") else [],
                year=self._year(item.get("pushed_at") or item.get("updated_at")),
                publisher="GitHub public repository",
                is_primary=True,
                peer_reviewed=None,
                full_text_available=False,
                read_level="snippet" if snippet else "metadata",
                read_note=(
                    "Repository metadata/description mila; implementation ke code files "
                    "abhi inspect nahi hue. README ya repo page ko code read nahi maana gaya."
                ),
                doc_kind="code_repository",
                doc_kind_label="public code repository",
                doc_kind_confidence="high",
            ))
        return out

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        clean = _search_terms(query)
        if not clean:
            self.last_reason = "empty_query"
            self.last_note = "code repository search ke liye usable topic term nahi mila"
            return []
        payload = github_json(
            f"{GITHUB_API}/search/repositories",
            params={
                "q": f"{clean} in:name,description,readme fork:false archived:false",
                "sort": "stars",
                "order": "desc",
                "per_page": max(1, min(int(max_results or 1), 10)),
            },
            timeout=self.timeout,
        )
        records = self.parse(payload)[:max_results]
        if records:
            self.last_note = (
                f"{len(records)} public GitHub repository metadata mila; code files "
                "alag bounded inspection stage mein padhe jayenge")
        else:
            self.last_note = "GitHub public repository search chali par relevant repo nahi mila"
        return records


class CodeRepositoryConnector:
    """Facade kept parallel to PaperConnector/DatasetConnector/MarketConnector."""

    def __init__(self):
        self.connectors: List[BaseConnector] = [GitHubRepositoryConnector()]

    def by_name(self, name: str) -> Optional[BaseConnector]:
        return next((c for c in self.connectors if c.name == name), None)

    def available_names(self) -> List[str]:
        return [c.name for c in self.connectors]

    def search(self, query: str, max_per_source: int = 3,
               only: Optional[List[str]] = None) -> Dict:
        records: List[SourceRecord] = []
        log: List[Dict] = []
        for connector in self.connectors:
            if only and connector.name not in only:
                continue
            result = connector.safe_search(query, max_per_source)
            records.extend(result.get("records", []))
            log.append({k: v for k, v in result.items() if k != "records"})
        return {"records": records, "log": log}
