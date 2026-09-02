"""
HypothesisEngine — Spec Section 10 (New Hypothesis Generation)

Sabse important rule (spec se): "AI ki generated hypothesis ko established fact
kabhi mat banana." Isliye:

    * har hypothesis ka status HARDCODED hai: "UNTESTED HYPOTHESIS"
    * har hypothesis ke saath test-design maanga jaata hai
    * confidence ko "evidence-backed" nahi, "reasoning-based" likha jaata hai

Hypothesis tab hi generate hoti hai jab sawal genuinely unresolved/creative ho
ya evidence contradictory ho — har chhote sawal pe hypothesis banana bekaar hai.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, List, Optional, Sequence
import re as _re_module  # avoid conflict with module-level _FIELD_RE

from .models import (EvidencePack, NOVELTY_DUPLICATE, NOVELTY_KNOWN,
                     NOVELTY_KNOWN_VARIANT, NOVELTY_MINOR, NOVELTY_POSSIBLE,
                     NOVELTY_STATES, NOVELTY_UNVERIFIED)

STATUS = "UNTESTED HYPOTHESIS"

# Provider exact template follow kare to `## Hypothesis 1` aata hai, lekin
# kabhi `## H1`, `### Hypothesis #2`, ya `## 3. Hypothesis` bhi aa jaata hai.
# In headings ko ek block maan kar parse karo; prose ke andar likhe shabd par
# split nahi hota kyunki markdown heading marker zaroori hai.
_H_HEADING = (
    r"(?:hypothesis(?:\s*#?\s*\d+)?|h\s*#?\s*\d+|"
    r"\d+\s*[\).:\-]?\s*hypothesis)"
)
_H_SPLIT_RE = re.compile(
    r"^\s*#{1,6}\s*" + _H_HEADING + r"\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
# NOTE: `simple explanation`, `assumptions`, `if true`, `if false` baad mein
# add hue (2026-08-20) — intel ka rule: hypothesis ko aise samjhao jaise samne
# baithe bande ne ye concept pehle kabhi suna hi nahi. Sirf ek-line statement
# dena kaafi nahi hai.
# NOTE 2: `counter-evidence`, `required experiment|simulation` aur
# `falsification test` 2026-08-21 ko add hue (point 11). Wajah: spec har
# hypothesis se CHHE cheezein maangta hai — support, counter-evidence,
# assumptions, falsification test, required experiment/simulation, confidence.
# Pehle experiment aur falsification dono `how to test` ke andar chhipe the,
# isliye report ye alag-alag naap hi nahi sakti thi ki kya missing hai.
# ORDER MATTERS: lamba naam pehle likho ("falsification test" se pehle
# "falsification" likh do to label kabhi match nahi karega).
# Jaan-boojh kar BARE "falsification" label NAHI hai: model "Prediction:" ke
# neeche continuation line mein "Falsification: reject if ..." likhta hai, aur
# use alag field bana dene se prediction ka block toot jaata (aur uska
# falsification_condition gum ho jaata). Wo line prediction ke andar hi rehni
# chahiye — `Hypothesis.falsification_test` wahan se bhi utha leti hai.
_FIELD_NAMES = (
    r"statement|simple explanation|simple|reasoning|supporting evidence|against|"
    r"contradicting evidence|counter[\s\-]?evidence|evidence against|"
    r"mechanism|knowledge gap|gap|"
    r"novelty|assumptions?|prediction|"
    r"required experiment|required simulation|experimental plan|experiment|"
    r"simulation|"
    r"falsification test|how to falsify|"
    r"how to test|test|"
    r"if true|if false|risks|confidence")
_FIELD_RE = re.compile(
    r"^\s*(?:[-*]\s*)?\**\s*(" + _FIELD_NAMES + r")"
    r"\s*\**\s*[:\-]\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)

# `_FIELD_RE` sirf EK line uthata hai (`.` newline match nahi karta). Gemini
# aksar multi-line likhta hai — "Reasoning:" ke neeche step-by-step chain, aur
# "Prediction:" ke neeche "Variables: / Expected outcome: / Measurement:" wali
# labelled lines. Purana parser un continuation lines ko chup-chaap phenk deta
# tha, isliye structured prediction kabhi complete nahi banti thi aur reasoning
# chain ki pehli line ke baad sab gum ho jaata tha.
# Isliye ab line-by-line scan hota hai: label mile to naya field shuru, warna
# line pichhle field ke saath jud jaati hai (agli label ya `##` heading tak).
_FIELD_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?\**\s*(" + _FIELD_NAMES + r")"
    r"\s*\**\s*[:\-]\s*(.*)$",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s")
_MAX_FIELD_CHARS = 4000   # runaway continuation se bachne ke liye

# "ye result ise galat sabit kar dega" wali baat pehchanne ke liye. Sirf keyword
# hai — koi model nahi, isliye ₹0 aur deterministic.
_FALSIFY_HINT_RE = re.compile(
    r"falsif|disprove|reject if|refute|null result|no change|no effect|"
    r"galat sabit|galat hogi|khaarij", re.IGNORECASE)

# ── point 11: evidence-sufficiency gate ──────────────────────────────────────
# Kyun: "kam se kam 3 testable hypotheses" ka matlab "har haalat mein 3" nahi
# hai. Do source aur wo bhi sirf snippet — us par 3 hypotheses likhna sirf
# tukka hai, aur tukke ko research kehna is project ka sabse bada mana kaam
# hai. Isliye pehle naapte hain ki evidence kitni hypotheses ka bojh utha
# sakta hai, aur jitna utha sakta hai utna hi maangte hain — baaki ke liye
# wajah likhte hain.
#
# Saare number yahan ek jagah, taaki report inhe naam le kar bata sake.
_GATE_MIN_RELEVANCE = 0.25   # relevance floor (relevance.py ka wahi floor)
_GATE_FULL_TARGET = 3        # 3+ hypotheses ke liye itne relevant source chahiye
_GATE_DEEP_TARGET = 2        # ...aur itne kam se kam abstract-level padhe hue


# ═══════════════════════════════════════════════════════════════════════════
# §13-§18 — app ki apni hypothesis ka POORA record
# ═══════════════════════════════════════════════════════════════════════════
#
# Pichhli dark-matter report ki sabse badi galti yahi thi: app ne PBH, MOND,
# dark photon aur "modeling systematics" ko apni nayi soch ki tarah pesh kar
# diya, aur uske saath 90-95% jaisa number bhi lag gaya. Dono baatein galat
# hain — wo ideas decades purane hain, aur kisi bhi hypothesis ko number-wale
# probability dena bina calculation ke jhooth hai.
#
# Isliye ab har hypothesis ke saath ye cheezein deterministic tareeke se
# banti hain (koi LLM nahi, ₹0):
#   * stable ID (RV-HYP-YYYY-NNN) — same statement, same ID
#   * provenance: kaun se facts use hue aur kaunsa GAP bharne ki koshish hai
#   * source_claim_disclaimer: "ye kisi source ka claim nahi hai" (English)
#   * closest_prior_work: mile hue sources me se sabse milta-julta kaam
#   * novelty_search + novelty_status: sirf whitelist ke chhe labels
#   * confidence: BAND (Very Low/Low/Moderate/High) + reason codes, number nahi
#   * validation_status: aage kya-kya hona baaki hai

# §13 — ye line hypothesis ke saath HAMESHA jaati hai (English, jaan-boojh kar:
# ye legal/epistemic disclaimer hai, translation me matlab patla pad jaata hai).
SOURCE_CLAIM_DISCLAIMER = (
    "This hypothesis was generated by this app from the retrieved evidence. "
    "No cited source states this hypothesis. It is untested and must not be "
    "treated as a finding, a discovery, or established science."
)

# §18 — confidence sirf in chaar BANDS me. Number (jaise "92%") banana mana hai:
# uske peeche koi calculation nahi hoti, wo sirf bharosa jagane ka trick hai.
CONF_VERY_LOW = "VERY LOW"
CONF_LOW = "LOW"
CONF_MODERATE = "MODERATE"
CONF_HIGH = "HIGH"
CONFIDENCE_BANDS = (CONF_VERY_LOW, CONF_LOW, CONF_MODERATE, CONF_HIGH)

# Reason codes — band ke saath WAJAH bhi machine-readable ho, taaki audit
# check kar sake ki band kis base par bana.
CONF_REASON_CODES = {
    "NO_DIRECT_SOURCE": "kisi source ne is baat ko seedha test nahi kiya",
    "THIN_EVIDENCE": "evidence patla hai (relevant/deep source kam hain)",
    "SHALLOW_ACCESS": "sources ka poora text nahi padha ja saka",
    "NO_COUNTER_SEARCH": "iske khilaf ki side alag se search nahi hui",
    "NO_CALCULATION": "koi calculation/quantitative check nahi hua",
    "NO_PREDICTION": "measurable prediction nahi di gayi",
    "NO_FALSIFICATION": "falsification test nahi diya gaya",
    "UNTESTED": "ye hypothesis kabhi lab/field me test nahi hui",
    "KNOWN_IDEA": "idea pehle se literature me maujood hai",
    "MULTI_SOURCE_BASE": "ek se zyada relevant source ka base hai",
    "CONTRADICTION_DRIVEN": "evidence me asli takraav hai, isliye ye zaroori bhi hai",
    "MECHANISM_GIVEN": "kaam karne ka mechanism likha gaya hai",
}

# §18 — "validation" ka matlab checklist hai, tick mark nahi.
VALIDATION_NOT_STARTED = "NOT VALIDATED — NO TEST RUN"
VALIDATION_PLAN_ONLY = "TEST PLAN ONLY — NOT EXECUTED"
VALIDATION_NEEDS_PLAN = "NOT VALIDATED — NO USABLE TEST PLAN"
VALIDATION_STATES = (VALIDATION_NOT_STARTED, VALIDATION_PLAN_ONLY,
                     VALIDATION_NEEDS_PLAN)

# §14 — ye ideas KNOWN hain. In par hypothesis banana bura nahi hai; inhe "app
# ki nayi khoj" batana bura hai. List me sirf wahi cheezein hain jo pichhli live
# report me galti se "possibly novel" bani thi, plus unke aas-paas ke standard
# alternatives.
KNOWN_IDEA_PATTERNS = {
    "primordial black hole": "primordial black holes (PBH) — 1970s se dark matter candidate",
    "pbh": "PBH (primordial black holes) — literature me decades purana candidate",
    "mond": "MOND (modified Newtonian dynamics) — Milgrom 1983",
    "modified newtonian": "modified Newtonian dynamics (MOND) — Milgrom 1983",
    "modified gravity": "modified gravity — dark matter ka purana alternative program",
    "f(r) gravity": "f(R) gravity — established modified-gravity family",
    "emergent gravity": "emergent/entropic gravity — Verlinde et al.",
    "entropic gravity": "entropic gravity — established proposal",
    "dark photon": "dark photon / hidden photon — standard dark-sector candidate",
    "hidden photon": "hidden photon — standard dark-sector candidate",
    "fifth force": "fifth force — decades purani search",
    "axion": "axions — mainstream dark matter candidate",
    "sterile neutrino": "sterile neutrino — mainstream candidate",
    "self-interacting dark matter": "self-interacting dark matter (SIDM) — established model",
    "warm dark matter": "warm dark matter — established model",
    "fuzzy dark matter": "fuzzy/ultralight dark matter — established model",
    "wimp": "WIMPs — mainstream candidate",
    "macho": "MACHOs — purana candidate",
    "systematic error": "measurement/modeling systematics — routine explanation, nayi soch nahi",
    "modeling systematic": "modeling systematics — routine explanation",
    "modelling systematic": "modelling systematics — routine explanation",
    "baryonic feedback": "baryonic feedback — standard astrophysical explanation",
}

# §14 — ye shabd kabhi output me nahi jaane chahiye. App discovery nahi karti;
# app hypothesis banati hai jinhe koi aur test karega.
FORBIDDEN_NOVELTY_PHRASES = (
    "100% new", "100 % new", "completely new to science", "duniya mein pehli",
    "duniya me pehli", "world first", "world's first", "first in the world",
    "scientific discovery", "we discovered", "humne khoj", "khoj kar li",
    "nayi khoj hai", "breakthrough discovery", "proven novel", "definitely novel",
)

# #114 — inkaar pakadne ke chhote auzaar. Window chhoti aur punctuation par
# rukne wali hai, taaki "nahi" doosre vaakya se udhaar na liya ja sake.
_NOVELTY_LEFT = 48
_NOVELTY_RIGHT = 36
_NOVELTY_BOUNDARY = re.compile("[.,;:!?|()\n—–\"]")
_NOVELTY_NEGATORS = re.compile(
    r"\bnot\b|\bno\b|\bnever\b|n't\b|\bcannot\b|\bcan not\b|\bwithout\b|"
    r"\bnahin?\b|\bnhi\b|\bmat\b|\bbina\b|\binkaar\b", re.IGNORECASE)
_NOVELTY_FALSE_DENIAL = (
    "no doubt", "not only", "not just", "no question", "without doubt",
    "without question", "shak nahi", "sandeh nahi", "doubt nahi",
)

# Prior-art similarity thresholds (deterministic, token-overlap based).
_PRIOR_DUP = 0.80      # itna match = wahi kaam pehle se hai
_PRIOR_CLOSE = 0.55    # itna match = chhota-sa fark, minor modification
_PRIOR_NEAR = 0.35     # itna match = variant of a known line of work

_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "have", "has", "are",
    "was", "were", "will", "would", "could", "should", "than", "then", "into",
    "such", "more", "most", "less", "very", "also", "been", "being", "their",
    "there", "these", "those", "when", "which", "while", "where", "what",
    "hypothesis", "hypotheses", "study", "studies", "paper", "papers", "result",
    "results", "data", "using", "used", "based", "shows", "show", "showed",
    "suggest", "suggests", "may", "can", "not", "but", "our", "new", "novel",
    "effect", "effects", "analysis", "approach", "model", "models",
}


def _tokens(text: str) -> set:
    """Content words (4+ akshar, stopword nahi). Koi library nahi — ₹0."""
    words = re.findall(r"[a-z][a-z0-9\-]{3,}", (text or "").lower())
    return {w for w in words if w not in _STOP}


def _overlap(a: set, b: set) -> float:
    """`a` ke kitne hisse `b` me bhi hain (0..1). Asymmetric — jaan-boojh kar:
    hum poochh rahe hain "hypothesis ki baat pehle se kahin likhi hai kya",
    ulta nahi."""
    if not a:
        return 0.0
    return round(len(a & b) / float(len(a)), 3)


def hypothesis_id(statement: str, index: int = 0,
                  year: Optional[int] = None) -> str:
    """
    Stable ID: `RV-HYP-2026-041`.

    Statement se hash banta hai, run ke order se NAHI. Kyun: pichhli baar ID
    "Hypothesis 1/2/3" thi, aur dobara run karne par wahi soch alag number le
    leti thi — us se koi bhi hypothesis time ke saath track nahi ho sakti thi.
    """
    norm = " ".join(re.sub(r"[^a-z0-9 ]", " ", (statement or "").lower()).split())
    if not norm:
        norm = f"unnamed-{int(index)}"
    digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()
    number = (int(digest[:8], 16) % 999) + 1
    y = int(year or date.today().year)
    return f"RV-HYP-{y}-{number:03d}"


def known_idea_hits(*texts: str) -> List[Dict]:
    """
    Statement/mechanism me maujood JAANE-PEHCHANE ideas.

    Ye "hypothesis galat hai" nahi kehta — sirf itna kehta hai ki ise "app ki
    nayi soch" batana galat hoga.
    """
    blob = " ".join((t or "") for t in texts).lower()
    blob = re.sub(r"[\s\-]+", " ", blob)
    hits: List[Dict] = []
    seen = set()
    for pattern, why in KNOWN_IDEA_PATTERNS.items():
        needle = re.sub(r"[\s\-]+", " ", pattern)
        if needle in blob and why not in seen:
            seen.add(why)
            hits.append({"idea": pattern, "why_known": why})
    return hits


def _novelty_negator_in(window: str) -> bool:
    """Is chhoti window me asli inkaar hai ya nahi (#114)."""
    clean = window
    # "no doubt" / "shak nahi" me negator hai par wo daawe ko nahi kaatta —
    # ulta pakka karta hai. Aise span ko pehle hata dete hain, warna
    # "Isme koi shak nahi, ye 100% new hai" cleared ho jaata (guard kamzor).
    for phrase in _NOVELTY_FALSE_DENIAL:
        if phrase in clean:
            clean = clean.replace(phrase, " " * len(phrase))
    return bool(_NOVELTY_NEGATORS.search(clean))


def _novelty_negated(low: str, start: int, end: int) -> bool:
    """
    Ek occurrence ke aas-paas inkaar likha hai kya.

    Window jaan-boojh kar chhoti hai aur punctuation par ruk jaati hai: isse
    "Ye purana nahi hai, ye 100% new hai." me comma ke us paar ka `nahi`
    phrase ko bacha nahi paata — yaani jhooth phir bhi pakda jaata hai.
    """
    left = low[max(0, start - _NOVELTY_LEFT):start]
    ends = [m.end() for m in _NOVELTY_BOUNDARY.finditer(left)]
    if ends:
        left = left[ends[-1]:]
    right = low[end:end + _NOVELTY_RIGHT]
    stop = _NOVELTY_BOUNDARY.search(right)
    if stop:
        right = right[:stop.start()]
    return _novelty_negator_in(left) or _novelty_negator_in(right)


def forbidden_novelty_phrases(*texts: str) -> List[str]:
    """
    Jo shabd kabhi nahi likhne chahiye — mile to naam le kar lautao.

    #114 — pehle ye seedha substring check tha, isliye imaandaar INKAAR bhi
    "banned" gina jaata tha ("Ye idea 100% new nahi hai", "This is not 100%
    new"). Ab har occurrence ke aas-paas ki chhoti window dekhi jaati hai:
    phrase saaf hota hai sirf tab jab uski HAR jagah inkaar ke saath ho. Ek
    jagah bina inkaar mila to phrase banned hi rehta hai (guard dheela nahi
    hua). Aur agar phrase sirf do field jodne se bana hai, to bharosa nahi —
    wo bina shart banned hai.
    """
    fields = [(t or "").lower() for t in texts]
    blob = " ".join(fields)
    out: List[str] = []
    for phrase in FORBIDDEN_NOVELTY_PHRASES:
        if phrase not in blob:
            continue
        in_field = False
        all_denied = True
        for low in fields:
            at = low.find(phrase)
            while at != -1:
                in_field = True
                if not _novelty_negated(low, at, at + len(phrase)):
                    all_denied = False
                at = low.find(phrase, at + 1)
        if not in_field or not all_denied:
            out.append(phrase)
    return out


def closest_prior_work(statement: str, sources: Optional[Sequence] = None,
                       mechanism: str = "", limit: int = 3) -> List[Dict]:
    """
    §15 — mile hue kaam me se sabse milta-julta kaam, `same`/`difference` ke saath.

    Ye "prior art search" ka poora badal NAHI hai (isliye novelty_status alag se
    handle hota hai) — ye sirf imaandaari se batata hai ki jo sources humare paas
    HAIN, unme se koi ye baat pehle se keh raha hai ya nahi. Khaali list ka
    matlab "kuch match nahi mila" hai, "koi prior work nahi hai" nahi.
    """
    hyp_tokens = _tokens(f"{statement} {mechanism}")
    out: List[Dict] = []
    for s in list(sources or []):
        text = " ".join(str(getattr(s, attr, "") or "")
                        for attr in ("title", "snippet", "venue"))
        src_tokens = _tokens(text)
        if not src_tokens:
            continue
        sim = _overlap(hyp_tokens, src_tokens)
        if sim <= 0.0:
            continue
        shared = sorted(hyp_tokens & src_tokens)[:8]
        extra = sorted(hyp_tokens - src_tokens)[:8]
        out.append({
            "source_id": str(getattr(s, "source_id", "") or ""),
            "title": str(getattr(s, "title", "") or "")[:200],
            "similarity": sim,
            "same": ("dono me common: " + ", ".join(shared)) if shared else "",
            "difference": (("is hypothesis me extra: " + ", ".join(extra))
                           if extra else "koi saaf fark nahi dikha"),
        })
    out.sort(key=lambda d: -float(d["similarity"]))
    return out[:max(1, int(limit))]


def novelty_queries(statement: str, mechanism: str = "",
                    question: str = "") -> List[str]:
    """
    §15 — prior-art check ke liye 5 ALAG-ALAG query (exact, mechanism, synonym,
    negative/review, aur sawaal ke context wali). Deterministic: same statement
    par same queries, taaki audit inhe verify kar sake.
    """
    stem = " ".join((statement or "").split())[:180]
    terms = sorted(_tokens(statement))[:6]
    core = " ".join(terms[:4]) or stem[:60]
    mech = " ".join(sorted(_tokens(mechanism))[:4])
    qterms = " ".join(sorted(_tokens(question))[:3])
    queries = [
        stem,
        f"{core} mechanism" + (f" {mech}" if mech else ""),
        f"{core} hypothesis proposed",
        f"{core} review OR criticism OR ruled out",
        (f"{qterms} {core}").strip(),
    ]
    seen, unique = set(), []
    for q in queries:
        q = " ".join(str(q).split())
        if len(q) >= 8 and q.lower() not in seen:
            seen.add(q.lower())
            unique.append(q)
    while len(unique) < 5 and stem:
        unique.append(f"{stem} evidence {len(unique)}")
    return unique[:5]


def novelty_assessment(statement: str, mechanism: str = "",
                       prior: Optional[List[Dict]] = None,
                       prior_art_searched: Optional[bool] = None,
                       databases: Optional[Sequence[str]] = None,
                       queries: Optional[Sequence[str]] = None,
                       question: str = "") -> Dict:
    """
    §14 — novelty ka faisla, sirf whitelist ke chhe labels me.

    Sabse zaroori do rules:
      1. Jaana-pehchana idea (PBH, MOND, dark photon, fifth force, modeling
         systematics...) kabhi "possibly novel" nahi banta.
      2. "POSSIBLY NOVEL" sirf tab jab prior-art search SACH ME chali ho. Search
         hi nahi chali to jawab "NOVELTY UNVERIFIED" hai — "novel" nahi.
    """
    prior = list(prior or [])
    known = known_idea_hits(statement, mechanism)
    top = prior[0] if prior else None
    top_sim = float(top["similarity"]) if top else 0.0
    searched = bool(prior_art_searched) if prior_art_searched is not None else False
    close_match = (None if prior_art_searched is None
                   else bool(top_sim >= _PRIOR_CLOSE))

    if top_sim >= _PRIOR_DUP:
        status = NOVELTY_DUPLICATE
        why = (f"{top['source_id'] or 'ek source'} me lagbhag yahi baat pehle se "
               f"hai (match {top_sim}).")
    elif known:
        # Quantitative/mechanistic twist ho to "variant", warna seedha KNOWN.
        has_twist = bool(re.search(r"\d", statement or "")) or len(
            (mechanism or "").strip()) >= 40
        status = NOVELTY_KNOWN_VARIANT if has_twist else NOVELTY_KNOWN
        why = ("Ye pehle se maujood idea par bani hai: "
               + "; ".join(h["why_known"] for h in known[:2])
               + (". Isme ek specific twist hai, par idea nayi nahi hai."
                  if has_twist else ". Ise app ki nayi soch batana galat hoga."))
    elif top_sim >= _PRIOR_CLOSE:
        status = NOVELTY_MINOR
        why = (f"{top['source_id'] or 'ek source'} ke kaam se bahut milti hai "
               f"(match {top_sim}) — sirf chhota fark hai.")
    elif top_sim >= _PRIOR_NEAR:
        status = NOVELTY_KNOWN_VARIANT
        why = (f"{top['source_id'] or 'ek source'} wali line of work ka variant "
               f"lagta hai (match {top_sim}).")
    elif searched:
        status = NOVELTY_POSSIBLE
        why = ("Jo databases aur queries chalayi gayi unme close match nahi mila. "
               "Iska matlab 'duniya me pehli baar' NAHI hai — sirf itna ki humari "
               "search me nahi mila.")
    else:
        status = NOVELTY_UNVERIFIED
        why = ("Prior-art search alag se nahi chali, isliye novelty ka faisla "
               "nahi kiya ja sakta. 'Nayi hai' likhna yahan jhooth hota.")

    if status not in NOVELTY_STATES:
        # Defensive: whitelist se bahar ka shabd kabhi user tak nahi jaana chahiye.
        status = NOVELTY_UNVERIFIED
    return {
        "novelty_status": status,
        "why": why,
        "known_idea_hits": known,
        "novelty_search": {
            "performed": prior_art_searched,     # None = chali hi nahi (pata nahi)
            "queries": list(queries or novelty_queries(statement, mechanism, question)),
            "databases": list(databases or []),
            "close_match_found": close_match,
            "closest_similarity": top_sim if prior else None,
        },
        "closest_prior_work": prior,
    }


@dataclass
class EvidenceGate:
    """
    Kitni hypotheses banane layak evidence hai — aur kyun (insaani wajah).

    `allowed` upper limit hai, target nahi: agar user ne 2 maangi aur evidence 5
    ka bojh utha sakta hai, to 2 hi banengi.
    """
    requested: int = 0
    allowed: int = 0
    sufficient: bool = False       # True = 3+ hypotheses ka evidence hai
    relevant_sources: int = 0
    deep_sources: int = 0          # abstract ya full_text tak padhe hue
    full_text_sources: int = 0
    contradictions: int = 0
    total_sources: int = 0
    reason: str = ""

    @property
    def target(self) -> int:
        """Asal mein kitni maangni chahiye (request aur evidence, dono ka lihaaz)."""
        if self.allowed <= 0:
            return 0
        return min(max(1, self.requested or 1), self.allowed)

    @property
    def short_of_request(self) -> bool:
        return bool(self.requested) and self.allowed < self.requested

    def to_dict(self) -> Dict:
        return {
            "requested": self.requested,
            "allowed": self.allowed,
            "target": self.target,
            "sufficient": self.sufficient,
            "relevant_sources": self.relevant_sources,
            "deep_sources": self.deep_sources,
            "full_text_sources": self.full_text_sources,
            "contradictions": self.contradictions,
            "total_sources": self.total_sources,
            "reason": self.reason,
            "short_of_request": self.short_of_request,
        }


def evidence_gate(pack: Optional[EvidencePack], requested: int = 0,
                  contradictions: Optional[List[Dict]] = None) -> EvidenceGate:
    """
    Evidence naapo aur batao ki kitni hypotheses banana imaandaar hai.

    Rule (deterministic, report mein bhi yahi likha jaata hai):
      * relevant source = relevance floor (0.25) paar, reject nahi hua, aur
        retraction ka nishaan nahi
      * deep source = wahi relevant source jise kam se kam abstract level tak
        padha gaya
      * 3+ hypotheses = 3 relevant + 2 deep source (ya evidence mein asli
        takraav ho to 2 relevant + 1 deep — kyunki takraav hi wo jagah hai
        jahan nayi hypothesis ki sabse zyada zaroorat hoti hai)
      * 1 relevant source = sirf 1 hypothesis
      * 0 relevant source = 0 hypothesis (aur wajah saaf likhi jaati hai)
    """
    gate = EvidenceGate(requested=max(0, int(requested or 0)),
                        contradictions=len(contradictions or []))
    sources = list(getattr(pack, "sources", []) or []) if pack is not None else []
    gate.total_sources = len(sources)

    usable = [s for s in sources
              if float(getattr(s, "relevance_score", 0.0) or 0.0) >= _GATE_MIN_RELEVANCE
              and not str(getattr(s, "rejected_reason", "") or "").strip()
              and getattr(s, "retracted", None) is not True]
    gate.relevant_sources = len(usable)
    levels = [(s.reading_level() if hasattr(s, "reading_level") else "") for s in usable]
    gate.deep_sources = len([lvl for lvl in levels if lvl in ("abstract", "full_text")])
    gate.full_text_sources = len([lvl for lvl in levels if lvl == "full_text"])

    if not sources:
        gate.reason = ("ek bhi source retrieve nahi hua, isliye hypothesis banana "
                       "sirf andaza hota — nahi banayi.")
        return gate
    if not usable:
        gate.reason = (f"{len(sources)} source mile par ek bhi sawaal se juda "
                       f"(relevance {_GATE_MIN_RELEVANCE}+) nahi nikla, isliye "
                       f"hypothesis ka koi asli base nahi hai.")
        return gate

    strong = (gate.relevant_sources >= _GATE_FULL_TARGET
              and gate.deep_sources >= _GATE_DEEP_TARGET)
    conflict_route = (gate.contradictions > 0 and gate.relevant_sources >= 2
                      and gate.deep_sources >= 1)

    if strong or conflict_route:
        gate.sufficient = True
        gate.allowed = max(3, gate.requested)
        why = ("evidence mein asli takraav mila, isliye nayi hypothesis ki "
               "zaroorat bhi hai" if conflict_route and not strong
               else "kaafi relevant source hain aur unme se kuch gehrai tak padhe gaye")
        gate.reason = (f"{gate.relevant_sources} relevant source "
                       f"({gate.deep_sources} kam se kam abstract tak padhe, "
                       f"{gate.full_text_sources} ka poora text) — {why}.")
        return gate

    if gate.relevant_sources >= 2 and gate.deep_sources >= 1:
        gate.allowed = 2
        gate.reason = (f"sirf {gate.relevant_sources} relevant source hain aur "
                       f"{gate.deep_sources} gehrai tak padhe gaye — itne par 2 se "
                       f"zyada hypothesis likhna tukka ban jaata.")
        return gate

    gate.allowed = 1
    gate.reason = (f"evidence patla hai ({gate.relevant_sources} relevant source, "
                   f"{gate.deep_sources} gehrai tak padhe) — is par sirf 1 "
                   f"hypothesis imaandaari se ban sakti hai.")
    return gate


def _fields(chunk: str) -> List[tuple]:
    """Ek hypothesis block se (key, multi-line value) nikaalo, order barkarar."""
    found: List[list] = []
    current: Optional[list] = None
    for line in chunk.splitlines():
        if _HEADING_RE.match(line):
            current = None                      # naya section — field khatam
            continue
        match = _FIELD_LINE_RE.match(line)
        if match:
            # label ko normalize karo: "Counter-Evidence" / "counter  evidence"
            # dono ek hi key banein, warna parse() mein teen-teen spelling
            # handle karni padti hai (aur ek chhoot jaati hai).
            key = re.sub(r"[\s\-]+", " ", match.group(1).lower()).strip()
            current = [key, [match.group(2).strip()]]
            found.append(current)
            continue
        if current is not None and line.strip():
            current[1].append(line.strip())
    out = []
    for key, lines in found:
        value = "\n".join(l for l in lines if l).strip().strip("*").strip()
        out.append((key, value[:_MAX_FIELD_CHARS]))
    return out


@dataclass
class PredictionStructure:
    """
    Spec §10 requirement: structured prediction field.

    Ek hypothesis tab falsifiable hoti hai jab ye clear ho ki:
      1. Kaunse variables measure honge
      2. Expected outcome kya hai (numeric ranges, qualitative states)
      3. Measurement method kya hogi
      4. Kya result hypothesis ko reject kar dega
    """
    variables: List[str] = field(default_factory=list)     # ["blood glucose", "insulin sensitivity"]
    expected_outcome: str = ""                              # "30% reduction in fasting glucose"
    measurement_method: str = ""                            # "HOMA-IR index, fasting plasma glucose"
    falsification_condition: str = ""                       # "no significant change after 12 weeks"

    def to_dict(self) -> Dict:
        return {
            "variables": self.variables,
            "expected_outcome": self.expected_outcome,
            "measurement_method": self.measurement_method,
            "falsification_condition": self.falsification_condition,
        }

    @property
    def is_complete(self) -> bool:
        """Structured prediction tabhi complete jab saare fields meaningful hon."""
        return (len(self.variables) > 0
                and len(self.expected_outcome.strip()) >= 10
                and len(self.measurement_method.strip()) >= 10)


@dataclass
class ExperimentStructure:
    """
    §16 — "test plan" tabhi test plan hai jab ye saaf ho ki kya chalayenge, kis
    par, kis control ke saath, kaunsi cheez naapenge, aur kaunsa nateeja
    hypothesis ko khatam kar dega.

    Pichhli report me "weak test plans" ko falsification bata diya gaya tha:
    "simulation chalao" jaisi line ko plan gina gaya. Isliye ab plan ke hisse
    alag-alag naape jaate hain aur adhoore hisse naam le kar report hote hain.
    Kuch bhi bharke complete nahi banaya jaata.
    """
    experiment_type: str = ""        # observation / simulation / lab / re-analysis
    setup: str = ""                  # kya banega/chalega
    system_or_sample: str = ""       # kis par (dataset, galaxy sample, cell line)
    sample_size: str = ""            # kitna / kitne runs
    control: str = ""                # control ya null model
    measured_quantity: str = ""      # kya naapa jayega
    instrument_or_dataset: str = ""  # kis instrument/dataset se
    expected_signal: str = ""        # hypothesis sach ho to kya dikhega
    null_result: str = ""            # galat ho to kya dikhega
    feasibility: str = ""            # aaj ke tools se ho sakta hai ya nahi
    limitations: str = ""            # is plan ki apni kamzori
    # §16 ke baaki paanch naam. Ye plan ke "core" mein nahi hain (is_complete
    # inhe nahi dekhta, warna aaj ke saare plan achaanak adhoore ho jaate) par
    # spec inhe naam se maangta hai, isliye ab ye alag fields hain aur
    # `to_spec_dict()` mein wahi naam se jaate hain. Bharte SIRF tab hain jab
    # text mein sach mein likhe ho — placeholder kabhi nahi.
    parameter_range: str = ""        # pehle se tay bounded range
    statistical_metric: str = ""     # pehle se chuna hua metric (p, chi2, BF…)
    measurement_precision: str = ""  # kitni precision chahiye
    replication_plan: str = ""       # doosra group isko dobara kaise karega
    cost_and_safety: str = ""        # ₹0 feasibility + risk limits

    _CORE = ("experiment_type", "setup", "system_or_sample",
             "measured_quantity", "expected_signal", "null_result")

    def to_dict(self) -> Dict:
        return {
            "experiment_type": self.experiment_type,
            "setup": self.setup,
            "system_or_sample": self.system_or_sample,
            "sample_size": self.sample_size,
            "control": self.control,
            "measured_quantity": self.measured_quantity,
            "instrument_or_dataset": self.instrument_or_dataset,
            "expected_signal": self.expected_signal,
            "null_result": self.null_result,
            "feasibility": self.feasibility,
            "limitations": self.limitations,
            "missing": self.missing,
            "is_complete": self.is_complete,
        }

    # §16 ka exact naam-wala view. Kyun alag: hamare andar ke naam insaani
    # report ke liye bane the ("kya naapa jayega"), aur spec integration ke
    # liye tay naam maangta hai. Dono chahiye — isliye mapping yahan ek jagah
    # likhi hai, aur jo hissa text mein nahi mila wo KHAALI jaata hai (bharke
    # complete dikhana hi wo galti thi jise §16 rok raha hai).
    SPEC_KEYS = ("dataset_or_sample", "control_or_baseline", "measured_variables",
                 "parameter_range", "statistical_metric", "success_threshold",
                 "failure_threshold", "falsification_condition",
                 "measurement_precision", "replication_plan", "cost_and_safety")

    def to_spec_dict(self, falsification: str = "") -> Dict:
        dataset = " — ".join(p for p in (self.system_or_sample.strip(),
                                         self.sample_size.strip()) if p)
        if self.instrument_or_dataset.strip() and not dataset:
            dataset = self.instrument_or_dataset.strip()
        measured = [p.strip() for p in re.split(r",|\baur\b|\band\b",
                                                self.measured_quantity)
                    if len(p.strip()) >= 2]
        # Kabhi-kabhi prose plan ek hi lambi line hota hai; use comma par todne
        # se "variables" ki jagah aadhe vaakya aa jaate hain. Aisi haalat mein
        # poora hissa ek hi item rehta hai — todne ka faayda tabhi jab tukde
        # sach mein chhote naam hon.
        if any(len(p) > 120 for p in measured):
            measured = ([self.measured_quantity.strip()]
                        if self.measured_quantity.strip() else [])
        cost = " — ".join(p for p in (self.cost_and_safety.strip()
                                      or self.feasibility.strip(),
                                      self.limitations.strip()) if p)
        return {
            "dataset_or_sample": dataset,
            "control_or_baseline": self.control.strip(),
            "measured_variables": measured,
            "parameter_range": self.parameter_range.strip(),
            "statistical_metric": self.statistical_metric.strip(),
            "success_threshold": self.expected_signal.strip(),
            "failure_threshold": self.null_result.strip(),
            "falsification_condition": (falsification or "").strip()
                                       or self.null_result.strip(),
            "measurement_precision": self.measurement_precision.strip(),
            "replication_plan": self.replication_plan.strip(),
            "cost_and_safety": cost,
        }

    def spec_missing(self, falsification: str = "") -> List[str]:
        """§16 ke wo naam jo is plan mein sach much nahi aaye."""
        spec = self.to_spec_dict(falsification)
        return [key for key in self.SPEC_KEYS
                if not (spec[key] if isinstance(spec[key], list)
                        else str(spec[key]).strip())]

    # §16 ke spec naam padhne wale ke liye bekaar hain ("statistical_metric"),
    # aur sirf ledger mein "plan poora nahi bana" likh dena kaafi nahi tha:
    # hypothesis card par experiment ki ek line chhap jaati thi jo CHALAYA JA
    # SAKNE WALA plan lagti thi, jabki 11 mein se 7 hisse khaali the. Isliye
    # yahan insaani naam rakhe hain aur card par saaf likha jaata hai ki plan ka
    # kaunsa hissa likha hi nahi gaya.
    SPEC_LABELS = {
        "dataset_or_sample": "kis dataset/sample par (aur kitna bada)",
        "control_or_baseline": "control ya baseline kya hoga",
        "measured_variables": "kaunse variables naape jayenge",
        "parameter_range": "kis range mein parameters ghumaye jayenge",
        "statistical_metric": "kaunsa statistical metric pehle se chuna gaya",
        "success_threshold": "pass maanne ki hadd",
        "failure_threshold": "fail maanne ki hadd",
        "falsification_condition": "kaunsa nateeja ise galat sabit karega",
        "measurement_precision": "measurement ki zaroori precision",
        "replication_plan": "doosri team se dohraane ka plan",
        "cost_and_safety": "kharcha aur safety ki hadd",
    }

    def spec_missing_labels(self, falsification: str = "") -> List[str]:
        """Missing spec hisse, padhne wale ki bhasha mein."""
        return [self.SPEC_LABELS.get(k, k)
                for k in self.spec_missing(falsification)]

    @property
    def missing(self) -> List[str]:
        """Plan ke jo core hisse nahi aaye (user ki bhasha me)."""
        labels = {
            "experiment_type": "kis tarah ka test hai (observation/simulation/lab)",
            "setup": "setup (kya chalega)",
            "system_or_sample": "kis system/sample par",
            "measured_quantity": "kya naapa jayega",
            "expected_signal": "sach hone par kya dikhega",
            "null_result": "galat hone par kya dikhega",
        }
        out = []
        for name in self._CORE:
            if len(str(getattr(self, name, "") or "").strip()) < 8:
                out.append(labels[name])
        return out

    @property
    def is_complete(self) -> bool:
        return not self.missing

    @property
    def is_usable(self) -> bool:
        """Adhoora par kaam ka: kya naapenge + kaunsa nateeja galat sabit karega."""
        return (len(self.measured_quantity.strip()) >= 8
                and len(self.null_result.strip()) >= 8)


@dataclass
class ConfidenceAssessment:
    """
    §18 — confidence ek BAND hai, number nahi.

    `numeric_allowed` jaan-boojh kar False hai aur kabhi True nahi hota: "90-95%
    probability" jaisa number bina calculation ke banta hai, aur wahi pichhli
    report ki sabse bhari galti thi.
    """
    band: str = CONF_VERY_LOW
    reason_codes: List[str] = field(default_factory=list)
    why: str = ""
    model_said: str = ""             # LLM ne khud jo likha (LOW/MEDIUM/HIGH)
    numeric_allowed: bool = False

    def to_dict(self) -> Dict:
        return {
            "band": self.band,
            "reason_codes": list(self.reason_codes),
            "reasons": [CONF_REASON_CODES.get(c, c) for c in self.reason_codes],
            "why": self.why,
            "model_said": self.model_said,
            "numeric_allowed": self.numeric_allowed,
            "basis": "reasoning-based — evidence-backed proof nahi",
        }


@dataclass
class Hypothesis:
    statement: str = ""
    simple: str = ""              # "simple words mein" — user-facing explanation
    reasoning: str = ""
    supporting_evidence: str = ""
    contradicting_evidence: str = ""
    novelty: str = ""
    assumptions: str = ""         # kya maan kar chal rahe hain
    prediction: Optional[PredictionStructure] = None  # spec §10: structured field
    prediction_text: str = ""                          # fallback: agar structured parse na ho
    how_to_test: str = ""
    experiment: str = ""          # point 11: required experiment / simulation
    falsification: str = ""       # point 11: falsification test (alag field)
    if_true: str = ""             # agar sahi nikli to kya badlega
    if_false: str = ""            # agar galat nikli to kya matlab hoga
    risks: str = ""
    confidence: str = ""
    status: str = STATUS          # kabhi override nahi hota

    # ── §13-§18 ka extra record (enrich() bharta hai, parser nahi) ───────────
    # Ye sab OPTIONAL hain aur default khaali/None hai — purana code jo sirf
    # `statement`/`prediction` padhta tha, waise hi chalta rahega.
    hypothesis_id: str = ""                       # RV-HYP-2026-041 (stable)
    mechanism: str = ""                           # §13: kaam karne ka tareeka
    gap: str = ""                                 # §13: kaunsa khaali hissa bhar rahi hai
    facts_used: List[str] = field(default_factory=list)   # cite hui source IDs
    experiment_struct: Optional[ExperimentStructure] = None   # §16
    prior_work: List[Dict] = field(default_factory=list)      # §15
    novelty_record: Dict = field(default_factory=dict)        # §14
    confidence_record: Optional[ConfidenceAssessment] = None  # §18
    validation: str = VALIDATION_NOT_STARTED                  # §18
    safety_sensitive: Optional[bool] = None       # §2: risk checks compulsory kab

    @property
    def provenance(self) -> Dict:
        """§13 — hypothesis kis cheez se bani: kaunse facts, kaunsa gap."""
        return {
            "facts_used": list(self.facts_used),
            "facts_used_count": len(self.facts_used),
            "gap": self.gap,
            "reasoning_chain": self.reasoning,
            "from_sources": bool(self.facts_used),
        }

    @property
    def is_testable(self) -> bool:
        # `experiment_plan` = explicit "Required experiment" warna "How to test".
        # Pehle sirf `how_to_test` dekha jaata tha, isliye jis hypothesis ne
        # poora experiment design "Required experiment:" mein diya (jo humne
        # point 11 mein khud maanga hai) wo bhi "untestable" gini jaati thi.
        return len(self.experiment_plan) >= 20

    # ── point 11 ke chhe zaroori hisse ───────────────────────────────────────
    # Spec har hypothesis se maangta hai: support, counter-evidence,
    # assumptions, falsification test, required experiment/simulation,
    # confidence. Pehle in sab ka koi single naap nahi tha, isliye report ye
    # bata hi nahi sakti thi ki hypothesis "poori" hai ya aadhi.
    @property
    def falsification_test(self) -> str:
        """
        Explicit falsification field, warna prediction ka falsification
        condition, warna `how to test` ka wo hissa jisme "galat sabit" ki baat
        hai. Kuch bana kar nahi likhte — jo asal mein aaya wahi lautate hain.
        """
        if self.falsification.strip():
            return self.falsification.strip()
        if self.prediction and self.prediction.falsification_condition.strip():
            return self.prediction.falsification_condition.strip()
        for source in (self.how_to_test, self.prediction_text):
            text = (source or "").strip()
            if not text:
                continue
            if _FALSIFY_HINT_RE.search(text):
                return text
        return ""

    @property
    def experiment_plan(self) -> str:
        """Required experiment/simulation — alag field, warna test design."""
        return (self.experiment.strip() or self.how_to_test.strip())

    @property
    def missing_fields(self) -> List[str]:
        """
        Jo zaroori hisse nahi aaye — user ki bhasha mein. Khaali list = poori
        hypothesis (spec ke chhe requirement ke hisaab se).
        """
        missing: List[str] = []
        if len(self.supporting_evidence.strip()) < 10:
            missing.append("support dene wala evidence")
        if len(self.contradicting_evidence.strip()) < 10:
            missing.append("iske khilaf ka evidence (counter-evidence)")
        if len(self.assumptions.strip()) < 10:
            missing.append("assumptions")
        if len(self.falsification_test) < 15:
            missing.append("falsification test (kaunsa result ise galat karega)")
        if len(self.experiment_plan) < 20:
            missing.append("zaroori experiment/simulation")
        if not self.confidence.strip():
            missing.append("confidence")
        return missing

    @property
    def is_complete(self) -> bool:
        """Poori hypothesis = chhe zaroori hisse + testable + prediction."""
        return (not self.missing_fields
                and self.is_testable and self.has_prediction)

    @property
    def has_prediction(self) -> bool:
        """
        Prediction hi hypothesis ko falsifiable banati hai: agar 'kya observe hoga'
        likha hi nahi, to koi observation use galat sabit nahi kar sakta.
        """
        if self.prediction and self.prediction.is_complete:
            return True
        return len(self.prediction_text.strip()) >= 15

    def to_dict(self) -> Dict:
        """
        Structured prediction prefer karo, par text bhi saath rakho.

        §16 prediction ke CHAAR naam maangta hai: variables, expected_outcome,
        measurement_method, falsification_condition. Pehle ye naam sirf tab
        aate the jab structured parse poora ho jaata tha, warna dict sirf
        `{text, structured}` reh jaati thi — yaani adhoore case mein spec ke
        naam gayab. Aur ulta case bhi galat tha: structured ban jaane par asli
        `text` gir jaata tha. Ab chaaron naam HAMESHA maujood hain (jo nahi
        mila wo khaali), `text` bhi hamesha rehta hai, aur `structured` batata
        hai ki chaaron fields bharose ke laayak bane ya nahi.
        """
        pred_struct = bool(self.prediction and self.prediction.is_complete)
        pred_src = self.prediction or PredictionStructure()
        pred = {
            "variables": list(pred_src.variables),
            "expected_outcome": pred_src.expected_outcome,
            "measurement_method": pred_src.measurement_method,
            "falsification_condition": (pred_src.falsification_condition
                                        or self.falsification_test),
            "text": self.prediction_text,
            "structured": pred_struct,
        }
        novelty = dict(self.novelty_record or {})
        out = {
            "status": STATUS,
            "statement": self.statement,
            "simple": self.simple,
            "reasoning": self.reasoning,
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "novelty": self.novelty,
            "assumptions": self.assumptions,
            "prediction": pred,
            "has_prediction": self.has_prediction,
            "how_to_test": self.how_to_test,
            # point 11 — ye do alag se report hote hain, kyunki "test kar lenge"
            # aur "kaunsa result ise galat sabit karega" ek baat nahi hai.
            "experiment": self.experiment_plan,
            "falsification_test": self.falsification_test,
            "if_true": self.if_true,
            "if_false": self.if_false,
            "is_testable": self.is_testable,
            "risks": self.risks,
            "confidence_reasoning_based": self.confidence,
            "missing_fields": self.missing_fields,
            "is_complete": self.is_complete,
            "disclaimer": ("UNTESTED HYPOTHESIS — asli validation lab/field test se "
                          "hi hoga, AI-generated assumption ko fact mat maano"),
        }
        # ── §13-§18 ka structured record ─────────────────────────────────────
        # Purani keys upar jaisi ki waisi hain (koi consumer toota nahi), ye sab
        # UPAR SE juda hua hissa hai.
        out.update({
            "hypothesis_id": self.hypothesis_id,
            "mechanism": self.mechanism,
            "provenance": self.provenance,
            "source_claim_disclaimer": SOURCE_CLAIM_DISCLAIMER,
            "app_generated": True,
            "is_established_fact": False,
            "closest_prior_work": list(self.prior_work),
            "novelty_status": novelty.get("novelty_status", NOVELTY_UNVERIFIED),
            "novelty_why": novelty.get("why", ""),
            "novelty_search": novelty.get("novelty_search", {}),
            "known_idea_hits": novelty.get("known_idea_hits", []),
            "experiment_structured": (self.experiment_struct.to_dict()
                                      if self.experiment_struct else None),
            # §16 ka exact naam-wala experiment record (11 keys). Upar wala
            # `experiment_structured` hamare andar ke naam rakhta hai (report
            # usse likhi jaati hai); ye wahi plan spec ke naamon mein deta hai,
            # aur `experiment_spec_missing` saaf batata hai ki kaunsa hissa
            # plan mein sach mein nahi tha.
            "experiment_spec": (
                self.experiment_struct.to_spec_dict(self.falsification_test)
                if self.experiment_struct else None),
            "experiment_spec_missing": (
                self.experiment_struct.spec_missing(self.falsification_test)
                if self.experiment_struct else list(
                    ExperimentStructure.SPEC_KEYS)),
            # Wahi list padhne wale ki bhasha mein — report isse card par ek
            # line chhaapti hai, taaki adhoora plan poora na lage.
            "experiment_spec_missing_human": (
                self.experiment_struct.spec_missing_labels(
                    self.falsification_test)
                if self.experiment_struct else
                [ExperimentStructure.SPEC_LABELS[k]
                 for k in ExperimentStructure.SPEC_KEYS]),
            "confidence": (self.confidence_record.to_dict()
                           if self.confidence_record else None),
            "confidence_band": (self.confidence_record.band
                                if self.confidence_record else None),
            "validation_status": self.validation,
            "safety_sensitive": self.safety_sensitive,
        })
        return out


class HypothesisEngine:
    # ── kab generate karna hai ───────────────────────────────────────────────
    def should_generate(self, plan: Dict, pack: EvidencePack,
                        contradictions: Optional[List[Dict]] = None,
                        evidence_level: str = "") -> bool:
        if plan.get("is_unresolved") or plan.get("is_creative"):
            return True
        if contradictions:
            return True
        if evidence_level in ("MIXED", "WEAK") and plan.get("is_scientific"):
            return True
        return False

    # ── PASS 5 prompt (Spec Section 10) ──────────────────────────────────────
    # `count` baad mein juda (2026-08-20): user ka prompt "kam se kam 3 nayi
    # hypotheses banao" keh sakta hai. Pehle yahan hard-coded "Maximum 2" tha,
    # yaani engine user ki explicit request KABHI poori nahi kar sakta tha.
    # Default 2 hai taaki purani positional call (`prompt(q, a, pack, plan)`)
    # bilkul waise hi chalti rahe.
    def prompt(self, question: str, analysis: str, pack: EvidencePack,
               plan: Dict, contradictions: Optional[List[Dict]] = None,
               count: int = 2, gate: Optional[EvidenceGate] = None) -> str:
        gaps = "\n".join(f"  - {c.get('summary', '')}" for c in (contradictions or [])[:5])
        gap_block = f"\nEVIDENCE CONFLICTS jo mile:\n{gaps}\n" if gaps else ""
        fields = ", ".join(plan.get("relevant_fields", [])[:4]) or "relevant fields"
        count = max(1, min(int(count or 2), 6))
        blocks = "\n\n".join(self._format_block(i) for i in range(1, count + 1))
        gate_block = self._gate_block(gate)
        # Lens block yahan sabse zyada zaroori hai: hypothesis banane ka kaam hi
        # "kaunsa dhaancha lagaun" par tika hai. Pehle framework ka naam sirf
        # search query tak jaata tha, isliye app ke paas apni soch me lagane ke
        # liye koi ozaar nahi hota tha. Khaali lens par "" — tab prompt bilkul
        # purana rehta hai.
        lens_block = ""
        try:
            from .lenses import reasoning_block as lens_reasoning_block
            lens_text = lens_reasoning_block(
                (plan.get("lens") if isinstance(plan, dict) else None) or {})
            lens_block = f"\n{lens_text}\n" if lens_text else ""
        except Exception:          # pragma: no cover - lens layer optional hai
            lens_block = ""

        return f"""Tum ek Hypothesis Generator ho. Tumhara kaam NAYI possibility
propose karna hai — literature ka summary dohrana nahi.

SAWAL: {question}

CURRENT EVIDENCE-BASED ANALYSIS:
{analysis[:4000]}
{gap_block}
SOURCES (sirf inhi ko cite karo, [S#] format mein):
{pack.to_prompt_block(max_chars_per_source=500)}
{gate_block}{lens_block}
Rules — ye tod'ne par output reject ho jaayega:
1. Hypothesis ko FACT ki tarah mat likho. Har hypothesis ka status
   "{STATUS}" hai.
2. Reasoning chain step-by-step likho: kaun se evidence se kaun sa step nikla.
3. Jo baat kisi source se supported nahi hai, use [NO-SOURCE] mark karo.
4. Test design REAL hona chahiye (kya measure karoge, control kya hoga,
   kitna sample, kya result hypothesis ko galat sabit karega).
5. Medical/chemical/biological hypothesis ho to risks aur safety concerns
   likhna zaroori hai. "Ye ilaj hai" jaisa dawa mat karo.
6. {fields} ko cross-connect karke sochne ki koshish karo.
7. Prediction concrete honi chahiye: "agar ye hypothesis sach hai to KYA
   observe hoga" — measurable, aur aisi ki galat nikle to pata chal jaaye.
8. "Simple explanation" line har hypothesis mein ZAROORI hai: ekdum aam bhasha
   mein, jaise samne baithe bande ne ye concept pehle kabhi suna hi na ho.
   Jargon aaye to bracket mein uska matlab likho.
9. Har hypothesis mein ye CHHE cheezein zaroori hain, warna wo adhoori maani
   jayegi (aur report mein "adhoori" likha jayega): supporting evidence,
   contradicting evidence, assumptions, falsification test, required
   experiment/simulation, confidence.
10. Evidence patla ho to hypotheses ki GINTI ghata do, quality nahi. Bina base
   ki hypothesis likhne se behtar hai ek line likh dena: "sirf N ban sakti,
   kyunki ...".
11. NOVELTY par jhooth mana hai: "100% new", "duniya mein pehli", "discovery ho
   gayi" jaise shabd nahi. Jo idea pehle se literature mein hai (PBH, MOND, dark
   photon, fifth force, axion, sterile neutrino, modeling systematics jaisi
   cheezein) use "known idea" likho — us par nayi hypothesis banana theek hai,
   par use apni khoj batana galat hai.
12. Mechanism zaroori hai: sirf "X ki wajah se Y hota hoga" nahi — KAISE hota
   hai, kis cheez par asar padta hai, kis step ke baad kya. Mechanism na likh
   pao to saaf likho ki mechanism nahi pata.

{count} hypotheses do (isse kam nahi — agar {count} banane layak material nahi hai
to jitni bani utni do aur alag line mein saaf likho: "sirf N ban sakti, kyunki ...").
Format exactly aise:

{blocks}

Ab hypothesis do:"""

    @staticmethod
    def _gate_block(gate: Optional[EvidenceGate]) -> str:
        """
        Model ko evidence ki asli haalat batao. Kyun: patle evidence par 3
        hypotheses maangne se model fabricate karta hai — usi ko point 11 rokta
        hai. Ye block "jhoothi confidence" ka sabse sasta ilaj hai (₹0).
        """
        if gate is None:
            return ""
        line = (f"\nEVIDENCE KI HAALAT (system ne gini hai): "
                f"{gate.relevant_sources} relevant source, {gate.deep_sources} kam "
                f"se kam abstract tak padhe, {gate.full_text_sources} ka poora text, "
                f"{gate.contradictions} takraav.")
        if not gate.sufficient:
            line += ("\nYaani evidence patla hai: kam hypotheses do, par jo do "
                     "unka base saaf dikhao. Base na ho to saaf likho.")
        return line + "\n"

    @staticmethod
    def _format_block(index: int) -> str:
        """Ek hypothesis ka maanga hua format. Fields ke labels PARSER se match
        karte hain (`_FIELD_NAMES`) — inhe badalna hai to dono jagah badlo."""
        return f"""## Hypothesis {index}
- Statement: (ek line, testable)
- Simple explanation: (2-4 line, ekdum aam bhasha mein — "humara idea ye hai ki
  ..."; koi jargon nahi, aur ek roz-marra ka example do)
- Gap: (kaunsa khaali hissa ye bhar rahi hai — jo baat sources me MILI HI NAHI)
- Mechanism: (ye kaam KAISE karega — step by step physical/biological raasta;
  "ho sakta hai" kaafi nahi, jo cheez kis par asar karegi wo likho)
- Reasoning: (step-by-step chain: kis evidence se kaun sa step nikla)
- Supporting evidence: ([S#] ke saath, aur ek line mein ye bhi ki wo source kya
  kehta hai)
- Contradicting evidence: (kya iske khilaf jaata hai — "kuch nahi mila" likhne se
  pehle sach mein dhoondo)
- Novelty: (existing literature se kaise different hai; pehle se known ho sakta
  hai to saaf likho. PBH, MOND, dark photon, fifth force, axion, sterile
  neutrino, modeling systematics jaisi cheezein PEHLE SE KNOWN hain — inhe apni
  nayi soch mat batao. "100% new", "duniya mein pehli", "discovery" jaise shabd
  mana hain.)
- Assumptions: (kya maan kar chal rahe hain — jo maan liya wo galat ho sakta hai)
- Prediction: (agar sach hai to kya measurable cheez dikhegi — aur kya dikhna ise
  galat sabit kar dega)
- Required experiment: (wo asli experiment ya simulation jo ise test karega:
  kya setup, kya control, kitna sample/kitne runs, kaunsa measurement, kaunse
  instrument/dataset, expected signal, aur null result kya dikhega)
- Falsification test: (ek line — KAUNSA result aane par ye hypothesis khatam
  maani jayegi; "kuch nahi" likhna allowed nahi)
- How to test: (concrete experiment/analysis + falsification condition)
- If true: (sahi nikli to practically kya badlega)
- If false: (galat nikli to kya seekhne ko milega)
- Risks: (safety, ethical, practical)
- Confidence: (LOW/MEDIUM/HIGH — reasoning-based hai, proof nahi. Percentage ya
  probability ka number MAT likho: uske peeche koi calculation nahi hoti)"""

    def prompt_appendix(self, count: int = 2) -> str:
        """
        Jab call budget kam ho (DEEP/MAXIMUM = 2-3 calls), tab hypothesis ke liye
        alag call nahi bachti. Ye chhota block critic prompt ke saath jod diya
        jaata hai, taaki ek hi response mein critique + hypothesis dono aa jaayein.

        2026-08-20: `count` add hua. Live run mein user ne 3 hypotheses maangi
        thi aur quota ki wajah se hypothesis pass hi nahi chala — ab ye appendix
        ANALYSIS pass ke saath bhi jud sakta hai, isliye count honour karna
        zaroori hai.
        """
        count = max(1, min(int(count or 2), 6))
        blocks = "\n\n".join(self._format_block(i) for i in range(1, count + 1))
        return f"""
---
ISI RESPONSE MEIN, aakhir mein, {count} nayi hypotheses bhi do (isse kam nahi).
Rules: hypothesis ko fact ki tarah mat likho; status "{STATUS}" hai; test design
concrete ho; prediction measurable ho; medical/chemical ho to risks likho;
[S#] se cite karo, warna [NO-SOURCE] likho. "Simple explanation" line skip mat
karo — wahi line user asal mein padhta hai.

Format exactly aise:

{blocks}
"""

    # ── structured prediction parser (Spec §10) ──────────────────────────────
    # YAHAN EK ASLI BUG THA (2026-08-19 ko pakda gaya): is class mein
    # `_parse_prediction` DO baar define tha. Python mein doosri definition pehli
    # ko chup-chaap kha jaati hai, aur doosri `(PredictionStructure, text)` ka
    # TUPLE lautati thi. `parse()` us tuple ko `h.prediction` mein rakh deta tha,
    # aur `Hypothesis.to_dict()` mein `self.prediction.is_complete` par poora
    # pipeline crash karta tha:
    #     AttributeError: 'tuple' object has no attribute 'is_complete'
    # Ye MAXIMUM mode ka asli raasta hai (hypothesis ban kar answer mein jaati
    # hai), isliye ye live crash tha — sirf test ka issue nahi.
    #
    # Dono purani strategies bachi hui hain, ek hi function mein:
    #   1. LABELLED lines ("Variables: x, y" / "Measurement: HOMA-IR") — Gemini
    #      se hum yahi format maangte hain, isliye pehle ye.
    #   2. Free-text heuristic (keywords + percentage regex) — jab model ne
    #      labels na likhe ho.
    # Jaan-boojh kar hataayi gayi sirf ek cheez: placeholder bharna
    # ("expected_outcome = 'change expected'", "measurement = 'to be
    # determined'"). Us se khaali prediction bhi `is_complete` ban jaati thi,
    # yaani report jhooth bolti ki structured prediction maujood hai.
    @staticmethod
    def _parse_prediction(text: str) -> Optional[PredictionStructure]:
        """
        Free-text prediction se structured prediction nikaalo (mile to).

        Kuch na mile to None — tab `Hypothesis.prediction_text` (asli text) hi
        aage jaata hai. Khaali structure banana mana hai.
        """
        if not text or len(text.strip()) < 20:
            return None

        pred = PredictionStructure()
        lower = text.lower()

        # ── 1. labelled lines ────────────────────────────────────────────────
        for line in [l.strip() for l in text.split("\n") if l.strip()]:
            low = line.lower()
            if any(k in low for k in ("variable", "parameter", "factor")):
                items = re.findall(r'["\']([^"\']+)["\']|:\s*([^,\n]+)', line)
                for a, b in items:
                    value = (a or b or "").strip()
                    if value and value not in pred.variables:
                        pred.variables.append(value)
            if any(k in low for k in ("expect", "outcome", "result")):
                match = re.search(
                    r"(\d+%|\d+\.\d+|\d+\s*(?:fold|times|unit|point|level))[^.]*",
                    line)
                if match and not pred.expected_outcome:
                    pred.expected_outcome = match.group(0).strip()
            if any(k in low for k in ("measur", "assess", "index", "scale", "method")):
                match = re.search(r"(?:using|via|through|with|by)\s+([^,.\n]+)",
                                  line, re.IGNORECASE)
                if match and not pred.measurement_method:
                    pred.measurement_method = match.group(1).strip()
                elif (":" in line and not pred.measurement_method
                      # sirf tab jab LABEL hi measurement ka ho. Warna
                      # "Variables: fasting glucose, HOMA-IR index" wali line
                      # ("index" ki wajah se) measurement ban jaati thi.
                      and any(k in low.split(":", 1)[0]
                              for k in ("measur", "assess", "method"))):
                    pred.measurement_method = line.split(":", 1)[1].strip()
            if any(k in low for k in ("falsif", "disprove", "reject", "null",
                                      "no change", "no effect")):
                if not pred.falsification_condition:
                    pred.falsification_condition = line.strip()

        # ── 2. free-text heuristic (labels na mile ho to) ────────────────────
        if not pred.variables:
            var_keywords = ["glucose", "insulin", "pressure", "weight",
                            "temperature", "level", "rate", "count", "score",
                            "index", "concentration", "gap", "error"]
            pred.variables = [kw for kw in var_keywords if kw in lower]
        if not pred.expected_outcome:
            for pattern in (
                r"(increase|decrease|reduction|rise|drop|change).*?(\d+[-–]?\d*%?)",
                r"(significant|no significant|positive|negative|elevated|reduced)",
            ):
                match = _re_module.search(pattern, lower)
                if match:
                    pred.expected_outcome = match.group(0)
                    break
        if not pred.measurement_method:
            match = re.search(
                r"measur\w*\s+(?:via|by|using|with)\s+([^;,\.]+)", lower)
            if match:
                pred.measurement_method = match.group(1).strip()
        if not pred.falsification_condition:
            match = re.search(
                r"(?:if no|if opposite|reject\w* if|falsif\w* if)\s+([^;,\.]+)",
                lower)
            if match:
                pred.falsification_condition = match.group(0).strip()

        # kuch asli mila tabhi lautao — warna text fallback behtar hai
        if pred.variables or pred.expected_outcome:
            return pred
        return None

    # ── §16 structured experiment parser ─────────────────────────────────────
    # Kyun zaroori: "Required experiment: run a simulation" ek line hai, plan
    # nahi. Pichhli report me aise hi line ko falsification test bata diya gaya
    # tha. Ye parser sirf WAHI bharta hai jo text me asal me likha hai — koi
    # placeholder nahi, warna adhoora plan "complete" dikhne lagta hai.
    _EXP_LABELS = (
        ("setup", ("setup", "design", "protocol", "procedure", "method")),
        ("system_or_sample", ("sample", "system", "population", "cohort",
                              "dataset", "galaxies", "cluster", "subjects")),
        ("sample_size", ("sample size", "n =", "runs", "how many", "kitne")),
        ("control", ("control", "null model", "baseline", "comparison group",
                     "placebo")),
        ("measured_quantity", ("measure", "measurement", "observable",
                               "quantity", "endpoint", "naap")),
        ("instrument_or_dataset", ("instrument", "telescope", "survey data",
                                   "data from", "using data", "catalog")),
        ("expected_signal", ("expected", "if true", "signal", "prediction")),
        ("null_result", ("null", "if false", "no signal", "no change",
                         "reject", "falsif", "rule out")),
        ("feasibility", ("feasib", "possible today", "current technology",
                         "cost", "time required")),
        ("limitations", ("limitation", "caveat", "weakness", "kamzori")),
        # §16 ke paanch extra naam — sirf jab text mein likhe ho.
        ("parameter_range", ("parameter range", "range of", "between",
                             "bounded range", "scan range", "sweep")),
        ("statistical_metric", ("statistic", "p-value", "p value", "chi2",
                                "chi-squared", "bayes factor", "sigma",
                                "confidence interval", "metric")),
        ("measurement_precision", ("precision", "resolution", "accuracy",
                                   "error bar", "uncertainty of",
                                   "sensitivity of")),
        ("replication_plan", ("replicat", "independent group", "second group",
                              "reproduce", "another team")),
        ("cost_and_safety", ("safety", "risk limit", "biosafety", "hazard",
                             "₹0", "zero cost", "free data", "budget")),
    )

    # Bina label likhe bhi log naapne wali cheez ka NAAM lete hain
    # ("4-probe resistance", "rotation curve", "Tc"). In shabdon ko pakadna
    # fabrication nahi hai — hum plan ka wahi hissa quote karte hain, apni
    # taraf se koi measurement invent nahi karte.
    _MEASURE_HINTS = re.compile(
        r"\b(resistance|resistivity|susceptibilit\w*|conductivit\w*|spectrum|"
        r"spectra|spectroscop\w*|flux|luminosit\w*|brightness|velocit\w*|"
        r"rotation curve|lensing|redshift|mass function|concentration|"
        r"temperature|\btc\b|pressure|voltage|current|magnetisation|"
        r"magnetization|count rate|cross[- ]section|amplitude|abundance|"
        r"yield|efficiency|survival|incidence)\b", re.IGNORECASE)

    # Lab/observation ka ishaara upkaran ke naam se bhi milta hai.
    _SETUP_HINTS = re.compile(
        r"\b(run|build|collect|compare|observe|measure|measurement|napo|naap\w*|"
        r"simulat\w*|analyz\w*|analys\w*|design|prepare|synthes\w*|test)\w*\b",
        re.IGNORECASE)

    @classmethod
    def _parse_experiment(cls, text: str, falsification: str = "",
                          prediction: Optional[PredictionStructure] = None,
                          prediction_text: str = ""
                          ) -> Optional[ExperimentStructure]:
        """Free-text experiment plan se §16 ka structured record (mile to)."""
        blob = (text or "").strip()
        if len(blob) < 20:
            return None
        exp = ExperimentStructure()
        lower = blob.lower()

        for pattern, value in (
                (r"\b(simulation|n-body|monte carlo)\b", "simulation"),
                (r"\b(observation|survey|telescope|imaging|spectroscop)\w*", "observation"),
                (r"\b(lab|bench|in vitro|in vivo|clinical|trial)\b", "lab experiment"),
                (r"\b(anvil|cryostat|apparatus|four[- ]probe|4[- ]probe|"
                 r"synthesi[sz]|reactor|furnace|centrifuge)\w*", "lab experiment"),
                (r"\b(re-?analysis|reanaly|archival)\w*", "re-analysis of existing data")):
            if re.search(pattern, lower):
                exp.experiment_type = value
                break

        # Prose plan ek hi line me sab kuch keh deta hai ("10 sample, 4-probe
        # resistance, ek control sample"). Pehle har line se sirf EK field
        # bharti thi, isliye poora plan bhi "adhoora" dikhta tha. Isliye ab
        # comma/aur par bhi tod kar dekhte hain — chhota hissa pehle, kyunki
        # "4-probe resistance" poori line se zyada saaf jawab hai.
        segments: List[str] = []
        for line in [l.strip(" -*\t") for l in re.split(r"[\n;]+", blob) if l.strip()]:
            if ":" in line:
                segments.append(line)
                continue
            parts = [p.strip() for p in re.split(r",|\baur\b|\band\b", line)
                     if len(p.strip()) >= 4]
            segments.extend(p for p in parts if p != line)
            segments.append(line)
        for line in segments:
            low = line.lower()
            body = line.split(":", 1)[1].strip() if ":" in line else line
            for name, cues in cls._EXP_LABELS:
                if getattr(exp, name):
                    continue
                head = low.split(":", 1)[0] if ":" in low else low
                if any(cue in head for cue in cues):
                    setattr(exp, name, body[:600] or line[:600])
                    break

        # Label na ho par naapne wali cheez ka naam ho — wahi hissa quote karo.
        if not exp.measured_quantity:
            used = {exp.system_or_sample, exp.control, exp.setup,
                    exp.expected_signal, exp.null_result}
            cands = [s for s in segments
                     if cls._MEASURE_HINTS.search(s) and s not in used]
            if cands:
                exp.measured_quantity = min(cands, key=len)[:600]

        # Jo cheez kahin aur SE PEHLE hi mil chuki hai, wo dobara maangna bekaar:
        # falsification aur structured prediction se seedha bhar sakte hain.
        if not exp.null_result and falsification.strip():
            exp.null_result = falsification.strip()[:600]
        if prediction is not None:
            if not exp.measured_quantity and prediction.measurement_method.strip():
                exp.measured_quantity = prediction.measurement_method.strip()[:600]
            if not exp.expected_signal and prediction.expected_outcome.strip():
                exp.expected_signal = prediction.expected_outcome.strip()[:600]
            if not exp.null_result and prediction.falsification_condition.strip():
                exp.null_result = prediction.falsification_condition.strip()[:600]
        # Structured prediction na bane to uska asli text bhi "sach hone par kya
        # dikhega" ka jawab hai — ye quote hai, guess nahi.
        if not exp.expected_signal and len(prediction_text.strip()) >= 15:
            exp.expected_signal = prediction_text.strip()[:600]
        if not exp.setup and len(blob) >= 40:
            # Poora plan hi setup ka description ho sakta hai — par sirf tab jab
            # usme kaam ki baat ho (koi bhi 40 char nahi).
            if (cls._SETUP_HINTS.search(lower) or exp.experiment_type
                    or exp.system_or_sample):
                exp.setup = blob[:600]

        filled = [n for n, _ in cls._EXP_LABELS if getattr(exp, n)]
        if not filled and not exp.experiment_type:
            return None
        return exp

    def parse(self, text: str, max_count: Optional[int] = None,
              rejects: Optional[List[Dict]] = None) -> List[Hypothesis]:
        """
        Model ke text se hypotheses nikaalo.

        `max_count` pehle hard-coded 3 tha. User "kam se kam 3" maange aur model
        4 de de, to chauthi chup-chaap phenki jaati thi — isliye cap request ke
        hisaab se BADH sakta hai.

        2026-08-21 (cross-domain benchmark): cap mein `max(3, ...)` ka floor tha,
        yaani neeche kabhi nahi ja sakta tha. Nateeja: 2 patle snippet-only
        sources par evidence gate `allowed=1` kehta tha, orchestrator 1 hi
        maangta tha, par model ke bheje 3 blocks poore parse ho jaate the aur
        report mein teen hypotheses chhap jaati thi — gate ka faisla kaagaz par
        reh jaata tha. Ab explicit cap ki izzat hoti hai (1 bhi), aur cap na
        bheja jaaye to purana default 3 hi rehta hai.

        #117: cap se bahar wale blocks aur "statement hi nahi mila" wale blocks
        pehle CHUP-CHAAP gir jaate the. Ab `rejects` list do (optional, purane
        caller waise hi chalte hain) to har gire hue block ka naapa hua record
        milta hai — `rejects.py` usse answer ka reject-section banata hai.
        """
        if not text or not text.strip():
            return []

        asked = int(max_count or 0)
        cap = max(1, asked) if asked > 0 else 3
        blocks = _H_SPLIT_RE.split(text)
        chunks = [b for b in blocks[1:] if b and b.strip()] if len(blocks) > 1 else [text]
        log: List[Dict] = rejects if isinstance(rejects, list) else []

        out: List[Hypothesis] = []
        for position, chunk in enumerate(chunks, 1):
            if position > cap:
                # Cap se bahar. Naap saath jaati hai: kitni aayi, kitni allowed.
                log.append({
                    "reason_code": "over_evidence_cap",
                    "statement": self._chunk_statement(chunk),
                    "index": position,
                    "measured": {"model_ne_bheji": len(chunks),
                                 "cap_allowed": cap,
                                 "block_number": position},
                })
                continue
            h = Hypothesis()
            for key, value in _fields(chunk):
                if key == "statement":
                    h.statement = value
                elif key in ("simple", "simple explanation"):
                    h.simple = value
                elif key == "reasoning":
                    h.reasoning = value
                elif key == "supporting evidence":
                    h.supporting_evidence = value
                elif key in ("against", "contradicting evidence",
                             "counter evidence", "evidence against"):
                    h.contradicting_evidence = value
                elif key == "novelty":
                    h.novelty = value
                elif key == "mechanism":
                    h.mechanism = value
                elif key in ("gap", "knowledge gap"):
                    h.gap = value
                elif key in ("assumption", "assumptions"):
                    h.assumptions = value
                elif key == "prediction":
                    h.prediction_text = value
                    # Try structured parse
                    h.prediction = self._parse_prediction(value)
                elif key in ("required experiment", "required simulation",
                             "experimental plan", "experiment", "simulation"):
                    h.experiment = value
                elif key in ("falsification test", "how to falsify"):
                    h.falsification = value
                elif key in ("how to test", "test"):
                    h.how_to_test = value
                elif key == "if true":
                    h.if_true = value
                elif key == "if false":
                    h.if_false = value
                elif key == "risks":
                    h.risks = value
                elif key == "confidence":
                    h.confidence = value
            if not h.statement:
                # Field format na mila — pehli meaningful line ko statement maan lo
                lines = [l.strip("-*# ").strip() for l in chunk.splitlines() if l.strip()]
                h.statement = next((l for l in lines if len(l) > 25), "")
            if h.statement:
                out.append(h)
            else:
                # #117 — yahi wo chup-chaap drop tha. Ab naap saath jaati hai:
                # block me kitni line thi aur sabse lambi line kitni chhoti thi
                # (25 char ki hadd isi jagah lagti hai).
                block_lines = [l.strip("-*# ").strip()
                               for l in chunk.splitlines() if l.strip()]
                longest = max((len(l) for l in block_lines), default=0)
                log.append({
                    "reason_code": "no_statement_in_block",
                    "statement": "",
                    "index": position,
                    "measured": {"block_chars": len(chunk.strip()),
                                 "lines": len(block_lines),
                                 "sabse_lambi_line_chars": longest,
                                 "kam_se_kam_chahiye_chars": 26},
                })
        return out

    @staticmethod
    def _chunk_statement(chunk: str) -> str:
        """Gire hue block ki pehchan ke liye ek line — reject record me dikhti hai."""
        for line in (chunk or "").splitlines():
            clean = line.strip("-*# ").strip()
            if clean.lower().startswith("statement:"):
                return clean.split(":", 1)[1].strip()
        for line in (chunk or "").splitlines():
            clean = line.strip("-*# ").strip()
            if len(clean) > 25:
                return clean
        return ""

    # ── §13-§18: hypothesis ka poora record (deterministic, LLM ke bina) ─────
    # §2 — in domains me risk/safety check chhodna allowed nahi hai.
    _SAFETY_RE = re.compile(
        r"\b(dose|dosage|drug|drugs|medicine|patient|patients|clinical|therapy|"
        r"treatment|treat|cure|vaccine|toxic|toxicity|carcinogen|pathogen|virus|"
        r"bacteri\w*|gene editing|crispr|synthesis of|reagent|explosive|"
        r"radiation|radioactive|inject|ingest|human trial|in vivo)\b",
        re.IGNORECASE)

    def enrich(self, hypotheses: List[Hypothesis],
               question: str = "",
               pack: Optional[EvidencePack] = None,
               gate: Optional[EvidenceGate] = None,
               contradictions: Optional[List[Dict]] = None,
               counter_search_performed: Optional[bool] = None,
               calculations_done: Optional[bool] = None,
               prior_art_searched: Optional[bool] = None,
               prior_art_databases: Optional[Sequence[str]] = None,
               prior_art_hits: Optional[Dict[str, List[Dict]]] = None,
               ) -> List[Hypothesis]:
        """
        §13-§18 — parse ke baad ka deterministic record (koi LLM call nahi).

        Ye function kabhi kuch "bharke" complete nahi banata: jo cheez nahi mili
        wo khaali rehti hai aur `missing`/reason code me naam le kar aati hai.
        `prior_art_searched=None` ka matlab "search chali hi nahi" hai — usme
        novelty ka jawab NOVELTY UNVERIFIED rehta hai, "novel" nahi.
        """
        sources = list(getattr(pack, "sources", []) or []) if pack is not None else []
        valid_ids = {str(getattr(s, "source_id", "") or "") for s in sources}
        seen_ids: Dict[str, str] = {}     # hypothesis_id -> statement (dup detect)

        for i, h in enumerate(hypotheses, 1):
            # 1. stable ID (statement se, run ke order se nahi)
            h.hypothesis_id = hypothesis_id(h.statement, index=i)
            if h.hypothesis_id in seen_ids:
                # same statement dobara — ID same rahegi, par ise duplicate
                # maana jayega (§14 ka REJECTED AS DUPLICATE isse alag hai:
                # wo prior work ke against hai, ye apne hi output ke against).
                h.gap = h.gap or ""
            seen_ids[h.hypothesis_id] = h.statement

            # 2. provenance — kaunse [S#] asal me cite hue (aur pack me hain bhi)
            cited = re.findall(r"\[?(S\d+)\]?",
                               f"{h.supporting_evidence} {h.reasoning} "
                               f"{h.contradicting_evidence}")
            if valid_ids:
                h.facts_used = [sid for sid in dict.fromkeys(cited) if sid in valid_ids]
            else:
                h.facts_used = list(dict.fromkeys(cited))
            if not h.gap:
                # Model ne "Gap:" nahi likha to KHUD gap ka daawa nahi karte —
                # sirf wahi likhte hain jo sach hai: kis takraav/kami se ye bani.
                if contradictions:
                    first = str((contradictions[0] or {}).get("summary") or "").strip()
                    h.gap = (f"evidence me khula takraav: {first}" if first else "")
                elif gate is not None and gate.full_text_sources == 0 and gate.relevant_sources:
                    h.gap = ("relevant sources ka poora text nahi mila, isliye "
                             "yahan mechanism ka hissa khula hai")

            # 3. §16 structured experiment
            h.experiment_struct = self._parse_experiment(
                h.experiment_plan, falsification=h.falsification_test,
                prediction=h.prediction, prediction_text=h.prediction_text)

            # 4. §15 closest prior work + §14 novelty (whitelist labels only)
            hits = (prior_art_hits or {}).get(h.hypothesis_id)
            h.prior_work = (list(hits) if hits is not None
                            else closest_prior_work(h.statement, sources,
                                                    mechanism=h.mechanism))
            h.novelty_record = novelty_assessment(
                h.statement, mechanism=h.mechanism, prior=h.prior_work,
                prior_art_searched=prior_art_searched,
                databases=prior_art_databases, question=question)

            # 5. §18 confidence band + reason codes
            h.confidence_record = self._confidence(
                h, gate=gate, contradictions=contradictions,
                counter_search_performed=counter_search_performed,
                calculations_done=calculations_done)

            # 6. §18 validation status (kabhi "validated" nahi hota)
            if h.experiment_struct and h.experiment_struct.is_usable:
                h.validation = VALIDATION_PLAN_ONLY
            elif h.is_testable:
                h.validation = VALIDATION_NOT_STARTED
            else:
                h.validation = VALIDATION_NEEDS_PLAN

            # 7. §2 safety-sensitive detection (risks field compulsory)
            h.safety_sensitive = bool(self._SAFETY_RE.search(
                f"{h.statement} {h.mechanism} {h.experiment_plan}"))
        return hypotheses

    @staticmethod
    def _confidence(h: Hypothesis, gate: Optional[EvidenceGate] = None,
                    contradictions: Optional[List[Dict]] = None,
                    counter_search_performed: Optional[bool] = None,
                    calculations_done: Optional[bool] = None
                    ) -> ConfidenceAssessment:
        """
        §18 — band DETERMINISTIC hai: kami ginte hain, plus point ginte hain, aur
        HIGH ka darwaza band hai. Kyun band hai: ek untested hypothesis par "high
        confidence" likhna hi wo galti hai jise ye poora section rok raha hai.
        Model ne khud "HIGH" likha ho to wo `model_said` me alag se rehta hai.
        """
        codes: List[str] = []
        relevant = int(getattr(gate, "relevant_sources", 0) or 0)
        deep = int(getattr(gate, "deep_sources", 0) or 0)
        full = int(getattr(gate, "full_text_sources", 0) or 0)

        if not h.facts_used:
            codes.append("NO_DIRECT_SOURCE")
        if relevant < 2:
            codes.append("THIN_EVIDENCE")
        if full == 0:
            codes.append("SHALLOW_ACCESS")
        if counter_search_performed is not True:
            codes.append("NO_COUNTER_SEARCH")
        if calculations_done is not True:
            codes.append("NO_CALCULATION")
        if not h.has_prediction:
            codes.append("NO_PREDICTION")
        if len(h.falsification_test) < 15:
            codes.append("NO_FALSIFICATION")
        codes.append("UNTESTED")   # ye code HAMESHA lagta hai

        plus = 0
        if len(h.facts_used) >= 2 and relevant >= 2:
            codes.append("MULTI_SOURCE_BASE")
            plus += 1
        if contradictions:
            codes.append("CONTRADICTION_DRIVEN")
            plus += 1
        if len((h.mechanism or "").strip()) >= 40:
            codes.append("MECHANISM_GIVEN")
            plus += 1
        known = known_idea_hits(h.statement, h.mechanism)
        if known:
            codes.append("KNOWN_IDEA")

        hard = [c for c in codes if c in ("NO_DIRECT_SOURCE", "THIN_EVIDENCE",
                                          "NO_PREDICTION", "NO_FALSIFICATION")]
        # MODERATE ka darwaza sirf tab khulta hai jab full text bhi padha ho aur
        # counter-side search bhi chali ho. Warna "moderate confidence" ka matlab
        # "humne dono taraf dekha" ho jaata — jo sach nahi hota.
        blocked = any(c in codes for c in ("NO_COUNTER_SEARCH", "SHALLOW_ACCESS"))
        if hard:
            band = CONF_VERY_LOW
        elif plus >= 2 and deep >= 2 and not blocked:
            band = CONF_MODERATE
        else:
            band = CONF_LOW

        why_bits = [CONF_REASON_CODES[c] for c in codes if c in CONF_REASON_CODES]
        why = (f"Band {band} — " + "; ".join(why_bits[:4])
               + ". Ye number nahi hai aur proof nahi hai: reasoning ka level hai.")
        return ConfidenceAssessment(band=band, reason_codes=codes, why=why,
                                    model_said=(h.confidence or "").strip()[:80])

    # ── report ───────────────────────────────────────────────────────────────
    # Ye do warnings pehle se apni alag line mein chhapti hain, isliye
    # `missing_fields` wali consolidated line mein dobara nahi aani chahiye —
    # warna user ko ek hi kami do baar dikhti hai.
    _ALREADY_REPORTED = {"iske khilaf ka evidence (counter-evidence)"}

    def honesty_check(self, hypotheses: List[Hypothesis]) -> List[str]:
        """Spec Section 10/11 — jo hypothesis untestable/adhoori hai, usko flag karo."""
        warnings: List[str] = []
        for i, h in enumerate(hypotheses, 1):
            if not h.is_testable:
                warnings.append(
                    f"Hypothesis {i} ke saath concrete test design nahi hai — "
                    "isliye ye sirf speculation ke level pe hai.")
            if not h.has_prediction:
                warnings.append(
                    f"Hypothesis {i} ke saath testable prediction nahi hai — "
                    "'agar sach hai to kya dikhega' ke bina ise galat sabit "
                    "karna bhi possible nahi.")
            if not h.contradicting_evidence:
                warnings.append(
                    f"Hypothesis {i} ke against koi evidence list nahi hui — "
                    "self-falsification adhoora hai.")
            if len((h.simple or "").strip()) < 40:
                # Ye "galti" nahi hai, par user-facing quality ki kami hai:
                # sirf ek-line statement se padhne wale ko idea samajh nahi aata.
                warnings.append(
                    f"Hypothesis {i} ka simple-language explanation nahi aaya — "
                    "isliye ise aam bhasha mein samjhaya nahi ja saka, sirf "
                    "technical statement hai.")
            # point 11: spec ki CHHE zaroori cheezein. Jo bachi hui kami hai wo
            # ek hi line mein, naam le kar — "adhoori hai" bolna kaafi nahi,
            # user ko pata hona chahiye KYA missing hai.
            rest = [m for m in h.missing_fields if m not in self._ALREADY_REPORTED]
            if rest:
                warnings.append(
                    f"Hypothesis {i} adhoori hai — ye cheezein nahi aayi: "
                    f"{', '.join(rest)}.")
            # ── §14/§16/§2 ke naye check ─────────────────────────────────────
            # 1. "duniya me pehli"/"discovery" jaisa shabd kabhi allowed nahi.
            banned = forbidden_novelty_phrases(h.statement, h.novelty, h.simple,
                                               h.reasoning, h.if_true)
            if banned:
                warnings.append(
                    f"Hypothesis {i} ke text me aisa daawa hai jo app kar hi nahi "
                    f"sakti ({', '.join(banned[:3])}) — ise novelty ka saboot mat "
                    "maano, ye sirf shabd hai.")
            # 2. Jaana-pehchana idea ko nayi soch batana mana hai.
            known = known_idea_hits(h.statement, h.mechanism, h.novelty)
            if known and re.search(r"\bnovel|nayi|new idea|pehli baar\b",
                                   (h.novelty or "") + " " + (h.statement or ""),
                                   re.IGNORECASE):
                warnings.append(
                    f"Hypothesis {i} ko 'nayi' nahi kaha ja sakta — "
                    f"{known[0]['why_known']}.")
            # 3. Adhoora test plan ko falsification kehna hi pichhli galti thi.
            # honesty_check `enrich()` par depend nahi karta: agar structured
            # record pehle se nahi bana, to yahin bana ke dekhte hain. Warna
            # sirf parse karke check karne par poora-poora plan bhi galti se
            # "ek line ka plan" ban jaata tha.
            struct = h.experiment_struct
            if struct is None and h.experiment_plan:
                struct = self._parse_experiment(
                    h.experiment_plan, falsification=h.falsification_test,
                    prediction=h.prediction, prediction_text=h.prediction_text)
            if struct is not None and struct.missing:
                warnings.append(
                    f"Hypothesis {i} ka test plan adhoora hai — ye hisse nahi "
                    f"aaye: {', '.join(struct.missing[:4])}. "
                    "Isliye ise poora falsification test nahi maana ja sakta.")
            elif struct is None and h.experiment_plan:
                warnings.append(
                    f"Hypothesis {i} ka test plan sirf ek line hai (kya naapenge, "
                    "kis par, kaunsa nateeja galat sabit karega — kuch structured "
                    "nahi mila).")
            # 4. §2 — safety-sensitive baat par risks likhna compulsory hai.
            if h.safety_sensitive and len((h.risks or "").strip()) < 15:
                warnings.append(
                    f"Hypothesis {i} medical/chemical/biological ya safety se judi "
                    "hai par risks/safety checks nahi likhe gaye — is haalat me ise "
                    "aage badhana galat hoga.")
            # 5. Confidence me number likhna mana hai (band hi chalega).
            if re.search(r"\d{1,3}\s?%", h.confidence or ""):
                warnings.append(
                    f"Hypothesis {i} ki confidence me percentage likha tha — "
                    "hataya gaya, kyunki uske peeche koi calculation nahi hai. "
                    "Sirf band (VERY LOW/LOW/MODERATE/HIGH) hi imaandaar hai.")
        return warnings

    # ── evidence gate wrapper ────────────────────────────────────────────────
    def gate(self, pack: Optional[EvidencePack], requested: int = 0,
             contradictions: Optional[List[Dict]] = None) -> EvidenceGate:
        """
        `evidence_gate()` ka convenience wrapper, taaki orchestrator ko module
        se alag function import na karna pade (aur test bhi engine ke through
        hi ho jaaye).
        """
        return evidence_gate(pack, requested=requested,
                             contradictions=contradictions)

    # ── point 10: LLM ke BINA bhi kaam ka output ──────────────────────────────
    # Purana behaviour: quota khatam ho jaaye to hypothesis section mein khaali
    # template chala jaata tha ("## Hypothesis 1 - Statement:" jaisa dhaancha
    # bina content). Wo do tarah se bura tha — dikhta jhootha tha, aur user ko
    # kuch kaam ka nahi milta tha.
    #
    # Ab, LLM na ho to system KHUD ek research plan banata hai — sirf usi cheez
    # se jo asal mein retrieve hui: open questions, kaun source kis level tak
    # padha gaya, kaun takraav khula reh gaya. Ye hypothesis NAHI hai aur khud
    # ko hypothesis bolta bhi nahi. Koi API, koi model, ₹0.
    def open_questions(self, question: str, pack: Optional[EvidencePack] = None,
                       contradictions: Optional[List[Dict]] = None,
                       plan: Optional[Dict] = None) -> List[str]:
        """Wo sawaal jo retrieve hui cheezon se HAL nahi hue (deterministic)."""
        out: List[str] = []
        conflicts = list(contradictions or [])
        for c in conflicts[:4]:
            summary = str(c.get("summary") or "").strip()
            if summary:
                out.append(f"{summary} — ye takraav evidence se tay nahi hua.")

        sources = list(getattr(pack, "sources", []) or []) if pack is not None else []
        usable = [s for s in sources
                  if float(getattr(s, "relevance_score", 0.0) or 0.0) >= _GATE_MIN_RELEVANCE
                  and not str(getattr(s, "rejected_reason", "") or "").strip()]
        shallow = [s for s in usable
                   if (s.reading_level() if hasattr(s, "reading_level") else "")
                   in ("metadata", "snippet")]
        if shallow:
            names = ", ".join((getattr(s, "title", "") or "")[:60]
                              for s in shallow[:3])
            out.append(
                f"{len(shallow)} relevant source ka poora text nahi mil paaya "
                f"(sirf title/snippet tak pahunch bani): {names} — inka full "
                "text padhe bina inke andar ka data claim nahi kiya ja sakta.")
        if not usable and sources:
            out.append(
                f"{len(sources)} result mile par ek bhi is sawaal se juda nahi "
                "nikla — matlab search terms ya connectors badalne padenge.")
        if not sources:
            out.append("Is sawaal par ek bhi source retrieve nahi hua — "
                       "pehla kaam retrieval theek karna hai, hypothesis nahi.")

        for sub in list((plan or {}).get("sub_questions") or [])[:4]:
            sub = str(sub).strip()
            if sub and sub.lower() != (question or "").strip().lower():
                out.append(f"Ye hissa khula hai: {sub}")

        # duplicate hatao, order rakho
        seen, unique = set(), []
        for item in out:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique[:8]

    def fallback_plan(self, question: str, pack: Optional[EvidencePack] = None,
                      contradictions: Optional[List[Dict]] = None,
                      gate: Optional[EvidenceGate] = None,
                      plan: Optional[Dict] = None) -> Dict:
        """
        LLM available na ho (quota/network/error) tab ka deterministic output.

        Lautata hai: `questions` (khule sawaal), `steps` (agla kaam), `note`
        (evidence ki asli ginti) aur `text` (report mein chhapne layak block).
        `is_hypothesis` hamesha False — isse synthesizer galti se ise hypothesis
        ki jagah nahi rakh sakta.
        """
        gate = gate if gate is not None else evidence_gate(
            pack, contradictions=contradictions)
        questions = self.open_questions(question, pack, contradictions, plan)

        steps: List[str] = []
        if gate.total_sources and not gate.relevant_sources:
            steps.append(
                "Search dobara chalao — is baar sawaal ke asli technical terms "
                "aur field-specific sources par, kyunki jo mile wo topic se "
                "match hi nahi kar rahe.")
        if gate.relevant_sources and gate.full_text_sources == 0:
            steps.append(
                "Kam se kam 2 relevant sources ka POORA text nikaalo "
                "(preprint/open-access version, ya PDF ka page-by-page read) — "
                "abstract se claim confirm nahi hota.")
        if gate.contradictions:
            steps.append(
                f"{gate.contradictions} takraav wale sources ka method "
                "side-by-side rakho: sample, condition aur measurement compare "
                "karo — aksar takraav method ka hota hai, nateeje ka nahi.")
        fields = ", ".join(list((plan or {}).get("relevant_fields") or [])[:3])
        if fields:
            steps.append(f"Jo fields is sawaal se jude hain ({fields}) — unme se "
                         "har ek ka ek strong source alag se dhoondo, taaki ek "
                         "hi angle par poora jawab na tike.")
        steps.append(
            "Jab evidence itna ho jaaye ki dono taraf ki baat saamne ho, tab "
            "hypothesis banao — usse pehle banayi hui hypothesis andaaza hoti hai.")

        note = (f"Ginti: {gate.relevant_sources} relevant source, "
                f"{gate.deep_sources} abstract-ya-usse-gehre, "
                f"{gate.full_text_sources} full text, "
                f"{gate.contradictions} takraav.")

        return {
            "is_hypothesis": False,
            "reason": gate.reason,
            "questions": questions,
            "steps": steps[:6],
            "note": note,
            "gate": gate.to_dict(),
            "text": self._render_fallback(questions, steps[:6], note, gate),
        }

    @staticmethod
    def _render_fallback(questions: List[str], steps: List[str], note: str,
                         gate: EvidenceGate) -> str:
        # Do bilkul alag haalat hain, aur inhe mila dena jhooth ban jaata hai:
        #   * evidence hi patla tha  -> wajah gate ki ginti hai
        #   * evidence theek tha par model/quota ne saath nahi diya -> tab gate
        #     ki "kaafi source hain" wali line ko WAJAH ki tarah likhna galat
        #     hoga (upar section pehle se asli wajah bata raha hota hai).
        if gate.sufficient:
            head = ("**Nayi hypothesis is run mein nahi ban paayi** — evidence "
                    "iske layak tha, kami reasoning pass mein rahi.")
        else:
            head = ("**Nayi hypothesis is baar nahi banayi gayi.** "
                    + (gate.reason or "Evidence itna nahi tha ki nayi hypothesis "
                                      "banayi ja sake."))
        lines = [
            head,
            "",
            "Iski jagah system ne khud ek research plan banaya hai — ye AI ki "
            "hypothesis NAHI hai, sirf wahi baat hai jo mile hue sources se "
            "seedha nikalti hai:",
        ]
        if questions:
            lines.append("")
            lines.append("**Ab tak jo sawaal khule hain:**")
            lines.extend(f"- {q}" for q in questions)
        if steps:
            lines.append("")
            lines.append("**Aage ka kaam (isi kram mein):**")
            lines.extend(f"{i}. {s}" for i, s in enumerate(steps, 1))
        lines.append("")
        lines.append(f"_{note}_")
        return "\n".join(lines)
