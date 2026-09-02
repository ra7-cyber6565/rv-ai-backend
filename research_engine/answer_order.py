"""
§12 — jawab ka FIXED order aur "APP ORIGINAL RESEARCH LAB" ki alag jagah.

Kyun ye module bana (dark-matter run ki asli dikkat):
  1. App ki khud ki hypotheses report ke beech mein, established evidence ke
     saath mil kar chhap rahi thi — padhne wale ko lagta tha ki wo bhi research
     ka nateeja hai. Ab wo ek ALAG section mein jaati hain, heading bilkul
     `## APP ORIGINAL RESEARCH LAB` (yahi shabd, kuch aur nahi), aur uske
     pehli line par saaf warning.
  2. "Calculations" section tabhi chhapta tha jab hisaab ban jaaye. Na banne par
     section gayab — aur gayab section se user ko pata hi nahi chalta ki hisaab
     hua tha ya nahi. Ab section HAMESHA rehta hai; na bane to wahan WAJAH
     likhi jaati hai.
  3. Section ke naam sirf Hinglish mein the, isliye contract (§4) ke canonical
     naam se match nahi karte the aur "sections poore hain?" wala check
     hamesha fail rehta tha. Ab heading dono deti hai: pehle canonical naam,
     phir "—" ke baad wahi baat aasaan Hinglish mein.

Ye file jaan-boojh kar pure-Python hai (koi network, koi model), taaki offline
test ho sake. Sirf naam/order/`##` heading ka hisaab — content yahan nahi banta.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

# (key, canonical naam, user ko dikhne wali heading, pehchan ke aliases)
# Order = §12 ka mandatory order. Index hi order hai.
CANONICAL_SECTIONS: Tuple[Tuple[str, str, str, Tuple[str, ...]], ...] = (
    ("direct_answer", "Seedha jawab", "Seedha jawab",
     ("seedha jawab", "direct answer")),
    ("established_knowledge", "Established knowledge",
     "Established knowledge — research se kya pata chala?",
     ("established knowledge", "research se kya pata chala",
      "established evidence")),
    ("supporting_evidence", "Supporting evidence",
     "Supporting evidence — evidence kya kehta hai?",
     ("supporting evidence", "evidence kya kehta hai")),
    ("counterevidence", "Counterevidence",
     "Counterevidence — iske against kya mila?",
     ("counterevidence", "counter evidence", "counter-evidence",
      "iske against kya mila", "evidence against")),
    ("calculations", "Calculations",
     "Calculations — formula, inputs, units aur assumptions",
     ("calculations", "hisaab", "quantitative checks")),
    ("unknowns", "Unknowns", "Unknowns — kya abhi unknown hai?",
     ("unknowns", "kya abhi unknown hai", "what remains unknown")),
    ("conclusion", "Evidence-based conclusion",
     "Evidence-based conclusion — final conclusion",
     ("evidence-based conclusion", "evidence based conclusion",
      "final conclusion")),
    ("original_lab", "APP ORIGINAL RESEARCH LAB", "APP ORIGINAL RESEARCH LAB",
     ("app original research lab", "humari hypotheses",
      "app-generated research hypotheses")),
    ("audit", "Audit and limits",
     "Audit and limits — research quality aur technical audit",
     ("audit and limits", "audit & limits", "research quality",
      "technical audit")),
    ("sources", "Sources", "Sources", ("sources", "references")),
)

SECTION_KEYS: Tuple[str, ...] = tuple(k for k, _, _, _ in CANONICAL_SECTIONS)
CANONICAL_NAMES: Tuple[str, ...] = tuple(n for _, n, _, _ in CANONICAL_SECTIONS)
DISPLAY_HEADINGS: Tuple[str, ...] = tuple(h for _, _, h, _ in CANONICAL_SECTIONS)
_BY_KEY: Dict[str, Tuple[str, str, str, Tuple[str, ...]]] = {
    row[0]: row for row in CANONICAL_SECTIONS
}

# §12 — ye heading shabd-ba-shabd yahi rehni hai. App ki apni soch ko dhoondhna
# aasan hona chahiye, isliye iska naam translate/chhota nahi karte.
LAB_HEADING = "APP ORIGINAL RESEARCH LAB"
LAB_WARNING = (
    "⚠️ **Ye hissa app ki KHUD ki soch hai — research ka established fact "
    "nahi.** Neeche di gayi hypotheses kisi paper ka nateeja nahi hain; ye is "
    "app ne mile hue evidence se banayi hain aur inka test hona baaki hai. "
    "Inhe fact, discovery ya \"proven\" ki tarah na padhein."
)
# Calculations section kabhi gayab nahi hota — na bane to wajah likhni hai.
NO_CALC_REASONS: Dict[str, str] = {
    "not_asked": "Is sawaal mein koi hisaab (number/estimate) maanga nahi gaya "
                 "tha, aur bina zaroorat ke number banana theek nahi — isliye "
                 "yahan koi calculation nahi hai.",
    "no_inputs": "Hisaab maanga gaya tha, par sources se zaroori inputs (value "
                 "+ unit) nahi mile. Bina input ke number likhna andaza hota, "
                 "isliye jaan-boojh kar khaali chhoda gaya.",
    "no_reasoning": "Reasoning model is run mein poora nahi chala, isliye "
                    "calculation nahi ban paayi. Ye 'hisaab galat nikla' nahi "
                    "hai — hisaab hua hi nahi.",
}

_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)
_TOP_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _norm(title: str) -> str:
    """Heading ko match karne layak banao — shabd nahi badalte, sirf safai."""
    text = str(title or "").strip().lstrip("#").strip()
    text = re.sub(r"^[\d]+[\.\)]\s*", "", text)
    text = re.sub(r"[*_`#]", "", text)
    text = "".join(ch for ch in text if ch.isalnum() or ch.isspace()
                   or ch in "-/?&,:()'—–")
    return " ".join(text.lower().split())


def canonical_key(title: str) -> str:
    """Ek heading kis canonical section ki hai — warna "" (extra section).

    Pehle poora naam, phir alias. Sabse lamba alias pehle dekha jaata hai taaki
    "counter evidence" ko "evidence" wale chhote alias se pehle match mile.
    """
    text = _norm(title)
    if not text:
        return ""
    for key, name, _display, _aliases in CANONICAL_SECTIONS:
        if text == _norm(name):
            return key
    best_key, best_len = "", 0
    for key, _name, _display, aliases in CANONICAL_SECTIONS:
        for alias in aliases:
            if alias in text and len(alias) > best_len:
                best_key, best_len = key, len(alias)
    return best_key


def display_heading(key: str) -> str:
    row = _BY_KEY.get(key)
    return row[2] if row else ""


def canonical_name(key: str) -> str:
    row = _BY_KEY.get(key)
    return row[1] if row else ""


def top_headings(answer_text: str) -> List[str]:
    """Sirf `##` (top-level) headings, jaise ke waise."""
    return [" ".join(m.strip().split())
            for m in _TOP_HEADING_RE.findall(answer_text or "")]


def section_keys_in_order(answer_text: str) -> List[str]:
    """Jawab mein canonical sections kis kram mein aaye (extra ignore)."""
    out: List[str] = []
    for heading in top_headings(answer_text):
        key = canonical_key(heading)
        if key and key not in out:
            out.append(key)
    return out


def order_report(answer_text: str) -> Dict:
    """
    §12 ka deterministic audit: kaun-kaunsa section hai, kis kram mein, aur
    kya galat hai. Koi text badalta nahi — sirf sach batata hai.

    `None` yahan nahi aata: text diya gaya hai to jawab bhi pakka hai.
    """
    present = section_keys_in_order(answer_text)
    missing = [k for k in SECTION_KEYS if k not in present]
    expected = [k for k in SECTION_KEYS if k in present]
    misplaced: List[Tuple[str, str]] = []
    if present != expected:
        for index, key in enumerate(present):
            want = expected[index] if index < len(expected) else ""
            if want and want != key:
                misplaced.append((key, want))
    headings = top_headings(answer_text)
    duplicates = sorted({k for k in present
                         if sum(1 for h in headings
                                if canonical_key(h) == k) > 1})
    lab_exact = f"## {LAB_HEADING}" in (answer_text or "")
    lab_warned = False
    if lab_exact:
        block = (answer_text or "").split(f"## {LAB_HEADING}", 1)[1]
        head = block.split("\n##", 1)[0][:600].lower()
        lab_warned = ("app ki khud ki soch" in head
                      or "established fact nahi" in head)
    return {
        "present": present,
        "missing": missing,
        "missing_names": [canonical_name(k) for k in missing],
        "order_ok": not misplaced,
        "misplaced": misplaced,
        "duplicates": duplicates,
        "all_present": not missing,
        # §12/§13 — app ki apni soch ka section naam se bhi alag dikhna chahiye
        # aur uske sar par warning honi chahiye.
        "lab_heading_exact": lab_exact,
        "lab_warning_present": lab_warned,
        "sections_present_names": [canonical_name(k) for k in present],
    }


def _spans(answer_text: str) -> List[Tuple[str, int, int]]:
    text = answer_text or ""
    matches = list(_TOP_HEADING_RE.finditer(text))
    spans: List[Tuple[str, int, int]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        spans.append((match.group(1).strip(), match.start(), end))
    return spans


def section_start(answer_text: str, key: str) -> int:
    """Us canonical section ki `##` line ka index — na ho to -1.

    Heading ka exact naam yaad rakhne ki zaroorat nahi rehti: guard aur
    synthesizer dono isi se poochte hain, isliye heading ka wording badalne par
    kuch toota nahi.
    """
    for title, start, _end in _spans(answer_text):
        if canonical_key(title) == key:
            return start
    return -1


def section_body(answer_text: str, key: str) -> str:
    for title, start, end in _spans(answer_text):
        if canonical_key(title) == key:
            block = (answer_text or "")[start:end]
            return block.split("\n", 1)[1].strip() if "\n" in block else ""
    return ""


def order_note(report: Optional[Dict]) -> str:
    """Audit mein jaane wali ek chhoti, seedhi Hinglish line."""
    r = dict(report or {})
    if not r:
        return "Answer ka section order check nahi hua."
    bits: List[str] = []
    total = len(SECTION_KEYS)
    bits.append(f"{len(r.get('present') or [])}/{total} mandatory sections mile")
    if r.get("missing_names"):
        bits.append("nahi mile: " + ", ".join(r["missing_names"]))
    bits.append("order §12 ke hisaab se hai" if r.get("order_ok")
                else "order §12 se hat gaya")
    if not r.get("lab_heading_exact"):
        bits.append(f"'{LAB_HEADING}' heading nahi mili")
    elif not r.get("lab_warning_present"):
        bits.append("app-original section par warning nahi mili")
    return "; ".join(bits) + "."




