"""
Patent helpers — patent ko first-class source banane ke liye (₹0 patent batch).

Ye file JAAN-BOOJH KAR dependency-free hai (requests / gemini / chromadb kuch
nahi): connector, models, dedup, planner aur offline test — sab ise akele
import kar sakein, bina network aur bina API key.

TEEN HONESTY RULES jo yahin enforce hote hain:

  1. "Missing info ko guess mat karna" — PatentMeta ka har field khaali ho
     sakta hai, aur khaali ka matlab EK HI hai: "provider ne diya nahi". Hum
     legal status / date / assignee kabhi andaaze se nahi bharte. Sirf ek
     cheez derive hoti hai: number ke andar likhi hui jurisdiction aur kind
     code (US9876543B2 mein "US" aur "B2" LIKHA hua hai — ye parsing hai,
     andaaza nahi).

  2. Patent SCIENTIFIC PROOF NAHI hai. Patent ke claims LEGAL dawe hote hain;
     publication ya grant ka matlab "experiment ne sach saabit kar diya" NAHI
     hai. Isliye PATENT_EVIDENCE_NOTE har patent record ke saath chalta hai aur
     claim_labels/consensus_gate patent-only baat ko ESTABLISHED nahi banate.

  3. "Koi patent nahi mila" ka matlab "idea novel hai" NAHI hai — search
     coverage adhoori ho sakti hai. novelty_note() sirf itna kehta hai ki jo
     sources search hue unme prior-art signal mila ya nahi mila; patentability
     ya novelty ki legal opinion kabhi nahi.

FAMILY DEDUP KYUN: ek hi invention US, EP aur WO — teen jagah publish hoti hai.
Teen records ko teen INDEPENDENT evidence ginna galat hoga; wo ek hi dawa hai
teen daftaron mein. family_key() unhe ek hi key par le aata hai, aur wahi key
SourceRecord.independence_key se hokar dedup + independence counting mein
lagti hai (parallel counting path banane ki zaroorat nahi padi).

READ DEPTH KYUN ALAG: patent ka abstract, uske CLAIMS aur uski poori
description — teen bilkul alag gehraiyan hain. "Patent padha" tabhi likhna hai
jab claims ya description sach mein process hue hon, isliye yahan
DEPTH_CLAIMS ek asli level hai (models.READ_LEVEL_ORDER mein bhi jodha gaya).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

# ── read depth (models.READ_LEVEL_ORDER ke naam se match karta hai) ──────────
DEPTH_METADATA = "metadata"
DEPTH_ABSTRACT = "abstract"
DEPTH_CLAIMS = "claims"
DEPTH_FULL = "full_text"

# Itne chars se kam text ko "padha" kehna jhooth hai — patent ke boilerplate
# (title + bibliographic line) hi itna lamba ho jaata hai.
MIN_ABSTRACT_CHARS = 120
MIN_CLAIMS_CHARS = 200
MIN_DESCRIPTION_CHARS = 1200

# Ye line prompt ke andar bhi jaati hai aur audit mein bhi — reasoning model ko
# PEHLE hi pata hona chahiye ki ye legal dawa hai, experiment nahi.
PATENT_EVIDENCE_NOTE = (
    "PATENT = legal document, scientific proof NAHI. Patent ke claims legal "
    "dawe hote hain; publication/grant ka matlab experiment se saabit hona "
    "nahi hai."
)

# Jurisdiction codes — sirf label ke liye. Is dict mein na ho to hum code hi
# dikhate hain, "unknown country" jaisa andaaza nahi lagate.
_JURISDICTION_LABELS = {
    "US": "United States (USPTO)",
    "EP": "European Patent Office (EPO)",
    "WO": "WIPO / PCT",
    "JP": "Japan (JPO)",
    "CN": "China (CNIPA)",
    "KR": "Korea (KIPO)",
    "IN": "India (IPO)",
    "GB": "United Kingdom (UKIPO)",
    "DE": "Germany (DPMA)",
    "FR": "France (INPI)",
    "CA": "Canada (CIPO)",
    "AU": "Australia (IP Australia)",
    "RU": "Russia (Rospatent)",
    "BR": "Brazil (INPI-BR)",
}


# ── number parsing (parsing, not guessing) ───────────────────────────────────
def normalize_number(raw: str) -> str:
    """'US 9,876,543 B2' / 'us-9876543-b2' → 'US9876543B2'."""
    return re.sub(r"[^0-9A-Z]", "", str(raw or "").upper())


def split_number(raw: str) -> Dict[str, str]:
    """
    Patent number ko teen hisson mein todo: jurisdiction / serial / kind code.

    Kind code (A1, B2, ...) publication STAGE batata hai, invention nahi:
    US9876543B1 aur US9876543B2 ek hi patent ke do publication hain. Isliye
    family key mein kind code shaamil NAHI hota — warna ek hi cheez do
    independent evidence gin jaati.
    """
    text = normalize_number(raw)
    if not text:
        return {"jurisdiction": "", "serial": "", "kind": ""}
    jurisdiction = text[:2] if text[:2].isalpha() else ""
    rest = text[2:] if jurisdiction else text
    match = re.match(r"^([0-9]+)([A-Z][0-9]?)?$", rest)
    if match:
        return {"jurisdiction": jurisdiction,
                "serial": match.group(1),
                "kind": match.group(2) or ""}
    return {"jurisdiction": jurisdiction, "serial": rest, "kind": ""}


def jurisdiction_label(code: str) -> str:
    """Label pata ho to label, warna code jaisa hai waisa — koi andaaza nahi."""
    key = str(code or "").strip().upper()
    return _JURISDICTION_LABELS.get(key, key)


def looks_like_patent_number(text: str) -> bool:
    """'EP1234567A1' / 'US 9,876,543 B2' jaisa kuch hai?"""
    candidate = normalize_number(text)
    if len(candidate) < 7 or len(candidate) > 20:
        return False
    return bool(re.match(r"^[A-Z]{2}[0-9]{4,}[A-Z]?[0-9]?$", candidate))


# ── small internal helpers ───────────────────────────────────────────────────
def _val(meta, key: str):
    """PatentMeta ya plain dict — dono se ek hi tareeke se field padho."""
    if isinstance(meta, dict):
        return meta.get(key)
    return getattr(meta, key, None)


def _year_of(value) -> Optional[int]:
    """'2019-04-01' / '2019' / 2019 → 2019. Kuch samajh na aaye to None."""
    text = str(value or "")
    for i in range(max(0, len(text) - 3)):
        chunk = text[i:i + 4]
        if chunk.isdigit() and 1700 <= int(chunk) <= 2100:
            return int(chunk)
    return None


def _date_key(value) -> str:
    """Date se sirf digits — '2019-04-01' aur '20190401' ek hi key banein."""
    return re.sub(r"[^0-9]", "", str(value or ""))[:8]


_SLUG_STOP = {"the", "and", "for", "with", "from", "that", "this", "method",
              "system", "apparatus", "device", "process", "means", "using"}


def _title_slug(title: str, limit: int = 5) -> str:
    """
    Title ke matlab wale shabd — family key ka fallback hissa.

    "method/system/apparatus/device/process" jaise shabd har doosre patent ke
    title mein hote hain, isliye wo slug se bahar hain: warna do bilkul alag
    invention ("method for cooling" vs "method for drying") ek hi family key par
    aa jaate aur hum sach mein independent do sources ko ek gin lete.
    """
    words = re.findall(r"[0-9a-z]+", str(title or "").lower())
    keep = [w for w in words if len(w) >= 4 and w not in _SLUG_STOP]
    return "-".join(keep[:limit])


# ── PatentMeta ───────────────────────────────────────────────────────────────
@dataclass
class PatentMeta:
    """
    Ek patent/publication ka structured metadata.

    HAR field ka default khaali hai, aur khaali ka matlab EK HI hai: "provider
    ne ye nahi diya". Isliye kabhi bhi `legal_status == ""` ko "abandoned" ya
    "active" maan kar report mat karna — status_label() isi baat ko saaf likhta
    hai. Missing fields ki list missing_fields() se milti hai, taaki audit mein
    "kitna pata hai" bhi imaandaari se dikhe.
    """
    number: str = ""                 # publication/patent number, provider ke roop mein
    jurisdiction: str = ""           # "US" | "EP" | "WO" ... (number se parse ho sakta hai)
    kind_code: str = ""              # "A1" | "B2" ... publication stage
    title: str = ""
    inventors: List[str] = field(default_factory=list)
    assignee: str = ""               # applicant / assignee
    filing_date: str = ""
    publication_date: str = ""
    priority_date: str = ""
    family_id: str = ""              # DOCDB/INPADOC simple family id (jab mile)
    cpc: List[str] = field(default_factory=list)
    ipc: List[str] = field(default_factory=list)
    abstract: str = ""
    claims_text: str = ""            # asli claims text (jab process hua ho)
    description_text: str = ""       # asli description/full text (jab process hua ho)
    # Legal status SIRF tab bharo jab reliable source ne diya ho, aur uska
    # source bhi likho — "status kahan se aaya" bina "status" adhoora hai.
    legal_status: str = ""
    legal_status_source: str = ""
    url: str = ""
    provider: str = ""               # "epo_lod" | "uspto_odp" ...

    def __post_init__(self) -> None:
        # Number ke andar jurisdiction aur kind code LIKHE hote hain — inhe
        # nikalna parsing hai, andaaza nahi. Provider ne khud diya ho to uski
        # value ko chhedte nahi.
        parts = split_number(self.number)
        if not self.jurisdiction and parts["jurisdiction"]:
            self.jurisdiction = parts["jurisdiction"]
        if not self.kind_code and parts["kind"]:
            self.kind_code = parts["kind"]

    # ── derived, sab bina andaaze ke ─────────────────────────────────────────
    @property
    def year(self) -> Optional[int]:
        """Publication year pehle; na ho to filing; na ho to priority."""
        for value in (self.publication_date, self.filing_date, self.priority_date):
            got = _year_of(value)
            if got:
                return got
        return None

    def claim_count(self) -> int:
        """
        Claims text mein kitne numbered claims hain (0 = claims text hi nahi).

        Sirf line/segment ki shuruaat mein aaye "1." / "2)" gine jaate hain —
        description ke andar likhe "claim 1" se ginti nahi badhti.
        """
        text = self.claims_text or ""
        if not text.strip():
            return 0
        found = re.findall(r"(?:^|\n)\s*(\d{1,3})\s*[\.\)]", text)
        return len({int(n) for n in found}) or 1

    def read_depth(self) -> str:
        """
        Is patent ko SACH MEIN kitna process kiya — "patent padha" ka imaandaar
        jawab. Description → claims → abstract → metadata, isi tarteeb mein.
        """
        if len((self.description_text or "").strip()) >= MIN_DESCRIPTION_CHARS:
            return DEPTH_FULL
        if len((self.claims_text or "").strip()) >= MIN_CLAIMS_CHARS:
            return DEPTH_CLAIMS
        if len((self.abstract or "").strip()) >= MIN_ABSTRACT_CHARS:
            return DEPTH_ABSTRACT
        return DEPTH_METADATA

    def text_chars(self) -> int:
        """Kul kitne chars asli text ke roop mein aaye (audit ke liye)."""
        return sum(len((t or "").strip()) for t in
                   (self.abstract, self.claims_text, self.description_text))

    def read_note(self) -> str:
        """
        Ek line jo saaf batati hai kya-kya process hua aur kya NAHI.

        "Patent padha" ka dawa isi line se check hota hai: agar yahan
        "claims nahi mile" likha hai, to kisi bhi report mein "patent ke claims
        ke mutabik" likhna jhooth hai.
        """
        got: List[str] = []
        missing: List[str] = []
        depth = self.read_depth()
        if depth == DEPTH_FULL:
            got.append(f"description process hui ({len(self.description_text.strip())} chars)")
        elif self.description_text.strip():
            missing.append("description sirf tukda bhar mila (process nahi maana)")
        else:
            missing.append("description nahi mili")
        if self.claim_count() and len(self.claims_text.strip()) >= MIN_CLAIMS_CHARS:
            got.append(f"{self.claim_count()} claims process hue")
        else:
            missing.append("claims text nahi mila")
        if len((self.abstract or "").strip()) >= MIN_ABSTRACT_CHARS:
            got.append("abstract mila")
        elif not self.abstract.strip():
            missing.append("abstract nahi mila")
        head = ", ".join(got) if got else "sirf bibliographic metadata mila"
        return head + (" | " + ", ".join(missing) if missing else "")

    def status_label(self) -> str:
        """Legal status — sirf jab reliable source ne diya ho."""
        if not (self.legal_status or "").strip():
            return "legal status: provider ne nahi diya (isse 'active' ya " \
                   "'abandoned' maan lena galat hoga)"
        source = f" (source: {self.legal_status_source})" if self.legal_status_source else ""
        return f"legal status: {self.legal_status.strip()}{source}"

    # Ye fields research ke liye maayne rakhte hain; jo na mile wo audit mein
    # naam se dikhte hain (trap #10: incomplete metadata ko chhupana nahi hai).
    _AUDIT_FIELDS = ("number", "title", "assignee", "inventors", "filing_date",
                     "publication_date", "priority_date", "family_id",
                     "legal_status")

    def missing_fields(self) -> List[str]:
        return [name for name in self._AUDIT_FIELDS if not _val(self, name)]

    def family_key(self) -> str:
        return family_key(self)

    def label(self) -> str:
        """Prompt/report mein dikhne wala short descriptor."""
        bits = [b for b in (self.number, jurisdiction_label(self.jurisdiction)) if b]
        if self.assignee:
            bits.append(f"assignee: {self.assignee}")
        if self.year:
            bits.append(str(self.year))
        bits.append(PATENT_EVIDENCE_NOTE)
        return " | ".join(bits)

    def to_dict(self, include_text: bool = False) -> Dict:
        """
        Audit/API ke liye dict.

        Bade text (claims/description) DEFAULT mein bahar rehte hain — warna
        ek patent record API response ko megabytes tak le jaata. Unki jagah
        char-count aur claim-count jaate hain, jinse "kitna padha" ka sawaal
        poora jawab paa leta hai.
        """
        data = asdict(self)
        if not include_text:
            for key in ("abstract", "claims_text", "description_text"):
                data.pop(key, None)
        data.update({
            "jurisdiction_label": jurisdiction_label(self.jurisdiction),
            "year": self.year,
            "claim_count": self.claim_count(),
            "read_depth": self.read_depth(),
            "read_note": self.read_note(),
            "status_label": self.status_label(),
            "family_key": self.family_key(),
            "abstract_chars": len((self.abstract or "").strip()),
            "claims_chars": len((self.claims_text or "").strip()),
            "description_chars": len((self.description_text or "").strip()),
            "missing_fields": self.missing_fields(),
            "evidence_note": PATENT_EVIDENCE_NOTE,
        })
        return data


# ── family key (dedup ka dil) ────────────────────────────────────────────────
def family_key(meta) -> str:
    """
    Ek invention = ek key. PatentMeta ya plain dict, dono chalte hain.

    Tarteeb (sabse bharosemand pehle):
      1. family_id      — provider ne khud bataya ki ye ek hi family hai
      2. priority date + title slug — family id na ho to priority relationship
         hi asli rishta hai (ek hi priority se US/EP/WO nikalte hain)
      3. number ka jurisdiction+serial (kind code HATA kar) — B1/B2 ek hi cheez
      4. sirf title slug — aakhri sahara
    Kuch bhi na ho to khaali string, aur khaali key par dedup NAHI hota (warna
    do bilkul unknown patents ek gin jaate).
    """
    fam = str(_val(meta, "family_id") or "").strip()
    if fam:
        return "patfam:" + re.sub(r"[^0-9A-Za-z]", "", fam).lower()

    slug = _title_slug(_val(meta, "title") or "")
    priority = _date_key(_val(meta, "priority_date")) or _date_key(_val(meta, "filing_date"))
    if priority and slug:
        return f"patpri:{priority}:{slug}"

    parts = split_number(_val(meta, "number") or "")
    if parts["serial"]:
        return f"patno:{parts['jurisdiction'].lower()}{parts['serial']}"
    if slug:
        return f"pattitle:{slug}"
    return ""


def family_members(metas: List) -> Dict[str, List]:
    """family key → us key ke saare records. Khaali key wale alag hi rehte hain."""
    groups: Dict[str, List] = {}
    for meta in metas:
        key = family_key(meta)
        if not key:
            continue
        groups.setdefault(key, []).append(meta)
    return groups


# ── intent routing (planner isi ko poochta hai) ──────────────────────────────
# "Har generic question par patent connector wastefully call mat karna" —
# isliye do darwaze hain:
#   STRONG  : sawaal mein patent/prior-art ki baat SEEDHE hai → haan
#   TECH+DO : invention-jaisi cheez (device/material/process) + banane/design
#             karne ka iraada dono ho → haan
# Sirf ek taraf ho (jaise "battery kya hai") to patent search nahi hoti.
_STRONG_PATENT_TERMS = (
    "patent", "patented", "patents", "prior art", "prior-art", "priorart",
    "uspto", "epo", "wipo", "espacenet", "ipc classification", "cpc class",
    "पेटेंट", "patentability", "infringement", "claim chart", "freedom to operate",
)
_TECH_OBJECT_TERMS = (
    "device", "apparatus", "machine", "circuit", "sensor", "actuator", "reactor",
    "electrode", "membrane", "catalyst", "alloy", "composite", "coating",
    "material", "materials", "prototype", "module", "battery", "cell", "engine",
    "motor", "turbine", "pump", "chip", "semiconductor", "wafer", "antenna",
    "robot", "drone", "implant", "cartridge", "architecture", "assembly",
    "fabrication", "manufacturing", "process", "method", "technique", "system",
    "यंत्र", "उपकरण", "मशीन", "सामग्री", "प्रक्रिया",
)
_BUILD_INTENT_TERMS = (
    "invent", "invention", "novel", "novelty", "design", "designing", "build",
    "building", "develop", "developing", "engineer", "engineering", "implement",
    "implementation", "manufacture", "manufacturing", "fabricate", "fabricating",
    "commercial", "commercialize", "scale up", "scale-up", "product", "prototype",
    "existing approach", "existing approaches", "state of the art",
    "state-of-the-art", "already exists", "pehle se", "pehle hua", "banaya",
    "banane", "banana", "बनाना", "बनाने", "आविष्कार", "नया", "डिजाइन",
)


def _hits(text: str, terms) -> List[str]:
    return [t for t in terms if t in text]


def patent_intent(question: str, extra: str = "") -> Dict:
    """
    Kya is sawaal par patent search karni chahiye? Poori wajah ke saath.

    Returns: {"wanted": bool, "kind": "", "signals": [...], "reason": "..."}
    `kind` = "explicit" (patent/prior-art seedhe poocha) ya "technical"
    (invention-jaisa sawaal) ya "" (nahi chahiye).

    Ye function DETERMINISTIC hai — koi LLM nahi, koi randomness nahi, taaki
    ek hi sawaal par routing hamesha ek hi rahe (test isi par tika hai).
    """
    text = f"{question or ''} {extra or ''}".lower()
    if not text.strip():
        return {"wanted": False, "kind": "", "signals": [],
                "reason": "sawaal khaali hai"}

    strong = _hits(text, _STRONG_PATENT_TERMS)
    if strong:
        return {"wanted": True, "kind": "explicit", "signals": strong[:4],
                "reason": "sawaal mein patent/prior-art ki baat seedhe hai: "
                          + ", ".join(strong[:4])}

    objects = _hits(text, _TECH_OBJECT_TERMS)
    intents = _hits(text, _BUILD_INTENT_TERMS)
    if objects and intents:
        return {"wanted": True, "kind": "technical",
                "signals": (objects[:3] + intents[:3]),
                "reason": ("invention-jaisa sawaal hai (cheez: "
                           + ", ".join(objects[:3]) + " | iraada: "
                           + ", ".join(intents[:3]) + ") — prior-art signal "
                           "dekhna kaam ka hai")}

    why = "koi patent/prior-art signal nahi mila"
    if objects and not intents:
        why = ("technical cheez ka zikr hai par banane/novelty ka iraada nahi "
               "(" + ", ".join(objects[:3]) + ") — patent search yahan bekaar "
               "API call hoti")
    elif intents and not objects:
        why = ("banane/novelty ke shabd hain par koi technical cheez nahi "
               "(" + ", ".join(intents[:3]) + ")")
    return {"wanted": False, "kind": "", "signals": [], "reason": why}


# ── novelty honesty (point 8) ────────────────────────────────────────────────
NOVELTY_DISCLAIMER = (
    "Ye legal novelty ya patentability ki opinion NAHI hai — sirf itna hai ki "
    "jo sources search hue, unme prior-art signal mila ya nahi mila. Patent "
    "search coverage kabhi poori nahi hoti (18 mahine tak applications "
    "publish hi nahi hoti, aur har jurisdiction search nahi hui)."
)


def novelty_note(hit_count: int,
                 providers_searched: Optional[List[str]] = None,
                 providers_stopped: Optional[List[str]] = None,
                 families: Optional[int] = None) -> str:
    """
    Prior-art signal ka imaandaar bayaan — "novel hai" kabhi nahi bolta.

    hit_count        : kitne patent records mile
    providers_searched: jinki search SACH MEIN chali
    providers_stopped : jo chal hi nahi paaye (no_key / rate limit / timeout)
    families         : kitni ALAG families (US/EP/WO ko ek ginne ke baad)
    """
    searched = [p for p in (providers_searched or []) if p]
    stopped = [p for p in (providers_stopped or []) if p]
    stopped_bit = (f" Jo provider chal hi nahi paaye: {', '.join(stopped)}."
                   if stopped else "")

    if hit_count > 0:
        fam_bit = ""
        if families is not None and families != hit_count:
            fam_bit = (f" (ye {hit_count} publications hain par sirf {families} "
                       f"alag invention families — ek hi family ke US/EP/WO ko "
                       f"alag evidence nahi gina gaya)")
        return (f"Searched patent sources mein {hit_count} prior-art signal mile"
                f"{fam_bit}. Source: {', '.join(searched) or 'unknown'}."
                f"{stopped_bit} {NOVELTY_DISCLAIMER}")

    if not searched:
        return ("Patent search CHALI HI NAHI." + stopped_bit
                + " Isliye prior art ke baare mein kuch bhi kehna — mila ya "
                  "nahi mila — galat hoga. " + NOVELTY_DISCLAIMER)

    return (f"Jo patent sources search hue ({', '.join(searched)}), unme is "
            f"query par koi matching patent NAHI mila." + stopped_bit
            + " Iska matlab 'idea novel hai' nahi hai — sirf itna hai ki in "
              "sources mein, in queries par, signal nahi mila. "
            + NOVELTY_DISCLAIMER)


# ── novelty overclaim detector (point 8 ka deterministic safety net) ─────────
# Prompt rule model ko pehle bata deta hai, par bharosa uspar nahi hai. Agar
# answer mein phir bhi "ye idea novel hai / kisi ne patent nahi kiya isliye
# naya hai" jaisa dava aa jaaye, to engine use chupchaap jaane nahi deta — ek
# saaf correction warning report mein jaati hai. Text kaata nahi jaata (content
# kabhi nahi khota), sirf saath mein sach likh diya jaata hai.
_NOVELTY_CLAIM_PATTERNS = (
    r"\bidea\s+novel\b", r"\bnaya\s+invention\s+hai\b",
    r"\bpatentable\b", r"\bpatent\s+mil\s+(?:jayega|sakta)\b",
    r"\bpatent\s+ho\s+sakta\s+hai\b",
    r"\bno\s+prior\s+art\b", r"\bprior\s+art\s+(?:nahi|not)\s+(?:hai|exists?)\b",
    r"\bkoi\s+patent\s+nahi\s+hai\s*,?\s*isliye\b",
    r"\bfirst\s+of\s+its\s+kind\b",
    r"\bkisi\s+ne\s+(?:ye|yeh)?\s*(?:nahi\s+banaya|patent\s+nahi\s+kiya)\b",
    r"\bunpatented\b", r"\bfreely\s+patentable\b",
    r"\bnovelty\s+(?:saabit|confirm(?:ed)?|established)\b",
)


def novelty_overclaim(text: str) -> List[str]:
    """Answer mein novelty/patentability ka dava dikha? Jo phrase mile wo lautao."""
    body = str(text or "")
    if not body.strip():
        return []
    found: List[str] = []
    for pattern in _NOVELTY_CLAIM_PATTERNS:
        for hit in re.findall(pattern, body, flags=re.IGNORECASE):
            phrase = (hit if isinstance(hit, str) else " ".join(hit)).strip()
            if phrase and phrase.lower() not in [f.lower() for f in found]:
                found.append(phrase)
    return found


def evidence_text(meta, limit: int = 1500) -> str:
    """
    Patent ka wo text jo evidence ki tarah aage jaata hai — clearly LABELLED.

    Label lagana cosmetic nahi hai: reasoning model ko pata hona chahiye ki wo
    "CLAIM (legal dawa)" padh raha hai ya "ABSTRACT (summary)". Bina label ke
    claims ka text bilkul kisi paper ke result jaisa dikhta hai — aur wahi se
    "patent claim = saabit fact" wali galti shuru hoti hai.
    """
    parts: List[str] = []
    abstract = (_val(meta, "abstract") or "").strip()
    claims = (_val(meta, "claims_text") or "").strip()
    description = (_val(meta, "description_text") or "").strip()
    if abstract:
        parts.append("ABSTRACT (patent ka summary): " + " ".join(abstract.split()))
    if claims:
        parts.append("CLAIMS (LEGAL dawe, experiment nahi): "
                     + " ".join(claims.split()))
    if description:
        parts.append("DESCRIPTION (patent ka apna text): "
                     + " ".join(description.split()))
    text = " || ".join(parts)
    return text[:limit] if limit and limit > 0 else text


# ── prompt block (patent wale pack ke saath hi jaata hai) ────────────────────
# Deterministic gates (claim_labels, claim_verification, consensus_gate) model
# par bharosa nahi karte — wo galti ko BAAD mein pakadte hain. Ye block usse
# pehle ka kaam karta hai: model ko rule pata ho to wo galti hi kam karega.
# Pack mein patent na ho to ye prompt mein jaata bhi nahi (bekaar tokens nahi).
PATENT_RULE_PROMPT = """# PATENT RULE (patent legal document hai, experiment ka result nahi)
- Patent ke claims LEGAL dawe hain. "Granted" ka matlab examiner ko novel/
  non-obvious laga — ye NAHI ki koi experiment se saabit ho gaya. Isliye patent
  par tiki baat ka label `[SOURCE-REPORTED]` hi rahega, `[ESTABLISHED]` nahi
  (ye engine mein deterministic gate bhi hai — todne par khud neeche ho jayega).
