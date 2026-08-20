"""
Source ka ASLI kind — §6.

Bug jo isse theek hota hai: kind connector se decide ho raha tha. Zenodo par
mila hua "High-Temperature Superconductors: Recent Advances in Cuprate,
Iron-Based, and Nickelate Systems" ek REVIEW hai, par report ne use
"dataset (raw numbers)" likh diya, kyunki zenodo ka connector class-level par
DATASET set karta hai. Isi tarah har Crossref/DOI result "research paper" ban
jaata tha — editorial, comment, book chapter, thesis, sab.

Ab kind title + snippet + venue + publisher + URL + connector, sabko dekh kar
banta hai, aur pata na ho to imaandaari se UNKNOWN rehta hai. Ye field purane
`source_type` ko HATATA nahi hai (wo routing/dedup mein use hota hai) — uske
saath ek zyada sach bolne wala label jodta hai.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# §6 ki poori list. "unknown" jaan-boojh kar allowed hai.
KINDS = (
    "peer_reviewed_article", "review_article", "preprint", "news_editorial",
    "comment_criticism", "dataset", "book", "book_chapter",
    "government_report", "conference_paper", "patent", "thesis", "software",
    "unknown",
)

LABELS: Dict[str, str] = {
    "peer_reviewed_article": "peer-reviewed research article",
    "review_article": "review article",
    "preprint": "preprint (peer review baaki)",
    "news_editorial": "news / editorial",
    "comment_criticism": "comment / criticism",
    "dataset": "dataset (raw numbers)",
    "book": "book",
    "book_chapter": "book chapter",
    "government_report": "government / agency report",
    "conference_paper": "conference paper",
    "patent": "patent",
    "thesis": "thesis",
    "software": "software / code",
    "unknown": "type pata nahi (UNKNOWN)",
}

_RE = {
    "review": re.compile(
        r"\b(a|this|comprehensive|systematic|critical|brief|short|narrative|"
        r"literature)?\s*review\b|\bsurvey of\b|\boverview of\b|"
        r"\bstate of the art\b|\bmeta[- ]analysis\b", re.I),
    "dataset": re.compile(
        r"\b(data\s?set|dataset|raw data|data file|data repositor|"
        r"csv|tabular data|data collection|indicator|time series)\b", re.I),
    "software": re.compile(
        r"\b(software|source code|python package|library release|"
        r"github|version v?\d+\.\d+|toolkit|codebase)\b", re.I),
    "thesis": re.compile(
        r"\b(thesis|dissertation|partial fulfil?lment|doctoral|"
        r"master'?s degree|phd submitted)\b", re.I),
    "patent": re.compile(r"\b(patent|claims?\s+\d+\s*[-–]\s*\d+|uspto|wipo)\b", re.I),
    "conference": re.compile(
        r"\b(proceedings|conference|symposium|workshop|icml|neurips|"
        r"aps march meeting)\b", re.I),
    "chapter": re.compile(r"\b(chapter|in:\s|handbook of|encyclopedia of)\b", re.I),
    "editorial": re.compile(
        r"\b(editorial|op-?ed|news|press release|blog|interview|"
        r"correspondence|feature article)\b", re.I),
    "comment": re.compile(
        r"\b(comment on|reply to|response to|matters arising|"
        r"critique of|rebuttal|retraction note|expression of concern)\b", re.I),
    "gov": re.compile(
        r"\b(ministry|department of|agency|commission|bureau|"
        r"national health accounts|white paper|official statistics)\b", re.I),
    "presentation": re.compile(r"\b(slides|presentation|poster|talk given)\b", re.I),
}

_PREPRINT_HOSTS = ("arxiv.org", "biorxiv.org", "medrxiv.org", "chemrxiv",
                   "ssrn.com", "preprints.org", "osf.io", "hal.science")
_GOV_HOSTS = ("who.int", "worldbank.org", "oecd.org", "europa.eu", "un.org",
              "data.gov", "nih.gov", "cdc.gov", "nist.gov", "energy.gov")
_NEWS_HOSTS = ("nature.com/news", "sciencemag.org/news", "bbc.", "reuters.",
               "nytimes.", "theguardian.", "sciencealert.", "phys.org",
               "livescience.", "newscientist.")
_SOFTWARE_HOSTS = ("github.com", "gitlab.com", "pypi.org", "huggingface.co")


@dataclass
class KindVerdict:
    kind: str = "unknown"
    confidence: str = "low"        # "high" | "medium" | "low"
    reason: str = ""

    @property
    def label(self) -> str:
        return LABELS.get(self.kind, self.kind)

    def to_dict(self) -> Dict:
        return {"kind": self.kind, "label": self.label,
                "confidence": self.confidence, "reason": self.reason}


def classify(title: str = "", snippet: str = "", url: str = "",
             connector: str = "", venue: str = "", publisher: str = "",
             doi: str = "", peer_reviewed: Optional[bool] = None,
             full_text: str = "") -> KindVerdict:
    """
    Content + metadata se kind nikaalo. Order maayne rakhta hai: sabse pehle
    wo signals jo galat nahi ho sakte (URL host, patent), phir content ke
    patterns, phir metadata se andaza. Kuch pakka na ho to UNKNOWN.
    """
    t = title or ""
    s = snippet or ""
    body = f"{t}\n{s}\n{(full_text or '')[:4000]}"
    u = (url or "").lower()
    conn = (connector or "").lower()
    ven = f"{venue or ''} {publisher or ''}"

    def hit(key: str, *texts: str) -> bool:
        rx = _RE[key]
        return any(rx.search(x or "") for x in texts)

    # 1. URL host — sabse bharosemand
    if any(h in u for h in _SOFTWARE_HOSTS) and conn != "huggingface":
        return KindVerdict("software", "high", "code/repository host")
    if "patents.google" in u or hit("patent", t):
        return KindVerdict("patent", "high", "patent signal")
    if any(h in u for h in _PREPRINT_HOSTS) or conn in ("arxiv",):
        # arXiv par review bhi hota hai — content dekh kar batao
        if hit("review", t):
            return KindVerdict("review_article", "medium",
                               "preprint server par review article")
        return KindVerdict("preprint", "high", "preprint server")
    if any(h in u for h in _NEWS_HOSTS) or hit("editorial", t):
        return KindVerdict("news_editorial", "medium", "news/editorial signal")

    # 2. Content patterns — connector se PEHLE (yahi §6 ka asli fix hai)
    if hit("comment", t):
        return KindVerdict("comment_criticism", "high", "comment/reply title")
    if hit("thesis", t, s):
        return KindVerdict("thesis", "medium", "thesis/dissertation signal")
    if hit("review", t):
        return KindVerdict("review_article", "high", "title kehta hai review/survey")
    if hit("chapter", t):
        return KindVerdict("book_chapter", "medium", "chapter signal")
    if hit("conference", t, ven):
        return KindVerdict("conference_paper", "medium", "proceedings/conference")

    # 3. Repository jaise zenodo — content hi batayega
    if conn in ("zenodo", "data_gov", "data_gov_in", "figshare", "dryad"):
        if hit("review", s):
            return KindVerdict("review_article", "medium",
                               "repository item apne aap ko review kehta hai")
        if hit("software", t, s):
            return KindVerdict("software", "medium", "repository software record")
        if hit("presentation", t, s):
            return KindVerdict("unknown", "low",
                               "repository item presentation/slides lagta hai")
        if hit("dataset", t, s) or conn != "zenodo":
            return KindVerdict("dataset", "medium", "repository dataset record")
        return KindVerdict("unknown", "low",
                           "zenodo record — kind metadata se pakka nahi hua")
    if conn in ("who_gho", "world_bank"):
        return KindVerdict("dataset", "high", "official statistics API")
    if conn == "huggingface":
        return KindVerdict("dataset", "medium", "model/dataset hub record")
    if conn in ("google_books", "open_library", "internet_archive"):
        return KindVerdict("book", "medium", "book catalogue")
    if hit("gov", t, s, ven) or any(h in u for h in _GOV_HOSTS):
        return KindVerdict("government_report", "medium", "agency/government source")
    if hit("dataset", t) and not hit("review", t):
        return KindVerdict("dataset", "medium", "title kehta hai dataset")

    # 4. Metadata se andaza — sirf tab jab sach mein journal ka nishan ho
    if doi and ven.strip():
        if peer_reviewed is True:
            return KindVerdict("peer_reviewed_article", "medium",
                               "DOI + journal + peer-review signal")
        return KindVerdict("peer_reviewed_article", "low",
                           "DOI + journal naam (peer review confirm nahi)")
    if conn in ("wikipedia",):
        return KindVerdict("unknown", "low", "encyclopedia entry")
    return KindVerdict("unknown", "low", "kind ka koi bharosemand signal nahi mila")
