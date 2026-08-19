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

import re
from datetime import datetime
from typing import Dict, List, Optional

from .dedup import DeduplicationEngine
from .models import SourceRecord, SourceType
from .quality_signals import STRONG_METHODOLOGY, WEAK_METHODOLOGY, enrich_record

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
_STOP = {
    "the", "a", "an", "of", "and", "or", "in", "on", "for", "to", "with", "is",
    "are", "was", "were", "by", "from", "at", "as", "that", "this", "kya", "hai",
    "mein", "ka", "ki", "ke", "se", "aur", "kaun", "kyon", "kaise",
}


def _words(text: str) -> set:
    return {
        w for w in re.findall(r"\b\w{3,}\b", (text or "").lower())
        if w not in _STOP
    }


class RelevanceEngine:
    def __init__(self, dedup: Optional[DeduplicationEngine] = None):
        self.dedup = dedup or DeduplicationEngine()

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
        q_words = _words(query)
        if not q_words:
            return 0.0
        title_words = _words(s.title)
        body_words = _words(s.snippet)

        title_hit = len(q_words & title_words) / len(q_words)
        body_hit = len(q_words & body_words) / len(q_words)
        # title match zyada matlab rakhta hai
        score = (title_hit * 0.6) + (body_hit * 0.4)

        # phrase bonus
        q_clean = " ".join(sorted(q_words))
        if len(q_words) >= 2 and q_clean and q_clean in " ".join(sorted(title_words)):
            score += 0.05
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
    ) -> List[SourceRecord]:
        unique = self.dedup.deduplicate(sources)

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
        # Low-trust sources (reddit/quora/blogs) sirf tab rakho jab better options
        # kam pad jayen — warna evidence base ganda ho jata hai.
        good = [s for s in unique if s.quality_score >= min_quality]
        weak = [s for s in unique if s.quality_score < min_quality]
        if len(good) < max_sources:
            good.extend(weak[: max_sources - len(good)])

        diverse = self.dedup.cap_per_origin(good, max_per_origin=max_per_origin)
        return diverse[:max_sources]

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
