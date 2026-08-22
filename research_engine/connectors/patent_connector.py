"""
Patent connectors — Spec Section 2 ka missing tier (₹0 patent batch)

PROVIDER KA FAISLA (kyun ye, kyun baaki nahi) — 2026-08-21 ki halat:

  epo_lod  (DEFAULT, keyless)
      EPO "Linked open EP data" ka public SPARQL endpoint:
          https://data.epo.org/linked-data/query
      Ye EPO ka apna official open-data service hai, bina account/API key
      chalta hai, aur bulk/query access publicly documented hai. Isliye ye
      ₹0 aur legal dono hai. EPO ki fair-use guidance ek IP se ~10
      search/minute ki baat karti hai, isliye hum ek round mein sirf ek
      query bhejte hain aur retry ek hi rakhte hain.
      IMAANDAAR NOTE: EPO khud kehta hai ki linked-data service "not an
      official publication of the EPO" hai — yaani legal status jaisi baat
      ke liye ise last word nahi maanna chahiye. Isi wajah se legal status
      sirf tab bharte hain jab response mein aaye, aur uske saath source
      bhi likha jaata hai.

  uspto_odp (OPTIONAL, key chahiye — default OFF)
      USPTO Open Data Portal (api.uspto.gov). Free hai par account +
      API key maangta hai (aur June 2026 se MFA), isliye ye connector
      sirf tab chalta hai jab env mein USPTO_ODP_API_KEY maujood ho.
      Key na ho to ConnectorSkipped → report mein "API key nahi hai"
      likha jaata hai, "kuch nahi mila" NAHI. Key repo mein kabhi nahi
      aati; sirf env se padhi jaati hai aur uski VALUE kahin log/report
      mein nahi jaati.

  JO JAAN-BOOJH KAR NAHI LIYE:
      * EPO OPS — free registration ke baad OAuth2 + XML; quota ke upar
        paid tier. Offline verify karna mushkil aur "unnecessary
        complexity mat add karo" ke khilaf.
      * Google Patents / Espacenet ke internal endpoints, PatFT ke
        undocumented JSON — koi bhi reverse-engineered/scraped raasta
        nahi. Rule saaf hai: sirf official public interface.
      * PatentsView — 2026-03-20 se USPTO ODP mein migrate ho gaya aur
        key-gated hai, isliye alag provider rakhne ka fayda nahi.

FIELD MAPPING KI IMAANDAARI:
    Is sandbox se network calls blocked hain, isliye endpoint ka SHAPE
    documentation se liya gaya hai, live call se verify NAHI hua. Parsing
    isi wajah se DEFENSIVE hai: variable/field ke kai naam try hote hain,
    jo na mile wo field khaali rehti hai (guess nahi hoti), aur poora
    payload bekaar ho to connector honest "0 result" ya HTTP error reason
    deta hai — crash nahi. parse() aur build_query() dono PURE functions
    hain, taaki offline test unhe fixture ke saath ginti se check kar sake.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

from ..models import SourceRecord, SourceType
from ..patents import (DEPTH_METADATA, PatentMeta, evidence_text,
                       looks_like_patent_number, split_number)
from .base import (SLOW_TIMEOUT, BaseConnector, ConnectorSkipped,
                   content_terms, http_get, select_terms, term_overlap)

# Humare khud ke lagaye labels ("ABSTRACT (patent ka summary):" etc.). Relevance
# matching se pehle ye nikalne padte hain — dekho `guard_text()` ka comment.
_LABEL_RE = re.compile(
    r"(?:METADATA ONLY|ABSTRACT|CLAIMS|DESCRIPTION)\s*\([^)]*\)\s*:")


class PatentProviderConnector(BaseConnector):
    """
    Patent providers ka shared base — record banana + relevance guard.

    source_type SAB ke liye PATENT hai, chahe provider koi bhi ho: patent ko
    "web result" ya "paper" ki tarah pipeline mein bhejna hi wo bug tha jisse
    patent ka legal claim science ki tarah treat hone lagta.
    """
    source_type = SourceType.PATENT
    timeout = SLOW_TIMEOUT      # patent APIs aksar slow hain, par free hain

    # ── record banana ────────────────────────────────────────────────────────
    def to_record(self, meta: PatentMeta, query: str = "") -> SourceRecord:
        """
        PatentMeta → SourceRecord. Yahan koi field "bhar" nahi jaati:
        peer_reviewed patent ke liye JAAN-BOOJH KAR None rehta hai (patent
        peer-reviewed nahi hota, par False likhna bhi galat message deta —
        peer review ka sawaal hi laagu nahi hota), aur read_level wahi jaata
        hai jitna text sach mein aaya.

        SNIPPET ka fallback (smoke test se pakda): kai providers metadata-only
        row dete hain — na abstract, na claims. Tab `evidence_text()` khaali
        aata hai, aur khaali snippet ka record aage jaakar do nuksaan karta hai:
        relevance guard ke paas match karne ko sirf title bachta hai, aur
        reasoning ko ek naam-maatra source milta hai jismein padhne layak kuch
        nahi. Isliye khaali hone par ek CLEARLY LABELLED metadata line jaati hai
        jo khud batati hai ki text nahi mila — ye "bharna" nahi hai, kyunki
        ismein sirf wahi hai jo provider ne diya.

        Fallback line `meta.label()` se NAHI banti, jaan-boojh kar: label ke
        andar PATENT_EVIDENCE_NOTE hota hai ("patent = legal document, ...") aur
        wo boilerplate snippet mein jaate hi relevance guard ko muft ka match de
        deta ("patent"/"process" jaise shabd har query mein aa sakte hain).
        Evidence note pehle se citation_label() aur to_prompt_block() mein jaata
        hai, isliye snippet mein sirf is patent ke apne facts rehte hain.
        """
        snippet = evidence_text(meta, limit=1500)
        if not snippet:
            facts = [b for b in (meta.number,
                                 meta.assignee,
                                 str(meta.year or ""),
                                 ", ".join(list(meta.cpc or []) + list(meta.ipc or []))[:120])
                     if b]
            snippet = ("METADATA ONLY (is patent ka text provider se nahi mila, "
                       "sirf bibliographic info): " + " | ".join(facts))
        return SourceRecord(
            title=meta.title or meta.number or "(patent title nahi mila)",
            # Provider ka apna URI pehle. Na ho to Espacenet ka official public
            # lookup link (ye "banaya hua" link hai, isliye PatentMeta.url mein
            # nahi jaata — wahan sirf provider ka sach rehta hai).
            url=meta.url or espacenet_lookup(meta.number),

            snippet=snippet,
            connector=self.name,
            source_type=SourceType.PATENT,
            authors=list(meta.inventors or []),
            year=meta.year,
            publisher=meta.assignee,
            venue=meta.jurisdiction,
            read_level=meta.read_depth(),
            read_note=meta.read_note(),
            full_text_chars=len((meta.description_text or "").strip()),
            patent_meta=meta.to_dict(),
            doc_kind="patent",
            doc_kind_label="patent (legal document)",
            doc_kind_confidence="high",
        )

    # ── relevance guard (trap: same keyword, bilkul alag invention) ──────────
    @staticmethod
    def guard_text(record: SourceRecord) -> str:
        """
        Guard ko dikhne wala text — humare apne LABELS hata kar.

        Kyun zaroori: snippet mein hum khud label lagate hain —
        "ABSTRACT (patent ka summary):", "CLAIMS (LEGAL dawe, experiment nahi):",
        "METADATA ONLY (... bibliographic info):". Ye shabd patent ke content ka
        hissa NAHI hain, par term matching ke liye poora text ek jaisa dikhta
        hai. Nateeja: "patent", "process", "experiment", "info" jaisi query par
        guard ko MUFT ka match mil jaata aur bilkul unrelated patent bach jaata.
        Isliye matching se pehle label parentheticals nikal dete hain.
        """
        cleaned = _LABEL_RE.sub(" ", record.snippet or "")
        return f"{record.title or ''} {cleaned}"

    @classmethod
    def relevance_guard(cls, records: List[SourceRecord],
                        query: str) -> List[SourceRecord]:
        """
        Query se bilkul unrelated patents hatao — paper connectors jaisa hi rule.

        Patent titles jaan-boojh kar CHAUDE likhe jaate hain ("System and method
        for processing a signal"), isliye ek hi keyword ka match kaafi nahi hai
        jab query mein 3+ content terms hain. Jo hataye jaate hain, unki ginti
        note mein jaati hai — chupchaap phenkna "0 result mila" jaisa jhooth
        ban jaata hai.
        """
        terms = content_terms(query, limit=6)
        if not terms:
            return records
        needed = 2 if len(terms) >= 3 else 1
        return [r for r in records
                if term_overlap(terms, cls.guard_text(r)) >= needed]

    def _finish(self, records: List[SourceRecord], raw_count: int,
                query: str, extra_note: str = "") -> List[SourceRecord]:
        """Guard lagao + honest note/reason likho (safe_search isse padhta hai)."""
        kept = self.relevance_guard(records, query)
        dropped = raw_count - len(kept)
        notes: List[str] = []
        if extra_note:
            notes.append(extra_note)
        if dropped and not kept:
            # sab guard ne hataye — ye "duniya mein patent nahi hai" NAHI hai
            self.last_reason = "filtered"
            notes.append(f"{self.name} se {raw_count} patent aaye par sabhi topic "
                         f"se door the (relevance guard ne hataye) — ye '0 patent "
                         f"mila' se alag baat hai")
        elif dropped:
            notes.append(f"{dropped} patent topic se door the, isliye hataye gaye")
        if notes:
            self.last_note = "; ".join(notes)
        return kept


# ── SPARQL binding aliases (doc se liye, live verify nahi hue) ───────────────
# Ek hi cheez ke kai naam ho sakte hain, aur endpoint ka schema hamare paas
# live test nahi hua — isliye har field ke liye naam ki LIST hai. Jo na mile
# wo khaali rehta hai; hum kabhi bhi doosre field se "andaaza" nahi lagate.
_ALIASES: Dict[str, tuple] = {
    "uri": ("publication", "publn", "pub", "s", "subject", "patent"),
    "number": ("number", "publicationNumber", "publnNumber", "docNumber",
               "publicationnumber"),
    "title": ("title", "titleOfInvention", "label", "inventionTitle"),
    "abstract": ("abstract", "abstractText", "description"),
    "publication_date": ("publicationDate", "date", "publnDate", "pubDate"),
    "filing_date": ("filingDate", "applicationDate", "dateFiled"),
    "priority_date": ("priorityDate", "earliestPriorityDate", "priority"),
    "family": ("family", "familyId", "simpleFamily", "docdbFamily",
               "familyID"),
    "assignee": ("applicant", "applicantName", "assignee", "applicantVC",
                 "owner"),
    "inventor": ("inventor", "inventorName", "inventorVC"),
    "ipc": ("ipc", "classificationIPC", "ipcClass", "classificationIPCInventive"),
    "cpc": ("cpc", "classificationCPC", "cpcClass", "classificationCPCInventive"),
    "kind": ("kind", "publicationKind", "kindCode"),
    "status": ("legalStatus", "status"),
}


def _binding_value(row: Dict, field: str) -> str:
    """SPARQL row se ek field ka value — jo naam mil jaye, wahi."""
    for key in _ALIASES.get(field, ()):
        cell = row.get(key)
        if isinstance(cell, dict):
            value = str(cell.get("value") or "").strip()
        else:
            value = str(cell or "").strip()
        if value:
            return value
    return ""


def espacenet_lookup(number: str) -> str:
    """
    Number se Espacenet ka PUBLIC search link.

    Ye publication ka apna URL nahi hai — ye ek lookup link hai, aur isi wajah
    se PatentMeta.url mein ye NAHI jaata (wahan sirf provider ka diya hua URI
    jaata hai). Record ke url mein isliye jaata hai ki user/citation engine ke
    paas patent tak pahunchne ka ek official raasta ho.
    """
    clean = re.sub(r"[^0-9A-Za-z]", "", str(number or "")).upper()
    if not clean:
        return ""
    return f"https://worldwide.espacenet.com/patent/search?q={clean}"


class EpoLinkedDataConnector(PatentProviderConnector):
    """
    EPO Linked open EP data — keyless SPARQL endpoint, official, ₹0.

    Rate limit: EPO ki fair-use guidance ~10 search/minute (per IP) kehti hai,
    isliye `rate_limited = True` hai aur hum ek query se zyada nahi bhejte.
    """
    name = "epo_lod"
    free = True
    rate_limited = True
    ENDPOINT = "https://data.epo.org/linked-data/query"
    MAX_TERMS = 3

    @classmethod
    def build_query(cls, query: str, limit: int = 5) -> str:
        """
        Deterministic SPARQL banao — ek hi sawaal par hamesha ek hi query.

        SANITIZE zaroori hai: user ka text seedha SPARQL string mein jaata hai,
        to quote/backslash/brace/newline hata kar sirf letters-digits-space-
        hyphen bachate hain (SPARQL injection ka darwaza band).

        Sirf EK pattern REQUIRED rehta hai — jispar FILTER lagta hai (title,
        ya patent number wale sawaal mein number). Baaki sab OPTIONAL, kyunki
        endpoint ka exact schema live verify nahi hua aur ek galat REQUIRED
        pattern poori query ko chupchaap 0-result bana deta hai.

        FILTER ki JAGAH maayne rakhti hai: OPTIONAL se aayi variable par filter
        lagane se wo variable unbound hone par filter FALSE ho jaata hai —
        yaani hamesha 0 result. Isliye jis cheez par filter hai, wahi pattern
        required banaya jaata hai.
        """
        terms = [re.sub(r"[^0-9a-z \-]", "", t.lower()).strip()
                 for t in select_terms(query, max_terms=cls.MAX_TERMS)]
        terms = [t for t in terms if len(t) >= 3][:cls.MAX_TERMS]
        number = cls.number_in(query)
        if not terms and not number:
            return ""

        optional_lines = [
            "  OPTIONAL { ?publication patent:publicationDate ?publicationDate }",
            "  OPTIONAL { ?publication patent:filingDate ?filingDate }",
            "  OPTIONAL { ?publication patent:abstract ?abstract }",
            "  OPTIONAL { ?publication patent:simpleFamily ?family }",
            "  OPTIONAL { ?publication patent:applicantVC ?applicant }",
            "  OPTIONAL { ?publication patent:inventorVC ?inventor }",
            "  OPTIONAL { ?publication patent:classificationIPCInventive ?ipc }",
            "  OPTIONAL { ?publication patent:classificationCPCInventive ?cpc }",
        ]
        if number:
            # Sawaal mein seedha patent number hai — title mein keyword dhoondhna
            # bekaar hota (title ke andar number nahi hota).
            required = "  ?publication patent:publicationNumber ?number .\n"
            filters = f'CONTAINS(UCASE(STR(?number)), "{number}")'
            optional_lines.insert(
                0, "  OPTIONAL { ?publication patent:titleOfInvention ?title }")
        else:
            required = "  ?publication patent:titleOfInvention ?title .\n"
            filters = " && ".join(
                f'CONTAINS(LCASE(STR(?title)), "{t}")' for t in terms)
            optional_lines.insert(
                0, "  OPTIONAL { ?publication patent:publicationNumber ?number }")

        rows = max(1, min(int(limit or 1), 25))
        return (
            "PREFIX patent: <http://data.epo.org/linked-data/def/patent/>\n"
            "PREFIX dcterms: <http://purl.org/dc/terms/>\n"
            "SELECT ?publication ?number ?title ?abstract ?publicationDate "
            "?filingDate ?family ?applicant ?inventor ?ipc ?cpc WHERE {\n"
            + required
            + f"  FILTER({filters})\n"
            + "\n".join(optional_lines) + "\n"
            "}\n"
            f"LIMIT {rows}"
        )

    @staticmethod
    def number_in(text: str) -> str:
        """
        Sawaal ke andar patent number hai to wo (normalized), warna khaali.

        Kind code (A1/B2) HATA diya jaata hai search ke liye: user aksar
        "US9876543" likhta hai jabki publication "US9876543B2" hai, aur ulta
        bhi hota hai. Number ka core (jurisdiction + serial) match karana
        dono haalat mein kaam karta hai.

        REGEX ki hadd (ye ek asli bug tha, smoke test ne pakda): pehle serial
        wale hisse mein letters bhi allowed the (`[0-9A-Za-z...]`), to
        "US11234567 prior art" par poora "US11234567 prior art" ek token ban
        jaata tha — aur `looks_like_patent_number()` poore token par chalta hai,
        isliye wo FALSE aa jaata. Nateeja: number wala sawaal chupchaap title
        search ban jaata tha (title mein number nahi hota => hamesha 0 result).
        Ab number ke beech mein sirf digits/separator allowed hain, aur kind
        code (agar ho) alag se aakhir mein — yaani padoos ke shabd andar nahi
        ghus sakte.
        """
        pattern = (r"\b[A-Za-z]{2}[\s\-]?[0-9][0-9,\s\-/]{2,}[0-9]"
                   r"(?:[\s\-]?[A-Za-z][0-9]?)?\b")
        for token in re.findall(pattern, str(text or "")):
            if looks_like_patent_number(token):
                parts = split_number(token)
                if parts["serial"]:
                    return f"{parts['jurisdiction']}{parts['serial']}"
        return ""


    @staticmethod
    def number_from_uri(uri: str) -> str:
        """
        LOD resource URI se publication number nikaalo (parsing, andaaza nahi).

        EPO ka URI pattern: .../data/publication/EP/1234567/A1/-
        Isse "EP1234567A1" banta hai. Pattern na mile to khaali — hum URI ka
        aakhri tukda uthakar "number" nahi bana dete.
        """
        match = re.search(r"/publication/([A-Z]{2})/([0-9A-Z]+)/([A-Z][0-9]?)(?:/|$)",
                          str(uri or ""))
        if not match:
            return ""
        return f"{match.group(1)}{match.group(2)}{match.group(3)}"

    @classmethod
    def parse(cls, payload: Dict) -> List[PatentMeta]:
        """
        SPARQL JSON → PatentMeta list. PURE function (test iske saath fixture
        deta hai), isliye ismein koi network ya state nahi.

        Ek publication ki KAI rows aa sakti hain (do applicant, teen IPC class
        = cross product). Inhe waise hi records bana dena "5 patents mile" wala
        jhooth ban jaata, isliye rows publication ke hisaab se group hoti hain
        aur list-fields merge hote hain.
        """
        rows = (((payload or {}).get("results") or {}).get("bindings") or [])
        grouped: Dict[str, Dict] = {}
        order: List[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            uri = _binding_value(row, "uri")
            number = _binding_value(row, "number") or cls.number_from_uri(uri)
            key = number or uri
            if not key:
                continue
            if key not in grouped:
                grouped[key] = {"uri": uri, "number": number, "inventors": [],
                                "ipc": [], "cpc": []}
                order.append(key)
            entry = grouped[key]
            for field in ("title", "abstract", "publication_date", "filing_date",
                          "priority_date", "family", "assignee", "kind", "status"):
                if not entry.get(field):
                    value = _binding_value(row, field)
                    if value:
                        entry[field] = value
            for field, target in (("inventor", "inventors"), ("ipc", "ipc"),
                                  ("cpc", "cpc")):
                value = _binding_value(row, field)
                if value and value not in entry[target]:
                    entry[target].append(value)

        metas: List[PatentMeta] = []
        for key in order:
            e = grouped[key]
            metas.append(PatentMeta(
                number=e.get("number", ""),
                kind_code=e.get("kind", ""),
                title=e.get("title", ""),
                inventors=e.get("inventors", []),
                assignee=e.get("assignee", ""),
                filing_date=e.get("filing_date", ""),
                publication_date=e.get("publication_date", ""),
                priority_date=e.get("priority_date", ""),
                family_id=e.get("family", ""),
                ipc=e.get("ipc", []),
                cpc=e.get("cpc", []),
                abstract=e.get("abstract", ""),
                # legal status sirf tab, jab response mein sach mein aaya ho —
                # aur uske saath source ka naam bhi, kyunki EPO linked-data
                # khud ko "not an official publication" kehta hai.
                legal_status=e.get("status", ""),
                legal_status_source=("epo_lod (EPO linked open data — EPO isse "
                                     "official publication nahi maanta)"
                                     if e.get("status") else ""),
                url=e.get("uri", ""),
                provider="epo_lod",
            ))
        return metas

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        sparql = self.build_query(query, limit=max(3, int(max_results or 1) * 2))
        if not sparql:
            # Ye "kuch nahi mila" NAHI hai — query hi search-layak nahi thi.
            self.last_reason = "no_query"
            self.last_note = ("query se koi kaam ka term nahi bana, isliye EPO "
                              "par search bheji hi nahi gayi")
            return []
        resp = http_get(
            self.ENDPOINT,
            params={"query": sparql, "format": "application/sparql-results+json"},
            headers={"Accept": "application/sparql-results+json"},
            timeout=self.timeout,
            # EPO fair use: ~10 search/minute. Retry se hum khud apna hi quota
            # khaate hain, isliye yahan retry BAND hai — ek honest fail behtar
            # hai ek chori-chhupe double call se.
            retries=0,
        )
        try:
            payload = resp.json()
        except Exception:
            payload = {}
        metas = self.parse(payload)
        records = [self.to_record(m, query) for m in metas]
        raw_count = len(records)
        extra = ""
        if not raw_count:
            extra = ("EPO linked-data par search chali par is query se koi EP "
                     "publication match nahi hui")
        return self._finish(records, raw_count, query, extra)[:max_results]


def _first(data: Dict, *keys) -> str:
    """Nested/renamed JSON se pehla non-empty scalar — warna khaali."""
    if not isinstance(data, dict):
        return ""
    for key in keys:
        value = data.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()
        if isinstance(value, list) and value:
            head = value[0]
            if isinstance(head, (str, int, float)) and str(head).strip():
                return str(head).strip()
    return ""


class UsptoOdpConnector(PatentProviderConnector):
    """
    USPTO Open Data Portal — free hai, par account + API key maangta hai.

    Isliye ye connector OPTIONAL hai: `USPTO_ODP_API_KEY` env mein na ho to
    ConnectorSkipped uthta hai aur report mein "API key nahi hai" likha jaata
    hai — "kuch nahi mila" NAHI. Key ki VALUE kahin log/report/prompt mein nahi
    jaati; sirf request header mein.
    """
    name = "uspto_odp"
    free = False
    rate_limited = True
    ENDPOINT = "https://api.uspto.gov/api/v1/patent/applications/search"

    @staticmethod
    def api_key() -> str:
        return (os.getenv("USPTO_ODP_API_KEY") or "").strip()

    @classmethod
    def parse(cls, payload: Dict) -> List[PatentMeta]:
        """
        ODP JSON → PatentMeta. PURE function; field naam doc se liye hain aur
        live verify nahi hue, isliye har field ke kai naam try hote hain aur
        na milne par field KHAALI rehti hai.
        """
        rows = ((payload or {}).get("patentFileWrapperDataBag")
                or (payload or {}).get("results")
                or (payload or {}).get("data") or [])
        metas: List[PatentMeta] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            meta_block = row.get("applicationMetaData") or row
            applicants = meta_block.get("applicantBag") or []
            assignee = ""
            if isinstance(applicants, list) and applicants:
                head = applicants[0]
                assignee = (_first(head, "applicantNameText", "name",
                                   "organizationNameText")
                            if isinstance(head, dict) else str(head).strip())
            inventors: List[str] = []
            for item in (meta_block.get("inventorBag") or []):
                name = (_first(item, "inventorNameText", "name")
                        if isinstance(item, dict) else str(item).strip())
                if name and name not in inventors:
                    inventors.append(name)
            first_inventor = _first(meta_block, "firstInventorName")
            if first_inventor and first_inventor not in inventors:
                inventors.insert(0, first_inventor)
            number = _first(meta_block, "patentNumber", "publicationNumber") \
                or _first(row, "applicationNumberText", "applicationNumber")
            status = _first(meta_block, "applicationStatusDescriptionText",
                            "statusDescriptionText")
            metas.append(PatentMeta(
                number=("US" + number if number and number[:1].isdigit() else number),
                jurisdiction="US",
                title=_first(meta_block, "inventionTitle", "title"),
                inventors=inventors,
                assignee=assignee,
                filing_date=_first(meta_block, "filingDate", "effectiveFilingDate"),
                publication_date=_first(meta_block, "publicationDateBag",
                                        "patentIssueDate", "publicationDate"),
                priority_date=_first(meta_block, "earliestPublicationDate",
                                     "effectiveFilingDate"),
                # ODP ek hi application ka wrapper deta hai; family id alag
                # endpoint se aata hai. Yahan family_id KHAALI rehta hai —
                # aur khaali honest hai: family_key() tab priority+title par
                # gir jaata hai, jhoothi family id banane se behtar.
                family_id="",
                cpc=[c for c in [_first(meta_block, "cpcClassificationBag",
                                        "classificationBag")] if c],
                abstract=_first(meta_block, "abstractText", "abstract"),
                legal_status=status,
                legal_status_source="uspto_odp (USPTO Open Data Portal)" if status else "",
                url=_first(row, "applicationURI", "uri"),
                provider="uspto_odp",
            ))
        return metas

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        key = self.api_key()
        if not key:
            raise ConnectorSkipped(
                "USPTO_ODP_API_KEY env mein nahi hai — USPTO Open Data Portal "
                "free hai par account+key maangta hai, isliye ye connector "
                "chala hi nahi (ye '0 patent mila' se alag baat hai)")
        terms = select_terms(query, max_terms=4)
        search_text = EpoLinkedDataConnector.number_in(query) or " ".join(terms)
        if not search_text.strip():
            self.last_reason = "no_query"
            self.last_note = ("query se koi kaam ka term nahi bana, isliye USPTO "
                              "par search bheji hi nahi gayi")
            return []
        resp = http_get(
            self.ENDPOINT,
            params={"q": search_text, "limit": max(3, int(max_results or 1) * 2)},
            headers={"X-API-KEY": key,
                     "Accept": "application/json"},
            timeout=self.timeout,
            retries=0,
        )
        try:
            payload = resp.json()
        except Exception:
            payload = {}
        records = [self.to_record(m, query) for m in self.parse(payload)]
        raw_count = len(records)
        extra = ("USPTO ODP par search chali par is query se koi application "
                 "match nahi hui") if not raw_count else ""
        return self._finish(records, raw_count, query, extra)[:max_results]


class PatentDiscoveryConnector:
    """
    Saare patent providers ek jagah — baaki facades (Web/Paper/Book/Dataset)
    jaisa hi interface: `by_name()` aur `search() -> {"records", "log"}`,
    taaki SourceDiscovery ise alag se special-case na kare.

    Order maayne rakhta hai: keyless official provider PEHLE. Key wala provider
    key na hone par ConnectorSkipped deta hai, jo log mein "no_key" reason ban
    kar jaata hai — yaani report mein saaf dikhta hai ki wo chala hi nahi.
    """

    def __init__(self):
        self.connectors: List[BaseConnector] = [
            EpoLinkedDataConnector(),
            UsptoOdpConnector(),
        ]

    def by_name(self, name: str) -> Optional[BaseConnector]:
        return next((c for c in self.connectors if c.name == name), None)

    def available_names(self) -> List[str]:
        """
        Jo provider is waqt sach mein chal sakte hain.

        Key-gated provider ko planner ke plan mein daalna bekaar API call nahi
        hai (call hoti hi nahi), par log mein har round "no_key" likhna bhi
        shor hai — planner isi list se decide karta hai.
        """
        names: List[str] = []
        for connector in self.connectors:
            if isinstance(connector, UsptoOdpConnector) and not connector.api_key():
                continue
            names.append(connector.name)
        return names

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
