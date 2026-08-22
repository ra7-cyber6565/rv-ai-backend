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

from .answer_order import CANONICAL_NAMES, canonical_key

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

# Count aur `hypothesis` ke beech user aksar quality adjective likhta hai:
# "3 testable hypotheses", "3 nayi falsifiable hypotheses". Purana regex
# sirf `3 hypotheses` / `3 nayi hypotheses` samajhta tha. Live release question
# isi wajah se 3 ko 1 padh raha tha. Qualifiers ko explicit allow-list rakha hai
# taaki kisi door ke unrelated number ko hypothesis count na maan lein.
_HYP_QUALIFIER = (
    r"(?:new|nayi|nai|naye|naya|novel|testable|falsifiable|scientific|"
    r"नई|नयी|नए|नये|परीक्षणीय|जाँचने\s*योग्य)"
)

_TOKEN = r"([0-9०-९]+|[A-Za-zऀ-ॿ]{2,7})"

# "kam se kam 3 ... hypotheses" / "3 nayi hypotheses" / "hypotheses: at least 3"
_HYP_COUNT_RES = (
    re.compile(_ATLEAST + r"\s*" + _TOKEN + r"[^.\n।]{0,40}?" + _HYP, re.IGNORECASE),
    re.compile(
        _TOKEN + r"\s+(?:" + _HYP_QUALIFIER + r"\s+){0,4}" + _HYP,
        re.IGNORECASE,
    ),
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


# ─────────────────────────────────────────────────────────────────────────────
# §4 — QUALITY CONTRACT
#
# Kyun (2026-08-21, dark-matter run ke baad): us run mein "answer complete" ka
# faisla is baat par ho raha tha ki text bhara hua dikh raha hai ya nahi. Isliye
# adhoora jawab bhi "COMPLETE + ✅ VERIFIED" chhap gaya, jabki calculation nahi
# bani thi, counter-search chali hi nahi thi, aur retrieved sources mein se aadhe
# sawaal ke hi nahi the.
#
# Ab pehle ek CONTRACT banta hai (sawaal + mode se, ek bhi LLM call nahi), aur
# aakhir mein us contract ke against ginti hoti hai. Contract ka koi bhi mandatory
# item missing ho to:
#     answer_complete = False, result PARTIAL / INSUFFICIENT EVIDENCE,
#     aur `VERIFIED` ka darwaza band.
# ─────────────────────────────────────────────────────────────────────────────

# §12 ka fixed order. Ye 10 top-level section HAR jawab mein hone chahiye —
# "Calculations" bhi, kyunki calculation na banne par bhi us section mein WAJAH
# likhni hai (khaali chhod dena hi pichhli baar jhooth ban gaya tha).
#
# Naam aur order ek hi jagah (`answer_order.py`) se aate hain. Pehle yahan aur
# synthesizer mein alag-alag list thi, aur wahi do-list wali haalat "sections
# poore hain?" check ko hamesha fail karwaati thi.
CONTRACT_SECTIONS = CANONICAL_NAMES

# §4 ke do numeric floor. DONO provisional hain — inhe "universal truth" ki tarah
# nahi likhna. `minimum_average_relevance_status` isi liye contract mein jaata
# hai, taaki report bhi ise calibration-pending bata sake.
MIN_DIRECTLY_RELEVANT_SOURCES = 2
MIN_AVERAGE_RELEVANCE = 0.65
MIN_AVERAGE_RELEVANCE_STATUS = (
    "provisional — ye number benchmark corpus par calibrate hona hai, koi "
    "universal sachchai nahi hai")

# ── calculation kab sach mein maangi gayi hai ────────────────────────────────
# Sirf "number" dikhne par nahi: "2024 mein" ek saal hai, calculation nahi.
_CALC_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"calculat\w+", r"compute", r"quantif\w+", r"estimate\b", r"estimation",
    r"derive\b", r"derivation", r"order[\s\-]of[\s\-]magnitude",
    r"kitna\s+(?:hoga|hota|banega|chahiye|zyada|kam)", r"kitne\s+(?:%|percent)",
    r"how\s+(?:much|many|fast|far|long|big)", r"what\s+fraction",
    r"गणना", r"अनुमान\s*लगाओ", r"हिसाब",
    r"\bnumbers?\s+(?:do|dena|nikalo|batao)\b", r"hisaab\s+(?:lagao|karo|do)",
    r"\bratio\b", r"\bpercentage\b", r"\bmass\s+of\b", r"\bdensity\s+of\b",
    r"\bcross[\s\-]section\b", r"\bupper\s+limit\b", r"\blower\s+bound\b",
))

