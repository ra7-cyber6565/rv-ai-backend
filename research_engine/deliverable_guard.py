"""
#155 — Maanga hua deliverable kabhi chup-chaap gayab na ho.

Asli dikkat (intel ka live Marathon run, 2026-08-30): usne cinematic Punjabi
gaana maanga. CRAFT stage ne gaana banaya bhi aur naapa bhi — `run_craft(...)`
ke report me `final_draft` maujood tha. Par uske BAAD orchestrator ka "6c-3"
block (evidence-first boundary ka doosra stage) poora answer surface
`local_reasoning.compose(...)` se dobara bana deta hai. Us rebuild me gaana
kahin nahi hota. Nateeja: user ko "Seedha jawab" ki jagah ek cover-song CNN
paper ki line dikhti hai, aur uska maanga hua gaana chup-chaap gayab.

Ye module sirf ek kaam ka zimmedaar hai: jo deliverable PEHLE SE BAN CHUKA HAI
wo jawab me dikhe, apne alag label ke saath.

Do baat jo ye module JAAN-BOOJH KAR nahi karta:
  1. Deliverable KHUD NAHI BANATA. `final_draft` khaali ho to yahan se koi
     gaana nahi nikalta — sirf naapi hui wajah likhi jaati hai. `MISSING` ka
     matlab "bana hi nahi" hai, "mila nahi" nahi.
  2. Evidence ki haalat, claim ki ginti aur label ko nahi chhoota. Jo hissa ye
     jodta hai usme `[ESTABLISHED]` / `[STRONG EVIDENCE]` / `[SOURCE-REPORTED]`
     / "VERIFIED" jaisa koi shabd nahi ja sakta — wo creative deliverable hai,
     saboot nahi. Isliye guard claim verification ke BAAD chalta hai: uske
     numbers jaise the waise hi rehte hain.

Non-craft farmaish par (jaise trading model) ye module answer ko CHHOOTA HI
NAHI — text bilkul byte-identical laut jaata hai. Lane isolation ka wahi taala.

0 Gemini call, 0 network, pure Python — wahi report do to wahi text.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .answer_order import SECTION_KEYS, section_start
from .craft import DRAFT_OK, DRAFT_UNMEASURED, DRAFT_WEAK, NO_DRAFT, NOT_RUN

# ── states (paanch, aur paanchon ka matlab alag) ─────────────────────────────
# NOT_ASKED  = kuch banane ki farmaish hi nahi thi → answer chhua bhi nahi gaya
# PRESENT    = deliverable jawab me pehle se maujood tha → kuch joda nahi gaya
# RESTORED   = ban chuka tha par jawab se gayab tha → wapas lagaya gaya
# MISSING    = bana hi nahi → naapi hui wajah likhi gayi, kuch banaya NAHI gaya
# BLOCKED    = ban gaya tha, par usme evidence-label bacha reh gaya → guard ne
#              JAAN-BOOJH KAR nahi lagaya (fail-closed) aur ye chhupaya nahi
NOT_ASKED = "DELIVERABLE_NOT_ASKED"
PRESENT = "DELIVERABLE_PRESENT"
RESTORED = "DELIVERABLE_RESTORED"
MISSING = "DELIVERABLE_MISSING"
BLOCKED = "DELIVERABLE_BLOCKED"
STATES: Tuple[str, ...] = (NOT_ASKED, PRESENT, RESTORED, MISSING, BLOCKED)

SCHEMA_VERSION = "deliverable-guard-1"

# Naam se hi sach — ye jhoote na ho jaayein isliye constant hain, comment nahi.
GEMINI_CALLS = 0
NETWORK_USED = False
IS_EVIDENCE = False
COUNTS_AS_CLAIM = False
GUARD_WROTE_DELIVERABLE = False
QUALITY_PROVEN = False

# Section ka label. Ye jaan-boojh kar kisi bhi evidence-label se milta nahi:
# "CREATIVE-DELIVERABLE" claim_labels ke kisi bhi label me nahi hai, isliye
# claim scanner ise support/fact ki tarah nahi ginta.
LABEL = "[CREATIVE-DELIVERABLE]"
HEADING = "Maanga hua deliverable"
DISPLAY_HEADING = "Maanga hua deliverable — jo banane ko kaha gaya tha"

NOT_EVIDENCE_LINE = (
    "⚠️ **Ye hissa app ka LIKHA HUA deliverable hai — research ka nateeja ya "
    "kisi source ka dava nahi.** Iski jaanch sirf dhaanche ki hui hai (CRAFT "
    "aur SONG LAB ke naap); A–E claim check isse nahi guzra, kyunki ye koi "
    "factual dava hi nahi hai. Ise saboot, evidence ya \"verified\" ki tarah na "
    "padhein."
)

# Ye label is section me kabhi nahi ja sakte. Draft me aa jaayein (model ne
# prose fenced block me daal di ho) to guard deliverable ko HATATA nahi —
# bracket ko round bracket bana deta hai, taaki koi claim scanner ise evidence
# label ki tarah na padhe. Ginti audit me jaati hai. Iske baad bhi ek bracket
# bach jaaye to section joda hi nahi jaata (fail-closed).
BANNED_IN_BLOCK: Tuple[str, ...] = (
    "[ESTABLISHED]", "[ESTABLISHED FACT]", "[FACT]", "[STRONG EVIDENCE]",
    "[SOURCE-REPORTED]", "[SOURCE REPORTED]", "[EVIDENCE]", "[VERIFIED]",
)
_LABEL_RE = re.compile(
    r"\[\s*(ESTABLISHED(?:\s+FACT)?|FACT|STRONG\s+EVIDENCE|"
    r"SOURCE[\s-]?REPORTED|EVIDENCE|UNVERIFIED|VERIFIED|"
    r"MIXED\s+EVIDENCE|WEAK\s+EVIDENCE)\s*\]",
    re.IGNORECASE,
)

# Draft ki 80% line jawab me mil jaayein to use "pehle se maujood" maana jaata
# hai. Ye 100% nahi hai kyunki annotate/label pass line ke aage-peeche marker
# jod deta hai — exact containment par guard wahi gaana DOBARA chipka deta.
_PRESENT_MIN_RATIO = 0.8

_LEADING_HASH_RE = re.compile(r"^([ \t]*)#+[ \t]?", re.MULTILINE)
_CRLF_RE = re.compile(r"\r\n?")

# `direct_answer` ke BAAD ka pehla canonical section — deliverable usse pehle
# baithta hai, taaki user ko gaana shuru me hi mil jaaye. List hand-typed nahi
# hai: §12 ka apna kram (`answer_order.SECTION_KEYS`) hi kram deta hai.
_AFTER_KEYS: Tuple[str, ...] = tuple(k for k in SECTION_KEYS
                                     if k != "direct_answer")

# CRAFT ke status se seedhi, naapi hui wajah. Andaza nahi: jo status aaya usi
# ka matlab likha jaata hai, aur anjaan status par "status: X" hi likhte hain.
_WHY_BY_STATUS: Dict[str, str] = {
    NO_DRAFT: "reasoning pass ne naapne laayak koi draft hi nahi likha",
    NOT_RUN: "CRAFT stage is run me chala hi nahi",
    DRAFT_UNMEASURED: "draft mila par uska naap nahi ho paaya",
    DRAFT_WEAK: "draft ke naap target par nahi the",
    DRAFT_OK: "draft ke naap target par the",
}


# ── chhote helper ────────────────────────────────────────────────────────────
def _text(value: Any) -> str:
    return _CRLF_RE.sub("\n", str(value or ""))


def _lines(block: str) -> List[str]:
    """Sirf kaam ki line — khaali line naap me nahi ginti."""
    return [ln.strip() for ln in _text(block).split("\n") if ln.strip()]


def _neutralise(block: str) -> Tuple[str, int]:
    """Draft ki line ke shuru ke `#` hata do (ginti ke saath).

    Kyun: model ka likha draft agar `## Seedha jawab` se shuru ho jaaye to wo
    ek NAYA top-level section ban jaata hai aur `answer_order` ko lagta hai ki
    canonical section do baar aaya. Lyrics me `#` ka koi kaam nahi hota, isliye
    hataana surakshit hai — par ginti audit me jaati hai, chup-chaap nahi.
    """
    text = _text(block)
    hits = len(_LEADING_HASH_RE.findall(text))
    return (_LEADING_HASH_RE.sub(r"\1", text) if hits else text), hits


def _banned_hit(block: str) -> str:
    upper = block.upper()
    for token in BANNED_IN_BLOCK:
        if token in upper:
            return token
    return ""


def _delabel(block: str) -> Tuple[str, int]:
    """Evidence-jaisa bracket-label round bracket me badal do (ginti ke saath).

    Kyun HATANA nahi: agar draft me `[SOURCE-REPORTED]` aa gaya to do raste
    the — deliverable phenk dena, ya label ko de-fang karna. Pehla rasta user
    ka maanga hua gaana kha jaata hai (wahi bug jo #155 me theek ho raha hai),
    isliye guard bracket badalta hai: `(SOURCE-REPORTED)` kisi claim scanner ke
    liye label nahi hai, par likhawat bachi rehti hai. Ginti audit me jaati hai.
    """
    text = _text(block)
    hits = len(_LABEL_RE.findall(text))
    if not hits:
        return text, 0
    return _LABEL_RE.sub(lambda m: "(" + m.group(1) + ")", text), hits


# ── 1. capture — craft ke report se deliverable ka record ────────────────────
def not_asked(reason: str = "kuch banane ki farmaish nahi thi") -> Dict[str, Any]:
    """Non-craft farmaish ka record. `ensure()` isse answer ko chhoota hi nahi."""
    return {
        "asked": False,
        "form": "",
        "label": "",
        "draft": "",
        "draft_lines": 0,
        "craft_status": "",
        "reason": str(reason or ""),
    }


def capture(craft_report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """CRAFT ke report se: kya maanga gaya tha, aur kya bana.

    Yahan koi text parse nahi hota — jo `run_craft(...)` ne apne naap ke saath
    lauta diya wahi uthaya jaata hai. Isliye "jis draft ka naap chhapa" aur
    "jo draft dikha" kabhi do alag cheez nahi ho sakte.
    """
    report = craft_report if isinstance(craft_report, dict) else {}
    if not report or report.get("ran") is not True:
        return not_asked(str(report.get("reason") or "")
                         or "CRAFT stage chala hi nahi")
    spec = report.get("spec") if isinstance(report.get("spec"), dict) else {}
    form = str(report.get("form") or spec.get("form") or "")
    if not form:
        return not_asked("craft report me koi form nahi tha")
    draft = _text(report.get("final_draft"))
    return {
        "asked": True,
        "form": form,
        "label": str(spec.get("label") or form),
        "draft": draft,
        "draft_lines": len(_lines(draft)),
        "craft_status": str(report.get("status") or ""),
        "reason": "",
    }


# ── 2. jawab me pehle se hai ya nahi ─────────────────────────────────────────
def present_ratio(answer: str, record: Optional[Dict[str, Any]]) -> float:
    """Draft ki kitni line jawab me pehle se maujood hai (0.0 – 1.0)."""
    rec = record if isinstance(record, dict) else {}
    draft_lines = _lines(rec.get("draft"))
    if not draft_lines:
        return 0.0
    body = _text(answer)
    found = sum(1 for line in draft_lines if line in body)
    return found / float(len(draft_lines))


def present_in(answer: str, record: Optional[Dict[str, Any]]) -> bool:
    """Pehle se maujood? Poora draft mile, ya uski `_PRESENT_MIN_RATIO` line."""
    rec = record if isinstance(record, dict) else {}
    draft = _text(rec.get("draft")).strip()
    if not draft:
        return False
    if draft in _text(answer):
        return True
    return present_ratio(answer, rec) >= _PRESENT_MIN_RATIO


# ── 3. section banao (evidence ka koi label isme nahi ja sakta) ──────────────
def build_section(record: Optional[Dict[str, Any]]) -> Tuple[str, Dict[str, int]]:
    """`(section_text, counts)` — khaali draft par `("", counts-zero)`."""
    rec = record if isinstance(record, dict) else {}
    body, hashes = _neutralise(rec.get("draft"))
    body, labels = _delabel(body)
    body = body.strip("\n")
    counts = {"heading_chars_neutralised": hashes,
              "evidence_labels_neutralised": labels}
    if not body.strip():
        return "", {"heading_chars_neutralised": 0,
                    "evidence_labels_neutralised": 0}
    label = str(rec.get("label") or rec.get("form") or "deliverable")
    head = f"## {DISPLAY_HEADING}\n{NOT_EVIDENCE_LINE}\n\n{LABEL} {label}:\n\n"
    return head + body + "\n", counts


def why_missing(record: Optional[Dict[str, Any]]) -> str:
    """CRAFT ke status se naapi hui wajah. Anjaan status par bhi jhooth nahi."""
    rec = record if isinstance(record, dict) else {}
    status = str(rec.get("craft_status") or "")
    known = _WHY_BY_STATUS.get(status)
    if known:
        return known
    if status:
        return f"CRAFT status: {status}"
    return str(rec.get("reason") or "") or "CRAFT ne koi status hi nahi diya"


def build_missing_section(record: Optional[Dict[str, Any]]) -> str:
    """Deliverable bana hi nahi — sirf naapi hui wajah, koi banawat nahi.

    Ye section JAAN-BOOJH KAR khaali haath hai. Yahan ek "thoda-thoda" gaana
    likh dena sabse bada jhooth hota: user ko lagta ki app ne bana diya, jabki
    naap kisi cheez ka hua hi nahi.
    """
    rec = record if isinstance(record, dict) else {}
    label = str(rec.get("label") or rec.get("form") or "deliverable")
    return (
        f"## {DISPLAY_HEADING}\n"
        f"{LABEL} {label}: **is run me bana hi nahi.**\n\n"
        f"- Wajah (naapi hui, andaza nahi): {why_missing(rec)}\n"
        f"- Ye guard khud deliverable NAHI banata, isliye iski jagah koi "
        f"aadha-adhoora {label} likh kar nahi diya gaya.\n"
        f"- Neeche ka research hissa jaisa tha waisa hi hai — usme se kuch "
        f"hataya ya badla nahi gaya.\n"
    )


def _raw(answer: Any) -> str:
    """Answer ko JAISA HAI waisa hi — CRLF normalise NAHI.

    Kyun: `section_start` ke index isi string par lagte hain. Yahan `_text()`
    laga dete to CRLF wale answer me index khisak jaata aur section beech-line
    me ghus jaata.
    """
    return answer if isinstance(answer, str) else str(answer or "")


def _insert_index(answer: str) -> Tuple[int, str]:
    """Kahan ghusega: `direct_answer` ke turant baad, warna sabse aakhir me."""
    raw = _raw(answer)
    for key in _AFTER_KEYS:
        pos = section_start(raw, key)
        if pos >= 0:
            return pos, key
    return len(raw), "end"


def _insert(answer: str, section: str) -> Tuple[str, str]:
    """Section ko ek hi baar, saaf khaali line ke saath ghusa do."""
    raw = _raw(answer)
    idx, where = _insert_index(raw)
    head, tail = raw[:idx], raw[idx:]
    if head.strip():
        head = head.rstrip("\n") + "\n\n"
    block = section if section.endswith("\n") else section + "\n"
    if tail.strip():
        block = block + "\n"
    return head + block + tail, where


# ── 4. audit ka dhaancha (naam se hi sach, har run me wahi keys) ─────────────
def _audit(**kw: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "state": NOT_ASKED,
        "asked": False,
        "form": "",
        "label": "",
        "restored": False,
        "already_present": False,
        "answer_changed": False,
        "present_ratio": 0.0,
        "draft_lines": 0,
        "heading_chars_neutralised": 0,
        "evidence_labels_neutralised": 0,
        "insert_position": "",
        "blocked_token": "",
        "craft_status": "",
        "reason": "",
        "note": "",
        # Ye paanch naap constants se aate hain, haath se nahi likhe jaate —
        # isliye ye audit line kabhi jhooth nahi bol sakti.
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "is_evidence": IS_EVIDENCE,
        "counts_as_claim": COUNTS_AS_CLAIM,
        "guard_wrote_deliverable": GUARD_WROTE_DELIVERABLE,
        "quality_proven": QUALITY_PROVEN,
    }
    base.update(kw)
    return base


# ── 5. ensure — ek hi darwaza, paanch nateeje ────────────────────────────────
def ensure(answer: str,
           record: Optional[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """`(answer, audit)` — maanga hua deliverable jawab me zinda rakho.

    Sab se pehli sharat: farmaish nahi thi to answer **byte-identical** laut
    jaata hai (`answer is result` bhi sach rehta hai). Lane isolation ka taala
    yahi hai — trading ka model maange to ye function ek akshar nahi chhoota.
    """
    raw = _raw(answer)
    rec = record if isinstance(record, dict) else {}

    if rec.get("asked") is not True:
        return answer, _audit(
            state=NOT_ASKED,
            reason=str(rec.get("reason") or "kuch banane ki farmaish nahi thi"),
            note="answer bilkul nahi chhua gaya",
        )

    form = str(rec.get("form") or "")
    label = str(rec.get("label") or form or "deliverable")
    ratio = present_ratio(raw, rec)
    common: Dict[str, Any] = {
        "asked": True,
        "form": form,
        "label": label,
        "craft_status": str(rec.get("craft_status") or ""),
        "draft_lines": int(rec.get("draft_lines") or 0),
        "present_ratio": round(ratio, 4),
    }

    # Guard ka section pehle se laga hai (dobara chala) → kuch nahi jodna.
    if HEADING in raw:
        return answer, _audit(state=PRESENT, already_present=True,
                              note="guard ka section is jawab me pehle se tha",
                              **common)

    # Bana hi nahi → naapi hui wajah, aur kuch nahi. Yahan koi banawat nahi.
    if not _text(rec.get("draft")).strip():
        text, where = _insert(raw, build_missing_section(rec))
        return text, _audit(state=MISSING, answer_changed=True,
                            insert_position=where,
                            reason=why_missing(rec),
                            note="wajah likhi gayi; deliverable banaya NAHI gaya",
                            **common)

    # Pehle se maujood → chhoona hi nahi. (Dobara chipkana sabse gandi bug hai.)
    if present_in(raw, rec):
        return answer, _audit(state=PRESENT, already_present=True,
                              note="deliverable jawab me pehle se maujood tha",
                              **common)

    section, counts = build_section(rec)
    if not section:
        # Draft me kaam ki line thi hi nahi (sirf `#` / khaali line).
        text, where = _insert(raw, build_missing_section(rec))
        return text, _audit(state=MISSING, answer_changed=True,
                            insert_position=where,
                            reason="draft me naapne laayak koi line nahi bachi",
                            note="wajah likhi gayi; deliverable banaya NAHI gaya",
                            **common)

    # Fail-closed: de-fang ke baad bhi evidence-label bacha to lagana hi nahi.
    hit = _banned_hit(section)
    if hit:
        return answer, _audit(state=BLOCKED, blocked_token=hit,
                              reason=f"section me evidence-label bacha: {hit}",
                              note="jaan-boojh kar nahi lagaya (fail-closed)",
                              **dict(common, **counts))

    text, where = _insert(raw, section)
    return text, _audit(state=RESTORED, restored=True, answer_changed=True,
                        insert_position=where,
                        note="ban chuka deliverable jawab se gayab tha, wapas lagaya",
                        **dict(common, **counts))


# ── 6. warnings — user ko saaf-saaf, chup-chaap kuch nahi ────────────────────
def warnings(audit: Optional[Dict[str, Any]]) -> List[str]:
    """Run ke warnings. NOT_ASKED aur PRESENT par jaan-boojh kar khaali list."""
    rec = audit if isinstance(audit, dict) else {}
    state = str(rec.get("state") or "")
    label = str(rec.get("label") or "deliverable")
    out: List[str] = []
    if state == RESTORED:
        out.append(
            f"Maanga hua {label} jawab se gayab ho gaya tha (evidence-first "
            f"boundary ne answer dobara banaya) — guard ne use wapas lagaya. "
            f"Ye hissa app ka LIKHA HUA deliverable hai, research ka saboot nahi."
        )
    elif state == MISSING:
        out.append(
            f"Maanga hua {label} is run me bana hi nahi — wajah: "
            f"{rec.get('reason') or 'CRAFT ne koi status nahi diya'}. Guard ne "
            f"apni taraf se kuch likh kar nahi diya."
        )
    elif state == BLOCKED:
        out.append(
            f"Maanga hua {label} ban gaya tha par usme evidence-jaisa label "
            f"({rec.get('blocked_token') or 'label'}) bacha reh gaya, isliye "
            f"guard ne use jawab me nahi lagaya (fail-closed). Creative "
            f"likhawat ko evidence ka label dena mana hai."
        )
    if int(rec.get("evidence_labels_neutralised") or 0) > 0:
        out.append(
            f"Deliverable me {rec.get('evidence_labels_neutralised')} jagah "
            f"evidence-jaisa bracket-label mila — guard ne bracket badal diya "
            f"taaki wo claim ki tarah na pade. Likhawat hataayi nahi gayi."
        )
    return out


# ── 7. seema — is guard se kya SAABIT nahi hota ──────────────────────────────
def limits() -> List[str]:
    """Imaandaar seema. Ye list chhoti karna = user se sach chhupana."""
    return [
        "Ye guard sirf wahi deliverable dikhata hai jo CRAFT stage pehle se "
        "bana chuka hai — khud ek line bhi nahi likhta. CRAFT khaali to yahan "
        "bhi khaali.",
        "Deliverable ki QUALITY yahan se saabit nahi hoti: naap sirf dhaanche "
        "ka hai (CRAFT + SONG LAB); A–E claim check isse nahi guzra kyunki ye "
        "koi factual dava hi nahi hai.",
        "Guard evidence ki haalat, claim ki ginti aur label nahi badalta — "
        "gaana dikh jaane se research ka bharosa ek rai bhi nahi badhta.",
        "\"Pehle se maujood hai\" ka faisla line-match se hota hai "
        f"({int(_PRESENT_MIN_RATIO * 100)}% line); bahut bhaari re-writing ke "
        "baad guard use naya maan kar dobara laga sakta hai.",
        "Draft ke shuru ke `#` aur evidence-jaise bracket-label badal diye "
        "jaate hain (ginti audit me hai) — isliye likhawat bilkul waisi nahi "
        "rehti jaisi model ne likhi thi.",
        "Ek run me sirf ek deliverable dikhta hai (CRAFT ka final draft); ek "
        "hi farmaish me do cheezein maangi ho to doosri yahan nahi aayegi.",
        "\"Kya maanga gaya tha\" ye CRAFT ke report se aata hai — CRAFT galat "
        "form pakde (gaana vs kavita) to guard bhi wahi galat form dikhayega.",
        "Ye guard sirf deliverable ka hona pakka karta hai; gaana sun-ne "
        "laayak hai ya nahi, ye koi bhi automated naap tay nahi kar sakta.",
    ]


# #149 ka wahi taala: synthesizer isi ginti se slice karta hai, isliye nayi
# seema-line kabhi chupke se kat nahi sakti.
MAX_AUDIT_LIMIT_LINES = len(limits())


# ── 8. public record — API/UI ke liye, sirf naap ─────────────────────────────
def public_record(audit: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Audit ka safe roop. Deliverable ka TEXT yahan nahi jaata — sirf naap."""
    rec = audit if isinstance(audit, dict) else {}
    out = _audit()
    for key in list(out.keys()):
        if key in rec:
            out[key] = rec[key]
    out["state_vocabulary"] = list(STATES)
    out["limits"] = limits()[:MAX_AUDIT_LIMIT_LINES]
    out["warnings"] = warnings(rec)
    return out
