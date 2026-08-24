"""ClassicTextConnector — public-domain / khuli-licence wale MOOL TEXT ka lane.

Kyun alag connector: baaki book connectors CATALOGUE dhoondhte hain (metadata,
availability). Ye lane us text ke liye hai jo ASLI ME padha ja sakta hai —
granth, purane classic, mahan logon ka apna likha hua jo public domain me hai.

Kaise: sirf Wikimedia ka apna **official MediaWiki action API**. Koi HTML
scraping nahi, koi third-party mirror nahi, koi API key nahi (§2 ka rule:
"unofficial APIs ya scraping bypass nahi").

Jaan-boojhkar SHAAMIL NAHI:
  * gutendex.com aur baaki Gutenberg "API" — ye third-party wrapper hain,
    Gutenberg ka apna search sirf HTML page hai. Isliye Gutenberg is lane me
    SEARCH ka source nahi hai; wo sirf READING route hai (content_fetcher me),
    jab uska URL kisi aur jagah se pehle hi mil chuka ho.
  * shadow library (libgen/sci-hub/annas-archive...) — ``classics.py`` inhe
    host level par mana karta hai, aur yahan bhi kabhi query nahi jaati.

Honesty: ye connector jo record deta hai unpar ``full_text_available=True`` tab
hi lagta hai jab us page ka apna text API se seedha milta hai. "Text mil sakta
hai" ka matlab "text padh liya" nahi — padhna ``content_fetcher`` ka kaam hai
aur wahan alag se likha jaata hai kitna padha.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from ..models import SourceRecord, SourceType
from .base import SLOW_TIMEOUT, BaseConnector, http_get

# Wikisource ke language subdomain. Ye "topic list" nahi hai — bhasha ka pata
# hai. Default sirf `en` (transliterated Hinglish query par Devanagari wiki se
# match nahi milta, aur bekaar HTTP call time kharch karti hai). Jise chahiye wo
# .env me WIKISOURCE_LANGS="en,sa,hi" kar sakta hai.
_DEFAULT_LANGS = ("en",)
_KNOWN_LANGS = ("en", "sa", "hi", "mr", "bn", "ta", "te", "kn", "gu", "pa",
                "or", "ml", "as", "ne", "fa", "ar", "he", "el", "la", "de",
                "fr", "es", "it", "ru", "zh", "ja")


def wikisource_langs() -> Tuple[str, ...]:
    """Env se bhasha list — galat/anjaan code chup-chaap gir jaata hai."""
    raw = (os.getenv("WIKISOURCE_LANGS") or "").strip()
    if not raw:
        return _DEFAULT_LANGS
    picked = tuple(part.strip().lower() for part in raw.replace(";", ",").split(",")
                   if part.strip().lower() in _KNOWN_LANGS)
    return picked or _DEFAULT_LANGS


class WikisourceConnector(BaseConnector):
    """Wikisource ka official action API — mool text ka sabse saaf free raasta.

    Ek hi call me search + text: ``generator=search`` ke saath
    ``prop=extracts&explaintext``, isliye snippet HTML nahi, saaf text hota hai.
    """

    name = "wikisource"
    source_type = SourceType.BOOK
    timeout: Tuple[int, int] = SLOW_TIMEOUT

    def __init__(self, lang: str = "en"):
        self.lang = (lang or "en").strip().lower() or "en"
        # naam me bhasha rehti hai taaki log/report me pata chale kaunsi wiki
        self.name = "wikisource" if self.lang == "en" else f"wikisource_{self.lang}"

    @property
    def api_url(self) -> str:
        return f"https://{self.lang}.wikisource.org/w/api.php"

    def build_params(self, query: str, max_results: int) -> Dict:
        """Alag method taaki offline test bina network ke params check kar sake."""
        return {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "generator": "search",
            "gsrsearch": query,
            "gsrlimit": max(1, min(int(max_results), 10)),
            "gsrnamespace": "0",           # sirf mool text pages, Talk/Author nahi
            "prop": "extracts|info",
            "explaintext": "1",
            "exintro": "0",
            "exchars": "1200",             # snippet ke liye itna kaafi
            "inprop": "url",
        }

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        resp = http_get(self.api_url, params=self.build_params(query, max_results),
                        timeout=self.timeout)
        payload = resp.json() if hasattr(resp, "json") else {}
        pages = ((payload.get("query") or {}).get("pages") or [])
        if isinstance(pages, dict):        # formatversion=1 ka purana shape
            pages = list(pages.values())
        out: List[SourceRecord] = []
        for page in pages:
            if not isinstance(page, dict):
                continue
            title = self._clean(page.get("title"))
            if not title:
                continue
            extract = self._clean(page.get("extract"), 1200)
            url = self._clean(page.get("fullurl")) or (
                f"https://{self.lang}.wikisource.org/wiki/"
                f"{str(page.get('title') or '').replace(' ', '_')}")
            out.append(SourceRecord(
                title=title,
                url=url,
                snippet=extract or "(is page ka text API se khaali aaya)",
                connector=self.name,
                source_type=SourceType.BOOK,
                publisher=f"Wikisource ({self.lang})",
                # Wikisource par text page ka apna text hota hai, isliye full-text
                # ka raasta hai. Kitna padha — wo content_fetcher likhta hai.
                full_text_available=bool(extract),
                peer_reviewed=None,        # granth peer-reviewed nahi hota
                read_level="snippet",      # abhi sirf extract mila hai
            ))
        if not out:
            self.last_note = (f"{self.lang}.wikisource par is query ke liye koi "
                              f"mool-text page nahi mila")
        return out


class ClassicTextConnector:
    """Facade — ``BookConnector`` ke jaisa hi interface, taaki wiring same rahe."""

    def __init__(self, langs: Optional[Tuple[str, ...]] = None):
        chosen = tuple(langs) if langs else wikisource_langs()
        self.connectors: List[BaseConnector] = [
            WikisourceConnector(lang=lang) for lang in chosen
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