# "nayi/apni hypothesis banao" — yaani APP ORIGINAL RESEARCH LAB ka content
# maanga gaya hai. Sirf `hypothesis` shabd kaafi nahi: "is paper ki hypothesis
# kya thi" original research ki demand nahi hai.
_ORIGINAL_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"(?:new|nayi|nai|naye|naya|novel|original|apni|khud\s+ki)\s+"
    r"(?:\w+\s+){0,2}?" + _HYP,
    _HYP + r"\s*(?:banao|banana|generate|propose|do\b|dena)",
    r"(?:नई|नयी|नए|मौलिक)\s*परिकल्पना",
    r"apna\s+(?:idea|theory|explanation|model)\s*(?:do|banao|batao)",
    r"koi\s+nayi\s+(?:soch|theory|wajah|explanation)",
))

# Counter-evidence ki demand alag se likhi ho to ledger usko naam se dikhata
# hai — par counter SEARCH to hamesha mandatory hai, maanga jaaye ya na jaaye.
_COUNTER_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"counter[\s\-]?evidence", r"evidence\s+against", r"khilaf",
    r"विरुद्ध", r"opposing\s+(?:view|evidence|result)",
    r"alternative\s+(?:explanation|hypothes\w+|theor\w+)",
    r"disagree\w*", r"refut\w+", r"disconfirm\w+",
))


def wants_calculations(question: str) -> bool:
    """
    Sawaal quantitative kaam maang raha hai ya nahi.

    Jaan-boojh kar conservative: jahan shak ho wahan False, kyunki jhoothi
    "calculation missing" warning bhi ek jhooth hai. Math/optimization model ki
    demand apne aap mein calculation ki demand hai.
    """
    text = question or ""
    if _any(_MATH_RES, text):
        return True
    return _any(_CALC_RES, text)


def wants_original_hypotheses(question: str) -> bool:
    """App ki KHUD ki hypothesis maangi gayi hai (paper ki hypothesis nahi)."""
    return _any(_ORIGINAL_RES, question or "")


