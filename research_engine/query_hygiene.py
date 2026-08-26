"""
#112 — junk / meta-instruction shabd search query na banein.

NAAPI HUI BIMARI (offline probe, 2026-08-26). intel ke asli prompt par:

    "ache se dhyaan se kaam kro ok jldi kro or abb kaam suru kro or kaam
     adwance hona chahiye sab. mujhe superconductivity par room temperature
     ke naye dawe samjhao, 3-4 hypothesis banao ..."

    base query  = "kaam ache dhyaan jaldi abb suru adwance"     <- 0 topic shabd
    topic_terms = [kaam, ache, dhyaan, jaldi, abb, suru, adwance,
                   superconductivity]                           <- topic 8ve par

Yaani provider ko "kaam ache dhyaan jaldi abb suru adwance" bheja gaya, aur
round 2/3 me wahi kachra "... contradictory findings criticism limitations"
ke saath dobara gaya. Har axis query ka base bhi yahi tha (orchestrator ka
`axis_base = planner.clean_query(question)`), isliye ek galti poore round me
phaili.

YE FILE DO KAAM KARTI HAI

  1. `JUNK` — wo shabd jo KISI BHI sawaal me topic nahi hote: kaam, dhyaan,
     jldi, ok, banao, karke, kaunsa, proof, hisaab... `query_builder` apne
     `_ALWAYS_META` me isi set ko jodta hai, isliye ginti, relevance aur query
     — teeno jagah ek hi paribhasha rehti hai (do alag list hi purani galti thi).

  2. GATE — kisi bhi query me kam se kam EK content shabd hona chahiye. Jisme
     nahi hai wo provider ko bheji hi nahi jaati, aur "kyu nahi bheji" naap ke
     saath likha jaata hai (chup-chaap drop nahi — #117 ka wahi niyam).

JAAN-BOOJH KAR KYA NAHI KIYA: "advance", "plan", "schedule", "point", "key",
"pattern", "previous" JUNK me nahi hain. Ye asli topic ho sakte hain ("advanced
materials", "treatment plan", "boiling point", "public key", "vaccination
schedule"), aur topic maar dena junk bhejne se zyada nuksaan hai.

Zero Gemini call, zero network, ₹0. Sirf shabd dekhkar faisla.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# ── 1. junk shabd (kisi bhi sawaal me topic nahi) ────────────────────────────
# Roman/Hinglish — intel ke prompt ka asli vocabulary.
_JUNK_ROMAN = {
    # "kaam kro / ache se / dhyaan se / jldi / abb / suru / adwance"
    "kaam", "kaamkaaj", "kamkaj",
    "ache", "achhe", "acche", "achha", "achhi", "acchi", "achi",
    "dhyaan", "dhyan", "dhian", "dyan",
    "jaldi", "jldi", "jaldy", "fatafat", "turant", "jald",
    "abb", "suru", "shuru", "shuroo",
    "adwance", "adwanced", "adwans",
    "ok", "okay", "oke", "thik", "theek", "thanks", "thanku", "thankyou",
    "plz", "pls",
    # "pura research karke btao"
    "pura", "poora", "puri", "poori", "puura",
    "karke", "krke", "karkar", "karun", "karu", "kru", "krna", "krne", "kr",
    "karo", "kro", "kijiye", "kijiyega", "karna",
    # "banao / dedo / bhejo / dikhao / likho"
    "banao", "bnao", "banake", "banado", "bnado", "bana", "banaa",
    "dedo", "dede", "dijiye", "dijiyega", "dena", "dedena", "dedijiye",
    "bhejo", "bhej", "bhejna",
    "dikhao", "dikha", "dikhado", "dikhana",
    "likh", "likhna", "likhkar",
    "padho", "padh", "padhna", "padhkar",
    "soch", "sochkar", "sochna",
    "btado", "btadena", "batadena", "batado", "chalao", "chalo",
    # "samjhe / hisaab / kaunsa / proof / imaandaari"
    "samjhe", "samjha", "samjhna", "samajhna", "samajh", "samjhaao",
    "hisaab", "hisab",
    "kaunsa", "kaunsi", "kaunse", "konsa", "konsi", "konse", "kaun", "kon",
    "proof", "proofs",
    "imaandaari", "imandari", "imaandari", "imaan",
    # "step by step / roz"
    "step", "steps", "stepwise",
    "roz", "rozana", "rozaana",
}

# Devanagari — wahi shabd, dusri lipi me.
_JUNK_DEVANAGARI = {
    "काम", "ध्यान", "जल्दी", "जल्द", "अच्छे", "अच्छा", "अच्छी", "ठीक",
    "शुरू", "फटाफट", "तुरंत",
    "करके", "करूँ", "करूं", "करूंगा", "करकर", "कीजिए", "कीजिये",
    "बनाओ", "बनाके", "बनाकर", "दिखाओ", "दिखाना", "भेजो", "भेजना",
    "दीजिए", "दीजिये", "देदो", "समझे", "समझा", "समझना",
    "हिसाब", "कौनसा", "कौनसी", "कौन", "प्रूफ",
    "ईमानदारी", "ईमानदार", "रोज", "रोज़", "रोजाना",
    "कदम", "चरण",
}

JUNK = frozenset(_JUNK_ROMAN | _JUNK_DEVANAGARI)

# ── 2. steering shabd (planner khud jodta hai) ───────────────────────────────
# Ye query me hone me koi harj nahi — par SIRF inse bani query ka matlab hai ki
# base topic gum ho gaya. Isliye gate ke liye ye content NAHI ginte.
STEERING = frozenset({
    "contradictory", "findings", "criticism", "limitations", "counter",
    "evidence", "study", "studies", "review", "systematic", "meta-analysis",
    "primary", "writings", "collected", "papers", "paper", "sources",
    "research", "replication", "retraction", "controversy", "peer-reviewed",
    "preprint", "dataset", "official", "report",
})

MIN_QUERY_CHARS = 3        # isse chhoti query provider ko bhejna bekaar hai

# Gate ke faisle ke naam. String hi rehne dena — logs/tests inhi par tikte hain.
DROP_NO_CONTENT = "query_me_koi_topic_shabd_nahi"
DROP_TOO_SHORT = "query_bahut_chhoti"
DROP_DUPLICATE = "query_pehle_hi_ja_chuki"
OK = ""


def is_junk_word(word: str) -> bool:
    """Kya ye shabd kisi bhi sawaal me topic nahi hota?"""
    low = str(word or "").strip().casefold()
    return bool(low) and low in JUNK


def _tokens(text: str) -> List[str]:
    """query_builder ka hi tokenizer — lazy import, warna circular ho jaata.

    Duplicate tokenizer likhna hi purani galti hai (do jagah do paribhasha).
    query_builder is file se `JUNK` leta hai, isliye ulta import function ke
    andar hota hai.
    """
    from . import query_builder as qb
    return qb._tokens(qb.normalize(text or ""))


def _stop_words() -> frozenset:
    from . import query_builder as qb
    return frozenset(qb._STOP)


def content_tokens(text: str) -> List[str]:
    """Sirf wo shabd jo sach me topic ka signal hain.

    Bahar: junk, function-word (`query_builder._STOP`), steering shabd aur
    sirf-ank token. Kram wahi rehta hai jo sawaal me tha.
    """
    stop = _stop_words()
    out: List[str] = []
    for token in _tokens(text):
        if token in stop or token in JUNK or token in STEERING:
            continue
        out.append(token)
    return out


def junk_tokens(text: str) -> List[str]:
    """Is text ke wo shabd jo JUNK list me hain — naap ke liye."""
    return [t for t in _tokens(text) if t in JUNK]


def strip_junk(text: str, keep_min: int = 2) -> str:
    """Query se junk shabd hataao — par query ko khaali mat karo.

    `keep_min` se kam content shabd bache to text ko CHHEDA hi nahi jaata.
    Wajah: chhote sawaal ("kaunsa business karu") par sab kuch kaat dena
    provider ko khaali query bhejne jaisa hai, jo 0 result laata hai. Aisi
    haalat me gate (`query_verdict`) faisla karta hai, ye function nahi.
    """
    words = str(text or "").split()
    if not words:
        return ""
    kept = [w for w in words if not is_junk_word(w.strip(".,;:!?()[]\"'"))]
    if len(content_tokens(" ".join(kept))) < max(1, int(keep_min)):
        return str(text or "").strip()
    return " ".join(kept).strip()


def tidy_query(text: str, keep_min: int = 2) -> str:
    """Junk + function shabd dono hatao — par query ko be-matlab mat karo.

    `strip_junk` sirf JUNK hataata hai. Isse aage ki safai `clean_query` ke
    chhote-sawaal raaste ke liye hai, jahan uski apni `_FILLER_WORDS` list
    bahut chhoti hai aur "jo / ho / bhi / by / do / par" jaise shabd query me
    bach jaate the ("hindi gaana jo feeling human psychology ho").

    `keep_min` se kam topic shabd bachein to poori safai chhod di jaati hai aur
    sirf junk hataaya jaata hai — kyunki chhote sawaal par sab kaat dena query
    ko khaali kar deta hai, aur khaali query ka matlab 0 result hai.
    """
    words = str(text or "").split()
    if not words:
        return ""
    stop = _stop_words()
    kept: List[str] = []
    for word in words:
        bare = word.strip(".,;:!?()[]\"'").casefold()
        if bare in JUNK or bare in stop:
            continue
        kept.append(word)
    joined = " ".join(kept).strip()
    if len(content_tokens(joined)) < max(1, int(keep_min)):
        return strip_junk(text, keep_min=keep_min)
    return joined


def query_verdict(query: str) -> Dict[str, Any]:
    """Ye query provider ko bhejni chahiye ya nahi — aur kis naap par.

    Wapsi: {"ok": bool, "reason": str, "measured": {...}}. `reason` khaali hi
    hota hai jab query theek hai; warna DROP_* me se ek.
    """
    text = str(query or "").strip()
    all_tokens = _tokens(text)
    content = content_tokens(text)
    junk = [t for t in all_tokens if t in JUNK]
    measured: Dict[str, Any] = {
        "chars": len(text),
        "shabd": len(all_tokens),
        "topic_shabd": len(content),
        "junk_shabd": len(junk),
    }
    if junk:
        measured["junk_mile"] = ", ".join(sorted(set(junk))[:8])
    if content:
        measured["topic_mile"] = ", ".join(content[:6])
    if len(text) < MIN_QUERY_CHARS:
        return {"ok": False, "reason": DROP_TOO_SHORT, "measured": measured}
    if not content:
        return {"ok": False, "reason": DROP_NO_CONTENT, "measured": measured}
    return {"ok": True, "reason": OK, "measured": measured}


def is_junk_query(query: str) -> bool:
    """Chhota wrapper — query me ek bhi topic shabd nahi hai?"""
    return not query_verdict(query)["ok"]


def _drop_line(query: str, verdict: Dict[str, Any]) -> str:
    """User ke liye ek line: kya nahi bheja aur kyu. Naap zaroori hai."""
    measured = verdict.get("measured") or {}
    bits = [f"{key}={value}" for key, value in measured.items()
            if value is not None and value != "" and value != []]
    return (f"Ye search query nahi bheji ({verdict.get('reason')}): "
            f"\"{query[:80]}\" — {', '.join(bits)}")


def filter_queries(queries: Optional[List[str]],
                   records: Optional[List[Dict[str, Any]]] = None,
                   keep_at_least: int = 1) -> List[str]:
    """Junk query hatao, kram aur baaki sab waisa hi rakho.

    `records` list di jaaye to har hataayi hui query ka record (query, reason,
    measured, line) usme jud jaata hai — audit isi se honest line banata hai.

    `keep_at_least`: agar SAARI queries junk nikal gayi to pehli query phir bhi
    jaati hai. Wajah: khaali query list ka matlab "ek bhi source nahi dekha"
    hota hai, aur wo research ko chup-chaap maar dena hai. Aisi haalat me record
    phir bhi likha jaata hai, taaki jhoothi safai na ho.
    """
    out: List[str] = []
    seen = set()
    log = records if isinstance(records, list) else []
    for raw in (queries or []):
        query = str(raw or "").strip()
        if not query:
            continue
        key = query.casefold()
        if key in seen:
            log.append({"query": query, "reason": DROP_DUPLICATE,
                        "measured": {"chars": len(query)},
                        "line": _drop_line(query, {"reason": DROP_DUPLICATE,
                                                   "measured": {"chars": len(query)}})})
            continue
        seen.add(key)
        verdict = query_verdict(query)
        if verdict["ok"]:
            out.append(query)
            continue
        log.append({"query": query, "reason": verdict["reason"],
                    "measured": verdict["measured"],
                    "line": _drop_line(query, verdict)})
    if not out and keep_at_least:
        for raw in (queries or []):
            query = str(raw or "").strip()
            if query:
                out.append(query)
                break
    return out


def drop_lines(records: Optional[List[Dict[str, Any]]],
               limit: int = 4) -> List[str]:
    """Audit ke liye lines — ginti ke saath, boilerplate nahi."""
    rows = [r for r in (records or []) if isinstance(r, dict)]
    if not rows:
        return []
    out = [f"{len(rows)} search query nahi bheji gayi (junk/meta shabd ya "
           "duplicate) — neeche naap ke saath."]
    for row in rows[: max(1, int(limit))]:
        line = str(row.get("line") or "").strip()
        if line:
            out.append(line)
    return out
