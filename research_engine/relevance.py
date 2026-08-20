"""
RelevanceEngine — Spec Section 6

"Agar 100,000 documents mile to sabhi ko Gemini ko mat bhejo."

Pipeline:
    dedupe -> quality score -> relevance score -> combined -> origin diversity
    -> top N (progressive selection)

Quality signals (Spec Section 7): primary vs secondary, peer-reviewed,
publication date, source authority, independence.
Ye sab free/offline hai — koi API call nahi.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .dedup import DeduplicationEngine
from .models import SourceRecord, SourceType
from .quality_signals import STRONG_METHODOLOGY, WEAK_METHODOLOGY, enrich_record
from .query_builder import topic_terms

# Domain authority tiers
_TIER_1 = (  # peer-reviewed / primary scholarly infrastructure
    "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "nature.com", "science.org",
    "sciencedirect.com", "springer.com", "link.springer.com", "wiley.com",
    "cell.com", "thelancet.com", "nejm.org", "bmj.com", "plos.org",
    "ieee.org", "ieeexplore.ieee.org", "acm.org", "dl.acm.org", "jstor.org",
    "doi.org", "openalex.org", "semanticscholar.org", "crossref.org", "doaj.org",
)
_TIER_2 = (  # preprints, official bodies, universities
    "arxiv.org", "biorxiv.org", "medrxiv.org", "ssrn.com", "osf.io",
    ".gov", ".gov.in", ".edu", ".ac.uk", ".ac.in", "who.int", "un.org",
    "worldbank.org", "oecd.org", "nist.gov", "nasa.gov",
)
_TIER_3 = ("wikipedia.org", "wikimedia.org", "archive.org", "books.google.com")
_LOW_TRUST = (
    "reddit.com", "quora.com", "yahoo.com", "pinterest.com", "medium.com",
    "blogspot.", "wordpress.com", "facebook.com", "twitter.com", "x.com",
    "tiktok.com", "answers.com",
)
_EVIDENCE_WORDS = (
    "peer-reviewed", "peer reviewed", "randomized", "randomised", "meta-analysis",
    "systematic review", "cohort", "clinical trial", "sample size", "p <", "p<",
    "doi:", "published", "journal", "abstract", "methodology", "dataset",
)

# ── relevance ke knobs ───────────────────────────────────────────────────────
# Kitne top topic terms par relevance naapein. Poore sawaal ke saare shabd lena
# hi live failure ki jad thi: 2000-character prompt = 300+ shabd, aur ek sahi
# paper bhi 3-4 shabd hi match karta hai -> ratio 0.01 -> "relevance = 0" jaisa.
# Phir combined score sirf domain authority se banta tha, aur who.int ka
# surgeons-density page energy ke sawaal mein top par aa jaata tha.
_TOPIC_TERMS = 8
# Denominator: itne terms match ho gaye to "poora match" maan lo. Ek paper ka
# title chhota hota hai — usse 8 mein se 8 term match karna asambhav hai.
_FULL_MATCH_TERMS = 4


def _stem(term: str) -> str:
    """Bahut halka stemming — 'batteries' aur 'battery' ek hi cheez hain."""
    term = term.lower()
    if len(term) > 5 and term.endswith("ies"):
        return term[:-3]
    if len(term) > 4 and term.endswith("s") and not term.endswith(("ss", "us", "is")):
        return term[:-1]
    return term


def _hits(terms: List[str], text: str) -> int:
    """Kitne topic terms is text mein hain (halka stem + substring match)."""
    low = (text or "").lower()
    if not low:
        return 0
    return sum(1 for t in terms if _stem(t) in low)


class RelevanceEngine:
    def __init__(self, dedup: Optional[DeduplicationEngine] = None):
        self.dedup = dedup or DeduplicationEngine()
        # ranking ki honest report — build_pack ise pack mein copy karta hai
        self.last_filter: Dict = {}
        self._topic_cache: Dict[str, List[str]] = {}

    # ── topic terms (query_builder se, ek hi jagah se) ───────────────────────
    def topic_of(self, query: str) -> List[str]:
        """
        Sawaal ka topic — search query banane wala WAHI code.

        Ek hi source-of-truth hona zaroori hai: agar hum "energy battery solar"
        dhoondein aur relevance kisi aur list se naapein, to jo mila usko "sahi
        hai" kehne ka koi aadhar nahi bachta.
        """
        key = (query or "")[:600]
        cached = self._topic_cache.get(key)
        if cached is None:
            cached = topic_terms(query, limit=_TOPIC_TERMS)
            if len(self._topic_cache) > 32:      # chhota bounded cache
                self._topic_cache.clear()
            self._topic_cache[key] = cached
        return cached

    # ── quality (Spec Section 7) ──────────────────────────────────────────────
    def score_quality(self, s: SourceRecord) -> float:
        score = 0.40
        url = (s.url or "").lower()
        snippet = (s.snippet or "").lower()

        # user ka apna document — trust high, kyunki usne khud diya hai
        if s.source_type == SourceType.DOCUMENT:
            score = 0.75
        elif any(d in url for d in _TIER_1):
            score = 0.80
        elif any(d in url for d in _TIER_2):
            score = 0.70
        elif any(d in url for d in _TIER_3):
            score = 0.55

        if s.peer_reviewed is True:
            score += 0.10
        if s.is_primary is True:
            score += 0.05
        if s.doi:
            score += 0.05
        if s.full_text_available:
            score += 0.03

        if any(w in snippet for w in _EVIDENCE_WORDS):
            score += 0.05
        if len(snippet) > 250:
            score += 0.04
        elif len(snippet) < 60:
            score -= 0.08

        # recency — naya data thoda better, par purane classics ko mat maaro
        if s.year:
            age = datetime.now().year - s.year
            if age <= 5:
                score += 0.05
            elif age > 25:
                score -= 0.05

        if s.citation_count and s.citation_count > 50:
            score += 0.04

        # ── Spec Section 7: methodology strength (signal #7) ──
        # Design se hi kitna bharosa banta hai. Unknown (-1) par kuch nahi
        # jodte-ghatate — "pata nahi" ko na inaam, na saza.
        rank = s.methodology_rank
        if rank >= STRONG_METHODOLOGY:
            score += 0.07
        elif rank >= 3:
            score += 0.04
        elif rank > WEAK_METHODOLOGY:
            score += 0.01
        elif rank == 0:
            score -= 0.05          # editorial/opinion — research nahi hai

        # replication ka zikr (signal #8) chhota bonus hai, kyunki free metadata
        # se sirf "zikr hai" pata chalta hai, "replicate ho gaya" nahi
        if s.replication:
            score += 0.02
        # COI/funding transparency (signal #10) — disclosure hone par thoda bonus.
        # Na hone par saza NAHI, kyunki wo lekhak ki galti bhi ho sakti hai aur
        # hum sirf ek regex se dekh rahe hain.
        if s.coi_disclosed is True:
            score += 0.02

        if any(d in url for d in _LOW_TRUST):
            score -= 0.25
        if not url and s.source_type != SourceType.DOCUMENT:
            score -= 0.10

        # ── retraction (signal #9) sabse bhaari — sabse aakhir mein ──
        # Ye baaki sab bonus ke BAAD lagta hai, taaki ek retracted Nature paper
        # bhi (tier-1 domain + peer-reviewed + citations) neeche chala jaaye.
        # Ranking mein neeche jaana = zyada chance ki wo top-N mein hi na aaye.
        if s.retracted is True:
            score -= 0.50

        return round(min(max(score, 0.0), 1.0), 4)

    # ── relevance ─────────────────────────────────────────────────────────────
    def score_relevance(self, s: SourceRecord, query: str) -> float:
        """
        Ye source sawaal ke topic ka hai ya nahi — 0.0 se 1.0.

        PURANA TARIKA (aur uski galti): query ke SAARE shabd le kar
        `len(match) / len(query_words)` nikalte the. Chhote sawaal par ye theek
        chalta hai, par 2000-character prompt par denominator 300+ ho jaata hai,
        matlab ek bilkul sahi paper ka score bhi ~0.01 aata tha. Us halat mein
        combined score sirf quality (domain authority) se banta tha — isliye
        who.int ka "surgeons density" page energy ke sawaal mein top par aaya.

        NAYA TARIKA: sirf top topic terms, aur denominator par cap
        (_FULL_MATCH_TERMS). 4 core terms match = poora match. Title ko snippet
        se zyada wazan, kyunki title paper ka asli vishay batata hai.
        """
        terms = self.topic_of(query)
        if not terms:
            return 0.0
        denom = max(1, min(len(terms), _FULL_MATCH_TERMS))

        title_hits = _hits(terms, s.title)
        body_hits = _hits(terms, s.snippet)

        title_ratio = min(title_hits / denom, 1.0)
        body_ratio = min(body_hits / denom, 1.0)
        score = (title_ratio * 0.6) + (body_ratio * 0.4)

        # sabse bhaari term (jo sawaal mein sabse zyada baar aaya) kahin hai?
        main = _stem(terms[0])
        if main in (s.title or "").lower():
            score += 0.12
        elif main in (s.snippet or "").lower():
            score += 0.06
        return round(min(score, 1.0), 4)

    # ── ranking + progressive selection ──────────────────────────────────────
    def rank(
        self,
        sources: List[SourceRecord],
        query: str,
        max_sources: int = 10,
        max_per_origin: int = 3,
        quality_weight: float = 0.55,
        min_quality: float = 0.30,
        min_relevance: float = 0.10,
    ) -> List[SourceRecord]:
        """
        Ranking + selection, ab RELEVANCE FLOOR ke saath.

        LIVE FAILURE (energy ka sawaal, 2026-08-19) is function ki do lines se
        aaya tha:

            good = [s for s in unique if s.quality_score >= min_quality]
            weak = [s for s in unique if s.quality_score < min_quality]
            if len(good) < max_sources:
                good.extend(weak[: max_sources - len(good)])

        Yahan relevance ka naam bhi nahi hai. Filter SIRF quality par tha, aur
        who.int (tier-2 = 0.70) aur openalex.org (tier-1 = 0.80) ke records
        quality mein aaram se pass ho jaate hain — chahe wo Gagea naam ke phool
        ki botany ho ya surgeons ki density. Upar se "kam pad gaye to weak se
        bhar do" wali line ne khaali jagah bhi kachre se bhar di. Nateeja: energy
        ke sawaal ka evidence pack poora off-topic tha, aur uske baad ka har
        step (reading, evidence, reasoning, synthesis) usi kachre par chala.

        Ab teen level hain:
          1. ZERO-OVERLAP (relevance == 0) = topic se ek shabd bhi match nahi.
             Ye HAMESHA nikal jaate hain, chahe domain kitna bhi bada ho.
             Sirf user ka apna document bacha rehta hai (usne khud diya hai).
          2. Floor se neeche (0 < relevance < min_relevance) = shak wale. Ye
             sirf tab aate hain jab acche sources kam pad jayen.
          3. Floor ke upar = asli candidates.

        Har baar ki ginti `self.last_filter` mein jaati hai, taaki report mein
        "N off-topic hate" sach-much likha ja sake — chupchaap na ho.
        """
        unique = self.dedup.deduplicate(sources)
        terms = self.topic_of(query)

        for s in unique:
            # Spec Section 7 ke text-based signals (methodology/retraction/
            # replication) yahan bharte hain — ye poore pipeline ka single
            # choke point hai, isliye source kis connector se aaya farak nahi
            # padta, treatment ek jaisa milta hai. Connector ne jo field pehle
            # se bhar di (API ka structured data), use ye chhedta nahi.
            enrich_record(s)
            s.quality_score = self.score_quality(s)
            s.relevance_score = self.score_relevance(s, query)
            s.combined_score = round(
                (s.quality_score * quality_weight)
                + (s.relevance_score * (1 - quality_weight)),
                4,
            )

        # user ke documents pehle, phir combined score
        unique.sort(
            key=lambda s: (s.source_type == SourceType.DOCUMENT, s.combined_score),
            reverse=True,
        )

        on_topic, borderline, offtopic = self._split_by_relevance(
            unique, min_relevance)

        # Low-trust sources (reddit/quora/blogs) sirf tab rakho jab better options
        # kam pad jayen — warna evidence base ganda ho jata hai.
        strong = [s for s in on_topic if s.quality_score >= min_quality]
        weak = [s for s in on_topic if s.quality_score < min_quality]

        picked = list(strong)
        for bucket in (weak, borderline):      # zaroorat par hi, isi kram mein
            if len(picked) >= max_sources:
                break
            picked.extend(bucket[: max_sources - len(picked)])

        diverse = self.dedup.cap_per_origin(picked, max_per_origin=max_per_origin)
        final = diverse[:max_sources]

        used_relevance = [s.relevance_score for s in final] or [0.0]
        self.last_filter = {
            "topic_terms": terms,
            "candidates": len(unique),
            "kept": len(final),
            "dropped_offtopic": len(offtopic),
            "borderline_used": len([s for s in final
                                    if 0 < s.relevance_score < min_relevance]),
            "min_relevance": min_relevance,
            "avg_relevance": round(sum(used_relevance) / len(used_relevance), 3),
            "max_relevance": round(max(used_relevance), 3),
            "offtopic_titles": [(s.title or s.url or "")[:80] for s in offtopic[:5]],
        }
        return final

    @staticmethod
    def _split_by_relevance(
        sources: List[SourceRecord], min_relevance: float,
    ) -> Tuple[List[SourceRecord], List[SourceRecord], List[SourceRecord]]:
        """(floor ke upar, floor se neeche par 0 se upar, bilkul off-topic)."""
        on_topic: List[SourceRecord] = []
        borderline: List[SourceRecord] = []
        offtopic: List[SourceRecord] = []
        for s in sources:
            # User ka apna uploaded document kabhi nahi hatta. Usne khud ise
            # diya hai — "ye tumhare sawaal se match nahi karta" hamara faisla
            # nahi hona chahiye.
            if s.source_type == SourceType.DOCUMENT:
                on_topic.append(s)
            elif s.relevance_score >= min_relevance:
                on_topic.append(s)
            elif s.relevance_score > 0:
                borderline.append(s)
            else:
                offtopic.append(s)
        return on_topic, borderline, offtopic

    # ── sufficiency check (Spec Section 2 — round 2/3 chahiye ya nahi) ────────
    def is_evidence_sufficient(
        self,
        sources: List[SourceRecord],
        min_independent: int = 3,
        min_avg_quality: float = 0.55,
        require_scholarly: bool = False,
    ) -> Dict:
        if not sources:
            return {"sufficient": False, "reasons": ["koi source nahi mila"]}

        reasons: List[str] = []
        independent = len({s.independence_key for s in sources})
        avg_quality = sum(s.quality_score for s in sources) / len(sources)
        scholarly = [
            s for s in sources
            if s.source_type in (SourceType.PAPER, SourceType.BOOK) or s.doi
        ]

        if independent < min_independent:
            reasons.append(f"sirf {independent} independent source(s) mile")
        if avg_quality < min_avg_quality:
            reasons.append(f"average source quality kam hai ({avg_quality:.2f})")
        if require_scholarly and not scholarly:
            reasons.append("scientific sawal hai par koi paper/book source nahi mila")

        return {
            "sufficient": not reasons,
            "reasons": reasons,
            "independent_sources": independent,
            "avg_quality": round(avg_quality, 3),
            "scholarly_sources": len(scholarly),
        }
