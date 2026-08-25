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
from typing import Dict, List, Optional, Tuple

from .dedup import DeduplicationEngine
from .models import SourceRecord, SourceType
from .quality_signals import STRONG_METHODOLOGY, WEAK_METHODOLOGY, enrich_record
from .query_builder import topic_terms
from .query_builder import is_generic_word as _is_generic_word
from . import domain as domain_mod
from . import evidence_axes as axes_mod
from . import facets as facets_mod
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


# Sawaal ka shabd aur source ka shabd ek hi cheez ke do roop hote hain:
# "hermeticism" vs "hermetic", "neuroplasticity" vs "neuroplastic",
# "investigation" vs "investigated". Substring match ek taraf chalta hai
# (chhota shabd bade text me), isliye lambe term ka SUFFIX kaat kar uski jad
# nikaali jaati hai. Jad kam se kam 6 akshar ki rakhi gayi hai taaki
# "information" se "inform" jaisa dhilaa match na bane, aur ye SIRF facet
# matching me use hoti hai — purana global lexical/semantic scoring bilkul
# waisa hi rehta hai, isliye purane benchmark hil nahi sakte.
_ROOT_SUFFIXES = ("ically", "ations", "ation", "ities", "ical", "ism", "ist",
                  "ity", "ness", "ance", "ence", "ment", "tion", "sion",
                  "ing", "ers", "er", "ed", "al", "ic")
_ROOT_MIN = 6


def _root(term: str) -> str:
    low = (term or "").lower()
    if len(low) < _ROOT_MIN + 2:
        return ""
    for suffix in _ROOT_SUFFIXES:
        if low.endswith(suffix) and len(low) - len(suffix) >= _ROOT_MIN:
            return low[: len(low) - len(suffix)]
    return ""


# ── §6 (2026-08-22): "topic ke aas-paas" vs "sawaal ko test karta hai" ──────
#
# Live dark-matter run ki jad: relevance ek hi number tha. 0.43 average par 18
# sources aaye, aur report ne unhe "evidence" maan liya — jabki unme se kai
# sirf usi field ke the, sawaal ki BAAT unme kahin nahi thi (TESS/Swift/WISE
# ke instrument papers). Ek number se ye farak nahi dikh sakta, isliye ab har
# source par das alag dimension par check hota hai aur pura record bachta hai.
#
# Har dimension teen haalat mein ho sakta hai — ye tri-state jaan-boojh kar hai:
#   True  = check chala aur mila
#   False = check chala aur NAHI mila
#   None  = check chalaya hi nahi ja sakta (jaise snippet hi nahi hai)
# "Snippet nahi tha" ko "sawaal ko test nahi karta" likhna wahi jhooth hai jise
# ye module rokta hai.
PROP_DIMENSIONS = (
    "entities", "mechanism", "observable", "population", "method",
    "required_axis", "abstract_conclusion", "title", "domain",
)
PROP_DIMENSION_WHY = {
    "entities": "sawaal ne jin cheezon ka naam liya, wo is source mein hain ya nahi",
    "mechanism": "'kaise/kyun hota hai' ki baat hai ya sirf nateeja likha hai",
    "observable": "koi naapi hui raashi (number + unit) maujood hai ya nahi",
    "population": "kis par study hui — patients/samples/galaxies/sheher",
    "method": "kaam ka tareeka (trial, cohort, simulation, survey) likha hai ya nahi",
    "required_axis": "saboot ke kis raaste par ye source kaam karta hai",
    "abstract_conclusion": "abstract/snippet mein asli nateeja likha hai ya sirf shirshak",
    "title": "shirshak khud sawaal ke topic ki baat karta hai ya nahi",
    "domain": "field ka faisla — ye source usi field ka hai jiska sawaal hai",
}

# §6 ki list mein DAS cheezein hain. Upar ke nau alag-alag naapi jaati hain;
# daswi ("whether source actually tests the requested proposition") un nau se
# banti hai par usko ek ALAG faisla ke roop mein rakha gaya hai — `tests_
# proposition`. Isliye niche wali checklist poore das naam deti hai: audit aur
# report isi se ginti karte hain, taaki "nau dekhe, das likha" jaisa farak
# kabhi na dikhe. Daswi ko dimensions ki `passed/failed` list mein NAHI mila
# rahe — wo derived hai, aur derived cheez ko naya saboot ginna do baar ginna
# hota hai.
PROP_VERDICT_CHECK = "tests_proposition"
PROP_CHECKLIST = PROP_DIMENSIONS + (PROP_VERDICT_CHECK,)
PROP_CHECK_WHY = dict(PROP_DIMENSION_WHY)
PROP_CHECK_WHY[PROP_VERDICT_CHECK] = (
    "aakhri faisla — ye source sawaal ki BAAT (proposition) sach mein test "
    "karta hai ya sirf usi topic ke aas-paas ka document hai")

# Structured reject codes — report/audit inhi codes se ginti karta hai, free-text
# se nahi (free-text har baar badal jaata hai aur count karna namumkin ho jaata).
REJECT_DOMAIN_MISMATCH = "DOMAIN_MISMATCH"
REJECT_LONE_KEYWORD = "LONE_KEYWORD"
REJECT_NO_PROPOSITION = "NO_PROPOSITION_TEST"
# §24 (2026-08-22) — dark-matter acceptance run se nikle do naye code.
REJECT_SUBJECT_MISSING = "SUBJECT_MISSING"
REJECT_NO_DATA_WEB = "NO_DATA_WEB"
REJECT_CODES = (REJECT_DOMAIN_MISMATCH, REJECT_LONE_KEYWORD,
                REJECT_NO_PROPOSITION, REJECT_SUBJECT_MISSING,
                REJECT_NO_DATA_WEB)