def quality_contract(question: str, config=None,
                     requests: Optional[Dict] = None) -> Dict:
    """
    Ek deterministic contract: is sawaal ka jawab kis-kis cheez ke bina adhoora
    hai. Ek bhi API call nahi, wahi sawaal → wahi contract (do run same).

    `config` DepthConfig hai (ya kuch bhi jismein `.name` ho). QUICK mode ka
    wada "turant jawab" hai, isliye wahan evidence-graph mandatory nahi karte —
    par counter-search wahan bhi mandatory hai, kyunki "sirf support dhoondhna"
    hi pichhli baar sabse bada jhooth ban gaya tha.
    """
    text = question or ""
    r = dict(requests or parse_requests(text))
    mode = str(getattr(config, "name", "") or "").upper()
    asked = int(r.get("hypothesis_count") or 0)
    original_needed = bool(wants_original_hypotheses(text)) or asked > 0
    return {
        "required_sections": list(CONTRACT_SECTIONS),
        # kitni maangi gayi thi. 0 = maangi hi nahi — aur us haalat mein
        # hypotheses ZABARDASTI banana bhi mana hai (§15).
        "hypotheses_requested": asked,
        "original_hypotheses_required": original_needed,
        "calculations_required": wants_calculations(text),
        # hamesha True. Ye flag isliye hai ki gate ise padh sake, badal na sake.
        "counter_search_required": True,
        "evidence_graph_required": mode != "QUICK",
        # §5 — saboot ke zaroori raaste (evidence axes) khaali hone par jawab
        # adhoora hai. QUICK ka wada "turant jawab" hai (ek round, 3 axis
        # queries), isliye wahan ye kami ledger mein DIKHTI hai par status nahi
        # giraati. DEEP/MAXIMUM mein ye mandatory hai — pichhli dark-matter
        # report mein 7 zaroori raaste khaali the aur jawab phir bhi COMPLETE
        # likha gaya tha.
        "evidence_axes_required": mode != "QUICK",
        "minimum_directly_relevant_sources": MIN_DIRECTLY_RELEVANT_SOURCES,
        "minimum_average_relevance": MIN_AVERAGE_RELEVANCE,
        "minimum_average_relevance_status": MIN_AVERAGE_RELEVANCE_STATUS,
        # prompt se parse hui explicit demands (backward compatible keys)
        "math_model_required": bool(r.get("wants_math_model")),
        "second_order_required": bool(r.get("wants_second_order")),
        "red_team_required": bool(r.get("wants_red_team")),
        "counter_evidence_asked": _any(_COUNTER_RES, text),
        "math_variables": list(r.get("math_variables") or []),
        "chain_steps": list(r.get("chain_steps") or []),
        # §15 — ginti poori karne ke liye hypothesis GHADNA mana hai. Ye flag
        # contract mein likha hai taaki koi baad mein "spec ne bola tha 3 chahiye"
        # keh kar filler na bhar de.
        "forced_hypothesis_count_allowed": False,
        "mode": mode or "DEEP",
    }


# Contract ka kaunsa item "mandatory" hai — yaani missing hone par jawab adhoora
# maana jaayega. Baaki items ledger mein dikhte hain par status nahi girate.
_MANDATORY_KEYS = (
    "sections", "counter_search", "hypotheses", "calculations",
    "directly_relevant_sources", "average_relevance",
    # §5 — saboot ke zaroori raaste. Ye key tab hi mandatory ginti hai jab
    # contract ne `evidence_axes_required` True kaha ho (QUICK mein nahi).
    "evidence_axes",
)


