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
        # §4 ki baaki saat demands + naam se maange gaye targets. Ye keys ADD
        # hui hain, koi purani key badli nahi — purane caller waise hi chalte
        # hain.
        "wants_units": _any(_UNIT_RES, text),
        "wants_comparison": _any(_COMPARE_RES, text),
        "comparison_dimensions": comparison_dimensions(text),
        "wants_experiment_design": _any(_EXPERIMENT_RES, text),
        "wants_falsification": _any(_FALSIFY_RES, text),
        "wants_confidence": _any(_CONFIDENCE_RES, text),
        "wants_readiness": _any(_READINESS_RES, text),
        "wants_source_depth": _any(_SOURCE_DEPTH_RES, text),
        "named_targets": named_targets(text),
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

# ─────────────────────────────────────────────────────────────────────────────
# §4 ki poori parser-list. Pehle ismein saat cheezein PARSE hi nahi hoti thi —
# units, comparison dimensions, experiment design, falsification, confidence,
# readiness/validation level aur source depth. Nateeja: user in saat mein se
# kuch maange to contract mein uska naam bhi nahi aata tha, yaani wo demand
# CHUP-CHAAP fail ho sakti thi — jo is poori file ka ulta hai.
#
# Sab regex jaan-boojh kar KANJOOS hain: shak ho to False. Jhoothi "ye cheez
# maangi gayi thi par nahi mili" warning bhi ek jhooth hai.
# ─────────────────────────────────────────────────────────────────────────────

# 1. Units — "units ke saath", "SI units", "unit likho"
_UNIT_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\bunits?\b", r"\bSI\s+unit", r"इकाई", r"मात्रक",
    r"\bdimensional\s+analysis\b",
))

# 2. Comparison dimensions — "X vs Y", "compare karo", "in dimensions par tulna"
_COMPARE_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\bcompar\w+", r"\bversus\b", r"\bvs\.?\b", r"\btulna\b", r"तुलना",
    r"difference[s]?\s+between", r"\bfarak\b", r"फर्क",
    r"\bbetter\s+than\b", r"kaun\s+(?:behtar|zyada|acha)",
    r"side[\s\-]by[\s\-]side",
))
# "in dimensions par compare karo: cost, speed, safety" — list stop-phrase ke
# BAAD aati hai. Isliye stop-phrase dhoondh kar uske aage ki list padhte hain.
_COMPARE_DIM_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"(?:compare|comparison|tulna|तुलना)[^:\n।]{0,40}?[:—-]\s*([^.\n।]{4,160})",
    # "compare EV vs petrol on cost, emissions and range" — colon ke bina bhi
    # list aati hai, "on/par/ke hisaab se" ke baad.
    r"(?:compare|comparison|tulna|तुलना)[^.\n।]{0,60}?\b(?:on|par|pe|"
    r"ke\s+hisaab\s+se|के\s*आधार\s*पर)\s+([^.\n।]{4,160})",
    r"(?:in|is|inn|niche\s+di\s+gayi)?\s*(?:dimensions?|parameters?|"
    r"criteria|axes|pehluon|पहलुओं|मापदंड)\s*(?:par|pe|on|ke\s*hisaab\s*se|"
    r"के\s*आधार\s*पर)?\s*[:—-]?\s*([^.\n।]{4,160})",
    # "EV vs petrol cars ko cost, emissions and range par compare karo" —
    # list VERB SE PEHLE. Capture mein object ka hissa bhi aa jaata hai
    # ("EV vs petrol cars ko cost"), isliye `_DIM_PREFIX_RE` use kaat deta hai.
    r"([^.\n।:]{4,160}?)\s*(?:par|pe|ke\s+hisaab\s+se|के\s*आधार\s*पर)\s+"
    r"(?:compare|comparison|tulna|तुलना)",
    # "tulna cost aur side effects ke hisaab se karo" — verb pehle, list beech
    # mein, "ke hisaab se" aakhir mein.
    r"(?:compare|comparison|tulna|तुलना)\s+([^.\n।:]{4,160}?)\s*"
    r"(?:ke\s+hisaab\s+se|के\s*आधार\s*पर|\bpar\b|\bpe\b)",
))