- Patent ki ginti se "sources sehmat hain" mat banao. Ek hi topic par 5 patent
  aam baat hai (companies aas-paas file karti hain) — wo 5 experiment nahi hain.
- "Koi matching patent nahi mila" ko "idea novel hai" MAT likhna. Search coverage
  kabhi poori nahi hoti: applications 18 mahine tak publish hi nahi hoti aur har
  jurisdiction search nahi hui. Sirf itna likho: "jo sources search hue unme ye
  prior-art signal mile / nahi mile".
- Legal novelty, patentability, infringement ya validity ki opinion kabhi mat
  do — ye patent attorney ka kaam hai. Engine sirf signal report karta hai.
- Patent ka text tabhi "padha" kehna jab CLAIMS ya DESCRIPTION process hua ho.
  Source block mein har patent par uska read depth likha hai — wahi dekho.
"""


__all__ = [
    "DEPTH_METADATA", "DEPTH_ABSTRACT", "DEPTH_CLAIMS", "DEPTH_FULL",
    "MIN_ABSTRACT_CHARS", "MIN_CLAIMS_CHARS", "MIN_DESCRIPTION_CHARS",
    "PATENT_EVIDENCE_NOTE", "NOVELTY_DISCLAIMER", "PATENT_RULE_PROMPT",
    "PatentMeta", "normalize_number", "split_number", "jurisdiction_label",
    "looks_like_patent_number", "family_key", "family_members",
    "patent_intent", "novelty_note", "evidence_text", "novelty_overclaim",
]
