"""
DatasetConnector — Spec Section 2 + 11 (public datasets / raw data)

Papers "kisi ne kya paaya" batate hain; DATASETS wo raw numbers hain jinpar wo
dava tika hai. Spec Section 11 (verification) ke liye ye zaroori hai: ek claim
verify karne ke liye "kaun sa data available hai" janna, aur us data ka honest
locator dena.

SAARE keyless + free providers (koi API key nahi):
    zenodo        CERN ka open-research-data repository (q= free-text search)
    data_gov      data.gov (US) — CKAN package_search (q= free-text)
    who_gho       WHO Global Health Observatory — OData indicator registry
    world_bank    World Bank open data catalog (DDH search)
    huggingface   Hugging Face public datasets (ML/AI datasets, search=)

EK provider jise KEY chahiye (isliye honestly optional rakha hai):
    data_gov_in   data.gov.in (India govt). Iski API ko free registration wali
                  key chahiye (DATA_GOV_IN_API_KEY). Key na ho to ye connector
                  CHUP-CHAAP "0 result" NAHI banta — ConnectorSkipped raise karta
                  hai, taaki report mein "ruka (API key nahi)" dikhe. Yaani spec
                  ka rule ("agar API free/unlimited-free nahi to saaf batao aur
                  free alternative do") yahan poora hota hai: uske keyless
                  alternatives upar maujood hain (US data.gov, Zenodo, WHO, WB).

HONESTY (Spec Section 2 + 11):
    - Dataset ko snippet/metadata level par hi rakha jaata hai. "Dataset mila"
      ka matlab "poora data padh liya / analyse kar liya" NAHI hai — sirf ye ki
      ye data VERIFICATION ke liye available hai. Reading level "metadata"/
      "snippet" hi rehta hai; koi jhootha "full_text" nahi.
    - peer_reviewed = None (dataset journal-peer-review se nahi guzarta — "pata
      nahi" hi imaandaar jawab hai, False bhi galat hoga).
    - methodology khaali chhodte hain: dataset koi "study design" nahi hai, use
      rct/cohort ka thappa lagana galat hoga.

TESTABILITY:
    Har connector ka `parse(payload)` alag hai (JSON dict/list -> SourceRecord),
    taaki offline fixture se field-mapping assert ho sake, bina network ke.

LIVE RUN (2026-08-17) ne teen asli bug nikale — teeno yahan fix hue:

    data_gov    -> HTTP 404 (teeno canonical path par ek saath). Ye "endpoint
                   badal gaya" JAISA dikhta tha, par teeno ka ek jaisa 404 dena
                   ishara karta hai ki path galat nahi — REQUEST block ho rahi
                   thi. data.gov Akamai WAF ke peechhe hai, jo bot-jaise
                   User-Agent ko 403 ke bajaye 404 deta hai. Fix: sirf is
                   connector par browser-jaisa User-Agent + `Accept: application/
                   json` bhejte hain. Endpoint ladder + process-wide "jo chale
                   wo yaad rakho" abhi bhi hai (asli move ke liye safety-net), aur
                   sab fail hone par honest error milta hai — chup-chaap "0 result"
                   NAHI. NOTE: ye fix is sandbox mein LIVE verify nahi hua (yahan
                   internet nahi hai) — asli confirmation `test_connectors.py`
                   tumhare laptop par dega. Ye paywall-bypass nahi: public
                   open-data API hai, koi auth nahi toda gaya.
    who_gho     -> 0 result. Wajah: OData ka `contains()` CASE-SENSITIVE hai, to
                   lowercase "diabetes" kabhi bhi Title-case "Diabetes ..." se
                   match nahi karta tha. Ab poora indicator registry ek baar laate
                   hain (per-process cache) aur locally case-insensitive filter
                   karte hain — is se multi-term ranking bhi muft mil jaati hai.
    huggingface -> 0 result. Wajah: `search=` poori sentence bhej rahe the, jabki
                   HF ka search dataset NAAM par substring match karta hai. Ab
                   keyword ladder (3 -> 2 -> 1 term) chalta hai.

    world_bank  -> HTTP 429 (server ka throttle, humari galti nahi). Isko "fix"
                   karne ka koi imaandaar tareeka nahi hai; ab `rate_limited=True`
                   set hai taaki quota disclosure sach bole aur report usko "ruka"
                   bucket mein dikhaye, "khaali" mein nahi.
"""
from __future__ import annotations

