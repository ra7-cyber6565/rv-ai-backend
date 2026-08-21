"""
§13 / point 7 — verification ke PAANCH ALAG check (A–E)

Purana bug: citation "verify ho gaya" ka matlab sirf itna tha ki `[S3]` naam ka
source pack mein maujood hai. Yaani ID exist karti thi, isliye claim ko verified
ginn liya jaata tha. Ye teen alag sawaalon ko ek maan lena tha:

    "citation likhi hai?"  ≠  "source is sawaal se juda hai?"
                           ≠  "us source ka text ye claim keh raha hai?"

Ab paanch check alag-alag chalte aur alag-alag report hote hain:

    A  citation exists        — line par [S#] hai aur wo pack mein milta hai
    B  source relevant        — wahi source is sawaal ke liye reject nahi hua
    C  claim entailed         — cited text mein is claim ka support dikhta hai
    D  reading depth adequate — us source ka kitna hissa asli mein padha gaya
    E  source quality adequate— retracted/kamzor source par dava nahi tikta

Sirf C "genuine support" dikhata hai (spec ka verbatim point). A pass hona bas
itna batata hai ki likhawat theek hai.

IMAANDAARI KI EK BAAT, SAAF-SAAF: check C ek DETERMINISTIC proxy hai — token
overlap + bigram similarity + number match. Ye NLI (natural language inference)
model nahi hai, aur ye khud ko wahi bhi nahi kehta. Isliye do haalaton mein wo
"unknown" bolta hai (fail nahi): jab cited source ka koi text hi humare paas
nahi hai, aur jab text bahut chhota hai. Jhoothe "verified" se jhootha
"unverified" behtar hai, par dono se behtar hai saaf likh dena ki check ho hi
nahi saka.

Poora module pure-Python hai: koi network, koi API key, koi paid service (₹0).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .models import ClaimType, EvidencePack, SourceRecord, label_to_claim_type

CHECK_LABELS: Dict[str, str] = {
    "A": "citation maujood hai",
    "B": "source sawaal se juda hai",
    "C": "claim us source ke text se support hota hai",
    "D": "padhne ki gehrai kaafi hai",
    "E": "source ki quality kaafi hai",
}

PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"

# Verdicts (sabse strong se sabse kamzor)
GENUINE_SUPPORT = "genuine_support"
SOURCE_REPORTED = "source_reported"
CITED_ONLY = "cited_only"
UNSUPPORTED = "unsupported"

VERDICT_LABELS: Dict[str, str] = {
    GENUINE_SUPPORT: "poora text padh kar support mila",
    SOURCE_REPORTED: "source ye report karta hai (poora text nahi padha gaya)",
    CITED_ONLY: "citation to hai, par us text mein is claim ka support nahi dikha",
    UNSUPPORTED: "koi valid source nahi",
}

_SID_RE = re.compile(r"\[\s*S\s*(\d{1,3})[^\]]*\]", re.IGNORECASE)
_LABEL_RE = re.compile(
    r"\[\s*(ESTABLISHED(?:\s+FACT)?|FACT|STRONG\s+EVIDENCE|SOURCE[\s\-]?REPORTED|"
    r"MIXED\s+EVIDENCE|WEAK\s+EVIDENCE|EVIDENCE|INFERENCE|HYPOTHESIS|"
    r"SPECULATION|UNVERIFIED|UNKNOWN|NO[\s\-]?SOURCE)\s*\]",
    re.IGNORECASE)
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
_STRONG_LABEL_RE = re.compile(
    r"\[\s*(ESTABLISHED(?:\s+FACT)?|FACT|STRONG\s+EVIDENCE)\s*\]", re.IGNORECASE)

# Sirf ye do family "ye sach hai" ka dava karti hain. HYPOTHESIS/SPECULATION/
# INFERENCE khud kehte hain ki sabit nahi hai — unki ginti verification mein
# nahi hoti (warna 3 hypotheses likhne se "unsupported" counter badh jaata).
_GROUNDED_TYPES = {ClaimType.FACT, ClaimType.EVIDENCE}

# Thresholds — ek jagah, taaki test aur code ek hi number dekhein.
_ENTAIL_SIM = 0.30          # isse upar = support dikha
_ENTAIL_SIM_WITH_NUM = 0.12  # numbers exact mile to itni similarity kaafi hai
_MIN_TEXT_CHARS = 120       # isse chhote text par C ka faisla nahi lete
_MIN_RELEVANCE = 0.25       # B ke liye
_MIN_QUALITY = 0.35         # E ke liye
_LOW_QUALITY = 0.20         # isse neeche = saaf fail


@dataclass
class Check:
    key: str
    label: str
    status: str = UNKNOWN
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == PASS

    def to_dict(self) -> Dict:
        return {"check": self.key, "label": self.label,
                "status": self.status, "detail": self.detail}


@dataclass
class ClaimCheck:
    """Ek claim, paanch check, ek verdict — aur har cheez ki wajah likhi hui."""
    text: str = ""
    cited_ids: List[str] = field(default_factory=list)
    checks: List[Check] = field(default_factory=list)
    verdict: str = UNSUPPORTED
    reason: str = ""
    best_source: str = ""
    strong_label: bool = False

    def check(self, key: str) -> Optional[Check]:
        for c in self.checks:
            if c.key == key:
                return c
        return None

    def status(self, key: str) -> str:
        c = self.check(key)
        return c.status if c else UNKNOWN

    @property
    def genuine(self) -> bool:
        """Sirf C pass hone par hi "asli support" — spec ka rule."""
        return self.status("C") == PASS

    def failed_checks(self) -> List[str]:
        return [c.key for c in self.checks if c.status == FAIL]

    def to_dict(self) -> Dict:
        return {"claim": self.text[:220], "cited_ids": list(self.cited_ids),
                "verdict": self.verdict, "verdict_label":
                    VERDICT_LABELS.get(self.verdict, self.verdict),
                "reason": self.reason, "best_source": self.best_source,
                "failed": self.failed_checks(),
                "checks": [c.to_dict() for c in self.checks]}


# ── helpers ──────────────────────────────────────────────────────────────────
def _similarity(claim: str, body: str) -> float:
    """semantic.py wahi scoring hai jo relevance/page-filter use karta hai."""
    try:
        from . import semantic
        return float(semantic.similarity(claim, body))
    except Exception:                       # pragma: no cover - defensive
        c = {w for w in re.findall(r"[a-z]{4,}", (claim or "").lower())}
        b = {w for w in re.findall(r"[a-z]{4,}", (body or "").lower())}
        return round(len(c & b) / len(c), 4) if c else 0.0


def _numbers(text: str) -> List[str]:
    """Claim ke numbers — inhi par asli scientific dava tikta hai (Tc, %, GPa)."""
    out: List[str] = []
    for raw in _NUM_RE.findall(text or ""):
        clean = raw.replace(",", "")
        if clean not in out:
            out.append(clean)
    return out


def cited_ids(line: str) -> List[str]:
    out: List[str] = []
    for num in _SID_RE.findall(line or ""):
        sid = f"S{int(num)}"
        if sid not in out:
            out.append(sid)
    return out


def claim_body(line: str) -> str:
    """Label aur [S#] hata kar sirf claim ka matlab bacha lo."""
    body = _LABEL_RE.sub(" ", line or "")
    body = _SID_RE.sub(" ", body)
    body = re.sub(r"^[#\s\-\*\d\.\)]+", "", body)
    return " ".join(body.split())


def source_text(source: SourceRecord, pack: Optional[EvidencePack] = None) -> str:
    """
    Us source ka jo bhi text humare paas ASLI mein hai.

    Passages pehle (full-text reading ke chune hue hisse), phir snippet/abstract.
    Yahan koi guess nahi hota: jo nahi hai wo khaali rehta hai, aur khaali hone
    par check C imaandaari se "unknown" bolta hai.
    """
    parts: List[str] = []
    if pack is not None:
        for passage in getattr(pack, "passages", []) or []:
            if getattr(passage, "source_id", "") == source.source_id:
                text = (getattr(passage, "text", "") or "").strip()
                if text:
                    parts.append(text)
    snippet = (source.snippet or "").strip()
    if snippet:
        parts.append(snippet)
    return "\n".join(parts).strip()


# ── A: citation exists ───────────────────────────────────────────────────────
def check_a(ids: Sequence[str], records: Sequence[SourceRecord],
            line: str = "") -> Check:
    c = Check("A", CHECK_LABELS["A"])
    if not ids:
        c.status = FAIL
        c.detail = "is line par koi [S#] citation nahi hai"
        return c
    if not records:
        c.status = FAIL
        c.detail = (", ".join(ids) + " evidence pack mein nahi mile "
                    "(ID likhi hai, source nahi)")
        return c
    found = [r.source_id for r in records]
    missing = [i for i in ids if i not in found]
    c.status = PASS
    c.detail = f"{', '.join(found)} pack mein maujood hai"
    if missing:
        c.detail += f"; {', '.join(missing)} nahi mile"
    return c


# ── B: source relevant ──────────────────────────────────────────────────────
def check_b(records: Sequence[SourceRecord]) -> Check:
    c = Check("B", CHECK_LABELS["B"])
    if not records:
        c.status = UNKNOWN
        c.detail = "koi source hi nahi mila, isliye relevance dekh nahi sakte"
        return c
    rejected = [r for r in records if (r.rejected_reason or "").strip()]
    scored = [r for r in records if (r.relevance_score or 0) >= _MIN_RELEVANCE]
    if scored:
        best = max(scored, key=lambda r: r.relevance_score or 0)
        c.status = PASS
        c.detail = (f"{best.source_id} ka relevance {best.relevance_score:.2f} "
                    f"(≥ {_MIN_RELEVANCE:.2f})")
        return c
    if rejected:
        c.status = FAIL
        c.detail = (f"{rejected[0].source_id} is sawaal ke liye reject hua tha: "
                    f"{(rejected[0].rejected_reason or '')[:90]}")
        return c
    graded = [r for r in records if (r.relevance_score or 0) > 0]
    if graded:
        worst = max(graded, key=lambda r: r.relevance_score or 0)
        c.status = FAIL
        c.detail = (f"sabse acha cited source bhi sirf "
                    f"{worst.relevance_score:.2f} relevance par hai "
                    f"(chahiye {_MIN_RELEVANCE:.2f})")
        return c
    c.status = UNKNOWN
    c.detail = "in sources par relevance score nahi chala tha"
    return c


# ── C: claim entailed (asli support — sirf yahi "verified" kehlata hai) ──────
def check_c(claim: str, records: Sequence[SourceRecord],
            pack: Optional[EvidencePack] = None) -> Tuple[Check, str]:
    """
    Returns (check, best_source_id).

    Faisla teen cheezon se: similarity, claim ke numbers ka text mein milna, aur
    text ki maujoodgi. Text hi na ho to "unknown" — kyunki us haalat mein humne
    claim ko na sach kaha ja sakta hai na jhooth.
    """
    c = Check("C", CHECK_LABELS["C"])
    body = claim_body(claim)
    if not records:
        c.status = UNKNOWN
        c.detail = "koi cited source nahi, isliye entailment check nahi hua"
        return c, ""
    if len(body) < 20:
        c.status = UNKNOWN
        c.detail = "claim itna chhota hai ki uska matlab hi nahi nikalta"
        return c, ""

    wanted = _numbers(body)
    best_id, best_score, best_note = "", -1.0, ""
    evaluated = False
    for record in records:
        text = source_text(record, pack)
        if len(text) < _MIN_TEXT_CHARS:
            continue
        evaluated = True
        score = _similarity(body, text)
        low = text.lower()
        hits = [n for n in wanted if n in low]
        matched_all = bool(wanted) and len(hits) == len(wanted)
        effective = score + (0.20 if matched_all else 0.0)
        if effective > best_score:
            best_score, best_id = effective, record.source_id
            if wanted:
                best_note = (f"{len(hits)}/{len(wanted)} number cited text mein "
                             f"mile, text-match {score:.2f}")
            else:
                best_note = f"text-match {score:.2f}"

    if not evaluated:
        c.status = UNKNOWN
        c.detail = ("cited source ka text humare paas nahi hai (sirf metadata/"
                    "chhota snippet), isliye claim ka support check nahi ho saka")
        return c, ""

    threshold = _ENTAIL_SIM_WITH_NUM if wanted else _ENTAIL_SIM
    if best_score >= threshold:
        c.status = PASS
        c.detail = f"{best_id} ke text se support mila — {best_note}"
    else:
        c.status = FAIL
        c.detail = (f"cited text mein is claim ka support nahi dikha — "
                    f"{best_note or 'text-match bahut kam'}")
    return c, (best_id if c.status == PASS else "")


# ── D: reading depth ────────────────────────────────────────────────────────
def check_d(records: Sequence[SourceRecord]) -> Check:
    c = Check("D", CHECK_LABELS["D"])
    if not records:
        c.status = UNKNOWN
        c.detail = "koi source nahi"
        return c
    levels: Dict[str, str] = {}
    for record in records:
        try:
            levels[record.source_id] = record.reading_level()
        except Exception:                   # pragma: no cover - defensive
            levels[record.source_id] = "metadata"
    detail = ", ".join(f"{sid}={lvl}" for sid, lvl in levels.items())
    full = [sid for sid, lvl in levels.items() if lvl == "full_text"]
    if full:
        c.status = PASS
        c.detail = f"poora text padha gaya: {', '.join(full)} ({detail})"
        # §12 ki honesty: badi PDF page-by-page padhi ho to wahi likho.
        notes = [r.read_note for r in records
                 if r.source_id in full and (r.read_note or "").strip()]
        if notes:
            c.detail += f" — dhyan rahe: {notes[0][:120]}"
        return c
    if any(lvl == "abstract" for lvl in levels.values()):
        c.status = UNKNOWN
        c.detail = (f"sirf abstract level tak padha gaya ({detail}) — claim "
                    f"'source-reported' se aage nahi jaa sakta")
        return c
    c.status = FAIL
    c.detail = f"sirf snippet/metadata mila ({detail})"
    return c


# ── E: source quality ───────────────────────────────────────────────────────
def check_e(records: Sequence[SourceRecord]) -> Check:
    c = Check("E", CHECK_LABELS["E"])
    if not records:
        c.status = UNKNOWN
        c.detail = "koi source nahi"
        return c
    retracted = [r.source_id for r in records if r.retracted is True]
    if retracted and len(retracted) == len(records):
        c.status = FAIL
        c.detail = f"cited source retracted hai: {', '.join(retracted)}"
        return c
    scores = [(r.source_id, float(r.quality_score or 0.0)) for r in records]
    best_id, best = max(scores, key=lambda kv: kv[1])
    if best >= _MIN_QUALITY:
        c.status = PASS
        c.detail = f"{best_id} ka quality score {best:.2f} (≥ {_MIN_QUALITY:.2f})"
    elif best <= _LOW_QUALITY:
        c.status = FAIL
        c.detail = (f"sabse acha cited source bhi {best:.2f} quality par hai — "
                    f"itne par 'established' dava theek nahi")
    else:
        c.status = UNKNOWN
        c.detail = f"quality signals adhoore hain (best {best:.2f})"
    if retracted:
        c.detail += f"; dhyan rahe {', '.join(retracted)} retracted hai"
    return c


# ── ek claim = A..E + ek verdict ─────────────────────────────────────────────
def verify_claim(line: str, pack: Optional[EvidencePack] = None) -> ClaimCheck:
    """
    Ek claim line par paanchon check chalao aur ek verdict do.

    Verdict ka rule (jaan-boojh kar strict, aur A par nahi tikta):
        genuine_support  — A,B,C pass AUR D pass (full text) AUR E fail nahi
        source_reported  — A,B,C pass, par gehrai sirf abstract tak
        cited_only       — citation to sahi hai, par C ne support nahi dikhaya
        unsupported      — A hi fail (citation nahi / ID pack mein nahi)
    """
    ids = cited_ids(line)
    records: List[SourceRecord] = []
    if pack is not None:
        for sid in ids:
            src = pack.by_id(sid)
            if src is not None:
                records.append(src)

    cc = ClaimCheck(text=claim_body(line), cited_ids=list(ids))
    cc.strong_label = bool(_STRONG_LABEL_RE.search(line or ""))

    a = check_a(ids, records, line)
    b = check_b(records)
    c_check, best = check_c(line, records, pack)
    d = check_d(records)
    e = check_e(records)
    cc.checks = [a, b, c_check, d, e]
    cc.best_source = best

    if not a.ok:
        cc.verdict = UNSUPPORTED
        cc.reason = a.detail
        return cc
    if b.status == FAIL:
        cc.verdict = CITED_ONLY
        cc.reason = b.detail
        return cc
    if e.status == FAIL:
        cc.verdict = CITED_ONLY
        cc.reason = e.detail
        return cc
    if c_check.ok:
        if d.ok:
            cc.verdict = GENUINE_SUPPORT
            cc.reason = f"{c_check.detail}; {d.detail}"
        else:
            cc.verdict = SOURCE_REPORTED
            cc.reason = f"{c_check.detail}; par {d.detail}"
        return cc
    cc.verdict = CITED_ONLY
    cc.reason = c_check.detail
    return cc


# ── poore answer ka report ───────────────────────────────────────────────────
@dataclass
class VerificationReport:
    """
    Poore answer ke claim-level checks — aur unka imaandaar denominator.

    §14 ki galti yahan dobara nahi honi chahiye: "verified: 12" likhne se pehle
    ye batana zaroori hai ki 12 KISME se hai, aur kitne check ho hi nahi sake.
    Isliye har count alag rakha gaya hai: genuine / source_reported /
    cited_only / unsupported, aur unknown_entailment alag.
    """
    claims: List[ClaimCheck] = field(default_factory=list)
    overclaims: List[ClaimCheck] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.claims)

    def _count(self, verdict: str) -> int:
        return len([c for c in self.claims if c.verdict == verdict])

    @property
    def genuine(self) -> int:
        return self._count(GENUINE_SUPPORT)

    @property
    def source_reported(self) -> int:
        return self._count(SOURCE_REPORTED)

    @property
    def cited_only(self) -> int:
        return self._count(CITED_ONLY)

    @property
    def unsupported(self) -> int:
        return self._count(UNSUPPORTED)

    @property
    def unknown_entailment(self) -> int:
        """
        Wo claims jinka support check HO HI NAHI SAKA.

        Dhyan: sirf wahi ginte hain jinki citation SAHI thi (A pass) par us
        source ka text hi humare paas nahi tha. Jinme citation hi nahi thi wo
        pehle se `unsupported` mein gine ja rahe hain — unhe dobara ginna
        denominator ko jhootha bana deta.
        """
        return len([c for c in self.claims
                    if c.status("C") == UNKNOWN and c.status("A") == PASS])

    @property
    def genuine_ratio(self) -> float:
        return round(self.genuine / self.total, 3) if self.total else 0.0

    def check_counts(self) -> Dict[str, Dict[str, int]]:
        out: Dict[str, Dict[str, int]] = {}
        for key in ("A", "B", "C", "D", "E"):
            row = {PASS: 0, FAIL: 0, UNKNOWN: 0}
            for cc in self.claims:
                row[cc.status(key)] = row.get(cc.status(key), 0) + 1
            out[key] = row
        return out

    def to_dict(self) -> Dict:
        return {"total_claims": self.total, "genuine_support": self.genuine,
                "source_reported": self.source_reported,
                "cited_only": self.cited_only, "unsupported": self.unsupported,
                "entailment_not_checkable": self.unknown_entailment,
                "genuine_ratio": self.genuine_ratio,
                "check_counts": self.check_counts(),
                "overclaims": [c.to_dict() for c in self.overclaims],
                "claims": [c.to_dict() for c in self.claims]}

    # ── user ko dikhne wali do cheezein ──────────────────────────────────────
    def note(self) -> str:
        """Ek line — audit section ke liye, denominator ke saath."""
        if not self.total:
            return ("Is jawab mein koi labelled + cited claim nahi mila, isliye "
                    "claim-level verification chala hi nahi.")
        bits = [f"{self.total} labelled claim par paanch check chale",
                f"{self.genuine} par poora text padh kar support mila",
                f"{self.source_reported} sirf 'source ye report karta hai' level par hai",
                f"{self.cited_only} mein citation to thi par us text mein support nahi dikha",
                f"{self.unsupported} par koi valid source hi nahi"]
        line = "; ".join(bits) + "."
        if self.unknown_entailment:
            line += (f" Inme {self.unknown_entailment} claim ka support check "
                     f"HO HI NAHI SAKA (us source ka text humare paas nahi tha) "
                     f"— unhe 'verified' nahi gina gaya.")
        return line

    def block(self) -> str:
        """Answer ke aakhir mein jaane wala saaf-saaf verification block."""
        lines = ["**Claim verification (A–E, har check alag):**", "",
                 self.note(), ""]
        counts = self.check_counts()
        for key in ("A", "B", "C", "D", "E"):
            row = counts[key]
            lines.append(f"- **{key}** — {CHECK_LABELS[key]}: "
                         f"{row[PASS]} pass, {row[FAIL]} fail, "
                         f"{row[UNKNOWN]} check nahi ho saka")
        lines.append("")
        lines.append("_Sirf check **C** 'asli support' dikhata hai. **A** pass hona "
                     "itna hi batata hai ki citation likhne ka tareeka theek hai._")
        if self.overclaims:
            lines.append("")
            lines.append(f"⚠️ **{len(self.overclaims)} claim par label zarurat se "
                         f"zyada strong tha** (ESTABLISHED/FACT, par upar ke check "
                         f"usse support nahi karte):")
            for cc in self.overclaims[:5]:
                lines.append(f"- {cc.text[:140]} — {cc.reason[:120]}")
        return "\n".join(lines)


