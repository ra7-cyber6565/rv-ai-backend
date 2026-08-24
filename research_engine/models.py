"""
Deep Research Engine — Shared Data Models
Spec Section 16 (Architecture Requirement)

IMPORTANT: is file mein koi heavy dependency nahi hai (chromadb / gemini / requests
kuch nahi). Isliye ye module akele import + test kiya ja sakta hai, bina server
start kiye aur bina Gemini quota kharch kiye.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional
from urllib.parse import unquote, urlparse

from .quality_signals import (
    METHODOLOGY_RANK,
    methodology_label,
    methodology_rank,
    replication_label,
)
# patents.py bhi dependency-free hai aur models se KUCH import nahi karta,
# isliye ye import safe hai (koi circular import nahi).
from .patents import PATENT_EVIDENCE_NOTE
from .patents import family_key as patent_family_key


# ── Source types (Spec Section 2) ─────────────────────────────────────────────
class SourceType(str, Enum):
    DOCUMENT = "document"          # user ka apna uploaded PDF/note
    PAPER = "paper"                # research paper / preprint
    BOOK = "book"                  # book (full text ya sirf metadata)
    WEB = "web"                    # general webpage
    ENCYCLOPEDIA = "encyclopedia"  # Wikipedia/Wikimedia
    DATASET = "dataset"            # government/public dataset
    TRANSCRIPT = "transcript"      # video/audio transcript
    # Patent ek LEGAL document hai — iske claims legal dawe hote hain, koi
    # experiment se saabit nateeja nahi. Isliye ise WEB/PAPER mein chhupana
    # galat tha: paper maan lene par peer-review/quality scoring usko science
    # ki tarah treat karti, aur "patent claim" report mein fact ban jaata.
    PATENT = "patent"


# ── Reading levels (Spec Section 2 ka honesty rule) ──────────────────────────
# "Karodon sources mein search karna" aur "karodon sources ka poora text
# padhna" alag cheezein hain. Isliye system har source ke saath ye level
# report karta hai, aur final report mein isi ka breakdown chhapta hai.
#
# "claims" patent ke liye ek ASLI level hai: patent ka abstract padhna aur uske
# claims padhna do bilkul alag gehraiyan hain, aur "patent padha" ka dawa sirf
# claims/description process hone par hi sach hota hai. Ye list sirf display
# order ke liye use hoti hai (read_level_counts), isliye naya level jodna kisi
# purane consumer ko nahi todta.
READ_LEVEL_ORDER = ["metadata", "snippet", "abstract", "claims", "full_text"]
READ_LEVEL_LABELS = {
    "metadata": "sirf metadata (title/author/year)",
    "snippet": "search snippet",
    "abstract": "abstract",
    "claims": "patent ke claims (legal dawe) process hue",
    "full_text": "full text",
}


def normalize_doi(value: object) -> str:
    """Canonical DOI identity across URL, ``doi:`` and case variants."""
    raw = unquote(str(value or "")).strip().casefold()
    if not raw:
        return ""
    raw = re.sub(r"^doi\s*:\s*", "", raw)
    raw = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", raw)
    raw = raw.split("#", 1)[0].split("?", 1)[0].strip()
    if not raw.startswith("10.") or "/" not in raw:
        return ""
    return raw.rstrip(".,; ")


# ── §9 — ACCESS DEPTH ka poora vocabulary (sirf ye paanch label allowed) ──────
#
# Kyun (dark-matter run): report mein "FULL-TEXT VERIFIED" chhapta tha. Us ek
# label ne DO alag baaton ko ek bana diya — "text mil gaya" aur "claim verify ho
# gaya". S12 sirf abstract par tha aur phir bhi "full-text verified" dikha.
# Isliye:
#   * access depth = humne kitna TEXT dekha (ye label)
#   * verification  = claim ko us text ne support kiya ya nahi (alag field,
#                     claim_verification.py mein)
# "VERIFIED" shabd is vocabulary mein jaan-boojh kar nahi hai.
ACCESS_METADATA = "METADATA ONLY"
ACCESS_SNIPPET = "SNIPPET ONLY"
ACCESS_ABSTRACT = "ABSTRACT ONLY"
ACCESS_SECTIONS = "RELEVANT SECTIONS REVIEWED"
ACCESS_FULL = "FULL TEXT ACCESSED"

ACCESS_DEPTH_ALLOWED = (ACCESS_METADATA, ACCESS_SNIPPET, ACCESS_ABSTRACT,
                        ACCESS_SECTIONS, ACCESS_FULL)

# read_level (andar ka naam) → §9 ka label
ACCESS_DEPTH_LABELS = {
    "metadata": ACCESS_METADATA,
    "snippet": ACCESS_SNIPPET,
    "abstract": ACCESS_ABSTRACT,
    # patent ke claims poora document nahi hote — wo document ka ek chuna hua
    # hissa hai, isliye "sections" family mein aata hai.
    "claims": ACCESS_SECTIONS,
    "full_text": ACCESS_FULL,
}

ACCESS_DEPTH_EXPLAIN = {
    ACCESS_METADATA: "sirf title/author/year mile — content dekha hi nahi gaya",
    ACCESS_SNIPPET: "sirf search ka chhota tukda mila",
    ACCESS_ABSTRACT: "sirf abstract (summary) padha gaya, poora paper nahi",
    ACCESS_SECTIONS: "document ke chune hue hisse padhe gaye, poora document nahi",
    ACCESS_FULL: "poora text process hua",
}


# ── §20 — chaar ALAG state machine (ek doosre ka matlab nahi nikaalte) ────────
#
# Pichhli galti: "provider ka job complete ho gaya" ko "jawab poora ho gaya"
# maan liya gaya tha, aur "citation theek hai" ko "evidence strong hai". Isliye
# ab chaaron cheezein alag naam se, alag values mein rehti hain.

# 1. Job (background kaam) ki haalat — sirf process ke baare mein.
JOB_QUEUED = "QUEUED"
JOB_RUNNING = "RUNNING"
JOB_FINISHED = "FINISHED"          # kaam ruk gaya — jawab acha hai ya nahi, ye ISSE pata NAHI chalta
JOB_FAILED = "FAILED"
JOB_RECOVERED = "RECOVERED"        # connection toota tha, result history se wapas mila
JOB_STATES = (JOB_QUEUED, JOB_RUNNING, JOB_FINISHED, JOB_FAILED, JOB_RECOVERED)

# 2. Jawab poora hua ya nahi — contract ke against (requested.contract_ledger).
ANSWER_COMPLETE = "COMPLETE"
ANSWER_PARTIAL = "PARTIAL"
ANSWER_INSUFFICIENT = "INSUFFICIENT EVIDENCE"
ANSWER_FAILED = "FAILED"
ANSWER_STATES = (ANSWER_COMPLETE, ANSWER_PARTIAL, ANSWER_INSUFFICIENT,
                 ANSWER_FAILED)

# 3. Evidence ki haalat — retrieval/verification se, LLM ke bharose se nahi.
EVIDENCE_STRONG = "STRONG"
EVIDENCE_MODERATE = "MODERATE"
EVIDENCE_WEAK = "WEAK"
EVIDENCE_MIXED = "MIXED"                 # support aur counter dono mile
EVIDENCE_NONE = "NO USABLE EVIDENCE"
EVIDENCE_NOT_CHECKED = "NOT CHECKED"     # check hua hi nahi — "zero" se ALAG
EVIDENCE_STATES = (EVIDENCE_STRONG, EVIDENCE_MODERATE, EVIDENCE_WEAK,
                   EVIDENCE_MIXED, EVIDENCE_NONE, EVIDENCE_NOT_CHECKED)

# 4. Novelty ki haalat — §14 ka poora whitelist (isse bahar koi shabd nahi).
NOVELTY_KNOWN = "KNOWN IDEA"
NOVELTY_KNOWN_VARIANT = "KNOWN VARIANT"
NOVELTY_MINOR = "MINOR MODIFICATION"
NOVELTY_POSSIBLE = "POSSIBLY NOVEL — NO CLOSE MATCH FOUND"
NOVELTY_UNVERIFIED = "NOVELTY UNVERIFIED"
NOVELTY_DUPLICATE = "REJECTED AS DUPLICATE"
NOVELTY_STATES = (NOVELTY_KNOWN, NOVELTY_KNOWN_VARIANT, NOVELTY_MINOR,
                  NOVELTY_POSSIBLE, NOVELTY_UNVERIFIED, NOVELTY_DUPLICATE)



# ── Claim classification (Spec Section 7) ────────────────────────────────────
class ClaimType(str, Enum):
    FACT = "FACT"
    EVIDENCE = "EVIDENCE"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    SPECULATION = "SPECULATION"
    # "Source support abhi prove nahi hua" ek evidence state hai, invented
    # guess nahi.  Ise SPECULATION map karna semantic bug tha: downstream audit
    # unsupported factual claims ko creative hypotheses ke saath mila deta tha.
    UNVERIFIED = "UNVERIFIED"
    UNKNOWN = "UNKNOWN"


# Gemini output mein jo labels aate hain, unko ClaimType pe map karo
_LABEL_TO_CLAIM = {
    "ESTABLISHED": ClaimType.FACT,
    "ESTABLISHED FACT": ClaimType.FACT,
    "FACT": ClaimType.FACT,
    "STRONG EVIDENCE": ClaimType.EVIDENCE,
    # intel ka rule (2026-08-20): abstract/snippet-only evidence ka label
    # "SOURCE-REPORTED" hai — source ye keh raha hai, humne full text padh kar
    # confirm nahi kiya. Ye EVIDENCE hai, FACT nahi.
    "SOURCE-REPORTED": ClaimType.EVIDENCE,
    "SOURCE REPORTED": ClaimType.EVIDENCE,
    "EVIDENCE": ClaimType.EVIDENCE,
    "MIXED EVIDENCE": ClaimType.EVIDENCE,
    "WEAK EVIDENCE": ClaimType.EVIDENCE,
    "INFERENCE": ClaimType.INFERENCE,
    "HYPOTHESIS": ClaimType.HYPOTHESIS,
    "SPECULATION": ClaimType.SPECULATION,
    "UNVERIFIED": ClaimType.UNVERIFIED,
    "UNKNOWN": ClaimType.UNKNOWN,
}


def label_to_claim_type(label: str) -> ClaimType:
    """'[STRONG EVIDENCE]' jaisa label ClaimType mein badlo."""
    key = label.strip().strip("[]").upper()
    return _LABEL_TO_CLAIM.get(key, ClaimType.UNKNOWN)


# ── SourceRecord ─────────────────────────────────────────────────────────────
@dataclass
class SourceRecord:
    """
    Ek retrieved source. Spec Section 3 + 7 ke hisaab se metadata + provenance
    dono saath rakhte hain, taaki citation aur quality scoring real ho.
    """
    title: str = ""
    url: str = ""
    snippet: str = ""
    connector: str = ""                    # "openalex" | "tavily" | "user_pdf" ...
    source_type: SourceType = SourceType.WEB

    # Spec Section 3 — book/paper metadata
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    publisher: str = ""
    venue: str = ""
    doi: str = ""
    locator: str = ""                      # "Page 12" ya "00:14:32"

    # Spec Section 7 — quality signals
    peer_reviewed: Optional[bool] = None   # None = pata nahi (jhooth mat bolo)
    is_primary: Optional[bool] = None
    citation_count: Optional[int] = None
    full_text_available: bool = False

    # Spec Section 7 ke baaki signals — poori detail quality_signals.py mein.
    # Sabhi ka khaali/None matlab EK HI hai: "signal nahi mila". Ye "signal
    # negative hai" se alag baat hai, aur report mein alag likha jaata hai.
    methodology: str = ""                  # controlled vocab: rct/cohort/... (METHODOLOGY_RANK)
    replication: str = ""                  # "evidence_synthesis" | "replication_signal" | ""
    retracted: Optional[bool] = None       # True = retraction se juda signal mila
    coi_disclosed: Optional[bool] = None   # sirf full text padhne par hi pata chalta hai
    funding_disclosed: Optional[bool] = None

    # Spec Section 2 ka honesty rule: "karodon sources mein search karna" aur
    # "karodon sources ka poora text padhna" ALAG cheezein hain. Isliye har
    # source par likha rehta hai ki system ne ise kis gehrai tak padha:
    #   "metadata"  → sirf title/author/year mila, text nahi
    #   "snippet"   → search result ka chhota tukda
    #   "abstract"  → poora abstract mila (paper ka summary)
    #   "full_text" → legally-free full text download + process hua
    # Khaali chhodne par reading_level() khud imaandaar andaza lagata hai.
    read_level: str = ""
    full_text_chars: int = 0               # asli mein kitne chars process hue

    # §12 (2026-08-20): badi PDF poori nahi, PAGE-BY-PAGE padhi jaati hai —
    # sawaal se milte-julte pages chun kar. Aisi haalat mein sirf "full_text"
    # likhna adhoori baat hoti, isliye yahan ek line rehti hai jo saaf batati
    # hai kitne pages mein se kaun padhe gaye. Khaali = poora document padha
    # gaya (ya reading hui hi nahi).
    read_note: str = ""
    pages_read: int = 0                    # streaming reading mein chune hue pages
    pages_total: int = 0                   # document mein kul pages (agar pata ho)

    # Engine ke bhare hue scores
    source_id: str = ""                    # "S1", "S2" ... CitationEngine isse map karta hai
    quality_score: float = 0.0
    relevance_score: float = 0.0
    combined_score: float = 0.0
    round_found: int = 1                   # kis research round mein mila

    # ── §6 (2026-08-20): content se nikala hua ASLI document kind ────────────
    # `source_type` (upar) routing/dedup ka mota label hai — connector se aata
    # hai. Ye teen field content + metadata se bante hain (source_kind.py) aur
    # pata na ho to imaandaari se "unknown" rehte hain. Purana field hataya
    # NAHI gaya: dono saath chalte hain.
    doc_kind: str = ""                     # "review_article" | "preprint" | "unknown" ...
    doc_kind_label: str = ""               # user ko dikhane wala Hinglish label
    doc_kind_confidence: str = ""          # "high" | "medium" | "low"

    # ── §2/§5: domain-level faisla, poori wajah ke saath ────────────────────
    # relevance kyun mili/nahi mili — ye report aur test dono padhte hain.
    domain_verdict: Dict = field(default_factory=dict)
    relevance_parts: Dict = field(default_factory=dict)
    rejected_reason: str = ""              # khaali = reject nahi hua

    # ── PATENT ka structured metadata (patents.PatentMeta.to_dict()) ─────────
    # Khaali dict = ye patent nahi hai (ya provider ne kuch structured nahi
    # diya). Yahan dict rakha hai, dataclass nahi, do wajah se:
    #   1. `asdict()`/`to_dict()` bina kisi extra code ke API tak le jaata hai,
    #   2. models.py ko patents.PatentMeta par type-level nirbhar nahi hona
    #      padta (dependency-free rehna is file ka rule hai).
    # Isme kabhi guess ki hui value nahi jaati — jo provider ne nahi diya, wo
    # field khaali rehti hai aur `missing_fields` mein naam se dikhti hai.
    patent_meta: Dict = field(default_factory=dict)


    # ── helpers ──
    @property
    def domain(self) -> str:
        try:
            netloc = urlparse(self.url).netloc.lower()
            return netloc[4:] if netloc.startswith("www.") else netloc
        except Exception:
            return ""

    @property
    def normalized_title(self) -> str:
        t = re.sub(r"[^\w\s]", " ", (self.title or "").lower())
        return re.sub(r"\s+", " ", t).strip()

    @property
    def is_patent(self) -> bool:
        return self.source_type == SourceType.PATENT

    @property
    def patent_family_key(self) -> str:
        """Ek invention ki ek key (US/EP/WO members ek hi key par)."""
        if not self.patent_meta:
            return ""
        return patent_family_key(self.patent_meta)

    @property
    def independence_key(self) -> str:
        """
        Spec Section 7: "ek hi information ki 100 copied websites ko 100
        independent sources mat maano." DOI same = same work. Warna domain.

        PATENT ka apna rule pehle aata hai: ek hi invention US, EP aur WO —
        teen jagah publish hoti hai. Teeno ka domain bhi same provider ka hota
        hai aur DOI kisi ka nahi hota, to purana rule unhe "domain:data.epo.org"
        par ek saath daal deta — yaani do ALAG inventions bhi ek hi origin gin
        jaate aur cap_per_origin unme se ek ko phenk deta. Family key se dono
        baatein theek hoti hain: ek family = ek evidence, alag family = alag
        evidence.
        """
        if self.is_patent:
            family = self.patent_family_key
            if family:
                return family
        doi = normalize_doi(self.doi)
        if doi:
            return f"doi:{doi}"
        if self.source_type == SourceType.DOCUMENT:
            return f"doc:{self.title.lower()}"
        return f"domain:{self.domain}" if self.domain else f"title:{self.normalized_title[:60]}"

    def citation_label(self) -> str:
        """Prompt ke andar dikhane wala short descriptor."""
        bits = []
        # RETRACTION sabse pehle. Ye cosmetic nahi hai: ye line Gemini ke prompt
        # mein jaati hai, aur reasoning model ko pehle hi pata hona chahiye ki
        # is source ko normal evidence ki tarah use nahi karna.
        if self.retracted is True:
            bits.append("RETRACTION se juda — evidence ki tarah use na karein")
        # Patent ka warning bhi utna hi zaroori hai: prompt mein "patent" shabd
        # dikhna kaafi nahi hai, kyunki model patent ke claims ko aasani se
        # "proven result" maan leta hai. Isliye seedhi bhasha mein likha jaata
        # hai ki ye legal dawa hai.
        if self.is_patent:
            bits.append(PATENT_EVIDENCE_NOTE)
            number = (self.patent_meta or {}).get("number", "")
            if number:
                bits.append(str(number))
            status = (self.patent_meta or {}).get("status_label", "")
            if status:
                bits.append(str(status))
        if self.source_type == SourceType.DOCUMENT:
            bits.append("tumhara uploaded document")
        else:

            # §6: content se nikala hua kind pehle. Connector-based mota label
            # (source_type) tab hi bolte hain jab content kuch pakka na bata
            # sake — warna "review" ko "dataset" keh dena jhooth ban jaata hai.
            bits.append(self.doc_kind_label or self.source_type.value)
        if self.peer_reviewed is True:
            bits.append("peer-reviewed")
        if self.methodology:
            bits.append(methodology_label(self.methodology))
        if self.year:
            bits.append(str(self.year))
        if self.connector:
            bits.append(f"via {self.connector}")
        bits.append(f"padha gaya: {READ_LEVEL_LABELS.get(self.reading_level(), self.reading_level())}")
        return ", ".join(bits)

    @property
    def methodology_rank(self) -> int:
        """Strong design zyada, unknown = -1 (yaani 'pata nahi', 0 se alag)."""
        return methodology_rank(self.methodology)

    def quality_signal_bits(self) -> List[str]:
        """
        Spec Section 7 ke signals ko padhne layak lines mein badlo — sirf wahi
        jinka jawab pakka hai. `None` wale signals yahan nahi aate, kyunki
        "pata nahi" ko "theek hai" ki tarah dikhana hi sabse bada jhooth hota.
        """
        bits: List[str] = []
        if self.retracted is True:
            bits.append("RETRACTION signal")
        if self.methodology:
            bits.append(methodology_label(self.methodology))
        if self.replication:
            bits.append(replication_label(self.replication))
        if self.coi_disclosed is True:
            bits.append("conflict-of-interest statement mila")
        elif self.coi_disclosed is False:
            bits.append("full text mein COI statement nahi mila")
        if self.funding_disclosed is True:
            bits.append("funding source likha hai")
        elif self.funding_disclosed is False:
            bits.append("full text mein funding statement nahi mila")
        return bits

    def reading_level(self) -> str:
        """
        System ne is source ko kitna padha — imaandaar jawab.

        Explicit read_level set ho to wahi. Warna andaza lagate hain, par
        kabhi "full_text" ka andaza NAHI lagate. Full text sirf do jagah se
        set hota hai, dono jagah asli processing ke baad:
            * ContentFetcher — legally-free full text download + process
            * EvidenceEngine / VectorSearch — user ka apna document, jo ingest
              ke waqt poora process hua tha
        Isliye yahan DOCUMENT ke liye koi shortcut nahi hai: agar kisi document
        record par read_level set karna bhool gaye, to wo imaandaari se
        "snippet" dikhega, jhooth se "full_text" nahi.
        """
        if self.read_level:
            return self.read_level
        text = (self.snippet or "").strip()
        # PATENT: gehrai ka jawab patent_meta ke ASLI text se aata hai (kitne
        # chars claims/description ke roop mein process hue), snippet ki lambai
        # se nahi. Ye andaaza nahi hai — connector ne jo text sach mein diya
        # hai, sirf usi par ye level banta hai, aur text na hone par "metadata"
        # hi rehta hai.
        if self.is_patent and self.patent_meta:
            depth = str(self.patent_meta.get("read_depth") or "")
            if depth in READ_LEVEL_ORDER:
                return depth
        if not text:
            return "metadata"
        if self.source_type in (SourceType.PAPER,) and len(text) >= 250:
            return "abstract"
        return "snippet"

    # ── §9 — access depth (5 allowed labels, "VERIFIED" inme se koi nahi) ─────
    def access_depth(self) -> str:
        """
        Humne is source ka kitna TEXT dekha — sirf itni baat.

        Ye claim ke sach hone ke baare mein KUCH NAHI kehta. "18 of 30 pages
        padhe" ka imaandaar label `RELEVANT SECTIONS REVIEWED` hai, `FULL TEXT
        ACCESSED` nahi — ye farq yahan ek hi jagah tay hota hai, taaki report,
        claim-check aur UI teeno wahi ek baat bolein.
        """
        level = self.reading_level()
        label = ACCESS_DEPTH_LABELS.get(level, ACCESS_METADATA)
        if label == ACCESS_FULL:
            pages_total = int(self.pages_total or 0)
            pages_read = int(self.pages_read or 0)
            # poore document ka dava sirf tab jab (a) page ginti pata na ho, ya
            # (b) jitne page the utne padhe gaye hon
            if pages_total and pages_read and pages_read < pages_total:
                return ACCESS_SECTIONS
        return label

    def access_depth_note(self) -> str:
        """Label + insaani matlab + (agar pata ho) page ginti."""
        label = self.access_depth()
        note = f"{label} — {ACCESS_DEPTH_EXPLAIN.get(label, '')}".rstrip(" —")
        pages_total = int(self.pages_total or 0)
        pages_read = int(self.pages_read or 0)
        if pages_total and pages_read:
            note += f" ({pages_read}/{pages_total} page process hue)"
        elif pages_read:
            note += f" ({pages_read} page process hue)"
        return note

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["source_type"] = self.source_type.value
        d["domain"] = self.domain
        d["reading_level"] = self.reading_level()
        d["access_depth"] = self.access_depth()
        d["access_depth_note"] = self.access_depth_note()
        d["methodology_label"] = methodology_label(self.methodology) if self.methodology else ""
        d["methodology_rank"] = self.methodology_rank
        d["quality_signals"] = self.quality_signal_bits()
        if self.is_patent:
            d["patent_family_key"] = self.patent_family_key
            d["patent_evidence_note"] = PATENT_EVIDENCE_NOTE
        return d



# ── Passage ──────────────────────────────────────────────────────────────────
@dataclass
class Passage:
    """Kisi source ka exact hissa + capture-time provenance/depth.

    SourceRecord mutable hai: full-text reading ke baad uska read_level upgrade
    ho sakta hai. Isliye passage ko capture ke waqt ka level alag freeze karna
    zaroori hai; warna purana search snippet baad mein full-text evidence ban
    sakta hai. Khaali fields legacy/manual callers ke liye backward-compatible
    hain; production writers inhe explicitly set karte hain.
    """
    source_id: str
    text: str
    locator: str = ""
    provenance: str = ""
    read_level_at_capture: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


# ── Claim ────────────────────────────────────────────────────────────────────
@dataclass
class Claim:
    """
    Spec Section 7 — har important claim apne evidence/provenance ke saath.
    source_ids khaali hona = claim kisi source se linked nahi hai (honesty flag).
    """
    text: str
    claim_type: ClaimType = ClaimType.UNKNOWN
    source_ids: List[str] = field(default_factory=list)

    @property
    def is_grounded(self) -> bool:
        return len(self.source_ids) > 0

    def to_dict(self) -> Dict:
        # Older Android/API consumers already understand UNKNOWN but may reject
        # an enum value added after their build.  Keep the legacy field inside
        # the old vocabulary while exposing the precise new state separately.
        # New code should prefer ``claim_state`` when present.
        serialized = (
            ClaimType.UNKNOWN.value
            if self.claim_type == ClaimType.UNVERIFIED
            else self.claim_type.value
        )
        payload = {
            "text": self.text,
            "claim_type": serialized,
            "source_ids": self.source_ids,
            "grounded": self.is_grounded,
        }
        if self.claim_type == ClaimType.UNVERIFIED:
            payload["claim_state"] = ClaimType.UNVERIFIED.value
        return payload


# ── EvidencePack ─────────────────────────────────────────────────────────────
@dataclass
class EvidencePack:
    """
    Spec Section 6 + 7 — jo evidence reasoning model ko diya jayega, uska
    structured bundle. Yahi cheez "bade prompt" aur "real research engine" ka
    farq hai: sources ke IDs, metadata, independence aur coverage sab track hote hain.
    """
    question: str = ""
    sources: List[SourceRecord] = field(default_factory=list)
    passages: List[Passage] = field(default_factory=list)
    rounds_run: int = 0
    discovered_count: int = 0      # dedup/ranking se pehle kitne mile the
    searched_connectors: List[str] = field(default_factory=list)

    # ── retrieval ki honest report (live failure 2026-08-19 ke baad add hui) ──
    # Pehle pack ke paas ye pata hi nahi tha ki jo sources usme hain wo sawaal
    # ke topic ke hain ya nahi. Isliye grade_evidence sirf ginti dekh kar
    # "✅ VERIFIED" chhaap deta tha — jabki us test mein saare sources off-topic
    # the (Gagea phool, surgeons density) aur 0/5 ka full text pada tha.
    # Ab retrieval ka sach pack ke saath chalta hai.
    topic_terms: List[str] = field(default_factory=list)
    retrieval_filter: Dict = field(default_factory=dict)

    # §11 — jo queries SACH MEIN chali. Consensus gate isse dekh kar batata hai
    # ki opposition/criticism side ki search hui thi ya sirf support side ki.
    # Pehle ye jaankari discovery loop ke andar hi mar jaati thi.
    search_queries: List[str] = field(default_factory=list)

    # reasoning passes poore hue ya quota/error se adhoore reh gaye
    reasoning_planned: int = 0
    reasoning_done: int = 0
    reasoning_failures: List[str] = field(default_factory=list)

    # ── lookups ──
    def by_id(self, source_id: str) -> Optional[SourceRecord]:
        for s in self.sources:
            if s.source_id == source_id:
                return s
        return None

    @property
    def valid_ids(self) -> List[str]:
        return [s.source_id for s in self.sources if s.source_id]

    @property
    def independent_source_count(self) -> int:
        """Spec Section 7 — copied duplicates ko ek hi ginte hain."""
        return len({s.independence_key for s in self.sources})

    def document_sources(self) -> List[SourceRecord]:
        return [s for s in self.sources if s.source_type == SourceType.DOCUMENT]

    # ── retrieval sach (VERIFIED ka gate inhi par lagta hai) ──
    @property
    def avg_relevance(self) -> float:
        """Jo sources use ho rahe hain, wo topic se kitne match karte hain."""
        if not self.sources:
            return 0.0
        return round(
            sum(s.relevance_score for s in self.sources) / len(self.sources), 3)

    @property
    def on_topic_count(self) -> int:
        """Kitne sources ka topic se theek-thaak match hai (0.25+)."""
        return len([s for s in self.sources if s.relevance_score >= 0.25])

    @property
    def full_text_read_count(self) -> int:
        """
        Kitne sources ka POORA text asal mein padha gaya.

        Ye ginti do tarah se ban sakti hai aur dono asli hain: internet se
        legally-free full text download hua (full_text_chars > 0), ya user ka
        apna uploaded document jo ingest ke waqt poora process hua tha.
        """
        return len([
            s for s in self.sources
            if s.full_text_chars > 0
            or (s.source_type == SourceType.DOCUMENT
                and s.reading_level() == "full_text")
        ])

    @property
    def reasoning_complete(self) -> bool:
        """
        Jitne reasoning pass plan hue the, utne chale ya nahi.

        `reasoning_planned == 0` ka matlab "kisi ne bataya hi nahi" hai —
        us halat mein hum ise "poora ho gaya" NAHI maanenge, kyunki bina
        jaankari ke shabaashi dena hi wo bug tha jise theek kar rahe hain.
        """
        return self.reasoning_planned > 0 and self.reasoning_done >= self.reasoning_planned

    def relevance_note(self) -> str:
        """Retrieval ne kya chhaanta — asli ginti se banti line, hardcoded nahi."""
        if not self.sources:
            return "Koi source select nahi hua."
        info = self.retrieval_filter or {}
        parts = [f"Topic terms: {', '.join(self.topic_terms) or '—'}."]
        dropped = int(info.get("dropped_offtopic") or 0)
        if dropped:
            parts.append(f"{dropped} source topic se bilkul match nahi kar rahe the, "
                         f"isliye hata diye gaye.")
        parts.append(f"Jo {len(self.sources)} use ho rahe hain unka average topic "
                     f"match {self.avg_relevance:.2f} hai "
                     f"({self.on_topic_count} theek-thaak match).")
        borderline = int(info.get("borderline_used") or 0)
        if borderline:
            parts.append(f"{borderline} source kamzor match ke hain — acche sources "
                         f"kam pad gaye the, isliye majboori mein liye gaye.")
        # §6 (2026-08-22): "topic ka hai" aur "sawaal ki baat test karta hai" —
        # ye do alag cheezein hain, aur report mein bhi alag likhni chahiye.
        # Dark-matter run mein average match 0.43 tha aur usi ginti ko "evidence"
        # kaha gaya tha, jabki kai source sirf usi field ke the.
        prop = info.get("proposition") or {}
        if prop:
            yes = prop.get("tests_proposition")
            no = prop.get("does_not_test")
            und = prop.get("undecided")
            parts.append(
                f"Inme se {yes} source sawaal ki baat sach mein test karte hain, "
                f"{no} nahi karte, aur {und} par faisla nahi ho saka (metadata "
                f"itna hi mila) — aakhri ginti ko 'theek hai' na samjhein.")
        return " ".join(parts)

    def proposition_report(self) -> Dict:
        """§6 — relevance gate ka structured record (khaali dict = gate chala nahi)."""
        return dict((self.retrieval_filter or {}).get("proposition") or {})

    def reject_code_counts(self) -> Dict:
        """§6 — kis code se kitne source hate (free-text nahi, ginne layak codes)."""
        info = (self.retrieval_filter or {}).get("reject_codes") or {}
        return dict(info.get("counts") or {})

    def reasoning_note(self) -> str:
        if self.reasoning_planned <= 0:
            return "Reasoning passes ki ginti record nahi hui."
        if self.reasoning_complete:
            return f"{self.reasoning_done}/{self.reasoning_planned} reasoning pass poore hue."
        note = (f"SIRF {self.reasoning_done}/{self.reasoning_planned} reasoning pass "
                f"poore ho sake — is jawab ka reasoning adhoora hai.")
        if self.reasoning_failures:
            note += " Wajah: " + "; ".join(self.reasoning_failures[:3])
        return note

    def external_sources(self) -> List[SourceRecord]:
        return [s for s in self.sources if s.source_type != SourceType.DOCUMENT]

    # ── prompt rendering ──
    def to_prompt_block(self, max_chars_per_source: int = 1200) -> str:
        """
        Sources ko [S1] [S2] ... blocks mein render karo.
        Gemini ko inhi IDs se cite karne ko kaha jayega, taaki CitationEngine
        baad mein verify kar sake ki citation asli hai ya banayi hui.
        """
        if not self.sources:
            return "(Koi source retrieve nahi hua.)"
        blocks = []
        for s in self.sources:
            head = f"[{s.source_id}] ({s.citation_label()})"
            meta = []
            if s.title:
                meta.append(f"Title: {s.title}")
            if s.authors:
                meta.append(f"Author(s): {', '.join(s.authors[:4])}")
            if s.publisher:
                meta.append(f"Publisher: {s.publisher}")
            if s.venue:
                meta.append(f"Venue: {s.venue}")
            if s.locator:
                meta.append(f"Location: {s.locator}")
            if s.url:
                meta.append(f"URL: {s.url}")
            # Read level prompt mein JAANA zaroori hai: claim_labels.py ka rule
            # ("[ESTABLISHED] sirf full text par") model tabhi follow kar sakta
            # hai jab use pata ho ki kis source ka kitna hissa padha gaya. Pehle
            # ye line nahi thi, isliye model abstract-only source par bhi
            # [ESTABLISHED] chipka deta tha.
            meta.append(f"Read: {s.reading_level()}")
            # §12: badi PDF page-by-page padhi gayi ho to model ko yahi batana
            # zaroori hai, warna wo "poora document padha gaya" maan kar
            # [ESTABLISHED] label laga deta hai.
            if s.read_note:
                meta.append(f"Read scope: {s.read_note}")
            # PATENT ke liye ek aur line: kis daftar ka, kis family ka, aur
            # kitna hissa (abstract / claims / description) sach mein process
            # hua. Bina iske model "patent kehta hai X" ko "X saabit hai" bana
            # deta hai — aur family info bina, ek hi invention ke US/EP/WO ko
            # "teen patents isi baat par sehmat hain" likh deta hai.
            if s.is_patent:
                pm = s.patent_meta or {}
                patent_bits = [b for b in (
                    f"number: {pm.get('number', '')}" if pm.get("number") else "",
                    f"office: {pm.get('jurisdiction_label', '')}" if pm.get("jurisdiction_label") else "",
                    f"family: {pm.get('family_key', '')}" if pm.get("family_key") else "",
                    f"claims: {pm.get('claim_count', 0)}" if pm.get("claim_count") else "claims text nahi mila",
                    str(pm.get("status_label", "")),
                ) if b]
                meta.append("Patent info: " + " | ".join(patent_bits))
                meta.append("Patent rule: " + PATENT_EVIDENCE_NOTE)

            body = (s.snippet or "").strip()[:max_chars_per_source]
            if body:
                meta.append(f"Excerpt: {body}")
            blocks.append(head + "\n" + "\n".join(meta))
        return "\n\n".join(blocks)

    def read_level_counts(self) -> Dict[str, int]:
        """Kitne sources kis gehrai tak padhe gaye — sirf ginti, dava nahi."""
        counts: Dict[str, int] = {}
        for s in self.sources:
            level = s.reading_level()
            counts[level] = counts.get(level, 0) + 1
        # stable order (metadata → full_text), khaali levels chhod do
        return {lvl: counts[lvl] for lvl in READ_LEVEL_ORDER if lvl in counts}

    def reading_note(self) -> str:
        """
        Spec Section 2 ka rule yahan enforce hota hai: jo padha usi ka dava.
        Ye line hardcoded nahi hai — asli counts se banti hai, isliye jhooth
        bol hi nahi sakti.

        Do tarah ka "full text" alag-alag bataya jaata hai, kyunki inka matlab
        alag hai: (1) jo internet se legally-free download hua, aur (2) jo
        aapne khud upload kiya tha aur ingest ke waqt poora process hua.
        """
        if not self.sources:
            return ("Koi source retrieve nahi hua, isliye kuch bhi padha nahi "
                    "gaya.")
        counts = self.read_level_counts()
        parts = [f"{n} {READ_LEVEL_LABELS.get(lvl, lvl)}" for lvl, n in counts.items()]
        note = f"{len(self.sources)} sources mein se: " + ", ".join(parts) + "."

        downloaded = [s for s in self.sources if s.full_text_chars > 0]
        if downloaded:
            chars = sum(s.full_text_chars for s in downloaded)
            note += (f" {len(downloaded)} source(s) ka legally-free full text "
                     f"download karke process kiya gaya (~{chars:,} chars).")

        own_docs = [s for s in self.sources
                    if s.source_type == SourceType.DOCUMENT
                    and s.reading_level() == "full_text"]
        if own_docs:
            note += (f" {len(own_docs)} aapke apne uploaded document ka hissa hai — "
                     f"wo file upload ke waqt poori process hui thi, yahan uske "
                     f"sabse relevant hisse hain.")

        # §12: jin badi files ko page-by-page padha gaya, unka dava "poora
        # document padh liya" nahi ho sakta. Ginti asli fields se banti hai.
        streamed = [s for s in self.sources if s.pages_read and s.pages_total]
        if streamed:
            pages_read = sum(s.pages_read for s in streamed)
            pages_total = sum(s.pages_total for s in streamed)
            note += (f" {len(streamed)} badi file(s) page-by-page padhi gayi: "
                     f"{pages_total} pages mein se sawaal se sabse milte-julte "
                     f"{pages_read} pages hi process hue — inka poora document "
                     f"padha gaya aisa dava nahi hai.")

        if counts.get("full_text", 0) < len(self.sources):
            note += (" Baaki sources ka poora text NAHI padha gaya — un par sirf "
                     "utna hi dava hai jitna upar likhe level se pata chala.")
        return note

    # ── Spec Section 7 signal roll-up ──
    def methodology_counts(self) -> Dict[str, int]:
        """
        Kis design ke kitne sources — strong se weak ke order mein.
        Jinka methodology pata nahi chala, wo "unknown" mein ginte hain
        (chhupate nahi, warna evidence base asli se strong dikhega).
        """
        counts: Dict[str, int] = {}
        for s in self.sources:
            key = s.methodology or "unknown"
            counts[key] = counts.get(key, 0) + 1
        ordered = sorted(
            counts.items(),
            key=lambda kv: (-METHODOLOGY_RANK.get(kv[0], -1), kv[0]),
        )
        return dict(ordered)

    def retracted_sources(self) -> List[SourceRecord]:
        return [s for s in self.sources if s.retracted is True]

    # ── PATENT roll-up (patent ≠ scientific proof) ───────────────────────────
    def patent_sources(self) -> List[SourceRecord]:
        return [s for s in self.sources if s.is_patent]

    def science_sources(self) -> List[SourceRecord]:
        """
        Patent NIKAAL kar baaki sources — "scientific evidence" ki ginti isi
        list par honi chahiye. Pehle poori list par ginti hoti, to 3 patent +
        0 paper wala pack "3 sources sehmat hain" bol deta.
        """
        return [s for s in self.sources if not s.is_patent]

    def patent_families(self) -> Dict[str, List[SourceRecord]]:
        """family key → us family ke records (khaali key wale bahar)."""
        groups: Dict[str, List[SourceRecord]] = {}
        for s in self.patent_sources():
            key = s.patent_family_key
            if key:
                groups.setdefault(key, []).append(s)
        return groups

    def patent_family_count(self) -> int:
        """
        Kitni ALAG inventions. Jis patent ka family key nahi bana (metadata
        adhoora tha) usse alag-alag ginte hain — kyunki uske baare mein humein
        pata NAHI hai ki wo kisi doosre ka family member hai ya nahi, aur
        "pata nahi" ko "same family" maan lena evidence chhupana hoga.
        """
        keyed = self.patent_families()
        unkeyed = len([s for s in self.patent_sources() if not s.patent_family_key])
        return len(keyed) + unkeyed

    def patent_read_depth_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for s in self.patent_sources():
            level = s.reading_level()
            counts[level] = counts.get(level, 0) + 1
        return {lvl: counts[lvl] for lvl in READ_LEVEL_ORDER if lvl in counts}

    def patent_note(self) -> str:
        """
        Patent evidence ka imaandaar bayaan — ginti se banta hai, hardcoded
        nahi. Do baatein jaan-boojh kar likhi jaati hain: (1) publications vs
        alag families ka farq, aur (2) kitne patents ka claims text SACH MEIN
        process hua — kyunki "patent padha" ka dawa sirf usi par ban sakta hai.
        """
        patents = self.patent_sources()
        if not patents:
            return ""
        families = self.patent_family_count()
        depth = self.patent_read_depth_counts()
        read_deep = depth.get("claims", 0) + depth.get("full_text", 0)
        note = (f"{len(patents)} patent publication mile, jo {families} alag "
                f"invention family ko dikhate hain (ek hi invention ke US/EP/WO "
                f"members ko alag evidence nahi gina gaya).")
        if read_deep:
            note += (f" Inme se {read_deep} ke claims/description sach mein "
                     f"process hue; baaki par sirf metadata/abstract tak baat "
                     f"ki ja sakti hai.")
        else:
            note += (" Kisi bhi patent ke claims/description process NAHI hue — "
                     "isliye 'patent padha' jaisa dawa is jawab mein nahi "
                     "banta.")
        note += " " + PATENT_EVIDENCE_NOTE
        if not self.science_sources():
            note += (" CHETAVANI: is pack mein patent ke alawa koi source nahi "
                     "hai — sirf patent ke bharose koi baat scientifically "
                     "saabit nahi maani ja sakti.")
        return note


    def strong_methodology_sources(self) -> List[SourceRecord]:
        return [s for s in self.sources if s.methodology_rank >= 5]

    def quality_signal_note(self) -> str:
        """
        Spec Section 7 ka honest summary. Do cheezein jaan-boojh kar likhi
        jaati hain: (1) kitne sources ka design pata BHI nahi chala, aur
        (2) COI/funding ka jawab sirf full text padhne par milta hai. Inko
        chhupane se evidence base asli se mazboot dikhne lagta hai.
        """
        if not self.sources:
            return "Koi source nahi mila, isliye quality signals bhi nahi hain."

        total = len(self.sources)
        parts: List[str] = []

        retracted = self.retracted_sources()
        if retracted:
            ids = ", ".join(s.source_id or s.title[:30] for s in retracted)
            parts.append(
                f"CHETAVANI: {len(retracted)} source par retraction/withdrawal ka "
                f"signal hai ({ids}) — inhe normal evidence ki tarah use nahi "
                f"karna chahiye.")

        counts = self.methodology_counts()
        known = {k: v for k, v in counts.items() if k != "unknown"}
        if known:
            listed = ", ".join(f"{n} {methodology_label(k)}" for k, n in known.items())
            parts.append(f"Study design: {listed}.")
        unknown = counts.get("unknown", 0)
        if unknown:
            parts.append(
                f"{unknown}/{total} sources ka study design metadata se pata nahi "
                f"chala — inka design 'strong' maan lena galat hoga.")
        else:
            strong = len(self.strong_methodology_sources())
            parts.append(f"Inme se {strong} strong design (RCT/meta-analysis level) hain.")

        checked = [s for s in self.sources if s.coi_disclosed is not None]
        if checked:
            disclosed = len([s for s in checked if s.coi_disclosed is True])
            parts.append(
                f"Conflict-of-interest sirf un {len(checked)} source par check ho "
                f"saka jinka full text mila; {disclosed} mein COI statement tha.")
        else:
            parts.append(
                "Conflict-of-interest kisi source par check nahi ho saka — ye "
                "statement sirf full text mein hoti hai, abstract mein nahi.")
        return " ".join(parts)

    def coverage_report(self) -> Dict:
        """Spec Section 2 + 7 — coverage aur source-quality ki honest report."""
        return {
            "sources_used": len(self.sources),
            "independent_sources": self.independent_source_count,
            "candidates_discovered": self.discovered_count,
            "documents_from_user": len(self.document_sources()),
            "external_sources": len(self.external_sources()),
            "connectors_searched": self.searched_connectors,
            "research_rounds": self.rounds_run,
            "read_levels": self.read_level_counts(),
            "full_text_chars_read": sum(s.full_text_chars for s in self.sources),
            "full_text_sources_read": self.full_text_read_count,
            "honesty_note": self.reading_note(),
            # retrieval ka sach — inhi par VERIFIED/STRONG ka gate lagta hai
            "topic_terms": list(self.topic_terms),
            "avg_relevance": self.avg_relevance,
            "on_topic_sources": self.on_topic_count,
            "offtopic_dropped": int((self.retrieval_filter or {}).get(
                "dropped_offtopic") or 0),
            "relevance_note": self.relevance_note(),
            # §6 — relevance gate ka structured hisaab (proposition-test +
            # reject codes). Khaali dict = gate chala hi nahi, "sab pass" nahi.
            "proposition_test": self.proposition_report(),
            "relevance_reject_codes": self.reject_code_counts(),
            "reasoning_passes": f"{self.reasoning_done}/{self.reasoning_planned}",
            "reasoning_note": self.reasoning_note(),
            "methodologies": self.methodology_counts(),
            "retracted_sources": len(self.retracted_sources()),
            "strong_methodology_sources": len(self.strong_methodology_sources()),
            "coi_checked_sources": len(
                [s for s in self.sources if s.coi_disclosed is not None]),
            "quality_signal_note": self.quality_signal_note(),
            # ── patent evidence, scientific evidence se ALAG ginti mein ──
            # Ye keys hamesha rehti hain (0 bhi ek imaandaar jawab hai), taaki
            # audit padhne wale ko pata rahe ki patent tier dekha gaya tha.
            "patent_sources": len(self.patent_sources()),
            "patent_families": self.patent_family_count(),
            "patent_read_levels": self.patent_read_depth_counts(),
            "science_sources": len(self.science_sources()),
            "patent_note": self.patent_note(),
        }


    def to_dict(self) -> Dict:
        return {
            "question": self.question,
            "sources": [s.to_dict() for s in self.sources],
            "passages": [p.to_dict() for p in self.passages],
            "coverage": self.coverage_report(),
        }


# ── ResearchResult ───────────────────────────────────────────────────────────
@dataclass
class ResearchResult:
    """
    Final output. Purane API contract ke saare keys yahan preserve hain
    (question, answer, sources, safety_flags, evidence_level, mode,
    question_types, relevant_fields) — plus naye research fields.
    """
    question: str = ""
    answer: str = ""
    sources: List[Dict] = field(default_factory=list)
    safety_flags: List[Dict] = field(default_factory=list)
    evidence_level: str = ""
    mode: str = "DEEP"
    question_types: List[str] = field(default_factory=list)
    relevant_fields: List[str] = field(default_factory=list)

    citations: List[Dict] = field(default_factory=list)
    uncited_sources: List[Dict] = field(default_factory=list)
    invalid_citations: List[str] = field(default_factory=list)
    ungrounded_claims: List[str] = field(default_factory=list)
    contradictions: List[Dict] = field(default_factory=list)
    hypotheses: List[Dict] = field(default_factory=list)
    verification: Dict = field(default_factory=dict)
    coverage: Dict = field(default_factory=dict)
    # "maanga vs mila" ka ledger aur label-gate ka report. Ye answer text mein
    # bhi chhapte hain, par API/UI ko structured roop mein bhi chahiye — warna
    # frontend ko dobara text parse karna padta.
    requested_ledger: Dict = field(default_factory=dict)
    label_report: Dict = field(default_factory=dict)
    # Advanced scientific-discovery assessment.  Structured and optional so
    # older Android clients that ignore unknown fields remain compatible.
    discovery: Dict = field(default_factory=dict)
    # Specialist evidence lanes keep empirical science, official/declassified
    # records, historical/traditional texts, allegations and app-original
    # hypotheses machine-readably separate.  Optional for old clients.
    specialist_research: Dict = field(default_factory=dict)
    gemini_calls_used: int = 0
    warnings: List[str] = field(default_factory=list)

    # §1 — run ka imaandaar status, UI ke liye machine-readable.
    # "COMPLETE" / "PARTIAL" / "RESEARCH INCOMPLETE". Pehle adhoora run bhi
    # normal jawab jaisa dikhta tha; ab frontend seedha `status` dekh kar
    # warning banner laga sakta hai bina answer text parse kiye.
    status: str = "COMPLETE"
    status_reason: str = ""              # ek line, insaani bhasha (raw error nahi)
    failure_kind: str = ""               # daily_quota / auth_failure / ...
    missing_passes: List[str] = field(default_factory=list)
    missing_sections: List[str] = field(default_factory=list)
    # §9 — raw API/protobuf text SIRF yahan (aur report ke sabse neeche).
    # Ye kabhi bhi user-facing jawab ka hissa nahi banta.
    technical_details: List[str] = field(default_factory=list)
    api_accounting: Dict = field(default_factory=dict)

    # §4 + §7/§19 — "kya maanga gaya tha" (quality_contract), "kya asli mein
    # mila" (quality_context) aur dono ka aamna-saamna (contract_ledger).
    # Ye teen structured roop mein API/UI/final-gate tak jaate hain, taaki koi
    # bhi in numbers ke liye answer ka text parse na kare — text parse karna hi
    # wo raasta tha jisse audit ke andar ek doosre se ulte numbers aa gaye the.
    quality_contract: Dict = field(default_factory=dict)
    quality_context: Dict = field(default_factory=dict)
    contract_ledger: Dict = field(default_factory=dict)

    # §20 — chaar ALAG state ek hi dict mein: job_status / answer_state /
    # evidence_state / novelty_state, plus `conflicts` aur `verified_allowed`.
    # UI ko inme se kisi ek ka matlab doosre se nikaalna mana hai — pehle yahi
    # hota tha ("job FINISHED" ko "jawab COMPLETE" padh liya jaata tha).
    # Banane wala module: research_engine/research_state.py
    research_state: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)