# "EV vs petrol cars ko cost" me se sirf "cost" chahiye. Ye markers batate hain
# ki jis cheez ki tulna ho rahi hai wo khatam ho gayi aur pehlu shuru hue.
# `.*` (greedy) jaan-boojh kar: AAKHRI marker ke baad ka hissa hi pehlu hai.
_DIM_PREFIX_RE = re.compile(
    r"^.*(?:\bko\b|\bmein\b|\bbetween\b|\bvs\.?\b|\bversus\b|\bka\b|\bki\b)\s+",
    re.IGNORECASE)

# Doosri taraf ka kachra: "systematics par tulna karo" me se sirf "systematics"
# chahiye. Ye tab hota hai jab list ke BAAD verb aata hai ("— evidence strength
# aur systematics par tulna karo"). Sirf aakhir se kaatte hain, beech se nahi.
_DIM_SUFFIX_RE = re.compile(
    r"\s*(?:\b(?:par|pe|on|ke\s+hisaab\s+se|के\s*आधार\s*पर)\b\s*)?"
    r"(?:compare|comparison|tulna|तुलना)\b.*$", re.IGNORECASE)
# "cost dikhao" / "systematics likho" — sirf command verb aakhir mein ho to hate.
_DIM_VERB_TAIL_RE = re.compile(
    r"\s+(?:karo|karna|kijiye|banao|banana|do|dijiye|dikhao|likho|batao|"
    r"chahiye|karke\s+dikhao)\s*$", re.IGNORECASE)


def _strip_dim_edges(part: str) -> str:
    """Ek pehlu ke aage-peeche ka verb/object kachra hataao."""
    out = _DIM_PREFIX_RE.sub("", part or "")
    out = _DIM_SUFFIX_RE.sub("", out)
    for _ in range(2):                    # "par tulna karo" ke baad "karo" bacha ho
        out = _DIM_VERB_TAIL_RE.sub("", out)
    return out.strip()

# 3. Experiment design — "experiment design karo", "test kaise karenge"
_EXPERIMENT_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"experiment\w*\s*(?:design|protocol|plan|setup|banao|karo|do\b)",
    r"(?:design|propose|likho|banao)\s+(?:an?\s+)?experiment",
    r"test\s*(?:plan|protocol|design)", r"kaise\s+test\s+kar",
    r"how\s+(?:would|to|can)\s+(?:you\s+|we\s+)?test",
    r"प्रयोग\s*(?:की\s*रूपरेखा|डिज़ाइन|योजना)?", r"परीक्षण\s*योजना",
    r"\bpre[\s\-]?registered\b", r"\bcontrol\s+group\b",
))

# 4. Falsification — "galat kaise sabit hogi", "falsifiable"
_FALSIFY_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"falsif\w+", r"disprov\w+", r"refut\w+",
    r"galat\s+(?:kaise\s+)?(?:sabit|prove)", r"गलत\s+साबित",
    r"kya\s+(?:cheez|result)\s+ise\s+galat", r"khandan",
))

# 5. Confidence — "confidence kitna hai", "uncertainty do"
_CONFIDENCE_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\bconfidence\b", r"\bcertaint\w+", r"\buncertaint\w+",
    r"kitna\s+(?:yakeen|bharosa|pakka)", r"कितना\s+(?:यकीन|भरोसा)",
    r"\bconfidence\s+interval\b", r"\berror\s+bars?\b",
    r"\bkitni\s+sambhavna\b", r"आत्मविश्वास", r"विश्वास\s*स्तर",
))

# 6. Readiness / validation level — "TRL", "kitna validated hai"
_READINESS_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\breadiness\b", r"\bTRL[\s\-]?\d?\b", r"technology\s+readiness",
    r"validation\s+(?:level|status|state)", r"\bvalidated\b",
    r"maturity\s+level", r"kitna\s+(?:tested|validate|pakka\s+hua)",
    r"deployment\s+ready", r"प्रमाणित", r"परिपक्वता",
))

