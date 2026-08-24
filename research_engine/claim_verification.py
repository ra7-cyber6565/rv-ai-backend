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

from .citation import labelled_claim_spans
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

# ── §8 — ek claim ka apna nateeja (verdict se ALAG vocabulary) ───────────────
# Purana `verdict` (genuine_support/source_reported/cited_only/unsupported)
# waise ka waisa zinda hai — purane test, labels aur audit usi par tike hain.
# Ye naya `result` uske UPAR ek saaf, spec-wala nateeja deta hai, jisme do
# cheezein alag ho jaati hain jo pehle ek dikhti thi:
#   "support nahi mila"  ≠  "source ne ulta kaha"  ≠  "check ho hi nahi saka"
CLAIM_SUPPORTED = "SUPPORTED"
CLAIM_PARTIAL = "PARTIALLY SUPPORTED"
CLAIM_UNSUPPORTED = "UNSUPPORTED"
CLAIM_CONTRADICTED = "CONTRADICTED"
CLAIM_UNVERIFIABLE = "UNABLE TO VERIFY"

CLAIM_RESULTS: Tuple[str, ...] = (
    CLAIM_SUPPORTED, CLAIM_PARTIAL, CLAIM_UNSUPPORTED,
    CLAIM_CONTRADICTED, CLAIM_UNVERIFIABLE,
)

CLAIM_RESULT_EXPLAIN: Dict[str, str] = {
    CLAIM_SUPPORTED: ("cited source ka text is claim ko support karta hai aur "
                      "wo text asli mein padha gaya"),
    CLAIM_PARTIAL: ("support ke signal mile, par gehrai ya source-quality poori "
                    "nahi — 'sabit' kehna galat hoga"),
    CLAIM_UNSUPPORTED: ("us text mein is claim ka support nahi dikha (ya koi "
                        "valid source hi nahi)"),
    CLAIM_CONTRADICTED: "cited source is claim ke ULTA keh raha hai",
    CLAIM_UNVERIFIABLE: ("check HO HI NAHI SAKA — us source ka text humare paas "
                         "nahi hai; ye 'galat' ka matlab nahi hai"),
}

# Critical claim = wo dava jis par jawab ka nateeja tikta hai. Do tareeke se
# banti hai: (1) strong label ([ESTABLISHED FACT]/[FACT]/[STRONG EVIDENCE]),
# (2) seedha jawab / final conclusion wale section ki labelled line.
_CRITICAL_SECTION_RE = re.compile(
    r"(seedha\s+jawab|direct\s+answer|final\s+conclusion|"
    r"evidence[\s\-]?based\s+conclusion|conclusion)", re.IGNORECASE)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")