def verify_answer(text: str, pack: Optional[EvidencePack] = None,
                  max_claims: int = 60) -> VerificationReport:
    """
    Answer ki har FACTUAL labelled line par A–E chalao.

    Do cheezein jaan-boojh kar chhodi gayi hain:

    * bina label wali lines — wo explanation/teacher-style hissa hai, dava nahi.
      Un par verification lagana sirf shor paida karta.
    * `[HYPOTHESIS]` / `[SPECULATION]` / `[INFERENCE]` — inka poora matlab hi ye
      hai ki "ye source se sabit nahi hai". Inhe entailment mein fail dikhana
      jhoothi ginti banata: 3 hypotheses likhne se "2 claim unsupported" wala
      counter badhta, jabki wo hypothesis hone ke naate hi unsupported hai.
      Yaani sirf FACT/EVIDENCE family (ESTABLISHED, STRONG/MIXED/WEAK EVIDENCE,
      SOURCE-REPORTED) ki ginti hoti hai — wahi lines "sach" ka dava karti hain.
    """
    report = VerificationReport()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if len(line) < 25:
            continue
        labels = _LABEL_RE.findall(line)
        if not labels:
            continue
        types = {label_to_claim_type(lbl) for lbl in labels}
        if not (types & _GROUNDED_TYPES):
            continue
        cc = verify_claim(line, pack)
        report.claims.append(cc)
        if cc.strong_label and cc.verdict != GENUINE_SUPPORT:
            report.overclaims.append(cc)
        if len(report.claims) >= max_claims:
            break
    return report


# ── opt-in label gate (claim_labels isse use kar sakta hai) ──────────────────
def entailment_blocked(line: str, pack: Optional[EvidencePack] = None) -> bool:
    """
    True = is line par strong label (ESTABLISHED/FACT) nahi rehna chahiye,
    kyunki cited text ne claim ko support NAHI kiya (check C ka saaf FAIL).

    Dhyan do: `unknown` par False lautta hai — jaan-boojh kar. Jab support
    check ho hi na saka, to label girana bhi ek jhootha faisla hota; us haalat
    ko report `entailment_not_checkable` mein saaf likhti hai. Yahi wajah hai
    ki ye gate `claim_labels.downgrade` mein OPT-IN hai, default on nahi.
    """
    ids = cited_ids(line)
    if not ids or pack is None:
        return False
    records = [s for s in (pack.by_id(i) for i in ids) if s is not None]
    if not records:
        return False
    check, _ = check_c(line, records, pack)
    return check.status == FAIL
