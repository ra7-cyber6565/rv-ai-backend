"""
RequestLedger — "aapne kya maanga tha" vs "kya sach mein mila".

Kyun ye file bani (2026-08-20, live MAXIMUM test ke baad):
Us prompt mein saaf likha tha "kam se kam 3 nayi hypotheses banao",
"mathematical/optimization model banao", aur "second-order effects ki chain
(technology → behaviour → economy → society → environment) do". Report mein
teeno nahi aaye — aur report ne unke MISSING hone ka zikr bhi nahi kiya. Ulta
section 7 mein likha tha: "nayi hypothesis generate nahi ki gayi (zaroorat nahi
thi)". Wo jhooth tha: zaroorat thi, Gemini ki quota khatam ho gayi thi.

Isliye ab do kaam hote hain:
  1. Prompt se explicit deliverables NIKALE jaate hain (rule-based, zero cost,
     koi Gemini call nahi).
  2. Final answer mein ek ledger chhapta hai: kya maanga tha, kya mila, aur na
     mila to ASLI wajah.

Ye module kuch generate nahi karta — sirf ginti karta hai aur sach bolta hai.
Iska poora point yahi hai ki koi bhi maangi hui cheez CHUP-CHAAP fail na ho.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# ── numbers: "3", "teen", "तीन", "३" ─────────────────────────────────────────
_WORD_NUMBERS = {
    "ek": 1, "एक": 1, "one": 1,
    "do": 2, "दो": 2, "two": 2,
    "teen": 3, "तीन": 3, "three": 3,
    "char": 4, "चार": 4, "four": 4,
    "paanch": 5, "panch": 5, "पांच": 5, "पाँच": 5, "five": 5,
    "chhah": 6, "छह": 6, "six": 6,
}
_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_HYP = r"(?:hypothes[ei]s|hypotheses|hypothesis|परिकल्पना(?:एँ|एं|ओं)?)"
_ATLEAST = r"(?:kam[\s\-]?se[\s\-]?kam|कम[\s\-]?से[\s\-]?कम|at\s*least|minimum)"
_NEWISH = r"(?:new|nayi|nai|naye|naya|नई|नयी|नए|नये)?"

_TOKEN = r"([0-9०-९]+|[A-Za-zऀ-ॿ]{2,7})"

# "kam se kam 3 ... hypotheses" / "3 nayi hypotheses" / "hypotheses: at least 3"
_HYP_COUNT_RES = (
    re.compile(_ATLEAST + r"\s*" + _TOKEN + r"[^.\n।]{0,40}?" + _HYP, re.IGNORECASE),
    re.compile(_TOKEN + r"\s*" + _NEWISH + r"\s*" + _HYP, re.IGNORECASE),
    re.compile(_HYP + r"[^.\n।]{0,30}?" + _ATLEAST + r"\s*" + _TOKEN, re.IGNORECASE),
)
_HYP_ANY_RE = re.compile(_HYP, re.IGNORECASE)

# ── mathematical / optimization model ────────────────────────────────────────
# Proximity match, kyunki asli prompt "mathematical/optimization model" likhta
# hai (slash ke saath) aur "गणितीय मॉडल" bhi. Sirf "model" shabd par trigger
# karna galat hoga — "AI model" har doosre prompt mein hota hai.
_MATH_HEAD = r"(mathematic\w*|optimi[sz]ation|optimi[sz]e|quantitative|गणितीय|गणित|समीकरण)"
_MATH_TAIL = r"(model|मॉडल|समीकरण|equation|formula|function|framework|problem|banao|बनाओ)"
_MATH_RES = (
    re.compile(_MATH_HEAD + r"[^\n।]{0,45}?" + _MATH_TAIL, re.IGNORECASE),
    re.compile(_MATH_TAIL + r"[^\n।]{0,45}?" + _MATH_HEAD, re.IGNORECASE),
    re.compile(r"objective\s+function|utility\s+function|cost\s+function",
               re.IGNORECASE),
)

# ── second-order / chain effects ─────────────────────────────────────────────
_SECOND_ORDER_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"second[\s\-]?order", r"दूसरे\s*क्रम", r"second[\s\-]?level",
    r"knock[\s\-]?on", r"ripple\s+effects?", r"cascad\w+",
    r"chain\s+(?:of\s+)?(?:effects?|reactions?|impacts?)",
    r"downstream\s+effects?", r"indirect\s+effects?",
    r"अप्रत्यक्ष\s*प्रभाव", r"क्रमिक\s*प्रभाव", r"श्रृंखला",
))
# "technology → behaviour → economy → society → environment"
_ARROW_CHAIN_RE = re.compile(
    r"(?:[\wऀ-ॿ][\wऀ-ॿ \-]{1,30}?\s*(?:→|->|=>|⇒)\s*){2,}"
    r"[\wऀ-ॿ][\wऀ-ॿ \-]{0,30}")

# ── red team / self-falsification ────────────────────────────────────────────
_RED_TEAM_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"red[\s\-]?team", r"self[\s\-]?critic\w*", r"critique", r"आलोचना",
    r"khud\s+ko\s+galat", r"खुद\s+को\s+गलत", r"falsif\w+",
    r"counter[\s\-]?argument", r"apne\s+jawab\s+ki\s+kami",
))

# ── math model ke variables (prompt se, andaaze se nahi) ─────────────────────
# Asli prompt: "...population density, travel distance, transport mode share,
# energy consumption, emissions, road capacity और travel time को variables
# बनाकर mathematical/optimization model बनाओ". Yaani list STOP-phrase se PEHLE
# hoti hai. Isliye pehle stop-phrase dhoondte hain, phir uske pehle ki list.
_VAR_STOP_RE = re.compile(
    r"(?:ko|को)\s*variables?|as\s+variables?|variables?\s*(?:banakar|बनाकर|"
    r"maankar|मानकर|lekar|लेकर)|variables?\s*(?:ke\s*roop|के\s*रूप)",
    re.IGNORECASE)
_VAR_SPLIT_RE = re.compile(r",|;|·|\band\b|\baur\b|और|तथा", re.IGNORECASE)
_VAR_JUNK_RE = re.compile(
    r"^(?:the|a|an|ye|yeh|ye sab|inhe|inko|jaise|jaise ki|e\.?g\.?|etc\.?|"
    r"इन|इनको|जैसे)$", re.IGNORECASE)


def _num(token: str) -> int:
    token = (token or "").strip().translate(_DEV_DIGITS).lower()
    if token.isdigit():
        try:
            return int(token)
        except ValueError:
            return 0
    return _WORD_NUMBERS.get(token, 0)


def _clean_variable(phrase: str) -> str:
    text = re.sub(r"\s+", " ", (phrase or "")).strip(" .;:-–—()[]\"'")
    # aage-peeche ke connector shabd hata do, andar ke shabd chhedo mat
    text = re.sub(r"^(?:jaise|jaise ki|including|like|यानी|जैसे)\s+", "", text,
                  flags=re.IGNORECASE).strip()
    if not text or _VAR_JUNK_RE.match(text):
        return ""
    words = text.split()
    # 1-5 shabd wale noun phrase hi variable lagte hain; isse lamba text
    # poora vaakya hota hai, variable nahi
    if not (1 <= len(words) <= 5):
        return ""
    if len(text) < 3 or len(text) > 60:
        return ""
    return text


def math_variables(question: str, limit: int = 12) -> List[str]:
    """
    Prompt mein user ne jo variables GINAAYE hain, wahi lauta do.

    Kuch invent nahi hota: stop-phrase ("... ko variables banakar") na mile to
    khaali list jaati hai, aur ledger us halat mein "variables prompt mein
    explicitly nahi ginaaye the" bolta hai — apni marzi ke variables nahi
    thoopta.
    """
    text = question or ""
    match = _VAR_STOP_RE.search(text)
    if not match:
        return []
    head = text[max(0, match.start() - 400):match.start()]
    # sirf aakhri vaakya/line ki list chahiye
    head = re.split(r"[.\n।;]", head)[-1]
    out: List[str] = []
    for piece in _VAR_SPLIT_RE.split(head):
        cleaned = _clean_variable(piece)
        if cleaned and cleaned.lower() not in {v.lower() for v in out}:
            out.append(cleaned)
    return out[:limit]


def chain_steps(question: str) -> List[str]:
    """"technology → behaviour → economy" se steps ki list."""
    match = _ARROW_CHAIN_RE.search(question or "")
    if not match:
        return []
    parts = re.split(r"→|->|=>|⇒", match.group(0))
    return [p.strip(" .-–—") for p in parts if p.strip(" .-–—")][:8]


def hypothesis_count(question: str) -> int:
    """
    Prompt ne kitni hypotheses maangi. 0 = maangi hi nahi.

    Sabse zyada wala number jeetta hai ("kam se kam 3" aur "3 nayi hypotheses"
    dono likhe ho to 3 hi banta hai). Shabd `hypothesis` hai par ginti nahi
    likhi → 1, kyunki "hypothesis banao" ka matlab kam se kam ek hai.
    """
    text = question or ""
    best = 0
    for pattern in _HYP_COUNT_RES:
        for match in pattern.finditer(text):
            for group in match.groups():
                value = _num(group or "")
                if 1 <= value <= 20:
                    best = max(best, value)
    if best:
        return best
    return 1 if _HYP_ANY_RE.search(text) else 0


def _any(patterns, text: str) -> bool:
    return any(p.search(text) for p in patterns)


def parse_requests(question: str) -> Dict:
    """
    Prompt se explicit deliverables nikaalo — rule-based, ek bhi Gemini call
    nahi. Jo saaf-saaf maanga gaya ho wahi yahan aata hai; "shayad chahta hoga"
    wala andaza nahi lagate, warna ledger jhoothi kami dikhane lagega.
    """
    text = question or ""
    count = hypothesis_count(text)
    wants_math = _any(_MATH_RES, text)
    steps = chain_steps(text)
    wants_chain = bool(steps) or _any(_SECOND_ORDER_RES, text)
    return {
        "hypothesis_count": count,
        "wants_hypotheses": count > 0,
        "wants_math_model": wants_math,
        "math_variables": math_variables(text) if wants_math else [],
        "wants_second_order": wants_chain,
        "chain_steps": steps,
        "wants_red_team": _any(_RED_TEAM_RES, text),
    }


def any_explicit(requests: Optional[Dict]) -> bool:
    r = requests or {}
    return bool(r.get("wants_hypotheses") or r.get("wants_math_model")
                or r.get("wants_second_order") or r.get("wants_red_team"))


# ── delivery detection (answer text par, dava par nahi) ──────────────────────
# "=" wali lines ginte hain: ek equation mein kam se kam ek alphabetic term aur
# ek "=" hota hai. Do se kam ho to use "mathematical model" kehna dikhawa hai.
_EQUATION_LINE_RE = re.compile(
    r"^[^\n]{0,200}?[A-Za-zऀ-ॿ][^\n]{0,80}?[=≈∝][^\n]{0,120}$", re.MULTILINE)
_MATH_WORDS_RE = re.compile(
    r"objective\s+function|subject\s+to|minimi[sz]e\s|maximi[sz]e\s|"
    r"decision\s+variable|constraint", re.IGNORECASE)


def looks_like_math_model(text: str) -> bool:
    body = text or ""
    equations = len(_EQUATION_LINE_RE.findall(body))
    if equations >= 2:
        return True
    return equations >= 1 and bool(_MATH_WORDS_RE.search(body))


def looks_like_chain(text: str) -> bool:
    body = text or ""
    if _ARROW_CHAIN_RE.search(body):
        return True
    # "1st order ... 2nd order ... 3rd order" style bhi chain hai
    orders = len(re.findall(r"\b(?:first|second|third|1st|2nd|3rd)[\s\-]?order\b",
                            body, re.IGNORECASE))
    return orders >= 2


# ── prompt block (jo maanga gaya hai, wo model ko DOHRA kar batao) ────────────
def prompt_block(requests: Optional[Dict]) -> str:
    """
    Gemini ke prompt mein jaane wala explicit checklist.

    Kyun zaroori: lambe prompt ke beech mein dabi hui request ("...aur kam se
    kam 3 nayi hypotheses banao...") model se chhoot jaati hai. Isliye use
    aakhir mein alag, chhoti checklist ki tarah phir se diya jaata hai.
    """
    r = requests or {}
    if not any_explicit(r):
        return ""
    lines = ["", "# USER KI EXPLICIT REQUESTS — inme se koi bhi chhoota to jawab adhoora hai"]
    count = int(r.get("hypothesis_count") or 0)
    if count:
        lines.append(
            f"- {count} nayi hypotheses ZAROORI hain (kam nahi). Har ek ke saath: "
            f"Statement, Reasoning, Supporting evidence [S#], Contradicting "
            f"evidence, Prediction (measurable), Falsification condition, "
            f"How to test, Risks, Confidence.")
    if r.get("wants_math_model"):
        variables = r.get("math_variables") or []
        var_line = (", ".join(variables) if variables
                    else "prompt mein jo variables diye gaye hain")
        lines.append(
            f"- Ek ASLI mathematical/optimization model do — sirf baat nahi. "
            f"Variables: {var_line}. Har variable ka symbol define karo, phir "
            f"relations/equations likho (`=` ke saath), objective function aur "
            f"constraints likho, aur batao kaunsa number kis source [S#] se aaya "
            f"aur kaunsa assumption hai. Heading exactly: "
            f"`## Mathematical Model`")
    if r.get("wants_second_order"):
        steps = r.get("chain_steps") or []
        chain = " → ".join(steps) if len(steps) >= 2 else \
            "technology → behaviour → economy → society → environment"
        lines.append(
            f"- Second-order effects ki POORI chain do, step-by-step: {chain}. "
            f"Har step par likho: kya badlega, kis wajah se, kitne samay mein, "
            f"aur uska source [S#] ya [INFERENCE]. Heading exactly: "
            f"`## Second-Order Effects`")
    if r.get("wants_red_team"):
        lines.append(
            "- Red-team / self-falsification zaroori hai: apne hi jawab ki "
            "kamzoriyan, missing evidence aur alternative explanations likho.")
    return "\n".join(lines)


# ── ledger ───────────────────────────────────────────────────────────────────
def _dedupe_reasons(reasons: List[str]) -> List[str]:
    """
    Ek hi baat do-teen baar mat likho.

    Orchestrator kai jagah se wajah bhejta hai (reasoning note, Gemini error,
    hypothesis shortfall) aur unmein se ek badi line ke andar chhoti lines pehle
    se maujood hoti hain. Bina safai ke user ko aisa dikhta tha:

        "... free daily limit khatam ho gayi; 0/3 hypotheses hi ban paayi jo
         aapne maangi thi.; aaj ke liye is model ki free daily limit khatam ho
         gayi; 0/3 hypotheses hi ban paayi jo aapne maangi thi."

    Yahan sirf duplicate aur "kisi badi line ke andar pehle se maujood" wali
    line hatti hai — koi wajah chhupti nahi. Kram wahi rehta hai jo bheja gaya
    tha (deterministic, taaki do run ka jawab same rahe).
    """
    cleaned = [str(r).strip() for r in (reasons or []) if str(r).strip()]
    keep: List[str] = []
    for reason in cleaned:
        low = reason.lower()
        # Pehle se rakhi kisi line mein ye poori baat aa gayi hai? Chhod do.
        if any(low in kept.lower() for kept in keep):
            continue
        # Ye nayi line pehle rakhi chhoti line ko nigal leti hai? Chhoti hata do.
        keep = [kept for kept in keep if kept.lower() not in low]
        keep.append(reason)
    return keep


def _why(reasons: List[str]) -> str:
    reasons = _dedupe_reasons(reasons)
    if not reasons:
        return "Wajah record nahi hui."
    return "Wajah: " + "; ".join(reasons[:3])


def build_ledger(requests: Optional[Dict], delivered: Optional[Dict] = None,
                 reasons: Optional[List[str]] = None) -> Dict:
    """
    Maanga vs mila — ek honest ledger.

    `delivered` keys: hypotheses (int), math_model (bool), second_order (bool),
    red_team (bool). `reasons` mein asli wajah jaati hai (Gemini errors,
    reasoning note) — "shayad" nahi, jo record hua wahi.
    """
    r = requests or {}
    d = delivered or {}
    why = _why(reasons or [])
    items: List[Dict] = []

    asked = int(r.get("hypothesis_count") or 0)
    if asked:
        got = int(d.get("hypotheses") or 0)
        items.append({
            "what": f"{asked} nayi testable hypotheses",
            "got": f"{got}",
            "ok": got >= asked,
            "why": "" if got >= asked else (
                f"{got}/{asked} mili. " + (why if got < asked else "")),
        })
    if r.get("wants_math_model"):
        ok = bool(d.get("math_model"))
        variables = r.get("math_variables") or []
        label = "Mathematical / optimization model"
        if variables:
            label += f" ({len(variables)} variables: {', '.join(variables[:7])})"
        items.append({"what": label, "got": "bana" if ok else "nahi bana",
                      "ok": ok, "why": "" if ok else why})
    if r.get("wants_second_order"):
        ok = bool(d.get("second_order"))
        steps = r.get("chain_steps") or []
        label = "Second-order effects chain"
        if len(steps) >= 2:
            label += " (" + " → ".join(steps[:6]) + ")"
        items.append({"what": label, "got": "mili" if ok else "nahi mili",
                      "ok": ok, "why": "" if ok else why})
    if r.get("wants_red_team"):
        ok = bool(d.get("red_team"))
        items.append({"what": "Red-team / self-falsification pass",
                      "got": "chala" if ok else "nahi chala",
                      "ok": ok, "why": "" if ok else why})

    unmet = [i for i in items if not i["ok"]]
    lines = [
        f"- {'✅' if i['ok'] else '❌'} {i['what']} → **{i['got']}**"
        + (f" — {i['why']}" if i["why"] else "")
        for i in items
    ]
    banner = ""
    if unmet:
        banner = "\n".join(
            ["> ⚠️ **AAPKI REQUEST POORI NAHI HUI — pehle ye padh lo:**"]
            + [f"> - {i['what']} → **{i['got']}**"
               + (f" ({i['why']})" if i["why"] else "") for i in unmet]
            + ["> ",
               "> Neeche jo likha hai wo asli hai, par ye hisse missing hain. "
               "Inhe 'ho gaya' maan kar aage mat badho."]
        )
    return {"any_requested": bool(items), "items": items, "unmet": unmet,
            "lines": lines, "banner": banner}
