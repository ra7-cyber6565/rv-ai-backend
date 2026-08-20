"""
PaperConnector — Spec Section 2 + 3 (research papers)

Sab free, koi API key nahi:
    arXiv            preprints        (peer_reviewed = False — honestly)
    OpenAlex         240M+ works      (metadata + citation counts)
    Crossref         DOI metadata
    DOAJ             open-access peer-reviewed journals
    PubMed/NCBI      medical/biology
    Semantic Scholar bina key ke rate-limited (429) — ab honestly "rate limited"
                     report hota hai, "0 results" nahi

Purane rag/academic_sources.py se farak: yahan sirf title/snippet/url nahi,
balki author, year, publisher, venue, DOI, citation count aur peer-review status
bhi nikalta hai — kyunki EvidenceEngine ko source quality judge karni hoti hai.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional

from ..models import SourceRecord, SourceType
from ..quality_signals import (
    methodology_from_pubtypes,
    methodology_from_text,
    methodology_from_work_type,
    retraction_from_crossref,
    retraction_from_pubtypes,
    retraction_from_text,
)
from .base import (BaseConnector, ConnectorHTTPError, content_terms, http_get,
                   select_terms, term_overlap)


def domain_filter(records: List[SourceRecord], query: str) -> List[SourceRecord]:
    """
    §2 ka domain guard, connector level par.

    Lexical overlap kaafi nahi hai: "Room-temperature ferroelectricity in ..."
    query se 2 term share karta hai (room, temperature) par superconductivity
    ka koi anchor nahi rakhta. Field pata ho (strict profile) to anchor-less
    result yahin gir jaata hai — aage padhne ka waqt bhi bachta hai.

    Domain pata na ho to kuch nahi hatta (bina samajh ke filter karna andha
    filter hai).
    """
    if not records:
        return records
    try:
        from ..domain import detect as _detect
        plan = _detect(query or "")
        if not plan.strict:
            return records
        return [r for r in records
                if not plan.assess(r.title, r.snippet).rejected]
    except Exception:
        return records


# ── arXiv ────────────────────────────────────────────────────────────────────
class ArxivConnector(BaseConnector):
    """
    LIVE BUG (2026-08-17) jo test ne "OK" bata diya tha:

        query : "algorithmic bias in healthcare risk prediction"
        result: "Sequential Design and Spatial Modeling for Portfolio Tail
                 Risk Measurement"

    Field mapping bilkul theek tha — is liye connector test PASS dikha raha tha.
    Galti query BANANE mein thi: `search_query=all:<poori sentence>` bhejne par
    arXiv usko dheela match karta hai (aur default sort submission date hai),
    to sirf "risk" jaisa ek shabd match hone par bhi paper aa jaata hai.

    Do-parat fix:
      1. Query ko content words mein toda aur AND se joda ->
         all:"algorithmic" AND all:"bias" AND all:"healthcare" ...
         Saath mein sortBy=relevance. Zyada terms se 0 result aaye to
         apne aap terms ghata kar dobara try karta hai (ladder 5 -> 3 -> 1;
         2 par rukna bhi bug tha: `all:"diabetes" AND all:"ilaj"` hamesha 0 hai,
         par sirf `all:"diabetes"` se asli papers milte hain).
      2. Local relevance guard: jo record query se 2 se kam terms share kare
         use girao. Kyunki galat paper ka aana khaali haath se ZYADA bura hai —
         wo aage citation ban sakta hai.

    arXiv ki 3-second guideline: pehle sirf ladder ke andar sleep tha, par
    SourceDiscovery arXiv ko ek round mein 3 queries ke liye 3 THREADS mein
    chalata hai — yaani ek hi second mein 3 requests, guideline toot rahi thi.
    Ab `_throttle()` poore process ke liye lock ke saath gap rakhta hai.
    """

    name = "arxiv"
    source_type = SourceType.PAPER
    _NS = {"atom": "http://www.w3.org/2005/Atom"}
    _ARXIV_NS = {"arxiv": "http://arxiv.org/schemas/atom"}

    # process-wide politeness (threads ke aar-paar bhi)
    _REQUEST_LOCK = threading.Lock()
    _MIN_GAP_SECONDS = 3.0
    _last_request_at = 0.0

    @classmethod
    def _throttle(cls) -> float:
        """arXiv ko dhakka na do: do requests ke beech >= 3s. Kitna ruke, wo return."""
        with ArxivConnector._REQUEST_LOCK:
            waited = 0.0
            gap = time.time() - ArxivConnector._last_request_at
            if gap < cls._MIN_GAP_SECONDS:
                waited = cls._MIN_GAP_SECONDS - gap
                time.sleep(waited)
            ArxivConnector._last_request_at = time.time()
            return waited

    @staticmethod
    def anchor_terms(query: str, limit: int = 2) -> List[str]:
        """Is query ke domain anchors (domain.py se) — search ke liye."""
        try:
            from ..domain import anchor_terms as _anchors
            return [a for a in _anchors(query or "", limit) if a]
        except Exception:
            return []

    @classmethod
    def build_search_query(cls, query: str, max_terms: int = 5) -> str:
        """
        Testable — network ke bina bhi assert kar sakte hain.

        §4 ka fix: query dheeli karte waqt bhi DOMAIN ANCHOR nahi girta.
        Pehle ladder ka aakhri step query ka PEHLA content term le leta tha:

            query : "room-temperature superconductivity ambient pressure"
            step 3: all:"room-temperature"        <- anchor gaayab
            result: "Room-temperature FERROELECTRICITY..."   (galat field)

        Ab anchor sabse aage rehta hai:

            step 3: all:"superconductivity"
        """
        terms = select_terms(query, max_terms=max_terms)
        anchors = cls.anchor_terms(query, limit=1 if max_terms <= 2 else 2)
        if anchors:
            merged: List[str] = []
            for term in anchors + terms:
                if term not in merged:
                    merged.append(term)
            keep = max(max_terms, len(anchors))
            if len(merged) > keep:
                if keep <= 1:
                    merged = merged[:1]          # sirf anchor — ye ladder ka aakhri step
                else:
                    # select_terms ki tarah aakhri (steering) term bacha kar rakho
                    merged = merged[: keep - 1] + [merged[-1]]
            terms = merged
        if not terms:
            cleaned = " ".join(str(query or "").split())
            return f'all:"{cleaned}"'
        return " AND ".join(f'all:"{term}"' for term in terms)

    def parse(self, xml_payload) -> List[SourceRecord]:
        """XML -> SourceRecord. Alag method, taaki offline fixture se test ho sake."""
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml_payload)
        out: List[SourceRecord] = []
        for entry in root.findall("atom:entry", self._NS):
            title_el = entry.find("atom:title", self._NS)
            summary_el = entry.find("atom:summary", self._NS)
            id_el = entry.find("atom:id", self._NS)
            published_el = entry.find("atom:published", self._NS)
            authors = [
                a.findtext("atom:name", default="", namespaces=self._NS)
                for a in entry.findall("atom:author", self._NS)
            ]
            doi_el = entry.find("arxiv:doi", self._ARXIV_NS)
            out.append(SourceRecord(
                title=self._clean(title_el.text if title_el is not None else ""),
                url=self._clean(id_el.text if id_el is not None else ""),
                snippet=self._clean(summary_el.text if summary_el is not None else ""),
                connector=self.name,
                source_type=SourceType.PAPER,
                authors=[a for a in authors if a],
                year=self._year(published_el.text if published_el is not None else None),
                venue="arXiv (preprint)",
                doi=self._clean(doi_el.text) if doi_el is not None else "",
                # IMPORTANT: preprint peer-reviewed NAHI hota — jhooth mat bolo
                peer_reviewed=False,
                is_primary=True,
                full_text_available=True,
            ))
        return out

    @staticmethod
    def relevance_guard(records: List[SourceRecord], query: str,
                        used_terms: Optional[int] = None) -> List[SourceRecord]:
        """
        Query se bilkul unrelated records hatao.
        Bar: 3+ term wali query mein kam se kam 2 term match hone chahiye
        (1 term ka bar bahut dheela hai — sirf "risk" match hone par
        portfolio-risk ka paper healthcare-bias query mein ghus jaata hai).

        `used_terms` = ladder ke jis step se result MILE, usme kitne term the.
        Ye jodna zaroori tha, warna ladder ka poora fayda guard khud kha jaata —
        aur ye bug seedha Hinglish queries par lagta tha:

            query : "diabetes ka permanent ilaj kya hai"
            terms : ["diabetes", "permanent", "ilaj"]      -> bar = 2
            step 1: all:"diabetes" AND all:"permanent" AND all:"ilaj"  -> 0
            step 2: all:"diabetes"                        -> sahi paper mila
            guard : title mein "ilaj" kabhi nahi hoga (wo Hindi shabd hai),
                    yaani match 1, bar 2 -> SAHI paper bhi gir gaya

        Nateeja: ladder relax hota tha, asli paper aata tha, aur guard use
        chupchaap phenk kar "sab topic se door the" bata deta tha. Ab bar us
        query se zyada sakht nahi hota jo asal mein chali thi.
        """
        terms = content_terms(query, limit=6)
        if not terms:
            return domain_filter(records, query)
        needed = 2 if len(terms) >= 3 else 1
        if used_terms:
            needed = min(needed, max(1, used_terms))
        return domain_filter([
            r for r in records
            if term_overlap(terms, f"{r.title} {r.snippet}") >= needed
        ], query)

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        total_terms = len(content_terms(query, limit=None))
        # strict -> dheela. Har step par ek hi baar (dedup), aur aakhir mein
        # single-term try — kyunki 2-term AND bhi kai baar pakka 0 hota hai.
        ladder: List[int] = []
        for step in (5, 3, 1):
            value = min(step, total_terms) if total_terms else 1
            if value not in ladder:
                ladder.append(value)

        records: List[SourceRecord] = []
        used = ""
        used_terms = ladder[0] if ladder else 0
        relaxed = False
        for count in ladder:
            self._throttle()          # 3s guideline, threads ke aar-paar bhi
            used = self.build_search_query(query, max_terms=count)
            resp = http_get("https://export.arxiv.org/api/query", params={
                "search_query": used,
                "start": 0,
                # thoda extra maango — guard kuch girayega
                "max_results": max(max_results, min(max_results * 2, 20)),
                "sortBy": "relevance",
                "sortOrder": "descending",
            })
            records = self.parse(resp.content)
            used_terms = count
            relaxed = count != ladder[0]
            if records:
                break

        raw_count = len(records)
        kept = self.relevance_guard(records, query, used_terms=used_terms)
        # ZAROORI: dropped SIRF guard ka hisaab hai. Pehle ye `[:max_results]`
        # ke BAAD nikala jaata tha, to max_results ki normal limit ka blame bhi
        # guard par chala jaata tha — 6 sahi results par bhi note kehta tha
        # "6 mein se 3 relevance guard se hataye", jo saraasar jhooth tha
        # (guard ne ek bhi nahi hataya tha). Ye har successful search par lagta tha.
        dropped = raw_count - len(kept)
        capped = max(0, len(kept) - max_results)
        records = kept[:max_results]

        notes: List[str] = []
        if dropped and not records:
            # sab kuch guard ne hataya — ye "duniya mein kuch nahi mila" NAHI hai
            self.last_reason = "filtered"
            notes.append(f"arXiv se {raw_count} result aaye par sabhi topic se "
                         f"door the (relevance guard ne hataye) — ye '0 result' "
                         f"se alag baat hai")
        elif dropped:
            notes.append(f"{raw_count} arXiv result mein se {dropped} relevance "
                         f"guard ne hataye" +
                         (f", {capped} max_results limit se bahar" if capped else ""))
        elif capped:
            notes.append(f"arXiv se {raw_count} relevant result mile, "
                         f"max_results={max_results} ki limit lagi "
                         f"(relevance guard ne kuch nahi hataya)")
        elif raw_count == 0 and used:
            notes.append(f"arXiv par is query ke liye kuch nahi mila ({used})")
        if relaxed and records:
            # user ko pata rahe ki match dheela tha — ye quality ka signal hai
            notes.append(f"strict AND query par kuch nahi mila, isliye {used_terms} "
                         f"term wali dheeli query chali ({used})")
        if notes:
            self.last_note = "; ".join(notes)
        return records


# ── OpenAlex ─────────────────────────────────────────────────────────────────
class OpenAlexConnector(BaseConnector):
    name = "openalex"
    source_type = SourceType.PAPER

    @staticmethod
    def _abstract(inverted: Optional[dict]) -> str:
        if not inverted:
            return ""
        pairs = [(pos, word) for word, positions in inverted.items() for pos in positions]
        pairs.sort()
        return " ".join(word for _, word in pairs)[:1200]

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        resp = http_get(
            "https://api.openalex.org/works",
            params={"search": query, "per_page": max_results},
        )
        out: List[SourceRecord] = []
        for item in resp.json().get("results", []):
            location = (item.get("primary_location") or {}).get("source") or {}
            venue_type = (location.get("type") or "").lower()
            work_type = (item.get("type") or "").lower()
            authors = [
                (a.get("author") or {}).get("display_name", "")
                for a in item.get("authorships", [])[:8]
            ]
            peer = True if (venue_type == "journal" and work_type == "article") else None
            title = self._clean(item.get("title") or item.get("display_name"))
            abstract = self._clean(self._abstract(item.get("abstract_inverted_index")))
            out.append(SourceRecord(
                title=title,
                url=self._clean(item.get("doi") or item.get("id")),
                snippet=abstract,
                connector=self.name,
                source_type=SourceType.PAPER,
                authors=[a for a in authors if a],
                year=self._year(item.get("publication_year")),
                venue=self._clean(location.get("display_name"), 200),
                publisher=self._clean(location.get("host_organization_name"), 200),
                doi=self._clean((item.get("doi") or "").replace("https://doi.org/", ""), 120),
                peer_reviewed=peer,
                citation_count=item.get("cited_by_count"),
                full_text_available=bool((item.get("open_access") or {}).get("is_oa")),
                # Spec Section 7: OpenAlex ka `type` sirf form batata hai
                # (article/review/editorial), design nahi — isliye pehle usse
                # try karo, na mile to abstract mein likha design dekho.
                methodology=(methodology_from_work_type(work_type)
                             or methodology_from_text(f"{title} {abstract}")),
                # OpenAlex `is_retracted` field deta hai — jab wo saaf True ho
                # tabhi True bolo, warna None (pata nahi).
                retracted=(True if item.get("is_retracted") is True
                           else retraction_from_text(title)),
            ))
        return out


# ── Semantic Scholar ─────────────────────────────────────────────────────────
class SemanticScholarConnector(BaseConnector):
    """
    Bina key ke ye API 429 (rate limit) deta hai. Pehle wo silently "0 results"
    ban jaata tha — jo JHOOTH hai: search chali hi nahi thi, isliye "kuch nahi
    mila" kehna galat hai. Ab base.http_get 429 par RateLimited raise karta hai
    aur reason final log tak jaata hai.

    Free API key (Semantic Scholar khud free deta hai) .env mein
    SEMANTIC_SCHOLAR_API_KEY=... daal do to header apne aap lag jayega.
    """

    name = "semantic_scholar"
    source_type = SourceType.PAPER
    rate_limited = True   # bina key ke 429 aata hai

    @staticmethod
    def api_key() -> str:
        return (os.getenv("SEMANTIC_SCHOLAR_API_KEY") or "").strip()

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        key = self.api_key()
        resp = http_get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query": query,
                "limit": max_results,
                "fields": "title,abstract,url,year,authors,venue,externalIds,"
                          "citationCount,publicationTypes,isOpenAccess",
            },
            # key ho to bhejo; na ho to header hi nahi lagta (base None/"" chhod deta hai)
            headers={"x-api-key": key} if key else None,
        )
        data = resp.json().get("data", []) or []
        if not data and not key:
            self.last_note = ("0 results — bina free API key ke Semantic Scholar "
                              "aksar khaali/limited jawab deta hai "
                              "(.env mein SEMANTIC_SCHOLAR_API_KEY daal sakte ho)")
        out: List[SourceRecord] = []
        for item in data:
            pub_types = [str(t).lower() for t in (item.get("publicationTypes") or [])]
            ext = item.get("externalIds") or {}
            peer = True if "journalarticle" in pub_types else (
                False if "preprint" in pub_types else None
            )
            title = self._clean(item.get("title"))
            abstract = self._clean(item.get("abstract"))
            out.append(SourceRecord(
                title=title,
                url=self._clean(item.get("url")),
                snippet=abstract,
                connector=self.name,
                source_type=SourceType.PAPER,
                authors=[a.get("name", "") for a in (item.get("authors") or [])[:8]],
                year=self._year(item.get("year")),
                venue=self._clean(item.get("venue"), 200),
                doi=self._clean(ext.get("DOI"), 120),
                peer_reviewed=peer,
                citation_count=item.get("citationCount"),
                full_text_available=bool(item.get("isOpenAccess")),
                # Spec Section 7 — S2 ke publicationTypes camelCase mein aate
                # hain ("MetaAnalysis"), quality_signals unhe handle karta hai
                methodology=(methodology_from_pubtypes(pub_types)
                             or methodology_from_text(f"{title} {abstract}")),
                retracted=retraction_from_text(title),
            ))
        return out


# ── Crossref ─────────────────────────────────────────────────────────────────
class CrossrefConnector(BaseConnector):
    """
    LIVE BUG (2026-08-17): 2025 ke ek SSRN DOI par year=None aaya.

    Do wajah thi. (1) Code sirf `published-print` / `published-online` dekh raha
    tha — preprint/report records mein wo dono khaali hote hain, date `published`
    ya `issued` ya `created` mein hoti hai. (2) `select` param mein wo fields
    maangi hi nahi gayi thi, to Crossref unhe bhejta bhi nahi — fallback likhne
    par bhi kaam nahi karta.

    year=None sasta bug nahi hai: recency scoring aur contradiction engine ka
    "purana vs naya" check dono usi par khade hain.
    """

    name = "crossref"
    source_type = SourceType.PAPER
    # Order maayne rakhta hai. Crossref ka `published`/`issued` = print aur online
    # mein se SABSE PEHLI date. `published-print` pehle rakhna galat tha: jo paper
    # 2024 mein online aur 2025 mein print hua, uska saal 2025 dikhta tha — yaani
    # recency scoring paper ko asli se naya samajh leti. Isliye pehle "earliest
    # true publication", aur `created` (Crossref record banne ki date) sabse aakhir.
    _DATE_FIELDS = ("published", "issued", "published-online", "published-print",
                    "created")
    # Ye list se hi `select` string banti hai — dono ek jagah rakhne ka fayda:
    # test seedhe check kar sakta hai ki har _DATE_FIELDS wali field maangi bhi
    # gayi hai (Crossref jo field select mein nahi hai, wo bhejta hi nahi).
    _SELECT_FIELDS = ("title", "author", "published", "issued", "published-print",
                      "published-online", "created", "publisher", "container-title",
                      "DOI", "URL", "type", "subtype", "abstract",
                      "is-referenced-by-count", "update-to", "updated-by")
    _SELECT = ",".join(_SELECT_FIELDS)

    # LIVE BUG (2026-08-17, doosra round): isi connector ne HTTP 400 dena shuru
    # kar diya. Wajah hum khud the — retraction detection ke liye `subtype`,
    # `update-to`, `updated-by` select list mein jode gaye the. Crossref ka
    # `select` ek FIXED whitelist hai: usme se ek bhi field wo na pehchane to
    # poori request 400 ho jaati hai, yaani ek naye field ne poora connector
    # gira diya (pehle wale live run mein crossref theek chal raha tha).
    #
    # Do galat raste the: (a) risky fields hata dena — phir Crossref se
    # retraction metadata milna band ho jaata; (b) select hi na bhejna — har
    # request mein poore records (reference list ke saath) aate, bandwidth
    # bekaar jaati. Isliye teesra rasta: select ke saath try karo, aur SIRF 400
    # par bina select dobara maango. Bina select ke Crossref poora record deta
    # hai, jisme ye teeno field pehle se hote hain — yaani kuch feature nahi
    # khota. Flag process-bhar ke liye yaad rakhte hain, warna har query do
    # HTTP call kharch karti.
    _SELECT_LOCK = threading.Lock()
    _select_supported = True

    @classmethod
    def select_supported(cls) -> bool:
        with CrossrefConnector._SELECT_LOCK:
            return CrossrefConnector._select_supported

    @classmethod
    def disable_select(cls) -> None:
        """400 dekhne ke baad poore process mein select bhejna band."""
        with CrossrefConnector._SELECT_LOCK:
            CrossrefConnector._select_supported = False

    @classmethod
    def reset_select(cls) -> None:
        """Sirf test ke liye — process-wide flag saaf karo."""
        with CrossrefConnector._SELECT_LOCK:
            CrossrefConnector._select_supported = True

    def _fetch(self, query: str, max_results: int):
        params = {"query": query, "rows": max_results}
        if self.select_supported():
            try:
                return http_get("https://api.crossref.org/works",
                                params=dict(params, select=self._SELECT))
            except ConnectorHTTPError as exc:
                if getattr(exc, "status", None) != 400:
                    raise          # asli server/network problem — chhupao mat
                self.disable_select()
                self.last_note = (
                    "Crossref ne `select` field-list reject ki (HTTP 400) — "
                    "poore records maang kar kaam chalaya. Data poora hai, "
                    "sirf response bada aata hai."
                )
        return http_get("https://api.crossref.org/works", params=params)

    @classmethod
    def pick_year(cls, item: Dict) -> Optional[int]:
        """Testable — canned item se saal nikaalta hai, network ke bina."""
        for field in cls._DATE_FIELDS:
            block = item.get(field)
            if not isinstance(block, dict):   # kuch records mein ye list aata hai
                continue
            parts = block.get("date-parts") or []
            first = parts[0] if parts and isinstance(parts[0], (list, tuple)) else []
            year = BaseConnector._year(first[0] if first else None)
            if year:
                return year
            # kuch records mein sirf string date hoti hai
            year = BaseConnector._year(block.get("date-time"))
            if year:
                return year
        return None

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        resp = self._fetch(query, max_results)
        out: List[SourceRecord] = []
        retraction_hits = 0
        for item in resp.json().get("message", {}).get("items", []):
            titles = item.get("title") or []
            containers = item.get("container-title") or []
            authors = [
                " ".join(x for x in [a.get("given", ""), a.get("family", "")] if x).strip()
                for a in (item.get("author") or [])[:8]
            ]
            item_type = (item.get("type") or "").lower()
            title = self._clean(titles[0] if titles else "")
            snippet = self._clean(item.get("abstract") or
                                  f"{item_type or 'work'} published by "
                                  f"{item.get('publisher', 'unknown publisher')}")
            # Spec Section 7 — retraction do jagah se: metadata (`update-to` /
            # `updated-by` / type) aur title ki shuruaat.
            retracted = retraction_from_crossref(item) or retraction_from_text(title)
            if retracted is True:
                retraction_hits += 1
            out.append(SourceRecord(
                title=title,
                url=self._clean(item.get("URL")),
                snippet=snippet,
                connector=self.name,
                source_type=SourceType.PAPER,
                authors=[a for a in authors if a],
                year=self.pick_year(item),
                publisher=self._clean(item.get("publisher"), 200),
                venue=self._clean(containers[0] if containers else "", 200),
                doi=self._clean(item.get("DOI"), 120),
                peer_reviewed=True if item_type == "journal-article" else None,
                citation_count=item.get("is-referenced-by-count"),
                methodology=(methodology_from_work_type(
                                 (item.get("subtype") or "").lower() or item_type)
                             or methodology_from_text(f"{title} {snippet}")),
                retracted=retracted,
            ))
        if retraction_hits:
            # NOTE ko jodo, badlo mat: _fetch() ka select-fallback note bhi isi
            # field mein hai. Overwrite karne par user ko pata hi nahi chalta ki
            # Crossref ne 400 diya tha.
            retraction_note = (f"{retraction_hits} Crossref record par retraction/"
                               f"withdrawal ka signal hai — ranking mein neeche "
                               f"kar diye gaye")
            self.last_note = (f"{self.last_note}; {retraction_note}"
                              if self.last_note else retraction_note)
        return out


# ── DOAJ ─────────────────────────────────────────────────────────────────────
class DOAJConnector(BaseConnector):
    name = "doaj"
    source_type = SourceType.PAPER

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        from urllib.parse import quote

        resp = http_get(
            f"https://doaj.org/api/search/articles/{quote(query)}",
            params={"pageSize": max_results},
        )
        out: List[SourceRecord] = []
        for item in resp.json().get("results", []):
            bib = item.get("bibjson") or {}
            journal = bib.get("journal") or {}
            links = bib.get("link") or []
            doi = ""
            for ident in bib.get("identifier") or []:
                if (ident.get("type") or "").lower() == "doi":
                    doi = ident.get("id", "")
            title = self._clean(bib.get("title"))
            abstract = self._clean(bib.get("abstract"))
            out.append(SourceRecord(
                title=title,
                url=self._clean(links[0].get("url") if links else
                                (f"https://doi.org/{doi}" if doi else "")),
                snippet=abstract,
                connector=self.name,
                source_type=SourceType.PAPER,
                authors=[a.get("name", "") for a in (bib.get("author") or [])[:8]],
                year=self._year(bib.get("year")),
                venue=self._clean(journal.get("title"), 200),
                publisher=self._clean(journal.get("publisher"), 200),
                doi=self._clean(doi, 120),
                # DOAJ = Directory of Open Access *peer-reviewed* Journals
                peer_reviewed=True,
                full_text_available=True,
                # DOAJ study design nahi batata — sirf title/abstract se
                methodology=methodology_from_text(f"{title} {abstract}"),
                retracted=retraction_from_text(title),
            ))
        return out


# ── PubMed ───────────────────────────────────────────────────────────────────
class PubMedConnector(BaseConnector):
    """
    PubMed sirf peer-reviewed journals index nahi karta — usme editorial, letter,
    comment, erratum aur (ab) preprint bhi hote hain. Pehle hum har PubMed record
    par `peer_reviewed=True` thok dete the. Ye chhota jhooth nahi hai: EvidenceEngine
    isi field par source ka darja tay karta hai, to ek editorial ko clinical trial
    ke barabar wazan mil jaata. Ab esummary ka `pubtype` dekh kar honest jawab
    dete hain, aur pata na ho to None (yaani "maalum nahi") — True nahi.

    LIVE BUG (2026-08-17, doosra round) — bilkul arXiv wali galti, dobara:

        query : "algorithmic bias in healthcare risk prediction"
        result: "Machine learning to predict adverse perinatal outcomes"
                "The nephrologist in the present and near future"
                "Artificial intelligence in maternal and child health"
        term match: [0, 0, 0]  → 0/3 relevant

    Field mapping poori tarah theek tha, isliye connector test ne ise "fields
    theek, topic galat" bata diya — yahi sabse khatarnaak failure hai, kyunki
    upar se lagta hai connector kaam kar raha hai aur ye galat papers aage
    citation ban sakte hain.

    Do wajah:
      1. **`sort` nahi bheja tha.** E-utilities ka default order PubMed website
         ke "Best Match" jaisa NAHI hai — API sabse naye record pehle deti hai.
         Isi liye teeno result 2026 ke the aur teeno topic se bahar. Ab
         `sort=relevance` jaata hai.
      2. **Poori sentence term ki tarah bheji ja rahi thi.** PubMed uska
         Automatic Term Mapping karke terms ko OR se joddta hai, to sirf
         "prediction" match hone par bhi paper aa jaata hai. Ab arXiv jaisa
         AND-joined quoted terms banate hain, 5 -> 3 -> 1 ka ladder chalta hai,
         aur aakhir mein local relevance guard bachhe hue kachre ko girata hai.

    Guard ka bar arXiv jaisa hi (3+ term wali query mein 2 term match) rakha hai,
    ye jaante hue ki PubMed ka esummary abstract nahi deta — yaani match sirf
    TITLE par hota hai, jo sakht bar hai. Ye jaan-boojh kar chuna gaya: ek sahi
    paper chhoot jaana sirf recall ka nuksaan hai (11 aur connector hain), par ek
    galat paper dikha dena sach ka nuksaan hai.
    """

    name = "pubmed"
    source_type = SourceType.PAPER

    # NCBI ki guideline: bina API key ke 3 request/second se zyada nahi. Ek search
    # = 2 call (esearch + esummary), aur SourceDiscovery ek round mein 3 queries
    # 3 threads mein bhejta hai — yaani ek second mein 6 call ho sakte the, jiska
    # natija 429 hota (aur wo bug "PubMed kaam nahi karta" jaisa dikhta).
    _REQUEST_LOCK = threading.Lock()
    _MIN_GAP_SECONDS = 0.35          # ~3 req/sec
    _last_request_at = 0.0

    @classmethod
    def _throttle(cls) -> float:
        with PubMedConnector._REQUEST_LOCK:
            waited = 0.0
            gap = time.time() - PubMedConnector._last_request_at
            if gap < cls._MIN_GAP_SECONDS:
                waited = cls._MIN_GAP_SECONDS - gap
                time.sleep(waited)
            PubMedConnector._last_request_at = time.time()
            return waited

    # ye khud peer-reviewed article nahi hote, chahe peer-reviewed journal mein hon
    _NOT_PEER_REVIEWED = ("preprint", "editorial", "letter", "comment", "news",
                          "newspaper article", "erratum", "retraction",
                          "retracted publication", "biography", "interview")
    _PEER_REVIEWED = ("journal article", "review", "clinical trial",
                      "meta-analysis", "systematic review", "randomized controlled trial")

    @classmethod
    def peer_status(cls, pubtypes) -> Optional[bool]:
        """pubtype list -> True / False / None. Testable, network ke bina."""
        types = [str(t).strip().lower() for t in (pubtypes or []) if str(t).strip()]
        if not types:
            return None                       # maalum nahi — True bolna jhooth hoga
        # negative pehle: "Journal Article + Comment" wala item bhi peer-reviewed
        # research nahi hai. Shaq mein neeche rakhna theek hai, upar nahi.
        if any(bad in t for t in types for bad in cls._NOT_PEER_REVIEWED):
            return False
        if any(good in t for t in types for good in cls._PEER_REVIEWED):
            return True
        return None

    @staticmethod
    def build_term(query: str, max_terms: int = 5) -> str:
        """
        PubMed ke liye AND-joined quoted terms. Testable — network ke bina.

        Quotes jaan-boojh kar hain. Bina quote ke PubMed Automatic Term Mapping
        chalata hai: ek shabd ko MeSH heading + saare synonyms + all-fields ke ek
        bade OR mein khol deta hai. Do-teen shabd ke liye ye theek hai, par poori
        sentence par matlab hota hai "inme se kuch bhi mil jaye" — wahi bug tha.
        Quoted string par ATM nahi lagta, to jo maanga wahi dhoondha jaata hai.
        """
        terms = select_terms(query, max_terms=max_terms)
        if not terms:
            cleaned = " ".join(str(query or "").split())
            return f'"{cleaned}"' if cleaned else ""
        return " AND ".join(f'"{term}"' for term in terms)

    @staticmethod
    def relevance_guard(records: List[SourceRecord], query: str,
                        used_terms: Optional[int] = None) -> List[SourceRecord]:
        """
        Query se bilkul unrelated records hatao — arXiv wala hi bar.

        Ek farak jaan lena zaroori hai: esummary ABSTRACT nahi deta, to yahan
        match sirf title + journal name par hota hai. Yaani ye bar arXiv se
        SAKHT hai aur kuch sahi papers bhi gir sakte hain. Ye maan kar chuna gaya
        hai ki chhoot jaana (recall ka nuksaan, 11 aur connector bache hain) galat
        paper dikhane (sach ka nuksaan) se behtar hai — aur ye guard tab hi kaam
        karta hai jab `sort=relevance` ke baad bhi kachra bacha ho.

        `used_terms` ka matlab arXiv ke guard jaisa hi hai: agar strict AND query
        khaali thi aur ladder ne sirf 1 term wali query se result nikala, to 2
        term match maangna khud ka kaam khud kaatna hai (Hinglish query mein
        "ilaj" jaisa shabd English title mein kabhi nahi milega).
        """
        terms = content_terms(query, limit=6)
        if not terms:
            return domain_filter(records, query)
        needed = 2 if len(terms) >= 3 else 1
        if used_terms:
            needed = min(needed, max(1, used_terms))
        return domain_filter([
            r for r in records
            if term_overlap(terms, f"{r.title} {r.snippet}") >= needed
        ], query)

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        total_terms = len(content_terms(query, limit=None))
        # strict -> dheela, dedup ke saath (arXiv jaisa). 1 par khatam karna
        # zaroori hai: 2-term AND bhi PubMed par kai baar pakka 0 hota hai.
        ladder: List[int] = []
        for step in (5, 3, 1):
            value = min(step, total_terms) if total_terms else 1
            if value not in ladder:
                ladder.append(value)

        # guard kuch girayega, isliye thoda extra maango (par 20 se zyada nahi —
        # esummary ek hi call mein saare ids leta hai, response bada ho jaata hai)
        retmax = max(max_results, min(max_results * 2, 20))
        ids: List[str] = []
        used = ""
        used_terms = ladder[0] if ladder else 0
        relaxed = False
        for count in ladder:
            used = self.build_term(query, max_terms=count)
            if not used:
                break
            self._throttle()          # NCBI: 3 req/sec, threads ke aar-paar bhi
            search = http_get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={
                    "db": "pubmed",
                    "term": used,
                    "retmax": retmax,
                    "retmode": "json",
                    # ASLI BUG YAHI THA: E-utilities ka default order
                    # most-recent-first hai (website ka "Best Match" nahi).
                    "sort": "relevance",
                },
            )
            ids = search.json().get("esearchresult", {}).get("idlist", []) or []
            used_terms = count
            relaxed = count != ladder[0]
            if ids:
                break

        if not ids:
            if used:
                self.last_note = f"PubMed par is query ke liye kuch nahi mila ({used})"
            return []

        self._throttle()
        summary = http_get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
        )
        data = summary.json().get("result", {})
        found: List[SourceRecord] = []
        for pid in ids:
            item = data.get(pid) or {}
            if not item:
                continue
            doi = ""
            for aid in item.get("articleids") or []:
                if (aid.get("idtype") or "").lower() == "doi":
                    doi = aid.get("value", "")
            authors = [a.get("name", "") for a in (item.get("authors") or [])[:8]]
            journal = item.get("fulljournalname") or item.get("source") or ""
            pubtypes = item.get("pubtype") or []
            peer = self.peer_status(pubtypes)
            title = self._clean(item.get("title"))
            # Spec Section 7 — PubMed ka pubtype pehle se fetch ho raha tha,
            # bas use nahi kiya ja raha tha. Yahi sabse sasta aur sabse pakka
            # methodology + retraction signal hai (koi extra API call nahi).
            retracted = (retraction_from_pubtypes(pubtypes)
                         or retraction_from_text(title))
            found.append(SourceRecord(
                title=title,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
                snippet=self._clean(
                    f"{journal}, {item.get('pubdate', 'date unknown')}. "
                    f"{item.get('elocationid', '')}"
                ),
                connector=self.name,
                source_type=SourceType.PAPER,
                authors=[a for a in authors if a],
                year=self._year(item.get("pubdate")),
                venue=self._clean(journal, 200),
                doi=self._clean(doi, 120),
                # pubtype se aaya honest jawab — sabko True kehna band
                peer_reviewed=peer,
                methodology=(methodology_from_pubtypes(pubtypes)
                             or methodology_from_text(title)),
                retracted=retracted,
            ))

        raw_count = len(found)
        kept = self.relevance_guard(found, query, used_terms=used_terms)
        # dropped SIRF guard ka hisaab hai, capped SIRF max_results ka — dono ko
        # mila dena wahi jhooth hota jo arXiv mein pakda gaya tha ("guard ne 3
        # hataye" jabki guard ne ek bhi nahi hataya tha).
        dropped = raw_count - len(kept)
        capped = max(0, len(kept) - max_results)
        out = kept[:max_results]

        # ye ginti FINAL records par hai, saare fetched records par nahi — warna
        # note un papers ke baare mein bolta jo hum de hi nahi rahe.
        not_research = sum(1 for r in out if r.peer_reviewed is False)
        retraction_hits = sum(1 for r in out if r.retracted is True)

        notes: List[str] = []
        if dropped and not out:
            # sab kuch guard ne hataya — ye "duniya mein kuch nahi mila" NAHI hai
            self.last_reason = "filtered"
            notes.append(f"PubMed se {raw_count} result aaye par sabhi topic se door "
                         f"the (relevance guard ne hataye) — ye '0 result' se alag "
                         f"baat hai")
        elif dropped:
            notes.append(f"{raw_count} PubMed result mein se {dropped} relevance "
                         f"guard ne hataye" +
                         (f", {capped} max_results limit se bahar" if capped else ""))
        elif capped:
            notes.append(f"PubMed se {raw_count} relevant result mile, "
                         f"max_results={max_results} ki limit lagi "
                         f"(relevance guard ne kuch nahi hataya)")
        if not_research:
            notes.append(f"{not_research} PubMed result editorial/letter/preprint "
                         f"type ke hain — peer-reviewed research nahi maane gaye")
        if retraction_hits:
            notes.append(f"{retraction_hits} result par PubMed ka retraction flag hai "
                         f"— evidence ki tarah use nahi karna chahiye")
        if relaxed and out:
            notes.append(f"strict AND query par kuch nahi mila, isliye {used_terms} "
                         f"term wali dheeli query chali ({used})")
        if notes:
            self.last_note = "; ".join(notes)
        return out


# ── Facade ───────────────────────────────────────────────────────────────────
class PaperConnector:
    """Saare paper connectors ek jagah. Spec Section 16 ka 'PaperConnector'."""

    def __init__(self):
        self.connectors: List[BaseConnector] = [
            OpenAlexConnector(),
            ArxivConnector(),
            CrossrefConnector(),
            DOAJConnector(),
            PubMedConnector(),
            SemanticScholarConnector(),
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
