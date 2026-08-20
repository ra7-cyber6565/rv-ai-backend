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
from . import domain as domain_mod
from . import semantic
from .source_kind import classify as classify_kind

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
        self._domain_cache: Dict[str, object] = {}

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
    # §5 (2026-08-20): score ab EK signal se nahi banta. Live failure mein
    # prosthetic-leg biocomposite ko 0.45 mila aur "Hunting for Room Temperature
    # Superconductors" ko 0.51 — yaani do bilkul alag cheezein lagbhag barabar.
    # Wajah: dono mein "room-temperature"/"materials" jaise shabd the, aur score
    # SIRF isi lexical overlap se banta tha.
    _W_LEXICAL = 0.25
    _W_SEMANTIC = 0.30
    _W_ANCHOR = 0.25
    _W_BRANCH = 0.20
    # Strict field (jaise superconductivity) mein floor upar uthta hai: aam
    # shabd ka match kaafi nahi.
    _STRICT_FLOOR = 0.22

    def plan_of(self, query: str):
        """Sawaal ka domain plan (cached) — §2/§3/§4 sab isi se poochte hain."""
        key = (query or "")[:600]
        plan = self._domain_cache.get(key)
        if plan is None:
            plan = domain_mod.detect(query)
            if len(self._domain_cache) > 16:
                self._domain_cache.clear()
            self._domain_cache[key] = plan
        return plan

    def focus_text(self, query: str) -> str:
        """
        Semantic comparison ke liye sawaal ka nichod. Poora 2000-char prompt
        compare karna bekaar hai (instructions, formatting, "3 hypotheses do"
        — ye source mein kabhi nahi milega).
        """
        terms = self.topic_of(query)
        plan = self.plan_of(query)
        bits = list(terms)
        for b in plan.focus_branches()[:3]:
            bits.extend(b.terms[:2])
        return " ".join(bits) if bits else (query or "")[:200]

    def score_relevance(self, s: SourceRecord, query: str) -> float:
        """
        Ye source sawaal ke topic ka hai ya nahi — 0.0 se 1.0.

        Chaar signal, phir HARD REJECTION:
          1. lexical   — top topic terms ka title/snippet overlap (purana tarika)
          2. semantic  — weighted + bigram similarity (semantic.py)
          3. anchor    — field ke anchors mile ya nahi (domain.py)
          4. branch    — kis research sub-question mein madad karta hai
        Hard rejection: strict field mein anchor 0 = 0.0, chahe lexical overlap
        kitna bhi ho. Isi ek line se banana-fibre, maternal-deaths, sunbed aur
        room-temperature-ferroelectricity sab nikal jaate hain.
        """
        terms = self.topic_of(query)
        plan = self.plan_of(query)
        title = s.title or ""
        body = s.snippet or ""

        verdict = plan.assess(title, body, f"{s.venue} {s.publisher}")
        s.domain_verdict = verdict.to_dict()

        # user ka apna document kabhi reject nahi hota — usne khud diya hai
        if verdict.rejected and s.source_type != SourceType.DOCUMENT:
            s.rejected_reason = verdict.reason
            s.relevance_parts = {"hard_rejected": True, "reason": verdict.reason}
            return 0.0
        s.rejected_reason = ""

        # 1. lexical (purana behaviour — generic sawaalon ke liye zaroori)
        lexical = 0.0
        if terms:
            denom = max(1, min(len(terms), _FULL_MATCH_TERMS))
            title_ratio = min(_hits(terms, title) / denom, 1.0)
            body_ratio = min(_hits(terms, body) / denom, 1.0)
            lexical = min(1.0, (title_ratio * 0.65) + (body_ratio * 0.35))

        # 2. semantic
        focus = self.focus_text(query)
        sem_title = semantic.similarity(focus, title)
        sem_body = semantic.similarity(focus, body)
        sem = min(1.0, (sem_title * 0.6) + (sem_body * 0.4))

        # 3. domain anchors (title mein mile to zyada bharosa)
        anchor = min(1.0, verdict.anchor_hits / 3.0)
        if verdict.title_anchor_hits:
            anchor = min(1.0, anchor + 0.20)

        # 4. sub-question coverage
        branch = min(1.0, verdict.branch_count / 2.0)
        if verdict.focus_branch_hits:
            branch = min(1.0, branch + 0.25)

        if plan.is_known:
            score = (lexical * self._W_LEXICAL + sem * self._W_SEMANTIC
                     + anchor * self._W_ANCHOR + branch * self._W_BRANCH)
        else:
            # koi field profile match nahi hua — anchor/branch ka matlab nahi,
            # isliye purane do signal par hi rahо (regression na aaye)
            score = (lexical * 0.55) + (sem * 0.45)

        # source kind ka halka asar (§5 "source type" signal)
        kind = s.doc_kind or ""
        if kind == "news_editorial":
            score *= 0.90
        elif kind == "dataset" and plan.strict and verdict.anchor_hits < 2:
            score *= 0.80
        elif kind in ("review_article", "peer_reviewed_article", "preprint"):
            score = min(1.0, score * 1.05)

        # rival field ka nishaan mila par anchor kamzor hai — shak barqaraar
        if verdict.rival_hits >= 2 and verdict.anchor_hits <= 1:
            score *= 0.75

        score = round(min(max(score, 0.0), 1.0), 4)
        s.relevance_parts = {
            "lexical": round(lexical, 4), "semantic": round(sem, 4),
            "anchor": round(anchor, 4), "branch": round(branch, 4),
            "kind": kind or "unknown", "final": score,
            "domain": plan.key,
        }
        return score

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
        plan = self.plan_of(query)

        for s in unique:
            # Spec Section 7 ke text-based signals (methodology/retraction/
            # replication) yahan bharte hain — ye poore pipeline ka single
            # choke point hai, isliye source kis connector se aaya farak nahi
            # padta, treatment ek jaisa milta hai. Connector ne jo field pehle
            # se bhar di (API ka structured data), use ye chhedta nahi.
            enrich_record(s)
            # §6: kind pehle nikaalo (relevance isko ek signal ki tarah use
            # karta hai), aur ye connector ke label ko override karta hai.
            if not s.doc_kind:
                kv = classify_kind(
                    title=s.title, snippet=s.snippet, url=s.url,
                    connector=s.connector, venue=s.venue,
                    publisher=s.publisher, doi=s.doi,
                    peer_reviewed=s.peer_reviewed,
                )
                s.doc_kind = kv.kind
                s.doc_kind_label = kv.label
                s.doc_kind_confidence = kv.confidence
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

        # §2/§5: jaane-pehchane field mein floor upar. Aam shabd ka overlap
        # (jo banana-fibre ko 0.45 dila raha tha) ab kaafi nahi hai.
        effective_floor = max(min_relevance, self._STRICT_FLOOR) if plan.strict \
            else min_relevance
        on_topic, borderline, offtopic = self._split_by_relevance(
            unique, effective_floor)

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
        hard = [s for s in offtopic if s.rejected_reason]
        self.last_filter = {
            "topic_terms": terms,
            "candidates": len(unique),
            # §11 ka gate poochhta hai "duplicates hataye gaye the?" — andaaza
            # lagane ke bajaye wo yahan se seedha padhta hai.
            "deduplicated": True,
            "duplicates_removed": max(0, len(sources) - len(unique)),
            "kept": len(final),
            "dropped_offtopic": len(offtopic),
            "borderline_used": len([s for s in final
                                    if 0 < s.relevance_score < effective_floor]),
            "min_relevance": effective_floor,
            "requested_min_relevance": min_relevance,
            "avg_relevance": round(sum(used_relevance) / len(used_relevance), 3),
            "max_relevance": round(max(used_relevance), 3),
            "offtopic_titles": [(s.title or s.url or "")[:80] for s in offtopic[:5]],
            # §2/§3/§5 ka honest hisaab: kis field ka sawaal mana gaya, aur
            # kaun-kaun HARD REJECT hua aur kyun.
            "domain": plan.key,
            "domain_label": plan.profile.label,
            "domain_strict": plan.strict,
            "sub_domains": [b.key for b in plan.focus_branches()],
            "hard_rejected": len(hard),
            "hard_rejected_examples": [
                {"title": (s.title or s.url or "")[:70], "why": s.rejected_reason[:120]}
                for s in hard[:5]
            ],
            "branch_coverage": sorted({
                b for s in final for b in (s.domain_verdict.get("branches") or [])
            }),
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
        min_on_topic: int = 3,
        min_avg_relevance: float = 0.30,
    ) -> Dict:
        """
        §15 ka asli root cause yahi function tha.

        Pehle ye SIRF ginti dekhta tha: independent origins, average quality,
        aur "koi paper mila ya nahi". Superconductivity run mein 14 off-topic
        sources mile the — par wo sab tier-1/tier-2 domains (openalex, who.int,
        zenodo) se the, isliye avg_quality 0.55 se upar tha aur independent >= 3
        tha. Nateeja: "sufficient = True", aur orchestrator ne MAXIMUM ke 3
        rounds mein se round 1 ke baad hi break kar diya. Reasoning model ka
        isse koi lena-dena nahi tha.

        Ab sufficiency mein RELEVANCE bhi shaamil hai: kitne sources sach mein
        topic ke hain, aur unka average relevance kya hai. Off-topic dher se
        research "poori" nahi hoti.
        """
        if not sources:
            return {"sufficient": False, "reasons": ["koi source nahi mila"]}

        reasons: List[str] = []
        independent = len({s.independence_key for s in sources})
        avg_quality = sum(s.quality_score for s in sources) / len(sources)
        scholarly = [
            s for s in sources
            if s.source_type in (SourceType.PAPER, SourceType.BOOK) or s.doi
        ]
        on_topic = [s for s in sources if s.relevance_score >= min_avg_relevance]
        avg_relevance = sum(s.relevance_score for s in sources) / len(sources)

        if independent < min_independent:
            reasons.append(f"sirf {independent} independent source(s) mile")
        if avg_quality < min_avg_quality:
            reasons.append(f"average source quality kam hai ({avg_quality:.2f})")
        if require_scholarly and not scholarly:
            reasons.append("scientific sawal hai par koi paper/book source nahi mila")
        if len(on_topic) < min_on_topic:
            reasons.append(f"sirf {len(on_topic)} source topic ke bilkul upar hain "
                           f"(chahiye {min_on_topic}) — ek aur round karna behtar hai")
        if avg_relevance < min_avg_relevance:
            reasons.append(f"average topic match kam hai ({avg_relevance:.2f})")

        return {
            "sufficient": not reasons,
            "reasons": reasons,
            "independent_sources": independent,
            "avg_quality": round(avg_quality, 3),
            "scholarly_sources": len(scholarly),
            "on_topic_sources": len(on_topic),
            "avg_relevance": round(avg_relevance, 3),
        }