def contract_ledger(contract: Optional[Dict], delivered: Optional[Dict] = None,
                    reasons: Optional[List[str]] = None) -> Dict:
    """
    Contract vs sach — "asked vs delivered" ledger.

    `delivered` keys (jo mile, wahi dekhte hain; missing key = "pata nahi"):
        sections_present: List[str]
        counter_search_performed: bool | None
        hypotheses: int
        original_hypotheses: int
        calculations: int
        directly_relevant_sources: int | None
        average_relevance: float | None

    Sabse zaroori niyam: `None` ka matlab "check hua hi nahi" hai, "zero mila"
    nahi. Dono ko ek jaisa dikhana pichhle run ki asli galti thi.
    """
    c = dict(contract or {})
    d = dict(delivered or {})
    # Wajah sirf tab likhte hain jab sach mein record hui ho. "Wajah record nahi
    # hui." har line ke peeche chipkana sirf shor hai.
    why = _why(reasons) if reasons else ""
    items: List[Dict] = []

    def add(key: str, what: str, got: str, ok: Optional[bool],
            note: str = "", mandatory: Optional[bool] = None) -> None:
        items.append({
            "key": key, "what": what, "got": got,
            # ok=None → "verify nahi kar paye" (na pass, na fail ka jhooth)
            "ok": ok, "unknown": ok is None,
            # `mandatory` sirf tab pass hota hai jab contract khud tay karta ho
            # (jaise §5 ke evidence axes QUICK mode mein mandatory nahi hote).
            "mandatory": (key in _MANDATORY_KEYS if mandatory is None
                          else bool(mandatory)),
            "why": "" if ok else (note or why),
        })

    # 1. sections
    required = [str(s) for s in (c.get("required_sections") or [])]
    if required:
        present = d.get("sections_present")
        if present is None:
            add("sections", f"{len(required)} mandatory sections",
                "check nahi hua", None,
                "sections ki ginti hi nahi hui — isliye 'poore hain' nahi keh sakte")
        else:
            # §12 (2026-08-22) — pehle yahan heading ka EXACT lowercase match hota
            # tha. Report ki heading Hinglish mein thi ("Evidence kya kehta hai?")
            # aur contract ka naam canonical ("Supporting evidence"), isliye ye
            # item HAMESHA fail hota tha — yaani har jawab bina wajah PARTIAL.
            # Ab pehchan `answer_order.canonical_key` se hoti hai, jo canonical
            # naam aur uske Hinglish alias dono ko ek hi key deta hai.
            have = {canonical_key(s) for s in present}
            have.discard("")
            missing = [s for s in required if canonical_key(s) not in have]
            add("sections", f"{len(required)} mandatory sections",
                f"{len(required) - len(missing)}/{len(required)}",
                not missing,
                (f"missing: {', '.join(missing)}. " + why) if missing else "")

    # 2. counter-search (hamesha mandatory)
    if c.get("counter_search_required", True):
        performed = d.get("counter_search_performed")
        if performed is None:
            add("counter_search", "Counter-evidence search", "check nahi hua", None,
                "counter-search ka record nahi mila — bina record consensus ka "
                "dava nahi ban sakta")
        else:
            add("counter_search", "Counter-evidence search",
                "chali" if performed else "nahi chali", bool(performed))

    # 3. hypotheses — ginti poori na ho to shortfall, par ghadna mana
    asked = int(c.get("hypotheses_requested") or 0)
    if asked:
        got = d.get("hypotheses")
        if got is None:
            add("hypotheses", f"{asked} testable hypotheses", "check nahi hua", None)
        else:
            got = int(got)
            add("hypotheses", f"{asked} testable hypotheses", f"{got}/{asked}",
                got >= asked,
                (f"{got}/{asked} bani. " + why) if got < asked else "")
    if c.get("original_hypotheses_required") and d.get("original_hypotheses") is not None:
        count = int(d.get("original_hypotheses") or 0)
        # 0 bhi ek imaandaar jawab hai (§15: koi defensible idea na bane to
        # "none generated" likhna hi sahi hai). Isliye ye item status nahi
        # giraata — sirf sach dikhata hai.
        add("original_hypotheses", "APP ORIGINAL RESEARCH LAB ka content",
            f"{count} app-original hypothes{'is' if count == 1 else 'es'}",
            True,
            "")

    # 4. calculations
    if c.get("calculations_required"):
        count = d.get("calculations")
        if count is None:
            add("calculations", "Calculation (formula + inputs + units)",
                "check nahi hua", None)
        else:
            count = int(count)
            add("calculations", "Calculation (formula + inputs + units)",
                f"{count} bani" if count else "koi nahi bani", count > 0)

    # 5/6. retrieval floors
    floor = int(c.get("minimum_directly_relevant_sources")
                or MIN_DIRECTLY_RELEVANT_SOURCES)
    direct = d.get("directly_relevant_sources")
    if direct is None:
        add("directly_relevant_sources", f"Kam se kam {floor} directly relevant source",
            "check nahi hua", None)
    else:
        direct = int(direct)
        add("directly_relevant_sources", f"Kam se kam {floor} directly relevant source",
            f"{direct} mile", direct >= floor)

    min_rel = float(c.get("minimum_average_relevance") or MIN_AVERAGE_RELEVANCE)
    avg = d.get("average_relevance")
    if avg is None:
        add("average_relevance", f"Average relevance ≥ {min_rel:.2f}",
            "check nahi hua", None)
    else:
        avg = float(avg)
        add("average_relevance", f"Average relevance ≥ {min_rel:.2f}",
            f"{avg:.2f}", avg >= min_rel,
            (f"{avg:.2f} < {min_rel:.2f} — ye floor abhi provisional hai "
             f"({MIN_AVERAGE_RELEVANCE_STATUS.split('—')[0].strip()})")
            if avg < min_rel else "")

    # 7. §5 — saboot ke zaroori raaste (evidence axes). Ye item hi wo taala hai
    # jo pichhli dark-matter report par nahi tha: 18 source mile the, par CMB,
    # BBN, Bullet Cluster, lensing, LSS aur dwarf galaxies par ek bhi nahi —
    # aur jawab phir bhi "COMPLETE" likha gaya tha. Ginti yahan kaam nahi aati.
    axes_required = bool(c.get("evidence_axes_required"))
    missing_axes = d.get("axes_mandatory_missing")
    if axes_required or missing_axes is not None:
        total = d.get("axes_total")
        covered = d.get("axes_covered")
        labels = [str(x) for x in (d.get("axes_missing_labels") or [])][:4]
        what = "Saboot ke zaroori raaste (evidence axes) cover hue"
        if missing_axes is None:
            add("evidence_axes", what, "check nahi hua", None,
                "axes ka coverage naapa hi nahi gaya — isliye 'koi zaroori "
                "raasta khaali nahi raha' nahi keh sakte",
                mandatory=axes_required)
        else:
            missing_axes = int(missing_axes)
            got = (f"{covered}/{total} raaste par relevant source"
                   if total is not None and covered is not None
                   else f"{missing_axes} zaroori raaste khaali")
            add("evidence_axes", what, got, missing_axes == 0,
                (f"{missing_axes} zaroori raaste khaali hain"
                 + (f" ({', '.join(labels)})" if labels else "")
                 + " — source ki ginti is kami ko nahi dhakti") if missing_axes
                else "",
                mandatory=axes_required)

    # extra explicit demands (mandatory nahi, par ledger mein dikhein)
    if c.get("math_model_required") and d.get("math_model") is not None:
        add("math_model", "Mathematical / optimization model",
            "bana" if d.get("math_model") else "nahi bana", bool(d.get("math_model")))
    if c.get("second_order_required") and d.get("second_order") is not None:
        add("second_order", "Second-order effects chain",
            "mili" if d.get("second_order") else "nahi mili",
            bool(d.get("second_order")))
    if c.get("red_team_required") and d.get("red_team") is not None:
        add("red_team", "Red-team / self-falsification",
            "chala" if d.get("red_team") else "nahi chala", bool(d.get("red_team")))

    failed = [i for i in items if i["ok"] is False]
    unknown = [i for i in items if i["ok"] is None]
    mandatory_missing = [i for i in items
                         if i["mandatory"] and i["ok"] is not True]
    lines = [
        "- " + ("✅" if i["ok"] is True else ("❔" if i["ok"] is None else "❌"))
        + f" {i['what']} → **{i['got']}**"
        + (f" — {i['why']}" if i["why"] else "")
        for i in items
    ]
    return {
        "items": items,
        "failed": failed,
        "unknown": unknown,
        "mandatory_missing": mandatory_missing,
        # Ye teen faisle gate ke liye hain — text padh kar andaza lagane ki
        # zaroorat na pade.
        "answer_complete": not mandatory_missing,
        "verified_allowed": not mandatory_missing,
        "result_state": ("COMPLETE" if not mandatory_missing else
                         ("INSUFFICIENT_EVIDENCE"
                          # §5 — zaroori evidence axis khaali rehna bhi "evidence
                          # kam hai" hi hai, sirf "adhoora likha" nahi.
                          if any(i["key"] in ("directly_relevant_sources",
                                              "average_relevance",
                                              "evidence_axes")
                                 and i["ok"] is False for i in items)
                          else "PARTIAL")),
        "lines": lines,
    }


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