REJECT_CODE_WHY = {
    REJECT_DOMAIN_MISMATCH: "source kisi doosre field ka hai (domain.py ka faisla)",
    REJECT_LONE_KEYWORD: "poore sawaal me se sirf ek generic shabd match hua, "
                         "koi sub-topic nahi",
    REJECT_NO_PROPOSITION: "field to sahi hai, par ye source sawaal ki baat "
                           "test nahi karta (koi entity/nateeja/naap nahi)",
    REJECT_SUBJECT_MISSING: "field to sahi hai par sawaal ka ASLI subject is "
                            "source mein kahin nahi hai, aur ye sawaal ki baat "
                            "test bhi nahi karta",
    REJECT_NO_DATA_WEB: "non-peer-reviewed web page, koi naap/number nahi, aur "
                        "sawaal ki baat bhi test nahi karta — ye evidence nahi hai",
}

_MECHANISM_WORDS = (
    "mechanism", "because", "due to", "driven by", "caused by", "causal",
    "pathway", "explain", "explanation", "why ", "underlying", "mediat",
    "responsible for", "leads to", "gives rise", "origin of", "theoretical",
    "model predicts", "arises from",
)
_POPULATION_WORDS = (
    "patient", "participant", "subject", "cohort", "sample", "specimen",
    "respondent", "household", "firm", "student", "volunteer", "n =", "n=",
    "galaxi", "galaxy", "cluster", "star", "cities", "city", "district",
    "population", "dataset of", "survey of", "cases", "animals", "mice",
    "cell line", "wafer", "batch", "site", "region",
)
_METHOD_WORDS = (
    "randomi", "double blind", "placebo", "cohort", "case-control",
    "cross-sectional", "longitudinal", "meta-analysis", "systematic review",
    "simulation", "monte carlo", "finite element", "regression", "instrumental "
    "variable", "difference-in-differences", "ab initio", "density functional",
    "four-probe", "four probe", "spectroscopy", "diffraction", "microscopy",
    "interview", "ethnograph", "excavation", "radiocarbon", "benchmark",
    "ablation", "protocol", "methodology", "we measure", "we simulate",
    "experiment", "trial", "observation campaign", "telescope", "assay",
)
_CONCLUSION_WORDS = (
    "we find", "we show", "we report", "we observe", "we conclude", "results show",
    "results indicate", "findings", "conclusion", "conclude", "suggests",
    "suggest that", "demonstrate", "evidence for", "evidence that", "no effect",
    "null result", "significant", "not significant", "consistent with",
    "inconsistent with", "rules out", "constrain", "increase", "decrease",
    "reduction", "improvement", "correlat", "associat",
)
# Number + unit / percentage / scientific notation — "koi naap hui cheez".
_MEASURE_RE = re.compile(
    r"(?<![a-z0-9])\d+(?:[.,]\d+)?\s?"
    r"(?:%|percent|k\b|kelvin|°c|celsius|gpa|mpa|tesla|gauss|ev\b|kev|mev|gev|tev|"
    r"nm\b|µm|um\b|mm\b|cm\b|km\b|kg\b|mg\b|ml\b|litre|liter|hz\b|khz|mhz|ghz|"
    r"years?\b|months?\b|days?\b|hours?\b|kwh|mwh|gw\b|mw\b|kw\b|wh/kg|mah|"
    r"m/s|km/s|kpc|mpc|gyr|myr|msun|m_sun|sigma|σ|fold|times|x\b)",
    re.IGNORECASE)
_STAT_RE = re.compile(
    r"(p\s?[<=>]\s?0?\.\d+|95\s?%\s?ci|confidence interval|odds ratio|"
    r"hazard ratio|relative risk|r\^?2\s?=|std\.? dev|standard deviation|"
    r"\d+\s?±\s?\d+|\be\s?[-+]\s?\d+\b)", re.IGNORECASE)


def _any_in(words: Tuple[str, ...], text: str) -> List[str]:
    low = text or ""
    return [w for w in words if w in low]


