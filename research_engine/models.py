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
from urllib.parse import urlparse

from .quality_signals import (
    METHODOLOGY_RANK,
    methodology_label,
    methodology_rank,
    replication_label,
)


# ── Source types (Spec Section 2) ─────────────────────────────────────────────
class SourceType(str, Enum):
    DOCUMENT = "document"          # user ka apna uploaded PDF/note
    PAPER = "paper"                # research paper / preprint
    BOOK = "book"                  # book (full text ya sirf metadata)
    WEB = "web"                    # general webpage
    ENCYCLOPEDIA = "encyclopedia"  # Wikipedia/Wikimedia
    DATASET = "dataset"            # government/public dataset
    TRANSCRIPT = "transcript"      # video/audio transcript


# ── Reading levels (Spec Section 2 ka honesty rule) ──────────────────────────
# "Karodon sources mein search karna" aur "karodon sources ka poora text
# padhna" alag cheezein hain. Isliye system har source ke saath ye level
# report karta hai, aur final report mein isi ka breakdown chhapta hai.
READ_LEVEL_ORDER = ["metadata", "snippet", "abstract", "full_text"]
READ_LEVEL_LABELS = {
    "metadata": "sirf metadata (title/author/year)",
    "snippet": "search snippet",
    "abstract": "abstract",
    "full_text": "full text",
}


# ── Claim classification (Spec Section 7) ────────────────────────────────────
class ClaimType(str, Enum):
    FACT = "FACT"
    EVIDENCE = "EVIDENCE"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    SPECULATION = "SPECULATION"
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
    "UNVERIFIED": ClaimType.SPECULATION,
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

    # Engine ke bhare hue scores
    source_id: str = ""                    # "S1", "S2" ... CitationEngine isse map karta hai
    quality_score: float = 0.0
    relevance_score: float = 0.0
    combined_score: float = 0.0
    round_found: int = 1                   # kis research round mein mila

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
    def independence_key(self) -> str:
        """
        Spec Section 7: "ek hi information ki 100 copied websites ko 100
        independent sources mat maano." DOI same = same work. Warna domain.
        """
        if self.doi:
            return f"doi:{self.doi.lower()}"
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
        if self.source_type == SourceType.DOCUMENT:
            bits.append("tumhara uploaded document")
        else:
            bits.append(self.source_type.value)
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
        if not text:
            return "metadata"
        if self.source_type in (SourceType.PAPER,) and len(text) >= 250:
            return "abstract"
        return "snippet"

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["source_type"] = self.source_type.value
        d["domain"] = self.domain
        d["reading_level"] = self.reading_level()
        d["methodology_label"] = methodology_label(self.methodology) if self.methodology else ""
        d["methodology_rank"] = self.methodology_rank
        d["quality_signals"] = self.quality_signal_bits()
        return d


# ── Passage ──────────────────────────────────────────────────────────────────
@dataclass
class Passage:
    """Kisi source ka wo hissa jo actually reasoning model ko bheja gaya."""
    source_id: str
    text: str
    locator: str = ""

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
        return {
            "text": self.text,
            "claim_type": self.claim_type.value,
            "source_ids": self.source_ids,
            "grounded": self.is_grounded,
        }


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
        return " ".join(parts)

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
            "reasoning_passes": f"{self.reasoning_done}/{self.reasoning_planned}",
            "reasoning_note": self.reasoning_note(),
            "methodologies": self.methodology_counts(),
            "retracted_sources": len(self.retracted_sources()),
            "strong_methodology_sources": len(self.strong_methodology_sources()),
            "coi_checked_sources": len(
                [s for s in self.sources if s.coi_disclosed is not None]),
            "quality_signal_note": self.quality_signal_note(),
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
    gemini_calls_used: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)