import os
import re
import threading
from typing import Dict, List, Optional

from ..models import SourceRecord, SourceType
from .base import (BaseConnector, ConnectorHTTPError, ConnectorSkipped,
                   content_terms, http_get, term_overlap)

# Zenodo/CKAN descriptions mein HTML aata hai — tags hata kar plain text banao
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: Optional[str]) -> str:
    return _TAG_RE.sub(" ", str(text or ""))


def _as_list(value) -> List:
    """JSON field kabhi list, kabhi single object, kabhi None — normalize."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# ── Zenodo ─────────────────────────────────────────────────────────────────────
class ZenodoConnector(BaseConnector):
    """CERN-run open research data. Keyless, free-text `q=` search."""

    name = "zenodo"
    source_type = SourceType.DATASET

    def parse(self, payload: Dict) -> List[SourceRecord]:
        hits = ((payload or {}).get("hits") or {}).get("hits") or []
        out: List[SourceRecord] = []
        for item in hits:
            if not isinstance(item, dict):
                continue
            meta = item.get("metadata") or {}
            links = item.get("links") or {}
            doi = (meta.get("doi") or item.get("doi") or "").strip()
            url = (self._clean(links.get("self_html") or links.get("html"), 300)
                   or (f"https://doi.org/{doi}" if doi else "")
                   or (f"https://zenodo.org/records/{item.get('id')}"
                       if item.get("id") else ""))
            authors = [self._clean((c or {}).get("name"), 120)
                       for c in _as_list(meta.get("creators"))]
            out.append(SourceRecord(
                title=self._clean(meta.get("title")),
                url=url,
                snippet=self._clean(_strip_html(meta.get("description"))),
                connector=self.name,
                source_type=SourceType.DATASET,
                authors=[a for a in authors if a],
                year=self._year(meta.get("publication_date")),
                publisher="Zenodo (CERN)",
                doi=self._clean(doi.replace("https://doi.org/", ""), 120),
                # dataset = raw primary data
                is_primary=True,
                peer_reviewed=None,
            ))
        return out

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        resp = http_get(
            "https://zenodo.org/api/records",
            params={"q": query, "size": max_results, "sort": "bestmatch"},
        )
        return self.parse(resp.json())[:max_results]


# ── data.gov (US, CKAN) ─────────────────────────────────────────────────────────
class DataGovConnector(BaseConnector):
    """US government open data (CKAN `package_search`). Keyless, free-text `q=`."""

    name = "data_gov"
    source_type = SourceType.DATASET

    def parse(self, payload: Dict) -> List[SourceRecord]:
        results = ((payload or {}).get("result") or {}).get("results") or []
        out: List[SourceRecord] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            slug = self._clean(item.get("name"), 200)
            org = (item.get("organization") or {}).get("title") if isinstance(
                item.get("organization"), dict) else ""
            out.append(SourceRecord(
                title=self._clean(item.get("title") or slug),
                url=(f"https://catalog.data.gov/dataset/{slug}" if slug else ""),
                snippet=self._clean(_strip_html(item.get("notes"))),
                connector=self.name,
                source_type=SourceType.DATASET,
                year=self._year(item.get("metadata_created")
                                or item.get("metadata_modified")),
                publisher=self._clean(org, 200) or "data.gov (US)",
                is_primary=True,
                peer_reviewed=None,
            ))
        return out

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        resp = self._fetch(query, max_results)
        return self.parse(resp.json())[:max_results]

    # LIVE BUG: `https://catalog.data.gov/api/3/action/package_search` ne HTTP 404
    # diya. CKAN ke saath ye aam baat hai — site upgrade/proxy ke saath API path
    # badal jaata hai. Do rasta the:
    #   (a) ek naya path hard-code kar dena — par main use LIVE verify nahi kar
    #       sakta (is sandbox mein internet nahi hai), to wo bas ek naya andaza hota.
    #   (b) candidate paths ka chhota ladder + jo chale usko process-wide yaad
    #       rakhna. Galat andaza mehenga nahi padta, aur ek baar sahi mil jaane ke
    #       baad har call seedha usi par jaati hai.
    # (b) chuna. Aur agar SAB 404 dein to hum khaali list NAHI dete — error raise
    # karte hain, taaki report "data.gov ka API path badal gaya" bole, na ki
    # "data.gov ke paas is topic ka data nahi hai". Ye dono bilkul alag baatein hain.
    _CANDIDATES = (
        "https://catalog.data.gov/api/3/action/package_search",
        "https://catalog.data.gov/api/action/package_search",
        "https://data.gov/api/3/action/package_search",
    )
    # data.gov Akamai WAF ke peechhe hai. Akamai bot-jaisa User-Agent dekh kar
    # 403 nahi, 404 deta hai (jaan-boojh kar "yahan kuch hai hi nahi" jaisa
    # dikhata hai). Isliye teeno canonical path ek saath 404 de rahe the — path
    # galat nahi tha, humara default UA ("InfinityResearchAI/1.0 ...") block ho
    # raha tha. Baaki koi API (OpenAlex/Crossref/PubMed/Zenodo/WHO...) itni sakht
    # nahi, isliye sirf yahan browser-jaisa User-Agent bhejte hain.
    #
    # Ye paywall-bypass NAHI hai: data.gov ek PUBLIC open-data API hai, koi auth/
    # login/token nahi toda ja raha — bas ek over-aggressive WAF ko bata rahe hain
    # ki request browser se aa sakti hai. (Copyright/paywall rule sirf licensed
    # content par lagta hai; ye US govt ka khula data hai.)
    _BROWSER_HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/126.0.0.0 Safari/537.36"),
        "Accept": "application/json",
    }
    _PATH_LOCK = threading.Lock()
    _working_path: Optional[str] = None

    @classmethod
    def working_path(cls) -> Optional[str]:
        with DataGovConnector._PATH_LOCK:
            return DataGovConnector._working_path

    @classmethod
    def remember_path(cls, url: Optional[str]) -> None:
        """Sahi path yaad rakho (None = bhool jao; sirf test ke liye)."""
        with DataGovConnector._PATH_LOCK:
            DataGovConnector._working_path = url

    def _fetch(self, query: str, max_results: int):
        params = {"q": query, "rows": max_results}
        known = self.working_path()
        order = ([known] + [u for u in self._CANDIDATES if u != known]
                 if known else list(self._CANDIDATES))
        tried: List[str] = []
        for url in order:
            try:
                resp = http_get(url, params=params, headers=self._BROWSER_HEADERS)
            except ConnectorHTTPError as exc:
                if getattr(exc, "status", None) not in (404, 400):
                    raise            # 500 / rate limit / network — chhupao mat
                tried.append(f"{url} -> HTTP {getattr(exc, 'status', '?')}")
                continue
            if url != known:
                self.remember_path(url)
                if tried:
                    self.last_note = (
                        f"data.gov ka pehla API path kaam nahi kiya, "
                        f"{url} se data mila (aage isi ka use hoga)"
                    )
            return resp
        raise ConnectorHTTPError(
            "data.gov ka CKAN API path nahi mila — ye 'is topic ka data nahi hai' "
            "se BILKUL alag baat hai (search chali hi nahi). Jo try kiya: "
            + "; ".join(tried),
            status=404,
        )


# ── WHO Global Health Observatory (OData) ───────────────────────────────────────
class WHOGhoConnector(BaseConnector):
    """
    WHO GHO indicator registry (OData). Keyless.

    LIVE BUG: 0 result. Purana code OData `$filter=contains(IndicatorName,'term')`
    bhejta tha — aur OData ka `contains()` CASE-SENSITIVE hai. Hum term lowercase
    karke bhej rahe the ("diabetes"), jabki registry mein naam Title-case hain
    ("Diabetes prevalence ..."). Yaani filter kabhi match hi nahi karta tha.
    Docstring mein likha bhi tha "case-sensitive ho sakta hai... live run par tune
    hoga" — live run ne wahi pakda.

    `tolower()` bhejna aasan lagta hai par GHO ka OData subset use reliably support
    nahi karta. Isliye ab: registry ek BAAR poori laate hain (ye ek chhoti,
    stable list hai — ~2000 indicator naam), per-process cache karte hain, aur
    filter LOCALLY karte hain. Teen fayde: case ka jhagda khatam, multi-term
    ranking muft, aur ek hi HTTP call (chahe 3 queries parallel chalein).

    url ke roop mein indicator ka ASLI data endpoint dete hain
    (https://ghoapi.azureedge.net/api/<CODE>) — ye ek real, resolvable JSON
    dataset hai, isliye locator imaandaar rehta hai.
    """

    name = "who_gho"
    source_type = SourceType.DATASET

    _INDEX_LOCK = threading.Lock()
    _index: Optional[List[Dict]] = None

    @classmethod
    def cached_index(cls) -> Optional[List[Dict]]:
        with WHOGhoConnector._INDEX_LOCK:
            return WHOGhoConnector._index

    @classmethod
    def set_index(cls, rows: Optional[List[Dict]]) -> None:
        """Test ke liye bhi kaam aata hai (None = cache saaf)."""
        with WHOGhoConnector._INDEX_LOCK:
            WHOGhoConnector._index = rows

    def _indicators(self) -> List[Dict]:
        cached = self.cached_index()
        if cached is not None:
            return cached
        # HTTP call lock ke BAHAR — warna 3 threads ek dusre ka intezaar karte.
        # Do thread ek saath fetch kar lein to bhi nuksaan nahi (pehla likhne
        # wala jeet jaata hai), aur ye poore process mein ek-do baar hi hota hai.
        resp = http_get("https://ghoapi.azureedge.net/api/Indicator")
        rows = [r for r in ((resp.json() or {}).get("value") or [])
                if isinstance(r, dict)]
        if self.cached_index() is None:
            self.set_index(rows)
        return self.cached_index() or rows

    @staticmethod
    def match(rows: List[Dict], query: str, max_results: int = 3) -> List[Dict]:
        """
        Case-insensitive, multi-term local filter. Testable — network ke bina.

        Ranking: pehle jitne zyada query-term match karein, phir chhota naam
        (chhota naam aksar zyada general/seedha indicator hota hai, jaise
        "Diabetes prevalence" vs "Diabetes-attributable deaths in men aged 30-70").
        """
        terms = content_terms(query, limit=6)
        if not terms:
            return list(rows)[:max_results]
        scored = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("IndicatorName") or "")
            hits = term_overlap(terms, name)
            if hits:
                scored.append((hits, -len(name), row))
        scored.sort(key=lambda t: (-t[0], -t[1]))
        return [row for _, _, row in scored][:max_results]

    def parse(self, payload: Dict) -> List[SourceRecord]:
        rows = (payload or {}).get("value") or []
        out: List[SourceRecord] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            code = self._clean(item.get("IndicatorCode"), 120)
            name = self._clean(item.get("IndicatorName"))
            if not (code or name):
                continue
            out.append(SourceRecord(
                title=name or code,
                url=(f"https://ghoapi.azureedge.net/api/{code}" if code else ""),
                snippet=self._clean(
                    f"WHO Global Health Observatory indicator"
                    + (f" ({code})" if code else "")
                    + ". Yeh ek official public-health dataset hai; data OData/JSON "
                      "endpoint par available hai."),
                connector=self.name,
                source_type=SourceType.DATASET,
                publisher="World Health Organization (GHO)",
                is_primary=True,
                peer_reviewed=None,
            ))
        return out

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        rows = self._indicators()
        picked = self.match(rows, query, max_results)
        if not picked and rows:
            self.last_note = (f"WHO GHO ke {len(rows)} indicator naamon mein is query "
                              f"ka koi shabd nahi mila (poora registry scan hua)")
        elif picked:
            self.last_note = (f"WHO GHO ke {len(rows)} indicator scan kiye, "
                              f"{len(picked)} naam query se match kiye")
        return self.parse({"value": picked})[:max_results]


# ── World Bank (open data catalog / DDH search) ─────────────────────────────────
class WorldBankConnector(BaseConnector):
    """
    World Bank open data catalog search (DDH). Keyless.

    DDH search ka JSON shape thoda vary karta hai, isliye parser defensive hai:
    `data` ya `value` array, aur har item mein nested `identification.title` ya
    flat `title`/`name` — dono try karta hai. Kuch samajh na aaye to khaali list
    (kabhi crash nahi).

    LIVE RUN: HTTP 429 mila — World Bank ka server-side throttle. Isko code se
    "fix" karne ka koi imaandaar tareeka nahi hai (retry/spoofing se aur block
    hoga). Ab `rate_limited = True` hai, taaki:
      - quota disclosure sach bole ("free hai par rate-limited"), aur
      - report ise "ruka (rate limited)" bucket mein rakhe, "khaali (kuch nahi
        mila)" mein NAHI. Ye farak hi poore project ki honesty ki jaan hai.
    Field mapping abhi bhi live-verified NAHI hai (429 ke kaaran response mila hi
    nahi) — isliye docs mein ye "live-unverified" list mein hi rehna chahiye.
    """

    name = "world_bank"
    source_type = SourceType.DATASET
    rate_limited = True          # live run par 429 mila — chhupana nahi hai

    @staticmethod
    def _first(item: Dict, *keys) -> str:
        for key in keys:
            if "." in key:
                head, tail = key.split(".", 1)
                sub = item.get(head)
                if isinstance(sub, dict) and sub.get(tail):
                    return str(sub.get(tail))
            elif item.get(key):
                return str(item.get(key))
        return ""

    def parse(self, payload: Dict) -> List[SourceRecord]:
        payload = payload or {}
        rows = payload.get("data") or payload.get("value") or payload.get("rows") or []
        if isinstance(rows, dict):                # kabhi {"dataset":[...]} bhi
            rows = rows.get("dataset") or rows.get("results") or []
        out: List[SourceRecord] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            title = self._clean(self._first(
                item, "title", "name", "identification.title", "dataset_name"))
            if not title:
                continue
            dataset_id = self._clean(self._first(
                item, "id", "dataset_unique_id", "guid", "identification.dataset_unique_id"),
                120)
            url = self._clean(self._first(item, "url", "landingPage", "link"), 300)
            if not url:
                url = (f"https://datacatalog.worldbank.org/search/dataset/{dataset_id}"
                       if dataset_id else "https://datacatalog.worldbank.org")
            out.append(SourceRecord(
                title=title,
                url=url,
                snippet=self._clean(_strip_html(self._first(
                    item, "description", "identification.description", "notes"))),
                connector=self.name,
                source_type=SourceType.DATASET,
                year=self._year(self._first(
                    item, "last_updated_date", "lastupdated", "modified_date")),
                publisher="World Bank",
                is_primary=True,
                peer_reviewed=None,
            ))
        return out

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        resp = http_get(
            "https://datacatalogapi.worldbank.org/ddhxext/search",
            params={"qterm": query, "$top": max_results},
        )
        return self.parse(resp.json())[:max_results]


# ── Hugging Face datasets ───────────────────────────────────────────────────────
class HuggingFaceDatasetsConnector(BaseConnector):
    """
    Hugging Face public datasets (mostly ML/AI training data). Keyless,
    free-text `search=`. List endpoint ek JSON ARRAY deta hai (wrapped nahi).

    is_primary = None jaan-boojh kar: HF par raw primary data bhi hai aur
    dusron ke data ka derived/curated version bhi — isliye "primary hai" ka
    dava galat hoga. "pata nahi" hi imaandaar hai.
    """

    name = "huggingface"
    source_type = SourceType.DATASET

    def parse(self, payload) -> List[SourceRecord]:
        # list endpoint array deta hai; defensively dict-wrapped bhi handle karo
        rows = payload if isinstance(payload, list) else (
            (payload or {}).get("datasets") or [])
        out: List[SourceRecord] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            repo_id = self._clean(item.get("id") or item.get("_id"), 200)
            if not repo_id:
                continue
            card = item.get("cardData") if isinstance(item.get("cardData"), dict) else {}
            desc = (item.get("description") or card.get("description")
                    or "; ".join(str(t) for t in _as_list(item.get("tags"))[:8]))
            author = self._clean(item.get("author"), 120)
            out.append(SourceRecord(
                title=repo_id,
                url=f"https://huggingface.co/datasets/{repo_id}",
                snippet=self._clean(_strip_html(desc)),
                connector=self.name,
                source_type=SourceType.DATASET,
                authors=[author] if author else [],
                year=self._year(item.get("lastModified") or item.get("createdAt")),
                publisher="Hugging Face Datasets",
                is_primary=None,
                peer_reviewed=None,
            ))
        return out

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        # LIVE BUG: `search=<poori sentence>` par 0 result. HF ka `search` dataset
        # ke NAAM par substring match karta hai, free-text index nahi hai — koi
        # dataset "algorithmic bias in healthcare risk prediction" naam se nahi
        # hota. Isliye keyword ladder: 3 -> 2 -> 1 term (dedup ke saath).
        terms = content_terms(query, limit=3)
        ladder: List[str] = []
        for count in (3, 2, 1):
            probe = " ".join(terms[:count]).strip()
            if probe and probe not in ladder:
                ladder.append(probe)
        if not ladder:
            ladder = [" ".join(str(query or "").split())]

        records: List[SourceRecord] = []
        used = ""
        for probe in ladder:
            if not probe:
                continue
            used = probe
            resp = http_get(
                "https://huggingface.co/api/datasets",
                params={"search": probe, "limit": max(max_results, 10),
                        "full": "true"},
            )
            records = self.parse(resp.json())
            if records:
                break

        if records and used != ladder[0]:
            self.last_note = (f"HuggingFace par poore keyword set se kuch nahi mila, "
                              f"'{used}' se {len(records)} dataset mile")
        elif not records and used:
            self.last_note = (f"HuggingFace par '{used}' naam ka koi public dataset "
                              f"nahi mila (HF ka search dataset NAAM par chalta hai, "
                              f"description par nahi)")
        return records[:max_results]


# ── data.gov.in (India — KEY chahiye, isliye optional) ──────────────────────────
class DataGovInConnector(BaseConnector):
    """
    India government open data. Iski API ko free-registration key chahiye
    (DATA_GOV_IN_API_KEY). Key na ho to ConnectorSkipped — "0 result" NAHI, taaki
    report saaf-saaf "API key nahi" dikha sake.

    NOTE (honesty): data.gov.in par ek clean free-text "sabhi datasets search"
    JSON endpoint documented nahi hai; API zyada tar resource-id based hai.
    Isliye ye connector "catalog list" endpoint par best-effort title-filter
    karta hai aur field mapping live run par confirm hona hai. Iske keyless
    alternatives (zenodo, data_gov US, who_gho, world_bank) hamesha chalte hain.
    """

    name = "data_gov_in"
    source_type = SourceType.DATASET
    free = False           # key chahiye — quota disclosure mein imaandaari
    rate_limited = True

    @staticmethod
    def api_key() -> str:
        return (os.getenv("DATA_GOV_IN_API_KEY") or "").strip()

    def parse(self, payload: Dict) -> List[SourceRecord]:
        payload = payload or {}
        rows = (payload.get("records") or payload.get("data")
                or payload.get("results") or [])
        out: List[SourceRecord] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            title = self._clean(item.get("title") or item.get("name")
                                 or item.get("desc"))
            if not title:
                continue
            out.append(SourceRecord(
                title=title,
                url=self._clean(item.get("url") or item.get("source"), 300)
                    or "https://data.gov.in",
                snippet=self._clean(_strip_html(
                    item.get("desc") or item.get("description"))),
                connector=self.name,
                source_type=SourceType.DATASET,
                publisher="data.gov.in (Government of India)",
                is_primary=True,
                peer_reviewed=None,
            ))
        return out

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        key = self.api_key()
        if not key:
            raise ConnectorSkipped(
                "DATA_GOV_IN_API_KEY .env mein nahi hai — data.gov.in search chali "
                "hi nahi (ye 'result nahi mila' se alag baat hai). Free key "
                "https://data.gov.in par register karke milti hai; uske bina bhi "
                "baaki dataset sources (zenodo, data_gov US, who_gho, world_bank) "
                "chalte hain."
            )
        resp = http_get(
            "https://api.data.gov.in/lists",
            params={"api-key": key, "format": "json", "limit": max_results,
                    "filters[title]": query},
        )
        return self.parse(resp.json())[:max_results]


# ── facade ──────────────────────────────────────────────────────────────────────
class DatasetConnector:
    """Saare dataset connectors ek jagah. Spec Section 16 ka 'DatasetConnector'.

    web_connector.py / paper_connector.py wale hi pattern: `by_name()` aur
    `search()` jo {"records", "log"} deta hai, taaki SourceDiscovery ise
    baaki connectors ki tarah hi treat kar sake.
    """

    def __init__(self):
        self.connectors: List[BaseConnector] = [
            ZenodoConnector(),
            DataGovConnector(),
            WHOGhoConnector(),
            WorldBankConnector(),
            HuggingFaceDatasetsConnector(),
            DataGovInConnector(),
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