# 7. Source depth — "full text padho", "abstract se aage jao"
_SOURCE_DEPTH_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"full[\s\-]?text", r"poora\s+(?:paper|text|document)\s*padh",
    r"abstract\s+se\s+(?:aage|zyada)", r"\bdeep\s+read\w*",
    r"primary\s+(?:source|literature)", r"peer[\s\-]?review\w*",
    r"source\s+depth", r"original\s+paper", r"मूल\s*(?:शोध|पेपर)",
    r"सिर्फ\s*abstract\s*नहीं",
))

# 8. Named datasets / missions / experiments — prompt mein naam se maange gaye
# targets. Ye ginti isliye zaroori hai ki "Planck aur Bullet Cluster dono dekho"
# likha ho aur report unme se ek ko chhod de, to wo kami dikhni chahiye.
# Acronym (2+ capitals / capital+digits) aur ek chhoti known-mission list —
# dono conservative hain, kyunki har capitalised shabd mission nahi hota.
_ACRONYM_RE = re.compile(r"\b([A-Z][A-Z0-9]{2,12}(?:-[A-Z0-9]{1,6})?)\b")
_ACRONYM_STOP = {
    "AND", "THE", "FOR", "NOT", "BUT", "ALL", "ANY", "YOU", "USE", "NEW",
    "API", "PDF", "URL", "AI", "ML", "OK", "TODO", "FAQ", "ETC", "VS",
    "QUICK", "DEEP", "MAXIMUM", "VERIFIED", "PARTIAL", "COMPLETE",
    "RV", "HYP", "JSON", "HTML", "CSV", "UI", "APP", "SI",
}
_NAMED_TARGET_RES = tuple(re.compile(p) for p in (
    r"\b(Planck|WMAP|Gaia|JWST|Hubble|LIGO|Virgo|KAGRA|Euclid|LSST|SDSS|"
    r"DESI|eROSITA|Fermi|Chandra|XENON\w*|LUX-?ZEPLIN|LZ|PandaX|"
    r"Bullet Cluster|CERN|LHC|ATLAS|CMS|IceCube|Auger|ALMA|VLA|"
    r"UK Biobank|Framingham|NHANES|ImageNet|MNIST|CIFAR|GenBank|"
    r"Human Genome Project|ENCODE|TCGA|COMPAS)\b",
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


def comparison_dimensions(question: str, limit: int = 8) -> List[str]:
    """
    "cost, speed aur safety par compare karo" → ["cost", "speed", "safety"].

    Kuch na mile to KHAALI list — aur khaali list ka matlab "compare maanga hi
    nahi" nahi hota (uske liye `wants_comparison` alag hai). Do alag baatein
    hain: "tulna maangi thi" aur "tulna ke pehlu naam se likhe the".
    """
    text = question or ""
    for pattern in _COMPARE_DIM_RES:
        m = pattern.search(text)
        if not m:
            continue
        raw = m.group(1) if m.groups() else ""
        # Pehla tukda kabhi "EV vs petrol cars ko cost" jaisa aata hai aur aakhri
        # tukda "systematics par tulna karo" jaisa — dono taraf ka kachra
        # `_strip_dim_edges` kaat deta hai. Ye kaam `_clean_variable` se PEHLE
        # hona zaroori hai: wo lambe phrase ko poora hi gira deta hai.
        parts = [_clean_variable(_strip_dim_edges(p))
                 for p in _VAR_SPLIT_RE.split(raw)]
        out: List[str] = []
        for p in parts:
            if not p or _VAR_JUNK_RE.match(p) or len(p) < 3:
                continue
            if p.lower() not in [x.lower() for x in out]:
                out.append(p)
        if len(out) >= 2:
            return out[:limit]
    return []


def named_targets(question: str, limit: int = 12) -> List[str]:
    """
    Prompt mein NAAM se maange gaye dataset / mission / experiment.

    Sirf acronym aur ek chhoti known list — "Galaxy" ya "Rotation" jaise aam
    shabd mission nahi maane jaate. Yahan zyada pakadne se ledger nakli kami
    dikhane lagega, isliye kanjoosi jaan-boojh kar hai.
    """
    text = question or ""
    out: List[str] = []
    for pattern in _NAMED_TARGET_RES:
        for m in pattern.finditer(text):
            name = m.group(1).strip()
            if name and name.lower() not in [x.lower() for x in out]:
                out.append(name)
    for m in _ACRONYM_RE.finditer(text):
        name = m.group(1).strip()
        if name.upper() in _ACRONYM_STOP:
            continue
        if name.lower() not in [x.lower() for x in out]:
            out.append(name)
    return out[:limit]


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
        # Every production research run builds evidence before drafting. This
        # makes absence of its audit a release-blocking condition instead of an
        # optional quality-context field that can disappear and fail open.
        "evidence_first_required": True,
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
        # §4 ki parser-list ka bacha hua hissa. `direct_answer_required` hamesha
        # True hai — har sawaal ka seedha jawab banta hai; ye flag isliye likha
        # hai ki contract padh kar hi pata chal jaaye, andaza na lagana pade.
        "direct_answer_required": True,
        "units_required": bool(r.get("wants_units")),
        "comparison_required": bool(r.get("wants_comparison")),
        "comparison_dimensions": list(r.get("comparison_dimensions") or []),
        "experiment_design_required": (bool(r.get("wants_experiment_design"))
                                       or original_needed),
        "falsification_required": (bool(r.get("wants_falsification"))
                                   or original_needed),
        # Confidence har hypothesis card par likhna hi hai (§18), isliye app ki
        # apni hypothesis maangi gayi ho to ye bhi apne aap zaroori ho jaati hai.
        "confidence_required": (bool(r.get("wants_confidence"))
                                or original_needed),
        "readiness_required": (bool(r.get("wants_readiness"))
                               or original_needed),
        "source_depth_required": bool(r.get("wants_source_depth")),
        "named_targets": list(r.get("named_targets") or []),
        # Kaunsi cheez user ne KHUD likh kar maangi (derived nahi). Sirf inhi ko
        # ledger mandatory ginta hai — "hypothesis maangi thi isliye confidence
        # bhi chahiye" jaisi derived demand report mein DIKHTI hai par status
        # nahi giraati, warna app apni hi shart par jawab ko fail kar deta.
        "explicitly_asked": [
            key for key, flag in (
                ("units", r.get("wants_units")),
                ("comparison", r.get("wants_comparison")),
                ("experiment_design", r.get("wants_experiment_design")),
                ("falsification", r.get("wants_falsification")),
                ("confidence", r.get("wants_confidence")),
                ("readiness", r.get("wants_readiness")),
                ("source_depth", r.get("wants_source_depth")),
            ) if flag
        ],
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

    # §4 ki baaki saat demands. Har ek ka ek hi pattern hai: contract mein
    # maangi gayi hai ya nahi → delivered mein uska jawab hai ya nahi. Jawab na
    # ho to ❔ ("check nahi hua"), ❌ nahi — kyunki "naapa nahi gaya" aur "nahi
    # mila" do alag baatein hain, aur pichhli report ki sabse badi galti inhi
    # dono ko ek karne se bani thi.
    explicit = set(str(x) for x in (c.get("explicitly_asked") or []))
    simple = (
        ("units", "units_required", "units",
         "Numbers ke saath units", "mile", "nahi mile",
         "units maange gaye the par jawab mein number ke saath unit nahi likha"),
        ("experiment_design", "experiment_design_required", "experiment_design",
         "Experiment design / test plan", "bana", "poora nahi bana",
         "test plan chalane laayak nahi hai — kis sample/dataset par, kya naapa "
         "jayega, ya kaunsa result pass-fail maana jayega, in mein se kuch "
         "likha hi nahi gaya"),
        ("falsification", "falsification_required", "falsification",
         "Falsification — kis result se ye galat ho jaayega", "likha",
         "nahi likha",
         "falsification maangi gayi thi par 'galat kaise sabit hoga' nahi likha"),
        ("confidence", "confidence_required", "confidence",
         "Confidence / uncertainty", "likha", "nahi likha",
         "confidence maanga gaya tha par uska level nahi likha"),
        ("readiness", "readiness_required", "readiness",
         "Readiness / validation level", "likha", "nahi likha",
         "readiness (kitna validate hua) maanga gaya tha par nahi likha"),
        ("source_depth", "source_depth_required", "source_depth",
         "Source depth — kitna gehra padha gaya", "likha", "nahi likha",
         "source depth maangi gayi thi par padhne ki gehrai nahi likhi"),
    )
    for key, need_key, got_key, what, yes_word, no_word, why in simple:
        if not c.get(need_key):
            continue
        got = d.get(got_key)
        if got is None:
            add(key, what, "check nahi hua", None,
                "ye maanga gaya tha par iska naap hi nahi hua — isliye 'mil "
                "gaya' nahi keh sakte", mandatory=key in explicit)
        else:
            add(key, what, yes_word if got else no_word, bool(got),
                "" if got else why, mandatory=key in explicit)

    # comparison — sirf haan/na nahi: prompt mein naam se likhe pehlu bhi ginte
    # hain, taaki "cost, speed, safety par compare karo" mein se ek chhoot jaaye
    # to wo kami dikhe.
    if c.get("comparison_required"):
        dims = [str(x) for x in (c.get("comparison_dimensions") or [])]
        covered = d.get("comparison_dimensions_covered")
        if dims:
            if covered is None:
                add("comparison", f"{len(dims)} pehluon par tulna",
                    "check nahi hua", None,
                    "tulna ke pehlu prompt mein the par jawab mein inhe khoja "
                    "hi nahi gaya", mandatory="comparison" in explicit)
            else:
                have = [str(x) for x in covered]
                missing = [x for x in dims if x not in have]
                add("comparison", f"{len(dims)} pehluon par tulna",
                    f"{len(have)}/{len(dims)} pehlu mile", not missing,
                    ("in pehluon par tulna nahi hui: " + ", ".join(missing[:4]))
                    if missing else "",
                    mandatory="comparison" in explicit)
        else:
            got = d.get("comparison")
            add("comparison", "Tulna (comparison)",
                "check nahi hua" if got is None else
                ("hui" if got else "nahi hui"),
                None if got is None else bool(got),
                "" if got else "tulna maangi gayi thi",
                mandatory="comparison" in explicit)

    # naam se maange gaye dataset / mission / experiment
    targets = [str(x) for x in (c.get("named_targets") or [])]
    if targets:
        found = d.get("named_targets_found")
        if found is None:
            add("named_targets", f"{len(targets)} naam se maange gaye target",
                "check nahi hua", None,
                "prompt mein naam se maange gaye dataset/mission the par unka "
                "milaan nahi hua")
        else:
            have = [str(x) for x in found]
            missing = [x for x in targets if x not in have]
            add("named_targets", f"{len(targets)} naam se maange gaye target",
                f"{len(have)}/{len(targets)} par kaam hua", not missing,
                ("in par kuch nahi mila: " + ", ".join(missing[:4]))
                if missing else "")

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


# ── §4 ki saat naye demands: jawab mein sach much aayi ya nahi ───────────────
# Ye sab MAAPA jaata hai — kisi ke keh dene par bharosa nahi kiya jaata. Jo cheez
# naapi hi na ja sake, uski key bheji hi nahi jaati (ledger use "check nahi hua"
# likhega, "nahi mila" nahi).

# Unit ka saboot: physics wale units `physics_checks.parse_quantities` pakad leta
# hai. Ye list uske baahar ki cheezein hai — paisa, percent, count-per-time,
# astronomy ke units — kyunki "units chahiye" ka matlab sirf SI nahi hota.
_EXTRA_UNIT_RE = re.compile(
    r"(?:[₹$€£]\s*\d|\d\s*(?:%|percent\b|per\s+cent\b)|"
    r"\d[\d.,]*\s*(?:solar\s+mass(?:es)?|M[_☉]|M_sun|sigma|σ|"
    r"crore|lakh|billion|million|trillion|"
    r"events?\s*/\s*(?:day|year|s)|counts?\s*/\s*(?:day|year|s)|"
    r"pc|kpc|Mpc|Gpc|AU|ly|light[\s-]?year(?:s)?|barn|zb|yr|"
    r"GeV|MeV|TeV|keV|eV|Hz|kHz|MHz|GHz|W|kW|MW|GW|kWh|MWh|"
    r"mol|mmol|molar|ppm|ppb|dB|bit(?:s)?|byte(?:s)?|GB|TB)\b)",
    re.IGNORECASE)

# Confidence ka saboot: band ka naam likha ho. Sirf "confidence" shabd likh dena
# saboot nahi — isliye level ka naam maanga jaata hai.
_CONFIDENCE_BAND_RE = re.compile(
    r"\b(?:VERY\s+LOW|LOW|MODERATE|MEDIUM|HIGH|VERY\s+HIGH)\b\s*"
    r"(?:confidence|bharosa|vishwas)|"
    r"confidence\s*(?:band|level|:)?\s*[:\-–]?\s*"
    r"(?:VERY\s+LOW|LOW|MODERATE|MEDIUM|HIGH|VERY\s+HIGH)\b",
    re.IGNORECASE)

# Readiness = "ye cheez kitna validate ho chuki hai". Hypothesis ka status
# (UNTESTED HYPOTHESIS) bhi readiness hi hai.
_READINESS_TEXT_RE = re.compile(
    r"UNTESTED\s+HYPOTHESIS|validation\s+(?:status|level|stage)|"
    r"readiness\s+(?:level|stage)?|TRL\s*\d|"
    r"(?:lab|field|clinical)\s+(?:test|trial)\s+(?:pending|baaki|nahi)",
    re.IGNORECASE)

# §9 ke paanch access-depth label. Inme se ek bhi jawab mein ho, to "kitna gehra
# padha" likha gaya hai.
_DEPTH_LABELS = ("METADATA ONLY", "SNIPPET ONLY", "ABSTRACT ONLY",
                 "RELEVANT SECTIONS REVIEWED", "FULL TEXT ACCESSED")

_COMPARE_CUE_RE = re.compile(
    r"\bvs\.?\b|\bversus\b|\bcompared\s+(?:to|with)\b|\btulna\b|"
    r"\bmuqabla\b|\bek\s+taraf\b.{0,80}\bdoosri\s+taraf\b|"
    r"\bdono\s+(?:mein|ka)\b", re.IGNORECASE | re.DOTALL)

_WORD_RE = re.compile(r"[A-Za-z0-9ऀ-ॿ]+")
_TARGET_STOP = {"the", "a", "an", "of", "and", "or", "ka", "ki", "ke", "aur",
                "data", "dataset", "mission", "survey", "experiment"}


def _phrase_present(phrase: str, haystack: str) -> bool:
    """
    Phrase ke matlab-wale shabd sab maujood hain ya nahi.

    Poore phrase ka exact match kaafi nahi: prompt "charging time" maangta hai
    aur jawab "time to charge" likhta hai. Isliye har content-word alag se
    dhoonda jaata hai (word boundary par, substring par nahi — "range" ko
    "arrange" mein ginna galat hoga).
    """
    words = [w.lower() for w in _WORD_RE.findall(phrase or "")]
    words = [w for w in words if len(w) >= 3 and w not in _TARGET_STOP]
    if not words:
        return False
    low = haystack.lower()
    for w in words:
        if not re.search(r"(?<![a-z0-9])" + re.escape(w) + r"[a-z]{0,3}(?![a-z])",
                         low):
            return False
    return True


def _experiment_design_present(hyps: List[Dict]) -> bool:
    """
    Test plan "bana" kab kaha jaaye: plan ka text ho, aur §16 ke wo teen hisse
    ho jinke bina plan chalaya hi nahi ja sakta — kis cheez par (dataset/sample),
    kya naapa jayega, aur kaunsa result pass/fail maana jayega.

    Sirf "experiment karna hoga" likh dena design nahi hai — yahi cheez pichhli
    report mein "test plan diya gaya" ban gayi thi.
    """
    core = ("dataset_or_sample", "measured_variables", "success_threshold")
    for h in hyps:
        text = " ".join(str(h.get(k) or "") for k in ("experiment", "how_to_test"))
        if not text.strip():
            continue
        missing = set(str(x) for x in (h.get("experiment_spec_missing") or []))
        if not [k for k in core if k in missing]:
            return True
    return False


def delivery_evidence(contract: Optional[Dict], answer: str,
                      hypotheses: Optional[List[Dict]] = None,
                      calculations: Optional[List[Dict]] = None,
                      source_titles: Optional[List[str]] = None) -> Dict:
    """
    §4 ki naye ledger items ke liye `delivered` values banao — answer ke ASLI
    text se, dave se nahi.

    Sirf wahi keys return hoti hain jinka naap sach mein ho gaya. Jaise
    experiment design / falsification hypothesis records se aate hain: agar
    hypotheses list hi nahi bheji gayi (yaani us run mein hypothesis engine
    chala hi nahi), to un keys ko `False` likhna jhooth hoga — key gayab rehti
    hai aur ledger imaandaari se "check nahi hua" chhapta hai.
    """
    c = dict(contract or {})
    body = str(answer or "")
    out: Dict = {}
    if not body.strip():
        return out

    # units — answer ke numbers par
    try:
        from .physics_checks import parse_quantities
        has_units = any(getattr(q, "unit", "") for q in parse_quantities(body))
    except Exception:
        has_units = False
    if not has_units:
        has_units = bool(_EXTRA_UNIT_RE.search(body))
    if not has_units:
        for rec in (calculations or []):
            # `CalculationRecord.units` ek dict hai ({"T_c": "K"}), dict-form
            # record mein "unit" bhi ho sakta hai — dono roop chalte hain.
            if isinstance(rec, dict):
                unit = rec.get("units") or rec.get("unit")
            else:
                unit = getattr(rec, "units", None) or getattr(rec, "unit", None)
            if unit if isinstance(unit, dict) else str(unit or "").strip():
                has_units = True
                break
    out["units"] = has_units

    # experiment design + falsification — hypothesis records par
    if hypotheses is not None:
        hyps = [h for h in hypotheses if isinstance(h, dict)]
        out["experiment_design"] = _experiment_design_present(hyps)
        out["falsification"] = any(
            str(h.get("falsification_test") or "").strip()
            or str(h.get("if_false") or "").strip()
            or str((h.get("experiment_spec") or {}).get("falsification_condition")
                   or "").strip()
            for h in hyps)

    # confidence — band ka naam
    band = False
    for h in (hypotheses or []):
        if isinstance(h, dict) and str(h.get("confidence_band") or "").strip():
            band = True
            break
    out["confidence"] = band or bool(_CONFIDENCE_BAND_RE.search(body))

    # readiness — kitna validate hua
    status = False
    for h in (hypotheses or []):
        if isinstance(h, dict) and str(h.get("validation_status") or "").strip():
            status = True
            break
    out["readiness"] = status or bool(_READINESS_TEXT_RE.search(body))

    # source depth — §9 ke paanch label
    out["source_depth"] = any(label in body for label in _DEPTH_LABELS)

    # comparison
    dims = [str(x) for x in (c.get("comparison_dimensions") or [])]
    if dims:
        out["comparison_dimensions_covered"] = [d for d in dims
                                                if _phrase_present(d, body)]
    elif c.get("comparison_required"):
        out["comparison"] = bool(_COMPARE_CUE_RE.search(body))

    # naam se maange gaye target — answer + source titles dono mein dekho
    targets = [str(x) for x in (c.get("named_targets") or [])]
    if targets:
        hay = body + "\n" + "\n".join(str(t) for t in (source_titles or []))
        out["named_targets_found"] = [t for t in targets
                                      if _phrase_present(t, hay)]
    return out


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
