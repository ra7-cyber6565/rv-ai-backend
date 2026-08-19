"""
QualitySignals — Spec Section 7 ke bache hue signals

Spec Section 7 source-quality ke liye 10 cheezein maangta hai. Jo pehle se
kahin thi, wo yahan likhi hai — taaki agli baar audit karne par pata rahe ki
kaam kahan hua:

    1. primary vs secondary   -> SourceRecord.is_primary
    2. peer-reviewed ya nahi  -> SourceRecord.peer_reviewed (connectors bharte hain)
    3. publication date       -> SourceRecord.year
    4. source authority       -> relevance.py ke domain tiers
    5. independence           -> SourceRecord.independence_key + dedup
    6. citation count         -> SourceRecord.citation_count
    7. methodology strength   -> IS FILE MEIN (methodology)
    8. replication status     -> IS FILE MEIN (replication)
    9. retraction status      -> IS FILE MEIN (retracted)
   10. conflict of interest   -> IS FILE MEIN (coi_disclosed / funding_disclosed)

IMAANDAAR LIMITS (free APIs se aage nahi ja sakte, isliye jhooth nahi bologe):

  * Methodology tier publication TYPE se nikalta hai — PubMed ka `pubtype`,
    Crossref ka `type`, ya title/abstract mein likha explicit design naam.
    Ye "poori methods section padhne" ke barabar NAHI hai. Sample size,
    blinding, dropout — inka pata sirf full text se chalta hai.
  * Retraction: PubMed ka "Retracted Publication" pubtype aur Crossref ka
    `update-to` free mein milte hain. Retraction Watch ka poora database yahan
    nahi hai. Isliye `retracted=None` ka matlab hai "retraction ka koi signal
    nahi mila" — "ye paper retracted nahi hai" NAHI.
  * COI/funding: ye statements sirf full text mein hoti hain, abstract mein
    nahi. Isliye jab tak ContentFetcher ne full text download nahi kiya, in
    dono ka jawab None (pata nahi) rehta hai.

Design rule: har function ya to PAKKA signal deta hai, ya None / "" —
andaza kabhi nahi. Isi wajah se ye poora module offline testable hai, koi
network call nahi.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:                      # runtime par import nahi — circular na ho
    from .models import SourceRecord


# ── methodology (Spec Section 7, signal #7) ──────────────────────────────────
# Rank = evidence design ki strength. Ye medical evidence pyramid ka simple
# version hai. Zyada rank = design se hi zyada bharosa, par phir bhi ek hi
# study "proof" nahi hoti.
METHODOLOGY_RANK: Dict[str, int] = {
    "meta_analysis": 6,
    "systematic_review": 6,
    "rct": 5,
    "clinical_trial": 4,
    "guideline": 4,
    "cohort": 3,
    "case_control": 3,
    "cross_sectional": 2,
    "observational": 2,
    "modelling": 2,
    "case_report": 1,
    "qualitative": 1,
    "narrative_review": 1,
    "opinion": 0,
}
STRONG_METHODOLOGY = 5      # isse upar/barabar = strong design
WEAK_METHODOLOGY = 1        # isse neeche/barabar = kamzor design

METHODOLOGY_LABELS: Dict[str, str] = {
    "meta_analysis": "meta-analysis (kai studies ka pooled result)",
    "systematic_review": "systematic review",
    "rct": "randomized controlled trial",
    "clinical_trial": "clinical trial",
    "guideline": "official practice guideline",
    "cohort": "cohort study",
    "case_control": "case-control study",
    "cross_sectional": "cross-sectional / survey",
    "observational": "observational study",
    "modelling": "simulation / computational model",
    "case_report": "case report ya case series",
    "qualitative": "qualitative study",
    "narrative_review": "narrative review",
    "opinion": "editorial / opinion (research nahi)",
}


def _phrase_re(*phrases: str) -> "re.Pattern":
    """
    Phrases ko word-boundary wale regex mein badlo.

    Plain `in` check yahan galat hota: "phase i" substring "phase inversion"
    mein bhi mil jaata aur ek material-science paper clinical trial ban jaata.
    """
    body = "|".join(re.escape(p) for p in phrases)
    return re.compile(r"(?<!\w)(?:" + body + r")(?!\w)", re.IGNORECASE)


# Order maayne rakhta hai: pehla match jeetega, isliye sabse specific pehle.
# "systematic review and meta-analysis" ko meta_analysis milna chahiye,
# narrative_review nahi.
_TEXT_METHODOLOGY = (
    ("meta_analysis", _phrase_re("meta-analysis", "meta analysis", "metaanalysis",
                                 "pooled analysis", "network meta-analysis")),
    ("systematic_review", _phrase_re("systematic review", "scoping review",
                                     "umbrella review", "systematic literature review")),
    ("rct", _phrase_re("randomized controlled trial", "randomised controlled trial",
                       "randomized clinical trial", "randomised clinical trial",
                       "randomized trial", "randomised trial", "double-blind",
                       "double blind", "placebo-controlled", "placebo controlled")),
    ("clinical_trial", _phrase_re("clinical trial", "phase i", "phase ii", "phase iii",
                                  "phase 1 trial", "phase 2 trial", "phase 3 trial",
                                  "open-label trial", "single-arm trial")),
    ("guideline", _phrase_re("practice guideline", "clinical guideline",
                             "consensus statement", "consensus guideline")),
    ("cohort", _phrase_re("cohort study", "prospective cohort", "retrospective cohort",
                          "longitudinal study", "birth cohort")),
    ("case_control", _phrase_re("case-control", "case control study",
                                "nested case-control")),
    ("cross_sectional", _phrase_re("cross-sectional", "cross sectional",
                                   "questionnaire survey", "survey study",
                                   "prevalence survey")),
    ("modelling", _phrase_re("simulation study", "in silico", "computational model",
                             "monte carlo", "agent-based model", "mathematical model",
                             "molecular docking")),
    ("qualitative", _phrase_re("qualitative study", "focus group", "focus groups",
                               "semi-structured interview", "semi-structured interviews",
                               "thematic analysis", "ethnographic")),
    ("case_report", _phrase_re("case report", "case reports", "case series")),
    # Sabse kamzor do tiers mein SIRF wo phrases hain jo apne aap ke baare mein
    # hoti hain. "editorial", "commentary", "literature review" jaise aam shabd
    # jaan-boojh kar hata diye: koi news page incidentally "commentary" likh de
    # to use "opinion (research nahi)" ka thappa lagana galat hoga. Wo shabd
    # pubtype list mein hain, jahan API khud bata rahi hoti hai.
    ("narrative_review", _phrase_re("narrative review", "review article",
                                    "this review", "we review", "in this review")),
    ("opinion", _phrase_re("opinion piece", "letter to the editor",
                           "editorial comment", "guest editorial")),
)

# PubMed `pubtype` -> methodology. PubMed ki apni vocabulary hai (MeSH
# publication types), isliye ise text patterns se alag rakha hai.
#
# Semantic Scholar ke `publicationTypes` bhi isi map se guzarte hain, par wo
# camelCase mein aate hain ("MetaAnalysis", "ClinicalTrial", "CaseReport",
# "LettersAndComments"). Lowercase karne ke baad unme space nahi hota, isliye
# har jagah space-wala aur bina-space wala DONO variant likha hai — warna
# Semantic Scholar ke saare types chup-chaap "" ban jaate.
_PUBTYPE_METHODOLOGY = (
    ("meta_analysis", ("meta-analysis", "metaanalysis")),
    ("systematic_review", ("systematic review", "systematicreview")),
    ("rct", ("randomized controlled trial", "randomised controlled trial",
             "randomizedcontrolledtrial")),
    ("clinical_trial", ("clinical trial", "clinicaltrial", "controlled clinical trial",
                        "adaptive clinical trial", "pragmatic clinical trial",
                        "equivalence trial", "clinical study")),
    ("guideline", ("practice guideline", "guideline",
                   "consensus development conference")),
    ("observational", ("observational study", "comparative study",
                       "multicenter study", "validation study")),
    ("case_report", ("case reports", "case report", "casereport")),
    ("narrative_review", ("review", "scientific integrity review")),
    ("opinion", ("editorial", "comment", "letter", "lettersandcomments", "news",
                 "newspaper article", "interview", "biography", "address",
                 "lecture", "preprint")),
)

# Crossref/OpenAlex `type` -> methodology. Ye publication FORM batate hain
# (journal-article, book-chapter...), study design nahi. Isliye sirf wahi map
# kiya hai jo saaf hai; "journal-article" ka koi design matlab nahi hota, use
# jaan-boojh kar chhoda gaya hai taaki text/pubtype signal ko jagah mile.
_WORKTYPE_METHODOLOGY = {
    "editorial": "opinion",
    "letter": "opinion",
    "comment": "opinion",
    "erratum": "opinion",
    "review": "narrative_review",
    "review-article": "narrative_review",
    "book-review": "narrative_review",
    "standard": "guideline",
    "report": "observational",
    "dataset": "observational",
}


def methodology_from_pubtypes(pubtypes) -> str:
    """PubMed pubtype list -> controlled-vocab methodology (ya "")."""
    types = [str(t).strip().lower() for t in (pubtypes or []) if str(t).strip()]
    if not types:
        return ""
    for label, needles in _PUBTYPE_METHODOLOGY:
        for needle in needles:
            if any(needle == t or needle in t for t in types):
                return label
    return ""


def methodology_from_work_type(work_type: str) -> str:
    """Crossref/OpenAlex `type` -> methodology (ya "" jab type se kuch pata na chale)."""
    key = str(work_type or "").strip().lower()
    return _WORKTYPE_METHODOLOGY.get(key, "")


def methodology_from_text(text: str) -> str:
    """Title/abstract mein likha explicit study design (ya "")."""
    body = str(text or "")
    if not body.strip():
        return ""
    for label, pattern in _TEXT_METHODOLOGY:
        if pattern.search(body):
            return label
    return ""


def methodology_rank(methodology: str) -> int:
    """Unknown methodology ka rank -1 — yaani 'pata nahi', 0 (opinion) se alag."""
    return METHODOLOGY_RANK.get(str(methodology or "").strip().lower(), -1)


def methodology_label(methodology: str) -> str:
    key = str(methodology or "").strip().lower()
    return METHODOLOGY_LABELS.get(key, key.replace("_", " "))


# ── retraction (Spec Section 7, signal #9) ───────────────────────────────────
# Title ki SHURUAAT mein hi dekhte hain. Beech mein match karna bug hota:
# "Trends in the retraction of cancer papers" ek normal bibliometrics paper hai,
# retracted nahi.
_RETRACT_TITLE = re.compile(
    r"^\s*[\[\(]?\s*(?:retracted(?:\s+article)?|retraction(?:\s+notice)?|"
    r"withdrawn(?:\s+article)?|withdrawal(?:\s+notice)?|"
    r"expression\s+of\s+concern|this\s+article\s+has\s+been\s+retracted)\b",
    re.IGNORECASE,
)


def retraction_from_pubtypes(pubtypes) -> Optional[bool]:
    """
    PubMed pubtype se retraction signal.

    True = signal mila. None = signal NAHI mila (iska matlab "clean hai" nahi —
    PubMed retraction notices ko index karne mein waqt leta hai).
    """
    types = [str(t).strip().lower() for t in (pubtypes or []) if str(t).strip()]
    if any("retract" in t for t in types):
        return True
    return None


def retraction_from_text(title: str) -> Optional[bool]:
    return True if _RETRACT_TITLE.search(str(title or "")) else None


def retraction_from_crossref(item: Dict) -> Optional[bool]:
    """
    Crossref do tarah se batata hai:
      * `type == "retraction"` / `"withdrawal"`  -> ye record khud notice hai
      * `update-to: [{type: "retraction", ...}]` -> ye record kisi doosre kaam ko
        retract kar raha hai, yaani ye bhi retraction notice hai
      * `updated-by: [{type: "retraction", ...}]` -> IS kaam ko retract kiya gaya

    Teeno case mein hum True bolte hain, par matlab ek hi hai jo report mein
    likha jaata hai: "ye record retraction se juda hai — normal evidence ki
    tarah mat use karo." Kaun-kis-ko retract kiya, wo free metadata se hamesha
    saaf nahi hota, isliye us se zyada dava nahi karte.
    """
    if not isinstance(item, dict):
        return None
    work_type = str(item.get("type") or "").strip().lower()
    if work_type in ("retraction", "withdrawal", "retracted-article"):
        return True
    for key in ("update-to", "updated-by"):
        for entry in item.get(key) or []:
            if isinstance(entry, dict) and "retract" in str(entry.get("type") or "").lower():
                return True
            if isinstance(entry, dict) and "withdraw" in str(entry.get("type") or "").lower():
                return True
    return None


# ── replication (Spec Section 7, signal #8) ──────────────────────────────────
_REPLICATION_RE = _phrase_re(
    "replication study", "replication of", "replicated", "replication attempt",
    "direct replication", "conceptual replication", "reproducibility",
    "reproducible", "independent validation", "external validation",
    "multi-site study", "multisite study", "pre-registered replication",
    "failed to replicate", "we replicate",
)

REPLICATION_LABELS = {
    "evidence_synthesis": "kai studies ka synthesis (replication andar shamil)",
    "replication_signal": "text mein replication/validation ka zikr hai "
                          "(guarantee nahi — sirf zikr)",
}


def replication_status(methodology: str, text: str) -> str:
    """
    Bahut soch-samajh kar kamzor rakha gaya hai. "Is study ko kitni baar
    replicate kiya gaya" ka jawab free metadata mein bilkul nahi hai — uske
    liye poore citation graph ko padhna padta. Isliye do hi imaandaar jawab:
        "evidence_synthesis" -> ye khud kai studies ko jodta hai
        "replication_signal" -> is text mein replication/validation ka zikr hai
    Warna "" (pata nahi).
    """
    if methodology in ("meta_analysis", "systematic_review"):
        return "evidence_synthesis"
    return "replication_signal" if _REPLICATION_RE.search(str(text or "")) else ""


def replication_label(status: str) -> str:
    key = str(status or "").strip().lower()
    return REPLICATION_LABELS.get(key, key.replace("_", " "))


# ── conflict of interest + funding (Spec Section 7, signal #10) ──────────────
_COI_RE = _phrase_re(
    "conflict of interest", "conflicts of interest", "competing interest",
    "competing interests", "declaration of interest", "declaration of interests",
    "declaration of competing interest", "disclosure statement",
    "financial disclosure", "disclosures", "coi statement",
)
_FUNDING_RE = _phrase_re(
    "funding", "funded by", "funding statement", "financial support",
    "grant number", "grant no", "supported by a grant", "supported by grants",
    "funding source", "funding sources", "research support",
)
# Itne chhote text mein COI/funding section hi nahi hota — abstract par
# "COI nahi mila" bolna technically sach par bekaar aur misleading hai.
_MIN_FULLTEXT_FOR_COI = 1500


def coi_from_full_text(text: str) -> Optional[bool]:
    """
    True  = full text mein COI/competing-interest statement mila
    False = full text mila par aisa koi statement nahi tha
    None  = full text hi nahi mila (ya bahut chhota) — pata nahi
    """
    body = str(text or "")
    if len(body.strip()) < _MIN_FULLTEXT_FOR_COI:
        return None
    return bool(_COI_RE.search(body))


def funding_from_full_text(text: str) -> Optional[bool]:
    """COI se alag signal: paisa kahan se aaya, ye likha hai ya nahi."""
    body = str(text or "")
    if len(body.strip()) < _MIN_FULLTEXT_FOR_COI:
        return None
    return bool(_FUNDING_RE.search(body))


# ── record enrichment (ek hi jagah, taaki har source ko same treatment mile) ──
def enrich_record(record: "SourceRecord") -> "SourceRecord":
    """
    Jo signal connector ne bhar diya, use CHHEDTE NAHI — connector ke paas API
    ka structured field hota hai, jo title-guess se hamesha behtar hai. Sirf
    khaali jagah bharte hain, title+snippet se.

    Ye RelevanceEngine.rank() ke andar har source par chalta hai, isliye chahe
    source kis bhi connector se aaya ho, signals ek jaise nikalte hain.
    """
    text = f"{record.title} {record.snippet}"
    if not record.methodology:
        record.methodology = methodology_from_text(text)
    if record.retracted is None:
        record.retracted = retraction_from_text(record.title)
    if not record.replication:
        record.replication = replication_status(record.methodology, text)
    return record


def enrich_records(records: List["SourceRecord"]) -> List["SourceRecord"]:
    for record in records or []:
        enrich_record(record)
    return records