# Evidence span = source ke text ka wahi tukda jise dekh kar faisla hua.
_SPAN_CHARS = 260

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
    # ── §8 ke naye field (sab optional, purana behaviour nahi badalta) ────────
    claim_id: str = ""                   # "CL001" — audit/UI isi se claim dhoondte hain
    epistemic_type: str = ""             # fact / evidence / hypothesis ...
    critical: bool = False               # nateeja isi par tika hai?
    contradicted: bool = False           # source ne ULTA kaha (result badal deta hai)
    spans: List[Dict] = field(default_factory=list)   # evidence spans
    section: str = ""                    # kis section ki line thi
    # §8/§9 ke naam-wale label. Ye CHECK ka pass/fail nahi hain — ye batate hain
    # "kitna padha gaya" aur "source kis darje ka hai". Dono baaton ko alag
    # rakhna hi §9 ka poora point hai.
    access_label: str = ""               # METADATA ONLY / ABSTRACT ONLY / ...
    quality_label: str = ""              # primary peer-reviewed / preprint / ...
    # P0-A: one-source A-E audit trail; aggregate checks never imply same-source proof.
    source_checks: List[Dict] = field(default_factory=list)
    canonical_span: Dict = field(default_factory=dict)
    supporting_source_id: str = ""
    # Exact source span that triggered an opposite stance; never source-wide.
    contradiction_span: Dict = field(default_factory=dict)

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
        return self.status("C") == PASS and not self.contradicted

    @property
    def passes_ae(self) -> bool:
        """True only when ONE cited source passes A, B, C, D and E together.

        `checks` remains the selected per-claim path for backwards-compatible
        reporting. Legacy manually-constructed ClaimCheck objects without
        `source_checks` keep the old local-check behaviour.
        """
        if self.source_checks:
            return any(bool(row.get("passes_ae")) for row in self.source_checks)
        return all(self.status(key) == PASS for key in ("A", "B", "C", "D", "E"))

    # ── §8: entailment aur source-quality ALAG-ALAG padhe jaate hain ─────────
    @property
    def entailment(self) -> str:
        """Check C ka apna status — 'verified' ka asli sawaal."""
        return self.status("C")

    @property
    def source_quality(self) -> str:
        """Check E ka apna status — isse entailment na samjha jaaye."""
        return self.status("E")

    @property
    def access_depth(self) -> str:
        """Check D ka status — 'kitna padha' ka sawaal, support ka nahi."""
        return self.status("D")

    @property
    def result(self) -> str:
        """Claim result without mixing contradiction, unknown, and partial support."""
        if self.contradicted:
            return CLAIM_CONTRADICTED
        if self.status("A") == FAIL:
            return CLAIM_UNSUPPORTED
        if self.entailment == UNKNOWN:
            return CLAIM_UNVERIFIABLE
        if self.entailment == FAIL:
            return CLAIM_UNSUPPORTED
        if self.passes_ae:
            return CLAIM_SUPPORTED
        return CLAIM_PARTIAL

    @property
    def has_spans(self) -> bool:
        # Canonical span is the artifact that actually drove C.  Legacy objects
        # may only have `spans`, so retain that compatibility fallback.
        return bool(self.canonical_span or self.spans)

    # ── §8/§9 ke naam-wale label (check ke pass/fail se ALAG) ────────────────
    @property
    def entailment_label(self) -> str:
        """
        "Source ne is claim ko support kiya?" ka jawab spec ki bhasha mein.

        `entailment` property check C ka pass/fail deti hai; ye uska matlab
        deti hai. Dono zaroori hain — "check nahi ho saka" ko "support nahi
        mila" mein milana wahi jhoothi ginti hai jise §8 rok raha hai.
        """
        if self.contradicted:
            return CLAIM_CONTRADICTED
        status = self.entailment
        if status == PASS:
            return CLAIM_SUPPORTED
        if status == FAIL:
            return "NOT SUPPORTED"
        return CLAIM_UNVERIFIABLE

    @property
    def access_depth_label(self) -> str:
        """§9 ke paanch labels mein se ek — kitna text sach mein dekha gaya."""
        if self.access_label:
            return self.access_label
        for span in self.spans:
            if span.get("source_id") == self.best_source and span.get("access_depth"):
                return str(span["access_depth"])
        for span in self.spans:
            if span.get("access_depth"):
                return str(span["access_depth"])
        return ""

    @property
    def source_quality_label(self) -> str:
        """Source ka darja (peer-reviewed / preprint / patent / retracted)."""
        return self.quality_label

    def failed_checks(self) -> List[str]:
        return [c.key for c in self.checks if c.status == FAIL]

    def to_dict(self) -> Dict:
        return {"claim": self.text[:220], "cited_ids": list(self.cited_ids),
                "verdict": self.verdict, "verdict_label":
                    VERDICT_LABELS.get(self.verdict, self.verdict),
                "reason": self.reason, "best_source": self.best_source,
                "failed": self.failed_checks(),
                # §8 — naye field, purane wale hataye bina
                "claim_id": self.claim_id,
                # §8 ke exact naam. `claim`/`cited_ids` purane consumers ke liye
                # upar waise hi pade hain; ye do spec ke naam hain aur `text`
                # poora claim rakhta hai (kata hua nahi).
                "text": self.text,
                "source_ids": list(self.cited_ids),
                "epistemic_type": self.epistemic_type,
                "critical": bool(self.critical),
                "section": self.section,
                "result": self.result,
                "result_why": CLAIM_RESULT_EXPLAIN.get(self.result, ""),
                # §8/§9 — LABEL aur CHECK alag-alag keys mein. `entailment`
                # spec ki bhasha bolta hai (SUPPORTED / NOT SUPPORTED / UNABLE
                # TO VERIFY / CONTRADICTED) aur `entailment_check` wahi purana
                # pass/fail rakhta hai. Dono ek hi cheez ke do jawab hain:
                # "support mila?" aur "check chal paaya?".
                "entailment": self.entailment_label,
                "entailment_check": self.entailment,
                "source_quality": self.source_quality_label,
                "source_quality_check": self.source_quality,
                "access_depth": self.access_depth_label,
                "access_depth_check": self.access_depth,
                "contradicted": bool(self.contradicted),
                "contradiction_span": (dict(self.contradiction_span)
                                       if self.contradiction_span else {}),
                "evidence_spans": [dict(s) for s in self.spans],
                "canonical_evidence_span": dict(self.canonical_span) if self.canonical_span else {},
                "supporting_source_id": self.supporting_source_id,
                "same_source_ae_passed": bool(self.passes_ae and not self.contradicted),
                "verified_support": bool(self.passes_ae and not self.contradicted),
                "source_checks": [dict(row) for row in self.source_checks],
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


def epistemic_type(line: str) -> str:
    """
    Is line ka epistemic type — label se, guess se nahi.

    8 categories mix na hon: isliye jo label likha hai wahi type banta hai, aur
    label na ho to "unlabelled" — "fact" maan lena spec ka saaf violation hai.
    """
    labels = _LABEL_RE.findall(line or "")
    if not labels:
        return "unlabelled"
    order = [label_to_claim_type(lbl) for lbl in labels]
    for wanted in (ClaimType.FACT, ClaimType.EVIDENCE):
        if wanted in order:
            return wanted.value
    first = order[0]
    return getattr(first, "value", str(first))


def _access_depth_of(record: SourceRecord) -> str:
    """models.SourceRecord.access_depth() — purane fake record par bhi safe."""
    getter = getattr(record, "access_depth", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:               # pragma: no cover - defensive
            pass
    try:
        return str(record.reading_level() or "metadata")
    except Exception:                   # pragma: no cover - defensive
        return "metadata"


def _quality_label_of(record: SourceRecord) -> str:
    """
    §8 ka `source_quality` — source KIS DARJE ka hai, ye batane wala label.

    Ye check E ka pass/fail nahi hai (wo alag key `source_quality_check` mein
    jaata hai). Yahan sirf imaandaar shreni likhi jaati hai, aur jahan pata
    nahi wahan "pata nahi" likha jaata hai — "peer-reviewed" ka andaaza kabhi
    nahi lagaya jaata.
    """
    if getattr(record, "retracted", None) is True:
        return "retracted — evidence ke laayak nahi"
    if getattr(record, "is_patent", False):
        return "patent (legal document, scientific proof nahi)"
    stype = getattr(record, "source_type", None)
    kind = getattr(stype, "value", str(stype or "source"))
    peer = getattr(record, "peer_reviewed", None)
    if peer is True:
        return f"primary peer-reviewed ({kind})"
    if peer is False:
        return f"peer-reviewed nahi ({kind})"
    return f"peer review ka pata nahi ({kind})"


def _best_window(claim: str, text: str, width: int = _SPAN_CHARS
                 ) -> Tuple[str, float]:
    """Source text ka wo hissa jo claim se sabse zyada milta hai."""
    body = (text or "").strip()
    if not body:
        return "", 0.0
    if len(body) <= width:
        return body, float(_similarity(claim, body))
    step = max(60, width // 2)
    best, best_score = body[:width].strip(), -1.0
    for start in range(0, len(body), step):
        window = body[start:start + width]
        if len(window.strip()) < 40:
            continue
        score = float(_similarity(claim, window))
        if score > best_score:
            best, best_score = window.strip(), score
    return best, max(best_score, 0.0)


def evidence_spans(line: str, records: Sequence[SourceRecord],
                   pack: Optional[EvidencePack] = None,
                   max_spans: int = 3) -> List[Dict]:
    """Choose one explicit best span per source before entailment is decided.

    Number agreement participates only in the existing ranking bonus; no
    threshold is weakened.  The selected `passage` is later fed verbatim to C.
    """
    body = claim_body(line)
    if not body:
        return []
    wanted = _numbers(body)
    out: List[Dict] = []
    for record in records:
        chunks: List[Tuple[str, str, str]] = []
        if pack is not None:
            for passage in getattr(pack, "passages", []) or []:
                if getattr(passage, "source_id", "") != record.source_id:
                    continue
                chunk = (getattr(passage, "text", "") or "").strip()
                if chunk:
                    chunks.append((chunk,
                                   getattr(passage, "locator", "") or "",
                                   "passage"))
        snippet = (record.snippet or "").strip()
        if snippet:
            chunks.append((snippet, record.locator or "", "snippet"))

        best: Optional[Dict] = None
        for chunk_text, locator, kind in chunks:
            window, score = _best_window(body, chunk_text)
            if not window:
                continue
            low = window.lower()
            hits = [n for n in wanted if n in low]
            matched_all = bool(wanted) and len(hits) == len(wanted)
            entailment_score = float(score) + (0.20 if matched_all else 0.0)
            where = (locator or record.locator or "").strip()
            if not where:
                where = ("full text ka padha gaya hissa (exact page ka pata nahi)"
                         if kind == "passage"
                         else "abstract/snippet (exact page ka pata nahi)")
            candidate = {
                "source_id": record.source_id,
                "passage": window,
                "locator": where,
                "span_kind": kind,
                "match": round(float(score), 4),
                "entailment_score": round(entailment_score, 4),
                "numbers_matched": len(hits),
                "numbers_total": len(wanted),
                "access_depth": _access_depth_of(record),
            }
            if best is None or (
                candidate["entailment_score"], candidate["match"]
            ) > (best["entailment_score"], best["match"]):
                best = candidate
        if best is not None:
            out.append(best)
    out.sort(
        key=lambda item: (item.get("entailment_score", 0.0), item.get("match", 0.0)),
        reverse=True,
    )
    return out[:max_spans]


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
def check_c_span(claim: str, span: Optional[Dict]) -> Check:
    """Evaluate C against one already-selected exact evidence span only."""
    c = Check("C", CHECK_LABELS["C"])
    body = claim_body(claim)
    if len(body) < 20:
        c.status = UNKNOWN
        c.detail = "claim itna chhota hai ki uska matlab hi nahi nikalta"
        return c
    if not span:
        c.status = UNKNOWN
        c.detail = "koi exact evidence span select nahi hua, isliye support check nahi hua"
        return c
    span_text = str(span.get("passage") or "").strip()
    if len(span_text) < _MIN_TEXT_CHARS:
        c.status = UNKNOWN
        c.detail = ("selected evidence span bahut chhota/khali hai, isliye claim ka "
                    "support check nahi ho saka")
        return c

    wanted = _numbers(body)
    score = _similarity(body, span_text)
    low = span_text.lower()
    hits = [n for n in wanted if n in low]
    matched_all = bool(wanted) and len(hits) == len(wanted)
    effective = score + (0.20 if matched_all else 0.0)
    # Relaxed numeric threshold sirf tab, jab claim ke SAARE numbers isi span mein
    # exact mile hon. Pehle yahan `if wanted` tha: claim mein number hone se hi
    # bar 0.30 se 0.12 gir jaata tha, chahe ek bhi number span mein na mile —
    # yaani "same-ish numbers, bilkul alag matlab" wala text bhi genuine support
    # ban jaata tha. Numbers adhoore mile to poora text-match hi maangte hain.
    threshold = _ENTAIL_SIM_WITH_NUM if matched_all else _ENTAIL_SIM
    sid = str(span.get("source_id") or "?")
    locator = str(span.get("locator") or "").strip()
    note = (f"{len(hits)}/{len(wanted)} number exact span mein mile, text-match {score:.2f}"
            if wanted else f"text-match {score:.2f}")
    where = f" ({locator})" if locator else ""
    if effective >= threshold:
        c.status = PASS
        c.detail = f"{sid} ke exact evidence span{where} se support mila — {note}"
    else:
        c.status = FAIL
        c.detail = f"{sid} ke exact evidence span{where} mein support nahi dikha — {note}"
    return c


def check_c(claim: str, records: Sequence[SourceRecord],
            pack: Optional[EvidencePack] = None) -> Tuple[Check, str]:
    """Choose explicit spans first, then evaluate C only on those exact spans."""
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

    spans = evidence_spans(claim, records, pack, max_spans=max(3, len(records)))
    if not spans:
        c.status = UNKNOWN
        c.detail = ("cited source ka text humare paas nahi hai (sirf metadata/"
                    "chhota snippet), isliye claim ka support check nahi ho saka")
        return c, ""

    evaluated = [(span, check_c_span(claim, span)) for span in spans]
    decisive = [(span, checked) for span, checked in evaluated
                if checked.status != UNKNOWN]
    if not decisive:
        return evaluated[0][1], ""
    decisive.sort(
        key=lambda pair: (
            1 if pair[1].status == PASS else 0,
            float(pair[0].get("entailment_score", 0.0) or 0.0),
            float(pair[0].get("match", 0.0) or 0.0),
        ),
        reverse=True,
    )
    best_span, best_check = decisive[0]
    return best_check, (str(best_span.get("source_id") or "")
                        if best_check.status == PASS else "")


# ── D: reading depth ────────────────────────────────────────────────────────
def check_d(records: Sequence[SourceRecord]) -> Check:
    """
    Kitni gehrai tak padha gaya — aur patent ka apna alag rule.

    PATENT (₹0 patent batch, point 4 + 6): patent ka full text padhna "reading
    depth" ke liye asli kaam hai, par ye check aage `verify_claim()` mein
    `genuine_support` ka darwaza kholta hai. Patent claims LEGAL dawe hote hain,
    experiment ka nateeja nahi — isliye jab cited sources SIRF patent hain, ye
    check PASS nahi hota. Wo UNKNOWN par rukta hai aur detail mein saaf likhta
    hai ki patent ke claims process hue (yaani read depth chhupayi nahi ja rahi,
    sirf uska matlab imaandaari se bataya ja raha hai).
    """
    c = Check("D", CHECK_LABELS["D"])
    if not records:
        c.status = UNKNOWN
        c.detail = "koi source nahi"
        return c
    levels: Dict[str, str] = {}
    patent_ids: List[str] = []
    for record in records:
        try:
            levels[record.source_id] = record.reading_level()
        except Exception:                   # pragma: no cover - defensive
            levels[record.source_id] = "metadata"
        if getattr(record, "is_patent", False):
            patent_ids.append(record.source_id)
    detail = ", ".join(f"{sid}={lvl}" for sid, lvl in levels.items())
    patent_only = bool(patent_ids) and len(patent_ids) == len(levels)
    full = [sid for sid, lvl in levels.items()
            if lvl == "full_text" and sid not in patent_ids]
    if full:
        c.status = PASS
        c.detail = f"poora text padha gaya: {', '.join(full)} ({detail})"
        # §12 ki honesty: badi PDF page-by-page padhi ho to wahi likho.
        notes = [r.read_note for r in records
                 if r.source_id in full and (r.read_note or "").strip()]
        if notes:
            c.detail += f" — dhyan rahe: {notes[0][:120]}"
        if patent_ids:
            c.detail += (f"; patent {', '.join(patent_ids)} sirf context hai "
                         f"(legal dawa, proof nahi)")
        return c
    if patent_only:
        deep = [sid for sid in patent_ids
                if levels.get(sid) in ("claims", "full_text")]
        c.status = UNKNOWN
        if deep:
            c.detail = (f"patent ka text process hua ({', '.join(deep)}) par "
                        f"evidence SIRF patent hai ({detail}) — patent ke claims "
                        f"legal dawe hain, experiment ka proof nahi, isliye ye "
                        f"'genuine support' nahi ban sakta")
        else:
            c.detail = (f"sirf patent metadata/abstract mila ({detail}) — patent "
                        f"ke claims process hi nahi hue")
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


# ── §8: "source ne ULTA kaha" — support se alag baat ─────────────────────────
def claim_contradiction_from_spans(
        line: str, spans: Sequence[Dict]) -> Tuple[bool, str, Dict]:
    """Detect an opposite stance only on an explicit claim-level span.

    Source-wide concatenation is forbidden here: a distant paragraph must not
    bleed into the canonical passage selected for this claim. The same existing
    semantic floor is retained, and a positive result carries exact provenance.
    """
    body = claim_body(line)
    if len(body) < 20 or not spans:
        return False, "", {}
    try:
        from .contradiction import ContradictionEngine
        engine = ContradictionEngine()
    except Exception:                       # pragma: no cover - defensive
        return False, "", {}
    claim_stance, _ = engine.stance(body)
    if claim_stance not in ("SUPPORT", "OPPOSE"):
        return False, "", {}

    for raw_span in spans:
        span = dict(raw_span or {})
        passage = str(span.get("passage") or "").strip()
        locator = str(span.get("locator") or "").strip()
        source_id = str(span.get("source_id") or "").strip()
        if (len(passage) < _MIN_TEXT_CHARS or not source_id
                or not locator):
            continue
        match = float(_similarity(body, passage))
        if match < _ENTAIL_SIM:
            continue
        source_stance, cues = engine.stance(passage)
        if source_stance not in ("SUPPORT", "OPPOSE") or source_stance == claim_stance:
            continue
        audit = dict(span)
        audit.update({
            "claim_stance": claim_stance,
            "source_stance": source_stance,
            "stance_cues": list(cues[:3]),
            "claim_match": round(match, 4),
        })
        where = f" ({locator})" if locator else ""
        cue = ", ".join(cues[:3])
        reason = (f"{source_id} ke exact claim-level evidence span{where} ka "
                  f"stance is claim ke ulta hai (claim={claim_stance}, "
                  f"source={source_stance}"
                  + (f"; ishaara: {cue}" if cue else "") + ")")
        return True, reason, audit
    return False, "", {}


def claim_contradicted(line: str, records: Sequence[SourceRecord],
                       pack: Optional[EvidencePack] = None) -> Tuple[bool, str]:
    """Backward-compatible wrapper, now grounded to selected exact spans."""
    spans = evidence_spans(line, records, pack, max_spans=max(1, len(records)))
    contradicted, reason, _span = claim_contradiction_from_spans(line, spans)
    return contradicted, reason


# ── ek claim = A..E + ek verdict ─────────────────────────────────────────────
def verify_claim(line: str, pack: Optional[EvidencePack] = None,
                 claim_id: str = "", critical: Optional[bool] = None,
                 section: str = "") -> ClaimCheck:
    """Verify a claim through independent per-source A-E chains."""
    ids = cited_ids(line)
    records: List[SourceRecord] = []
    if pack is not None:
        for sid in ids:
            src = pack.by_id(sid)
            if src is not None:
                records.append(src)

    cc = ClaimCheck(text=claim_body(line), cited_ids=list(ids))
    cc.strong_label = bool(_STRONG_LABEL_RE.search(line or ""))
    cc.claim_id = claim_id
    cc.epistemic_type = epistemic_type(line)
    cc.section = section
    cc.critical = bool(cc.strong_label if critical is None else critical)
    cc.spans = evidence_spans(line, records, pack, max_spans=max(3, len(records)))

    paths: List[Tuple[Dict, List[Check]]] = []
    for record in records:
        selected = evidence_spans(line, [record], pack, max_spans=1)
        canonical = dict(selected[0]) if selected else {}
        a = check_a([record.source_id], [record], line)
        b = check_b([record])
        c_check = check_c_span(line, canonical)
        d = check_d([record])
        e = check_e([record])
        checks = [a, b, c_check, d, e]
        path = {
            "source_id": record.source_id,
            "passes_ae": all(item.status == PASS for item in checks),
            "canonical_span": canonical,
            "checks": [item.to_dict() for item in checks],
        }
        paths.append((path, checks))
    cc.source_checks = [dict(path) for path, _ in paths]

    if not paths:
        a = check_a(ids, records, line)
        b = check_b(records)
        c_check, _ = check_c(line, records, pack)
        d = check_d(records)
        e = check_e(records)
        cc.checks = [a, b, c_check, d, e]
        cc.verdict = UNSUPPORTED if not a.ok else CITED_ONLY
        cc.reason = a.detail if not a.ok else c_check.detail
        return cc

    def _rank(item: Tuple[Dict, List[Check]]) -> Tuple[int, int, int, float, str]:
        path, checks = item
        by_key = {check.key: check for check in checks}
        pass_count = sum(1 for check in checks if check.status == PASS)
        span = path.get("canonical_span") or {}
        return (
            1 if path.get("passes_ae") else 0,
            1 if by_key["C"].status == PASS else 0,
            pass_count,
            float(span.get("entailment_score", 0.0) or 0.0),
            str(path.get("source_id") or ""),
        )

    chosen_path, chosen_checks = max(paths, key=_rank)
    chosen_source_id = str(chosen_path.get("source_id") or "")
    cc.checks = chosen_checks
    cc.canonical_span = dict(chosen_path.get("canonical_span") or {})
    contradiction_candidates = [
        dict(path.get("canonical_span") or {})
        for path, _checks in paths
        if path.get("canonical_span")
    ]
    contradicted, contra_why, contradiction_span = claim_contradiction_from_spans(
        line, contradiction_candidates
    )
    cc.contradicted = contradicted
    cc.contradiction_span = dict(contradiction_span or {})
    if cc.status("C") == PASS:
        cc.best_source = chosen_source_id
    if chosen_path.get("passes_ae") and not cc.contradicted:
        cc.supporting_source_id = chosen_source_id

    # Preserve latest-main named audit labels on the exact selected source path.
    label_src = next((record for record in records
                      if record.source_id == chosen_source_id), None)
    if label_src is None and records:
        label_src = records[0]
    if label_src is not None:
        cc.access_label = _access_depth_of(label_src)
        cc.quality_label = _quality_label_of(label_src)

    if contradicted:
        # Keep raw source_checks for audit, but do not expose contradicted proof
        # as accepted supporting evidence.
        cc.supporting_source_id = ""
        cc.verdict = CITED_ONLY
        cc.reason = contra_why
        return cc
    if cc.passes_ae:
        cc.verdict = GENUINE_SUPPORT
        cc.reason = (f"same-source A-E pass: {cc.supporting_source_id}; "
                     f"{cc.check('C').detail}; {cc.check('D').detail}")
        return cc
    if (cc.status("A") == PASS and cc.status("B") == PASS
            and cc.status("C") == PASS and cc.status("E") != FAIL):
        cc.verdict = SOURCE_REPORTED
        cc.reason = (f"{cc.check('C').detail}; par isi source par A-E poore nahi: "
                     f"{cc.check('D').detail}; {cc.check('E').detail}")
        return cc
    cc.verdict = CITED_ONLY
    for key in ("A", "B", "C", "E", "D"):
        item = cc.check(key)
        if item is not None and item.status != PASS:
            cc.reason = item.detail
            break
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

    @property
    def strong_claims(self) -> List[ClaimCheck]:
        return [claim for claim in self.claims if claim.strong_label]

    @property
    def strong_claims_passed(self) -> int:
        return len([claim for claim in self.strong_claims
                    if claim.passes_ae and not claim.contradicted])

    @property
    def strong_claims_failed(self) -> int:
        return len([claim for claim in self.strong_claims
                    if not claim.passes_ae or claim.contradicted])

    @property
    def same_source_ae_passed(self) -> int:
        return len([claim for claim in self.claims
                    if claim.passes_ae and not claim.contradicted])

    @property
    def critical_same_source_ae_passed(self) -> int:
        return len([claim for claim in self.critical_claims
                    if claim.passes_ae and not claim.contradicted])

    @property
    def claim_verification_achievement(self) -> bool:
        """Non-vacuous: at least one critical claim passed same-source A-E."""
        return bool(self.critical_claims) and self.critical_same_source_ae_passed > 0

    @property
    def gate_passed(self) -> bool:
        """Release safety contract: koi unsupported strong label bachna nahi chahiye.

        Zero strong labels par gate pass hona jaan-boojh kar hai: iska matlab
        "claims verified" nahi, sirf itna ki answer ne ESTABLISHED/FACT jaisa
        unsupported strong dawa public nahi chhoda. `gate_applicable` aur
        claim counts alag fields mein is distinction ko audit ke liye rakhte hain.
        """
        return self.strong_claims_failed == 0

    def check_counts(self) -> Dict[str, Dict[str, int]]:
        out: Dict[str, Dict[str, int]] = {}
        for key in ("A", "B", "C", "D", "E"):
            row = {PASS: 0, FAIL: 0, UNKNOWN: 0}
            for cc in self.claims:
                row[cc.status(key)] = row.get(cc.status(key), 0) + 1
            out[key] = row
        return out

    # ── §8 — result-level ginti (verdict counters ke SAATH, unki jagah nahi) ──
    def result_counts(self) -> Dict[str, int]:
        row = {name: 0 for name in CLAIM_RESULTS}
        for cc in self.claims:
            row[cc.result] = row.get(cc.result, 0) + 1
        return row

    @property
    def contradicted(self) -> int:
        return len([c for c in self.claims if c.contradicted])

    @property
    def critical_claims(self) -> List[ClaimCheck]:
        return [c for c in self.claims if c.critical]

    @property
    def unsupported_critical(self) -> List[ClaimCheck]:
        """
        Wo critical claims jo tik NAHI rahe.

        `UNABLE TO VERIFY` yahan JAAN-BOOJH KAR nahi hai — wo "galat" nahi,
        "check nahi ho saka" hai, aur uski apni ginti alag jaati hai.
        """
        return [c for c in self.critical_claims
                if c.result in (CLAIM_UNSUPPORTED, CLAIM_CONTRADICTED)]

    @property
    def unverifiable_critical(self) -> List[ClaimCheck]:
        return [c for c in self.critical_claims
                if c.result == CLAIM_UNVERIFIABLE]

    @property
    def critical_contradicted(self) -> List[ClaimCheck]:
        return [c for c in self.critical_claims if c.contradicted]

    @staticmethod
    def _exact_contradiction_span(span: Dict) -> bool:
        """A contradiction record needs attributable, inspectable opposite text."""
        return bool(
            str((span or {}).get("source_id") or "").strip()
            and str((span or {}).get("locator") or "").strip()
            and len(str((span or {}).get("passage") or "").strip()) >= _MIN_TEXT_CHARS
            and (span or {}).get("claim_stance") in ("SUPPORT", "OPPOSE")
            and (span or {}).get("source_stance") in ("SUPPORT", "OPPOSE")
            and (span or {}).get("claim_stance") != (span or {}).get("source_stance")
        )

    @property
    def critical_contradiction_spans_complete(self) -> Optional[bool]:
        """None = no critical contradiction; otherwise all need exact provenance."""
        if not self.critical_contradicted:
            return None
        return all(self._exact_contradiction_span(c.contradiction_span)
                   for c in self.critical_contradicted)

    @property
    def critical_without_spans(self) -> List[ClaimCheck]:
        return [c for c in self.critical_claims if not c.has_spans]

    @property
    def critical_spans_complete(self) -> Optional[bool]:
        """None = koi critical claim hi nahi mila (yaani check hua hi nahi)."""
        if not self.critical_claims:
            return None
        return not self.critical_without_spans

    def critical_claim_spans(self) -> List[Dict]:
        """Critical-claim audit rows with the canonical span that drove C."""
        out: List[Dict] = []
        for cc in self.critical_claims:
            out.append({
                "claim_id": cc.claim_id,
                "claim": cc.text[:220],
                "result": cc.result,
                "section": cc.section,
                "cited_ids": list(cc.cited_ids),
                "text": cc.text,
                "source_ids": list(cc.cited_ids),
                "epistemic_type": cc.epistemic_type,
                "entailment": cc.entailment_label,
                "access_depth": cc.access_depth_label,
                "source_quality": cc.source_quality_label,
                "contradicted": bool(cc.contradicted),
                "contradiction_span": (dict(cc.contradiction_span)
                                       if cc.contradiction_span else {}),
                "evidence_spans": [dict(s) for s in cc.spans],
                "supporting_source_id": cc.supporting_source_id,
                "same_source_ae_passed": bool(cc.passes_ae and not cc.contradicted),
                "verified_support": bool(cc.passes_ae and not cc.contradicted),
                "canonical_span": dict(cc.canonical_span) if cc.canonical_span else {},
                "spans": [dict(s) for s in cc.spans],
                "spans_present": cc.has_spans,
            })
        return out

    def supporting_source_ids(self, critical_only: bool = False) -> List[str]:
        """Only sources that passed A-E together may count as supporting sources."""
        out: List[str] = []
        for cc in self.claims:
            if critical_only and not cc.critical:
                continue
            if cc.contradicted:
                continue
            sid = cc.supporting_source_id if cc.passes_ae else ""
            if sid and sid not in out:
                out.append(sid)
        return out

    def to_dict(self) -> Dict:
        return {"total_claims": self.total, "genuine_support": self.genuine,
                "source_reported": self.source_reported,
                "cited_only": self.cited_only, "unsupported": self.unsupported,
                "entailment_not_checkable": self.unknown_entailment,
                "genuine_ratio": self.genuine_ratio,
                "gate_passed": self.gate_passed,
                "gate_applicable": bool(self.strong_claims),
                "strong_claims_checked": len(self.strong_claims),
                "strong_claims_passed": self.strong_claims_passed,
                "strong_claims_failed": self.strong_claims_failed,
                "same_source_ae_passed": self.same_source_ae_passed,
                "critical_claims_same_source_ae_passed": self.critical_same_source_ae_passed,
                "claim_verification_achievement": self.claim_verification_achievement,
                "check_counts": self.check_counts(),
                # §8 — claim-level results, spans aur critical accounting
                "result_counts": self.result_counts(),
                "contradicted_claims": self.contradicted,
                "critical_contradicted_claims": len(self.critical_contradicted),
                "critical_contradiction_spans_complete":
                    self.critical_contradiction_spans_complete,
                "critical_claims": len(self.critical_claims),
                "unsupported_critical_claims": len(self.unsupported_critical),
                "unverifiable_critical_claims": len(self.unverifiable_critical),
                "critical_claim_spans_complete": self.critical_spans_complete,
                "critical_claim_spans": self.critical_claim_spans(),
                "sources_supporting_claims": self.supporting_source_ids(),
                "sources_supporting_critical_claims":
                    self.supporting_source_ids(critical_only=True),
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
        # §8/§9 — har claim ka apna nateeja, ek hi jagah, alag-alag.
        results = self.result_counts()
        if self.total:
            lines.append("")
            lines.append("**Claim-level nateeje (alag-alag, mile-jule nahi):**")
            for name in CLAIM_RESULTS:
                lines.append(f"- {name}: {results.get(name, 0)} — "
                             f"{CLAIM_RESULT_EXPLAIN.get(name, '')}")
            crit = self.critical_claims
            if crit:
                missing = len(self.critical_without_spans)
                lines.append("")
                lines.append(
                    f"Inme {len(crit)} claim CRITICAL hain (nateeja inhi par tika "
                    f"hai): {len(self.unsupported_critical)} support nahi kar paaye, "
                    f"{len(self.unverifiable_critical)} ka check ho hi nahi saka, "
                    f"{len(crit) - missing}/{len(crit)} ke saath asli evidence span "
                    f"maujood hai.")
            else:
                lines.append("")
                lines.append("Koi claim CRITICAL nahi nikla, isliye critical-claim "
                             "wali ginti chali hi nahi (zero nahi — 'check nahi hua').")
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
    Answer ke har bounded FACTUAL labelled claim block par A–E chalao.

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
    # PR #16 ka bounded block + section tracking dono chahiye: block se
    # multiline claim ka citation nahi tootta, section se "critical claim"
    # ka faisla hota hai (seedha jawab / conclusion ki dava critical hai).
    section_at = []
    current_section = ""
    for raw in (text or "").splitlines():
        heading = _HEADING_RE.match(raw)
        if heading:
            current_section = " ".join(heading.group(1).split())
        section_at.append(current_section)
    covered: List[tuple] = []
    for start, end, block in labelled_claim_spans(text):
        if len(block) < 25:
            continue
        labels = _LABEL_RE.findall(block)
        if not labels:
            continue
        types = {label_to_claim_type(lbl) for lbl in labels}
        if not (types & _GROUNDED_TYPES):
            continue
        section = section_at[start] if start < len(section_at) else ""
        cid = f"CL{len(report.claims) + 1:03d}"
        # Critical = strong label YA seedha-jawab/conclusion section ki dava.
        critical = (bool(_STRONG_LABEL_RE.search(block))
                    or bool(_CRITICAL_SECTION_RE.search(section)))
        cc = verify_claim(block, pack, claim_id=cid, critical=critical,
                          section=section)
        report.claims.append(cc)
        covered.append((start, end))
        if cc.strong_label and (not cc.passes_ae or cc.contradicted):
            report.overclaims.append(cc)
        if len(report.claims) >= max_claims:
            break
    # §8 — doosra pass: "Seedha jawab" / final-conclusion section ki wo line jo
    # source cite karti hai par LABEL bhool gayi.
    #
    # Kyun: pehle sirf labelled lines ginti thi, isliye jab model ne apne nateeje
    # wali line par label nahi lagaya to poori report `critical_claims: 0` aur
    # `sources_supporting_critical_claims: 0` bolti thi — jo padhne mein "nateeje
    # ke peeche koi source nahi" jaisa lagta hai, jabki asli baat ye thi ki us
    # line ka label gayab tha. Live dark-matter run ki galti bilkul yahi thi.
    #
    # Label ab bhi banaya nahi jaata: `epistemic_type` saaf-saaf "unlabelled"
    # rehta hai, aur strong-label gate (overclaim) in par nahi lagta. Sirf A–E
    # chalti hai, taaki nateeje ke peeche ka saboot record mein aa jaaye.
    if len(report.claims) < max_claims:
        seen_bodies = {c.text.strip().lower() for c in report.claims if c.text}
        for idx, raw in enumerate((text or "").splitlines()):
            section = section_at[idx] if idx < len(section_at) else ""
            if not _CRITICAL_SECTION_RE.search(section):
                continue
            if _HEADING_RE.match(raw) or _LABEL_RE.search(raw):
                continue
            if not cited_ids(raw):
                continue
            body = claim_body(raw)
            if len(body) < 40:                 # aadhi line dava nahi hoti
                continue
            if any(s <= idx < e for s, e in covered):
                continue
            # Ek hi baat "Seedha jawab" aur "final conclusion" dono mein likhi ho
            # to wo EK dava hai — dobara ginne se counter jhootha bada dikhta.
            if body.strip().lower() in seen_bodies:
                continue
            seen_bodies.add(body.strip().lower())
            cid = f"CL{len(report.claims) + 1:03d}"
            report.claims.append(verify_claim(raw.strip(), pack, claim_id=cid,
                                              critical=True, section=section))
            covered.append((idx, idx + 1))
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


# ── final strict label contract (integration se aligned) ─────────────────────
# Niyam (2026-08-21): poora text padh liya gaya ho, PAR us text mein claim ka
# support saaf na mile, to strong label ([ESTABLISHED FACT] / [FACT] / [STRONG
# EVIDENCE]) bach nahi sakta — aur uski jagah `[SOURCE-REPORTED]` bhi galat hai,
# kyunki "source ye report karta hai" ek dava hai jo us source ne kiya hi nahi.
# Sahi label `[UNVERIFIED]` hai.
#
# Ye pass jaan-boojh kar `claim_labels.downgrade()` se ALAG rakha gaya hai:
# claim_labels ka kaam READING DEPTH hai (abstract-only → SOURCE-REPORTED), aur
# uska default behaviour (`check_entailment=False`) waisa hi chhoda gaya hai.
# Ye pass sirf support/entailment ke saaf FAIL par lagta hai; jahan support check
# HO HI NA SAKE wahan chup rehta hai (`entailment_blocked` unknown par False).
_STRICT_LABEL = "[UNVERIFIED]"


def strict_label_line(line: str,
                      pack: Optional[EvidencePack] = None) -> Tuple[str, bool]:
    """
    Ek line par strict rule lagao: `(nayi_line, badla_gaya)`.

    Text kabhi nahi kaata jaata — sirf label badalta hai, taaki content na khoye.
    """
    raw = line or ""
    if not _STRONG_LABEL_RE.search(raw):
        return raw, False
    if not entailment_blocked(raw, pack):
        return raw, False
    return _STRONG_LABEL_RE.sub(_STRICT_LABEL, raw), True


def enforce_strict_labels(text: str, pack: Optional[EvidencePack] = None
                          ) -> Tuple[str, Dict]:
    """
    Poore answer par strict rule. Returns `(naya_text, report)`.

    report: `checked` (kitni lines par strong label tha), `to_unverified`
    (kitni [UNVERIFIED] hui), `details` (max 8 chhoti lines) aur `note` (ek line
    ka human-readable summary — "" agar sab theek).
    """
    report: Dict = {"checked": 0, "to_unverified": 0, "details": [], "note": ""}
    body = text or ""
    if not body.strip() or pack is None:
        return body, report

    lines = body.splitlines()
    spans = {start: (end, block) for start, end, block in labelled_claim_spans(body)}
    out_lines: List[str] = []
    index = 0
    while index < len(lines):
        span = spans.get(index)
        if span is None:
            out_lines.append(lines[index])
            index += 1
            continue

        end, block = span
        raw = lines[index]
        if not _STRONG_LABEL_RE.search(raw):
            out_lines.extend(lines[index:end])
            index = end
            continue
        report["checked"] += 1
        changed = entailment_blocked(block, pack)
        new_line = _STRONG_LABEL_RE.sub(_STRICT_LABEL, raw) if changed else raw
        out_lines.append(new_line)
        out_lines.extend(lines[index + 1:end])
        if not changed:
            index = end
            continue
        report["to_unverified"] += 1
        if len(report["details"]) < 8:
            new_block = "\n".join([new_line] + lines[index + 1:end])
            snippet = re.sub(r"^[#\s\-\*\d\.]+", "", new_block).strip()
            snippet = " ".join(snippet.split())
            report["details"].append(snippet[:150])
        index = end
    if report["to_unverified"]:
        report["note"] = (
            f"{report['to_unverified']}/{report['checked']} 'established' dave "
            f"[UNVERIFIED] kar diye gaye — un sources ka poora text padha gaya "
            f"tha, par us text mein ye baat nahi mili.")
    return "\n".join(out_lines), report
