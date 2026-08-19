"""
BookConnector — Spec Section 3 (Book Research)

Spec ki demand:
    1. Books khojo
    2. Metadata collect karo (title, author, year, publisher, subject, availability)
    3. Jahan LEGALLY full text mile wahan content retrieve karo
    4. Jahan na mile wahan sirf metadata/preview use karo
    5. Relevant books rank karo
    6. Lakhon books blindly process MAT karo

Free sources: Google Books API (key ke bina rate-limited), Internet Archive,
Open Library (Internet Archive ka catalogue).

IMPORTANT: paywalled/copyrighted full text bypass nahi karte. Jahan sirf
preview/snippet legally available hai, wahan availability honestly record hoti hai.

LIVE TEST (2026-08-17) mein teeno book connectors fail hue the — teen alag wajah:
    internet_archive : ReadTimeout    (archive.org ka search sach mein slow hai)
    open_library     : ConnectTimeout (openlibrary.org kabhi der se connect hota hai)
    google_books     : 0 results      (India se `country` param ke bina khaali)
Teeno ka fix isi file mein neeche comment ke saath hai.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from ..models import SourceRecord, SourceType
from .base import SLOW_TIMEOUT, BaseConnector, http_get

# Google Books viewability -> kya hum legally full text padh sakte hain.
# Ye set spec ka paywall rule enforce karta hai, isliye ise dheela mat karna:
# NO_PAGES / PARTIAL kabhi full text nahi hai.
_FULL_VIEW = {"ALL_PAGES", "ALL_PAGES_PUBLIC_DOMAIN"}

# archive.org / openlibrary.org "slow but free" category mein aate hain.
# Inhe general default se zyada saans do — warna free source sirf slow hone ki
# wajah se hamesha ke liye chhoot jaata hai.
#
# Ye pehle hard-coded (15, 45) tha. Bug: error message user ko kehta tha
# "CONNECTOR_READ_TIMEOUT badha do", par CONNECTOR_READ_TIMEOUT=60 karne par
# baaki sab 60 par chale jaate the aur ye do slow sources 45 par hi atke rehte
# the — yaani jis knob ki salah di, wo in par lagta hi nahi tha. Ab base ka
# SLOW_TIMEOUT usi env knob se banta hai (kam se kam 15/45, us se upar env jitna).
_SLOW_TIMEOUT: Tuple[int, int] = SLOW_TIMEOUT


class GoogleBooksConnector(BaseConnector):
    """
    LIVE BUG (2026-08-17): 0 results, bina kisi error ke.

    Google Books API caller ke IP se country decide karta hai. Jab wo confident
    nahi hota (India se aksar hota hai) to ya to 403 "not available in your
    country" deta hai, ya chup-chaap khaali list. `country` param bhejne se ye
    theek ho jaata hai. Default IN hai, aur .env mein GOOGLE_BOOKS_COUNTRY se
    badla ja sakta hai (do-letter ISO code).
    """

    name = "google_books"
    source_type = SourceType.BOOK
    rate_limited = True   # bina API key ke 429 aa sakta hai

    @staticmethod
    def country() -> str:
        """
        Do-letter ISO code. Galat/adhoora value chup-chaap aage jaane par API
        phir 0 results de deti hai, isliye sirf letters accept karte hain —
        "in", "IND", "1N" jaise inputs par default IN par wapas aate hain.
        """
        code = (os.getenv("GOOGLE_BOOKS_COUNTRY") or "").strip().upper()
        return code if len(code) == 2 and code.isalpha() else "IN"

    def build_params(self, query: str, max_results: int) -> Dict:
        """Alag method taaki offline test assert kar sake ki country ja raha hai."""
        params = {
            "q": query,
            "maxResults": max(1, min(int(max_results), 40)),  # API ki hard limit 40
            "printType": "books",
            "country": self.country(),
        }
        key = (os.getenv("GOOGLE_BOOKS_API_KEY") or "").strip()
        if key:                       # optional — bina key bhi chalta hai
            params["key"] = key
        return params

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        resp = http_get(
            "https://www.googleapis.com/books/v1/volumes",
            params=self.build_params(query, max_results),
        )
        payload = resp.json()
        items = payload.get("items", []) or []
        if not items:
            # "kuch nahi mila" vs "API ne mana kiya" — dono ka farak likho
            total = payload.get("totalItems")
            self.last_note = (
                f"0 results (totalItems={total}, country={self.country()}) — agar "
                f"totalItems 0 hai to sach mein match nahi mila; agar phir bhi "
                f"khaali lage to .env mein GOOGLE_BOOKS_COUNTRY badal kar dekho"
            )
        out: List[SourceRecord] = []
        for item in items:
            info = item.get("volumeInfo") or {}
            access = item.get("accessInfo") or {}
            viewability = (access.get("viewability") or "").upper()
            public_domain = bool(access.get("publicDomain"))
            categories = ", ".join(info.get("categories") or [])
            availability = (
                "full text legally available" if viewability in _FULL_VIEW or public_domain
                else "sirf preview/snippet legally available"
            )
            out.append(SourceRecord(
                title=self._clean(info.get("title")),
                url=self._clean(info.get("infoLink") or info.get("canonicalVolumeLink")),
                snippet=self._clean(
                    f"{info.get('description') or 'No description available.'} "
                    f"[Subject: {categories or 'n/a'}] [Availability: {availability}]"
                ),
                connector=self.name,
                source_type=SourceType.BOOK,
                authors=(info.get("authors") or [])[:8],
                year=self._year(info.get("publishedDate")),
                publisher=self._clean(info.get("publisher"), 200),
                venue=self._clean(categories, 200),
                peer_reviewed=None,           # book ke liye pata nahi — jhooth mat bolo
                full_text_available=viewability in _FULL_VIEW or public_domain,
            ))
        return out


class InternetArchiveConnector(BaseConnector):
    """
    LIVE BUG: ReadTimeout (read timeout=8).

    archive.org ka advancedsearch endpoint pehla byte bhejne mein hi 10-30s le
    sakta hai — 8s bahut kam tha. Ye source content_fetcher ke liye important hai
    (public-domain books ka `_djvu.txt` full text yahin se aata hai), isliye ise
    "slow" maan kar zyada waqt dena sahi hai, hatana nahi.
    """

    name = "internet_archive"
    source_type = SourceType.BOOK
    timeout: Tuple[int, int] = _SLOW_TIMEOUT

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        resp = http_get(
            "https://archive.org/advancedsearch.php",
            params={
                "q": query,
                "fl[]": ["identifier", "title", "description", "creator",
                         "year", "publisher", "mediatype", "subject"],
                "rows": max_results,
                "page": 1,
                "output": "json",
            },
            timeout=self.timeout,
        )
        docs = (resp.json().get("response") or {}).get("docs", []) or []
        out: List[SourceRecord] = []
        for item in docs:
            creator = item.get("creator")
            authors = creator if isinstance(creator, list) else ([creator] if creator else [])
            description = item.get("description")
            if isinstance(description, list):
                description = " ".join(str(d) for d in description)
            mediatype = (item.get("mediatype") or "").lower()
            stype = SourceType.BOOK if mediatype in ("texts", "text") else (
                SourceType.TRANSCRIPT if mediatype in ("movies", "audio") else SourceType.WEB
            )
            subject = item.get("subject")
            if isinstance(subject, list):
                subject = ", ".join(str(s) for s in subject[:5])
            out.append(SourceRecord(
                title=self._clean(item.get("title")),
                url=f"https://archive.org/details/{item.get('identifier', '')}",
                snippet=self._clean(
                    f"{description or 'No description.'} [Subject: {subject or 'n/a'}] "
                    f"[Media: {mediatype or 'unknown'}]"
                ),
                connector=self.name,
                source_type=stype,
                authors=[a for a in authors if a][:8],
                year=self._year(item.get("year")),
                publisher=self._clean(item.get("publisher"), 200),
                full_text_available=mediatype in ("texts", "text"),
            ))
        return out


class OpenLibraryConnector(BaseConnector):
    """LIVE BUG: ConnectTimeout (connect timeout=8) — isliye bada connect window."""

    name = "open_library"
    source_type = SourceType.BOOK
    timeout: Tuple[int, int] = _SLOW_TIMEOUT

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        resp = http_get(
            "https://openlibrary.org/search.json",
            params={"q": query, "limit": max_results,
                    "fields": "title,author_name,first_publish_year,publisher,key,"
                              "subject,ebook_access,edition_count"},
            timeout=self.timeout,
        )
        out: List[SourceRecord] = []
        for item in resp.json().get("docs", []) or []:
            ebook_access = (item.get("ebook_access") or "no_ebook").lower()
            subjects = ", ".join((item.get("subject") or [])[:5])
            publishers = item.get("publisher") or []
            out.append(SourceRecord(
                title=self._clean(item.get("title")),
                url=f"https://openlibrary.org{item.get('key', '')}",
                snippet=self._clean(
                    f"[Subject: {subjects or 'n/a'}] "
                    f"[Editions: {item.get('edition_count', 'n/a')}] "
                    f"[Ebook access: {ebook_access}]"
                ),
                connector=self.name,
                source_type=SourceType.BOOK,
                authors=(item.get("author_name") or [])[:8],
                year=self._year(item.get("first_publish_year")),
                publisher=self._clean(publishers[0] if publishers else "", 200),
                full_text_available=ebook_access in ("public", "full"),
            ))
        return out


class BookConnector:
    """Spec Section 16 ka 'BookConnector' — saare book sources ek facade mein."""

    def __init__(self):
        self.connectors: List[BaseConnector] = [
            InternetArchiveConnector(),
            OpenLibraryConnector(),
            GoogleBooksConnector(),
        ]

    def by_name(self, name: str) -> Optional[BaseConnector]:
        return next((c for c in self.connectors if c.name == name), None)

    def search(self, query: str, max_per_source: int = 3,
               only: Optional[List[str]] = None) -> Dict:
        records: List[SourceRecord] = []
        log: List[Dict] = []
        for connector in self.connectors:
            if only and connector.name not in only:
                continue
            result = connector.safe_search(query, max_per_source)
            records.extend(result["records"])
            log.append({k: v for k, v in result.items() if k != "records"})
        return {"records": records, "log": log}