class RelevanceEngine:
    def __init__(self, dedup: Optional[DeduplicationEngine] = None):
        self.dedup = dedup or DeduplicationEngine()
        # ranking ki honest report — build_pack ise pack mein copy karta hai
        self.last_filter: Dict = {}
        self._topic_cache: Dict[str, List[str]] = {}
        self._domain_cache: Dict[str, object] = {}
        # sawaal ke hisse (facets) — bounded cache, poori tarah deterministic
        self._facet_cache: Dict[str, Tuple] = {}
        # Cross-lingual scoring anchor (2026-08-23). Khaali = purana behaviour.
        self.scoring_anchor: str = ""

    # ── cross-lingual scoring anchor ─────────────────────────────────────────
    #
    # Naapa hua bug: `rank()` ko RAW user question milta hai
    # (orchestrator.py se), aur poori scoring `semantic.similarity()` →
    # `domain.tokens()` par chalti hai, yaani literal token overlap. Isliye
    # Hinglish/Hindi sawaal par perfect English paper ka score gir jaata tha —
    # naapa gaya: 'dimag tej kaise kare' par teen bilkul sahi English papers me
    # se pehle ka score 0.0 aur ek chhoot gaya, jabki English phrasing par
    # teeno 0.19–0.79 par rehte hain.
    #
    # Fix: sirf SCORING ke liye sawaal me lens/glossary se nikli English
    # vocabulary jod dete hain (`research_engine.lenses.scoring_query`).
    # Do baatein jaan-boojh kar aisi hain:
    #   1. User ka asli sawaal kabhi replace nahi hota — sirf uske saath jodte
    #      hain, taaki jo shabd usne khud likhe wo bhi count hote rahein.
    #   2. Anchor khaali ho (pure English sawaal, ya lens ne kuch na diya) to
    #      expanded query == original query, yaani ye change provably NO-OP hai.
    #      Isi wajah se purane English benchmarks hil nahi sakte.
    def set_scoring_anchor(self, anchor: str) -> None:
        clean = re.sub(r"\s+", " ", str(anchor or "")).strip()[:240]
        if clean == self.scoring_anchor:
            return
        self.scoring_anchor = clean
        self._topic_cache.clear()
        self._domain_cache.clear()
        self._facet_cache.clear()

    def expanded_query(self, query: str) -> str:
        """Scoring ke liye query + English anchor. Anchor bina = bilkul same."""
        raw = query or ""
        anchor = self.scoring_anchor
        if not anchor:
            return raw
        if not raw.strip():
            return anchor
        if anchor.casefold() in raw.casefold():
            return raw
        return f"{raw} {anchor}"

    # ── topic terms (query_builder se, ek hi jagah se) ───────────────────────
    def topic_of(self, query: str) -> List[str]:
        """
        Sawaal ka topic — search query banane wala WAHI code.

        Ek hi source-of-truth hona zaroori hai: agar hum "energy battery solar"
        dhoondein aur relevance kisi aur list se naapein, to jo mila usko "sahi
        hai" kehne ka koi aadhar nahi bachta.
        """
        query = self.expanded_query(query)
        key = (query or "")[:600]
        cached = self._topic_cache.get(key)
        if cached is None:
            cached = topic_terms(query, limit=_TOPIC_TERMS)
            if len(self._topic_cache) > 32:      # chhota bounded cache
                self._topic_cache.clear()
            self._topic_cache[key] = cached
        return cached

    # Poori content-shabd list (kaati hui nahi). Scoring ke liye top-8 hi theek
    # hai (warna 300-shabd prompt ratio ko 0 kar deta hai), par kisi source ko
    # HARD REJECT karne se pehle poora sawaal dekhna chahiye — isliye ye alag
    # method hai, alag cache ke saath.
    _WIDE_TERMS = 40

    def wide_topic_of(self, query: str) -> List[str]:
        query = self.expanded_query(query)
        key = "w:" + (query or "")[:600]
        cached = self._topic_cache.get(key)
        if cached is None:
            cached = topic_terms(query, limit=self._WIDE_TERMS)
            if len(self._topic_cache) > 64:
                self._topic_cache.clear()
            self._topic_cache[key] = cached
        return cached

    # ── §F3 facet scoring: "ek source poore sawaal ka jawab nahi hota" ────────
    #
    # Naapa hua defect (2026-08-24, intel ke 1617-token Grand-Unified sawaal):
    # `topic_of()` poore sawaal se top-8 shabd nikaalta hai, aur us sawaal ke
    # top-8 nikle — model, consciousness, reality, theories, behaviour, human,
    # life, attention. Yaani sirf DHAANCHA; ek bhi shabd aisa nahi jo kisi hisse
    # ko alag karta ho (dopamine, individuation, Nash, entropy, freemasonry,
    # remote viewing, decoherence, hedonic). Nateeja: 15 me se 11 bilkul sahi
    # sources ka relevance 0.000.
    #
    # Asli baat: aisa sawaal 15-20 alag research sawaalon ka jhund hai. Dopamine
    # ka paper poore jhund se match nahi karega — wo EK hisse ka gehra jawab
    # hai. Isliye score do tarah se naapa jaata hai aur BEHTAR wala liya jaata
    # hai: (a) poora sawaal (purana tarika, bilkul waisa hi), (b) sawaal ka
    # sabse achha match karta HISSA (facets.py, deterministic, zero Gemini).
    #
    # Inflation na ho isliye teen pehre:
    #   1. facets sirf lambe (60+ token) multi-hisse sawaal par bante hain —
    #      chhote sawaal par `facets.build()` khaali deta hai, yaani ye poora
    #      raasta provably NO-OP hai aur purane benchmarks hil nahi sakte.
    #   2. ek facet GINA hi nahi jaata jab tak uske KAM SE KAM DO ALAG shabd
    #      source me na milein (AND-of-two-signals) — aur wo do shabd "gate ke
    #      layak" hone chahiye: poora shabd mila ho (root-guess nahi) aur aam
    #      shabd na ho. Naapa gaya kyun: gearbox-vibration ka paper f15 se
    #      ['based', 'interpretation', 'vibration'] par match ho kar 0.355 pa
    #      gaya tha — jisme 'based' aam shabd hai aur 'interpretation' sirf
    #      snippet ke boilerplate ("should not be interpreted") se root-guess
    #      par mila tha. Ek hi asli shabd ('vibration') bacha, aur wo aam shabd
    #      hai jo bilkul alag field me bhi aata hai.
    #      Chhoot sirf ek jagah: agar facet ka koi STRONG shabd (sirf usi hisse
    #      ka, 11+ akshar, concept-jaisa — "hermeticism", "neuroplasticity")
    #      poora mil jaaye, to wo akela hi kaafi hai; aisa shabd ittefaq se
    #      kisi doosre field ke source me nahi aata.
    #   3. facet score par discount lagta hai — hissa poore sawaal ke barabar
    #      nahi maana jaata.
    # Aur ye lift kisi HARD REJECT ke baad nahi lagti: jo source domain gate,
    # subject gate ya no-data gate se gir gaya, wo gira hi rehta hai.
    _FACET_MIN_TERMS = 2
    _FACET_DENOM = 4
    _FACET_DISCOUNT = 0.90
    _FACET_PHRASE_BONUS = 0.10

    def facets_of(self, query: str) -> Tuple:
        key = "fc:" + (query or "")[:600]
        cached = self._facet_cache.get(key)
        if cached is None:
            cached = facets_mod.build(self.expanded_query(query))
            if len(self._facet_cache) > 16:
                self._facet_cache.clear()
            self._facet_cache[key] = cached
        return cached

    @staticmethod
    def _facet_terms_found(terms: Tuple[str, ...], text: str) -> List[str]:
        low = (text or "").lower()
        if not low:
            return []
        out: List[str] = []
        for term in terms:
            if _stem(term) in low:
                out.append(term)
                continue
            root = _root(term)
            if root and root in low:
                out.append(term)
        return out

    @staticmethod
    def _facet_exact_found(terms: Tuple[str, ...], text: str) -> List[str]:
        """Sirf wo shabd jo POORE mile — `_root()` ka andaaza nahi.

        Root-guess match ("interpretation" ← "interpreted") padhne me madad
        karta hai, par wo saboot ke layak nahi: wahi guess research snippet ke
        aam boilerplate se lag jaata hai.
        """
        low = (text or "").lower()
        if not low:
            return []
        return [t for t in terms if _stem(t) in low]

    def _facet_gate_ok(self, facet, exact_all: List[str]) -> bool:
        """Kya ye hissa is source par 'mila' kehne layak hai?"""
        solid = [t for t in exact_all
                 if not _is_generic_word(t) and not facets_mod.is_discourse_word(t)]
        if len(solid) >= self._FACET_MIN_TERMS:
            return True
        strong = set(getattr(facet, "strong", ()) or ())
        return any(t in strong for t in exact_all)

    def facet_match(self, s: SourceRecord, query: str,
                    title: str = "", body: str = "") -> Dict:
        """Sabse achha match karta hissa — {score, key, label, terms, ...}."""
        pack = self.facets_of(query)
        if not pack:
            return {}
        title = title or (s.title or "")
        body = body or (s.snippet or "")
        best: Dict = {}
        for facet in pack:
            in_title = self._facet_terms_found(facet.terms, title)
            in_body = self._facet_terms_found(facet.terms, body)
            found = {t for t in in_title} | {t for t in in_body}
            if not found:
                continue
            title_exact = self._facet_exact_found(facet.terms, title)
            exact_all = sorted(set(title_exact)
                               | set(self._facet_exact_found(facet.terms, body)))
            # Pehra 2: do alag SAAF shabd, ya title me ek STRONG shabd.
            if not self._facet_gate_ok(facet, exact_all):
                continue
            denom = max(self._FACET_MIN_TERMS,
                        min(len(facet.terms), self._FACET_DENOM))
            lexical = min(1.0, (min(len(in_title) / denom, 1.0) * 0.65)
                          + (min(len(in_body) / denom, 1.0) * 0.35))
            focus = facet.query(limit=6)
            sem = min(1.0, (semantic.similarity(focus, title) * 0.6)
                      + (semantic.similarity(focus, body) * 0.4))
            score = (lexical * 0.55) + (sem * 0.45)
            low_all = f"{title} {body}".lower()
            phrase_hit = next((p for p in facet.phrases
                               if len(p.split()) >= 2 and p.lower() in low_all), "")
            if phrase_hit:
                score = min(1.0, score + self._FACET_PHRASE_BONUS)
            score = round(min(max(score, 0.0), 1.0), 4)
            if score > best.get("score", 0.0):
                best = {"score": score, "key": facet.key, "label": facet.label,
                        "terms": sorted(found), "matched_terms": len(found),
                        "phrase": phrase_hit, "lexical": round(lexical, 4),
                        "semantic": round(sem, 4), "weight": facet.weight}
        if not best:
            return {"score": 0.0, "key": "", "label": "", "terms": [],
                    "matched_terms": 0, "facet_count": len(pack)}
        best["facet_count"] = len(pack)
        return best

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
        query = self.expanded_query(query)
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
        return " ".join(bits) if bits else (self.expanded_query(query) or "")[:200]

    def axes_of(self, query: str):
        """Sawaal ke evidence axes (cached) — §6 ka `required_axis` isse aata hai."""
        query = self.expanded_query(query)
        key = "a:" + (query or "")[:600]
        got = self._domain_cache.get(key)
        if got is None:
            got = tuple(axes_mod.axes_for(query))
            if len(self._domain_cache) > 24:
                self._domain_cache.clear()
            self._domain_cache[key] = got
        return got

    def entities_of(self, query: str) -> List[str]:
        """Sawaal ne jin cheezon ka NAAM liya (Bullet Cluster, LIGO, LK-99…)."""
        expanded = self.expanded_query(query)
        key = "e:" + (expanded or "")[:600]
        got = self._topic_cache.get(key)
        if got is None:
            named = [e.lower() for e in axes_mod.named_entities(expanded, limit=8)]
            got = named or self.topic_of(query)[:4]
            self._topic_cache[key] = got
        return got

    def proposition_check(self, s: SourceRecord, query: str,
                          verdict=None, plan=None) -> Dict:
        """
        §6 — "ye source sawaal ki BAAT test karta hai?" ka structured jawab.

        Return dict: har dimension ke against True/False/None (tri-state), plus
        `tests_proposition` (wahi tri-state) aur `why` (insaani wajah). Score
        nahi badalta — ye alag record hai, taaki "kitna match hua" aur "kya ye
        sawaal ko test karta hai" do alag sawaal alag rahein.
        """
        plan = plan if plan is not None else self.plan_of(query)
        verdict = verdict if verdict is not None else plan.assess(
            s.title or "", s.snippet or "", f"{s.venue} {s.publisher}")
        title = (s.title or "").lower()
        body = (s.snippet or "")
        low_body = body.lower()
        both = f"{title} {low_body}"
        has_body = len(body.strip()) >= 80        # itne se kam = metadata jaisa

        checks: Dict[str, Dict] = {}

        def put(name: str, ok, found=None, note: str = "") -> None:
            checks[name] = {"ok": ok, "why_checked": PROP_DIMENSION_WHY[name],
                            "found": list(found or [])[:5], "note": note}

        # 1. entities — sawaal ke naam liye hue cheezein
        ents = self.entities_of(query)
        ent_found = [e for e in ents if _stem(e) in both] if ents else []
        put("entities", (bool(ent_found) if ents else None), ent_found,
            "" if ents else "sawaal se koi naam-wali cheez nahi nikli")

        # 2-5. mechanism / observable / population / method — sirf tab jab padhne
        # ko kuch ho. Khaali snippet par "nahi mila" likhna metadata ki kami ko
        # source ki kami bana deta hai.
        if has_body:
            mech = _any_in(_MECHANISM_WORDS, both)
            put("mechanism", bool(mech), mech)
            measures = _MEASURE_RE.findall(body) or _STAT_RE.findall(body)
            put("observable", bool(measures), [str(m)[:24] for m in measures])
            pop = _any_in(_POPULATION_WORDS, both)
            put("population", bool(pop), pop)
            meth = _any_in(_METHOD_WORDS, both)
            if not meth and (s.methodology or "").strip():
                meth = [str(s.methodology)[:40]]
            put("method", bool(meth), meth)
            concl = _any_in(_CONCLUSION_WORDS, low_body)
            put("abstract_conclusion", bool(concl), concl)
        else:
            for name in ("mechanism", "observable", "population", "method",
                         "abstract_conclusion"):
                put(name, None, [], "snippet/abstract itna hi chhota tha ki "
                                    "is baare mein kuch keh nahi sakte")

        # 6. required_axis — saboot ke kis raaste par ye kaam karta hai
        axes = self.axes_of(query)
        axis_id, axis_hits = axes_mod.axis_of(s, axes) if axes else ("", 0)
        put("required_axis", (bool(axis_id) if axes else None),
            [axis_id] if axis_id else [],
            f"{axis_hits} term mile" if axis_id else
            ("kisi bhi zaroori raaste ke terms nahi mile" if axes else
             "axis list hi nahi bani"))

        # 7. title — shirshak khud topic ki baat karta hai?
        wide = self.wide_topic_of(query)
        title_hits = _hits(wide, title) if wide else 0
        put("title", (title_hits >= 2 if wide else None),
            [w for w in wide if _stem(w) in title][:5],
            f"{title_hits} shabd shirshak mein")

        # 8. domain
        if not plan.is_known:
            put("domain", None, [], "is sawaal ka koi field profile match nahi hua")
        else:
            put("domain", (not verdict.rejected and verdict.anchor_hits >= 1),
                verdict.anchor_terms[:5],
                verdict.reason or f"{verdict.anchor_hits} anchor mile")

        # ── faisla ──────────────────────────────────────────────────────────
        # Rule jaan-boojh kar KANJOOS hai: `False` sirf tab jab saaf saboot ho
        # ki source sawaal ki baat nahi kar raha. Warna `None` — kyunki galat
        # `False` ek sahi source ko chupchaap pack se bahar kar dega.
        why = ""
        if checks["domain"]["ok"] is False:
            tests = False
            why = "field hi doosra hai — sawaal ki baat yahan test nahi hoti"
        elif not has_body and title_hits <= 1:
            tests = None
            why = ("sirf metadata mila (na abstract, na shirshak mein topic) — "
                   "isliye ye faisla nahi ho saka")
        elif (checks["entities"]["ok"] is False
                and checks["required_axis"]["ok"] is False):
            tests = False
            why = ("sawaal ki naam-wali cheezein bhi nahi hain aur saboot ke kisi "
                   "zaroori raaste par bhi ye kaam nahi karta")
        elif has_body and not any(checks[d]["ok"] for d in
                                 ("observable", "abstract_conclusion", "method",
                                  "mechanism")):
            tests = False
            why = ("abstract mein na koi naap, na nateeja, na tareeka — ye "
                   "sawaal ko test karta hua document nahi lagta")
        elif (checks["entities"]["ok"] or checks["required_axis"]["ok"]) and \
                any(checks[d]["ok"] for d in ("observable", "abstract_conclusion",
                                              "method", "mechanism")):
            tests = True
            why = "sawaal ki cheez par kaam karta hai aur nateeja/naap bhi deta hai"
        else:
            tests = None
            why = "poora faisla lene ke liye kaafi jankari nahi mili"

        unknown = [d for d in PROP_DIMENSIONS if checks[d]["ok"] is None]
        return {
            "dimensions": checks,
            "passed": [d for d in PROP_DIMENSIONS if checks[d]["ok"] is True],
            "failed": [d for d in PROP_DIMENSIONS if checks[d]["ok"] is False],
            "unknown": unknown,
            "checked": [d for d in PROP_DIMENSIONS if d not in unknown],
            "axis_id": axis_id,
            "tests_proposition": tests,
            "why": why,
        }

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
            s.relevance_parts = {
                "hard_rejected": True, "reason": verdict.reason,
                "reject_code": REJECT_DOMAIN_MISMATCH,
                "reject_dimension": "domain",
                "rejections": [{"code": REJECT_DOMAIN_MISMATCH,
                                "dimension": "domain",
                                "why": REJECT_CODE_WHY[REJECT_DOMAIN_MISMATCH],
                                "detail": verdict.reason}],
                "tests_proposition": False,
                "domain": plan.key,
            }
            return 0.0
        s.rejected_reason = ""

        # ── akela shabd = koi relevance nahi (2026-08-21, cross-domain benchmark)
        #
        # Ye trap engineering domain mein pakda gaya. Sawaal tha "induction motor
        # ki bearing failure ka kaaran aur vibration monitoring", aur pack mein
        # ghus gaya: "Bearing witness: oral history interviews with retired
        # railway workers". Ek bhi cheez match nahi hoti thi — sirf shabd
        # "bearing", aur wo bhi bilkul dusre matlab mein ("bearing witness" =
        # gawahi dena, machine ka bearing nahi). Score 0.222 aaya, strict floor
        # 0.22 — 0.002 se pass ho gaya.
        #
        # Anchor ginti se ise nahi pakda ja sakta: iska anchor_hits = 1 hai, aur
        # usi field ke JAAYAZ metadata-only sources (ISO standard chapter) ka bhi
        # anchor_hits = 1 hai. Farq sirf ek jagah dikhta hai — SUB-TOPIC:
        #   ISO chapter  → branches ['diagnostics', 'standards']
        #   oral history → branches []
        # Yaani jaayaz source kisi na kisi research sub-question mein kaam aata
        # hai; ye wala kisi mein nahi.
        #
        # Rule (sirf jaane-pehchane field mein, jahan branches ka matlab hai):
        # poore sawaal ke content shabdon me se sirf EK mila, koi sub-topic nahi,
        # aur anchor bhi ek se zyada nahi → reject. Teeno shart ek saath honi
        # zaroori hain, isliye asli source (jiske 2+ shabd ya koi branch milta
        # hai) is raaste se nahi girta.
        #
        # Ginti `topic_of()` ke top-8 par NAHI hoti — `wide_topic_of()` par hoti
        # hai. Kyun: pehla attempt top-8 par tha aur usne ek jaayaz paper
        # ("Transport mode share, road capacity and travel time in dense cities")
        # ko bhi maar diya, kyunki Hinglish prompt ke top-8 mein 'badhne',
        # 'logon', 'effects' jaisi bharti aa gayi thi aur 'transport/mode/road/
        # emissions' — jinhe sawaal ne KHUD variables kaha tha — list se bahar
        # reh gaye. Reject karne jaisa bada faisla lene ke liye poori list dekhni
        # chahiye, kaati hui nahi. (Wo paper ab 8 shabd match karta hai.)
        if (plan.is_known and s.source_type != SourceType.DOCUMENT
                and verdict.branch_count == 0
                and verdict.anchor_hits <= 1):
            wide = self.wide_topic_of(query)
            if len(wide) >= 3 and _hits(wide, f"{title} {body}") <= 1:
                s.rejected_reason = (
                    "poore sawaal me se sirf ek generic shabd match hua, is field "
                    "ka koi sub-topic nahi — shabd ka matlab hi alag lag raha hai")
                s.relevance_parts = {"hard_rejected": True,
                                     "reason": s.rejected_reason,
                                     "lone_keyword": True,
                                     "reject_code": REJECT_LONE_KEYWORD,
                                     "reject_dimension": "entities",
                                     "rejections": [
                                         {"code": REJECT_LONE_KEYWORD,
                                          "dimension": "entities",
                                          "why": REJECT_CODE_WHY[REJECT_LONE_KEYWORD],
                                          "detail": s.rejected_reason}],
                                     "tests_proposition": False,
                                     "domain": plan.key}
                return 0.0

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
        # §6: score ke SAATH structured proposition-test ka record. Ye score ko
        # nahi badalta — do alag sawaal alag rehte hain: "kitna match hua" aur
        # "ye source sawaal ki baat test karta hai kya". Aage ka pipeline
        # (quality_producers.directly_relevant_ids, evidence_axes.coverage)
        # sirf saaf `False` par source ko "directly relevant" ginti se hataata
        # hai; `None` ko nahi.
        prop = self.proposition_check(s, query, verdict=verdict, plan=plan)

        # ── §24 (2026-08-22): dark-matter run se nikle do naye hard rejection ──
        #
        # Dono rule KAM SE KAM do alag signal ki AND-shart hain (rule A mein
        # teen). Ek akela signal kaafi nahi rakha gaya, kyunki reject karna ek
        # bada faisla hai — ek jaayaz source chupchaap girna, ek kachre ke
        # ghusne se zyada mehenga hai.
        def _hard_reject(code: str, dimension: str, detail: str) -> float:
            s.rejected_reason = detail
            s.relevance_parts = {
                "hard_rejected": True, "reason": detail,
                "reject_code": code, "reject_dimension": dimension,
                "rejections": [{"code": code, "dimension": dimension,
                                "why": REJECT_CODE_WHY[code],
                                "detail": detail}],
                "tests_proposition": False,
                "proposition_why": prop["why"],
                "checks": prop["dimensions"],
                "checks_failed": prop["failed"],
                "checks_unknown": prop["unknown"],
                "axis_id": prop["axis_id"],
                "domain": plan.key,
                "final": 0.0,
            }
            return 0.0

        both_low = f"{title} {body}".lower()
        subj = plan.subject_anchors() if plan.is_known else ()

        # A. SUBJECT_MISSING — "field to sahi hai, par sawaal ka subject gayab hai"
        #
        # Live run ka jaal: dark-matter ke sawaal par "TESS transit photometry of
        # a warm Neptune" aur "Photometric calibration residuals of the survey
        # CCD pipeline" pack mein aa gaye. Domain 'space' hi hai, anchor bhi mil
        # jaate hain (survey, photometry, orbit) — isliye domain gate se ye nahi
        # rukte. Farak sirf ek jagah hai: sawaal ne KHUD jo cheezein naam lekar
        # poochhi ("galaxy", "dark matter", "gravitational lensing"), unme se ek
        # bhi in papers mein nahi hai, aur proposition-test bhi saaf False hai.
        #
        # Do shart isliye: Planck ka CMB paper aur dataset ka proposition-test
        # bhi False/None hota hai, par unme subject anchor MAUJOOD hai — wo is
        # raaste se nahi girte. Aur >=2 subject anchor ki shart isliye ki jab
        # sawaal ne apni field ki vocabulary mein bahut kam bola ho, tab is rule
        # ka koi haq nahi banta.
        #
        # Teesri shart (focus branch) pehle rule ne EK JAAYAZ source maar diya
        # tha, isliye lagayi gayi: archaeology ke sawaal par "Trade contraction
        # with Mesopotamia and Harappan urban decline" aur speleothem ka monsoon
        # proxy record — dono sahi paper hain, par unme "indus valley" shabd
        # nahi hai (synonym "Harappan", ya supporting proxy evidence). Farak: us
        # sawaal se koi focus sub-topic hi nahi nikla tha, isliye ab rule wahan
        # chalta hi nahi. Dark-matter sawaal se 'cosmology' focus nikla tha aur
        # dono jaal (exoplanet, CCD calibration) usme se ek bhi branch par kaam
        # nahi karte — asli saatों sources karte hain.
        if (plan.strict and s.source_type != SourceType.DOCUMENT
                and len(subj) >= 2 and prop["tests_proposition"] is False
                and plan.focus_branches() and verdict.focus_branch_hits == 0
                and not any(_stem(t) in both_low for t in subj)):
            return _hard_reject(
                REJECT_SUBJECT_MISSING, "entities",
                "sawaal ka asli subject (%s) is source mein kahin nahi hai, aur "
                "ye sawaal ki baat test bhi nahi karta — same field hona kaafi "
                "nahi hai" % ", ".join(subj[:3]))

        # B. NO_DATA_WEB — non-peer-reviewed web page jisme ek naap bhi nahi
        #
        # Live run ka jaal: "My blog theory: dark matter is just gravity behaving
        # differently" cite ho gaya tha. Ye subject anchor test PASS kar jaata
        # hai (usme "galaxy" aur "dark matter" dono likha hai) — isliye rule A
        # se nahi rukta. Rukta hai yahan: peer-review nahi, web page hai, poore
        # title+snippet mein ek bhi naap/statistic nahi, aur proposition-test
        # False. Sarkari report, dataset ya standard page in shartein paar kar
        # leta hai kyunki usme number hote hain.
        if (s.source_type == SourceType.WEB and s.peer_reviewed is not True
                and prop["tests_proposition"] is False
                and not _MEASURE_RE.search(both_low)
                and not _STAT_RE.search(both_low)):
            return _hard_reject(
                REJECT_NO_DATA_WEB, "observable",
                "peer-review ke bina web page hai, poore title+abstract mein ek "
                "bhi naap ya statistic nahi, aur sawaal ki baat bhi test nahi "
                "karta — ye evidence nahi, raay hai")

        # ── §F3: poora sawaal vs sawaal ka ek HISSA — behtar wala liya jaata hai
        # Yahan (saare hard reject ke BAAD) jaan-boojh kar hai: gira hua source
        # facet se zinda nahi hota, sirf bacha hua source apne asli hisse ka
        # poora credit paata hai.
        facet = self.facet_match(s, query, title, body)
        facet_lift = 0.0
        if facet.get("score", 0.0) > 0.0:
            facet_lift = round(min(1.0, facet["score"] * self._FACET_DISCOUNT), 4)
            if facet_lift > score:
                score = facet_lift

        s.relevance_parts = {
            "lexical": round(lexical, 4), "semantic": round(sem, 4),
            "anchor": round(anchor, 4), "branch": round(branch, 4),
            "kind": kind or "unknown", "final": score,
            "domain": plan.key,
            "facet": (facet or None),
            "facet_lift": facet_lift,
            "tests_proposition": prop["tests_proposition"],
            "proposition_why": prop["why"],
            "checks": prop["dimensions"],
            "checks_passed": prop["passed"],
            "checks_failed": prop["failed"],
            "checks_unknown": prop["unknown"],
            "axis_id": prop["axis_id"],
            "hard_rejected": False,
            "rejections": ([{"code": REJECT_NO_PROPOSITION,
                             "dimension": (prop["failed"] or ["proposition"])[0],
                             "why": REJECT_CODE_WHY[REJECT_NO_PROPOSITION],
                             "detail": prop["why"]}]
                           if prop["tests_proposition"] is False else []),
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
        # Patent family collapse ka hisaab dedup ke ANDAR hota hai, isliye uski
        # ginti alag se yahan likhi jaati hai — warna "3 patents mile" aur
        # "1 patent bacha" ke beech ka farak report mein gayab ho jaata.
        patent_families = self.dedup.patent_family_report(sources)
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

        # 2026-08-21 (cross-domain benchmark): padding wapas kaat di gayi.
        #
        # Purana code khaali slot bharne ke liye `borderline` (yaani field ke
        # apne relevance floor se NEECHE wale) sources bhi utha leta tha, sirf
        # isliye ki `max_sources` poora ho jaaye. Medicine ke sawaal par isi
        # raaste se "Top 10 celebrity juice cleanses" (relevance 0.083, floor
        # 0.22) evidence pack mein aa gaya aur uske aage ki poori chain — reading,
        # evidence extraction, citation — uspar chali.
        #
        # Naya rule: jaane-pehchane (strict) field mein, agar ek bhi on-topic
        # source mil gaya hai to pack ko floor se neeche wale sources se BHARA
        # nahi jaata. Khaali slot chhod dena imaandaar hai; kachre se bharna
        # nahi. Haan — agar on-topic ek bhi na mile to borderline hi sahara hai
        # (warna engine andha ho jaayega), aur uski ginti `borderline_used`
        # mein saaf jaati hai.
        picked = list(strong)
        buckets: List[List[SourceRecord]] = [weak]
        if not plan.strict or not picked:
            buckets.append(borderline)
        for bucket in buckets:                 # zaroorat par hi, isi kram mein
            if len(picked) >= max_sources:
                break
            picked.extend(bucket[: max_sources - len(picked)])

        diverse = self.dedup.cap_per_origin(picked, max_per_origin=max_per_origin)
        final = diverse[:max_sources]

        used_relevance = [s.relevance_score for s in final] or [0.0]
        hard = [s for s in offtopic if s.rejected_reason]
        kept_ids = {id(s) for s in final}
        # Jo borderline pack mein nahi aaya wo "chhoda gaya" hai — usko dropped
        # ginti se bahar rakhna report ko jhootha bana deta hai.
        borderline_dropped = [s for s in borderline if id(s) not in kept_ids]
        self.last_filter = {
            "topic_terms": terms,
            "candidates": len(unique),
            # §11 ka gate poochhta hai "duplicates hataye gaye the?" — andaaza
            # lagane ke bajaye wo yahan se seedha padhta hai.
            "deduplicated": True,
            "duplicates_removed": max(0, len(sources) - len(unique)),
            # Patent-specific: ek invention ke US/EP/WO members kitne mile aur
            # kitne ek record mein sameta gaye (0/0 = pack mein patent nahi tha).
            "patent_sources_found": patent_families["patent_sources"],
            "patent_families": patent_families["families"],
            "patent_family_duplicates_removed": patent_families["collapsed"],
            "patent_family_unknown": patent_families["unknown_family"],
            "kept": len(final),
            "dropped_offtopic": len(offtopic) + len(borderline_dropped),
            "dropped_zero_overlap": len(offtopic),
            "dropped_below_floor": len(borderline_dropped),
            "borderline_used": len([s for s in final
                                    if 0 < s.relevance_score < effective_floor]),
            "min_relevance": effective_floor,
            "requested_min_relevance": min_relevance,
            "avg_relevance": round(sum(used_relevance) / len(used_relevance), 3),
            "max_relevance": round(max(used_relevance), 3),
            "offtopic_titles": [(s.title or s.url or "")[:80]
                                for s in (offtopic + borderline_dropped)[:5]],
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
            # §6 ka structured hisaab. `_prop_report` teen ginti alag rakhta hai —
            # "sawaal ko test karta hai", "nahi karta", aur "pata nahi chala" —
            # kyunki teesri ginti ko doosri mein milaana hi jhooth hai.
            "proposition": self._prop_report(final),
            "reject_codes": self._reject_codes(unique),
        }
        return final

    @staticmethod
    def _prop_report(sources: List[SourceRecord]) -> Dict:
        """Pack mein kitne sources sach mein sawaal ki baat test karte hain."""
        yes = no = unknown = 0
        dim_fail: Dict[str, int] = {}
        for s in sources:
            parts = s.relevance_parts or {}
            flag = parts.get("tests_proposition")
            if flag is True:
                yes += 1
            elif flag is False:
                no += 1
            else:
                unknown += 1
            for dim in parts.get("checks_failed") or []:
                dim_fail[dim] = dim_fail.get(dim, 0) + 1
        return {
            "dimensions": list(PROP_DIMENSIONS),
            # Poori §6 checklist (nau dimension + daswa aakhri faisla) — report
            # isi se "kitni cheezein dekhi gayi" likhti hai.
            "checklist": list(PROP_CHECKLIST),
            "checklist_why": dict(PROP_CHECK_WHY),
            "tests_proposition": yes,
            "does_not_test": no,
            "undecided": unknown,
            "failed_dimensions": dict(sorted(dim_fail.items(),
                                             key=lambda kv: -kv[1])),
            "note": f"{yes} source sawaal ki baat sach mein test karte hain; "
                    f"{no} nahi karte; {unknown} par faisla nahi ho saka "
                    f"(metadata kam tha) — ye teesri ginti 'theek hai' nahi hai.",
        }

    @staticmethod
    def _reject_codes(sources: List[SourceRecord]) -> Dict:
        """Kis code se kitne sources hate — free-text nahi, ginne layak codes."""
        out: Dict[str, int] = {code: 0 for code in REJECT_CODES}
        for s in sources:
            parts = s.relevance_parts or {}
            for row in parts.get("rejections") or []:
                code = str(row.get("code") or "")
                if code:
                    out[code] = out.get(code, 0) + 1
        return {"counts": out, "why": dict(REJECT_CODE_WHY)}

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
        min_source_quality: float = 0.30,
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

        2026-08-21 (cross-domain benchmark): usi bug ka dusra roop pakda gaya.
        Aath mein se chhe field mein round 2 ke baad hi "sufficient = True" aa
        raha tha, isliye round 3 chala hi nahi — aur round 3 mein hi contra
        (ulta) evidence, snippet-only source aur meta index aate the. Wajah:
        ginti mein ek Medium blog ("I think room temperature superconductors are
        already secret") bhi ek "independent on-topic source" ki tarah gina ja
        raha tha, jiska quality score sirf 0.20 tha. Yaani teen "kaafi" sources
        mein se ek blog tha, aur us blog ki wajah se engine ne opposition
        dhoondhna hi band kar diya.

        Isliye ab GINTI sirf credible sources ki hoti hai: `quality_score`
        `min_source_quality` (0.30 — wahi floor jo `rank()` strong/weak ke liye
        use karta hai) se upar hona chahiye. Average (quality/relevance) phir
        bhi SAARE sources par nikalta hai, kyunki wo ek imaandaar aankda hai
        aur use chhupana nahi hai.
        """
        if not sources:
            return {"sufficient": False, "reasons": ["koi source nahi mila"]}

        reasons: List[str] = []
        credible = [s for s in sources if s.quality_score >= min_source_quality]
        weak_quality = len(sources) - len(credible)
        independent = len({s.independence_key for s in credible})
        avg_quality = sum(s.quality_score for s in sources) / len(sources)
        scholarly = [
            s for s in credible
            if s.source_type in (SourceType.PAPER, SourceType.BOOK) or s.doi
        ]
        on_topic = [s for s in credible if s.relevance_score >= min_avg_relevance]
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
        if reasons and weak_quality:
            reasons.append(f"{weak_quality} source quality floor "
                           f"({min_source_quality:.2f}) se neeche the, isliye unhe "
                           f"'kaafi evidence' ki ginti mein nahi joda gaya")

        return {
            "sufficient": not reasons,
            "reasons": reasons,
            "independent_sources": independent,
            "avg_quality": round(avg_quality, 3),
            "scholarly_sources": len(scholarly),
            "on_topic_sources": len(on_topic),
            "avg_relevance": round(avg_relevance, 3),
            "weak_quality_sources": weak_quality,
        }
