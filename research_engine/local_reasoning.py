"""
LocalReasoning — LLM ke BINA bhi poora, sectioned, cited jawab.

Kyun (intel, 2026-08-21): "iska quota khatam ho gya, ye kaam nhi kiya, iss wajah
se jawab thoda week rah gya ... 100% pura app working sab cheeje work kre."
Pehle Gemini ka quota marne par `extractive_summary()` chalta tha, jo sirf
`## Seedha jawab` ke neeche source ke tukde chipka deta tha. Nateeja: report ke
teen insaani section (`Research se kya pata chala?`, `Ye kyun hota hai?`,
`Kya abhi unknown hai?`) khaali reh jaate the aur jawab "weak" lagta tha.

Ye module wahi kaam bina kisi API ke karta hai — engine ne jo sources PADHE hain
unke apne text se. Teen niyam pakke hain:

  1. ₹0 aur offline — koi API, koi key, koi network. Sirf EvidencePack.
  2. IMAANDAAR — koi baat invent nahi hoti. Har line ke saath [S#] jaata hai, aur
     label kabhi `[ESTABLISHED]` nahi hota: source ke apne shabd
     `[SOURCE-REPORTED]` hain, aur engine ka jodna `[INFERENCE]` hai.
  3. DETERMINISTIC — wahi pack, wahi jawab, shabd-ba-shabd (benchmark test 10).

Heading canonical hain (`synthesizer.SECTION_TITLES`), kyunki `assemble()` inhi
naamon se section pehchaanta hai. Yahi wajah hai ki is text se sections 0,1,2,3,4,
7,8 bhar jaate hain aur "kaunse hisse nahi ban paaye" list khaali ho jaati hai.

Ye module STATUS nahi badalta: reasoning pass sach mein nahi chala, to report ab
bhi "RESEARCH INCOMPLETE" hi kehti hai. Farak sirf itna hai ki jawab adhoora
nahi rehta — sab section bharte hain, aur wajah saaf likhi hoti hai.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

from .explain_style import detect_language
from .models import EvidencePack, SourceRecord

# read level -> imaandaar label + insaani lafz
_LEVEL_WORD = {
    "full_text": "poora text padha gaya",
    "abstract": "sirf abstract (summary) padha gaya",
    "snippet": "sirf search ka chhota tukda mila",
    "metadata": "sirf title/author mila, text nahi",
}

# Bhasha mirror: user Hindi mein poochhe to Hindi, English mein poochhe to
# English, warna Hinglish. Ye sirf ENGINE ki apni lines hain — source ka text
# jaisa hai waisa hi rehta hai (translate karna = badalna, aur wo jhooth hai).
_W: Dict[str, Tuple[str, str, str]] = {
    # key: (hinglish, hindi, english)
    "engine_note": (
        "Ye jawab AI reasoning model ke bina bana hai — engine ne khud sources ka "
        "padha hua text jod kar likha hai. Koi baat invent nahi ki gayi.",
        "यह जवाब AI reasoning model के बिना बना है — engine ने खुद sources का पढ़ा "
        "हुआ text जोड़कर लिखा है। कोई बात अपने से नहीं जोड़ी गई।",
        "This answer was assembled without the AI reasoning model — the engine "
        "joined up the text it actually read from the sources. Nothing is invented."),
    "no_sources": (
        "Is sawal par ek bhi kaam ka source nahi mila, aur AI reasoning model bhi "
        "nahi chala. Isliye main koi jawab bana kar nahi de raha — jo pata nahi "
        "hai, wo pata nahi hai.",
        "इस सवाल पर एक भी काम का source नहीं मिला, और AI reasoning model भी नहीं "
        "चला। इसलिए मैं कोई जवाब बना कर नहीं दे रहा — जो पता नहीं है, वो पता नहीं है।",
        "No usable source was found for this question, and the AI reasoning model "
        "did not run either. So I am not going to manufacture an answer."),
    "found_lead": (
        "Sources ne khud jo kaha, wo ye hai:",
        "Sources ने खुद जो कहा, वह यह है:",
        "Here is what the sources themselves say:"),
    "infer_lead": (
        "Ye engine ka jodna hai (source ka daawa nahi):",
        "यह engine का जोड़ना है (source का दावा नहीं):",
        "These are the engine's own joins, not claims made by any source:"),
    "mech_none": (
        "In sources ke padhe hue hisse mein \"aisa kyun hota hai\" wali wajah "
        "saaf nahi likhi thi, isliye yahan andaaza nahi likha ja raha [UNKNOWN].",
        "इन sources के पढ़े हुए हिस्से में \"ऐसा क्यों होता है\" वाली वजह साफ़ नहीं "
        "लिखी थी, इसलिए यहाँ अंदाज़ा नहीं लिखा जा रहा [UNKNOWN].",
        "The parts of these sources that were read do not spell out a mechanism, "
        "so no guess is written here [UNKNOWN]."),
    "against_none": (
        "Padhe hue text mein koi saaf ulat baat ya limitation nahi mili. Iska "
        "matlab \"koi ulat baat nahi hai\" NAHI hai — sirf itna ki is search mein "
        "nahi mili [UNKNOWN].",
        "पढ़े हुए text में कोई साफ़ उलट बात या limitation नहीं मिली। इसका मतलब "
        "\"कोई उलट बात नहीं है\" नहीं है — सिर्फ़ इतना कि इस search में नहीं मिली [UNKNOWN].",
        "No clear counter-finding or limitation showed up in the text that was "
        "read. That does not mean none exists [UNKNOWN]."),
    "unknown_lead": (
        "Ye baatein is search ke baad bhi khuli hain:",
        "ये बातें इस search के बाद भी खुली हैं:",
        "These questions are still open after this search:"),
    "unknown_sub": (
        "Is sub-sawal ka jawab retrieve hue text mein nahi mila",
        "इस sub-सवाल का जवाब retrieve हुए text में नहीं मिला",
        "The retrieved text does not answer this sub-question"),
    "conclusion_lead": (
        "Kul milakar:",
        "कुल मिलाकर:",
        "Overall:"),
    "next_lead": (
        "Isse pakka karne ke liye agla kadam:",
        "इसे पक्का करने के लिए अगला कदम:",
        "To make this solid, the next step is:"),
    "reasoning_missing": (
        "AI reasoning model is baar nahi chala (uski free limit khatam thi), "
        "isliye ye jawab engine ke apne deterministic reasoning se bana hai. "
        "Sections poore hain, par \"multi-angle AI reasoning\" ka daawa nahi hai.",
        "AI reasoning model इस बार नहीं चला (उसकी free limit ख़त्म थी), इसलिए यह "
        "जवाब engine के अपने deterministic reasoning से बना है। Sections पूरे हैं, "
        "पर \"multi-angle AI reasoning\" का दावा नहीं है।",
        "The AI reasoning model did not run this time (its free limit was used "
        "up), so this answer comes from the engine's own deterministic reasoning. "
        "Every section is filled, but no multi-angle AI reasoning is claimed."),
}

_LANG_SLOT = {"hinglish": 0, "hindi": 1, "english": 2}


def _t(lang: str, key: str) -> str:
    row = _W.get(key)
    if not row:
        return ""
    return row[_LANG_SLOT.get(lang, 0)]


# ── chhote helper (sab pure aur deterministic) ───────────────────────────────
_SENT_SPLIT = re.compile(r"(?<=[.!?।])\s+")
_WS = re.compile(r"\s+")
_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "kya",
         "kaise", "kyun", "kyu", "hai", "hain", "aur", "par", "mein", "ka",
         "ki", "ke", "se", "ko", "what", "how", "why", "does", "did", "are",
         "was", "were", "can", "will", "about", "which", "there", "their"}
_CAUSE_CUES = ("because", "due to", "leads to", "causes", "caused by", "kyunki",
               "wajah", "mechanism", "results in", "driven by", "explains",
               "इसलिए", "क्योंकि", "vajah", "isliye")
_LIMIT_CUES = ("however", "but ", "limitation", "no significant", "not significant",
               "small sample", "unclear", "conflicting", "contradict", "failed to",
               "did not", "lekin", "magar", "kamzori", "लेकिन", "पर ", "risk of bias",
               "inconsistent", "could not", "no effect", "weak evidence")
_NUM = re.compile(r"\d")


def _clean(text: str, limit: int = 320) -> str:
    out = _WS.sub(" ", (text or "")).strip()
    if len(out) <= limit:
        return out
    cut = out[:limit].rsplit(" ", 1)[0]
    return f"{cut}…"


def _sentences(text: str) -> List[str]:
    body = _WS.sub(" ", (text or "")).strip()
    if not body:
        return []
    return [s.strip() for s in _SENT_SPLIT.split(body) if len(s.strip()) > 25]


def _terms(question: str, limit: int = 8) -> List[str]:
    words = re.findall(r"[A-Za-zऀ-ॿ][\w\-]{2,}", (question or "").lower())
    out: List[str] = []
    for w in words:
        if w in _STOP or w in out:
            continue
        out.append(w)
        if len(out) >= limit:
            break
    return out


def _score_sentence(sent: str, terms: Sequence[str]) -> int:
    low = sent.lower()
    hits = sum(1 for t in terms if t in low)
    if _NUM.search(sent):
        hits += 1
    return hits


def _best_sentence(source: SourceRecord, terms: Sequence[str],
                   cues: Sequence[str] = ()) -> str:
    """
    Source ke apne text se sabse kaam ki line. Deterministic: pehle score,
    barabar hone par jo pehle aayi wahi (index tie-break) — isliye do run ka
    output shabd-ba-shabd same rehta hai.
    """
    best, best_score = "", -1
    for i, sent in enumerate(_sentences(source.snippet)):
        score = _score_sentence(sent, terms)
        if cues:
            low = sent.lower()
            if not any(c in low for c in cues):
                continue
            score += 2
        if score > best_score:
            best, best_score = sent, score
    return _clean(best)


def _label(source: SourceRecord) -> str:
    """
    Source ke apne shabd `[SOURCE-REPORTED]` hain — `[ESTABLISHED]` yahan kabhi
    nahi, kyunki entailment engine ne check nahi kiya. (§13 ka strict rule.)
    """
    level = source.reading_level()
    if level in ("full_text", "abstract"):
        return "[SOURCE-REPORTED]"
    return "[SOURCE-REPORTED] [THIN-READ]"


def _ordered(pack: EvidencePack) -> List[SourceRecord]:
    """Sabse kaam ka pehle. Tie par original kram — yaani hamesha wahi kram."""
    rows = [(-(s.combined_score or s.relevance_score or 0.0), i, s)
            for i, s in enumerate(pack.sources) if not s.rejected_reason]
    rows.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in rows]


def _title_of(source: SourceRecord) -> str:
    return _clean(source.title or source.url or source.source_id, 110)


# ── section 0: Seedha jawab ──────────────────────────────────────────────────
def _direct(question: str, pack: EvidencePack, lang: str) -> str:
    terms = _terms(question)
    lines: List[str] = []
    for source in _ordered(pack)[:2]:
        sent = _best_sentence(source, terms)
        if sent:
            lines.append(f"{sent} [{source.source_id}] {_label(source)}")
    if not lines:
        return _t(lang, "no_sources")
    body = " ".join(lines)
    return f"{body}\n\n{_t(lang, 'engine_note')}"


# ── section 1: Research se kya pata chala? ───────────────────────────────────
def _findings(question: str, pack: EvidencePack, lang: str) -> str:
    terms = _terms(question)
    fact_lines: List[str] = []
    for source in _ordered(pack)[:8]:
        sent = _best_sentence(source, terms)
        if not sent:
            continue
        level = _LEVEL_WORD.get(source.reading_level(), source.reading_level())
        fact_lines.append(
            f"- **[{source.source_id}] {_title_of(source)}:** {sent} "
            f"{_label(source)} _({level})_")
    infer_lines = _inferences(pack, terms, lang)
    if not fact_lines and not infer_lines:
        return _t(lang, "no_sources")

    out = [f"{_t(lang, 'found_lead')}\n",
           "### Fact — jo research se already support hota hai\n"]
    out.append("\n".join(fact_lines) if fact_lines else _t(lang, "no_sources"))
    out.append("\n### Inference — sources ko jodne par jo logical conclusion nikalta hai\n")
    out.append(f"{_t(lang, 'infer_lead')}\n")
    out.append("\n".join(infer_lines) if infer_lines
               else f"- [INFERENCE] {_t(lang, 'against_none')}")
    return "\n".join(out)


def _inferences(pack: EvidencePack, terms: Sequence[str], lang: str) -> List[str]:
    """
    Engine ka apna jodna — sirf wahi jo GINTI se nikalta hai, andaaza nahi.
    Har line `[INFERENCE]` hai, aur jin sources par tiki hai unke id saath hain.
    """
    lines: List[str] = []
    sources = _ordered(pack)
    if not sources:
        return lines
    total = len(sources)

    for term in list(terms)[:3]:
        hits = [s for s in sources if term in (s.snippet or "").lower()
                or term in (s.title or "").lower()]
        if len(hits) >= 2:
            ids = ", ".join(f"[{s.source_id}]" for s in hits[:5])
            lines.append(
                f"- [INFERENCE] \"{term}\" par {len(hits)}/{total} sources ki baat "
                f"ek hi disha mein jaati hai ({ids}) — ye engine ki ginti hai, "
                f"inki aapsi swatantra sehmati ka saboot nahi.")

    kinds = sorted({(s.source_type.value if hasattr(s.source_type, "value")
                     else str(s.source_type)) for s in sources})
    if len(kinds) >= 2:
        lines.append(
            f"- [INFERENCE] Baat ek hi tarah ke source par nahi tiki: {len(kinds)} "
            f"alag kism ke source mile ({', '.join(kinds)}) — isliye ek platform "
            f"ki galti se poora jawab nahi badalta.")

    with_numbers = [s for s in sources if _NUM.search(s.snippet or "")]
    if len(with_numbers) >= 2:
        ids = ", ".join(f"[{s.source_id}]" for s in with_numbers[:4])
        lines.append(
            f"- [INFERENCE] {len(with_numbers)}/{total} sources mein asli aankde "
            f"hain ({ids}) — yaani baat sirf raay nahi, naapi hui cheez hai. "
            f"Aankdon ki aapsi tulna engine ne khud nahi ki.")

    full = pack.full_text_read_count
    if full < total:
        lines.append(
            f"- [INFERENCE] {full}/{total} sources ka poora text mila; baaki par "
            f"baat sirf abstract/snippet tak hai — isliye inhe \"pakka\" nahi, "
            f"\"source ne kaha\" samajhna chahiye.")
    return lines


# ── section 2: Ye kyun hota hai? ─────────────────────────────────────────────
def _mechanism(question: str, pack: EvidencePack, lang: str) -> str:
    terms = _terms(question)
    lines: List[str] = []
    for source in _ordered(pack)[:8]:
        sent = _best_sentence(source, terms, cues=_CAUSE_CUES)
        if sent:
            lines.append(f"- {sent} [{source.source_id}] {_label(source)}")
    if not lines:
        return _t(lang, "mech_none")
    return "\n".join(lines)


# ── section 3: Evidence kya kehta hai? ──────────────────────────────────────
def _evidence(pack: EvidencePack, lang: str) -> str:
    total = len(pack.sources)
    if not total:
        return _t(lang, "no_sources")
    peer = len([s for s in pack.sources if s.peer_reviewed])
    primary = len([s for s in pack.sources if s.is_primary])
    levels = pack.read_level_counts()
    level_bits = ", ".join(
        f"{_LEVEL_WORD.get(k, k)}: {v}/{total}" for k, v in levels.items())
    lines = [
        f"- Kul {total} sources par baat tiki hai; inmein "
        f"{pack.independent_source_count}/{total} aapas mein swatantra hain "
        f"(alag publisher/DOI/domain).",
        f"- Peer-reviewed: {peer}/{total}. Primary (asli study, review nahi): "
        f"{primary}/{total}.",
        f"- Kitna gehra padha gaya — {level_bits or 'koi text nahi mila'}.",
        f"- Poora text mila: {pack.full_text_read_count}/{total} sources ka.",
    ]
    methods = pack.methodology_counts()
    if methods:
        lines.append("- Study ka tarika: " + ", ".join(
            f"{k}: {v}/{total}" for k, v in methods.items()))
    if pack.retracted_sources():
        lines.append(f"- ⚠️ {len(pack.retracted_sources())}/{total} source retracted "
                     f"nishan wala hai — uspar bharosa nahi kiya gaya.")
    lines.append(
        "- Ye ginti engine ki apni hai (deterministic), kisi AI model ki raay "
        "nahi — isliye quota khatam hone par bhi ye hissa poora rehta hai.")
    return "\n".join(lines)


# ── section 4: Iske against kya mila? ───────────────────────────────────────
def _against(question: str, pack: EvidencePack, lang: str,
             contradictions: Optional[List[Dict]] = None) -> str:
    lines: List[str] = []
    for item in (contradictions or [])[:4]:
        claim = _clean(str(item.get("summary") or item.get("topic")
                           or item.get("claim") or ""), 200)
        ids = item.get("source_ids") or item.get("sources") or []
        tail = " ".join(f"[{i}]" for i in ids[:4] if i)
        if claim:
            lines.append(f"- {claim} {tail}".rstrip())

    terms = _terms(question)
    for source in _ordered(pack)[:8]:
        sent = _best_sentence(source, terms, cues=_LIMIT_CUES)
        if sent:
            lines.append(f"- {sent} [{source.source_id}] {_label(source)}")
    thin = [s for s in _ordered(pack) if s.reading_level() in ("snippet", "metadata")]
    if thin:
        ids = ", ".join(f"[{s.source_id}]" for s in thin[:5])
        lines.append(
            f"- [INFERENCE] {len(thin)}/{len(pack.sources)} sources ka poora text "
            f"nahi mila ({ids}) — inke naam par koi pakka daawa karna galat hoga. "
            f"Ye is jawab ki apni kamzori hai.")
    if not lines:
        return _t(lang, "against_none")
    return "\n".join(lines)


# ── section 7: Kya abhi unknown hai? ────────────────────────────────────────
def _unknown(question: str, pack: EvidencePack, plan: Optional[Dict],
             lang: str) -> str:
    lines: List[str] = []
    blob = " ".join((s.snippet or "") + " " + (s.title or "")
                    for s in pack.sources).lower()
    subs = list((plan or {}).get("sub_questions") or [])[:6]
    for sub in subs:
        terms = _terms(str(sub), limit=5)
        if not terms:
            continue
        hits = sum(1 for t in terms if t in blob)
        if hits <= max(1, len(terms) // 3):
            lines.append(f"- {_clean(str(sub), 160)} — {_t(lang, 'unknown_sub')} "
                         f"[UNKNOWN].")
    if pack.full_text_read_count < len(pack.sources):
        lines.append(
            f"- Jin {len(pack.sources) - pack.full_text_read_count} sources ka poora "
            f"text nahi khula, unke andar ka data abhi unknown hai [UNKNOWN].")
    if not lines:
        lines.append(f"- Is search ki hadd tak koi bada khula sawal saaf nahi "
                     f"dikha — par iska matlab \"sab pata hai\" nahi hai [UNKNOWN].")
    return f"{_t(lang, 'unknown_lead')}\n" + "\n".join(lines)


# ── section 8: Final conclusion ─────────────────────────────────────────────
def _conclusion(question: str, pack: EvidencePack, lang: str) -> str:
    total = len(pack.sources)
    if not total:
        return _t(lang, "no_sources")
    top = _ordered(pack)[0]
    sent = _best_sentence(top, _terms(question))
    lines = [f"{_t(lang, 'conclusion_lead')} {sent} [{top.source_id}] "
             f"{_label(top)}" if sent else _t(lang, "conclusion_lead")]
    lines.append("")
    lines.append(f"{_t(lang, 'next_lead')}")
    need = total - pack.full_text_read_count
    if need > 0:
        lines.append(f"- Baaki {need}/{total} sources ka poora text kholna, taaki "
                     f"baat abstract par na tike.")
    lines.append("- Ek independent primary study (review nahi) se cross-check "
                 "karna.")
    lines.append("- Wahi sawal Deep/Max mode mein dobara chalana jab AI reasoning "
                 "model ki free limit reset ho jaaye — tab isi evidence par "
                 "multi-angle reasoning bhi jud jaayega.")
    lines.append("")
    lines.append(_t(lang, "reasoning_missing"))
    return "\n".join(lines)


# ── public ──────────────────────────────────────────────────────────────────
def compose(question: str, pack: EvidencePack, plan: Optional[Dict] = None,
            contradictions: Optional[List[Dict]] = None,
            language: str = "") -> str:
    """
    Poora model-shaped jawab, bina kisi API call ke.

    `synthesizer.assemble()` isi text ko padh kar sections 0,1,2,3,4,7,8 bharta
    hai — isliye heading bilkul canonical hain. Sections 5,6,9,10 engine pehle
    se khud banata hai, yaani quota mar jaane par bhi report ka koi hissa khaali
    nahi rehta.
    """
    lang = language or detect_language(question)
    pack = pack or EvidencePack(question=question)
    blocks = [
        ("Seedha jawab", _direct(question, pack, lang)),
        ("Research se kya pata chala?", _findings(question, pack, lang)),
        ("Ye kyun hota hai?", _mechanism(question, pack, lang)),
        ("Evidence kya kehta hai?", _evidence(pack, lang)),
        ("Iske against kya mila?", _against(question, pack, lang, contradictions)),
        ("Kya abhi unknown hai?", _unknown(question, pack, plan, lang)),
        ("Final conclusion", _conclusion(question, pack, lang)),
    ]
    return "\n\n".join(f"## {title}\n{body}".rstrip() for title, body in blocks)


# ── QUICK mode ka backup (chat.py isse use karta hai) ───────────────────────
_QUICK_LEAD = (
    ("Mera AI model abhi thak gaya tha (free limit khatam), isliye maine ye jawab "
     "seedha free sources se padh kar diya hai:",
     "मेरा AI model अभी थक गया था (free limit ख़त्म), इसलिए मैंने यह जवाब सीधे free "
     "sources से पढ़कर दिया है:",
     "My AI model had hit its free limit, so I read this straight from free "
     "sources instead:"),
    ("Abhi mera AI model thoda saans le raha hai (free limit khatam ho gayi thi) "
     "aur is QUICK run mein koi bharosemand source bhi nahi mila. Main guess karke "
     "jawab nahi de raha. Isi sawal ko Deep/Max mode mein bhejo; background research "
     "source dhoondhte waqt normal page-request timeout par depend nahi karegi.",
     "अभी मेरा AI model थोड़ा साँस ले रहा है (free limit ख़त्म हो गई थी) और इस वक़्त "
     "कोई भरोसेमंद source भी नहीं मिला। मैं अनुमान से उत्तर नहीं दूँगा। इसी सवाल को "
     "Deep/Max mode में भेजें, जहाँ background research चलेगी।",
     "My AI model is catching its breath (free limit reached) and I could not "
     "find a reliable source in this QUICK run. I will not guess. Send the same "
     "question through Deep/Max so background research can gather evidence."),
    # teesra roop — jab key hi set nahi hai (quota ki baat karna jhooth hota)
    ("Abhi mera AI model connect nahi hai (server par uski key set nahi hai), "
     "aur is QUICK run mein koi bharosemand source bhi nahi mila. Main guess nahi "
     "karunga; isi sawal ko Deep/Max background research mein bhejo.",
     "अभी मेरा AI model connect नहीं है (server पर उसकी key सेट नहीं है), और इस वक़्त "
     "कोई भरोसेमंद source भी नहीं मिला। अनुमान लगाने के बजाय इसी सवाल को Deep/Max "
     "background research में भेजें।",
     "My AI model is not connected right now (its key is not set on the server) "
     "and I could not find a reliable source in this QUICK run. Rather than guess, "
     "send the same question through Deep/Max background research."),
)


def _free_search(query: str, limit: int = 3):
    """Sirf keyless, free connectors — koi key, koi paisa nahi."""
    out = []
    try:
        from .connectors.web_connector import (DuckDuckGoConnector,
                                               WikipediaConnector)
    except Exception:                       # noqa: BLE001
        return out
    for cls in (WikipediaConnector, DuckDuckGoConnector):
        try:
            result = cls().safe_search(query, max_results=limit)
        except Exception:                   # noqa: BLE001
            continue
        out.extend(result.get("records") or [])
        if len(out) >= limit:
            break
    return out[:limit]


def quick_answer(message: str, searcher=None, language: str = "",
                 cause: str = "quota") -> Dict:
    """
    QUICK mode ka ₹0 backup: saari free key ka quota khatam ho jaane par bhi
    user ko kaam ka jawab milta hai — free keyless sources se padh kar.

    Kabhi exception nahi phenkta aur kabhi khaali nahi lautata. Jab kuch bhi na
    mile, tab bhi jawab ek insaani, non-technical line hoti hai (user ko "error"
    kabhi nahi dikhna chahiye — intel ka rule).

    `cause="no-key"` do to "free limit khatam" ki jagah sach likha jaata hai
    (key hi set na ho to quota ki baat karna jhooth hota).

    `searcher` inject karne ke liye hai (offline test), aur
    `RV_QUICK_BACKUP_SEARCH=0` se network wala hissa poora band ho jaata hai.
    """
    import os as _os

    text = (message or "").strip()
    lang = language or detect_language(text)
    slot = _LANG_SLOT.get(lang, 0)
    records = []
    if text and (_os.getenv("RV_QUICK_BACKUP_SEARCH", "1") or "1") != "0":
        finder = searcher or _free_search
        try:
            records = list(finder(text) or [])
        except Exception:                   # noqa: BLE001 — backup kabhi na gire
            records = []

    terms = _terms(text)
    lines: List[str] = []
    for rec in records[:3]:
        sent = _clean(_best_sentence(rec, terms) or (rec.snippet or ""), 300)
        if not sent:
            continue
        title = _clean(getattr(rec, "title", "") or getattr(rec, "url", ""), 90)
        url = getattr(rec, "url", "") or ""
        lines.append(f"- **{title}** — {sent}" + (f"\n  {url}" if url else ""))

    if lines:
        body = "\n".join([_QUICK_LEAD[0][slot], ""] + lines)
        return {"answer": body, "mode": "QUICK", "ok": True, "backup": "free-sources",
                "sources": len(lines)}
    lead = _QUICK_LEAD[2] if cause == "no-key" else _QUICK_LEAD[1]
    return {"answer": lead[slot], "mode": "QUICK", "ok": True,
            "backup": "honest-message", "sources": 0}
